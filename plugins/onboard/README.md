# Onboard

Onboard: the strip map inside the carriage, for a train that is really running.

The display above the doors of a train: the line drawn as a row of stops, the
train sliding along it, the stop it is coming to next, and how far is left. The
train is a real one — Amtrak's live feed through the key-free Amtraker API — so
the dot moves because a train moved.

Pick a train by number, or name a station and it rides whichever train is out
there serving it.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/onboard
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `train` | `coast_starlight` | a route to ride, or type an Amtrak train number. One of `coast_starlight`, `california_zephyr`, `empire_builder`, `southwest_chief`, `sunset_limited`, `texas_eagle`, `lake_shore_limited`, and more |
| `station` | `` | a three-letter Amtrak station code to ride whatever is serving it (overrides the route only when no route is set) |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
