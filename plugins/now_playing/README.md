# Now playing

Now Playing: the song you are listening to, like an old car stereo.

Album art on the left, the title and artist scrolling like a head unit's
display, the track number and time, and a segmented spectrum analyser with
peak caps. From Spotify (your own free developer app) or from any Home Assistant
media player (Spotify, Sonos, Apple TV, an Echo…).

Neither Spotify nor Home Assistant publishes the audio itself, so the analyser
is a drummer, not a microphone: it plays a beat at a tempo picked for each song
and follows the song's real progress, pausing when the music does.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/now_playing
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `source` | `spotify` | Spotify directly, or whatever a Home Assistant media player is playing. One of `spotify`, `home_assistant` |
| `lyrics` | `True` | Time-synced lyrics from LRCLIB, when the song has them |
| `spotify_client_id` | `` | From your app at developer.spotify.com; spotify_login.py fills both Spotify fields |
| `spotify_refresh_token` | `` | Written by spotify_login.py |
| `ha_url` | `http://homeassistant.local:8123` |see the control page |
| `ha_token` | `` | Home Assistant → your profile → Security → Long-lived access tokens |
| `ha_entity` | `` | Leave empty to follow whichever player is playing |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
