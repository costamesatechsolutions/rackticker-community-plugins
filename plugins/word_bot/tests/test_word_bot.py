from types import SimpleNamespace
import unittest

import plugin as bot


def context(t, games, scene=1):
    return SimpleNamespace(animation_time=t, scene=scene, config={"display": {"fps": 30}},
                           snapshots={"word_bot": SimpleNamespace(data=games)})


class ScoreTests(unittest.TestCase):
    def test_repeated_letters(self):
        self.assertEqual(bot.score("speed", "abide"), (0, 0, 1, 0, 1))
        self.assertEqual(bot.score("eerie", "there"), (1, 0, 1, 0, 2))
        self.assertEqual(bot.score("crane", "crane"), (2, 2, 2, 2, 2))

    def test_words_are_clean(self):
        self.assertTrue(all(len(word) == 5 and word.isalpha() and word.islower() for word in bot.WORDS))
        self.assertIn(bot.OPENER, bot.WORDS)


class SolverTests(unittest.TestCase):
    def test_solves_almost_everything_quickly(self):
        sample = bot.WORDS[::7]
        results = [bot.solve(word) for word in sample]
        solved = [moves for moves in results if moves[-1][1] == (2, 2, 2, 2, 2)]
        self.assertGreaterEqual(len(solved), len(sample) - 2)
        self.assertLess(sum(len(moves) for moves in results) / len(results), 4)
        for word, moves in zip(sample, results):
            self.assertEqual(moves[0][0], bot.OPENER)
            if moves[-1][1] == (2, 2, 2, 2, 2):
                self.assertEqual(moves[-1][0], word)


class ScreenTests(unittest.TestCase):
    def test_plays_through_games(self):
        games = bot.solve_many(1, 5)
        module = bot.WordBot()
        frames = set()
        t = 0.0
        while t < 40:
            frames.add(module.render(context(t, games)).tobytes())
            t += .2
        self.assertGreater(len(frames), 60)
        self.assertFalse(module.available(context(0, None)))


if __name__ == "__main__":
    unittest.main()
