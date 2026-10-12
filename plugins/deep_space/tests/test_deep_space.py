from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import plugin as deep

TABLE = """header
$$SOE
 2026-Oct-12 00:00, , ,  172.0146366300, 16.8816483,  172.443936741661, 37.4062160,
 2026-Oct-13 00:00, , ,  172.0243853839, 16.8816450,  172.465474635611, 37.1807715,
 2026-Nov-30 00:00, , ,  172.4900000000, 16.8816000,  173.300000000000, 20.0000000,
$$EOE
footer"""


def context(ts, data, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts, timezone.utc), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"deep_space": {"units": "imperial"}}},
                           snapshots={"deep_space": SimpleNamespace(data=data)})


class DistanceTests(unittest.TestCase):
    def test_parse_and_carry_forward(self):
        rows = deep.parse(TABLE)
        self.assertEqual(len(rows), 3)
        start = datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp()
        km = deep.distance_km(rows, start + 3600, "earth")
        self.assertAlmostEqual(km, 172.443936741661 * deep.AU + 37.406216 * 3600, places=0)

    def test_light_day_found_between_rows(self):
        rows = deep.parse(TABLE)
        when = deep.light_day(rows, rows[0][0])
        self.assertTrue(rows[1][0] < when < rows[2][0])

    def test_light_time(self):
        self.assertEqual(deep.light_time(deep.LIGHT * 3600 * 23.91), "23H 54M")

    def test_no_table(self):
        with self.assertRaises(ValueError):
            deep.parse("Horizons is down")


class ScreenTests(unittest.TestCase):
    def test_cards(self):
        rows = deep.parse(TABLE)
        data = {"-31": rows, "-96": rows}
        module = deep.DeepSpace()
        frames = {module.render(context(rows[0][0] + 60, data, t)).tobytes() for t in (0, 5, 9, 13, 17, 21)}
        self.assertGreaterEqual(len(frames), 3)
        self.assertFalse(module.available(context(0, {})))


if __name__ == "__main__":
    unittest.main()
