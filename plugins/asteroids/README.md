# Asteroids

Space rocks passing close to Earth this month, sized like things you know.

- **This month**: how many asteroids pass closer than ten times the Moon's
  distance in the next 30 days (usually a dozen or more), and the nearest.
- **A card for each of the nearest**: the Earth with the Moon's orbit, and the
  rock sweeping past at its real miss distance; its name, when it is closest,
  how far in Moon distances (red when it comes inside the Moon's orbit), how big
  ("as big as a bus") and how fast.

Most are a few metres to a few dozen across and found only days before they
pass. Sizes come from JPL's measured diameter when there is one, otherwise from
how bright the rock is.

A rock passing inside the Moon's orbit takes over the display as it comes by.

From NASA JPL's [Small-Body Database](https://ssd-api.jpl.nasa.gov/doc/cad.html)
close-approach data (free, no key), checked every three hours.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/asteroids
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `within_moon_distances` | `10` | Count passes closer than this many Moon distances |
| `cards` | `4` | How many of the nearest passes get their own card |
| `alert` | on | Take over when one passes inside the Moon's orbit |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
