"""Video player: loops a short clip captured with ffmpeg (a local file, a direct
video URL, or a live stream ffmpeg can open) at panel resolution. Give it more
than one source and it becomes a chill channel, cycling to the next clip every
watch_seconds — the display never just glimpses one and cuts away. Point
`youtube` at a channel instead, and each turn picks a fresh random upload from
it via yt-dlp (personal-use resolving only: nothing is downloaded or kept, and
because no player ever loads, no ad plays — that's a real cost to whoever made
the video, so this is meant for a device in your own home, not redistribution).

ffmpeg decodes once into a raw RGB buffer that render() just slices — decoding
never happens on the render thread. A clip is intentionally short (seconds, not
minutes): that keeps the frame buffer small, and gives a live source (an HLS
feed, say) a fresh capture each time settings ask for a re-decode.
"""
from __future__ import annotations

import asyncio
import random
import shutil
import time

from PIL import Image

from rackticker import HEIGHT, WIDTH, Module, Plugin, Provider, Snapshot, centered, new_frame

FRAME_BYTES = WIDTH * HEIGHT * 3
# A Pi 3A+ over Wi-Fi took 29 s just opening a remote HLS URL (mostly network, not
# decode) for an 8 s clip; give it real headroom rather than call that a failure.
DECODE_TIMEOUT_MARGIN = 60  # seconds of ffmpeg startup/network slack on top of the clip itself
INLINE_BUDGET = 4.5         # keep our own fetch() well under the 6 s the host gives providers
# yt-dlp is slow on a Pi 3A+: listing a channel took 21-58 s and resolving one video
# 60 s (43 s of it CPU), so these are generous. A clip that's still on its way keeps
# the previous one on screen, so slow only means a later switch, never a blank panel.
YOUTUBE_LIST_TIMEOUT = 120    # listing a channel's uploads (metadata only, no formats resolved)
YOUTUBE_RESOLVE_TIMEOUT = 150  # resolving the one chosen video to a direct stream URL
YOUTUBE_LIST_TTL = 3600       # reuse a channel's upload list for an hour instead of re-listing each turn
RETRY_AFTER = 60              # after a failed capture, wait this long before trying the same thing again


