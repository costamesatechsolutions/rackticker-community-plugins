# RackTicker community plugins

This is the independent community plugin repository, not RackTicker core.
Do not edit, deploy, or modify a RackTicker checkout as part of plugin work.
Each folder in `plugins/` is independently installable and has its own AGENTS.md.
Follow those instructions and import only RackTicker's public API in plugin code.

- Keep manifest IDs stable. Folder names match manifest IDs.
- Add one matching entry to root `index.json` for each plugin.
- Install URLs must point to `.../tree/main/plugins/PLUGIN_ID`, not the repository root.
- Keep each plugin self-contained, including its license and required assets.
- Do not commit tokens, device configuration or credentials.
- Render and inspect preview.png and preview.gif using `python -m app.dev check`.
  Use a separate RackTicker checkout/environment as read-only tooling, with
  PYTHONDONTWRITEBYTECODE=1. All outputs belong here or in temporary directories.
- Run each plugin's tests separately to avoid generic module-name collisions.
- Preserve attribution and provenance when migrating a plugin; leave the original
  source and catalog alone until the user explicitly requests the core migration.
- Publishing plugin source is separate from uploading it to a device.

Root catalog test: `python -m unittest discover -s tests -v`.
Plugin test: from its folder, `python -m unittest discover -s tests -v`
with RackTicker installed or its checkout on PYTHONPATH.
