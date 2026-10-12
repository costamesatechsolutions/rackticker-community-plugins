"""Wildfires: the fires burning near you, how big, how contained, and which way.

A count of the active fires within your distance, then a card for each of the
nearest and biggest: a flame, its name, acres burned, a containment bar, how far
away and in which direction, and how many days it has burned. A new fire
starting close to you takes over the display once.

From the US National Interagency Fire Center's current incident list (all
states, updated through the day; free, no key).
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import math
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, offload, text_width,
                         tiny_width)

API = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
       "WFIGS_Incident_Locations_Current/FeatureServer/0/query")
ASK_EVERY = 600
WHITE, GREY, AMBER, GOLD, RED, GREEN = ((236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60),
                                        (255, 50, 30), (90, 230, 120))
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
SUMMARY, CARD = 6.0, 7.0
NAME_REST, NAME_SPEED = 1.3, 18


def miles(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def bearing(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return math.degrees(math.atan2(y, x)) % 360


def tidy(name):
    """"0445 CROSSWHITE" -> "0445 Crosswhite"; keeps short codes like "SQF" in capitals."""
    words = []
    for word in str(name or "Unnamed").split():
        words.append(word if len(word) <= 3 and word.isalpha() and word.isupper() and word not in ("THE", "AND")
                     else word.capitalize())
    return " ".join(words)


def parse(payload, home, within, smallest=10):
    fires = []
    for feature in payload.get("features") or []:
        attributes, geometry = feature.get("attributes") or {}, feature.get("geometry") or {}
        if geometry.get("x") is None:
            continue
        where = (geometry["y"], geometry["x"])
        distance = miles(home, where)
        contained = attributes.get("PercentContained")
        size = float(attributes.get("IncidentSize") or 0)
        if distance > within or (contained is not None and contained >= 100) or size < smallest:
            continue      # far away, out, or a spot fire caught at a few acres (most first reports)
        fires.append({"name": tidy(attributes.get("IncidentName")), "acres": float(attributes.get("IncidentSize") or 0),
                      "contained": contained, "miles": round(distance),
                      "look": COMPASS[round(bearing(home, where) / 22.5) % 16],
                      "started": (attributes.get("FireDiscoveryDateTime") or 0) / 1000,
                      "state": str(attributes.get("POOState") or "").replace("US-", "")})
    return fires


class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.fires, self.asked, self.key, self.alerted = [], -1e9, None, set()

    async def fetch(self):
        settings = self.context.settings
        home = (settings["latitude"], settings["longitude"])
        if home == (0, 0):
            raise ValueError("Set your home location in Settings")
        key = (home, settings["within_miles"], settings["min_acres"])
        if key != self.key or time.monotonic() - self.asked >= ASK_EVERY:
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),
                                                     headers={"User-Agent": "RackTicker wildfires plugin"})
            pad_lat = settings["within_miles"] / 69
            pad_lon = settings["within_miles"] / max(10.0, 69 * math.cos(math.radians(home[0])))
            params = {"where": "IncidentTypeCategory='WF'", "f": "json", "outSR": "4326", "inSR": "4326",
                      "outFields": "IncidentName,IncidentSize,PercentContained,POOState,FireDiscoveryDateTime",
                      "geometry": f"{home[1] - pad_lon},{home[0] - pad_lat},{home[1] + pad_lon},{home[0] + pad_lat}",
                      "geometryType": "esriGeometryEnvelope", "spatialRel": "esriSpatialRelIntersects",
                      "returnGeometry": "true", "resultRecordCount": "500"}
            try:
                async with self.session.get(API, params=params) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
                if "error" in payload:
                    raise ValueError(str(payload["error"]))
                self.fires = parse(payload, home, settings["within_miles"], settings["min_acres"])
                self.asked, self.key = time.monotonic(), key
            except (aiohttp.ClientError, TimeoutError, ValueError):
                self.asked = time.monotonic() - ASK_EVERY + 120
                if self.key is None:
                    raise
        now = time.time()
        for fire in self.fires:
            if (settings["alert"] and fire["miles"] <= settings["alert_miles"] and now - fire["started"] < 6 * 3600
                    and fire["name"] not in self.alerted):
                self.alerted.add(fire["name"])
                self.context.emit_event("wildfires", 20)
        return Snapshot(self.fires)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# --- the screen ------------------------------------------------------------------------------

def _noise(x, y):
    n = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 0xFFFF


def flame(frame, left, top, width, height, t):
    """A flickering flame: hot white-yellow at the base, red licks at the top, from its own time."""
    pixels = frame.load()
    rise = int(t * 14)
    for y in range(height):
        up = 1 - y / height                                   # 1 at the bottom row
        for x in range(width):
            centre = 1 - abs(x - (width - 1) / 2) / (width / 2)
            n = (_noise(x // 2, (y + rise) // 2) + _noise(x, y + rise)) / 2
            heat = up * .9 + centre * .7 + n * .6 - 1.0
            if heat <= 0:
                continue
            color = ((255, 240, 160) if heat > .75 else (255, 200, 40) if heat > .5 else
                     (255, 120, 10) if heat > .28 else (200, 40, 10))
            pixels[left + x, top + height - 1 - y] = color


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


def acres(value):
    return f"{value / 1000:.0f}K" if value >= 100000 else f"{value:,.0f}"


class Wildfires(Module):
    name = "wildfires"
    event_priority = 26

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _fires(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data else []

    def available(self, context):
        return bool(self._fires(context))

    def hold(self, context):
        return self.story.hold()

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        fires = self._fires(context)
        if not fires:
            draw_text(frame, "No fires nearby", 2, 12, GREEN, mixed=True)
            return frame
        settings = context.config["plugins"][self.name]
        nearest = sorted(fires, key=lambda fire: fire["miles"])[:settings["cards"]]
        biggest = max(fires, key=lambda fire: fire["acres"])
        shown = nearest + ([biggest] if biggest not in nearest else [])

        def build(visit):
            return [("summary", SUMMARY)] + [(index, CARD) for index in range(len(shown))]

        self.story.sync(context.animation_time, build, context.scene)
        card, local, _ = self.story.current(context.animation_time, build) or ("summary", 0, 0)
        if card == "summary":
            self._summary(frame, fires, settings, context.animation_time)
        else:
            self._fire(frame, shown[min(card, len(shown) - 1)], context.now.timestamp(), local, context.animation_time)
        return frame

    @staticmethod
    def _summary(frame, fires, settings, t):
        flame(frame, 1, 4, 12, 26, t)
        count = str(len(fires))
        draw_text(frame, count, 18, 5, AMBER, scale=2, smooth=True)
        x = 18 + text_width(count, 2) + 4
        draw_tiny(frame, "ACTIVE FIRES" if len(fires) != 1 else "ACTIVE FIRE", x, 6, WHITE)
        draw_tiny(frame, f"WITHIN {settings['within_miles']} MI", x, 13, GREY)
        total = sum(fire["acres"] for fire in fires)
        draw_tiny(frame, f"{total:,.0f} ACRES BURNING", 18, 25, GREY)

    @staticmethod
    def _fire(frame, fire, ts, local, t):
        flame(frame, 1, 4, 12, 26, t + fire["miles"])
        x = 17
        fitted(frame, fire["name"], x, 0, 128 - x, WHITE, local)
        size = f"{fire['acres']:,.0f}"
        draw_text(frame, size, x, 11, AMBER)
        draw_tiny(frame, "ACRES", x + text_width(size) + 3, 13, AMBER)
        where = f"{fire['miles']} MI {fire['look']}"
        draw_tiny(frame, where, 128 - tiny_width(where), 13, GREY)
        draw = ImageDraw.Draw(frame)
        contained = fire["contained"]
        draw.rectangle((x, 21, x + 60, 24), outline=(80, 80, 90))
        if contained:
            draw.rectangle((x + 1, 22, x + 1 + round(58 * contained / 100 * min(1.0, local / 1.2)), 23), fill=GREEN)
        label = f"{contained:.0f}% CONTAINED" if contained is not None else "CONTAINMENT UNKNOWN"
        draw_tiny(frame, label, x, 27, GREEN if contained else RED)
        if fire["started"]:
            days = max(1, math.ceil((ts - fire["started"]) / 86400))
            when = f"DAY {days}" if days > 1 else "NEW TODAY"
            draw_tiny(frame, when, 128 - tiny_width(when), 21, RED if days <= 1 else GREY)


def validate_settings(settings):
    if not 10 <= float(settings.get("within_miles", 250)) <= 1000:
        raise ValueError("within_miles must be 10 to 1000")
    if not 1 <= int(settings.get("cards", 4)) <= 10:
        raise ValueError("cards must be 1 to 10")
    return settings


plugin = Plugin(
    "wildfires", "Wildfires", module=Wildfires, provider=Feed,
    defaults={"latitude": 0.0, "longitude": 0.0, "within_miles": 250, "min_acres": 10, "cards": 4, "alert": True,
              "alert_miles": 25},
    validate_settings=validate_settings,
    help={"latitude": "Leave at 0 to use the home location from Settings",
          "min_acres": "Leave out fires smaller than this: most first reports are spot fires put out at an acre or two",
          "alert": "Take over once when a new fire starts within the alert distance"},
    ui={"latitude": {"type": "location", "label": "Location"}, "longitude": {"advanced": True},
        "within_miles": {"type": "slider", "min": 25, "max": 1000, "step": 25, "unit": "mi", "label": "Show fires within"},
        "min_acres": {"type": "slider", "min": 0, "max": 1000, "step": 10, "unit": "acres", "label": "Smallest fire"},
        "cards": {"type": "slider", "min": 1, "max": 10, "step": 1, "label": "Nearest fires shown"},
        "alert": {"label": "Take over for a new fire nearby"},
        "alert_miles": {"type": "slider", "min": 5, "max": 100, "step": 5, "unit": "mi", "label": "Nearby means within"}},
)
