"""Three bodies: the Sun, the Earth and the Moon as they are right now.

The Sun is NOAA's newest picture from the GOES-19 solar imager (minutes old), the
Earth is the newest full-disc picture from a GOES weather satellite 22,236 miles
up (ten minutes old, with the real clouds and, at night, city lights), and the
Moon is drawn here in its exact phase. Then a card for each: the Sun's latest
flare, the Earth's picture, and the Moon's phase and the next full or new Moon.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
import io
import json
import math
import time

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, ease_out, offload,
                         text_width, tiny_width)

SUVI = "https://services.swpc.noaa.gov/images/animations/suvi/primary/{band}/latest.png"
GOES = "https://cdn.star.nesdis.noaa.gov/{satellite}/ABI/FD/GEOCOLOR/339x339.jpg"
FLARES = "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-latest.json"
SATELLITES = {"west": ("GOES18", "GOES-WEST"), "east": ("GOES19", "GOES-EAST")}
BANDS = ("304", "195", "171", "284", "131", "094")
SUN_EVERY, EARTH_EVERY, FLARES_EVERY = 600, 600, 300

WHITE, GREY, AMBER, GOLD, CYAN = (236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60), (60, 200, 255)
FLARE_COLORS = {"A": (90, 230, 120), "B": (90, 230, 120), "C": (255, 214, 60), "M": (255, 140, 30), "X": (255, 50, 40)}
TRIPTYCH, CARD = 9.0, 7.0
SIZE = 32


# --- pictures (helper process) --------------------------------------------------------------

def _disc(image, size):
    """The picture cut to a size × size circle, everything outside it black."""
    image = image.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4))
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    out = Image.new("RGB", (size, size))
    out.paste(image, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out


def decode_sun(raw, size=SIZE):
    """GOES-19 SUVI composite -> the solar disc with a ring of corona, LED-ready RGB bytes."""
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    width, height = image.size
    grey = image.convert("L").crop((0, 0, width, int(height * .9)))   # leave out the caption
    box = grey.point(lambda v: 255 if v > 90 else 0).getbbox()
    if not box:
        raise ValueError("no Sun in the picture")
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    radius = max(box[2] - box[0], box[3] - box[1]) / 2 * 1.08
    image = image.crop((round(cx - radius), round(cy - radius), round(cx + radius), round(cy + radius)))
    image = ImageEnhance.Color(ImageEnhance.Contrast(image).enhance(1.25)).enhance(1.3)
    return image.resize((size, size), Image.LANCZOS).tobytes()


def decode_earth(raw, size=SIZE):
    """A GOES full disc (339 px, with a caption across the bottom) -> LED-ready RGB bytes."""
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    width, height = image.size
    ImageDraw.Draw(image).rectangle((0, height - height // 22, width, height), fill=(0, 0, 0))
    image = ImageEnhance.Color(ImageEnhance.Brightness(image).enhance(1.15)).enhance(1.7)
    return _disc(image, size).tobytes()


# --- the Moon and the Sun from here ---------------------------------------------------------

def _days(ts):
    return ts / 86400 + 2440587.5 - 2451545.0


def sun_longitude(ts):
    n = _days(ts)
    g = math.radians(357.528 + .9856003 * n)
    return (280.460 + .9856474 * n + 1.915 * math.sin(g) + .020 * math.sin(2 * g)) % 360, \
        1.00014 - .01671 * math.cos(g) - .00014 * math.cos(2 * g)


def moon(ts):
    """(ecliptic longitude°, distance km) from the largest terms of Meeus' lunar theory (about 0.3°)."""
    t = _days(ts) / 36525
    lp = 218.3164477 + 481267.88123421 * t
    d = math.radians(297.8501921 + 445267.1114034 * t)
    m = math.radians(357.5291092 + 35999.0502909 * t)
    mp = math.radians(134.9633964 + 477198.8675055 * t)
    f = math.radians(93.2720950 + 483202.0175233 * t)
    longitude = (lp + 6.289 * math.sin(mp) + 1.274 * math.sin(2 * d - mp) + .658 * math.sin(2 * d)
                 + .214 * math.sin(2 * mp) - .186 * math.sin(m) - .114 * math.sin(2 * f)) % 360
    distance = (385000.56 - 20905.36 * math.cos(mp) - 3699.11 * math.cos(2 * d - mp)
                - 2955.97 * math.cos(2 * d) - 569.93 * math.cos(2 * mp))
    return longitude, distance


