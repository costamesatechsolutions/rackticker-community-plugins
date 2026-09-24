"""Virtual Aquarium: a small planted world, optionally reflecting a real tank."""
from datetime import datetime, timezone
import json
import hashlib
import math
from urllib.parse import urlsplit

import aiohttp
from PIL import ImageDraw
from rackticker import Module, Plugin, Provider, Snapshot, draw_text, new_frame

NAME = "virtual_aquarium"
DEFAULTS = {"habitat": "reef", "fish_count": 7, "lighting": "day", "speed": 1.0,
            "bubbles": True, "show_readings": True, "tank_url": "", "tank_token": ""}


def validate(settings):
    for key, low, high in (("fish_count", 1, 12), ("speed", .25, 2.0)):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
    if int(settings["fish_count"]) != settings["fish_count"]:
        raise ValueError("fish_count must be a whole number")
    for key, options in (("habitat", ("reef", "planted")), ("lighting", ("day", "night", "cycle"))):
        if settings[key] not in options:
            raise ValueError(f"Invalid {key}")
    url = urlsplit(settings["tank_url"])
    if settings["tank_url"] and (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.fragment):
        raise ValueError("tank_url must be an HTTP(S) URL without embedded credentials or a fragment")


def parse_readings(raw, now):
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Tank feed must be a JSON object")
    stamp = datetime.fromisoformat(str(payload.get("updated_at", "")).replace("Z", "+00:00"))
    if stamp.tzinfo is None or (stamp - now).total_seconds() > 30:
        raise ValueError("updated_at must include a timezone and must not be in the future")
    data = {}
    for key, low, high in (("temperature_c", -5, 50), ("ph", 0, 14)):
        value = payload.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Invalid {key}")
            data[key] = float(value)
    if "light_on" in payload:
        if not isinstance(payload["light_on"], bool):
            raise ValueError("light_on must be boolean")
        data["light_on"] = payload["light_on"]
    if not data:
        raise ValueError("Tank feed has no supported readings")
    return Snapshot(data, updated_at=stamp, stale=(now - stamp).total_seconds() > 30, source="tank")


def endpoint_id(settings):
    return hashlib.sha256(settings["tank_url"].encode()).hexdigest()


class Tank(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None

    async def fetch(self):
        settings = self.context.settings
        if not settings["tank_url"]:
            return Snapshot({}, source="simulation")
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4))
        headers = {"Authorization": "Bearer " + settings["tank_token"]} if settings["tank_token"] else {}
        async with self.session.get(settings["tank_url"], headers=headers, allow_redirects=False) as response:
            if response.status != 200:
                raise ValueError("Tank feed did not return HTTP 200")
            raw = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                raw.extend(chunk)
                if len(raw) > 16384:
                    raise ValueError("Tank feed exceeds 16 KiB")
        snapshot = parse_readings(raw, datetime.now(timezone.utc))
        snapshot.metadata["endpoint"] = endpoint_id(settings)
        return snapshot

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


def fish(draw, x, y, direction, color, species, phase):
    """Hand-drawn silhouettes: striped clownfish, tall angelfish, neon tetras."""
    def point(a, b):
        return round(x + a * direction), round(y + b)
    def polygon(points, fill):
        draw.polygon([point(a, b) for a, b in points], fill=fill)
    tail = 1 if math.sin(phase) > 0 else 2
    polygon([(-4, 0), (-7, -tail), (-7, tail)], color)
    if species == 1:
        polygon([(-3, 0), (-1, -5), (2, -1), (4, 0), (1, 3), (-1, 5)], color)
        draw.line([point(0, -2), point(0, 3)], fill=(0, 80, 160))
    else:
        polygon([(-4, -1), (-2, -2), (2, -2), (4, 0), (2, 2), (-2, 2), (-4, 1)], color)
        if species == 0:
            for stripe in (-2, 1):
                draw.line([point(stripe, -1), point(stripe, 1)], fill=(245, 245, 210))
        else:
            draw.line([point(-3, 0), point(2, 0)], fill=(0, 220, 255))
    draw.point(point(2, -1), fill=(0, 0, 0))
    draw.point(point(3, 0), fill=(240, 240, 200))


