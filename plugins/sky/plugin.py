"""Sky: your whole horizon, all 360 degrees of it, across the panel.

North at both ends, south in the middle (the other way round below the equator).
The Sun, the Moon, the five planets you can see without a telescope and the
brightest stars sit at their real compass bearing and height, over a sky coloured
by the time of day. Then tonight in ten seconds, and when each planet is up.

Everything is worked out here: planets from JPL's approximate orbital elements
(good to a fraction of a degree, far finer than a pixel), the Moon from the main
terms of its theory, the stars from their catalogue places.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import math
import time

from PIL import Image, ImageDraw

from rackticker import Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, tiny_width

WHITE, GREY, AMBER, GOLD = (236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60)
HORIZON_ROW = 25            # altitude 0; altitude 90 is row 0
COMPASS8 = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
NOW_SECONDS, LAPSE_SECONDS, LIST_SECONDS = 12.0, 11.0, 7.0
OBLIQUITY = math.radians(23.43928)

# JPL "Approximate Positions of the Planets" (Standish), 1800-2050: a, e, I, L, perihelion, node,
# and their rates per century.
ELEMENTS = {
    "Mercury": ((0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
                (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081)),
    "Venus": ((0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
              (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418)),
    "Earth": ((1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
              (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    "Mars": ((1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
             (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
    "Jupiter": ((5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
                (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106)),
    "Saturn": ((9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
               (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794)),
}
PLANETS = {"Mercury": (230, 170, 110), "Venus": (255, 250, 210), "Mars": (255, 80, 40),
           "Jupiter": (255, 222, 160), "Saturn": (235, 200, 110)}
# The brightest stars (J2000 right ascension in hours, declination, magnitude) and the
# ones that draw Orion and the Big Dipper.
STARS = (
    (6.752, -16.716, -1.46), (6.399, -52.696, -.74), (14.261, 19.182, -.05), (18.616, 38.784, .03),
    (5.278, 45.998, .08), (5.242, -8.202, .13), (7.655, 5.225, .34), (5.919, 7.407, .5), (1.629, -57.237, .46),
    (19.846, 8.868, .77), (4.599, 16.509, .85), (16.490, -26.432, 1.09), (13.420, -11.161, .97),
    (7.755, 28.026, 1.14), (22.961, -29.622, 1.16), (20.690, 45.280, 1.25), (10.139, 11.967, 1.35),
    (7.577, 31.888, 1.58), (2.530, 89.264, 1.98), (5.419, 6.350, 1.64), (5.604, -1.202, 1.69),
    (5.679, -1.943, 1.74), (5.533, -.299, 2.23), (11.062, 61.751, 1.79), (13.792, 49.313, 1.86),
    (13.399, 54.925, 2.23), (12.900, 55.960, 1.77), (11.031, 56.382, 2.37), (11.897, 53.695, 2.44),
    (12.257, 57.033, 3.31), (3.405, 49.861, 1.79), (2.120, 23.462, 2.0), (0.140, 29.091, 2.06),
    (17.582, 12.560, 2.08), (9.460, -8.659, 1.98), (14.845, 74.156, 2.08), (0.675, 56.537, 2.24),
)


def centuries(ts):
    return (ts / 86400 + 2440587.5 - 2451545.0) / 36525


def heliocentric(name, t):
    (a, e, inc, mean_long, peri, node), rates = ELEMENTS[name]
    a, e, inc, mean_long, peri, node = (value + rate * t for value, rate in zip((a, e, inc, mean_long, peri, node), rates))
    m = math.radians((mean_long - peri) % 360)
    big_e = m + e * math.sin(m)
    for _ in range(6):
        big_e -= (big_e - e * math.sin(big_e) - m) / (1 - e * math.cos(big_e))
    x, y = a * (math.cos(big_e) - e), a * math.sqrt(1 - e * e) * math.sin(big_e)
    w, o, i = math.radians(peri - node), math.radians(node), math.radians(inc)
    cw, sw, co, so, ci, si = math.cos(w), math.sin(w), math.cos(o), math.sin(o), math.cos(i), math.sin(i)
    return ((cw * co - sw * so * ci) * x + (-sw * co - cw * so * ci) * y,
            (cw * so + sw * co * ci) * x + (-sw * so + cw * co * ci) * y,
            (sw * si) * x + (cw * si) * y)


def ecliptic_to_radec(x, y, z):
    ye = y * math.cos(OBLIQUITY) - z * math.sin(OBLIQUITY)
    ze = y * math.sin(OBLIQUITY) + z * math.cos(OBLIQUITY)
    return math.atan2(ye, x), math.atan2(ze, math.hypot(x, ye))


def planet_radec(name, ts):
    t = centuries(ts)
    px, py, pz = heliocentric(name, t)
    ex, ey, ez = heliocentric("Earth", t)
    return ecliptic_to_radec(px - ex, py - ey, pz - ez)


def sun_radec(ts):
    ex, ey, ez = heliocentric("Earth", centuries(ts))
    return ecliptic_to_radec(-ex, -ey, -ez)


def moon_radec(ts):
    """The Moon from the largest terms of Meeus' lunar theory, about a quarter of a degree."""
    t = centuries(ts)
    lp = 218.3164477 + 481267.88123421 * t
    d = math.radians(297.8501921 + 445267.1114034 * t)
    m = math.radians(357.5291092 + 35999.0502909 * t)
    mp = math.radians(134.9633964 + 477198.8675055 * t)
    f = math.radians(93.2720950 + 483202.0175233 * t)
    lam = math.radians(lp + 6.289 * math.sin(mp) + 1.274 * math.sin(2 * d - mp) + .658 * math.sin(2 * d)
                       + .214 * math.sin(2 * mp) - .186 * math.sin(m) - .114 * math.sin(2 * f))
    beta = math.radians(5.128 * math.sin(f) + .2806 * math.sin(mp + f) + .2777 * math.sin(mp - f)
                        + .1732 * math.sin(2 * d - f))
    return ecliptic_to_radec(math.cos(beta) * math.cos(lam), math.cos(beta) * math.sin(lam), math.sin(beta))