def elongation(ts):
    """How far the Moon is round from the Sun: 0 new, 180 full, rising in between."""
    return (moon(ts)[0] - sun_longitude(ts)[0]) % 360


def lit_fraction(ts):
    return (1 - math.cos(math.radians(elongation(ts)))) / 2


def phase_name(ts):
    e = elongation(ts)
    for limit, name in ((6, "New Moon"), (84, "Waxing crescent"), (96, "First quarter"), (174, "Waxing gibbous"),
                        (186, "Full Moon"), (264, "Waning gibbous"), (276, "Last quarter"), (354, "Waning crescent")):
        if e < limit:
            return name
    return "New Moon"


def next_phase(ts, target):
    """When the elongation next reaches target (180 full, 0 new), to the minute."""
    def gap(when):
        return (target - elongation(when)) % 360
    step, when = 6 * 3600, ts
    while gap(when + step) < gap(when) and when < ts + 31 * 86400:
        when += step
    lo, hi = when, when + step
    for _ in range(20):
        mid = (lo + hi) / 2
        if gap(mid) < gap(lo) and gap(mid) < 180:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# Seas on the near side: (latitude°, longitude°, radius°). Dark basalt plains.
MARIA = ((33, -16, 10), (28, 17, 7), (8, 31, 9), (17, 59, 5.5), (-8, 51, 6.5), (-15, 35, 4), (-21, -17, 8),
         (18, -57, 14), (5, -45, 12), (-24, -39, 4.5), (56, 1, 5), (56, -20, 4), (56, 22, 4), (-3, -2, 5),
         (25, 30, 3))
TYCHO = (-43, -11)


@lru_cache(maxsize=64)
def moon_disc(elong_step, southern, size=SIZE):
    """The Moon at this elongation (in 2° steps), its seas, Tycho, and a faint edge on its dark side."""
    e = math.radians(elong_step * 2)
    sun_x, sun_z = math.sin(e), -math.cos(e)
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    radius = size / 2 - .5
    for y in range(size):
        for x in range(size):
            nx, ny = (x - radius) / radius, (radius - y) / radius
            rr = nx * nx + ny * ny
            if rr > 1:
                continue
            nz = math.sqrt(1 - rr)
            lat, lon = math.degrees(math.asin(ny)), math.degrees(math.atan2(nx, nz))
            albedo = 1.0
            for mlat, mlon, mr in MARIA:
                if (lat - mlat) ** 2 + ((lon - mlon) * math.cos(math.radians(lat))) ** 2 < mr * mr:
                    albedo = .55
                    break
            if (lat - TYCHO[0]) ** 2 + (lon - TYCHO[1]) ** 2 < 9:
                albedo = 1.25
            light = (nx if not southern else -nx) * sun_x + nz * sun_z
            if light > 0:
                shade = min(1, .35 + light * 1.2) * albedo
                pixels[x, y] = (min(255, round(225 * shade)), min(255, round(222 * shade)), min(255, round(200 * shade)))
            else:   # earthshine: the dark side faintly, a little brighter at the rim
                pixels[x, y] = (44, 48, 70) if rr > .78 else (round(26 * albedo + 4), round(28 * albedo + 4), round(42 * albedo + 4))
    return image


# --- the provider ----------------------------------------------------------------------------

