# Three bodies

The Sun, the Earth and the Moon side by side, as they are right now, with how far
apart they are today.

- **The Sun**: NOAA's newest picture from the GOES-19 solar ultraviolet imager,
  minutes old, then its latest flare (C yellow, M orange, X red) and when it peaked.
- **The Earth**: the newest full-disc picture from a GOES weather satellite
  22,236 miles up: today's clouds by day, city lights by night. GOES-West sees the
  Pacific and the Americas, GOES-East the Americas and the Atlantic.
- **The Moon**: drawn here in its exact phase, with its seas and Tycho, the dark
  side faintly lit by earthshine; then the phase name, how much of it is lit and the
  next full or new Moon.

Pictures are shrunk to 32 × 32 in a helper process, so the panel never waits on them.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/three_bodies
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| Location | home | South of the equator the Moon is lit from the other side, as you see it |
| `earth_satellite` | `west` | `west` (GOES-18) or `east` (GOES-19) |
| `sun_band` | `304` | The ultraviolet colour: `304` the orange surface; `195`, `171`, `284`, `131`, `094` the corona |

## Credits

Sun and Earth pictures: NOAA (GOES-19 SUVI via the Space Weather Prediction Center;
GOES ABI GeoColor via NESDIS STAR). Flares: NOAA SWPC. US government works, public domain.

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
