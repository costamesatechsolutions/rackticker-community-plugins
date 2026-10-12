# Space station

The International Space Station, live on your panel.

- **The world, lit as it is right now**: green where it is day, blue where it is
  night, the Sun overhead as a gold dot, your home as a red one.
- **Its track**: the last orbit in grey, the next one in amber, and the station
  itself crossing the map.
- **What it is over** ("Brazil", "Indian Ocean"), its speed and its height.
- **The crew's next sunset or sunrise**, counting down: they see sixteen of each a day.
- **The next time you can see it from home**: the day and time, which way it
  crosses your sky and how high it gets.
- **Who is aboard**, by surname, with their country.
- **Look up**: when the station crosses your sky while it is lit by the Sun and your
  sky is dark, the screen takes over a couple of minutes early with a countdown and
  where to look, then follows it across a compass with its live direction and height.

Positions are worked out on the device from the station's published orbit
(CelesTrak), so it keeps moving even when the network drops.
Crew from the [people-in-space API](https://github.com/corquaid/international-space-station-APIs).
Map and country outlines from [Natural Earth](https://www.naturalearthdata.com/) (public domain).

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/iss
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| Location | home | Where you watch from; leave it to use the home location from Settings |
| `units` | `imperial` | mph and miles, or km/h and kilometres |
| `alert` | on | Take over the display while a pass you can see is happening |
| `alert_lead_minutes` | `2` | How many minutes before it rises the countdown starts |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
