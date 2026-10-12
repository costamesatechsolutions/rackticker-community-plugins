"""Launches: the next rockets to go, with a countdown, and a take-over for the ones you can see.

Each card is one launch: the rocket on its pad, the mission, a countdown and its
status, and where it goes from, how far away and which way to look. A launch
close enough to see (Vandenberg, from most of California) comes first, flagged
when it is at twilight, when the plume lit by the Sun above a dark sky makes the
"jellyfish". Ten minutes before one of those, the screen takes over with the
count, the liftoff and where to look.

From The Space Devs' free Launch Library 2.
"""
from __future__ import annotations

from datetime import datetime
import math
import random
import re
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, sprite, stamp,
                         text_width, tiny_width)

API = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/"
# Anonymous use is 15 requests an hour; launches move by minutes, not seconds.
ASK_EVERY, ASK_EVERY_NEAR = 900, 360
WHITE, GREY, AMBER, GOLD, RED, GREEN = ((236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60),
                                        (255, 60, 40), (90, 230, 120))
CYAN = (60, 200, 255)
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
CARD = 7.0
NAME_REST, NAME_SPEED = 1.4, 18
ROCKET = ("..w..", ".www.", ".www.", ".www.", ".wbw.", ".www.", ".www.", ".www.", ".www.", ".wbw.",
          ".www.", ".www.", ".www.", ".www.", "wwwww", "w.w.w")
TIMED = ("Second", "Minute")


# --- the data --------------------------------------------------------------------------------

