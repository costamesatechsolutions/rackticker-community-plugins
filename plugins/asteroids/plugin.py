"""Asteroids: the space rocks passing close to Earth this month, sized like things you know.

A summary of the month's close passes, then a card for each of the nearest: the
Earth with the Moon's orbit and the rock sweeping past at its real distance (in
Moon distances), its name, when it is closest, how fast and how big ("as big as a
bus"). One passing inside the Moon's orbit takes over the display as it comes by.

From NASA JPL's Small-Body Database close-approach data: free, no key.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, ease_in_out,
                         text_width, tiny_width)

API = "https://ssd-api.jpl.nasa.gov/cad.api"
LD = 0.00256955529          # the Moon's mean distance, in AU
ASK_EVERY = 3 * 3600
WHITE, GREY, AMBER, GOLD, RED, CYAN = ((236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60),
                                       (255, 60, 40), (60, 200, 255))
ROCK = (190, 150, 110)
SIZES = ((4, "A CAR"), (12, "A BUS"), (25, "A HOUSE"), (60, "A JUMBO JET"), (200, "A STADIUM"),
         (500, "A SKYSCRAPER"), (2000, "A MOUNTAIN"), (1e9, "A CITY"))
SUMMARY, CARD = 6.0, 7.0


def size_meters(h, diameter_km=None, albedo=.14):
    """Measured size if known, otherwise from its brightness (absolute magnitude H) at a typical albedo."""
    if diameter_km:
        return float(diameter_km) * 1000
    return 1329 / math.sqrt(albedo) * 10 ** (-float(h) / 5) * 1000


def like(meters):
    for limit, name in SIZES:
        if meters <= limit:
            return name
    return SIZES[-1][1]


def short_name(full):
    """"  99942 Apophis (2004 MN4)" -> "Apophis"; "  (2026 TG9)" -> "2026 TG9"."""
    full = str(full).strip()
    named = re.match(r"^\d+\s+([^(]+?)\s*\(", full)
    if named:
        return named.group(1)
    if full.startswith("(") and full.endswith(")"):
        return full[1:-1]
    return full


def parse(payload):
    fields = payload.get("fields") or []
    rows = []
    for values in payload.get("data") or []:
        row = dict(zip(fields, values))
        try:
            when = datetime.strptime(row["cd"], "%Y-%b-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
            meters = size_meters(row["h"], row.get("diameter"))
            rows.append({"name": short_name(row.get("fullname") or row["des"]), "at": when,
                         "ld": float(row["dist"]) / LD, "speed": float(row["v_rel"]), "meters": meters})
        except (KeyError, TypeError, ValueError):
            continue
    return rows


class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.rows, self.asked, self.alerted = [], -1e9, set()

    async def fetch(self):
        settings = self.context.settings
        if time.monotonic() - self.asked >= ASK_EVERY:
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),
                                                     headers={"User-Agent": "RackTicker asteroids plugin"})
            params = {"date-min": "now", "date-max": "+30", "dist-max": f"{settings['within_moon_distances']}LD",
                      "sort": "date", "diameter": "true", "fullname": "true"}
            try:
                async with self.session.get(API, params=params) as response:
                    response.raise_for_status()
                    self.rows = parse(await response.json(content_type=None))
                self.asked = time.monotonic()
            except (aiohttp.ClientError, TimeoutError, ValueError):
                self.asked = time.monotonic() - ASK_EVERY + 600
                if not self.rows:
                    raise
        now = time.time()
        for row in self.rows:
            if (settings["alert"] and row["ld"] < 1 and abs(row["at"] - now) < 1800
                    and row["name"] not in self.alerted):
                self.alerted.add(row["name"])
                self.context.emit_event("asteroids", 30)
        return Snapshot([row for row in self.rows if row["at"] > now - 3600])

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


def when_text(ts, now):
    local = datetime.fromtimestamp(ts, now.tzinfo)
    days = (local.date() - now.date()).days
    day = "TODAY" if days == 0 else "TOMORROW" if days == 1 else local.strftime("%a %b %-d").upper()
    return f"{day} {local.strftime('%I:%M').lstrip('0')}{'AM' if local.hour < 12 else 'PM'}"


def put(frame, x, y, color):
    x, y = round(x), round(y)
    if 0 <= x < 128 and 0 <= y < 32:
        frame.putpixel((x, y), color)


def radius(ld):
    """Moon distances to pixels: the Moon's orbit at 9, ten Moon distances at the panel's edge."""
    return 9 * math.sqrt(max(ld, .02))


class Asteroids(Module):
    name = "asteroids"
    event_priority = 20

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _rows(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data else []

    def available(self, context):
        return bool(self._rows(context))

    def hold(self, context):
        return self.story.hold()

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        rows = self._rows(context)
        if not rows:
            draw_text(frame, "No close passes", 2, 12, GREY, mixed=True)
            return frame
        settings = context.config["plugins"][self.name]
        closest = sorted(rows, key=lambda row: row["ld"])[:settings["cards"]]
        shown = sorted(closest, key=lambda row: row["at"])

        def build(visit):
            return [("summary", SUMMARY)] + [(row["name"], CARD) for row in shown]

        self.story.sync(context.animation_time, build, context.scene)
        current = self.story.current(context.animation_time, build)
        key, local = (current[0], current[1]) if current else ("summary", 0)
        if key == "summary":
            self._summary(frame, rows, settings, context, local)
        else:
            row = next((row for row in shown if row["name"] == key), shown[0])
            self._pass(frame, row, context, local)
        return frame

    @staticmethod
    def _summary(frame, rows, settings, context, local):
        count = str(len(rows))
        draw_text(frame, count, 0, 4, AMBER, scale=2, smooth=True)
        x = text_width(count, 2) + 5
        draw_tiny(frame, "ASTEROIDS PASS CLOSER", x, 4, WHITE)
        moons = settings["within_moon_distances"]
        draw_tiny(frame, f"THAN {moons:g} MOONS IN 30 DAYS", x, 11, WHITE)
        nearest = min(rows, key=lambda row: row["ld"])
        line = f"NEAREST {nearest['ld']:.2f}× MOON  {when_text(nearest['at'], context.now)}"
        while tiny_width(line) > 128 and " " in line:
            line = line.rsplit(" ", 1)[0]
        draw_tiny(frame, line, 0, 26, GOLD if nearest["ld"] < 1 else GREY)

    @staticmethod
    def _pass(frame, row, context, local):
        draw = ImageDraw.Draw(frame)
        ex, ey = 3, 16
        moon = radius(1)
        for step in range(0, 360, 8):              # the Moon's orbit, dotted
            angle = math.radians(step)
            put(frame, ex + moon * math.cos(angle), ey + moon * math.sin(angle), (60, 64, 80))
        moon_angle = local * .3 - .8
        put(frame, ex + moon * math.cos(moon_angle), ey + moon * math.sin(moon_angle), (200, 200, 190))
        draw.ellipse((ex - 3, ey - 3, ex + 3, ey + 3), fill=(30, 100, 220))
        draw.point((ex - 1, ey - 1), fill=(60, 180, 90))
        # The rock comes down past the Earth on a straight line at its closest distance.
        miss = min(radius(row["ld"]), 36)
        progress = ease_in_out(min(1.0, local / (CARD - 1.5)))
        rock_y = -4 + progress * 40
        rock_x = ex + miss
        for back in range(1, 8):
            ty = rock_y - back * 1.6
            level = 1 - back / 8
            put(frame, rock_x, ty, tuple(round(c * level * .6) for c in ROCK))
        if -2 < rock_y < 33:
            draw.ellipse((rock_x - 1, rock_y - 1, rock_x + 1, rock_y + 1), fill=ROCK)
        x = 44
        draw_tiny(frame, when_text(row["at"], context.now), x, 1, GREY)
        draw_text(frame, row["name"], x, 8, WHITE)
        inside = row["ld"] < 1
        distance = f"{row['ld']:.2f}× MOON DISTANCE" if row["ld"] < 10 else f"{row['ld']:.0f}× MOON"
        draw_tiny(frame, distance, x, 18, RED if inside else AMBER)
        meters = row["meters"]
        across = f"ABOUT {round(meters)} M ACROSS" if meters < 1000 else f"ABOUT {meters / 1000:.1f} KM ACROSS"
        lines = (f"AS BIG AS {like(meters)}", across, f"{row['speed']:.0f} KM/S, {row['speed'] * 2237:,.0f} MPH")
        line = lines[int(local / 2.3) % 3]
        while tiny_width(line) > 128 - x and "," in line:
            line = line.rsplit(",", 1)[0]
        draw_tiny(frame, line, x, 25, GREY)


def validate_settings(settings):
    if not 1 <= float(settings.get("within_moon_distances", 10)) <= 50:
        raise ValueError("within_moon_distances must be 1 to 50")
    if not 1 <= int(settings.get("cards", 4)) <= 10:
        raise ValueError("cards must be 1 to 10")
    return settings


plugin = Plugin(
    "asteroids", "Asteroids", module=Asteroids, provider=Feed,
    defaults={"within_moon_distances": 10, "cards": 4, "alert": True},
    validate_settings=validate_settings,
    help={"within_moon_distances": "Count passes closer than this many times the Moon's distance",
          "cards": "How many of the nearest passes get their own card",
          "alert": "Take over when one passes inside the Moon's orbit"},
    ui={"within_moon_distances": {"type": "slider", "min": 1, "max": 50, "step": 1, "label": "Closer than (Moons)"},
        "cards": {"type": "slider", "min": 1, "max": 10, "step": 1, "label": "Nearest passes shown"},
        "alert": {"label": "Take over inside the Moon's orbit"}},
)
