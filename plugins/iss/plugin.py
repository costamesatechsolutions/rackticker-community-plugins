"""Space station: where the International Space Station is right now, and when to look up.

The left panel is the whole world with the day and night sides lit as they are this
minute, the station's track across it and the station itself. The right panel says
what it is flying over, how fast, when the crew next sees the sun set, when you can
next see it from home, and who is aboard. During a pass you can see, the screen
takes over and points to it in the sky.

Positions come from the station's published orbit (CelesTrak), worked forward here,
so it keeps moving even while the network is down.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, offload,
                         text_width, tiny_width)

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle"
CREW_URL = "https://corquaid.github.io/international-space-station-APIs/JSON/people-in-space.json"
TLE_EVERY, CREW_EVERY, PASSES_EVERY = 4 * 3600, 6 * 3600, 1800
SEARCH_DAYS = 7

RE, MU, J2, TAU = 6378.137, 398600.4418, 1.08262668e-3, 2 * math.pi
E2 = 6.69437999014e-3

WHITE, GREY, AMBER, RED = (236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 60, 40)
GOLD, CYAN, GREEN = (255, 214, 60), (60, 200, 255), (90, 230, 120)
DAY_LAND, NIGHT_LAND, TWILIGHT_LAND = (40, 150, 70), (34, 56, 130), (40, 100, 110)
TRACK_AHEAD, TRACK_BEHIND = (170, 120, 30), (70, 74, 80)
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
PAGE_SECONDS = 6.0
NAME_REST, NAME_SPEED = 1.4, 18
MAP_W = 64


# --- the orbit -----------------------------------------------------------------------------

def parse_tle(line1, line2):
    """Mean elements from a two-line element set, with the J2 drift rates.

    Kepler's ellipse turned by the Earth's bulge (J2) and slowly lowered by drag is
    within a few kilometres of SGP4 over the days a fresh element set is used for:
    far closer than one pixel of a 64-pixel world (600 km)."""
    year = int(line1[18:20])
    year += 2000 if year < 57 else 1900
    epoch = datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() + (float(line1[20:32]) - 1) * 86400
    ndot = float(line1[33:43])
    inc, raan = math.radians(float(line2[8:16])), math.radians(float(line2[17:25]))
    ecc, argp = float("0." + line2[26:33].strip()), math.radians(float(line2[34:42]))
    m0, n = math.radians(float(line2[43:51])), float(line2[52:63]) * TAU / 86400
    a1 = (MU / n ** 2) ** (1 / 3)
    d1 = .75 * J2 * (RE / a1) ** 2 * (3 * math.cos(inc) ** 2 - 1) / (1 - ecc ** 2) ** 1.5
    a0 = a1 * (1 - d1 / 3 - d1 ** 2 - 134 / 81 * d1 ** 3)
    n0 = n / (1 + d1 * (a1 / a0) ** 2)
    a = (MU / n0 ** 2) ** (1 / 3)
    rate = 1.5 * J2 * (RE / (a * (1 - ecc ** 2))) ** 2 * n0
    ci = math.cos(inc)
    return (epoch, inc, raan, ecc, argp, m0, n0, a, -rate * ci, rate / 2 * (5 * ci ** 2 - 1),
            n0 + rate / 2 * math.sqrt(1 - ecc ** 2) * (3 * ci ** 2 - 1), ndot * TAU / 86400 ** 2)


def eci(el, ts):
    """Position (km) in the Earth-centred inertial frame at unix time ts."""
    epoch, inc, raan0, e, argp0, m0, n0, a0, draan, dargp, dm, ndot = el
    dt = ts - epoch
    m = m0 + dm * dt + ndot * dt * dt
    a = a0 * (n0 / (n0 + 2 * ndot * dt)) ** (2 / 3)
    raan, argp = raan0 + draan * dt, argp0 + dargp * dt
    big_e = m
    for _ in range(5):
        big_e -= (big_e - e * math.sin(big_e) - m) / (1 - e * math.cos(big_e))
    nu = 2 * math.atan2(math.sqrt(1 + e) * math.sin(big_e / 2), math.sqrt(1 - e) * math.cos(big_e / 2))
    r, u = a * (1 - e * math.cos(big_e)), argp + nu
    cu, su, co, so, ci, si = math.cos(u), math.sin(u), math.cos(raan), math.sin(raan), math.cos(inc), math.sin(inc)
    return (r * (co * cu - so * su * ci), r * (so * cu + co * su * ci), r * su * si)


def gmst(ts):
    return math.radians((280.46061837 + 360.98564736629 * (ts / 86400 + 2440587.5 - 2451545.0)) % 360)


def to_ecef(p, ts):
    g = gmst(ts)
    c, s = math.cos(g), math.sin(g)
    return (c * p[0] + s * p[1], -s * p[0] + c * p[1], p[2])


def geodetic(p):
    """(latitude°, longitude°, altitude km) of an Earth-fixed position."""
    x, y, z = p
    r = math.hypot(x, y)
    lat = math.atan2(z, r * (1 - E2))
    for _ in range(3):
        n = RE / math.sqrt(1 - E2 * math.sin(lat) ** 2)
        lat = math.atan2(z + E2 * n * math.sin(lat), r)
    n = RE / math.sqrt(1 - E2 * math.sin(lat) ** 2)
    return math.degrees(lat), (math.degrees(math.atan2(y, x)) + 180) % 360 - 180, r / math.cos(lat) - n


def site(lat, lon):
    lat, lon = math.radians(lat), math.radians(lon)
    n = RE / math.sqrt(1 - E2 * math.sin(lat) ** 2)
    return (n * math.cos(lat) * math.cos(lon), n * math.cos(lat) * math.sin(lon), n * (1 - E2) * math.sin(lat),
            math.sin(lat), math.cos(lat), math.sin(lon), math.cos(lon))


def look(observer, p):
    """(azimuth°, elevation°) of an Earth-fixed point seen from an observer made by site()."""
    ox, oy, oz, slat, clat, slon, clon = observer
    dx, dy, dz = p[0] - ox, p[1] - oy, p[2] - oz
    south = slat * clon * dx + slat * slon * dy - clat * dz
    east = -slon * dx + clon * dy
    up = clat * clon * dx + clat * slon * dy + slat * dz
    return (math.degrees(math.atan2(east, -south)) % 360,
            math.degrees(math.atan2(up, math.hypot(south, east))))


def sun(ts):
    """The Sun's direction (unit vector, inertial frame), good to a hundredth of a degree."""
    n = ts / 86400 + 2440587.5 - 2451545.0
    g = math.radians(357.528 + .9856003 * n)
    lam = math.radians(280.460 + .9856474 * n + 1.915 * math.sin(g) + .020 * math.sin(2 * g))
    eps = math.radians(23.439 - 4e-7 * n)
    return (math.cos(lam), math.cos(eps) * math.sin(lam), math.sin(eps) * math.sin(lam))


