"""Surf: the waves at your break, key-free.

Open-Meteo's marine forecast for wave height, swell period and direction and
water temperature; NOAA's tide predictions for the next high or low. The wave
rolling along the bottom is sized and paced by the real swell.
"""
from __future__ import annotations

from datetime import datetime
import math

import aiohttp
from PIL import ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, draw_text, draw_tiny, new_frame, text_width,
                        tiny_width, triangle)

MARINE = "https://marine-api.open-meteo.com/v1/marine"
TIDES = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
# Break: (name, latitude, longitude just offshore, NOAA tide station)
SPOTS = {
    "huntington": ("Huntington Pier", 33.650, -118.010, "9410580"),
    "newport": ("The Wedge", 33.590, -117.885, "9410580"),
    "trestles": ("Trestles", 33.378, -117.595, "9410230"),
    "blacks": ("Black's Beach", 32.880, -117.260, "9410230"),
    "malibu": ("Malibu", 34.030, -118.680, "9410840"),
    "steamer_lane": ("Steamer Lane", 36.950, -122.030, "9413745"),
    "mavericks": ("Mavericks", 37.490, -122.505, "9414290"),
    "ocean_beach": ("Ocean Beach SF", 37.760, -122.515, "9414290"),
    "pipeline": ("Pipeline", 21.668, -158.055, "1612340"),
}
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
# The picture on the right: a slice of sea meeting a beach. Waves come in from the left,
# run up the sand, and the tide moves the waterline up and down the slope.
WINDOW_X, WINDOW_TOP = 88, 8
WINDOW_W, WINDOW_H = 128 - WINDOW_X, 32 - WINDOW_TOP
SLOPE_START, SLOPE = 14, .8           # where the sand starts to rise, and how fast (rows per column)
WATER = ((120, 224, 255), (70, 190, 250), (40, 150, 240), (30, 120, 225), (24, 96, 200), (18, 72, 168),
         (14, 56, 140), (12, 46, 120))            # surface to deep
SAND, WET_SAND, FOAM_WHITE = (216, 190, 138), (150, 124, 90), (240, 250, 255)
WHITE, GREY, AMBER, SEA, FOAM = (236, 238, 236), (140, 146, 150), (255, 176, 20), (30, 110, 220), (200, 235, 255)


def nearest(latitude, longitude):
    return min(SPOTS, key=lambda spot: (SPOTS[spot][1] - latitude) ** 2 + (SPOTS[spot][2] - longitude) ** 2)


