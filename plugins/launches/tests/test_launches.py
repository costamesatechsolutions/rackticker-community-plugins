from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import plugin as launches

HOME = (33.64, -117.92)
SETTINGS = {"latitude": 0.0, "longitude": 0.0, "count": 4, "visible_miles": 400, "alert": True,
            "alert_lead_minutes": 10}


def row(net, name="Falcon 9 Block 5 | Starlink Group 15-25", lat=34.632, lon=-120.611, place="Vandenberg SFB, CA, USA",
        precision="Second", status="Go"):
    return {"id": name + net, "name": name, "net": net, "net_precision": {"name": precision},
            "status": {"abbrev": status}, "pad": {"latitude": lat, "longitude": lon, "location": {"name": place}},
            "rocket": {"configuration": {"name": name.split(" | ")[0]}},
            "launch_service_provider": {"name": "SpaceX"}}


def context(ts, data, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts).astimezone(), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"launches": SETTINGS}},
                           snapshots={"launches": SimpleNamespace(data=data)})


class ParseTests(unittest.TestCase):
    def test_vandenberg_from_costa_mesa(self):
        [launch] = launches.parse({"results": [row("2026-10-13T00:11:47Z")]}, HOME)
        self.assertEqual((launch["rocket"], launch["mission"], launch["site"]),
                         ("Falcon 9", "Starlink Group 15-25", "Vandenberg"))
        self.assertTrue(150 < launch["miles"] < 175)
        self.assertEqual(launch["look"], "WNW")
        self.assertFalse(launch["twilight"])          # 5:11 pm in October: the Sun is still up

    def test_twilight_after_sunset(self):
        [launch] = launches.parse({"results": [row("2026-10-13T02:20:00Z")]}, HOME)   # 7:20 pm PDT
        self.assertTrue(launch["twilight"])

    def test_bad_rows_are_skipped(self):
        self.assertEqual(launches.parse({"results": [{"net": "soon"}, row("2026-10-13T00:11:47Z")]}, HOME)[0]["site"],
                         "Vandenberg")


class ScreenTests(unittest.TestCase):
    def test_local_launch_first_and_take_over(self):
        rows = [row("2026-10-12T10:00:00Z", name="Falcon 9 Block 5 | Far Away", lat=28.5, lon=-80.6,
                    place="Cape Canaveral SFS, FL, USA"), row("2026-10-14T00:00:00Z")]
        data = launches.parse({"results": rows}, HOME)
        start = datetime(2026, 10, 11, 20, tzinfo=timezone.utc).timestamp()
        module = launches.Launches()
        self.assertEqual(module._order(data, SETTINGS, start)[0]["site"], "Vandenberg")
        net = data[1]["net"]
        before = module.render(context(net - 120, data))
        after = module.render(context(net + 60, data))
        self.assertIsNotNone(before.getbbox())
        self.assertNotEqual(before.tobytes(), after.tobytes())
        self.assertIsNone(module._live(data, SETTINGS, net - 3600))


if __name__ == "__main__":
    unittest.main()