def miles(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def bearing(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return math.degrees(math.atan2(y, x)) % 360


def sun_elevation(lat, lon, ts):
    """The Sun's height above the horizon (degrees) at a place and time, to about a tenth of a degree."""
    n = ts / 86400 + 2440587.5 - 2451545.0
    g = math.radians(357.528 + .9856003 * n)
    lam = math.radians(280.460 + .9856474 * n + 1.915 * math.sin(g) + .020 * math.sin(2 * g))
    eps = math.radians(23.439 - 4e-7 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    hour = math.radians((280.46061837 + 360.98564736629 * n + lon) % 360) - ra
    lat = math.radians(lat)
    return math.degrees(math.asin(math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(hour)))


def short_rocket(name):
    name = re.sub(r"\s+Block\s+\S+$", "", str(name or "")).strip()
    return {"Long March": "Long March"}.get(name, name)


def short_site(name):
    first = str(name or "").split(",")[0]
    return re.sub(r"\s+(SFB|SFS|AFS|AFB|Space Force Base|Space Force Station)$", "", first).strip() or "Unknown"


def parse(payload, home):
    launches = []
    for row in payload.get("results") or []:
        try:
            net = datetime.fromisoformat(row["net"].replace("Z", "+00:00")).timestamp()
            pad = row.get("pad") or {}
            where = (float(pad["latitude"]), float(pad["longitude"]))
        except (KeyError, TypeError, ValueError):
            continue
        name = str(row.get("name") or "")
        rocket, _, mission = name.partition(" | ")
        config = ((row.get("rocket") or {}).get("configuration") or {}).get("name")
        precision = (row.get("net_precision") or {}).get("name") or "Second"
        status = (row.get("status") or {}).get("abbrev") or "TBD"
        launch = {"id": str(row.get("id") or name), "mission": (mission or (row.get("mission") or {}).get("name")
                                                               or name).strip(),
                  "rocket": short_rocket(config or rocket), "net": net, "precision": precision, "status": status,
                  "site": short_site((pad.get("location") or {}).get("name") or pad.get("name")),
                  "provider": str(((row.get("launch_service_provider") or {}).get("name")) or "")}
        if home != (0, 0):
            launch["miles"] = round(miles(home, where))
            launch["look"] = COMPASS[round(bearing(home, where) / 22.5) % 16]
            sun = sun_elevation(*where, net)
            launch["twilight"] = precision in TIMED and -18 < sun < -4
            launch["dark"] = sun < -4
        launches.append(launch)
    return launches


class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.launches, self.asked, self.key = [], -1e9, None
        self.alerted = set()

    async def fetch(self):
        settings = self.context.settings
        home = (settings["latitude"], settings["longitude"])
        now = time.time()
        near = any(launch.get("miles", 1e9) <= settings["visible_miles"] and 0 < launch["net"] - now < 5400
                   for launch in self.launches)
        if (home, settings["visible_miles"]) != self.key or time.monotonic() - self.asked >= (
                ASK_EVERY_NEAR if near else ASK_EVERY):
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),
                                                     headers={"User-Agent": "RackTicker launches plugin"})
            try:
                async with self.session.get(API, params={"limit": 20, "mode": "normal",
                                                         "hide_recent_previous": "true"}) as response:
                    if response.status == 429:   # over the hourly allowance: keep what we have
                        self.asked = time.monotonic()
                        return Snapshot(self._shown(now))
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
                self.launches = parse(payload, home)
                self.asked, self.key = time.monotonic(), (home, settings["visible_miles"])
            except (aiohttp.ClientError, TimeoutError, ValueError):
                self.asked = time.monotonic() - ASK_EVERY + 120
                if not self.launches:
                    raise
        lead = settings["alert_lead_minutes"] * 60
        for launch in self.launches:
            if (settings["alert"] and launch.get("miles", 1e9) <= settings["visible_miles"]
                    and launch["precision"] in TIMED and launch["status"] in ("Go", "TBC")
                    and launch["net"] - lead <= now < launch["net"] + 240 and launch["id"] not in self.alerted):
                self.alerted.add(launch["id"])
                self.context.emit_event("launches", min(900, launch["net"] + 240 - now))
        return Snapshot(self._shown(now))

    def _shown(self, now):
        return [launch for launch in self.launches if launch["net"] > now - 600]

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# --- the screen ------------------------------------------------------------------------------

def _glide(local, distance):
    if distance <= 0:
        return 0
    glide = distance / NAME_SPEED
    phase = local % (2 * (NAME_REST + glide))
    if phase < NAME_REST:
        return 0
    if phase < NAME_REST + glide:
        return round((phase - NAME_REST) * NAME_SPEED)
    if phase < 2 * NAME_REST + glide:
        return distance
    return round(distance - (phase - 2 * NAME_REST - glide) * NAME_SPEED)


def fitted(frame, text, x, y, room, color, local):
    if text_width(text, 1, True) <= room:
        draw_text(frame, text, x, y, color, mixed=True)
        return
    full = text_width(text, 1, True)
    stops = [text_width(text[:i], 1, True) + 1 for i in range(1, len(text))]
    distance = min([s for s in stops if full - s <= room] or [full - room])
    resting = text
    while resting and text_width(resting, 1, True) > room:
        resting = resting[:-1]
    shift = _glide(local, distance)
    cell = Image.new("RGB", (room, 9))
    draw_text(cell, resting.rstrip() if shift == 0 else text, -shift, 0, color, mixed=True)
    frame.paste(cell, (x, y))


def countdown(seconds, precision, net, now):
    if precision not in TIMED and precision != "Hour":
        local = datetime.fromtimestamp(net, now.tzinfo)
        return ("NET " + local.strftime("%b").upper() + (f" {local.day}" if precision == "Day" else "")
                if precision in ("Day", "Month") else "NET " + local.strftime("%b").upper())
    if seconds < 0:
        seconds = -seconds
        return f"T+{int(seconds // 60):02d}:{int(seconds % 60):02d}"
    if seconds >= 48 * 3600:
        return f"IN {round(seconds / 86400)} DAYS"
    hours, rest = divmod(int(seconds), 3600)
    return f"T-{hours:02d}:{rest // 60:02d}:{rest % 60:02d}"


def when_text(net, precision, now):
    local = datetime.fromtimestamp(net, now.tzinfo)
    hour = local.strftime("%I").lstrip("0") + ("" if precision == "Hour" else local.strftime(":%M")) + \
        ("AM" if local.hour < 12 else "PM")
    days = (local.date() - now.date()).days
    day = "TODAY" if days == 0 else "TOMORROW" if days == 1 else local.strftime("%a").upper()
    return f"{day} {hour}"


STATUS_COLORS = {"Go": GREEN, "TBC": AMBER, "TBD": GREY, "Hold": RED, "In Flight": CYAN, "Success": GREEN}


def rocket(frame, x, y, t, venting):
    stamp(frame, sprite(ROCKET, {"w": (220, 222, 216), "b": (40, 90, 200)}), x, y)
    if venting:
        rng = random.Random(int(t * 8))
        pixels = frame.load()
        for _ in range(3):
            px, py = x + rng.choice((-1, 5, 6, -2)), y + rng.randint(2, 12)
            if 0 <= px < 128 and 0 <= py < 32:
                pixels[px, py] = (150, 160, 170)


def plume(frame, x, base, length, t):
    """Fire and smoke under a climbing rocket, from its own time so every frame is reproducible."""
    pixels = frame.load()
    rng = random.Random(int(t * 30))
    for row in range(int(length)):
        y = base + row
        if not 0 <= y < 32:
            continue
        spread = 1 + row // 3
        for _ in range(2 + row // 2):
            px = x + 2 + rng.randint(-spread, spread)
            if 0 <= px < 128:
                heat = row / max(1, length)
                pixels[px, y] = ((255, 230, 120) if heat < .2 else (255, 140, 30) if heat < .45 else
                                 (150, 150, 150) if heat < .8 else (80, 80, 84))


def trail(frame, climb, twilight, t):
    pixels = frame.load()
    reach = min(1.0, (climb - 3) / 150)
    steps = max(2, int(reach * 60))
    head = None
    for index in range(steps):
        s = index / 60
        x, y = 3 + s * 17, 30 - 29 * math.sqrt(s)
        age = (reach - s) / max(reach, 1e-6)
        if twilight and s > .25:
            color = (255, round(214 - 90 * age), round(60 + 120 * age))
            color = tuple(round(c * (1 - .6 * age)) for c in color)
        else:
            color = tuple(round(c * (1 - .65 * age)) for c in (200, 200, 196))
        if 0 <= round(x) < 21 and 0 <= round(y) < 32:
            pixels[round(x), round(y)] = color
            head = (round(x), round(y))
    if head and int(t * 10) % 2 == 0:
        pixels[head] = (255, 255, 255)


class Launches(Module):
    name = "launches"
    event_priority = 30

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _launches(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data else []

    def available(self, context):
        return bool(self._launches(context))

    def hold(self, context):
        return self.story.hold()

    def _order(self, launches, settings, ts):
        """Launches you could see in the next week come first, then the rest by time."""
        visible = settings["visible_miles"]
        mine = [launch for launch in launches if launch.get("miles", 1e9) <= visible and launch["net"] - ts < 7 * 86400]
        rest = [launch for launch in launches if launch not in mine]
        return (mine + rest)[:max(1, settings["count"])]

    def _live(self, launches, settings, ts):
        lead = settings["alert_lead_minutes"] * 60
        for launch in launches:
            if (settings["alert"] and launch.get("miles", 1e9) <= settings["visible_miles"]
                    and launch["precision"] in TIMED and launch["status"] in ("Go", "TBC", "In Flight", "Success")
                    and launch["net"] - lead <= ts < launch["net"] + 240):
                return launch
        return None

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        launches = self._launches(context)
        settings = context.config["plugins"][self.name]
        ts = context.now.timestamp()
        if not launches:
            draw_text(frame, "No launches", 4, 12, GREY, mixed=True)
            return frame
        live = self._live(launches, settings, ts)
        if live:
            self._countdown(frame, live, ts, context.animation_time)
            return frame
        shown = self._order(launches, settings, ts)

        def build(visit):
            return [(launch["id"], CARD) for launch in shown]

        self.story.sync(context.animation_time, build, context.scene)
        current = self.story.current(context.animation_time, build)
        key, local = (current[0], current[1]) if current else (shown[0]["id"], 0)
        launch = next((launch for launch in shown if launch["id"] == key), shown[0])
        self._card(frame, launch, settings, context, ts, local)
        return frame

    def _card(self, frame, launch, settings, context, ts, local):
        draw = ImageDraw.Draw(frame)
        seconds = launch["net"] - ts
        draw.line((1, 6, 1, 30), fill=(120, 60, 30))     # the tower
        for y in range(8, 30, 4):
            draw.line((1, y, 3, y - 2), fill=(120, 60, 30))
        draw.line((0, 31, 12, 31), fill=(90, 90, 90))
        rocket(frame, 5, 15, context.animation_time, launch["precision"] in TIMED and 0 < seconds < 3 * 3600)
        x = 16
        head = launch["rocket"].upper()
        draw_tiny(frame, head, x, 1, GREY)
        status = launch["status"].upper()
        draw_tiny(frame, status, 128 - tiny_width(status), 1, STATUS_COLORS.get(launch["status"], GREY))
        fitted(frame, launch["mission"], x, 8, 128 - x, WHITE, local)
        count = countdown(seconds, launch["precision"], launch["net"], context.now)
        draw_text(frame, count, x, 18, AMBER)
        mine = launch.get("miles", 1e9) <= settings["visible_miles"]
        timed = launch["precision"] in TIMED + ("Hour",) and seconds > 0
        lines = []
        if mine:
            lines.append((f"{launch['site'].upper()} {launch['miles']} MI {launch['look']}", CYAN))
            if timed:
                lines.append((when_text(launch["net"], launch["precision"], context.now), WHITE))
            if launch.get("twilight"):
                lines.append(("TWILIGHT: LOOK " + launch["look"], GOLD))
        elif timed:
            lines.append((f"{when_text(launch['net'], launch['precision'], context.now)}  {launch['site'].upper()}",
                          GREY))
        else:
            lines.append((launch["site"].upper(), GREY))
        bottom, color = lines[int(local / 2.4) % len(lines)]
        while tiny_width(bottom) > 128 - x and " " in bottom:
            bottom = bottom.rsplit(" ", 1)[0]
        draw_tiny(frame, bottom, x, 27, color)

    def _countdown(self, frame, launch, ts, t):
        """The take-over: the count, liftoff and the climb, with where to look."""
        seconds = launch["net"] - ts
        draw = ImageDraw.Draw(frame)
        right = 22
        if seconds > 0:
            draw.line((2, 6, 2, 30), fill=(120, 60, 30))
            draw.line((0, 31, 20, 31), fill=(90, 90, 90))
            rocket(frame, 8, 15, t, True)
            draw_tiny(frame, launch["rocket"].upper(), right, 1, GREY)
            if seconds <= 10:
                digit = str(math.ceil(seconds))
                draw_text(frame, digit, right + 30, 4, GOLD, scale=3, smooth=True)
            else:
                text = f"T-{int(seconds // 60):02d}:{int(seconds % 60):02d}"
                draw_text(frame, text, right, 9, WHITE, scale=2, smooth=True)
            look = f"LOOK {launch.get('look', '')}" + (" AT DUSK" if launch.get("twilight") else "")
            draw_tiny(frame, look, right, 27, GOLD if launch.get("twilight") else AMBER)
            return
        climb = -seconds
        height = min(40, climb ** 1.6 * 1.2)
        y = 15 - height
        if climb > 3:   # far off now: the trail arcs away downrange, gold where the Sun still lights it
            trail(frame, climb, launch.get("twilight"), t)
        if y > -16:
            rocket(frame, 8, y, t, False)
            plume(frame, 8, round(y) + 16, min(18, 4 + climb * 2), t)
        if climb < 2:   # the pad lights up
            draw.rectangle((0, 28, 20, 31), fill=(255, 150, 40))
        if int(t * 3) % 3 or climb > 6:
            draw_text(frame, "LIFTOFF", right, 3, GOLD, scale=2, smooth=True)
        draw_text(frame, f"T+{int(climb // 60):02d}:{int(climb % 60):02d}", right, 19, WHITE)
        draw_tiny(frame, f"LOOK {launch.get('look', '')}, LOW", right + 48, 21, AMBER)


def validate_settings(settings):
    if not 1 <= int(settings.get("count", 4)) <= 10:
        raise ValueError("count must be 1 to 10")
    if not 0 <= float(settings.get("alert_lead_minutes", 10)) <= 15:
        raise ValueError("alert_lead_minutes must be 0 to 15")
    return settings


plugin = Plugin(
    "launches", "Launches", module=Launches, provider=Feed,
    defaults={"latitude": 0.0, "longitude": 0.0, "count": 4, "visible_miles": 400, "alert": True,
              "alert_lead_minutes": 10},
    validate_settings=validate_settings,
    help={"latitude": "Leave at 0 to use the home location from Settings",
          "visible_miles": "Launch sites this close are 'yours': shown first, with where to look",
          "alert": "Take over the display for a launch from a site within that distance"},
    ui={"latitude": {"type": "location", "label": "Location"}, "longitude": {"advanced": True},
        "count": {"type": "slider", "min": 1, "max": 10, "step": 1, "label": "Launches to show"},
        "visible_miles": {"type": "slider", "min": 50, "max": 1000, "step": 50, "unit": "mi",
                          "label": "You can see launches within"},
        "alert": {"label": "Take over for a launch you can see"},
        "alert_lead_minutes": {"type": "slider", "min": 0, "max": 15, "step": 1, "unit": "min",
                               "label": "Start the countdown"}},
)