class Conditions(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None

    async def fetch(self):
        settings = self.context.settings
        spot = settings["spot"]
        if spot == "nearest":
            if settings["latitude"] == 0 and settings["longitude"] == 0:
                raise ValueError("Pick a break, or set your home location in Settings")
            spot = nearest(settings["latitude"], settings["longitude"])
        name, latitude, longitude, station = SPOTS[spot]
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        params = {"latitude": latitude, "longitude": longitude, "length_unit": "imperial",
                  "temperature_unit": "fahrenheit", "timezone": "auto",
                  "current": "wave_height,wave_period,wave_direction,swell_wave_height,swell_wave_period,"
                             "swell_wave_direction,sea_surface_temperature"}
        async with self.session.get(MARINE, params=params) as response:
            response.raise_for_status()
            current = (await response.json(content_type=None))["current"]
        tide = None
        today = datetime.now()
        tide_params = {"product": "predictions", "application": "rackticker", "datum": "MLLW", "station": station,
                       "begin_date": today.strftime("%Y%m%d"), "range": "48", "time_zone": "lst_ldt",
                       "units": "english", "interval": "hilo", "format": "json"}
        try:
            async with self.session.get(TIDES, params=tide_params) as response:
                predictions = (await response.json(content_type=None)).get("predictions") or []
            upcoming = [row for row in predictions if datetime.strptime(row["t"], "%Y-%m-%d %H:%M") > today]
            if upcoming:
                # The one after it too: two turns of the tide say which way the water
                # is going now, and how far through the swing it is.
                tide = {"high": upcoming[0]["type"] == "H", "time": upcoming[0]["t"],
                        "feet": float(upcoming[0]["v"]),
                        "then": upcoming[1]["t"] if len(upcoming) > 1 else None}
        except (aiohttp.ClientError, ValueError, KeyError):
            tide = None
        return Snapshot({"spot": name, "height": current.get("wave_height"), "period": current.get("swell_wave_period")
                         or current.get("wave_period"), "direction": current.get("swell_wave_direction")
                         or current.get("wave_direction"), "water": current.get("sea_surface_temperature"),
                         "tide": tide})

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


def face(height):
    """Wave height in the way surfers say it: '2-3 FT'."""
    if height is None:
        return "--"
    low, high = max(0, math.floor(height * .8)), max(1, math.ceil(height * 1.1))
    return f"{high} FT" if low == high or low == 0 and high <= 1 else f"{low}-{high} FT"


class Waves:
    """A slice of sea meeting a beach, seen side on, and what swell does there.

    Out in deep water a wave is a long, low, rounded swell. As the floor rises it slows, so
    the crests bunch up; it stands taller, and its crest sharpens while the trough between
    flattens. When the water under it is about as deep as the wave is high, it breaks: the
    crest curls into foam, and what is left runs at the beach as a low, white bore that
    climbs the sand and slides back off it. All of that is a function of the depth at each
    column, so it is worked out once per tide and size, and each frame is just the phase.
    The real swell period sets the pace, and real swell comes in sets, so the size of the
    waves swells and fades a little over time."""

    LENGTH = 24.0           # deep-water wavelength, in columns
    BREAK = 1.9             # a wave breaks where the water is this many wave-heights deep

    def __init__(self, width=WINDOW_W):
        self.width = width
        self.key = None
        self.phase, self.amp, self.sharp, self.depth, self.broken = [], [], [], [], []

    def build(self, surface, size):
        """Per-column facts about the sea floor and the wave that runs over it."""
        key = (round(surface * 4), round(size * 4))
        if key == self.key:
            return
        self.key = key
        deep = max(4.0, 31 - surface)
        theta, total = [], 0.0
        self.amp, self.sharp, self.depth, self.broken = [], [], [], []
        for column in range(self.width):
            floor = 31 - max(0.0, (column - SLOPE_START) * SLOPE)          # the sand's top edge here
            depth = max(0.0, floor - surface)                              # water above it at rest
            shoal = 1 - min(1.0, depth / deep)                             # 0 far out, 1 at the shore
            # The wave shortens as it slows over the rising floor: crests bunch towards the beach.
            total += math.tau / self.LENGTH * (1 + 1.6 * shoal)
            height = size * (1 + 1.3 * shoal)
            limit = self.BREAK * height
            broken = depth < limit
            if broken:              # past the break what is left is a bore, dying as the water shallows
                height *= .3 + .7 * depth / limit
            theta.append(total)
            self.amp.append(height)
            self.sharp.append(.08 + .45 * shoal)
            self.depth.append(depth)
            self.broken.append(broken)
        self.phase = theta

    def surface(self, column, t, period, surface):
        """The water's top edge at this column, in rows, and how much it is breaking (0 to 1)."""
        omega = math.tau / period
        # Sets: the swell builds and fades over a few waves, and not evenly along the beach.
        sets = .8 + .2 * math.sin(t * omega / 3.7 + column * .045)
        angle = self.phase[column] - omega * t
        sharp = self.sharp[column]
        lift = (math.cos(angle) + sharp * math.cos(2 * angle)) / (1 + sharp)
        return surface - self.amp[column] * sets * lift, lift


class Report(Module):
    name = "surf"

    def __init__(self):
        self.waves = Waves()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def available(self, context):
        snap = context.snapshots.get(self.name)
        return bool(snap and snap.data and snap.data.get("height") is not None)

    def render(self, context):
        frame = new_frame()
        snap = context.snapshots.get(self.name)
        surf = snap.data if snap and snap.data else None
        if not surf:
            draw_text(frame, "Surf", 2, 12, GREY, mixed=True)
            return frame
        t = context.animation_time
        level = self._level(surf.get("tide"), context.now.replace(tzinfo=None))
        self._sea(frame, surf, t, level)
        # Everything to read is on the left, on black, clear of the water.
        draw_text(frame, surf["spot"], 0, 0, AMBER, mixed=True)
        if surf.get("water") is not None:
            water = f"{round(surf['water'])}°"
            draw_text(frame, water, 128 - text_width(water), 0, SEA)
        size = face(surf["height"])
        room = WINDOW_X - 3
        scale = 2 if text_width(size, 2) <= room else 1
        draw_text(frame, size, 0, 9 if scale == 2 else 12, WHITE, scale, scale == 2)
        # One line under it: the swell, then the tide with an arrow for which way it is going.
        x = 0
        if surf.get("period"):
            direction = COMPASS[round((surf.get("direction") or 0) / 45) % 8]
            swell = f"{round(surf['period'])}S {direction}"
            draw_tiny(frame, swell, x, 26, GREY)
            x += tiny_width(swell) + 6
        tide = surf.get("tide")
        if tide:
            when = datetime.strptime(tide["time"], "%Y-%m-%d %H:%M")
            clock = when.strftime("%I:%M%p").lstrip("0").replace("AM", "A").replace("PM", "P")
            label = f"{'HIGH' if tide['high'] else 'LOW'} {clock}"
            if x + 7 + tiny_width(label) <= room:
                triangle(frame, x, 27, bool(tide["high"]), SEA)
                draw_tiny(frame, label, x + 7, 26, GREY)
        return frame

    @staticmethod
    def _size(surf):
        """How tall the waves are drawn, in rows: sized by the real surf."""
        return min(5.0, 1.6 + (surf.get("height") or 1) * .7)

    def _sea(self, frame, surf, t, level=None):
        """A slice of the real thing: swell coming in from the left, steepening and breaking on
        the beach rising on the right, and the waterline sitting where the real tide has put it."""
        size = self._size(surf) * .7
        # The real period sets the pace, but a swell that takes fifteen seconds to arrive is
        # not worth watching: the picture keeps to between four and a half and nine.
        period = max(4.5, min(9.0, (surf.get("period") or 10) * .6))
        # Low tide leaves the water low and the beach wide; high tide floods up the slope.
        surface = 16.5 - ((.5 if level is None else level) - .5) * 6
        waves = self.waves
        waves.build(surface, size)
        top = frame.load()
        for column in range(WINDOW_W):
            x = WINDOW_X + column
            sand = 31 - max(0.0, (column - SLOPE_START) * SLOPE)          # the beach's top edge here
            wave, lift = waves.surface(column, t, period, surface)
            water_row, sand_row = round(wave), round(sand)
            for y in range(max(WINDOW_TOP, min(water_row, sand_row)), 32):
                if y >= sand_row:
                    # Sand the water has just left is wet, and darker for it.
                    top[x, y] = WET_SAND if y - sand_row < 2 and water_row < sand_row + 2 else SAND
                else:
                    top[x, y] = WATER[min(len(WATER) - 1, y - water_row)]
            if water_row >= sand_row or water_row < WINDOW_TOP:
                continue
            if waves.broken[column]:
                # Breaking: white water. The crest of the wave is foam and the face behind it
                # is streaked with it, running towards the shore.
                if lift > -.2 or sand_row - water_row <= 1:
                    top[x, water_row] = FOAM_WHITE
                    if lift > .55 and water_row - 1 >= WINDOW_TOP:       # the lip, thrown forward
                        top[x, water_row - 1] = FOAM
                        if x + 1 < 128:
                            top[x + 1, water_row - 1] = FOAM_WHITE
                for streak in (1, 2):
                    if water_row + streak < sand_row and (column * 3 + int(t * 5) + streak * 2) % 5 == 0:
                        top[x, water_row + streak] = FOAM
            elif lift > .8:
                top[x, water_row] = WATER[0]                             # a bright, unbroken crest
            elif sand_row - water_row <= 1:
                top[x, water_row] = FOAM_WHITE

    @staticmethod
    def _level(tide, now=None):
        """How far through the swing the water is: 0 at dead low, 1 at dead high.

        The tide gives the next turn and the one after, so the swing between them
        is the same length as the one running now, counted back from the next turn."""
        if not tide or not tide.get("then"):
            return None
        now = now or datetime.now()
        try:
            turn = datetime.strptime(tide["time"], "%Y-%m-%d %H:%M")
            after = datetime.strptime(tide["then"], "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return None
        swing = (after - turn).total_seconds()
        if swing <= 0:
            return None
        done = min(1.0, max(0.0, 1 - (turn - now).total_seconds() / swing))
        return done if tide["high"] else 1 - done


plugin = Plugin(
    "surf", "Surf", module=Report, provider=Conditions,
    defaults={"spot": "nearest", "latitude": 0.0, "longitude": 0.0},
    choices={"spot": ("nearest", *SPOTS)},
    help={"spot": "nearest picks the break closest to your home location"},
    ui={"latitude": {"advanced": True}, "longitude": {"advanced": True}},
)
