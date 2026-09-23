"""Onboard: the display above the carriage doors, for a train that is really running.

It says what the display above a train's doors says: the stop the train is coming to,
when it gets there, whether it is running to time, and a line from the last stop to
the next with the train on it. The train is a real one, from Amtrak's live feed through
the key-free Amtraker API.

Where the train is on that line comes from where the train actually is (its position
against the two stations' positions), not from the timetable, so it only ever moves
forward, and it moves smoothly: the bar and the train are drawn to a fraction of a
pixel, because a train covers a pixel of this line in minutes.

Pick a route, or a train number, or name a station and it rides whichever train is
out there serving it. Give it a home location and it picks the nearest one.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import math
import re
import time

import aiohttp

from rackticker import (AMBER, GREEN, MUTED, RED, WHITE, Module, Plugin, Provider, Snapshot, draw_text,
                        draw_tiny, new_frame, offload, text_width, tiny_width)

API = "https://api-v3.amtraker.com/v3"
UA = {"User-Agent": "RackTicker onboard (+https://github.com/costamesatechsolutions/rackticker)"}
TRACK = (52, 58, 64)
BODY, LAMP = (238, 240, 238), (255, 226, 90)
WHEEL, WINDOW = (86, 92, 100), (26, 30, 36)
WINDOWS = {2, 5}   # dx positions in the body row that read as windows, not fuzz
# Routes worth riding when you have no particular train in mind: (name in the feed, train numbers,
# a station every train of the route calls at). A route with a hub asks the feed which trains
# serve it instead of guessing numbers, because a busy corridor has dozens of them.
ROUTES = {
    "coast_starlight": ("Coast Starlight", (11, 14), ""),
    "california_zephyr": ("California Zephyr", (5, 6), ""),
    "empire_builder": ("Empire Builder", (7, 8, 27, 28), ""),
    "southwest_chief": ("Southwest Chief", (3, 4), ""),
    "sunset_limited": ("Sunset Limited", (1, 2), ""),
    "texas_eagle": ("Texas Eagle", (21, 22), ""),
    "lake_shore_limited": ("Lake Shore Limited", (48, 49), ""),
    "crescent": ("Crescent", (19, 20), ""),
    "silver_star": ("", (91, 92, 97, 98), ""),
    "auto_train": ("Auto Train", (52, 53), ""),
    "cardinal": ("Cardinal", (50, 51), ""),
    "city_of_new_orleans": ("City of New Orleans", (58, 59), ""),
    "adirondack": ("Adirondack", (68, 69), ""),
    "pacific_surfliner": ("Pacific Surfliner", (), "SNA"),
    "capitol_corridor": ("Capitol Corridor", (), "SAC"),
    "amtrak_cascades": ("Amtrak Cascades", (), "SEA"),
    "acela": ("Acela", (), "NYP"),
}
TRIM = (" Amtrak Station", " Transportation Center", " Santa Fe Depot", " Union Station", " Union",
        " Penn Station", " King Street", " Station")
MAX_TRAINS = 10             # requests per refresh
STOPPED_MPH = 3             # slower than this and the train is standing still
LEFT, RIGHT = 3, 124        # the line, end to end
CLOSE = 3                   # a train this many minutes from a stop is "arriving"
MAX_AGE = 20 * 60           # a picture of the train older than this is not shown as live
FIX_MAX_AGE = 2 * 3600      # a train not heard from for this long is not one to ride
DEAD_RECKON = 5 * 60        # and it is only carried forward this long between pictures
# Pixels of the train, nose to the right: roof, body, wheels. Two wheel patterns turn over.
TRAIN = (".######.",
         "########",
         "#.####.#")
WHEELS = ("#.####.#", ".#.##.#.")


def short(name):
    """A stop's name as the display has room for it."""
    name = str(name or "").split(",")[0].strip()
    for tail in TRIM:
        if name.endswith(tail) and len(name) > len(tail) + 2:
            name = name[: -len(tail)]
            break
    return name.replace("-", " ").strip()


def _moment(value):
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def _clock(moment):
    """8:07P: the time of day at the stop, as the stop's own clock reads it."""
    return f"{moment.hour % 12 or 12}:{moment.minute:02d}{'A' if moment.hour < 12 else 'P'}" if moment else ""


def _epoch(moment):
    return moment.timestamp() if moment else None


def miles(a, b):
    """Great-circle distance in miles between two (lat, lon) points."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(min(1.0, math.sqrt(h)))


def station_coords(body):
    """{code: (lat, lon)} from the feed's list of every station (large: parsed off the render loop)."""
    found = {}
    for code, station in (json.loads(body) or {}).items():
        try:
            found[str(code)] = (float(station["lat"]), float(station["lon"]))
        except (KeyError, TypeError, ValueError):
            continue
    return found


