# Video player

Loops a short clip on the panel — a local file, a direct video URL, or any live
stream ffmpeg can open (mp4, GIF, HLS `.m3u8`, RTSP/RTMP).

ffmpeg captures a few seconds at panel resolution and RackTicker loops that
buffer; nothing is decoded on the render thread. Ships pointed at a free
CC-BY demo clip (Big Buck Bunny, served by Mux's public test stream) so it
plays the moment it's installed — change **source** to your own file or a
live feed any time. Needs `ffmpeg` on the device (`sudo apt install ffmpeg`
on a Pi).

Add more than one **source** (chips in Settings, comma separated under the
hood) and it becomes a chill channel: it plays each for **watch_seconds**,
then decodes the next one in the background and cuts over — a rotation
through your own clips instead of just one on loop. `watch_seconds` also
tells the playlist how long to stay on this screen each visit, so it's a
real watch, not a glimpse.

## YouTube channel mode

Fill in **YouTube channel(s)** instead (a link, an `@handle`, or just a name
to search for — comma separated for more than one) and every `watch_seconds`
it picks a random recent upload and plays a silent clip of it, the same way
as any other source. This needs
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp) installed separately — it isn't
bundled, and it needs its own updates as YouTube changes things:

```sh
sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp
# later, when YouTube pulling stops working:
sudo yt-dlp -U
```

The Debian/Raspberry Pi OS `yt-dlp` apt package is typically years stale and
won't keep up with YouTube — use the standalone binary above instead.

This is personal use only: it resolves a direct stream URL and captures a few
seconds of it, nothing is downloaded or kept. But since no YouTube player ever
loads, no ad plays either — that's real revenue the video's creator doesn't
get for that view, so keep this to a device in your own home, not something
you redistribute or show publicly.

```sh
python -m app.dev check path/to/this/folder     # renders preview.png and preview.gif
python -m app.dev preview path/to/this/folder   # live in the browser, reloads on save
python -m app.dev push path/to/this/folder --to rackticker.local:8081
```

To share it, put this folder in a public GitHub repository. Anyone can then paste the link into
**Plugins → Add a plugin** on their RackTicker.
