"""Video player: loops a short clip captured with ffmpeg (a local file, a direct
video URL, or a live stream ffmpeg can open) at panel resolution. Give it more
than one source and it becomes a chill channel, cycling to the next clip every
watch_seconds — the display never just glimpses one and cuts away.

ffmpeg decodes once into a raw RGB buffer that render() just slices — decoding
never happens on the render thread. A clip is intentionally short (seconds, not
minutes): that keeps the frame buffer small, and gives a live source (an HLS
feed, say) a fresh capture each time settings ask for a re-decode.
"""
from __future__ import annotations

import asyncio
import shutil
import time

from PIL import Image

from rackticker import HEIGHT, WIDTH, Module, Plugin, Provider, Snapshot, centered, new_frame

FRAME_BYTES = WIDTH * HEIGHT * 3
# A Pi 3A+ over Wi-Fi took 29 s just opening a remote HLS URL (mostly network, not
# decode) for an 8 s clip; give it real headroom rather than call that a failure.
DECODE_TIMEOUT_MARGIN = 60  # seconds of ffmpeg startup/network slack on top of the clip itself
INLINE_BUDGET = 4.5         # keep our own fetch() well under the 6 s the host gives providers


def sources(value):
    """One or more clips, comma separated (edited as chips in Settings): a chill
    channel that cycles to the next after watch_seconds, instead of just one clip."""
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _scale_filter(fit):
    if fit == "stretch":
        return f"scale={WIDTH}:{HEIGHT}"
    if fit == "contain":
        return (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black")
    return f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"  # cover


def _settings_key(source, settings):
    return (source, round(float(settings["clip_seconds"]), 1),
            round(float(settings["fps"]), 1), settings["fit"])


async def _capture(ffmpeg, source, clip_seconds, fps, fit):
    """Run as its own asyncio task: shells out to ffmpeg and hands back raw frames.
    Never raises — errors come back as the last tuple element, so a slow or broken
    source never looks like an unhandled crash to the caller."""
    args = ["-hide_banner", "-loglevel", "error", "-nostdin",
            "-t", f"{clip_seconds}", "-i", source, "-an", "-sn",
            "-vf", f"fps={fps},{_scale_filter(fit)},format=rgb24",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    try:
        process = await asyncio.create_subprocess_exec(
            ffmpeg, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except OSError as exc:
        return None, 0, str(exc)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), clip_seconds + DECODE_TIMEOUT_MARGIN)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return None, 0, "Timed out opening or decoding that source"
    if process.returncode != 0:
        lines = stderr.decode("utf-8", "replace").strip().splitlines()
        return None, 0, (lines[-1][:200] if lines else f"ffmpeg exited with status {process.returncode}")
    count = len(stdout) // FRAME_BYTES
    if count < 1:
        return None, 0, "No frames decoded from that source"
    return stdout[:count * FRAME_BYTES], count, None


class VideoProvider(Provider):
    def __init__(self, context):
        self.context = context
        self.frames, self.fps, self.count, self.key, self.error = None, None, None, None, None
        self.task, self.task_key = None, None
        self.playlist, self.index, self.rotated_at = (), 0, 0.0

    async def fetch(self):
        settings = self.context.settings
        playlist = sources(settings["source"])
        if not playlist:
            if self.task and not self.task.done():
                self.task.cancel()
            self.frames = self.fps = self.count = self.key = self.error = self.task = self.task_key = None
            self.playlist, self.index = (), 0
            return Snapshot(None, source="video_player")

        now = time.monotonic()
        watch = float(settings["watch_seconds"])
        if playlist != self.playlist:
            self.playlist, self.index, self.rotated_at = playlist, 0, now
        elif len(playlist) > 1 and now - self.rotated_at >= watch:
            self.index = (self.index + 1) % len(playlist)
            self.rotated_at = now

        key = _settings_key(playlist[self.index], settings)
        if key != self.key and key != self.task_key:
            if self.task and not self.task.done():
                self.task.cancel()
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg is None:
                self.error, self.task, self.task_key = "ffmpeg is not installed on this device", None, None
            else:
                source_arg, clip_seconds, fps, fit = key
                self.task = asyncio.create_task(_capture(ffmpeg, source_arg, clip_seconds, fps, fit))
                self.task_key = key

        if self.task is not None:
            await asyncio.wait({self.task}, timeout=INLINE_BUDGET)
            if self.task.done():
                frames, count, error = self.task.result()
                if error:
                    self.error = error
                else:
                    self.frames, self.count, self.fps, self.key, self.error = frames, count, key[2], self.task_key, None
                self.task, self.task_key = None, None

        if self.frames is None:
            return Snapshot(None, source="video_player", error=self.error)
        return Snapshot({"frames": self.frames, "fps": self.fps, "count": self.count},
                        source="video_player", stale=(self.key != key))

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()


class VideoPlayer(Module):
    name = "video_player"

    def available(self, context):
        return bool(sources(context.config["plugins"][self.name]["source"]))

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _index(self, context, data):
        settings = context.config["plugins"][self.name]
        raw = int(context.animation_time * data["fps"])
        return raw % data["count"] if settings["loop"] else min(raw, data["count"] - 1)

    def hold(self, context):
        # Ask the playlist to stay put for watch_seconds so a visit is actually long
        # enough to watch something, not just a glimpse before it moves on.
        settings = context.config["plugins"][self.name]
        return context.animation_time < float(settings["watch_seconds"])

    def render(self, context):
        frame = new_frame()
        snap = context.snapshots.get(self.name)
        if not snap or not snap.data:
            error = snap.error if snap else None
            text = "NO FFMPEG" if error and "install" in error else "LOADING" if not error else "BAD SOURCE"
            centered(frame, text, 12)
            return frame
        offset = self._index(context, snap.data) * FRAME_BYTES
        return Image.frombytes("RGB", (WIDTH, HEIGHT), snap.data["frames"][offset:offset + FRAME_BYTES])


def validate(settings):
    if not 2 <= float(settings["clip_seconds"]) <= 30:
        raise ValueError("clip_seconds must be 2-30")
    if not 2 <= float(settings["fps"]) <= 20:
        raise ValueError("fps must be 2-20")
    if not 5 <= float(settings["watch_seconds"]) <= 60:
        raise ValueError("watch_seconds must be 5-60")
    if len(settings["source"]) > 900:
        raise ValueError("source is too long")


# Big Buck Bunny (CC-BY, Blender Foundation), Mux's public test stream. Pointed at the
# 320x184 rendition directly, not the adaptive master: given a master playlist, ffmpeg
# picks its first-listed variant regardless of bitrate, which here was 720p — a Pi 3A+
# needed 53 s of CPU to decode 8 s of that for a panel 128 px wide. Nothing above a few
# hundred pixels wide ever helps here, whichever source it comes from.
DEMO_SOURCE = "https://test-streams.mux.dev/x36xhzz/url_2/193039199_mp4_h264_aac_ld_7.m3u8"


plugin = Plugin(
    "video_player", "Video player", module=VideoPlayer, provider=VideoProvider,
    defaults={"source": DEMO_SOURCE, "fit": "cover", "clip_seconds": 8, "fps": 10, "loop": True,
              "watch_seconds": 30},
    validate_settings=validate,
    choices={"fit": ("cover", "contain", "stretch")},
    help={"source": "A local file path or a direct http(s)/rtsp/rtmp/HLS (.m3u8) URL that ffmpeg can open — "
                    "an mp4 clip, an animated GIF, or a live stream. Add more than one, comma separated, for a "
                    "chill channel that cycles to the next after watch_seconds. Needs ffmpeg installed on this "
                    "device. For an adaptive stream with several qualities (most live TV/IPTV), point this at "
                    "its lowest-resolution rendition if it publishes one directly — the panel is 128 px wide, "
                    "so anything above a few hundred pixels just costs decode time for nothing. Ships pointed "
                    "at a free CC-licensed demo clip (Big Buck Bunny); swap in your own file or stream any time.",
          "fit": "cover fills the panel and crops top/bottom; contain shows the whole frame with side bars; "
                 "stretch fills it exactly and distorts",
          "clip_seconds": "How much of the source to capture and loop, in seconds — kept short to save memory",
          "fps": "Playback frame rate. The panel is tiny, so 8-12 already looks smooth",
          "loop": "Keep looping the captured clip. Off plays it once, then holds the last frame.",
          "watch_seconds": "How long to stay on each clip before the playlist can move on (and, with more "
                           "than one source, before switching to the next)."},
    ui={"source": {"type": "tags", "label": "Source(s)"},
        "watch_seconds": {"type": "slider", "min": 5, "max": 60, "step": 5, "unit": "s"},
        "clip_seconds": {"type": "slider", "min": 2, "max": 30, "step": 1, "unit": "s", "advanced": True},
        "fps": {"type": "slider", "min": 2, "max": 20, "step": 1, "advanced": True}},
)