def journey(run, coords=None):
    """One train run as the display needs it, or None if it has no stops to speak of.

    Amtraker marks a stop 'Departed' once the train has left it, 'Enroute' while it is
    still ahead and 'Station' while the train is standing at it. It also says 'Station',
    with no times at all, for stops it never heard about before the train reached them, so
    the stop the train is heading for is the one after the last that says 'Departed'."""
    stops = []
    for raw in run.get("stations") or []:
        if raw.get("bus"):
            continue                                    # a connecting bus is not the train's line
        arrive = _moment(raw.get("arr") or raw.get("schArr") or raw.get("dep") or raw.get("schDep"))
        leave = _moment(raw.get("dep") or raw.get("schDep") or raw.get("arr") or raw.get("schArr"))
        planned = _moment(raw.get("schArr") or raw.get("schDep"))
        planned_leave = _moment(raw.get("schDep") or raw.get("schArr"))
        status = str(raw.get("status") or "").lower()
        where = (coords or {}).get(str(raw.get("code") or ""))
        stops.append({"code": str(raw.get("code") or ""), "name": short(raw.get("name")),
                      "arrive": _epoch(arrive), "leave": _epoch(leave), "planned": _epoch(planned),
                      "planned_leave": _epoch(planned_leave), "clock": _clock(arrive), "leave_clock": _clock(leave),
                      "done": status == "departed", "here": status == "station" and bool(raw.get("arr")),
                      "at": where})
    if not stops:
        return None
    speed = max(0.0, _number(run.get("velocity")))
    departed = max((index for index, stop in enumerate(stops) if stop["done"]), default=-1)
    if departed == len(stops) - 1:
        return None                                     # it has been to the end of the line
    ahead = departed + 1
    # 'Station' that the train is speeding away from is the feed being a few minutes behind.
    here = stops[ahead]["here"] and speed < 15
    if stops[ahead]["here"] and not here and ahead < len(stops) - 1:
        ahead += 1
    stop = stops[ahead]
    behind = stops[ahead - 1] if ahead else None
    position = None
    lat, lon = _number(run.get("lat"), None), _number(run.get("lon"), None)
    if lat is not None and lon is not None:
        position = (lat, lon)
    if here:
        wanted, planned = stop["leave"], stop["planned_leave"]
    else:
        wanted, planned = stop["arrive"], stop["planned"]
    late = round((wanted - planned) / 60) if wanted and planned else 0
    ride = {"route": str(run.get("routeName") or ""), "number": str(run.get("trainNum") or ""),
            "origin": short(run.get("origName")), "to": short(run.get("destName")),
            "stops": stops, "next": ahead, "here": here, "late": late, "speed": round(speed),
            "moving": speed >= STOPPED_MPH, "position": position, "arrive": wanted,
            "behind": behind["leave"] if behind else None,
            "left": len(stops) - ahead - 1, "geo": False, "p0": 0.0, "leg": 0.0}
    # Where the train is between the two stops, by where it is. A train that is nowhere near
    # the straight line between them (a stale fix, a stop the feed skipped) falls back to the clock.
    if behind and behind["at"] and stop["at"] and position and not here:
        back, front, leg = miles(behind["at"], position), miles(position, stop["at"]), miles(behind["at"], stop["at"])
        if leg >= 1 and back + front <= leg * 1.6 + 15:
            ride.update(geo=True, p0=back / (back + front) if back + front else 0.0, leg=leg)
    return ride


def live(run, now=None):
    """A run that is out on the line and whose position the feed has heard recently. A run whose
    last fix is hours old is a train that lost its tracker, not one to watch."""
    if run.get("trainState") != "Active":
        return False
    fix = _moment(run.get("lastValTS"))
    return fix is None or (now or time.time()) - fix.timestamp() < FIX_MAX_AGE