def subsolar(ts):
    s = to_ecef(sun(ts), ts)
    return math.degrees(math.asin(s[2])), math.degrees(math.atan2(s[1], s[0]))


def sunlit(p, ts):
    """False in the Earth's shadow (a cylinder behind the Earth is close enough at 400 km)."""
    s = sun(ts)
    along = p[0] * s[0] + p[1] * s[1] + p[2] * s[2]
    if along > 0:
        return True
    return (p[0] - along * s[0]) ** 2 + (p[1] - along * s[1]) ** 2 + (p[2] - along * s[2]) ** 2 > RE ** 2


def sun_elevation(observer, ts):
    s = to_ecef(sun(ts), ts)
    far = 1.496e8
    return look(observer, (s[0] * far, s[1] * far, s[2] * far))[1]


def find_passes(line1, line2, lat, lon, start, days=SEARCH_DAYS):
    """Passes you can see from (lat, lon): the station is lit, your sky is dark and it is 10° up.

    Runs in a helper process (about half a second on a laptop for a week)."""
    el, observer = parse_tle(line1, line2), site(lat, lon)

    def elevation(ts):
        return look(observer, to_ecef(eci(el, ts), ts))[1]

    def edge(lo, hi, rising):
        for _ in range(12):
            mid = (lo + hi) / 2
            if (elevation(mid) >= 10) == rising:
                hi = mid
            else:
                lo = mid
        return hi if rising else lo

    passes, ts, end = [], start - 600, start + days * 86400
    previous = elevation(ts)
    while ts < end and len(passes) < 12:
        ts += 30
        now = elevation(ts)
        if previous < 10 <= now:
            rise = edge(ts - 30, ts, True)
            step = rise
            while elevation(step + 20) >= 10:
                step += 20
            setting = edge(step, step + 20, False)
            seen, best = [], (-90, 0)
            t = rise
            while t <= setting:
                p = eci(el, t)
                az, alt = look(observer, to_ecef(p, t))
                if sunlit(p, t) and sun_elevation(observer, t) < -6:
                    seen.append((t, az, alt))
                    best = max(best, (alt, az))
                t += 5
            if len(seen) >= 12 and seen[-1][0] > start:
                passes.append({"start": seen[0][0], "end": seen[-1][0], "from": seen[0][1], "to": seen[-1][1],
                               "max": best[0], "max_az": best[1]})
            ts = setting + 60
            now = elevation(ts)
        previous = now
    return passes


