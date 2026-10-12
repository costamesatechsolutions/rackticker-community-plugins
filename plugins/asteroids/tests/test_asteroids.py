from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import plugin as rocks

PAYLOAD = {"fields": ["des", "orbit_id", "jd", "cd", "dist", "dist_min", "dist_max", "v_rel", "v_inf", "t_sigma_f",
                      "h", "diameter", "diameter_sigma", "fullname"],
           "data": [["2026 TG9", "1", "0", "2026-Oct-14 04:57", "0.00151910155122952", "0", "0", "11.63", "11.4",
                     "00:21", "27.025", None, None, "       (2026 TG9)"],
                    ["99942", "1", "0", "2029-Apr-13 21:46", "0.000254", "0", "0", "7.42", "5.8", "00:01", "19.09",
                     "0.34", None, "  99942 Apophis (2004 MN4)"],
                    ["bad", "1", "0", "someday", "x"]]}
SETTINGS = {"within_moon_distances": 10, "cards": 4, "alert": True}


def context(ts, rows, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts, timezone.utc), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"asteroids": SETTINGS}},
                           snapshots={"asteroids": SimpleNamespace(data=rows)})


class ParseTests(unittest.TestCase):
    def test_rows(self):
        rows = rocks.parse(PAYLOAD)
        self.assertEqual([row["name"] for row in rows], ["2026 TG9", "Apophis"])
        self.assertAlmostEqual(rows[0]["ld"], .59, places=2)
        self.assertEqual(rocks.like(rows[0]["meters"]), "A HOUSE")   # H 27.0: about 14 m
        self.assertAlmostEqual(rows[1]["meters"], 340)       # measured, not guessed from brightness

    def test_sizes(self):
        self.assertEqual(rocks.like(3), "A CAR")
        self.assertEqual(rocks.like(150), "A STADIUM")
        self.assertEqual(rocks.like(5000), "A CITY")


class ScreenTests(unittest.TestCase):
    def test_cards(self):
        rows = rocks.parse(PAYLOAD)
        module = rocks.Asteroids()
        ts = rows[0]["at"] - 86400
        frames = {module.render(context(ts, rows, t)).tobytes() for t in (0, 3, 7, 9, 11, 14, 17, 19)}
        self.assertGreater(len(frames), 4)
        self.assertFalse(module.available(context(ts, [])))


if __name__ == "__main__":
    unittest.main()
