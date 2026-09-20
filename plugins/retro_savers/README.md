# Retro Screensavers

Five original pixel interpretations of the Windows 95/98/XP desktop-screensaver era,
made for RackTicker's 128 × 32 LED panel. No downloads, accounts or external artwork.

![Retro Screensavers](preview.gif)

## Install

Paste this **folder URL** into RackTicker → Plugins → Add a plugin:

```
https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/retro_savers
```

## Savers

| Mode | On the panel |
| --- | --- |
| `pipes` | Three colored pipes build through a shallow 3D lattice, with shaded edges, bright joints and depth ordering. A fresh layout begins every 18 animation seconds. |
| `mystify` | Two bouncing wire polygons leave colored trails across a black screen. |
| `starfield` | Perspective stars fly toward you from the center. |
| `badge` | An original four-color, four-pane badge bounces off the edges. |
| `marquee` | Large smooth text bounces; longer phrases page at word boundaries so no word is cut off. |
| `rotate` | All five, changing every 16 seconds by default and advancing between playlist visits. |

Set the mode to **pipes** for a dedicated pipes screen. Change **speed**, **seed**,
**star count**, **seconds per mode**, or **message** in plugin settings. Messages allow 32 characters total and 10 per word.
A seed makes pipe layouts and stars repeatable. Cycle timing uses the scene's
animation clock; speed affects movement, not the selected mode's duration.

The plugin does not hold the playlist, use wall-clock animation, make network
requests, or write files at runtime. Rotation starts again at pipes after a plugin
restart. These are small original interpretations, not Microsoft screensaver
binaries, exact replicas, or official Microsoft artwork.

## Development

Follow `AGENTS.md`. With RackTicker installed in your environment:

```sh
python -m unittest discover -s tests -v
python -m app.dev check . --seconds 80
python -m app.dev preview .
```

The 80-second check samples all five modes. Inspect the contact sheet and GIF.
For one mode: `python -m app.dev check . --settings '{"mode":"pipes"}'`.

AGPL-3.0-only; see `LICENSE`. Built using CMTS's plugin starter instructions and
RackTicker's public plugin API. Plugin code and graphics are original.
