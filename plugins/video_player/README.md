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

```sh
python -m app.dev check path/to/this/folder     # renders preview.png and preview.gif
python -m app.dev preview path/to/this/folder   # live in the browser, reloads on save
python -m app.dev push path/to/this/folder --to rackticker.local:8081
```

To share it, put this folder in a public GitHub repository. Anyone can then paste the link into
**Plugins → Add a plugin** on their RackTicker.