def compass(azimuth):
    return COMPASS[round(azimuth / 22.5) % 16]


# --- the world -------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def world():
    data = json.loads((Path(__file__).parent / "world.json").read_text())
    grid = []
    for row in data["countries"]:
        cells = []
        for run in row.split(","):
            value, count = run.split("x")
            cells.extend([int(value)] * int(count))
        grid.append(cells)
    return data, grid


OCEANS = (  # (south, north, west, east, name): first match wins, so the small seas come first
    (30, 46, -6, 37, "Mediterranean"), (18, 31, -98, -81, "Gulf of Mexico"), (9, 22, -88, -60, "Caribbean"),
    (0, 23, 100, 121, "South China Sea"), (5, 23, 80, 95, "Bay of Bengal"), (5, 25, 51, 75, "Arabian Sea"),
    (12, 30, 32, 44, "Red Sea"), (51, 66, -95, -77, "Hudson Bay"), (-45, -30, 147, 175, "Tasman Sea"),
    (66, 90, -180, 180, "Arctic Ocean"), (-90, -56, -180, 180, "Southern Ocean"),
)


def over(lat, lon):
    """What the station is over: a country, or a sea or ocean."""
    data, grid = world()
    row, col = min(179, max(0, int(90 - lat))), int((lon + 180) % 360)
    if grid[row][col]:
        return data["names"][grid[row][col] - 1]
    for south, north, west, east, name in OCEANS:
        if south <= lat < north and west <= lon < east:
            return name
    if -70 <= lon < 20 and lat < 10 or -82 <= lon < -5 and lat >= 10:
        return "Atlantic"
    if 20 <= lon < 120 and lat < 25 or 120 <= lon < 147 and lat < -10:
        return "Indian Ocean"
    return "Pacific"


def map_xy(lat, lon):
    data, _ = world()
    north, south = data["map_north"], data["map_south"]
    return (lon + 180) / 360 * MAP_W, (north - lat) / (north - south) * 32


@lru_cache(maxsize=2)
def daylight_map(minute):
    """The 64 × 32 world lit as it is this minute: green by day, blue by night, teal at dusk."""
    data, _ = world()
    lat0, lon0 = subsolar(minute * 60)
    s_lat, c_lat = math.sin(math.radians(lat0)), math.cos(math.radians(lat0))
    image = Image.new("RGB", (MAP_W, 32))
    pixels = image.load()
    north, south = data["map_north"], data["map_south"]
    for y, row in enumerate(data["land"]):
        lat = math.radians(north - (y + .5) / 32 * (north - south))
        sl, cl = math.sin(lat), math.cos(lat)
        for x, cell in enumerate(row):
            lon = math.radians((x + .5) / MAP_W * 360 - 180 - lon0)
            height = sl * s_lat + cl * c_lat * math.cos(lon)   # sine of the Sun's height there
            if cell == "#":
                pixels[x, y] = DAY_LAND if height > .05 else NIGHT_LAND if height < -.1 else TWILIGHT_LAND
    return image


# --- the provider ----------------------------------------------------------------------------

