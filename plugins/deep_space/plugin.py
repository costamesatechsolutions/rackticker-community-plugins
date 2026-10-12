"""Deep space: how far away our farthest spacecraft are, counting up as you watch.

A card for each: Voyager 1 and 2, the first things we made to leave the Sun's
bubble, New Horizons past Pluto, and Parker Solar Probe diving at the Sun. The
distance rolls like an odometer at the real rate, with how long their radio
signal takes to reach us. Voyager 1 also counts down to being one light-day from
Earth, in November 2026, and after that how long it has been.

Distances from NASA JPL's Horizons system, asked once every six hours per craft.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import math
import random
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, offload, sprite, stamp,
                         text_width, tiny_width)

HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
AU = 149597870.700
LIGHT = 299792.458
LIGHT_DAY_AU = 86400 * LIGHT / AU
CRAFT = (  # (Horizons id, name, launched, measure from: Earth or Sun)
    ("-31", "VOYAGER 1", 1977, "earth"),
    ("-32", "VOYAGER 2", 1977, "earth"),
    ("-98", "NEW HORIZONS", 2006, "earth"),
    ("-96", "PARKER SOLAR PROBE", 2018, "sun"),
)
ASK_EVERY = 6 * 3600
AHEAD_DAYS = {"-31": 400}      # far enough to find when Voyager 1 reaches a light-day
WHITE, GREY, AMBER, GOLD, CYAN = (236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60), (60, 200, 255)
CARD = 8.0
PROBE = ("....g.....", "...ggg....", "..gwwwg...", ".gwwwwwg..", "..gwwwg...", "...ggg....", "....s.....",
         "...sss....", "....s.....", "....s.....")


def parse(result):
    """Rows of (unix time, r AU, rdot km/s, delta AU, deldot km/s) from a Horizons CSV table."""
    if "$$SOE" not in result:
        raise ValueError("Horizons sent no table")
    body = result.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    rows = []
    for line in body.strip().splitlines():
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) < 7:
            continue
        at = datetime.strptime(cells[0], "%Y-%b-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
        rows.append((at, float(cells[3]), float(cells[4]), float(cells[5]), float(cells[6])))
    if not rows:
        raise ValueError("Horizons table was empty")
    return rows


class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.data, self.asked = {}, {}

    async def fetch(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),
                                                 headers={"User-Agent": "RackTicker deep space plugin"})
        # One spacecraft per round, so a round never comes close to the provider's time limit.
        due = [craft for craft in CRAFT if time.monotonic() - self.asked.get(craft[0], -1e9) >= ASK_EVERY]
        if due:
            ident = due[0][0]
            start = datetime.now(timezone.utc).date() - timedelta(days=1)
            stop = start + timedelta(days=AHEAD_DAYS.get(ident, 3))
            params = {"format": "json", "COMMAND": f"'{ident}'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
                      "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'500@399'", "START_TIME": f"'{start}'",
                      "STOP_TIME": f"'{stop}'", "STEP_SIZE": "'1d'", "QUANTITIES": "'19,20'", "CSV_FORMAT": "'YES'"}
            try:
                async with self.session.get(HORIZONS, params=params) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
                self.data[ident] = await offload(parse, payload.get("result", ""))
                self.asked[ident] = time.monotonic()
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError):
                self.asked[ident] = time.monotonic() - ASK_EVERY + 300
                if not self.data:
                    raise
        return Snapshot(dict(self.data))

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# --- the screen ------------------------------------------------------------------------------

def distance_km(rows, ts, measure):
    """Distance now (km), carried forward from the nearest day's value at that day's rate."""
    row = min(rows, key=lambda r: abs(r[0] - ts) if r[0] <= ts else 1e12)
    if row[0] > ts:
        row = rows[0]
    at, r, rdot, delta, deldot = row
    if measure == "sun":
        return r * AU + rdot * (ts - at)
    return delta * AU + deldot * (ts - at)


def light_day(rows, ts):
    """When Voyager 1 first is (or was) one light-day from Earth, or None if not within the table."""
    previous = None
    for at, r, rdot, delta, deldot in rows:
        if delta >= LIGHT_DAY_AU:
            if previous is None:
                return None
            p_at, p_delta = previous
            return p_at + (LIGHT_DAY_AU - p_delta) / (delta - p_delta) * (at - p_at)
        previous = (at, delta)
    return None


def light_time(km):
    seconds = km / LIGHT
    hours, minutes = int(seconds // 3600), int(seconds % 3600 // 60)
    if hours:
        return f"{hours}H {minutes:02d}M"
    return f"{minutes}M {int(seconds % 60):02d}S"


@lru_cache(maxsize=20)
def rolling(digit, color):
    """A digit with the next one under it, for the last wheel of the odometer to roll through."""
    strip = Image.new("RGB", (5, 15))
    draw_text(strip, digit, 0, 0, color)
    draw_text(strip, str((int(digit) + 1) % 10), 0, 8, color)
    return strip


def odometer(frame, value, x, y, color, t, unit):
    """Digits that roll: the last few spin as the distance grows, like a car's mileage."""
    text = f"{int(value):,}"
    fraction = value - int(value)
    cx = x
    digits_left = sum(ch.isdigit() for ch in text)
    for ch in text:
        if ch.isdigit():
            digits_left -= 1
            if digits_left == 0 and fraction > .5:
                frame.paste(rolling(ch, color).crop((0, round((fraction - .5) * 2 * 8), 5,
                                                     round((fraction - .5) * 2 * 8) + 7)), (cx, y))
            else:
                draw_text(frame, ch, cx, y, color)
            cx += 6
        else:
            draw_text(frame, ch, cx, y, color)
            cx += text_width(ch) + 1
    draw_tiny(frame, unit, cx + 2, y + 2, color)


