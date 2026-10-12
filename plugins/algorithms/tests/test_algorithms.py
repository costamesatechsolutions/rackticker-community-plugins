from types import SimpleNamespace
import random
import unittest

import plugin as algo


def context(t, mode="auto", scene=1):
    return SimpleNamespace(animation_time=t, scene=scene,
                           config={"display": {"fps": 30}, "plugins": {"algorithms": {"mode": mode}}})


class SortTests(unittest.TestCase):
    def test_every_algorithm_sorts(self):
        values = list(range(1, algo.BARS + 1))
        random.Random(4).shuffle(values)
        for name in algo.NAMES:
            steps = algo.record(name, values)
            self.assertEqual(list(steps[-1][0]), sorted(values), name)
            self.assertEqual(list(steps[0][0]), values, name)

    def test_the_fast_one_is_in_every_race(self):
        for seed in range(20):
            left, right, _, _ = algo.race(seed)
            self.assertTrue({left, right} & {"quick", "merge", "heap", "shell"})
            self.assertNotEqual(left, right)

    def test_no_pink(self):
        for value in range(1, algo.BARS + 1):
            r, g, b = algo.bar_color(value)
            self.assertFalse(r > 180 and b > 120 and g < 120, value)


class MazeTests(unittest.TestCase):
    def test_every_cell_reached_and_path_connects(self):
        carved, flood, path, start, goal = algo.maze(3)
        self.assertEqual(len(carved), algo.COLS * algo.ROWS)
        self.assertEqual((path[0], path[-1]), (start, goal))
        for a, b in zip(path, path[1:]):
            self.assertEqual(abs(a[0] - b[0]) + abs(a[1] - b[1]), 1)


class ScreenTests(unittest.TestCase):
    def test_both_render(self):
        for mode in algo.MODES:
            module = algo.Algorithms()
            frames = {module.render(context(t, mode)).tobytes() for t in (0, 3, 8, 12, 17, 20, 24)}
            self.assertGreater(len(frames), 5, mode)


if __name__ == "__main__":
    unittest.main()
