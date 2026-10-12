"""Space weather: what the Sun is doing to the Earth, from NOAA's Space Weather Prediction Center.

Four cards: the geomagnetic storm level (Kp) with the last day and the forecast as
bars; the solar wind streaming past at its real speed with the direction of its
magnetic field; six hours of the Sun's X-rays on the flare scale (A, B, C, M, X);
and whether the northern lights could reach you, worked out from your geomagnetic
latitude. A strong storm, an X flare or an aurora within reach takes over once.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import random
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, offload, text_width,
                         tiny_width)

BASE = "https://services.swpc.noaa.gov/"
KP_NOW = BASE + "json/planetary_k_index_1m.json"
KP_FORECAST = BASE + "products/noaa-planetary-k-index-forecast.json"
WIND = BASE + "products/summary/solar-wind-speed.json"
FIELD = BASE + "products/summary/solar-wind-mag-field.json"
XRAYS = BASE + "json/goes/primary/xrays-6-hour.json"
SCALES = BASE + "products/noaa-scales.json"
ASK_EVERY = 120
WHITE, GREY, AMBER, GOLD, RED, GREEN, CYAN = ((236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60),
                                              (255, 60, 40), (90, 230, 120), (60, 200, 255))
ORANGE = (255, 120, 20)
CARD = 8.0
POLE = (80.8, -72.7)          # the geomagnetic north pole (IGRF, 2025)
STORMS = {0: "QUIET", 1: "G1 MINOR STORM", 2: "G2 MODERATE STORM", 3: "G3 STRONG STORM", 4: "G4 SEVERE STORM",
          5: "G5 EXTREME STORM"}
CLASSES = (("A", 1e-8), ("B", 1e-7), ("C", 1e-6), ("M", 1e-5), ("X", 1e-4))


def kp_color(kp):
    return GREEN if kp < 4 else GOLD if kp < 5 else ORANGE if kp < 7 else RED


def flare_class(flux):
    if not flux or flux <= 0:
        return "A0.0"
    letter, base = "A", 1e-8
    for name, floor in CLASSES:
        if flux >= floor:
            letter, base = name, floor
    return f"{letter}{flux / base:.1f}"


def flare_color(letter):
    return {"C": GOLD, "M": ORANGE, "X": RED}.get(letter[:1], GREEN)


def magnetic_latitude(lat, lon):
    lat, lon, plat, plon = map(math.radians, (lat, lon, *POLE))
    return math.degrees(math.asin(math.sin(lat) * math.sin(plat) + math.cos(lat) * math.cos(plat) * math.cos(lon - plon)))


# The lowest geomagnetic latitude that sees aurora on the northern horizon at each Kp,
# after NOAA's viewing guide. Kp stops at 9, so 9 stands for the rare extreme storms
# (May 2024) that reached 38°, Southern California and Alabama.
VIEW_LINE = (66, 64.5, 62.5, 60.5, 58.5, 56, 53.5, 50.5, 47, 38)


def kp_for_aurora(mlat):
    """The Kp at which aurora shows low on the northern horizon from this geomagnetic latitude."""
    for kp, edge in enumerate(VIEW_LINE):
        if abs(mlat) >= edge:
            return kp
    return None


def parse_xrays(raw):
    """Six hours of the long X-ray channel, one value a minute (helper process)."""
    rows = json.loads(raw)
    flux = {}
    for row in rows:
        if row.get("energy") == "0.1-0.8nm" and row.get("flux"):
            flux[row["time_tag"]] = float(row["flux"])
    return [flux[key] for key in sorted(flux)][-360:]


class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.data, self.asked, self.alerted = {}, -1e9, set()

    async def _json(self, url):
        async with self.session.get(url) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def fetch(self):
        settings = self.context.settings
        home = (settings["latitude"], settings["longitude"])
        if time.monotonic() - self.asked < ASK_EVERY and self.data:
            return Snapshot({**self.data, "home": home})
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),
                                                 headers={"User-Agent": "RackTicker space weather plugin"})
        data = dict(self.data)
        failures = []
        try:
            rows = await self._json(KP_NOW)
            recent = [float(row["estimated_kp"]) for row in rows[-15:] if row.get("estimated_kp") is not None]
            data["kp"] = round(sum(recent) / len(recent), 2)   # the minute estimate jitters; a quarter hour does not
        except Exception as exc:
            failures.append(exc)
        try:
            rows = await self._json(KP_FORECAST)
            bars = []
            for row in rows:
                if isinstance(row, dict) and row.get("kp") is not None:
                    at = datetime.fromisoformat(row["time_tag"]).replace(tzinfo=timezone.utc).timestamp()
                    bars.append((at, float(row["kp"]), row.get("observed") == "observed"))
            data["bars"] = bars
        except Exception as exc:
            failures.append(exc)
        try:
            data["speed"] = float((await self._json(WIND))[0]["proton_speed"])
            field = (await self._json(FIELD))[0]
            data["bz"], data["bt"] = float(field["bz_gsm"]), float(field["bt"])
        except Exception as exc:
            failures.append(exc)
        try:
            async with self.session.get(XRAYS) as response:
                response.raise_for_status()
                data["xrays"] = await offload(parse_xrays, await response.read())
        except Exception as exc:
            failures.append(exc)
        try:
            scales = (await self._json(SCALES))["0"]
            data["g"] = int(scales["G"]["Scale"] or 0)
        except Exception as exc:
            failures.append(exc)
        self.asked = time.monotonic()
        if failures and not data:
            raise failures[0]
        self.data = data
        self._alerts(data)
        return Snapshot({**data, "home": home})

    def _alerts(self, data):
        settings = self.context.settings
        if not settings["alert"]:
            return
        slot = int(time.time() // 10800)
        home = (settings["latitude"], settings["longitude"])
        needed = kp_for_aurora(magnetic_latitude(*home)) if home != (0, 0) else None
        reasons = []
        if data.get("g", 0) >= 3:
            reasons.append(("storm", slot))
        if data.get("xrays") and data["xrays"][-1] >= 1e-4:
            reasons.append(("flare", slot))
        if needed is not None and data.get("kp", 0) >= needed:
            reasons.append(("aurora", slot))
        for reason in reasons:
            if reason not in self.alerted:
                self.alerted.add(reason)
                self.context.emit_event("space_weather", 30)
                break

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# --- the screen ------------------------------------------------------------------------------

class SpaceWeather(Module):
    name = "space_weather"
    event_priority = 22

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
        settings = context.config["plugins"][self.name]
        if not data:
            draw_text(frame, "Asking NOAA", 4, 12, GREY, mixed=True)
            return frame
        cards = []
        if "kp" in data:
            cards.append("kp")
        if "speed" in data:
            cards.append("wind")
        if data.get("xrays"):
            cards.append("xrays")
        if "kp" in data and tuple(data.get("home") or (0, 0)) != (0, 0):
            cards.append("aurora")

        def build(visit):
            return [(card, CARD) for card in cards]

        self.story.sync(context.animation_time, build, context.scene)
        current = self.story.current(context.animation_time, build)
        card, local = (current[0], current[1]) if current else (cards[0], 0)
        getattr(self, "_" + card)(frame, data, settings, context, local)
        return frame

    @staticmethod
    def _kp(frame, data, settings, context, local):
        kp = data["kp"]
        draw_tiny(frame, "KP INDEX", 0, 1, GREY)
        value = f"{kp:.1f}"
        draw_text(frame, value, 0, 9, kp_color(kp), scale=2, smooth=True)
        draw_tiny(frame, STORMS.get(data.get("g", 0), "STORM"), 0, 27, kp_color(kp))
        # The bars: three-hour Kp, yesterday to the day after tomorrow, forecast dimmer.
        ts = context.now.timestamp()
        bars = [bar for bar in data.get("bars", []) if ts - 86400 <= bar[0] < ts + 86400][:16]
        draw = ImageDraw.Draw(frame)
        left = 128 - len(bars) * 4
        grow = min(1.0, local / 1.2)
        for index, (at, value, observed) in enumerate(bars):
            x = left + index * 4
            height = max(1, round(value / 9 * 28 * grow))
            color = kp_color(value) if observed else tuple(round(c * .45) for c in kp_color(value))
            draw.rectangle((x, 31 - height, x + 2, 31), fill=color)
            if at <= ts < at + 10800:
                draw.line((x + 1, 0, x + 1, 1), fill=WHITE)

    @staticmethod
    def _wind(frame, data, settings, context, local):
        speed = data["speed"]
        rng = random.Random(7)
        pixels = frame.load()
        pace = speed / 400 * 30                    # pixels per second on the panel
        for index in range(46):
            y = rng.randint(0, 15)
            x = (rng.uniform(0, 160) + local * pace * rng.uniform(.8, 1.2)) % 160 - 16
            for tail in range(3):
                px = int(x) - tail
                if 0 <= px < 128:
                    pixels[px, y] = tuple(round(c * (1 - tail * .35)) for c in (255, 190, 80))
        draw_tiny(frame, "SOLAR WIND", 0, 18, GREY)
        value = f"{round(speed)}"
        draw_text(frame, value, 0, 25, AMBER)
        draw_tiny(frame, "KM/S", text_width(value) + 3, 27, AMBER)
        bz = data.get("bz")
        if bz is not None:
            south = bz < 0
            label = f"BZ {bz:+.0f} NT {'SOUTH' if south else 'NORTH'}"
            draw_tiny(frame, label, 128 - tiny_width(label), 18, RED if south and bz <= -5 else GREY)
            hint = "GOOD FOR AURORA" if south and bz <= -5 else "QUIET FIELD"
            draw_tiny(frame, hint, 128 - tiny_width(hint), 26, RED if south and bz <= -5 else GREY)

    @staticmethod
    def _xrays(frame, data, settings, context, local):
        flux = data["xrays"]
        current = flare_class(flux[-1])
        peak = flare_class(max(flux))
        draw = ImageDraw.Draw(frame)
        top, bottom = 2, 29
        low, high = -8, -3

        def y_of(value):
            level = (math.log10(max(value, 1e-9)) - low) / (high - low)
            return round(bottom - max(0, min(1, level)) * (bottom - top))

        for name, floor in CLASSES:
            y = y_of(floor)
            for x in range(0, 112, 3):
                frame.putpixel((x, y), (40, 44, 52))
            draw_tiny(frame, name, 116, y - 5 if y - 5 >= 0 else y, flare_color(name))
        shown = min(len(flux), round(local / 1.5 * len(flux)) + 1)
        points = []
        for index in range(shown):
            x = round(index / max(1, len(flux) - 1) * 111)
            points.append((x, y_of(flux[index])))
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            draw.line((x1, y1, x2, y2), fill=GOLD)
        draw_tiny(frame, "SUN X-RAYS 6H", 0, 0, GREY)
        label = f"NOW {current}"
        draw_tiny(frame, label, 0, 26, flare_color(current))
        label = f"PEAK {peak}"
        draw_tiny(frame, label, 110 - tiny_width(label), 26, flare_color(peak))

    @staticmethod
    def _aurora(frame, data, settings, context, local):
        mlat = magnetic_latitude(*data["home"])
        needed = kp_for_aurora(mlat)
        kp = data["kp"]
        ts = context.now.timestamp()
        ahead = [value for at, value, observed in data.get("bars", []) if ts <= at + 10800 and at <= ts + 86400]
        best = max(ahead, default=kp)
        draw_tiny(frame, "NORTHERN LIGHTS HERE", 0, 1, GREY)
        if needed is None:
            draw_text(frame, "Out of reach", 0, 9, GREY, mixed=True)
        elif kp >= needed:
            if int(local * 3) % 3:
                draw_text(frame, "POSSIBLE NOW", 0, 9, GREEN)
        elif best >= needed:
            draw_text(frame, "Maybe tonight", 0, 9, GOLD, mixed=True)
        else:
            draw_text(frame, f"Needs Kp {needed}", 0, 9, WHITE, mixed=True)
        line = f"NOW {kp:.1f}  NEXT 24H UP TO {best:.1f}"
        draw_tiny(frame, line, 0, 21, kp_color(best))
        draw_tiny(frame, f"YOU ARE AT {abs(mlat):.0f}° MAGNETIC", 0, 27, GREY)
        # A small sky: the oval's edge creeping down towards you.
        if needed is not None:
            draw = ImageDraw.Draw(frame)
            reach = min(1.0, kp / max(needed, .1))
            for x in range(96, 128):
                wave = math.sin(x * .5 + local * 2) * 1.5
                height = round(2 + reach * 10 + wave)
                for y in range(max(0, 12 - height), 12):
                    fade = (y - (12 - height)) / max(1, height)
                    frame.putpixel((x, y), (0, round(80 + 150 * fade * reach), round(60 * fade)))


plugin = Plugin(
    "space_weather", "Space weather", module=SpaceWeather, provider=Feed,
    defaults={"latitude": 0.0, "longitude": 0.0, "alert": True},
    help={"latitude": "Leave at 0 to use the home location from Settings (for the northern lights)",
          "alert": "Take over for a strong geomagnetic storm, an X-class flare, or aurora within your reach"},
    ui={"latitude": {"type": "location", "label": "Location"}, "longitude": {"advanced": True},
        "alert": {"label": "Take over for big events"}},
)
