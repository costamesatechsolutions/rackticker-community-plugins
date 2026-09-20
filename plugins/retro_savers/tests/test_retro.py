import math
from types import SimpleNamespace
import unittest

import plugin as retro


def context(t=0, scene=1, **settings):
    return SimpleNamespace(animation_time=t, scene=scene,
        config={'display': {'fps': 30}, 'plugins': {'retro_savers': {**retro.DEFAULTS, **settings}}})


class RetroTests(unittest.TestCase):
    def test_all_modes_animate_without_empty_frames(self):
        for mode in retro.MODES:
            module = retro.RetroSavers()
            frames = []
            for t in (0, .5, 2, 17.99, 18, 32, 1000000):
                frame = module.render(context(t, mode=mode))
                self.assertEqual(frame.size, (128, 32))
                self.assertEqual(frame.mode, 'RGB')
                self.assertIsNotNone(frame.getbbox(), (mode, t))
                frames.append(frame.tobytes())
            self.assertGreater(len(set(frames)), 3, mode)

    def test_rotate_reaches_every_mode_in_one_visit(self):
        module = retro.RetroSavers()
        self.assertEqual([module.mode_at(context(i * 16), retro.DEFAULTS) for i in range(5)], list(retro.MODES))

    def test_short_playlist_visits_advance_modes(self):
        module = retro.RetroSavers()
        modes = []
        for scene in range(1, 7):
            modes.append(module.mode_at(context(0, scene), retro.DEFAULTS))
            module.mode_at(context(4, scene), retro.DEFAULTS)
        self.assertEqual(modes, [*retro.MODES, 'pipes'])

    def test_same_frame_does_not_advance_and_reset_does(self):
        module = retro.RetroSavers()
        self.assertEqual(module.render(context()).tobytes(), module.render(context()).tobytes())
        module.render(context(5))
        self.assertEqual(module.mode_at(context(0), retro.DEFAULTS), 'mystify')

    def test_fixed_mode_stays_selected_across_visits(self):
        module = retro.RetroSavers()
        settings = {**retro.DEFAULTS, 'mode': 'pipes'}
        for scene in range(5):
            self.assertEqual(module.mode_at(context(0, scene), settings), 'pipes')

    def test_routes_are_bounded_adjacent_and_nonintersecting_in_3d(self):
        for seed in (0, 95, 12345, 99999):
            seen = set()
            for path in retro.pipe_paths(seed):
                self.assertLessEqual(len(path), 26)
                for point in path:
                    self.assertNotIn(point, seen)
                    seen.add(point)
                    x, y = retro.project(point)
                    self.assertTrue(2 <= x <= 125 and 2 <= y <= 29)
                for a, b in zip(path, path[1:]):
                    self.assertEqual(sum(abs(c - d) for c, d in zip(a, b)), 1)

    def test_caches_are_bounded_over_many_epochs(self):
        module = retro.RetroSavers()
        for epoch in range(50):
            module.render(context(epoch * 18, mode='pipes'))
            self.assertLessEqual(sum(len(path) for path in module._paths), 78)
        module.render(context(mode='starfield', star_count=100))
        self.assertEqual(len(module._stars), 100)
        module.render(context(mode='starfield', star_count=15))
        self.assertEqual(len(module._stars), 15)

    def test_invalid_settings_rejected(self):
        for change in ({'speed': math.nan}, {'seed': -1}, {'star_count': 1000},
                       {'seconds_per_mode': 6.1}, {'message': ''}, {'message': 'x' * 33}, {'message': 'W' * 11}, {'message': '🐟'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                retro.validate({**retro.DEFAULTS, **change})

    def test_marquee_extremes_render_and_never_hold_playlist(self):
        module = retro.RetroSavers()
        for message in ('A', 'WINDOWS XP FOREVER'):
            for t in (0, 1, 5, 15):
                ctx = context(t, mode='marquee', message=message)
                module.render(ctx)
                self.assertFalse(module.hold(ctx))
                self.assertEqual(module.refresh_interval(ctx), 1 / 30)


if __name__ == '__main__':
    unittest.main()
