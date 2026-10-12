from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import plugin as sats

ISS = ("ISS (ZARYA)", "1 25544U 98067A   26284.17638745  .00009430  00000+0  18014-3 0  9995",
       "2 25544  51.6312  86.0933 0006713 248.1316 111.8959 15.48821882589734")
TEXT = "\n".join(ISS) + "\nBROKEN\n1 nonsense\n"
HOME = (33.64, -117.92)


def context(ts, data, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts, timezone.utc), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"satellites": {}}},
                           snapshots={"satellites": SimpleNamespace(data=data)})


class WorkTests(unittest.TestCase):
    def test_catalogue_parse_skips_junk(self):
        self.assertEqual(sats.parse_catalogue(TEXT), [ISS])

    def test_groups(self):
        self.assertEqual(sats.group("STARLINK-1007"), "starlink")
        self.assertEqual(sats.group("ONEWEB-0012"), "oneweb")
        self.assertEqual(sats.group("KUIPER-00010"), "kuiper")
        self.assertEqual(sats.group("ISS (ZARYA)"), "station")
        self.assertEqual(sats.group("GOES 18"), "other")

    def test_positions_find_the_station_when_it_is_up(self):
        start = 1791765640
        found = []
        for minute in range(0, 24 * 60, 2):
            found = sats.positions([ISS], *HOME, start + minute * 60, start + minute * 60 + 30)
            if found and found[0][2] > 10:
                break
        self.assertTrue(found)
        self.assertEqual(found[0][0], "station")
        self.assertEqual(found[0][6], "ISS")


class ScreenTests(unittest.TestCase):
    def test_swarm_and_counts(self):
        data = {"start": 1000.0, "span": 30, "home": HOME, "dark": True, "total": 3,
                "sats": [("starlink", 100, 20, 110, 25, True, ""), ("other", 180, 50, 180, 50, False, ""),
                         ("station", 250, 40, 260, 45, True, "ISS")]}
        module = sats.Satellites()
        frames = {module.render(context(1000 + t, data, t)).tobytes() for t in (0, 5, 10, 13, 16)}
        self.assertGreater(len(frames), 3)
        self.assertEqual(len(module._now(data, 1015)), 3)
        self.assertFalse(module.available(context(0, None)))


if __name__ == "__main__":
    unittest.main()