class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.tle, self.tle_at = None, -1e9
        self.crew, self.crew_at = [], -1e9
        self.passes, self.passes_key, self.passes_at = [], None, -1e9
        self.alerted = set()

    async def _get(self, url):
        async with self.session.get(url) as response:
            response.raise_for_status()
            return await response.text()

    async def fetch(self):
        settings = self.context.settings
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),
                                                 headers={"User-Agent": "RackTicker space station plugin"})
        clock = time.monotonic()
        if clock - self.tle_at >= TLE_EVERY or self.tle is None:
            try:
                lines = [line.strip() for line in (await self._get(TLE_URL)).splitlines() if line.strip()]
                pair = [line for line in lines if line[:2] in ("1 ", "2 ")]
                if len(pair) == 2:
                    parse_tle(*pair)
                    self.tle = tuple(pair)
                self.tle_at = clock
            except (aiohttp.ClientError, TimeoutError, ValueError):
                self.tle_at = clock - TLE_EVERY + 300 if self.tle else clock - TLE_EVERY + 30
                if self.tle is None:
                    raise
        if clock - self.crew_at >= CREW_EVERY:
            self.crew_at = clock
            try:
                people = json.loads(await self._get(CREW_URL)).get("people") or []
                self.crew = [{"name": str(p.get("name", "")), "country": str(p.get("country", ""))}
                             for p in people if p.get("iss") and p.get("name")]
            except (aiohttp.ClientError, TimeoutError, ValueError):
                self.crew_at = clock - CREW_EVERY + 600
        home = (settings["latitude"], settings["longitude"])
        now = time.time()
        if home != (0, 0):
            key = (self.tle, home)
            if key != self.passes_key or clock - self.passes_at >= PASSES_EVERY:
                self.passes = await offload(find_passes, *self.tle, *home, now)
                self.passes_key, self.passes_at = key, clock
            lead = settings["alert_lead_minutes"] * 60
            for found in self.passes:
                if (settings["alert"] and found["start"] - lead <= now < found["end"]
                        and found["start"] not in self.alerted):
                    self.alerted.add(found["start"])
                    self.context.emit_event("iss", min(900, found["end"] - now + 5))
        return Snapshot({"tle": self.tle, "crew": self.crew, "home": home,
                         "passes": [found for found in self.passes if found["end"] > now]})

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# --- the screen ------------------------------------------------------------------------------

@lru_cache(maxsize=4)
def elements(tle):
    return parse_tle(*tle)


@lru_cache(maxsize=2)
def orbit_minute(tle, minute):
    """Once a minute: the track an orbit back and an orbit ahead, and the crew's next sunset or sunrise."""
    el, start = elements(tle), minute * 60
    track = []
    for step in range(-46, 94):
        ts = start + step * 60
        lat, lon, _ = geodetic(to_ecef(eci(el, ts), ts))
        track.append((step, lat, lon))
    lit = sunlit(eci(el, start), start)
    change = None
    for second in range(0, 6000, 20):
        if sunlit(eci(el, start + second), start + second) != lit:
            change = start + second
            break
    return track, lit, change


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
    """A mixed-case name in `room` pixels: whole if it fits, otherwise resting on whole letters then gliding."""
    if text_width(text, 1, True) <= room:
        draw_text(frame, text, x, y, color, mixed=True)
        return
    stops = [text_width(text[:i], 1, True) + 1 for i in range(1, len(text))]
    full = text_width(text, 1, True)
    distance = min([s for s in stops if full - s <= room] or [full - room])
    resting = text
    while resting and text_width(resting, 1, True) > room:
        resting = resting[:-1]
    shift = _glide(local, distance)
    cell = Image.new("RGB", (room, 9))
    draw_text(cell, resting.rstrip() if shift == 0 else text, -shift, 0, color, mixed=True)
    frame.paste(cell, (x, y))


def clock_text(ts, now):
    local = datetime.fromtimestamp(ts, now.tzinfo)
    hour = local.strftime("%I").lstrip("0") + local.strftime(":%M") + ("am" if local.hour < 12 else "pm")
    days = (local.date() - now.date()).days
    if days == 0:
        return ("Tonight " if local.hour >= 17 else "Today ") + hour
    if days == 1:
        return "Tmrw " + hour
    return local.strftime("%a ") + hour


