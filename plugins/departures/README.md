# Departures

Departures: live station boards from Budapest, Rome, Milan, Florence, Venice,
Naples and Zürich, each drawn the way that country's boards look.

Live data, no keys: MÁV (Hungary), ViaggiaTreno (Trenitalia) and the Swiss
open transport API. While a station sleeps, "Clock" can replay its timetable at
your own time of day, so the board is busy when you are awake.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/departures
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `station` | `tour` | tour visits the European stations in turn, usa the Amtrak ones, world all of them. One of `tour`, `usa`, `socal`, `london`, `world`, `budapest_keleti`, `roma_termini`, `milano_centrale`, and more |
| `clock` | `auto` | station shows the real board now; mine replays the timetable at your time of day; auto uses the real board while the station is awake. One of `auto`, `station`, `mine` |
| `times` | `yours` | show departure times in your time zone or the stations. One of `yours`, `station` |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
