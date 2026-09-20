# Community repository migration

## Done

- This repository is the home for RackTicker community plugins: one self-contained
  folder each, with its own manifest, licence, README, agent notes and previews.
- Virtual Aquarium 1.0.0 copied from standalone commit `c345635`, and Retro
  Screensavers 1.0.0 added, both keeping their IDs and versions.
- Departures, Onboard, Surf, Quakes, Tanks and Now playing moved out of the
  RackTicker repository, keeping their IDs, versions, settings schemas and code
  unchanged. Only their `homepage`, author and documentation changed.
- Their tests came with them (`tests/test_plugins.py`); they skip when there is no
  RackTicker checkout beside this repository rather than failing.
- `index.json` lists all fourteen, and `tests/test_catalog.py` holds it to the
  manifests, so a catalog entry cannot drift from the plugin it describes.
- RackTicker's plugin browser reads this repository's `index.json`, with a bundled
  copy as the fallback for when the network is not there.

- Arcade, Formula 1, Prediction markets, the LED sign, Freeway traffic and Data from a
  link followed on 2026-09-20, the same way, with their tests in `tests/test_moved.py`
  and `tests/test_traffic.py`. RackTicker keeps seven plugins bundled: weather, town,
  finance, sportsbook, free sports, news and local ADS-B.

## What moving the files does not do

It does not move an installation. A plugin already on a panel recorded where it came
from in its own `.source.json`, and that still points at the old folder in the
RackTicker repository. It keeps running, but **Check for updates** will not find
anything once the old folders are gone.

Two ways to fix a panel that has one:

- Reinstall from the new folder URL. Settings are keyed by plugin ID, so they
  survive, and the playlist keeps its place.
- Or rewrite the recorded source in place, which avoids the reinstall:

```sh
sudo python3 - <<'PY'
import json, pathlib
NEW = "https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins"
for source in pathlib.Path("/var/lib/rackticker/plugins").glob("*/.source.json"):
    record = json.loads(source.read_text())
    if record.get("repo") != "rackticker" or not record.get("folder", "").startswith("community/"):
        continue
    name = record["folder"].split("/", 1)[1]
    record.update(repo="rackticker-community-plugins", folder=f"plugins/{name}", url=f"{NEW}/{name}")
    source.write_text(json.dumps(record, indent=2))
    print("repointed", name)
PY
sudo systemctl restart rackticker
```

## Still open

- The old `community/<name>` URLs 404 now that the folders are gone. That is what the
  note above is for; there is no redirect GitHub can give for a deleted folder.
