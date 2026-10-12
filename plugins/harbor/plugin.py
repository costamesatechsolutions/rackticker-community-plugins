"""Harbor: the ships around you, live from their own radio beacons (AIS).

A radar picture of the water near home with a sweep going round: every ship a
dot in the colour of its kind, the ones under way with a wake pointing where they
are headed, the ones at anchor blinking slowly. Then how many are at anchor,
under way and alongside, and a card for each of the biggest: name, what it is,
how long, what it is doing and where it says it is going.

Needs a free key from aisstream.io (Settings → Harbor → AIS key).
"""
from __future__ import annotations

import asyncio
import json
import math
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, text_width, tiny_width

STREAM = "wss://stream.aisstream.io/v0/stream"
FORGET = 1800              # a ship not heard from for half an hour has gone (or switched off)
WHITE, GREY, AMBER, GOLD, RED, GREEN, CYAN, BLUE = ((236, 238, 236), (140, 146, 150), (255, 176, 40),
                                                    (255, 214, 60), (255, 60, 40), (90, 230, 120),
                                                    (60, 200, 255), (40, 110, 255))
RADAR, COUNTS, CARD = 12.0, 6.0, 6.0
NAME_REST, NAME_SPEED = 1.3, 18
AT_ANCHOR, MOORED = 1, 5


def kind(code):
    """(what the ship is, its colour) from its AIS type number."""
    code = int(code or 0)
    if 70 <= code <= 79:
        return "CARGO SHIP", AMBER
    if 80 <= code <= 89:
        return "TANKER", RED
    if 60 <= code <= 69:
        return "PASSENGER SHIP", WHITE
    if code in (31, 32, 52):
        return "TUG", GREEN
    if code == 30:
        return "FISHING BOAT", CYAN
    if code in (36, 37):
        return "SAILBOAT" if code == 36 else "PLEASURE BOAT", BLUE
    if code == 35:
        return "NAVY SHIP", (150, 160, 170)
    if code == 50:
        return "PILOT BOAT", GOLD
    if code in (51, 55):
        return "PATROL BOAT", GOLD
    return "SHIP", (210, 210, 215)


def tidy(name):
    name = " ".join(str(name or "").replace("@", " ").split())
    return " ".join(word.capitalize() if len(word) > 2 else word for word in name.split()) or "Unnamed"


def box(home, radius):
    """The patch of sea watched, centred on home: twice as wide as it is tall (drawn a little squashed
    on the 4:1 panel), so a port a dozen miles up the coast is still in it."""
    lat, lon = home
    half_lon = radius / max(10.0, 69 * math.cos(math.radians(lat)))
    half_lat = radius / 2 / 69
    return lat - half_lat, lon - half_lon, lat + half_lat, lon + half_lon


