from datetime import datetime, timezone
import random
import statistics
from types import SimpleNamespace
import unittest

import plugin as ball


def context(ts):
    return SimpleNamespace(now=datetime.fromtimestamp(ts, timezone.utc), animation_time=0, scene=1,
                           config={"display": {"fps": 30}})


class GameTests(unittest.TestCase):
    def test_games_look_like_baseball(self):
        runs = []
        for number in range(150):
            g = ball.game(number)
            runs += [g["score"]["away"], g["score"]["home"]]
            self.assertTrue(g["score"]["away"] != g["score"]["home"] or g["innings"] >= 12)
            self.assertLessEqual(g["length"], ball.SLOT - ball.FINAL + 1e-6)
            for play in g["plays"]:
                self.assertLessEqual(play["outs"], 3)
        self.assertTrue(3 < statistics.mean(runs) < 5.5)

    def test_runners(self):
        rng = random.Random(1)
        self.assertEqual(ball.walk([True, True, True]), ([True, True, True], 1))
        self.assertEqual(ball.walk([False, True, False]), ([True, True, False], 0))
        self.assertEqual(ball.advance([True, True, True], 4, rng), ([False, False, False], 4))
        bases, scored = ball.advance([False, False, True], 1, rng)
        self.assertEqual((bases, scored), ([True, False, False], 1))

    def test_names_fit(self):
        self.assertEqual(ball.fit_name("Long Beach Lighthouses", 100), "Lighthouses")
        self.assertEqual(ball.fit_name("Irvine Owls", 100), "Irvine Owls")


class ScreenTests(unittest.TestCase):
    def test_a_whole_slot_renders(self):
        module = ball.PocketBaseball()
        start = ball.OPENING_DAY + 1234 * ball.SLOT
        frames = {module.render(context(start + s)).tobytes() for s in range(0, int(ball.SLOT), 7)}
        self.assertGreater(len(frames), 40)


if __name__ == "__main__":
    unittest.main()