def _number(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def progress(ride, now, asof):
    """How far along the last-stop-to-next-stop line the train is, 0 to 1, at time `now`."""
    if ride["here"]:
        return 1.0
    if ride["geo"]:
        # The train has moved on since the feed last said where it was.
        moved = ride["speed"] * min(max(0.0, now - asof), DEAD_RECKON) / 3600 / ride["leg"]
        return max(0.0, min(.985, ride["p0"] + moved))
    behind, arrive = ride.get("behind"), ride.get("arrive")
    if behind and arrive and arrive > behind:
        return max(0.0, min(.985, (now - behind) / (arrive - behind)))
    return 0.0


def minutes_to(ride, now):
    """Whole minutes until the train reaches the stop (or leaves it), from the clock now."""
    if not ride.get("arrive"):
        return None
    return max(0, math.ceil((ride["arrive"] - now) / 60))


def verdict(late):
    """How the train is running, in words and the colour to say them in."""
    if late >= 20:
        return f"{late}M LATE", RED
    if late >= 5:
        return f"{late}M LATE", AMBER
    if late <= -5:
        return f"{-late}M EARLY", GREEN
    return "ON TIME", GREEN


def duration(minutes):
    return f"{minutes}M" if minutes < 60 else f"{minutes // 60}H{minutes % 60:02d}M"


def nearest(rides, home):
    """The train closest to home if we know where home is; otherwise the one with furthest to go."""
    if home:
        located = [ride for ride in rides if ride["position"]]
        if located:
            return min(located, key=lambda ride: miles(home, ride["position"]))
    return max(rides, key=lambda ride: ride["left"])


class Onboard(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.coords = {}
        self.coords_until = 0.0
        self.data = None
        self.cache_until = 0.0

    async def _json(self, url):
        async with self.session.get(url, headers=UA) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def _trains(self):
        """(route name to keep or "", the train numbers to look at) from the settings."""
        settings = self.context.settings
        chosen = str(settings.get("train") or "").strip()
        if chosen in ROUTES:
            route, numbers, hub = ROUTES[chosen]
            if hub:
                numbers = await self._serving(hub)
            return route, [str(number) for number in numbers][:MAX_TRAINS]
        if re.fullmatch(r"\d{1,4}", chosen):
            return "", [chosen]
        station = str(settings.get("station") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{3}", station):
            return "", (await self._serving(station))[:MAX_TRAINS]
        return ROUTES["coast_starlight"][0], [str(number) for number in ROUTES["coast_starlight"][1]]

    async def _serving(self, station):
        payload = await self._json(f"{API}/stations/{station}")
        seen = []
        for train_id in ((payload or {}).get(station) or {}).get("trains") or []:
            number = str(train_id).split("-")[0]
            if number and number not in seen:
                seen.append(number)
        return seen

    async def _stations(self):
        """Where every station is, once a day."""
        if self.coords and time.monotonic() < self.coords_until:
            return self.coords
        try:
            async with self.session.get(f"{API}/stations", headers=UA) as response:
                response.raise_for_status()
                self.coords = await offload(station_coords, await response.text())
            self.coords_until = time.monotonic() + 24 * 3600
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            self.coords_until = time.monotonic() + 600      # try again in ten minutes; the clock will do meanwhile
        return self.coords

    def _home(self):
        settings = self.context.settings
        lat, lon = _number(settings.get("latitude")), _number(settings.get("longitude"))
        return (lat, lon) if lat or lon else None

    async def fetch(self):
        now = time.monotonic()
        if self.data is not None and now < self.cache_until:
            return Snapshot(self.data, source="amtraker")
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        route, numbers = await self._trains()
        if not numbers:
            raise ValueError("Name a route, a train number or a station code")

        async def one(number):
            try:
                return await self._json(f"{API}/trains/{number}")
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                return None

        answers = await asyncio.gather(*(one(number) for number in numbers))
        if all(answer is None for answer in answers):
            raise ConnectionError("Amtraker did not answer")
        coords = await self._stations()
        rides = []
        for payload in answers:
            for runs in (payload or {}).values():
                for run in runs if isinstance(runs, list) else []:
                    if route and run.get("routeName") != route:
                        continue
                    ride = journey(run, coords) if live(run) else None
                    if ride:
                        rides.append(ride)
        ride = nearest(rides, self._home()) if rides else None
        # Nothing running is an ordinary answer, not an error: the screen just is not on offer.
        self.data = {"ride": ride, "asof": time.time(), "running": len(rides)}
        self.cache_until = now + max(20.0, float(self.context.settings.get("refresh_seconds") or 60))
        return Snapshot(self.data, source="amtraker")

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


def blend(frame, x, y, color, weight):
    """Add light to one pixel: fractions of pixels are drawn as fractions of brightness."""
    x, y = int(x), int(y)
    if weight <= 0 or not (0 <= x < 128 and 0 <= y < 32):
        return
    old = frame.getpixel((x, y))
    frame.putpixel((x, y), tuple(min(255, round(old[i] + color[i] * min(1.0, weight))) for i in range(3)))


class Carriage(Module):
    name = "onboard"

    def __init__(self):
        self.key = None                 # which train and which stop the bar belongs to
        self.shown = 0.0                # how far along it is drawn: only ever forwards
        self.shown_at = None

    def refresh_interval(self, context):
        return 0.25

    def _ride(self, context):
        snap = context.snapshots.get(self.name)
        data = snap.data if snap and isinstance(snap.data, dict) else None
        ride = data.get("ride") if data else None
        if not ride or context.now.timestamp() - data["asof"] > MAX_AGE:
            return None, None, snap
        return ride, data["asof"], snap

    def available(self, context):
        return self._ride(context)[0] is not None

    def render(self, context):
        frame = new_frame()
        ride, asof, snap = self._ride(context)
        if ride is None:
            draw_text(frame, "Onboard", 2, 12, MUTED, mixed=True)
            return frame
        now = context.now.timestamp()
        text, colour = verdict(ride["late"])
        self._header(frame, ride, text, colour, snap.stale)
        self._headline(frame, ride)
        self._details(frame, ride, now, context.animation_time)
        self._line(frame, ride, self._smooth(ride, progress(ride, now, asof), now), colour,
                   context.animation_time)
        return frame

    def _smooth(self, ride, target, now):
        """The bar only ever goes forwards. New pictures of the train move the target a little
        either way; the bar takes the larger, and only gives ground if it was well out."""
        key = (ride["number"], ride["next"], ride["here"])
        if key != self.key or self.shown_at is None:
            self.key, self.shown = key, target
        elif target >= self.shown:
            self.shown = target
        elif self.shown - target > .05:
            self.shown = max(target, self.shown - .01 * max(0.0, now - self.shown_at))
        self.shown_at = now
        return self.shown

    @staticmethod
    def _header(frame, ride, verdict_text, colour, stale):
        """The line you are on, where it is finally headed, and whether it is running to
        time. Naming the destination here is what tells the strip map below it apart from
        the route: the bar only ever runs from the last stop to the next one, and without
        the actual destination written down, that next stop looks like the end of the
        line, even mid-route."""
        status = "OFFLINE" if stale else verdict_text
        room = 128 - tiny_width(status) - 6
        to = ride["to"]
        to_titles = (f"{ride['route']} {ride['number']} TO {to}", f"{ride['number']} TO {to}", f"TO {to}") if to else ()
        for title in to_titles + (f"{ride['route']} {ride['number']}", ride["route"], f"TRAIN {ride['number']}"):
            title = title.strip().upper()
            if title and tiny_width(title) <= room:
                draw_tiny(frame, title, 1, 0, AMBER)
                break
        draw_tiny(frame, status, 127 - tiny_width(status), 0, MUTED if stale else colour)

    @staticmethod
    def _headline(frame, ride):
        """The stop it is coming to, as big as it will go."""
        name = ride["stops"][ride["next"]]["name"]
        if ride["here"]:
            name = f"AT {name}" if text_width(f"AT {name.upper()}", 2) <= 126 else name
        upper = name.upper()
        if text_width(upper, 2) <= 126:
            draw_text(frame, upper, 1, 6, WHITE, 2, True)
            return
        # Too long to say at full size without cutting it: the same words, smaller, in lower case.
        while name and text_width(name, 1, True) > 126:
            name = name[:-1].rstrip()
        draw_text(frame, name, 1, 9, WHITE, 1, False, mixed=True)

    @staticmethod
    def _details(frame, ride, now, t):
        """When it gets there, how long that is, how fast it is going."""
        left = minutes_to(ride, now)
        stop = ride["stops"][ride["next"]]
        if ride["here"]:
            first, middle = ("AT STATION", GREEN), (f"DEP {stop['leave_clock']}" if stop["leave_clock"] else "", WHITE)
        else:
            soon = left is not None and left <= CLOSE
            first = ("ARRIVING" if soon else f"IN {duration(left)}" if left is not None else "", GREEN if not soon or int(t * 2) % 2 == 0 else WHITE)
            middle = (f"ARR {stop['clock']}" if stop["clock"] else "", WHITE)
        if ride["left"] == 0 and not ride["here"]:
            last = ("LAST STOP", AMBER)
        elif ride["here"] or not ride["moving"]:
            last = ("STOPPED" if not ride["here"] else "", AMBER)
        else:
            last = (f"{ride['speed']} MPH", MUTED)
        items = [item for item in (first, middle, last) if item[0]]
        # Left, middle and right if all three fit; otherwise drop the least important first.
        while items and sum(tiny_width(text) for text, _ in items) + 8 * (len(items) - 1) > 126:
            items.pop()
        y = 21
        if len(items) == 3:
            draw_tiny(frame, items[0][0], 1, y, items[0][1])
            draw_tiny(frame, items[1][0], (128 - tiny_width(items[1][0])) // 2, y, items[1][1])
            draw_tiny(frame, items[2][0], 127 - tiny_width(items[2][0]), y, items[2][1])
        elif items:
            draw_tiny(frame, items[0][0], 1, y, items[0][1])
            if len(items) == 2:
                draw_tiny(frame, items[1][0], 127 - tiny_width(items[1][0]), y, items[1][1])

    @staticmethod
    def _line(frame, ride, fraction, colour, t):
        """The whole route, stop by stop, not just the two ends of the leg you're on.
        Every stop is a tick, evenly spaced (a line map, not a scale map); stops
        already served are lit in the route's colour, the one just behind and the one
        ahead stand taller, and the train sits between them at a fraction of a pixel
        (a real train crosses a pixel every few minutes, and whole-pixel steps would
        sit still and then lurch). A lone pulse rides with it, the one light on the
        line that moves, so the eye finds it even on a busy multi-stop route."""
        stops = ride["stops"]
        span = RIGHT - LEFT
        legs = max(1, len(stops) - 1)
        xs = [LEFT + round(index / legs * span) for index in range(len(stops))]
        next_index = ride["next"]
        behind_x, ahead_x = xs[max(0, next_index - 1)], xs[next_index]
        edge = behind_x + fraction * (ahead_x - behind_x) if ahead_x > behind_x else float(ahead_x)
        for y in (30, 31):
            for x in range(LEFT, RIGHT + 1):
                frame.putpixel((x, y), TRACK)
            for x in range(LEFT, int(edge)):
                frame.putpixel((x, y), colour)
            blend(frame, int(edge), y, colour, edge - int(edge))
        for index, x in enumerate(xs):
            done = index < next_index or (index == next_index and ride["here"])
            near = index in (next_index - 1, next_index)
            top = 28 if near else 29
            frame.putpixel((x, 31), colour if done else WHITE if near else MUTED)
            for y in range(top, 31):
                frame.putpixel((x, y), colour if done else MUTED if near else TRACK)
        pulse = .35 + .35 * math.sin(t * 4)
        blend(frame, round(edge), 29, colour, pulse)
        wide = len(TRAIN[0])
        wheels = WHEELS[int(t * 2) % 2] if ride["moving"] else WHEELS[0]
        rows = (TRAIN[0], TRAIN[1], wheels)
        # The train's nose is at the head of the bar; drawn twice, weighted by the fraction of a
        # pixel it has moved, so the total light stays the same wherever it is.
        left = min(max(edge - wide + 1, LEFT + 1), RIGHT - wide)
        whole, part = int(left), left - int(left)
        for dy, row in enumerate(rows):
            for dx, mark in enumerate(row):
                if mark == "#":
                    # Dark wheels and windows on the light body are what read as a
                    # train at this size; solid white end to end read as a blob.
                    shade = (WHEEL if dy == 2 else LAMP if dx == wide - 1 and dy == 1
                             else WINDOW if dy == 1 and dx in WINDOWS else BODY)
                    blend(frame, whole + dx, 27 + dy, shade, 1 - part)
                    blend(frame, whole + dx + 1, 27 + dy, shade, part)


def validate(settings):
    train = str(settings.get("train") or "").strip()
    if train and train not in ROUTES and not re.fullmatch(r"\d{1,4}", train):
        raise ValueError("train must be a route, an Amtrak train number, or empty")
    station = str(settings.get("station") or "").strip()
    if station and not re.fullmatch(r"[A-Za-z]{3}", station):
        raise ValueError("station must be a three-letter Amtrak code, like LAX")
    refresh = settings.get("refresh_seconds")
    if isinstance(refresh, bool) or not isinstance(refresh, (int, float)) or not 20 <= refresh <= 600:
        raise ValueError("refresh_seconds must be 20–600")
    for key, limit in (("latitude", 90), ("longitude", 180)):
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not -limit <= value <= limit:
            raise ValueError(f"{key} must be between {-limit} and {limit}")


plugin = Plugin(
    "onboard", "Onboard", module=Carriage, provider=Onboard,
    defaults={"train": "coast_starlight", "station": "", "refresh_seconds": 60, "latitude": 0.0, "longitude": 0.0},
    choices={"train": ("", *ROUTES)},
    help={"train": "a route to ride, or type an Amtrak train number",
          "station": "a three-letter Amtrak station code to ride whatever is serving it (used only when no "
                     "route is set)",
          "latitude": "with a home location it rides the train nearest to it, when several are running"},
    validate_settings=validate,
    ui={"refresh_seconds": {"advanced": True}, "latitude": {"type": "location", "label": "Nearest to"},
        "longitude": {"type": "hidden"}},
)
