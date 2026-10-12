import json
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import plugin as wiki

PAYLOAD = {"query": {"recentchanges": [
    {"type": "edit", "title": "Moon", "rcid": 1, "bot": False, "oldlen": 100, "newlen": 340,
     "timestamp": "2026-10-12T01:24:51Z"},
    {"type": "new", "title": "A brand new page", "rcid": 2, "bot": False, "oldlen": 0, "newlen": 900,
     "timestamp": "2026-10-12T01:24:52Z"},
    {"type": "edit", "title": "Robot tidy", "rcid": 3, "bot": True, "oldlen": 10, "newlen": 9,
     "timestamp": "2026-10-12T01:24:53Z"},
    {"type": "edit", "title": "Broken", "rcid": 4}]}}


def context(ts, data, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts, timezone.utc), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"wiki_pulse": {}}},
                           snapshots={"wiki_pulse": SimpleNamespace(data=data)})


class ParseTests(unittest.TestCase):
    def test_rows(self):
        rows = wiki.parse(json.dumps(PAYLOAD), include_bots=False)
        self.assertEqual([row[2] for row in rows], ["Moon", "A brand new page"])
        self.assertEqual(rows[0][3], 240)
        self.assertTrue(rows[1][4])
        self.assertEqual(len(wiki.parse(json.dumps(PAYLOAD), include_bots=True)), 3)


class ScreenTests(unittest.TestCase):
    def test_cards(self):
        start = datetime(2026, 10, 12, 1, 25, tzinfo=timezone.utc).timestamp()
        recent = [(i, start - 30 - i * 2, f"Article {i % 5}", (-1) ** i * 50 * i, i % 7 == 0) for i in range(40)]
        data = {"recent": recent, "hot": [("Article 1", 8), ("Article 2", 5), ("Article 3", 2)],
                "new": ["A brand new page", "Another one"], "language": "en", "span": 3600, "count": 40}
        module = wiki.WikiPulse()
        frames = {module.render(context(start + t, data, t)).tobytes() for t in (0, 3, 6, 13, 18, 23, 26)}
        self.assertGreaterEqual(len(frames), 5)
        self.assertFalse(module.available(context(start, None)))


if __name__ == "__main__":
    unittest.main()
