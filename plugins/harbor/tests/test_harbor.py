from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import plugin as harbor

POSITION = {"MessageType": "PositionReport",
            "MetaData": {"MMSI": 338899000, "ShipName": "EVER GIVEN          ", "latitude": 33.74, "longitude": -118.17},
            "Message": {"PositionReport": {"Latitude": 33.74, "Longitude": -118.17, "Sog": 0.1, "Cog": 208,
                                           "NavigationalStatus": 1}}}
STATIC = {"MessageType": "ShipStaticData", "MetaData": {"MMSI": 338899000, "ShipName": "EVER GIVEN"},
          "Message": {"ShipStaticData": {"Type": 71, "Destination": "LONG  BEACH", "Dimension": {"A": 300, "B": 100}}}}


def context(data, t=0.0):
    return SimpleNamespace(now=datetime(2026, 10, 12, tzinfo=timezone.utc), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"harbor": {}}},
                           snapshots={"harbor": SimpleNamespace(data=data)})


class FeedTests(unittest.TestCase):
    def test_messages_build_a_ship(self):
        feed = harbor.Feed(SimpleNamespace(settings={}))
        feed._message(POSITION)
        feed._message(STATIC)
        ship = feed.ships[338899000]
        self.assertEqual((ship["name"], ship["length"], ship["destination"]), ("Ever Given", 400, "LONG BEACH"))
        self.assertEqual(harbor.kind(ship["type"])[0], "CARGO SHIP")
        self.assertEqual(harbor.doing(ship), "AT ANCHOR")

    def test_box_reaches_the_port_from_costa_mesa(self):
        south, west, north, east = harbor.box((33.64, -117.92), 20)
        self.assertTrue(south < 33.75 < north and west < -118.2 < east)


class ScreenTests(unittest.TestCase):
    def test_cards(self):
        ships = [{"mmsi": i, "name": f"Ship {i}", "lat": 33.6 + i * .01, "lon": -118.1 - i * .01, "speed": i % 3 * 6,
                  "course": 90, "status": 1 if i % 4 == 0 else 0, "type": 70 + i % 20, "length": 50 * i,
                  "destination": "OAKLAND"} for i in range(1, 12)]
        data = {"ships": ships, "area": harbor.box((33.64, -117.92), 20), "home": (33.64, -117.92)}
        module = harbor.Harbor()
        frames = {module.render(context(data, t)).tobytes() for t in (0, 5, 13, 19, 25, 31)}
        self.assertGreaterEqual(len(frames), 5)
        self.assertFalse(module.available(context({"ships": [], "area": data["area"], "home": data["home"]})))


if __name__ == "__main__":
    unittest.main()
