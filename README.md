# RackTicker community plugins

Independent, installable plugins for [RackTicker](https://github.com/costamesatechsolutions/rackticker).
This is the beginning of a separate community home. RackTicker core and its existing
community catalog have not been changed.

## Install a plugin

In RackTicker, open **Plugins → Add a plugin** and paste one of these folder links:

| Plugin | Install URL | What it does |
| --- | --- | --- |
| [Virtual Aquarium](plugins/virtual_aquarium) | [Install folder](https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/virtual_aquarium) | Animated fish, plants, coral, bubbles and a snail; optional real tank readings and lighting. |
| [Retro Screensavers](plugins/retro_savers) | [Install folder](https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/retro_savers) | 3D pipes, Mystify, starfield, a bouncing four-pane badge and marquee text. |

**Use a plugin's folder URL, not this repository's root URL.** Each folder contains
its own `plugin.json`, code, license, instructions and previews. Installation uses
RackTicker's existing third-party sandbox and does not require core changes.

### Virtual Aquarium

![Aquarium](plugins/virtual_aquarium/preview.gif)

### Retro Screensavers

![Retro screensavers](plugins/retro_savers/preview.gif)

## Catalog and migration

[index.json](index.json) follows the current RackTicker community-index schema.
It lists just these two plugins. RackTicker's built-in community browser still
uses the original catalog in the main repository, so these entries do **not**
automatically appear there yet. Use the folder URLs above for now.

Virtual Aquarium was copied from its standalone repository at commit `769ca73`,
with no runtime changes and the same `virtual_aquarium` ID and version. Its old
repository remains available. This repository is the home for future community
work; nothing installed on a rack is automatically moved or replaced by this migration.

See [MIGRATION.md](MIGRATION.md) for the future migration checklist. The existing
community plugins in RackTicker have not been copied, removed or redirected.

## Develop

Read [AGENTS.md](AGENTS.md) and the selected plugin's own instructions. Keep a
separate RackTicker checkout or installation for the public API and developer tools.
Do not edit RackTicker to implement a community plugin.

From the RackTicker checkout, using its Python environment:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m app.dev check ../rackticker-community-plugins/plugins/retro_savers --seconds 80
PYTHONDONTWRITEBYTECODE=1 python -m app.dev check ../rackticker-community-plugins/plugins/virtual_aquarium --seconds 24
```

From this repository, the catalog tests need only Python:

```sh
python -m unittest discover -s tests -v
```

Run each plugin's tests from its own folder, with RackTicker on PYTHONPATH or
installed in the environment. For example, from `plugins/retro_savers`:

```sh
python -m unittest discover -s tests -v
```

Include preview images but keep them compact: RackTicker downloads the repository
archive even when installing a single folder, and enforces an archive-size limit.

## License

AGPL-3.0-only; each installable folder includes its own license. Preserve original
attribution and migration provenance. Built by Costa Mesa Tech Solutions using
RackTicker's public plugin API and CMTS plugin starter instructions.
