# Space weather

What the Sun is doing to the Earth, live from NOAA's Space Weather Prediction Center.

- **Kp index**: the geomagnetic storm level now (0 calm to 9 extreme) with the
  storm scale (G1 to G5), and three-hour bars from yesterday through tomorrow's
  forecast, dimmer where they are forecast.
- **Solar wind**: particles stream across the panel at the wind's real speed, with
  the speed in km/s and which way its magnetic field points. A southward field
  (negative Bz) is what lets a storm in.
- **X-rays**: six hours of the Sun's X-ray brightness on the flare scale A, B, C,
  M and X, now and the peak.
- **Northern lights here**: the Kp at which aurora shows on your northern horizon,
  from your geomagnetic latitude, against now and the next 24 hours. Kp 3 for
  Anchorage, 7 for Seattle, 9 for Southern California.

A strong storm (G3+), an X-class flare or aurora within your reach takes over the
display once.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/space_weather
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| Location | home | Where you watch from, for the northern lights card |
| `alert` | on | Take over for a big storm, an X flare, or aurora you could see |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
