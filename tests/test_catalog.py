import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CatalogTests(unittest.TestCase):
    def test_catalog_matches_self_contained_plugin_folders(self):
        entries = json.loads((ROOT / 'index.json').read_text())['plugins']
        ids = [entry['id'] for entry in entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {p.name for p in (ROOT / 'plugins').iterdir() if p.is_dir()})
        for entry in entries:
            folder = ROOT / 'plugins' / entry['id']
            manifest = json.loads((folder / 'plugin.json').read_text())
            for key in ('id', 'name', 'author', 'description'):
                self.assertEqual(entry[key], manifest[key])
            self.assertEqual(entry['url'], f"https://github.com/costamesatechsolutions/rackticker-community-plugins/tree/main/plugins/{entry['id']}")
            for file in (manifest['entry'], 'README.md', 'LICENSE', 'AGENTS.md', 'preview.png', 'preview.gif'):
                self.assertTrue((folder / file).is_file(), file)


if __name__ == '__main__':
    unittest.main()
