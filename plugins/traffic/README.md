# Freeway traffic

Freeway traffic board: live CHP incidents on nearby freeways, shown as a freeway shield, what happened, where, and how long ago.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/traffic
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `dispatch_centers` | `auto` | auto uses every CHP center and keeps what is near you |
| `latitude` | `0.0` | Leave at 0 to use the home location from Settings |
| `longitude` | `0.0` |see the control page |
| `radius_miles` | `15` | How far from home counts as near |
| `refresh_seconds` | `120` |see the control page |
| `card_seconds` | `5` | Seconds per card |
| `max_age_hours` | `3` | Hide incidents logged longer ago than this; CHP keeps cleared logs in the feed |
| `freeways` | `` | Leave empty to use the freeways near you, or list up to four, e.g. I-405, SR-73 |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