def countdown(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def units(settings, km):
    return (f"{round(km * .621371):,}", "MPH") if settings["units"] == "imperial" else (f"{round(km):,}", "KM/H")


class Station(Module):
    name = "iss"
    event_priority = 30

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _data(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data and snap.data.get("tle") else None

    def available(self, context):
        return self._data(context) is not None

    def hold(self, context):
        return self.story.hold()

    @staticmethod
    def _active_pass(data, settings, ts):
        lead = settings["alert_lead_minutes"] * 60
        for found in data["passes"]:
            if found["start"] - lead <= ts < found["end"]:
                return found
        return None

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        data = self._data(context)
        if data is None:
            draw_text(frame, "Finding the ISS", 4, 12, GREY, mixed=True)
            return frame
        settings = context.config["plugins"][self.name]
        ts = context.now.timestamp()
        found = self._active_pass(data, settings, ts) if data["home"] != (0, 0) else None
        if found:
            self._look_up(frame, data, found, ts, context.animation_time)
            return frame
        self._map(frame, data, ts, context.animation_time)
        self._panel(frame, data, settings, context, ts)
        return frame

    # The left half: the world, lit as it is now.
    def _map(self, frame, data, ts, t):
        minute = int(ts // 60)
        frame.paste(daylight_map(minute), (0, 0))
        pixels = frame.load()
        track, _, _ = orbit_minute(data["tle"], minute)
        for step, lat, lon in track:
            x, y = map_xy(lat, lon)
            if 0 <= y < 32 and (step < 0 or (step - int(t * 4)) % 3):
                pixels[int(x) % MAP_W, int(y)] = TRACK_AHEAD if step >= 0 else TRACK_BEHIND
        s_lat, s_lon = subsolar(ts)
        sx, sy = map_xy(s_lat, s_lon)
        if 0 <= sy < 32:
            pixels[int(sx) % MAP_W, int(sy)] = GOLD
        if data["home"] != (0, 0):
            hx, hy = map_xy(*data["home"])
            if 0 <= hy < 32 and int(t * 2) % 2 == 0:
                pixels[int(hx) % MAP_W, int(hy)] = RED
        el = elements(data["tle"])
        lat, lon, _ = geodetic(to_ecef(eci(el, ts), ts))
        x, y = map_xy(lat, lon)
        x, y = int(x), int(y)
        glow = .55 + .45 * math.sin(t * 6)
        for dx, dy, color in ((-1, 0, CYAN), (1, 0, CYAN), (0, -1, WHITE), (0, 1, WHITE), (0, 0, WHITE),
                              (-2, 0, CYAN), (2, 0, CYAN)):
            px, py = (x + dx) % MAP_W, y + dy
            if 0 <= py < 32:
                pixels[px, py] = color if (dx, dy) != (0, 0) else tuple(round(c * glow) for c in WHITE)
        ImageDraw.Draw(frame).line((MAP_W, 0, MAP_W, 31), fill=(0, 0, 0))

    # The right half: pages about the station.
    def _panel(self, frame, data, settings, context, ts):
        pages = ["now", "sun"]
        if data["passes"]:
            pages.append("pass")
        crew = data["crew"]
        pages += [("crew", index) for index in range(0, len(crew), 2)]

        def build(visit):
            return [(page, PAGE_SECONDS if page != "now" else PAGE_SECONDS + 2) for page in pages]

        self.story.sync(context.animation_time, build, context.scene)
        current = self.story.current(context.animation_time, build)
        page, local = (current[0], current[1]) if current else ("now", 0)
        x = MAP_W + 3
        el = elements(data["tle"])
        p = eci(el, ts)
        if page == "now":
            lat, lon, altitude = geodetic(to_ecef(p, ts))
            draw_tiny(frame, "ISS IS OVER", x, 1, GREY)
            fitted(frame, over(lat, lon), x, 8, 128 - x, WHITE, local)
            q = eci(el, ts + 1)
            speed = math.dist(p, q) * 3600
            value, unit = units(settings, speed)
            draw_text(frame, value, x, 19, AMBER)
            draw_tiny(frame, unit, x + text_width(value) + 3, 21, AMBER)
            height = (f"{round(altitude * .621371)} MI UP" if settings["units"] == "imperial"
                      else f"{round(altitude)} KM UP")
            draw_tiny(frame, height, x, 27, GREY)
        elif page == "sun":
            _, lit, change = orbit_minute(data["tle"], int(ts // 60))
            draw_tiny(frame, "CREW SEES THE", x, 1, GREY)
            label = "SUNSET IN" if lit else "SUNRISE IN"
            draw_tiny(frame, label, x, 7, GOLD if lit else CYAN)
            if change:
                text = countdown(change - ts)
                draw_text(frame, text, x, 15, WHITE, scale=2 if text_width(text, 2) <= 128 - x else 1, smooth=True)
            else:
                draw_text(frame, "soon", x, 15, WHITE, mixed=True)
        elif page == "pass":
            found = data["passes"][0]
            draw_tiny(frame, "NEXT SIGHTING", x, 1, GREY)
            fitted(frame, clock_text(found["start"], context.now), x, 8, 128 - x, WHITE, local)
            minutes = max(1, round((found["end"] - found["start"]) / 60))
            draw_text(frame, f"{compass(found['from'])}→{compass(found['to'])}", x, 18, AMBER)
            draw_tiny(frame, f"{minutes} MIN, {round(found['max'])}° HIGH", x, 27, GREY)
        else:
            index = page[1]
            draw_tiny(frame, f"ON BOARD: {len(crew)}", x, 1, GREY)
            for row, person in enumerate(crew[index:index + 2]):
                y = 9 + row * 11
                fitted(frame, person["name"].split()[-1], x, y, 128 - x - 14, WHITE, local)
                flag = {"United States": "USA", "Russia": "RUS", "Canada": "CAN", "Japan": "JPN", "Italy": "ITA",
                        "Germany": "GER", "France": "FRA", "United Kingdom": "UK", "Denmark": "DEN",
                        "United Arab Emirates": "UAE", "India": "IND", "Spain": "ESP", "Sweden": "SWE",
                        "Poland": "POL", "Hungary": "HUN"}.get(person["country"], person["country"][:3].upper())
                draw_tiny(frame, flag, 128 - tiny_width(flag), y + 1, GREY)

    # A pass you can see: the take-over.
    def _look_up(self, frame, data, found, ts, t):
        draw = ImageDraw.Draw(frame)
        cx, cy, radius = 15, 15, 15
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(40, 70, 120))
        for label, dx, dy in (("N", 0, -1), ("E", 1, 0), ("S", 0, 1), ("W", -1, 0)):
            draw_tiny(frame, label, cx + dx * (radius - 3) - 1, cy + dy * (radius - 3) - 2, (60, 90, 150))
        el, observer = elements(data["tle"]), site(*data["home"])

        def dome(when):
            az, alt = look(observer, to_ecef(eci(el, when), when))
            r = (90 - max(alt, 0)) / 90 * radius
            return cx + r * math.sin(math.radians(az)), cy - r * math.cos(math.radians(az)), az, alt

        pixels = frame.load()
        when = found["start"] - 30
        while when <= found["end"] + 30:
            x, y, _, alt = dome(when)
            if alt > 0:
                pixels[int(x), int(y)] = TRACK_AHEAD
            when += 10
        x, y, az, alt = dome(ts)
        right = 36
        if ts < found["start"]:
            draw_tiny(frame, "ISS RISING IN", right, 1, GREY)
            draw_text(frame, countdown(found["start"] - ts), right, 8, WHITE, scale=2, smooth=True)
            draw_tiny(frame, f"LOOK {compass(found['from'])}, LOW", right, 26, AMBER)
            sx, sy, _, _ = dome(found["start"])
            if int(t * 3) % 2 == 0:
                draw.rectangle((sx - 1, sy - 1, sx + 1, sy + 1), fill=AMBER)
            return
        if alt > 0:
            glow = .6 + .4 * math.sin(t * 8)
            draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=tuple(round(c * glow) for c in WHITE))
        if int(t * 2) % 4 != 3:
            draw_text(frame, "LOOK UP", right, 1, AMBER, scale=2, smooth=True)
        draw_text(frame, f"{compass(az)} {round(max(alt, 0))}° up", right, 17, WHITE, mixed=True)
        draw_tiny(frame, f"GONE IN {countdown(found['end'] - ts)}", right, 27, GREY)


def validate_settings(settings):
    if settings.get("units") not in ("imperial", "metric"):
        raise ValueError("units must be imperial or metric")
    if not 0 <= float(settings.get("alert_lead_minutes", 0)) <= 15:
        raise ValueError("alert_lead_minutes must be between 0 and 15")
    return settings


plugin = Plugin(
    "iss", "Space station", module=Station, provider=Feed,
    defaults={"latitude": 0.0, "longitude": 0.0, "units": "imperial", "alert": True, "alert_lead_minutes": 2},
    choices={"units": ("imperial", "metric")},
    validate_settings=validate_settings,
    help={"latitude": "Leave at 0 to use the home location from Settings",
          "alert": "Take over the display while the station is crossing your sky and you can see it",
          "alert_lead_minutes": "Start the take-over this many minutes before it rises, with a countdown"},
    ui={"latitude": {"type": "location", "label": "Location"}, "longitude": {"advanced": True},
        "alert": {"label": "Take over for a pass you can see"},
        "alert_lead_minutes": {"type": "slider", "min": 0, "max": 15, "step": 1, "unit": "min",
                               "label": "Warn before it rises"}},
)
