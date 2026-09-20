# Data from a link

Any number or text from a JSON web address, shown as a big clean card. No code: paste a link and the field to show.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/url_data
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `refresh_seconds` | `60` |see the control page |
| `label_1` | `Bitcoin` | Card 1: label |
| `url_1` | `https://api.coinbase.com/v2/prices/BTC-USD/spot` | Card 1: link |
| `path_1` | `data.amount` | Where the value is in the JSON, e.g. data.amount or items.0.price |
| `unit_1` | `USD` | Card 1: unit |
| `decimals_1` | `0` | -1 shows the number as it comes |
| `label_2` | `` | Card 2: label |
| `url_2` | `` | Card 2: link |
| `path_2` | `` | Card 2: field |
| `unit_2` | `` | Card 2: unit |
| `decimals_2` | `-1` | Card 2: decimals |
| `label_3` | `` | Card 3: label |
| `url_3` | `` | Card 3: link |
| `path_3` | `` | Card 3: field |
| `unit_3` | `` | Card 3: unit |
| `decimals_3` | `-1` | Card 3: decimals |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