def _age(response):
    try:
        return parsedate_to_datetime(response.headers["Last-Modified"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return time.time()


class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.data = {"sun": None, "sun_at": None, "earth": None, "earth_at": None, "flare": None, "satellite": None}
        self.asked = {"sun": (None, -1e9), "earth": (None, -1e9), "flare": (None, -1e9)}

    def _due(self, what, key, every):
        asked, at = self.asked[what]
        return asked != key or time.monotonic() - at >= every

    async def fetch(self):
        settings = self.context.settings
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),
                                                 headers={"User-Agent": "RackTicker three-bodies plugin"})
        failures = []
        band = settings["sun_band"]
        if self._due("sun", band, SUN_EVERY):
            try:
                async with self.session.get(SUVI.format(band=band)) as response:
                    response.raise_for_status()
                    raw, at = await response.read(), _age(response)
                self.data["sun"], self.data["sun_at"] = await offload(decode_sun, raw), at
                self.asked["sun"] = (band, time.monotonic())
            except Exception as exc:  # a bad picture keeps the last good one
                failures.append(exc)
                self.asked["sun"] = (band, time.monotonic() - SUN_EVERY + 60)
        satellite = settings["earth_satellite"]
        if self._due("earth", satellite, EARTH_EVERY):
            try:
                async with self.session.get(GOES.format(satellite=SATELLITES[satellite][0])) as response:
                    response.raise_for_status()
                    raw, at = await response.read(), _age(response)
                self.data["earth"], self.data["earth_at"] = await offload(decode_earth, raw), at
                self.data["satellite"] = SATELLITES[satellite][1]
                self.asked["earth"] = (satellite, time.monotonic())
            except Exception as exc:
                failures.append(exc)
                self.asked["earth"] = (satellite, time.monotonic() - EARTH_EVERY + 60)
        if self._due("flare", None, FLARES_EVERY):
            try:
                async with self.session.get(FLARES) as response:
                    response.raise_for_status()
                    rows = json.loads(await response.text())
                row = rows[-1] if isinstance(rows, list) and rows else {}
                if row.get("max_class") and row.get("max_time"):
                    peak = datetime.fromisoformat(row["max_time"].replace("Z", "+00:00")).timestamp()
                    self.data["flare"] = {"class": row["max_class"], "at": peak}
                self.asked["flare"] = (None, time.monotonic())
            except Exception as exc:
                failures.append(exc)
                self.asked["flare"] = (None, time.monotonic() - FLARES_EVERY + 60)
        if failures and not (self.data["sun"] or self.data["earth"]):
            raise failures[0]
        return Snapshot(dict(self.data))

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# --- the screen ------------------------------------------------------------------------------

@lru_cache(maxsize=8)
def picture(raw):
    return Image.frombytes("RGB", (SIZE, SIZE), raw)