class Aquarium(Module):
    name = NAME

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def render(self, context):
        settings = context.config["plugins"][NAME]
        t = context.animation_time
        snap = context.snapshots.get(NAME)
        connected = bool(settings["tank_url"])
        # A changed/removed endpoint must never present an offline snapshot as live.
        has_data = connected and snap is not None and snap.source == "tank" and snap.metadata.get("endpoint") == endpoint_id(settings) and bool(snap.data)
        stale = bool(has_data and (snap.stale or (context.now - snap.updated_at).total_seconds() > 30))
        data = snap.data if has_data else {}
        night = settings["lighting"] == "night"
        if settings["lighting"] == "cycle":
            night = t % 120 >= 80
        if has_data and not stale and "light_on" in data:
            night = not data["light_on"]
        brightness = .48 if night else 1.0
        def lit(color):
            return tuple(round(channel * brightness) for channel in color)
        frame = new_frame()
        draw = ImageDraw.Draw(frame)
        for y in range(29):
            draw.line((0, y, 127, y), fill=lit((0, max(3, 22 - y // 2), max(10, 65 - y))))
        # Wandering shafts of light and short surface glints.
        for i in range(5):
            x = int((i * 31 + math.sin(t * .23 + i) * 5) % 150) - 12
            draw.line((x, 2, x + 12, 27), fill=lit((0, 35, 76)))
        for x in range(128):
            y = 1 + round(math.sin(x * .16 + t * .8))
            if (x + int(t * 3)) % 19 < 10:
                draw.point((x, y), fill=lit((0, 125, 200)))
        draw.rectangle((0, 29, 127, 31), fill=lit((88, 57, 0)))
        for i in range(45):
            draw.point(((i * 37) % 128, 29 + i % 3), fill=lit((160, 105, 0)))
        # Rock arch with an open swim-through.
        draw.polygon([(77, 29), (79, 22), (83, 20), (91, 20), (96, 25), (97, 29)], fill=lit((0, 80, 100)))
        draw.rectangle((84, 24, 90, 29), fill=lit((0, 10, 45)))
        draw.line((81, 22, 90, 21), fill=lit((0, 130, 140)))
        for base, height in ((5, 17), (12, 12), (21, 9), (106, 12), (116, 20), (124, 15)):
            for branch in (-1, 0, 1):
                points = []
                for row in range(height):
                    sway = math.sin(t * .8 + base * .1 + row * .16) * row / 8
                    points.append((round(base + branch * row / 7 + sway), 29 - row))
                draw.line(points, fill=lit((0, 170 if branch == 0 else 100, 40)), width=1)
                for row in range(4, height, 5):
                    px, py = points[row]
                    draw.line((px, py, px + (2 if row % 2 else -2), py - 2), fill=lit((40, 200, 0)))
        if settings["habitat"] == "reef":
            for base in (30, 65):
                for i in range(5):
                    x = base + i * 2
                    top = 25 - i % 3 * 2
                    draw.line((base + 4, 29, x, top), fill=lit((255, 80, 0)))
                    draw.point((x, top - 1), fill=lit((255, 170, 0)))
        if settings["bubbles"]:
            for i in range(9):
                y = 28 - (t * (3 + i % 3) + i * 3.1) % 27
                x = 100 + math.sin(t * 1.3 + i * 2) * 2
                if i % 3 == 0:
                    draw.ellipse((round(x), round(y), round(x) + 2, round(y) + 2), outline=lit((0, 160, 220)))
                else:
                    draw.point((round(x), round(y)), fill=lit((0, 190, 235)))
        # Each visit picks the fish up somewhere else along their paths: starting from the
        # same moment every time, the tank played the same few seconds on every visit.
        drift = (getattr(context, "scene", 0) or 0) * 37.7 % 600
        motion = (t + drift) * settings["speed"] * (.55 if night else 1)
        for i in range(int(settings["fish_count"])):
            # Smooth turns at the glass: no sudden wrapping across the tank.
            phase = motion * (.13 + (i % 3) * .025) + i * 2.399
            x = 64 + 51 * math.sin(phase)
            direction = 1 if math.cos(phase) >= 0 else -1
            # Spread through the water: "8 + i * 7 % 14" put every fish on one of two
            # rows, so they kept swimming through one another.
            y = 6 + (i * 11 % 17) + math.sin(motion * .8 + i) * 1.5
            species = i % 3 if settings["habitat"] == "reef" else (1 if i == 0 else 2)
            color = ((255, 100, 0), (255, 210, 0), (0, 95, 240))[species]
            fish(draw, x, y, direction, lit(color), species, motion * 7 + i)
        # A tiny bottom-dwelling snail, with feelers and a spiral shell.
        sx = round(43 + 8 * math.sin(t * .04))
        draw.line((sx - 3, 28, sx + 3, 28), fill=lit((180, 150, 0)))
        draw.ellipse((sx - 2, 24, sx + 2, 28), fill=lit((230, 125, 0)))
        draw.point((sx, 26), fill=(65, 30, 0))
        draw.point((sx + 3, 27), fill=lit((240, 210, 0)))
        # Readouts visit briefly; the aquarium gets most of the screen time.
        if connected and (not has_data or stale):
            draw.rectangle((0, 0, 77, 8), fill=(0, 0, 0))
            draw_text(frame, "STALE" if has_data else "NO DATA", 2, 1, (255, 150, 0))
        elif connected and settings["show_readings"] and t % 16 < 5:
            readings = []
            if "temperature_c" in data:
                readings.append(f'{data["temperature_c"]:.1f}C')
            if "ph" in data:
                readings.append(f'PH {data["ph"]:.1f}')
            if readings:
                label = readings[int(t // 16) % len(readings)]
                draw.rectangle((0, 0, len(label) * 6 + 3, 8), fill=(0, 0, 0))
                draw_text(frame, label, 2, 1, (0, 230, 220))
        return frame


plugin = Plugin(NAME, "Virtual Aquarium", module=Aquarium, provider=Tank,
    defaults=DEFAULTS, validate_settings=validate,
    choices={"habitat": ("reef", "planted"), "lighting": ("day", "night", "cycle")},
    help={"tank_url": "Optional read-only JSON endpoint: updated_at, temperature_c, ph, light_on. Blank means offline aquarium.",
          "tank_token": "Optional bearer token for your tank bridge. Use HTTPS when sending a token.",
          "lighting": "Cycle is an artistic 120-second day/night loop. Fresh tank light_on overrides it.",
          "show_readings": "Show real tank values briefly every 16 seconds; stale data is always marked."},
    ui={"fish_count": {"type": "slider", "min": 1, "max": 12, "step": 1},
        "speed": {"type": "slider", "min": .25, "max": 2, "step": .25},
        "tank_token": {"type": "secret"}, "tank_url": {"advanced": True}})