def sources(value):
    """One or more clips (or, for `youtube`, channels/searches), comma separated
    and edited as chips in Settings: a chill channel that cycles to the next
    after watch_seconds, instead of just one clip."""
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _scale_filter(fit):
    if fit == "stretch":
        return f"scale={WIDTH}:{HEIGHT}"
    if fit == "contain":
        return (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black")
    return f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"  # cover


def _settings_key(entry, nonce, settings):
    # `nonce` breaks the cache on purpose for a youtube pick that should be
    # refreshed (a new random video) without the channel string itself changing.
    return (entry, nonce, round(float(settings["clip_seconds"]), 1),
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


def _channel_url(query):
    """A channel link, an @handle, or plain text to search for and take the top hits of."""
    text = query.strip()
    if text.startswith(("http://", "https://")):
        return text if text.rstrip("/").endswith(("videos", "streams", "shorts")) else text.rstrip("/") + "/videos"
    if text.startswith("@"):
        return f"https://www.youtube.com/{text}/videos"
    return f"ytsearch20:{text}"


async def _run_ytdlp(ytdlp, args, timeout):
    try:
        process = await asyncio.create_subprocess_exec(
            ytdlp, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except OSError as exc:
        return None, str(exc)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return None, "Timed out talking to YouTube"
    if process.returncode != 0:
        lines = stderr.decode("utf-8", "replace").strip().splitlines()
        return None, (lines[-1][:200] if lines else "yt-dlp failed")
    return stdout.decode("utf-8", "replace"), None


async def _youtube_capture(ffmpeg, ytdlp, query, clip_seconds, fps, fit, listings):
    """One random recent upload from a channel or search, captured exactly like any
    other source. Two cheap yt-dlp calls: a flat, metadata-only listing, then
    resolving just the one chosen video to a direct playable URL — nothing is
    downloaded or saved, and video-only (we strip audio anyway) skips muxing. The
    listing is cached in `listings` so later turns only pay for the resolve."""
    cached = listings.get(query)
    if cached and time.monotonic() - cached[1] < YOUTUBE_LIST_TTL:
        ids = cached[0]
    else:
        out, error = await _run_ytdlp(ytdlp, ["--flat-playlist", "--print", "id", "--playlist-end", "20",
                                              "--no-warnings", "--socket-timeout", "15", _channel_url(query)],
                                      YOUTUBE_LIST_TIMEOUT)
        if error:
            return None, 0, error
        ids = [line.strip() for line in out.splitlines() if line.strip()]
        if not ids:
            return None, 0, "No videos found for that channel or search"
        listings[query] = (ids, time.monotonic())
    out, error = await _run_ytdlp(ytdlp, ["-f", "bv*[height<=240]/bv*/best", "-g", "--no-playlist",
                                          "--no-warnings", "--socket-timeout", "15",
                                          f"https://www.youtube.com/watch?v={random.choice(ids)}"],
                                  YOUTUBE_RESOLVE_TIMEOUT)
    if error:
        return None, 0, error
    urls = [line.strip() for line in out.splitlines() if line.strip()]
    if not urls:
        return None, 0, "yt-dlp did not return a playable stream"
    return await _capture(ffmpeg, urls[0], clip_seconds, fps, fit)


class VideoProvider(Provider):
    def __init__(self, context):
        self.context = context
        self.frames, self.fps, self.count, self.key, self.error = None, None, None, None, None
        self.task, self.task_key = None, None
        self.mode, self.playlist, self.index, self.rotated_at = "source", (), 0, 0.0
        self.pick, self.listings, self.failed_key, self.failed_at = 0, {}, None, 0.0

    async def fetch(self):
        settings = self.context.settings
        channels = sources(settings["youtube"])
        mode = "youtube" if channels else "source"
        playlist = channels if channels else sources(settings["source"])
        if not playlist:
            if self.task and not self.task.done():
                self.task.cancel()
            self.frames = self.fps = self.count = self.key = self.error = self.task = self.task_key = None
            self.mode, self.playlist, self.index = "source", (), 0
            return Snapshot(None, source="video_player")

        now = time.monotonic()
        watch = float(settings["watch_seconds"])
        if playlist != self.playlist or mode != self.mode:
            self.mode, self.playlist, self.index, self.rotated_at = mode, playlist, 0, now
        # A youtube channel always rotates to a fresh pick, even with just one channel;
        # a fixed list of direct sources only rotates when there's more than one. Never
        # while a capture is still in flight: on a slow device that would cancel every
        # pick before it lands, and nothing new would ever play.
        elif (now - self.rotated_at >= watch and self.task is None
              and (mode == "youtube" or len(playlist) > 1)):
            self.index = (self.index + 1) % len(playlist)
            self.pick += 1
            self.rotated_at = now

        entry = playlist[self.index]
        nonce = self.pick if mode == "youtube" else None
        key = _settings_key(entry, nonce, settings)
        retry_wait = key == self.failed_key and now - self.failed_at < RETRY_AFTER
        if key != self.key and key != self.task_key and not retry_wait:
            if self.task and not self.task.done():
                self.task.cancel()
            ffmpeg = shutil.which("ffmpeg")
            ytdlp = shutil.which("yt-dlp") if mode == "youtube" else None
            if ffmpeg is None:
                self.error, self.task, self.task_key = "ffmpeg is not installed on this device", None, None
            elif mode == "youtube" and ytdlp is None:
                self.error, self.task, self.task_key = "yt-dlp is not installed on this device", None, None
            else:
                entry_arg, _nonce, clip_seconds, fps, fit = key
                coro = (_youtube_capture(ffmpeg, ytdlp, entry_arg, clip_seconds, fps, fit, self.listings)
                        if mode == "youtube"
                        else _capture(ffmpeg, entry_arg, clip_seconds, fps, fit))
                self.task = asyncio.create_task(coro)
                self.task_key = key

        if self.task is not None:
            await asyncio.wait({self.task}, timeout=INLINE_BUDGET)
            if self.task.done():
                frames, count, error = self.task.result()
                if error:
                    self.error, self.failed_key, self.failed_at = error, self.task_key, time.monotonic()
                else:
                    self.frames, self.count, self.fps = frames, count, self.task_key[3]
                    self.key, self.error = self.task_key, None
                    # Watch time counts from when the clip actually shows, not from when it was asked for.
                    self.rotated_at = time.monotonic()
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
        settings = context.config["plugins"][self.name]
        return bool(sources(settings["source"]) or sources(settings["youtube"]))

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
            error = (snap.error or "") if snap else ""
            low = error.lower()
            text = ("NO FFMPEG" if "ffmpeg" in low and "install" in low
                   else "NO YT-DLP" if "yt-dlp" in low and "install" in low
                   else "LOADING" if not error else "BAD SOURCE")
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
    if len(settings["youtube"]) > 900:
        raise ValueError("youtube is too long")


# Big Buck Bunny (CC-BY, Blender Foundation), Mux's public test stream. Pointed at the
# 320x184 rendition directly, not the adaptive master: given a master playlist, ffmpeg
# picks its first-listed variant regardless of bitrate, which here was 720p — a Pi 3A+
# needed 53 s of CPU to decode 8 s of that for a panel 128 px wide. Nothing above a few
# hundred pixels wide ever helps here, whichever source it comes from.
DEMO_SOURCE = "https://test-streams.mux.dev/x36xhzz/url_2/193039199_mp4_h264_aac_ld_7.m3u8"


plugin = Plugin(
    "video_player", "Video player", module=VideoPlayer, provider=VideoProvider,
    defaults={"source": DEMO_SOURCE, "youtube": "", "fit": "cover", "clip_seconds": 8, "fps": 10,
              "loop": True, "watch_seconds": 30},
    validate_settings=validate,
    choices={"fit": ("cover", "contain", "stretch")},
    help={"source": "A local file path or a direct http(s)/rtsp/rtmp/HLS (.m3u8) URL that ffmpeg can open — "
                    "an mp4 clip, an animated GIF, or a live stream. Add more than one, comma separated, for a "
                    "chill channel that cycles to the next after watch_seconds. Needs ffmpeg installed on this "
                    "device. For an adaptive stream with several qualities (most live TV/IPTV), point this at "
                    "its lowest-resolution rendition if it publishes one directly — the panel is 128 px wide, "
                    "so anything above a few hundred pixels just costs decode time for nothing. Ships pointed "
                    "at a free CC-licensed demo clip (Big Buck Bunny); swap in your own file or stream any time. "
                    "Ignored while youtube (below) has anything in it.",
          "youtube": "One or more YouTube channels, comma separated — a link, an @handle, or just its name to "
                    "search for. Overrides source above. Each turn picks a random recent upload and plays a "
                    "silent clip of it via yt-dlp, which must be installed on this device separately (it needs "
                    "its own updates as YouTube changes; see the README). Personal use on your own device: "
                    "nothing is downloaded or kept, but since no player ever loads, no ad runs either — that's "
                    "lost revenue for whoever made the video, so this isn't meant for redistribution.",
          "fit": "cover fills the panel and crops top/bottom; contain shows the whole frame with side bars; "
                 "stretch fills it exactly and distorts",
          "clip_seconds": "How much of the source to capture and loop, in seconds — kept short to save memory",
          "fps": "Playback frame rate. The panel is tiny, so 8-12 already looks smooth",
          "loop": "Keep looping the captured clip. Off plays it once, then holds the last frame.",
          "watch_seconds": "How long to stay on each clip before the playlist can move on — and, with more "
                           "than one source or a youtube channel, before switching to the next."},
    ui={"source": {"type": "tags", "label": "Source(s)"},
        "youtube": {"type": "tags", "label": "YouTube channel(s)"},
        "watch_seconds": {"type": "slider", "min": 5, "max": 60, "step": 5, "unit": "s"},
        "clip_seconds": {"type": "slider", "min": 2, "max": 30, "step": 1, "unit": "s", "advanced": True},
        "fps": {"type": "slider", "min": 2, "max": 20, "step": 1, "advanced": True}},
)
