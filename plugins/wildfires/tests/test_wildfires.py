from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import plugin as fires

HOME = (33.64, -117.92)
PAYLOAD = {"features": [
    {"attributes": {"IncidentName": "BOUQUET", "IncidentSize": 1048, "PercentContained": 93, "POOState": "US-CA",
                    "FireDiscoveryDateTime": 1791000000000}, "geometry": {"x": -118.4, "y": 34.5}},
    {"attributes": {"IncidentName": "LAC-365197", "IncidentSize": 0.1, "PercentContained": None},
     "geometry": {"x": -118.0, "y": 33.8}},
    {"attributes": {"IncidentName": "OLD ONE", "IncidentSize": 5000, "PercentContained": 100},
     "geometry": {"x": -118.0, "y": 33.8}},
    {"attributes": {"IncidentName": "FAR AWAY", "IncidentSize": 5000, "PercentContained": 10},
     "geometry": {"x": -100.0, "y": 45.0}},
    {"attributes": {"IncidentName": "NO PLACE"}, "geometry": {}}]}
SETTINGS = {"latitude": 0.0, "longitude": 0.0, "within_miles": 250, "min_acres": 10, "cards": 4, "alert": True,
            "alert_miles": 25}


def context(ts, data, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts, timezone.utc), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"wildfires": SETTINGS}},
                           snapshots={"wildfires": SimpleNamespace(data=data)})


class ParseTests(unittest.TestCase):
    def test_keeps_real_nearby_burning_fires(self):
        found = fires.parse(PAYLOAD, HOME, 250, 10)
        self.assertEqual([fire["name"] for fire in found], ["Bouquet"])
        self.assertEqual(found[0]["look"], "NNW")
        self.assertTrue(60 < found[0]["miles"] < 75)

    def test_names(self):
        self.assertEqual(fires.tidy("0445 CROSSWHITE"), "0445 Crosswhite")
        self.assertEqual(fires.tidy("SQF COMPLEX"), "SQF Complex")


class ScreenTests(unittest.TestCase):
    def test_cards(self):
        found = fires.parse(PAYLOAD, HOME, 250, 10) * 2
        module = fires.Wildfires()
        frames = {module.render(context(1791767641, found, t)).tobytes() for t in (0, 3, 7, 10, 14)}
        self.assertGreaterEqual(len(frames), 4)
        self.assertFalse(module.available(context(0, [])))


if __name__ == "__main__":
    unittest.main()