def moon_lit(ts):
    sun_ra, sun_dec = sun_radec(ts)
    moon_ra, moon_dec = moon_radec(ts)
    cos_e = (math.sin(sun_dec) * math.sin(moon_dec)
             + math.cos(sun_dec) * math.cos(moon_dec) * math.cos(sun_ra - moon_ra))
    return (1 - cos_e) / 2


def horizontal(ra, dec, lat, lon, ts):
    """(azimuth°, altitude°) of a right ascension and declination (radians) from a place."""
    lst = math.radians((280.46061837 + 360.98564736629 * (ts / 86400 + 2440587.5 - 2451545.0) + lon) % 360)
    hour = lst - ra
    lat = math.radians(lat)
    alt = math.asin(math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(hour))
    az = math.atan2(-math.cos(dec) * math.sin(hour),
                    math.sin(dec) * math.cos(lat) - math.cos(dec) * math.sin(lat) * math.cos(hour))
    return math.degrees(az) % 360, math.degrees(alt)


def bodies(lat, lon, ts):
    """Everything in the sky as (name, azimuth, altitude)."""
    found = [("Sun", *horizontal(*sun_radec(ts), lat, lon, ts)), ("Moon", *horizontal(*moon_radec(ts), lat, lon, ts))]
    for name in PLANETS:
        found.append((name, *horizontal(*planet_radec(name, ts), lat, lon, ts)))
    return found


def column(az, south_up):
    """Panel x for an azimuth: south in the middle (north below the equator)."""
    middle = 180 if south_up else 0
    return ((az - middle + 180) % 360) / 360 * 128


def row(alt):
    return HORIZON_ROW - alt / 90 * HORIZON_ROW


# --- drawing -------------------------------------------------------------------------------

