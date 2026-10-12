from datetime import datetime
import time
from types import SimpleNamespace
import unittest

import plugin as iss

L1 = "1 25544U 98067A   26284.17638745  .00009430  00000+0  18014-3 0  9995"
L2 = "2 25544  51.6312  86.0933 0006713 248.1316 111.8959 15.48821882589734"
HOME = (33.64, -117.92)
SETTINGS = {"latitude": 0.0, "longitude": 0.0, "units": "imperial", "alert": True, "alert_lead_minutes": 2}


def context(ts, data, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts).astimezone(), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"iss": SETTINGS}},
                           snapshots={"iss": SimpleNamespace(data=data)})


class OrbitTests(unittest.TestCase):
    def test_position_matches_a_known_fix(self):
        # wheretheiss.at reported 48.7015, 114.7647, 430 km at this moment.
        ts = 1791765640
        lat, lon, alt = iss.geodetic(iss.to_ecef(iss.eci(iss.parse_tle(L1, L2), ts), ts))
        self.assertAlmostEqual(lat, 48.70, delta=.3)
        self.assertAlmostEqual(lon, 114.76, delta=.3)
        self.assertAlmostEqual(alt, 430, delta=15)

    def test_passes_are_dark_sky_and_in_order(self):
        start = 1791765640
        passes = iss.find_passes(L1, L2, *HOME, start)
        self.assertTrue(passes)
        observer = iss.site(*HOME)
        for found in passes:
            self.assertLess(found["start"], found["end"])
            self.assertGreaterEqual(found["max"], 10)
            self.assertLess(iss.sun_elevation(observer, found["start"]), -6)
        self.assertEqual(passes, sorted(passes, key=lambda found: found["start"]))

    def test_over_names_land_and_sea(self):
        self.assertEqual(iss.over(39, -98), "United States")
        self.assertEqual(iss.over(0, -150), "Pacific")
        self.assertEqual(iss.over(-20, 80), "Indian Ocean")
        self.assertEqual(iss.over(30, -40), "Atlantic")


class ScreenTests(unittest.TestCase):
    def test_pages_and_take_over_render(self):
        start = 1791765640
        passes = iss.find_passes(L1, L2, *HOME, start)
        data = {"tle": (L1, L2), "crew": [{"name": "Jessica Watkins", "country": "United States"}],
                "home": HOME, "passes": passes}
        module = iss.Station()
        frames = [module.render(context(start, data, t)).tobytes() for t in (0, 3, 9, 15, 21, 27)]
        self.assertGreater(len(set(frames)), 3)
        during = module.render(context(passes[0]["start"] + 30, data))
        self.assertIsNotNone(during.getbbox())
        self.assertNotEqual(during.tobytes(), frames[0])

    def test_unavailable_without_an_orbit(self):
        self.assertFalse(iss.Station().available(context(time.time(), {"tle": None})))


if __name__ == "__main__":
    unittest.main()