class DeepSpace(Module):
    name = "deep_space"

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _data(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data else {}

    def available(self, context):
        return bool(self._data(context))

    def hold(self, context):
        return self.story.hold()

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        data = self._data(context)
        if not data:
            draw_text(frame, "Asking JPL", 4, 12, GREY, mixed=True)
            return frame
        settings = context.config["plugins"][self.name]
        ts = context.now.timestamp()
        cards = []
        for ident, name, launched, measure in CRAFT:
            if ident in data:
                cards.append((ident, CARD))
                if ident == "-31" and (light_day(data[ident], ts) or data[ident][0][3] >= LIGHT_DAY_AU):
                    cards.append(("milestone", CARD))

        def build(visit):
            return cards

        self.story.sync(context.animation_time, build, context.scene)
        current = self.story.current(context.animation_time, build)
        key, local = (current[0], current[1]) if current else (cards[0][0], 0)
        self._stars(frame, context.animation_time)
        if key == "milestone":
            self._milestone(frame, data["-31"], ts, local)
        else:
            craft = next(craft for craft in CRAFT if craft[0] == key)
            self._craft(frame, craft, data[key], settings, ts, local)
        return frame

    @staticmethod
    def _stars(frame, t):
        pixels = frame.load()
        rng = random.Random(3)
        for _ in range(14):
            x = (rng.uniform(0, 20) - t * rng.uniform(.3, .9)) % 20
            y = rng.randint(0, 31)
            level = rng.randint(50, 140)
            pixels[int(x), y] = (level, level, level + 10)

    @staticmethod
    def _craft(frame, craft, rows, settings, ts, local):
        ident, name, launched, measure = craft
        stamp(frame, sprite(PROBE, {"g": (200, 170, 90), "w": (230, 230, 225), "s": (150, 150, 150)}), 5, 10)
        km = distance_km(rows, ts, measure)
        x = 22
        draw_tiny(frame, name, x, 1, CYAN)
        since = f"SINCE {launched}"
        if tiny_width(name) + tiny_width(since) + 6 <= 128 - x:
            draw_tiny(frame, since, 128 - tiny_width(since), 1, GREY)
        imperial = settings["units"] == "imperial"
        value, unit = (km * .621371, "MI") if imperial else (km, "KM")
        odometer(frame, value, x, 10, WHITE, local, unit)
        if measure == "sun":
            draw_tiny(frame, "FROM THE SUN", x, 20, GREY)
            draw_tiny(frame, f"{km / AU:.2f} OF EARTH'S DISTANCE", x, 26, AMBER)
        else:
            draw_tiny(frame, "FROM EARTH  RADIO TAKES", x, 20, GREY)
            draw_tiny(frame, light_time(km), x, 26, AMBER)
            row = min(rows, key=lambda r: abs(r[0] - ts))
            speed = abs(row[4]) * (.621371 if imperial else 1)
            label = f"{'+' if row[4] >= 0 else '-'}{speed:.1f} {unit}/S"
            draw_tiny(frame, label, 128 - tiny_width(label), 26, GREY)

    @staticmethod
    def _milestone(frame, rows, ts, local):
        when = light_day(rows, ts) or rows[0][0]
        stamp(frame, sprite(PROBE, {"g": (200, 170, 90), "w": (230, 230, 225), "s": (150, 150, 150)}), 5, 10)
        x = 22
        draw_tiny(frame, "VOYAGER 1", x, 1, CYAN)
        draw_text(frame, "1 light-day", x, 8, GOLD, mixed=True)
        draw_tiny(frame, "FROM EARTH", x, 19, GREY)
        days = (when - ts) / 86400
        if days > 1:
            text = f"IN {math.ceil(days)} DAYS"
        elif days > 0:
            text = f"IN {math.ceil(days * 24)} HOURS"
        else:
            text = "AND STILL GOING"
        draw_tiny(frame, text, x, 26, AMBER)
        fraction = min(1.0, max(0.0, distance_km(rows, ts, "earth") / AU / LIGHT_DAY_AU))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((86, 21, 126, 25), outline=(80, 80, 90))
        draw.rectangle((87, 22, 87 + round(38 * fraction), 24), fill=GOLD)
        percent = f"{fraction * 100:.2f}%"
        draw_tiny(frame, percent, 127 - tiny_width(percent), 27, GOLD)


def validate_settings(settings):
    if settings.get("units") not in ("imperial", "metric"):
        raise ValueError("units must be imperial or metric")
    return settings


plugin = Plugin(
    "deep_space", "Deep space", module=DeepSpace, provider=Feed,
    defaults={"units": "imperial"}, choices={"units": ("imperial", "metric")},
    validate_settings=validate_settings,
    help={"units": "Miles or kilometres"},
)
