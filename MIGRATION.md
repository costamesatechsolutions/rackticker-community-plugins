# Community repository migration

## Completed here

- Created a separate community repository, with one self-contained folder per plugin.
- Copied Virtual Aquarium 1.0.0 from standalone commit `769ca73`, retaining its ID,
  runtime code, tests and license. Updated only its local documentation.
- Added Retro Screensavers 1.0.0 as a new independent plugin.
- Added a root index.json using the existing community-catalog schema and folder URLs.

No changes to the RackTicker main repository, deployed core, existing plugin
source URLs or running device configuration are part of this repository setup.
The standalone aquarium repository remains accessible for existing links.

## Future work — requires an explicit migration task

1. Copy existing community plugins one at a time; retain IDs, settings schema,
   version history/provenance and licenses. Test each in the third-party sandbox.
2. Add entries to this catalog and verify each public folder URL with the installer.
3. Plan update-source transitions for already installed plugins; preserve settings
   and playlist membership. Merely copying files does not migrate installed sources.
4. In a separately reviewed RackTicker change, point the remote community catalog
   at this repository and update its bundled fallback catalog. Keep old links usable.
5. Remove old source copies only after that migration is validated and explicitly approved.

Do not point the core browser at this two-entry catalog prematurely: that would
hide the existing community entries until they have been migrated or linked here.
