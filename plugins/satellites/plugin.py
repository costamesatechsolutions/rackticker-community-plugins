"""Satellites: every working satellite above your horizon right now, moving.

Thousands of satellites circle the Earth, most of them SpaceX's Starlink. This
shows the ones over your sky this minute across the whole 360° horizon, each
dot moving at its real pace; those still lit by the Sun after dark (the ones you
could actually see) shine brighter. The space stations are named. Then the count
and who they belong to.

Orbits from CelesTrak's catalogue of active satellites, worked forward here.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
from pathlib import Path
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, offload, text_width,
                         tiny_width)

CATALOGUE = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"
# CelesTrak asks that the same data is not downloaded more than once every two hours.
CATALOGUE_EVERY, NEARBY_EVERY, POSITIONS_EVERY = 6 * 3600, 600, 30
NEARBY_MARGIN = -12          # degrees below the horizon still worth following for the next ten minutes

RE, MU, J2, TAU = 6378.137, 398600.4418, 1.08262668e-3, 2 * math.pi
E2 = 6.69437999014e-3


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


# --- the work, in a helper process ---------------------------------------------------------


def group(name):
    name = name.upper()
    if name.startswith("STARLINK"):
        return "starlink"
    if name.startswith("ONEWEB"):
        return "oneweb"
    if name.startswith(("KUIPER", "AMAZON")):
        return "kuiper"
    if name.startswith(("ISS (", "CSS (")):
        return "station"
    return "other"


def parse_catalogue(text):
    """[(name, line1, line2)] from three-line TLE text."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    sats = []
    for index in range(len(lines) - 2):
        if lines[index + 1].startswith("1 ") and lines[index + 2].startswith("2 ") and not lines[index].startswith(("1 ", "2 ")):
            try:
                parse_tle(lines[index + 1], lines[index + 2])
            except ValueError:
                continue
            sats.append((lines[index].strip(), lines[index + 1], lines[index + 2]))
    return sats


def nearby(sats, lat, lon, start):
    """The satellites that are up, or come up, over the next ten minutes."""
    observer = site(lat, lon)
    keep = []
    for sat in sats:
        el = parse_tle(sat[1], sat[2])
        for step in (0, 150, 300, 450, 600):
            ts = start + step
            if look(observer, to_ecef(eci(el, ts), ts))[1] > NEARBY_MARGIN:
                keep.append(sat)
                break
    return keep


def positions(sats, lat, lon, start, later):
    """For each satellite above the horizon at either moment: (group, az0, el0, az1, el1, lit)."""
    observer = site(lat, lon)
    found = []
    for name, line1, line2 in sats:
        el = parse_tle(line1, line2)
        p0, p1 = eci(el, start), eci(el, later)
        az0, alt0 = look(observer, to_ecef(p0, start))
        az1, alt1 = look(observer, to_ecef(p1, later))
        if alt0 > -2 or alt1 > -2:
            label = name.split(" (")[0] if group(name) == "station" else ""
            found.append((group(name), round(az0, 2), round(alt0, 2), round(az1, 2), round(alt1, 2),
                          sunlit(p0, start), label))
    return found


# --- the provider ----------------------------------------------------------------------------