@lru_cache(maxsize=48)
def sky_backdrop(sun_alt_step, sun_x, south_up):
    """The sky's colour for the Sun's height (in 1° steps), lighter around the Sun and the horizon.

    Worked out a quarter as wide and stretched: it is a soft gradient, and a full-size
    one is 18 ms on a Pi, which the time-lapse would need every other frame."""
    alt = sun_alt_step
    if alt <= -12:
        return Image.new("RGB", (128, 32))
    small = Image.new("RGB", (32, HORIZON_ROW + 1))
    pixels = small.load()
    for y in range(HORIZON_ROW + 1):
        near = y / HORIZON_ROW                     # 1 at the horizon
        for x in range(32):
            dx = min(abs(x * 4 + 2 - sun_x), 128 - abs(x * 4 + 2 - sun_x)) / 64   # 0 under the Sun
            if alt > 6:
                color = (round(10 + 30 * near), round(40 + 50 * near), round(120 + 50 * near))
            else:
                glow = max(0.0, 1 - dx * 1.6) * near ** 2 * (1 - (6 - alt) / 18)
                depth = (alt + 12) / 18
                color = (round(255 * glow), round(110 * glow + 30 * depth * near),
                         round(60 * depth + 50 * depth * near + 10 * glow))
            pixels[x, y] = color
    image = Image.new("RGB", (128, 32))
    image.paste(small.resize((128, HORIZON_ROW + 1), Image.BILINEAR), (0, 0))
    return image


