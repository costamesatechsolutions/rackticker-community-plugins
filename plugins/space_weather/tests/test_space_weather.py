import json
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import plugin as sw

SETTINGS = {"latitude": 0.0, "longitude": 0.0, "alert": True}


def context(t, data):
    return SimpleNamespace(now=datetime(2026, 10, 12, 1, tzinfo=timezone.utc), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"space_weather": SETTINGS}},
                           snapshots={"space_weather": SimpleNamespace(data=data)})


class ScaleTests(unittest.TestCase):
    def test_flare_classes(self):
        self.assertEqual(sw.flare_class(3.2e-7), "B3.2")
        self.assertEqual(sw.flare_class(1.1e-6), "C1.1")
        self.assertEqual(sw.flare_class(2.5e-4), "X2.5")

    def test_aurora_reach(self):
        self.assertEqual(sw.kp_for_aurora(sw.magnetic_latitude(33.64, -117.92)), 9)   # Southern California
        self.assertEqual(sw.kp_for_aurora(sw.magnetic_latitude(47.6, -122.3)), 7)     # Seattle
        self.assertIsNone(sw.kp_for_aurora(sw.magnetic_latitude(25.8, -80.2)))        # Miami

    def test_xrays_keep_the_long_channel(self):
        rows = [{"time_tag": f"2026-10-11T18:{m:02d}:00Z", "energy": energy, "flux": flux}
                for m in range(3) for energy, flux in (("0.05-0.4nm", 1e-9), ("0.1-0.8nm", 1e-6 * (m + 1)))]
        self.assertEqual(sw.parse_xrays(json.dumps(rows)), [1e-6, 2e-6, 3e-6])


class ScreenTests(unittest.TestCase):
    def test_every_card(self):
        start = datetime(2026, 10, 11, 12, tzinfo=timezone.utc).timestamp()
        data = {"kp": 5.3, "g": 1, "speed": 640, "bz": -9, "bt": 12, "xrays": [1e-6 * (1 + i % 50) for i in range(360)],
                "bars": [(start + i * 10800, i % 9, i < 5) for i in range(16)], "home": (47.6, -122.3)}
        module = sw.SpaceWeather()
        frames = {module.render(context(t, data)).tobytes() for t in (1, 5, 9, 13, 17, 21, 25, 29)}
        self.assertGreaterEqual(len(frames), 6)

    def test_nothing_yet(self):
        self.assertFalse(sw.SpaceWeather().available(context(0, {})))


if __name__ == "__main__":
    unittest.main()