class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.sats, self.sats_at, self.download, self.failed = [], -1e9, None, False
        self.near, self.near_at, self.near_key = [], -1e9, None
        self.snapshot = None

    async def _download(self):
        """The catalogue from the copy kept on disk if it is fresh, otherwise from CelesTrak.

        CelesTrak refuses (403) a second download of the same data within two hours,
        so after a restart the kept copy is what keeps the screen going."""
        cache = Path.home() / "celestrak-active.tle"
        age = time.time() - cache.stat().st_mtime if cache.exists() else 1e9
        if age < CATALOGUE_EVERY or (age < 2 * 86400 and not self.sats and self.failed):
            return await offload(parse_catalogue, await asyncio.to_thread(cache.read_text))
        timeout = aiohttp.ClientTimeout(total=90)
        try:
            async with aiohttp.ClientSession(timeout=timeout,
                                             headers={"User-Agent": "RackTicker satellites plugin"}) as session:
                async with session.get(CATALOGUE) as response:
                    response.raise_for_status()
                    text = await response.text()
        except (aiohttp.ClientError, TimeoutError):
            self.failed = True
            if age < 2 * 86400:
                return await offload(parse_catalogue, await asyncio.to_thread(cache.read_text))
            raise
        sats = await offload(parse_catalogue, text)
        if sats:
            await asyncio.to_thread(cache.write_text, text)
        return sats

    async def fetch(self):
        settings = self.context.settings
        home = (settings["latitude"], settings["longitude"])
        if home == (0, 0):
            raise ValueError("Set your home location in Settings")
        clock = time.monotonic()
        # The catalogue is big (2.7 MB), so it downloads on its own beside the regular rounds.
        if self.download is None and (not self.sats or clock - self.sats_at >= CATALOGUE_EVERY):
            self.download = asyncio.ensure_future(self._download())
        if self.download is not None and self.download.done():
            try:
                sats = self.download.result()
                if sats:
                    self.sats, self.sats_at, self.near_key = sats, clock, None
            except Exception:
                self.sats_at = clock - CATALOGUE_EVERY + (900 if self.sats else 120)
            self.download = None
        if not self.sats:
            return Snapshot(None)
        now = time.time()
        if self.near_key != home or clock - self.near_at >= NEARBY_EVERY:
            self.near = await offload(nearby, self.sats, *home, now)
            self.near_key, self.near_at = home, clock
        if self.snapshot is None or now - self.snapshot["start"] >= POSITIONS_EVERY:
            found = await offload(positions, self.near, *home, now, now + POSITIONS_EVERY)
            observer = site(*home)
            self.snapshot = {"start": now, "span": POSITIONS_EVERY, "sats": found, "home": home,
                             "dark": sun_elevation(observer, now) < -6, "total": len(self.sats)}
        return Snapshot(self.snapshot)

    async def close(self):
        if self.download is not None:
            self.download.cancel()


# --- the screen ------------------------------------------------------------------------------

WHITE, GREY, AMBER, GOLD = (236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60)
COLORS = {"starlink": (40, 100, 255), "oneweb": (40, 200, 140), "kuiper": (255, 140, 30),
          "station": (255, 214, 60), "other": (190, 190, 196)}
NAMES = {"starlink": "STARLINK", "oneweb": "ONEWEB", "kuiper": "AMAZON", "other": "OTHERS"}
HORIZON_ROW = 25
COMPASS8 = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
SWARM, COUNTS = 12.0, 8.0


def column(az, south_up):
    return ((az - (180 if south_up else 0) + 180) % 360) / 360 * 128


def interpolate(a0, a1, f):
    delta = (a1 - a0 + 180) % 360 - 180
    return (a0 + delta * f) % 360


