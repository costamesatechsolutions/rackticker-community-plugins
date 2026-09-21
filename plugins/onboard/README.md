# Onboard

Onboard: the display above the carriage doors, for a train that is really running.

It shows what that display shows: the stop the train is coming to in big letters, when it
gets there and how long that is, how fast it is going, whether it is on time, and a line from
the last stop to the next with the train on it. The train is a real one, from Amtrak's live
feed through the key-free Amtraker API.

Where the train sits on that line comes from where the train actually is, measured against
where the two stations are, so it only ever moves forward. It is drawn to a fraction of a
pixel, because at real speeds a train crosses a pixel of this line in minutes, and a bar that
moved in whole pixels would sit still and then lurch.

Pick a route, a train number, or name a station and it rides whichever train is out there
serving it. Give it a location and, when several trains are running (the Pacific Surfliner has
half a dozen at once), it rides the one nearest to you.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/onboard
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `train` | `coast_starlight` | a route to ride, or type an Amtrak train number. Routes: `coast_starlight`, `california_zephyr`, `empire_builder`, `southwest_chief`, `sunset_limited`, `texas_eagle`, `lake_shore_limited`, `crescent`, `auto_train`, `cardinal`, `city_of_new_orleans`, `adirondack`, `pacific_surfliner`, `capitol_corridor`, `amtrak_cascades`, `acela` |
| `station` | `` | a three-letter Amtrak station code to ride whatever is serving it (used only when no route is set) |
| `refresh_seconds` | `60` | how often to ask for the train's position (20 to 600); between answers the train is carried forward at its speed |
| `latitude`, `longitude` | `0` | with a location (0 uses the device's home location) it rides the nearest train when several are running |

When no train on the route is running the screen is simply not shown; that is not an error.

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