def draw_ground(frame, south_up):
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, HORIZON_ROW + 1, 127, 31), fill=(0, 0, 0))
    draw.line((0, HORIZON_ROW + 1, 127, HORIZON_ROW + 1), fill=(40, 90, 40))
    for index, label in enumerate(COMPASS8):
        x = round(column(index * 45, south_up))
        if x >= 127:
            x = 0
        width = tiny_width(label)
        draw_tiny(frame, label, min(128 - width, max(0, x - width // 2)), 27,
                  WHITE if len(label) == 1 else GREY)


def draw_sky(frame, lat, lon, ts, t, labels=True):
    south_up = lat >= 0
    found = bodies(lat, lon, ts)
    sun_az, sun_alt = found[0][1], found[0][2]
    frame.paste(sky_backdrop(max(-13, min(7, round(sun_alt))), round(column(sun_az, south_up)), south_up), (0, 0))
    pixels = frame.load()
    if sun_alt < -6:   # the stars come out as the sky darkens
        fade = min(1.0, (-6 - sun_alt) / 8)
        for index, (ra, dec, mag) in enumerate(STARS):
            az, alt = horizontal(math.radians(ra * 15), math.radians(dec), lat, lon, ts)
            if alt < 1:
                continue
            twinkle = .82 + .18 * math.sin(t * 5 + index * 2.3)
            level = fade * twinkle * max(.32, min(1.0, 1.05 - mag * .3))
            pixels[int(column(az, south_up)) % 128, int(row(alt))] = (round(235 * level), round(235 * level),
                                                                       round(255 * level))
    taken = []
    for name, az, alt in found:
        if alt < -.5:
            continue
        x, y = column(az, south_up), row(max(alt, 0))
        if name == "Sun":
            ImageDraw.Draw(frame).ellipse((x - 2, y - 2, x + 2, y + 2), fill=(255, 220, 90))
            continue
        if name == "Moon":
            lit = moon_lit(ts)
            shade = round(90 + 160 * lit)
            ImageDraw.Draw(frame).ellipse((x - 1, y - 1, x + 1, y + 1), fill=(shade, shade, round(shade * .95)))
        else:
            if sun_alt > 0 and name != "Venus":
                continue                                    # lost in daylight
            pixels[int(x) % 128, int(y)] = PLANETS[name]
            pixels[(int(x) + 1) % 128, int(y)] = tuple(round(c * .5) for c in PLANETS[name])
        if labels:
            label = name.upper()
            width = tiny_width(label)
            lx = min(128 - width, max(0, round(x) - width // 2))
            ly = round(y) - 7 if y >= 8 else round(y) + 3
            if ly + 5 > HORIZON_ROW:
                ly = round(y) - 7
            if all(lx + width + 1 < left or lx > right + 1 or abs(ly - top) > 5 for left, right, top in taken):
                taken.append((lx, lx + width, ly))
                draw_tiny(frame, label, lx, ly, PLANETS.get(name, (200, 200, 205)))
    draw_ground(frame, south_up)


def rises_and_sets(name, lat, lon, ts):
    """("up"/"down" now, next rise, next set) in the coming day, to five minutes."""
    def altitude(when):
        if name == "Moon":
            return horizontal(*moon_radec(when), lat, lon, when)[1]
        return horizontal(*planet_radec(name, when), lat, lon, when)[1]

    now = altitude(ts)
    rise = setting = None
    previous = now
    for step in range(1, 289):
        when = ts + step * 300
        value = altitude(when)
        if previous < 0 <= value and rise is None:
            rise = when
        if previous >= 0 > value and setting is None:
            setting = when
        previous = value
    return now >= 0, rise, setting


@lru_cache(maxsize=2)
def almanac(lat, lon, bucket):
    """Rise and set for the Moon and planets, worked out once every five minutes."""
    return [rises_and_sets(name, lat, lon, bucket * 300) for name in ("Moon", *PLANETS)]


def clock(ts, now):
    local = datetime.fromtimestamp(ts, now.tzinfo)
    return local.strftime("%I:%M").lstrip("0") + ("AM" if local.hour < 12 else "PM")


class Home(Provider):
    """No network: hands the screen the home location (screens only get it through a provider)."""

    def __init__(self, context):
        self.context = context

    async def fetch(self):
        settings = self.context.settings
        home = (settings["latitude"], settings["longitude"])
        # Rise and set times here, once every five minutes, rather than in a frame.
        table = almanac(*home, int(time.time() // 300)) if home != (0, 0) else []
        return Snapshot({"home": home, "almanac": table})


class Sky(Module):
    name = "sky"

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def hold(self, context):
        return self.story.hold()

    def _home(self, context):
        snap = context.snapshots.get(self.name)
        return tuple(snap.data["home"]) if snap and snap.data else (0, 0)

    def available(self, context):
        return self._home(context) != (0, 0)

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        lat, lon = self._home(context)
        if (lat, lon) == (0, 0):
            draw_text(frame, "Set home first", 2, 12, GREY, mixed=True)
            return frame
        ts = context.now.timestamp()

        def build(visit):
            return [("now", NOW_SECONDS), ("lapse", LAPSE_SECONDS), ("planets", LIST_SECONDS)]

        self.story.sync(context.animation_time, build, context.scene)
        page, local, _ = self.story.current(context.animation_time, build) or ("now", 0, 0)
        if page == "now":
            draw_sky(frame, lat, lon, ts, context.animation_time)
            if local < 2.5:
                draw_tiny(frame, "SKY NOW", 1, 1, WHITE)
        elif page == "lapse":
            self._lapse(frame, lat, lon, ts, local, context)
        else:
            self._planets(frame, context.snapshots[self.name].data["almanac"], local, context)
        return frame

    def _lapse(self, frame, lat, lon, ts, local, context):
        """The next twelve hours in eleven seconds."""
        when = ts + local / LAPSE_SECONDS * 12 * 3600
        draw_sky(frame, lat, lon, when, context.animation_time, labels=True)
        text = clock(when, context.now)
        draw_tiny(frame, text, 1, 1, AMBER)
        width = tiny_width("NEXT 12 HOURS")
        draw_tiny(frame, "NEXT 12 HOURS", 127 - width, 1, GREY)

    def _planets(self, frame, table, local, context):
        rows = []
        ts = context.now.timestamp()
        for name, (up, rise, setting) in zip(("Moon", *PLANETS), table):
            rise = rise if rise and rise > ts else None
            setting = setting if setting and setting > ts else None
            up = up if setting or not rise else False
            if up:
                text = f"UP, SETS {clock(setting, context.now)}" if setting else "UP ALL DAY"
            elif rise:
                text = f"RISES {clock(rise, context.now)}"
            else:
                continue
            rows.append((name, text, up))
        rows.sort(key=lambda item: not item[2])
        page = int(local / (LIST_SECONDS / 2)) % max(1, math.ceil(len(rows) / 3))
        for index, (name, text, up) in enumerate(rows[page * 3:page * 3 + 3]):
            y = 1 + index * 11
            draw_text(frame, name, 0, y, PLANETS.get(name, WHITE), mixed=True)
            draw_tiny(frame, text, 128 - tiny_width(text), y + 1, WHITE if up else GREY)


plugin = Plugin(
    "sky", "Sky", module=Sky, provider=Home,
    defaults={"latitude": 0.0, "longitude": 0.0},
    help={"latitude": "Leave at 0 to use the home location from Settings"},
    ui={"latitude": {"type": "location", "label": "Location"}, "longitude": {"advanced": True}},
)