class Satellites(Module):
    name = "satellites"

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _data(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data else None

    def available(self, context):
        return self._data(context) is not None

    def hold(self, context):
        return self.story.hold()

    def _now(self, data, ts):
        """Everything above the horizon at ts: (group, az, alt, lit, label)."""
        f = (ts - data["start"]) / data["span"]
        f = max(0.0, min(1.5, f))
        up = []
        for group_name, az0, el0, az1, el1, lit, label in data["sats"]:
            alt = el0 + (el1 - el0) * f
            if alt >= 0:
                up.append((group_name, interpolate(az0, az1, f), alt, lit, label))
        return up

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        data = self._data(context)
        if data is None:
            draw_text(frame, "Loading orbits", 2, 12, GREY, mixed=True)
            return frame
        up = self._now(data, context.now.timestamp())

        def build(visit):
            return [("swarm", SWARM), ("counts", COUNTS)]

        self.story.sync(context.animation_time, build, context.scene)
        page, local, _ = self.story.current(context.animation_time, build) or ("swarm", 0, 0)
        if page == "swarm":
            self._swarm(frame, data, up, local, context.animation_time)
        else:
            self._counts(frame, data, up, local)
        return frame

    @staticmethod
    def _swarm(frame, data, up, local, t):
        south_up = data["home"][0] >= 0
        pixels = frame.load()
        draw = ImageDraw.Draw(frame)
        labels = []
        for group_name, az, alt, lit, label in sorted(up, key=lambda item: item[0] == "station"):
            x, y = int(column(az, south_up)) % 128, int(HORIZON_ROW - alt / 90 * HORIZON_ROW)
            color = COLORS[group_name]
            if data["dark"]:
                color = color if lit else tuple(round(c * .3) for c in color)
            else:
                color = tuple(round(c * .7) for c in color)
            if group_name == "station":
                draw.rectangle((x - 1, y, x + 1, y), fill=GOLD)
                labels.append((x, y, label))
            elif sum(pixels[x, y]) < sum(color):
                pixels[x, y] = color
        for x, y, label in labels:
            ly = y - 7 if y >= 7 else y + 2
            width = tiny_width(label)
            draw_tiny(frame, label, min(128 - width, max(0, x - width // 2)), ly, GOLD)
        draw.line((0, HORIZON_ROW + 1, 127, HORIZON_ROW + 1), fill=(40, 90, 40))
        for index, label in enumerate(COMPASS8):
            x = round(column(index * 45, south_up))
            x = 0 if x >= 127 else x
            width = tiny_width(label)
            draw_tiny(frame, label, min(128 - width, max(0, x - width // 2)), 27, WHITE if len(label) == 1 else GREY)
        if local < 3.5:
            text = f"{len(up)} OVERHEAD"
            draw.rectangle((0, 0, tiny_width(text) + 1, 6), fill=(0, 0, 0))
            draw_tiny(frame, text, 1, 1, WHITE)

    @staticmethod
    def _counts(frame, data, up, local):
        count = str(len(up))
        draw_text(frame, count, 0, 1, AMBER, scale=2, smooth=True)
        x = text_width(count, 2) + 4
        draw_tiny(frame, "SATELLITES ABOVE", x, 2, WHITE)
        lit = sum(1 for item in up if item[3])
        line = f"{lit} SUNLIT, LOOK UP" if data["dark"] else "YOUR HORIZON NOW"
        draw_tiny(frame, line, x, 9, GOLD if data["dark"] else GREY)
        groups = {}
        for item in up:
            if item[0] != "station":
                groups[item[0]] = groups.get(item[0], 0) + 1
        draw = ImageDraw.Draw(frame)
        # One bar, split by owner, then the key.
        total = max(1, sum(groups.values()))
        left = 0
        order = [name for name in ("starlink", "oneweb", "kuiper", "other") if groups.get(name)]
        grow = min(1.0, local / 1.2)
        for name in order:
            width = round(groups[name] / total * 128 * grow)
            if width:
                draw.rectangle((left, 16, min(127, left + width - 1), 18), fill=COLORS[name])
            left += width
        parts = [(f"{NAMES[name]} {groups[name]}", COLORS[name]) for name in order]
        rows, line = [[]], 0
        for text, color in parts:          # as many as fit on a line, then the next
            used = sum(tiny_width(t) + 6 for t, _ in rows[-1])
            if rows[-1] and used + tiny_width(text) > 128:
                rows.append([])
            rows[-1].append((text, color))
        for index, row in enumerate(rows[:2]):
            x = 0
            for text, color in row:
                draw_tiny(frame, text, x, 21 + index * 6, color)
                x += tiny_width(text) + 6


plugin = Plugin(
    "satellites", "Satellites overhead", module=Satellites, provider=Feed,
    defaults={"latitude": 0.0, "longitude": 0.0},
    help={"latitude": "Leave at 0 to use the home location from Settings"},
    ui={"latitude": {"type": "location", "label": "Location"}, "longitude": {"advanced": True}},
)
