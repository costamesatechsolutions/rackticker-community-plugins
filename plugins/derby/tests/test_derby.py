from datetime import datetime
from types import SimpleNamespace
import unittest

import plugin as derby


def context(t, scene=1):
    return SimpleNamespace(scene=scene, now=datetime(2026, 10, 11, 20, 0).astimezone(), animation_time=t,
                           config={"display": {"fps": 30}})


class RaceTests(unittest.TestCase):
    def test_every_horse_finishes_and_order_matches_times(self):
        for seed in range(40):
            info = derby.race(seed)
            self.assertTrue(all(time is not None for time in info["finish"]))
            times = [info["finish"][horse] for horse in info["order"]]
            self.assertEqual(times, sorted(times))
            self.assertEqual(len(set(info["names"])), derby.FIELD)

    def test_payouts_are_real_tote_prices(self):
        for seed in range(40):
            for price in derby.payouts(derby.race(seed)):
                self.assertGreaterEqual(price, 2.1)
                self.assertAlmostEqual(price * 5, round(price * 5))

    def test_a_whole_race_renders_including_a_photo(self):
        photo = next(seed for seed in range(500)
                     if (lambda r: r["finish"][r["order"][1]] - r["finish"][r["order"][0]])(derby.race(seed)) < .05)
        for seed in (0, photo):
            module = derby.Derby()
            module._race(context(0))
            module.seed = seed
            length, _ = module._length(derby.race(seed))
            frames = set()
            t = 0.0
            while t < length:
                frame = module.render(context(t))
                self.assertEqual(frame.size, (128, 32))
                frames.add(frame.tobytes())
                t += .25
            self.assertGreater(len(frames), 60)
            self.assertTrue(module.hold(context(length - .5)))
            self.assertFalse(module.hold(context(length + .1)))

    def test_new_visit_new_race(self):
        module = derby.Derby()
        first = module._race(context(0, scene=1))
        second = module._race(context(0, scene=2))
        self.assertNotEqual(first["names"], second["names"])


if __name__ == "__main__":
    unittest.main()
