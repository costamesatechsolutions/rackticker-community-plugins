from dataclasses import replace
from datetime import datetime, timezone, timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rackticker import Snapshot
import rackticker_aquarium as aquarium

NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def context(settings=None, snapshot=None, t=0):
    return SimpleNamespace(animation_time=t, now=NOW,
        config={"display": {"fps": 30}, "plugins": {aquarium.NAME: {**aquarium.DEFAULTS, **(settings or {})}}},
        snapshots={aquarium.NAME: snapshot} if snapshot else {})


class FeedTests(unittest.TestCase):
    def feed(self, **changes):
        return json.dumps({"updated_at": NOW.isoformat(), "temperature_c": 25.4, "ph": 7.1, "light_on": False, **changes})

    def test_preserves_timestamp_and_marks_stale(self):
        stamp = NOW - timedelta(minutes=2)
        snap = aquarium.parse_readings(self.feed(updated_at=stamp.isoformat()), NOW)
        self.assertEqual(snap.updated_at, stamp)
        self.assertTrue(snap.stale)
        self.assertEqual(snap.source, "tank")

    def test_rejects_invalid_sensor_values_and_timestamps(self):
        for changes in ({"temperature_c": True}, {"temperature_c": float('nan')}, {"ph": 15},
                        {"light_on": "off"}, {"updated_at": ""},
                        {"updated_at": "2026-09-20T00:00:00"},
                        {"updated_at": (NOW + timedelta(minutes=2)).isoformat()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                aquarium.parse_readings(self.feed(**changes), NOW)

    def test_empty_or_non_object_feed_rejected(self):
        for raw in ('[]', '{}', json.dumps({"updated_at": NOW.isoformat()})):
            with self.assertRaises(ValueError):
                aquarium.parse_readings(raw, NOW)

    def test_settings_validation(self):
        for changes in ({"fish_count": 1.5}, {"fish_count": 99}, {"speed": float('inf')},
                        {"tank_url": "file:///etc/passwd"}, {"tank_url": "https://user:pass@example.com"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                aquarium.validate({**aquarium.DEFAULTS, **changes})


class RenderTests(unittest.TestCase):
    def test_frames_across_modes_extremes_and_time_resets(self):
        module = aquarium.Aquarium()
        for habitat in ('reef', 'planted'):
            for lighting in ('day', 'night', 'cycle'):
                for t in (0, 3, 79.9, 80, 119.9, 120, 1000000, 0):
                    frame = module.render(context({'habitat': habitat, 'lighting': lighting, 'fish_count': 12}, t=t))
                    self.assertEqual(frame.size, (128, 32))
                    self.assertEqual(frame.mode, 'RGB')
                    self.assertIsNotNone(frame.getbbox())

    def test_animation_moves_and_repeated_time_is_deterministic(self):
        module = aquarium.Aquarium()
        first = module.render(context(t=1)).tobytes()
        self.assertNotEqual(first, module.render(context(t=2)).tobytes())
        self.assertEqual(first, module.render(context(t=1)).tobytes())

    def test_live_light_and_stale_status(self):
        settings = {**aquarium.DEFAULTS, 'tank_url': 'https://example.com/tank', 'show_readings': False}
        snap = Snapshot({'light_on': False}, updated_at=NOW, source='tank', metadata={'endpoint': aquarium.endpoint_id(settings)})
        module = aquarium.Aquarium()
        live = module.render(context(settings, snap))
        night = module.render(context({'lighting': 'night'}))
        self.assertEqual(live.tobytes(), night.tobytes())
        snap = replace(snap, stale=True)
        with patch.object(aquarium, 'draw_text') as draw:
            module.render(context(settings, snap))
            self.assertEqual(draw.call_args.args[1], 'STALE')

    def test_changed_endpoint_hides_previous_tank(self):
        settings = {**aquarium.DEFAULTS, 'tank_url': 'https://example.com/new'}
        snap = Snapshot({'temperature_c': 25}, updated_at=NOW, source='tank', metadata={'endpoint': 'old'})
        with patch.object(aquarium, 'draw_text') as draw:
            aquarium.Aquarium().render(context(settings, snap))
            self.assertEqual(draw.call_args.args[1], 'NO DATA')


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_offline_never_opens_network(self):
        provider = aquarium.Tank(SimpleNamespace(settings=aquarium.DEFAULTS))
        with patch.object(aquarium.aiohttp, 'ClientSession', side_effect=AssertionError('network')):
            self.assertEqual((await provider.fetch()).source, 'simulation')
        await provider.close()
        await provider.close()

    async def test_bounded_feed_and_no_redirects(self):
        class Content:
            async def iter_chunked(self, size):
                for _ in range(5):
                    yield b'x' * size
        class Response:
            status = 200
            content = Content()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        class Session:
            closed = False
            def get(self, url, **kwargs):
                self.kwargs = kwargs
                return Response()
        provider = aquarium.Tank(SimpleNamespace(settings={**aquarium.DEFAULTS, 'tank_url': 'https://example.com', 'tank_token': 'test'}))
        provider.session = Session()
        with self.assertRaisesRegex(ValueError, '16 KiB'):
            await provider.fetch()
        self.assertFalse(provider.session.kwargs['allow_redirects'])
        self.assertEqual(provider.session.kwargs['headers'], {'Authorization': 'Bearer test'})


if __name__ == '__main__':
    unittest.main()
