"""Video player: loops a short clip captured with ffmpeg (a local file, a direct
video URL, or a live stream ffmpeg can open) at panel resolution.

ffmpeg decodes once into a raw RGB buffer that render() just slices — decoding
never happens on the render thread. A clip is intentionally short (seconds, not
minutes): that keeps the frame buffer small, and gives a live source (an HLS
feed, say) a fresh capture each time settings ask for a re-decode.
"""
from __future__ import annotations

import asyncio
import shutil

from PIL import Image

from rackticker import HEIGHT, WIDTH, Module, Plugin, Provider, Snapshot, centered, new_frame

FRAME_BYTES = WIDTH * HEIGHT * 3
DECODE_TIMEOUT_MARGIN = 20  # seconds of ffmpeg startup/network slack on top of the clip itself
INLINE_BUDGET = 4.5         # keep our own fetch() well under the 6 s the host gives providers


def _scale_filter(fit):
    if fit == "stretch":
        return f"scale={WIDTH}:{HEIGHT}"
    if fit == "contain":
        return (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black")
    return f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"  # cover


def _settings_key(settings):
    return (str(settings["source"]).strip(), round(float(settings["clip_seconds"]), 1),
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

    async def fetch(self):
        settings = self.context.settings
        source = str(settings["source"]).strip()
        if not source:
            if self.task and not self.task.done():
                self.task.cancel()
            self.frames = self.fps = self.count = self.key = self.error = self.task = self.task_key = None
            return Snapshot(None, source="video_player")

        key = _settings_key(settings)
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
        return bool(str(context.config["plugins"][self.name]["source"]).strip())

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _index(self, context, data):
        settings = context.config["plugins"][self.name]
        raw = int(context.animation_time * data["fps"])
        return raw % data["count"] if settings["loop"] else min(raw, data["count"] - 1)

    def hold(self, context):
        settings = context.config["plugins"][self.name]
        snap = context.snapshots.get(self.name)
        if settings["loop"] or not snap or not snap.data:
            return False
        return context.animation_time < snap.data["count"] / snap.data["fps"]

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
    if len(settings["source"]) > 500:
        raise ValueError("source is too long")


DEMO_SOURCE = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"  # Big Buck Bunny (CC-BY, Blender Foundation)


plugin = Plugin(
    "video_player", "Video player", module=VideoPlayer, provider=VideoProvider,
    defaults={"source": DEMO_SOURCE, "fit": "cover", "clip_seconds": 8, "fps": 10, "loop": True},
    validate_settings=validate,
    choices={"fit": ("cover", "contain", "stretch")},
    help={"source": "A local file path or a direct http(s)/rtsp/rtmp/HLS (.m3u8) URL that ffmpeg can open — "
                    "an mp4 clip, an animated GIF, or a live stream. Needs ffmpeg installed on this device. "
                    "Ships pointed at a free CC-licensed demo clip (Big Buck Bunny); swap in your own file or "
                    "stream any time.",
          "fit": "cover fills the panel and crops top/bottom; contain shows the whole frame with side bars; "
                 "stretch fills it exactly and distorts",
          "clip_seconds": "How much of the source to capture and loop, in seconds — kept short to save memory",
          "fps": "Playback frame rate. The panel is tiny, so 8-12 already looks smooth",
          "loop": "Keep looping the captured clip. Off plays it once, then holds the last frame."},
    ui={"clip_seconds": {"type": "slider", "min": 2, "max": 30, "step": 1, "unit": "s", "advanced": True},
        "fps": {"type": "slider", "min": 2, "max": 20, "step": 1, "advanced": True}},
)
