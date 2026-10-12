from datetime import datetime, timezone
import math
from types import SimpleNamespace
import unittest

import plugin as sky

HOME = (33.64, -117.92)


def context(ts, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts).astimezone(), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"sky": {"latitude": 0.0, "longitude": 0.0}}},
                           snapshots={"sky": SimpleNamespace(data={"home": HOME, "almanac": sky.almanac(*HOME, int(ts // 300))})})


def separation(a, b):
    (ra1, dec1), (ra2, dec2) = a, b
    return math.degrees(math.acos(math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)))


class AstronomyTests(unittest.TestCase):
    def test_sun_at_the_june_solstice(self):
        ts = datetime(2026, 6, 21, 8, 24, tzinfo=timezone.utc).timestamp()
        self.assertAlmostEqual(math.degrees(sky.sun_radec(ts)[1]), 23.44, delta=.05)

    def test_noon_sun_is_south_and_high(self):
        ts = datetime(2026, 6, 21, 19, 53, 30, tzinfo=timezone.utc).timestamp()     # local solar noon, Costa Mesa
        az, alt = sky.horizontal(*sky.sun_radec(ts), *HOME, ts)
        self.assertAlmostEqual(az, 180, delta=3)
        self.assertAlmostEqual(alt, 90 - 33.64 + 23.44, delta=.5)

    def test_great_conjunction_2020(self):
        # Jupiter and Saturn were a tenth of a degree apart on 21 December 2020.
        ts = datetime(2020, 12, 21, 18, tzinfo=timezone.utc).timestamp()
        self.assertLess(separation(sky.planet_radec("Jupiter", ts), sky.planet_radec("Saturn", ts)), .3)

    def test_full_moon_is_opposite_the_sun(self):
        ts = datetime(2024, 1, 25, 17, 54, tzinfo=timezone.utc).timestamp()
        self.assertGreater(separation(sky.moon_radec(ts), sky.sun_radec(ts)), 174)   # opposite in longitude; the Moon rides up to 5° off the ecliptic
        self.assertGreater(sky.moon_lit(ts), .99)


class ScreenTests(unittest.TestCase):
    def test_cards_render_day_and_night(self):
        for hour in (19, 5):    # noon and 10 pm in California
            ts = datetime(2026, 10, 11, hour, tzinfo=timezone.utc).timestamp()
            module = sky.Sky()
            frames = [module.render(context(ts, t)) for t in (0, 1, 13, 18, 25)]
            self.assertTrue(all(frame.getbbox() for frame in frames))
            self.assertGreater(len({frame.tobytes() for frame in frames}), 2)

    def test_needs_a_home(self):
        missing = context(0)
        missing.snapshots = {}
        self.assertFalse(sky.Sky().available(missing))


if __name__ == "__main__":
    unittest.main()