def ago(seconds):
    minutes = max(0, int(seconds // 60))
    if minutes < 2:
        return "JUST NOW"
    if minutes < 60:
        return f"{minutes} MIN AGO"
    hours = minutes // 60
    return f"{hours} HOUR AGO" if hours == 1 else f"{hours} HOURS AGO" if hours < 48 else f"{hours // 24} DAYS AGO"


def in_days(seconds):
    days = seconds / 86400
    if days < .75:
        return f"IN {max(1, round(seconds / 3600))} HOURS"
    if days < 1.5:
        return "TOMORROW"
    return f"IN {round(days)} DAYS"


def short_miles(miles):
    return f"{round(miles / 1e6)}M" if miles >= 1e6 else f"{round(miles / 1e3)}K"


def reveal(frame, image, x, local, delay):
    """A picture fading up from black."""
    amount = ease_out((local - delay) / .8)
    if amount <= 0:
        return
    if amount < 1:
        image = Image.eval(image, lambda v: round(v * amount))
    frame.paste(image, (x, 0))


class ThreeBodies(Module):
    name = "three_bodies"

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def hold(self, context):
        return self.story.hold()

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        snap = context.snapshots.get(self.name)
        data = snap.data if snap and snap.data else {}
        settings = context.config["plugins"][self.name]
        ts = context.now.timestamp()
        southern = settings["latitude"] < 0
        moon_image = moon_disc(round(elongation(ts) / 2) % 180, southern)
        sun_image = picture(data["sun"]) if data.get("sun") else None
        earth_image = picture(data["earth"]) if data.get("earth") else None

        def build(visit):
            cards = [("all", TRIPTYCH)]
            if sun_image:
                cards.append(("sun", CARD))
            if earth_image:
                cards.append(("earth", CARD))
            return cards + [("moon", CARD)]

        self.story.sync(context.animation_time, build, context.scene)
        page, local, _ = self.story.current(context.animation_time, build) or ("all", 0, TRIPTYCH)
        if page == "all":
            self._triptych(frame, sun_image, earth_image, moon_image, ts, local)
        elif page == "sun":
            reveal(frame, sun_image, 0, local, -.3)
            self._sun(frame, data, ts, local)
        elif page == "earth":
            reveal(frame, earth_image, 0, local, -.3)
            self._earth(frame, data, ts, local)
        else:
            reveal(frame, moon_image, 0, local, -.3)
            self._moon(frame, ts, local)
        return frame

    @staticmethod
    def _triptych(frame, sun_image, earth_image, moon_image, ts, local):
        slots = [(0, sun_image), (48, earth_image), (96, moon_image)]
        for index, (x, image) in enumerate(slots):
            if image is not None:
                reveal(frame, image, x, local, index * .5 - .3)
        if local < 2:
            return
        sun_miles = sun_longitude(ts)[1] * 92955807
        moon_miles = moon(ts)[1] * .621371
        for left, miles in ((32, sun_miles), (80, moon_miles)):
            label = short_miles(miles)
            draw_tiny(frame, label, left + 8 - tiny_width(label) // 2, 10, GREY)
            draw_tiny(frame, "MI", left + 8 - tiny_width("MI") // 2, 17, GREY)

    @staticmethod
    def _sun(frame, data, ts, local):
        x = 38
        draw_tiny(frame, "THE SUN", x, 1, GOLD)
        draw_tiny(frame, ago(ts - data["sun_at"]), 128 - tiny_width(ago(ts - data["sun_at"])), 1, GREY)
        flare = data.get("flare")
        if flare:
            draw_tiny(frame, "LATEST FLARE", x, 9, GREY)
            size = flare["class"]
            color = FLARE_COLORS.get(size[:1], WHITE)
            draw_text(frame, size, x, 16, color, scale=2, smooth=True)
            when = ago(ts - flare["at"])
            draw_tiny(frame, when, 128 - tiny_width(when), 26, GREY)
        else:
            draw_text(frame, "GOES-19", x, 14, WHITE)

    @staticmethod
    def _earth(frame, data, ts, local):
        x = 38
        draw_tiny(frame, "EARTH", x, 1, CYAN)
        age = ago(ts - data["earth_at"])
        draw_tiny(frame, age, 128 - tiny_width(age), 1, GREY)
        draw_tiny(frame, f"FROM {data.get('satellite') or 'GOES'},", x, 10, GREY)
        draw_text(frame, "22,236 mi up", x, 17, WHITE, mixed=True)

    @staticmethod
    def _moon(frame, ts, local):
        x = 38
        name = phase_name(ts)
        draw_tiny(frame, "THE MOON", x, 1, GREY)
        draw_text(frame, name, x, 8, WHITE, mixed=True)
        lit = f"{round(lit_fraction(ts) * 100)}%"
        draw_text(frame, lit, x, 19, AMBER)
        draw_tiny(frame, "LIT", x + text_width(lit) + 2, 21, AMBER)
        e = elongation(ts)
        target, label = (180, "FULL") if e < 174 else (0, "NEW") if e < 354 else (180, "FULL")
        upcoming = f"{label} {in_days(next_phase(ts, target) - ts)}"
        draw_tiny(frame, upcoming, 128 - tiny_width(upcoming), 27, GREY)


def validate_settings(settings):
    if settings.get("sun_band") not in BANDS:
        raise ValueError(f"sun_band must be one of {', '.join(BANDS)}")
    if settings.get("earth_satellite") not in SATELLITES:
        raise ValueError("earth_satellite must be west or east")
    return settings


plugin = Plugin(
    "three_bodies", "Three bodies", module=ThreeBodies, provider=Feed,
    defaults={"latitude": 0.0, "longitude": 0.0, "earth_satellite": "west", "sun_band": "304"},
    choices={"earth_satellite": tuple(SATELLITES), "sun_band": BANDS},
    validate_settings=validate_settings,
    help={"latitude": "South of the equator the Moon is drawn the way you see it, lit from the other side",
          "earth_satellite": "west sees the Pacific and the Americas; east sees the Americas and the Atlantic",
          "sun_band": "Which colour of ultraviolet light: 304 is the orange surface, 195 and 171 the corona"},
    ui={"latitude": {"type": "location", "label": "Location"}, "longitude": {"advanced": True},
        "earth_satellite": {"label": "Earth seen from"}, "sun_band": {"label": "Sun picture", "advanced": True}},
)
