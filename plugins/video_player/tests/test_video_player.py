import asyncio
from types import SimpleNamespace
import unittest
from unittest import mock

import plugin as video


class WatchTimeTests(unittest.TestCase):
    def setUp(self):
        video.WATCHED.update(seconds=0.0, last=None)

    def test_only_time_on_the_panel_counts(self):
        for step in range(30):                  # a second of frames
            video.watched(100 + step / 30)
        video.watched(500)                      # the screen was off for minutes
        video.watched(500 + 1 / 30)
        self.assertAlmostEqual(video.WATCHED["seconds"], 29 / 30 + 1 / 30, places=3)

    def test_a_youtube_pick_is_not_replaced_until_it_has_been_watched(self):
        """It used to resolve a new pick every watch_seconds of wall time, all day."""
        settings = dict(video.plugin.defaults, youtube="@channel", watch_seconds=30)
        provider = video.VideoProvider(SimpleNamespace(settings=settings))
        starts = []

        async def capture(*args):
            starts.append(args[2])
            return b"\0" * video.FRAME_BYTES, 1, None

        clock = [1000.0]
        with mock.patch.object(video, "_youtube_capture", capture), \
                mock.patch.object(video.shutil, "which", return_value="/usr/bin/tool"), \
                mock.patch.object(video.time, "monotonic", side_effect=lambda: clock[0]):
            async def polls(count):
                for _ in range(count):
                    await provider.fetch()
                    clock[0] += 5
            asyncio.run(polls(60))              # five minutes with the screen never shown
            self.assertEqual(len(starts), 1)
            video.WATCHED["seconds"] = 31       # then it is watched
            asyncio.run(polls(2))
            self.assertEqual(len(starts), 2)


if __name__ == "__main__":
    unittest.main()
