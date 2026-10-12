# Harbor

The ships around you, live from their own radio beacons (AIS).

- **Radar**: the water around home with a sweep going round it. Every ship is a
  dot in the colour of its kind (cargo amber, tankers red, passenger white, tugs
  green, fishing cyan, pleasure boats blue); ships under way trail a wake showing
  where they're headed; ships at anchor blink slowly. Home is the red blink.
- **The count**: how many are at anchor, under way and stopped.
- **The biggest ships**: name, what it is, how long (with the hull drawn to
  scale), what it is doing and where it says it is going.

Ships send their position every few seconds to few minutes and their name, size
and destination every six minutes, so the picture fills in over the first ten
minutes or so.

## You need a free key

1. Go to [aisstream.io](https://aisstream.io), sign in with GitHub and create an API key.
2. Paste it into RackTicker → Settings → Harbor → **AIS key** (it is kept secret).

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/harbor
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| AIS key | | Your free aisstream.io key |
| Location | home | The middle of the picture |
| `radius_miles` | `20` | How far east and west of home to watch; north and south is half that |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
