from datetime import datetime, timezone
import io
from types import SimpleNamespace
import unittest

from PIL import Image, ImageDraw

import plugin as bodies

SETTINGS = {"latitude": 33.6, "longitude": -117.9, "earth_satellite": "west", "sun_band": "304"}


def context(ts, data, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts, timezone.utc), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"three_bodies": SETTINGS}},
                           snapshots={"three_bodies": SimpleNamespace(data=data)})


def jpeg(size, disc=True):
    image = Image.new("RGB", (size, size))
    if disc:
        ImageDraw.Draw(image).ellipse((size // 4, size // 5, size * 3 // 4, size * 7 // 10), fill=(250, 140, 30))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


class MoonTests(unittest.TestCase):
    def test_known_full_moon(self):
        # Full Moon 2024-01-25 17:54 UTC (US Naval Observatory).
        full = datetime(2024, 1, 25, 17, 54, tzinfo=timezone.utc).timestamp()
        self.assertGreater(bodies.lit_fraction(full), .99)
        found = bodies.next_phase(full - 5 * 86400, 180)
        self.assertLess(abs(found - full), 3 * 3600)

    def test_phase_names_follow_the_month(self):
        start = datetime(2026, 10, 11, tzinfo=timezone.utc).timestamp()
        names = [bodies.phase_name(start + day * 3600) for day in range(0, 30 * 24, 3)]
        self.assertIn("Full Moon", names)
        self.assertIn("Waning gibbous", names)


class PictureTests(unittest.TestCase):
    def test_sun_is_found_and_centred(self):
        raw = bodies.decode_sun(jpeg(400))
        image = Image.frombytes("RGB", (32, 32), raw)
        self.assertGreater(image.getpixel((16, 16))[0], 150)
        self.assertLess(sum(image.getpixel((0, 0))), 30)

    def test_blank_picture_is_refused(self):
        with self.assertRaises(ValueError):
            bodies.decode_sun(jpeg(200, disc=False))


class ScreenTests(unittest.TestCase):
    def test_moon_only_still_shows(self):
        module = bodies.ThreeBodies()
        ts = datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()
        frames = [module.render(context(ts, {}, t)) for t in (1, 4, 10, 14)]
        self.assertTrue(all(frame.getbbox() for frame in frames))

    def test_all_cards(self):
        module = bodies.ThreeBodies()
        ts = datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()
        disc = bodies.decode_sun(jpeg(400))
        data = {"sun": disc, "sun_at": ts - 300, "earth": disc, "earth_at": ts - 600, "satellite": "GOES-WEST",
                "flare": {"class": "M2.4", "at": ts - 7200}}
        frames = {module.render(context(ts, data, t)).tobytes() for t in (1, 3, 10, 17, 24, 30)}
        self.assertGreaterEqual(len(frames), 5)


if __name__ == "__main__":
    unittest.main()
