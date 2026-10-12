# Blocks

The Bitcoin network building its chain, one block about every ten minutes.

- **The chain**: the last six blocks as cubes, newest on the right next to the
  dashed one being filled now, each with how long ago it was found and how many
  transactions it holds, and what it costs to get into the next one.
- **The latest block**: its number, who mined it and what they were paid, and
  how many transactions it carried.
- **The queue**: how many transactions are waiting to get in, about how many
  blocks' worth, and the fee for the next block.
- **The next halving**: blocks to go, when it should be, and the progress bar
  through this four-year stretch.

Turn on *Show every new block* and each new block drops onto the chain as it is
found, with who found it.

Public data from [mempool.space](https://mempool.space/) (free, no key). Watching a
counter, nothing else: no prices, no wallets, no trading.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/blocks
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `alert` | off | Take over briefly for every new block |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