class Feed(Provider):
    """Keeps the AIS stream open in the background; each round hands over who is out there."""

    def __init__(self, context):
        self.context = context
        self.ships, self.task, self.key, self.problem = {}, None, None, None

    def _message(self, message):
        meta = message.get("MetaData") or {}
        mmsi = meta.get("MMSI")
        if not mmsi:
            return
        ship = self.ships.setdefault(mmsi, {"mmsi": mmsi, "type": 0, "length": 0, "destination": ""})
        ship["name"] = tidy(meta.get("ShipName")) if meta.get("ShipName", "").strip() else ship.get("name", "Unnamed")
        ship["seen"] = time.time()
        body = message.get("Message") or {}
        if message.get("MessageType") == "PositionReport":
            report = body.get("PositionReport") or {}
            ship.update(lat=float(report.get("Latitude", meta.get("latitude", 0))),
                        lon=float(report.get("Longitude", meta.get("longitude", 0))),
                        speed=float(report.get("Sog") or 0), course=float(report.get("Cog") or 0),
                        status=int(report.get("NavigationalStatus", 15)))
        elif message.get("MessageType") == "ShipStaticData":
            static = body.get("ShipStaticData") or {}
            size = static.get("Dimension") or {}
            ship.update(type=int(static.get("Type") or 0),
                        length=int((size.get("A") or 0) + (size.get("B") or 0)),
                        destination=" ".join(str(static.get("Destination") or "").split()))

    async def _stream(self, key, area):
        wait = 5
        while True:
            try:
                async with aiohttp.ClientSession(headers={"User-Agent": "RackTicker harbor plugin"}) as session:
                    async with session.ws_connect(STREAM, heartbeat=30, timeout=15) as ws:
                        south, west, north, east = area
                        await ws.send_str(json.dumps({"APIKey": key, "BoundingBoxes": [[[south, west], [north, east]]],
                                                      "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}))
                        async for message in ws:
                            if message.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                                break
                            data = json.loads(message.data)
                            if "error" in data:
                                self.problem = str(data["error"])
                                break
                            self.problem = None
                            wait = 5
                            self._message(data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.problem = type(exc).__name__
            await asyncio.sleep(wait)
            wait = min(300, wait * 2)

    async def fetch(self):
        settings = self.context.settings
        home = (settings["latitude"], settings["longitude"])
        if not settings["api_key"]:
            raise ValueError("Add your free aisstream.io key in Settings")
        if home == (0, 0):
            raise ValueError("Set your home location in Settings")
        area = box(home, settings["radius_miles"])
        key = (settings["api_key"], area)
        if key != self.key or self.task is None or self.task.done():
            if self.task is not None:
                self.task.cancel()
            self.ships, self.key = {}, key
            self.task = asyncio.ensure_future(self._stream(settings["api_key"], area))
        cutoff = time.time() - FORGET
        for mmsi in [mmsi for mmsi, ship in self.ships.items() if ship["seen"] < cutoff]:
            del self.ships[mmsi]
        ships = [dict(ship) for ship in self.ships.values() if "lat" in ship]
        if not ships and self.problem:
            raise ValueError(f"AIS stream: {self.problem}")
        return Snapshot({"ships": ships, "area": area, "home": home})

    async def close(self):
        if self.task is not None:
            self.task.cancel()


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


def doing(ship):
    if ship.get("status") == AT_ANCHOR:
        return "AT ANCHOR"
    if ship.get("status") == MOORED or ship.get("speed", 0) < .5:
        return "ALONGSIDE" if ship.get("status") == MOORED else "STOPPED"
    return f"UNDER WAY {ship['speed']:.0f} KN"


class Harbor(Module):
    name = "harbor"

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _data(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data and snap.data.get("ships") else None

    def available(self, context):
        return self._data(context) is not None

    def hold(self, context):
        return self.story.hold()

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        data = self._data(context)
        if data is None:
            draw_text(frame, "Listening for ships", 0, 12, GREY, mixed=True)
            return frame
        ships = data["ships"]
        big = sorted((ship for ship in ships if ship.get("length")), key=lambda ship: -ship["length"])[:4]
        if len(big) < 4:   # sizes come in a few minutes after the positions; meanwhile, the ones moving
            big += sorted((ship for ship in ships if not ship.get("length") and ship.get("speed", 0) >= .5),
                          key=lambda ship: -ship["speed"])[:4 - len(big)]

        def build(visit):
            return [("radar", RADAR), ("counts", COUNTS)] + [(ship["mmsi"], CARD) for ship in big]

        self.story.sync(context.animation_time, build, context.scene)
        card, local, _ = self.story.current(context.animation_time, build) or ("radar", 0, 0)
        if card == "radar":
            self._radar(frame, data, local, context.animation_time)
        elif card == "counts":
            self._counts(frame, ships)
        else:
            ship = next((ship for ship in ships if ship["mmsi"] == card), None)
            if ship is None:
                self._counts(frame, ships)
            else:
                self._ship(frame, ship, local)
        return frame

    @staticmethod
    def _radar(frame, data, local, t):
        south, west, north, east = data["area"]
        draw = ImageDraw.Draw(frame)
        pixels = frame.load()

        def xy(lat, lon):
            return (lon - west) / (east - west) * 127, (north - lat) / (north - south) * 31

        hx, hy = xy(*data["home"])
        # The sweep: a line turning round home, leaving a fading green glow behind it.
        angle = t * 1.4
        for back in range(10):
            a = angle - back * .06
            level = 1 - back / 10
            for r in range(4, 140, 3):
                x, y = hx + math.cos(a) * r, hy + math.sin(a) * r * .25
                if 0 <= x < 128 and 0 <= y < 32:
                    pixels[int(x), int(y)] = (0, round(70 * level), round(20 * level))
        for ship in sorted(data["ships"], key=lambda ship: ship.get("length", 0)):
            x, y = xy(ship["lat"], ship["lon"])
            if not (0 <= x < 128 and 0 <= y < 32):
                continue
            _, color = kind(ship.get("type"))
            if ship.get("speed", 0) >= .5:
                rad = math.radians(ship.get("course", 0))
                for step in range(1, 4):           # the wake, behind it
                    wx, wy = x - math.sin(rad) * step, y + math.cos(rad) * step * .25
                    if 0 <= wx < 128 and 0 <= wy < 32:
                        pixels[int(wx), int(wy)] = tuple(round(c * (.5 - step * .12)) for c in color)
                pixels[int(x), int(y)] = color
            else:
                anchored = ship.get("status") == AT_ANCHOR
                level = (.55 + .45 * math.sin(t * 2 + ship["mmsi"] % 7)) if anchored else .8
                pixels[int(x), int(y)] = tuple(round(c * level) for c in color)
        if 0 <= hx < 128 and 0 <= hy < 32 and int(t * 2) % 2:
            pixels[int(hx), int(hy)] = RED
        # The count goes in whichever corner has the fewest ships under it (usually over land).
        label = f"{len(data['ships'])} SHIPS"
        width = tiny_width(label) + 2
        spots = [(0, 0), (128 - width, 0), (0, 25), (128 - width, 25)]
        places = [xy(ship["lat"], ship["lon"]) for ship in data["ships"]]
        lx, ly = min(spots, key=lambda spot: sum(1 for x, y in places
                                                 if spot[0] - 1 <= x <= spot[0] + width and spot[1] - 1 <= y <= spot[1] + 7))
        draw.rectangle((lx, ly, lx + width - 1, ly + 6), fill=(0, 0, 0))
        draw_tiny(frame, label, lx + 1, ly + 1, WHITE)

    @staticmethod
    def _counts(frame, ships):
        anchored = sum(1 for ship in ships if ship.get("status") == AT_ANCHOR)
        moving = sum(1 for ship in ships if ship.get("status") != AT_ANCHOR and ship.get("speed", 0) >= .5)
        still = len(ships) - anchored - moving
        for column, (count, label, color) in enumerate(((anchored, "AT ANCHOR", AMBER), (moving, "UNDER WAY", GREEN),
                                                        (still, "STOPPED", CYAN))):
            x = column * 43
            text = str(count)
            draw_text(frame, text, x + (40 - text_width(text, 2)) // 2, 3, color, scale=2, smooth=True)
            draw_tiny(frame, label, x + (40 - tiny_width(label)) // 2, 23, GREY)

    @staticmethod
    def _ship(frame, ship, local):
        what, color = kind(ship.get("type"))
        draw = ImageDraw.Draw(frame)
        # A hull to scale: the longest ships fill the bar.
        length = ship.get("length", 0)
        if length:
            hull = max(8, min(126, round(length / 400 * 126)))
            draw.polygon(((1, 28), (hull - 3, 28), (hull, 26), (1, 26)), fill=color)
            draw.rectangle((max(1, hull - 12), 24, max(4, hull - 8), 25), fill=WHITE)
        fitted(frame, ship.get("name", "Unnamed"), 0, 0, 128, WHITE, local)
        draw_tiny(frame, what, 0, 11, color)
        if length:
            size = f"{length} M LONG"
            draw_tiny(frame, size, 128 - tiny_width(size), 11, GREY)
        status = doing(ship)
        draw_tiny(frame, status, 0, 18, AMBER if status == "AT ANCHOR" else GREEN if "UNDER" in status else CYAN)
        if ship.get("destination"):
            going = f"TO {ship['destination'].upper()}"
            if tiny_width(status) + tiny_width(going) + 6 <= 128:
                draw_tiny(frame, going, 128 - tiny_width(going), 18, GREY)


def validate_settings(settings):
    if not 2 <= float(settings.get("radius_miles", 20)) <= 100:
        raise ValueError("radius_miles must be 2 to 100")
    return settings


plugin = Plugin(
    "harbor", "Harbor", module=Harbor, provider=Feed,
    defaults={"api_key": "", "latitude": 0.0, "longitude": 0.0, "radius_miles": 20},
    validate_settings=validate_settings,
    help={"api_key": "A free key from aisstream.io (sign in with GitHub, then API Keys)",
          "latitude": "Leave at 0 to use the home location from Settings",
          "radius_miles": "How far east and west of home to watch; north and south is half that"},
    ui={"api_key": {"type": "secret", "label": "AIS key"},
        "latitude": {"type": "location", "label": "Location"}, "longitude": {"advanced": True},
        "radius_miles": {"type": "slider", "min": 2, "max": 100, "step": 1, "unit": "mi", "label": "Watch within"}},
)
