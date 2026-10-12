# Wildfires

The fires burning near you, anywhere in the United States.

- **How many** active fires there are within your distance, and how many acres are burning.
- **A card for each of the nearest, and the biggest**: a flickering flame, the
  fire's name, acres burned, a containment bar, how far away and in which
  direction, and how many days it has burned.
- **A new fire close by** (within 25 miles, started in the last six hours) takes
  over the display once.

Small first reports, most of them spot fires put out at an acre or two, are left
out (10 acres and up by default).

From the National Interagency Fire Center's current incident list
([WFIGS](https://data-nifc.opendata.arcgis.com/)), which covers every state including
CAL FIRE's: free, no key, checked every ten minutes.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/wildfires
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| Location | home | Where you are |
| `within_miles` | `250` | Show fires within this distance |
| `min_acres` | `10` | Leave out fires smaller than this |
| `cards` | `4` | How many of the nearest get a card (the biggest always does) |
| `alert` | on | Take over once for a new fire nearby |
| `alert_miles` | `25` | What counts as nearby |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
