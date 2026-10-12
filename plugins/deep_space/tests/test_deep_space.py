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


class OdometerTests(unittest.TestCase):
    def pixels(self, value, rate=1.0):
        from PIL import Image
        frame = Image.new("RGB", (40, 12))
        deep.odometer(frame, value, 0, 1, (236, 238, 236), rate, "MI")
        return frame.crop((0, 0, 18, 12)).tobytes()  # the digits only, not the unit

    def test_a_wheel_at_rest_matches_plain_digits(self):
        from PIL import Image
        from rackticker import draw_text
        plain = Image.new("RGB", (40, 12))
        draw_text(plain, "216", 0, 1, (236, 238, 236))
        self.assertEqual(self.pixels(216.0), plain.crop((0, 0, 18, 12)).tobytes())
        self.assertEqual(self.pixels(216.5), plain.crop((0, 0, 18, 12)).tobytes())  # resting mid-unit

    def test_a_slow_wheel_rolls_to_the_next_digit_without_jumping(self):
        # At 1 a second the turn takes the last 0.35 of each unit; sampled finely, every
        # row of travel is seen on the way from 216 to 217, and the end is 217 exactly.
        from PIL import Image
        from rackticker import draw_text
        tops = [deep.wheel_position(216 + k / 200, 0, 1.0) for k in range(201)]
        self.assertTrue(all(b >= a for a, b in zip(tops, tops[1:])))
        self.assertEqual(len({round(top * 8) for top in tops}), 9)
        plain = Image.new("RGB", (40, 12))
        draw_text(plain, "217", 0, 1, (236, 238, 236))
        self.assertEqual(self.pixels(217.0), plain.crop((0, 0, 18, 12)).tobytes())

    def test_a_shrinking_distance_rolls_back(self):
        self.assertEqual(deep.wheel_position(217.0, 0, -1.0), 7)
        self.assertGreater(deep.wheel_position(216.99, 0, -1.0), 6.9)

    def test_tens_turn_while_units_pass_nine(self):
        # Voyager at 17 a second: the units flick (too fast to roll), the tens take the
        # last 0.35 s of each ten to roll (from about 4 in the units) and rest otherwise.
        self.assertEqual(deep.wheel_position(1203.0, 1, 17.0), 0)
        self.assertTrue(0 < deep.wheel_position(1207.0, 1, 17.0) < 1)
        self.assertGreater(deep.wheel_position(1209.99, 1, 17.0), .99)
        self.assertEqual(deep.wheel_position(1210.0, 1, 17.0), 1)

    def test_fast_units_wheel_shows_its_digit_dimmed(self):
        from PIL import Image
        frame = Image.new("RGB", (40, 12))
        deep.odometer(frame, 1234.4, 0, 1, (236, 238, 236), 17.0, "KM")
        units = frame.crop((24, 0, 30, 12))  # "1,23" then the units wheel
        self.assertTrue(units.getbbox())
        self.assertLess(max(units.getdata())[0], 236)

    def test_the_distance_moves_every_frame_not_once_a_second(self):
        module = deep.DeepSpace()
        start = deep.parse(TABLE)[0][0] + 60
        # In-process: context.now changes only on the whole second.
        seen = [module._clock(context(start + t // 30, {}, t / 30)) for t in range(300)]
        steps = [b - a for a, b in zip(seen, seen[1:])]
        self.assertTrue(all(step > 0 for step in steps))
        self.assertLess(max(steps) / min(steps), 1.2)  # an even pace, no catching up each second
        self.assertLess(abs(seen[-1] - (start + 10)), 1)

    def test_a_sandbox_now_that_wobbles_never_moves_it_backwards(self):
        # In a sandbox, now is the second the batch was asked in plus how far ahead the
        # frame is: it repeats and steps back a little at each batch, as on the Pi.
        import random
        module = deep.DeepSpace()
        start, rng, seen = 1_800_000_000, random.Random(1), []
        for frame in range(600):
            t = frame / 30
            asked = t - (frame % 4) / 30
            wall = start + int(asked) + (t - asked) + rng.uniform(-.05, .05)
            seen.append(module._clock(SimpleNamespace(now=datetime.fromtimestamp(wall, timezone.utc), animation_time=t)))
        self.assertTrue(all(b >= a for a, b in zip(seen, seen[1:])))
        steps = [b - a for a, b in zip(seen, seen[1:])]
        self.assertGreater(min(steps[30:]), 0)
        self.assertLess(abs(seen[-1] - (start + 20)), 1.5)

    def test_a_new_visit_starts_from_the_wall_clock(self):
        module = deep.DeepSpace()
        module._clock(context(1_800_000_000, {}, 50.0))
        self.assertAlmostEqual(module._clock(context(1_800_000_900, {}, 0.0)), 1_800_000_900, delta=.01)


if __name__ == "__main__":
    unittest.main()
