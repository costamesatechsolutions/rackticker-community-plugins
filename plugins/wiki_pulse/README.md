# Wiki pulse

The world editing Wikipedia, live.

- **The pulse**: a heartbeat line across the panel where every edit to an article
  is a blip, up for words added and down for words cut (the bigger the edit, the
  taller), gold for a new article, sliding past in real time; how many edits a
  minute; and the article just touched, with how much changed.
- **Most edited in the last hour**: when something happens in the world, its
  article is suddenly being edited by dozens of people at once, often before
  the news sites have it.
- **Brand-new articles**, as they are created.

From Wikipedia's public recent-changes list for the language you pick, asked every
ten seconds. Robot edits are left out unless you ask for them.

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/wiki_pulse
```

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `language` | `en` | Which Wikipedia: `en`, `de`, `fr`, `es`, `it`, `ja`, `pt`, `ru`, `zh`, `nl`, `pl`, `sv` |
| `include_bots` | off | Count the robots that tidy articles too |

## Licence

AGPL-3.0-only, the same as RackTicker. Built by [Costa Mesa Tech Solutions](https://github.com/costamesatechsolutions).
