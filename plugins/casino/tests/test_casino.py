from types import SimpleNamespace
import unittest

import plugin as casino


def context(t, mode="auto", scene=1):
    return SimpleNamespace(animation_time=t, scene=scene,
                           config={"display": {"fps": 30}, "plugins": {"casino": {"mode": mode}}})


class PlinkoTests(unittest.TestCase):
    def test_every_chip_lands_in_a_slot(self):
        for seed in range(200):
            path, slot = casino.drop(seed)
            self.assertGreaterEqual(path[-1][1], casino.FLOOR)
            self.assertTrue(0 <= slot < len(casino.SLOTS))

    def test_chips_spread_across_the_board(self):
        slots = {casino.drop(seed)[1] for seed in range(300)}
        self.assertGreaterEqual(len(slots), 7)


class SlotTests(unittest.TestCase):
    def test_payouts(self):
        jackpots = wins = 0
        for seed in range(400):
            stops, win, jackpot = casino.spin(seed)
            names = [casino.STRIP[stop] for stop in stops]
            if jackpot:
                self.assertEqual(names, ["seven"] * 3)
                jackpots += 1
            if names[0] == names[1] == names[2]:
                self.assertEqual(win, casino.PAYS[names[0]])
            wins += bool(win)
        self.assertTrue(5 <= jackpots <= 40)
        self.assertGreater(wins, 80)

    def test_reels_settle_on_their_stop(self):
        self.assertEqual(casino.reel_offset(5, 10, casino.SPIN_STOPS[0], 3), 5 + 3 * len(casino.STRIP))


class ScreenTests(unittest.TestCase):
    def test_both_games_render(self):
        for mode in casino.MODES:
            module = casino.Casino()
            frames = set()
            t = 0.0
            while t < 20:
                frame = module.render(context(t, mode))
                self.assertEqual(frame.size, (128, 32))
                frames.add(frame.tobytes())
                t += 1 / 3
            self.assertGreater(len(frames), 30, mode)


if __name__ == "__main__":
    unittest.main()
