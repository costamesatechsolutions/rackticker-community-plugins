# Word bot

A robot plays the five-letter word game on its own, the way you would.

It picks a hidden word, then guesses: each letter typed into the tiles, the tiles
flipping one by one, green for the right letter in the right place, gold for a
letter in the word but somewhere else, grey for one that is not in it, and how
many words could still be the answer. The share grid on the left fills in as it
goes. When it gets it, the tiles hop, and it keeps a running average across the
visit (about 3.2 tries).

It always opens with SLATE, then each time picks whichever possible answer splits
the remaining ones best. Games are solved ahead of time in a helper process, a
fresh set each day, so the display never waits. The word list is its own, about
850 everyday words.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/word_bot
```

No settings.

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
