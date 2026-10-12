# Satellites overhead

Every working satellite above your horizon right now: often a thousand at once.

- **The swarm**: your whole 360° horizon across the panel (south in the middle),
  every satellite at its real bearing and height, moving at its real pace.
  Starlink in blue, OneWeb green, Amazon's Kuiper orange, everything else
  white. The arc of still dots across the southern sky is the geostationary belt:
  TV and weather satellites parked 22,236 miles up. The space stations (ISS and
  China's Tiangong) are named.
- **After dark**, the satellites still lit by the Sun high above shine brighter
  and the rest fade: the bright ones are those you could see crawling across the sky.
- **The count**: how many are over you, how many are lit, and whose they are.

Orbits for every active satellite from [CelesTrak](https://celestrak.org/), downloaded
every six hours and kept on the device (CelesTrak refuses the same download twice
within two hours). Positions are worked out on the device: once every ten minutes
for all of them to find those near your sky, then every 30 seconds for those.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/satellites
```

The first picture takes a minute while the catalogue downloads.

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| Location | home | Where you are; leave it to use the home location from Settings |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
