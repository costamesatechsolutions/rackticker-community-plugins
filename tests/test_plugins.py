"""Every community plugin loads, registers and renders with no data.

These need a RackTicker checkout importable beside this repository, the same
way `python -m app.dev check` does; without one they skip rather than fail.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import unittest

try:
    from app.core.config import validate_config
    from app.core.manifest import read_manifest
    from app.core.models import Message, Snapshot, SystemStatus
    from app.core.plugins import PluginRegistry
    from app.core.renderer import validate_frame
    from app.modules.base import RenderContext
except ImportError:                     # no RackTicker beside us
    validate_config = None

COMMUNITY = Path(__file__).resolve().parents[1] / "plugins"


needs_rackticker = unittest.skipIf(validate_config is None,
                                   "clone RackTicker beside this repository to run these")


@needs_rackticker
class CommunityTests(unittest.TestCase):
    def test_index_lists_real_folders(self):
        index = json.loads((COMMUNITY.parent / "index.json").read_text())
        for entry in index["plugins"]:
            self.assertTrue((COMMUNITY / entry["id"] / "plugin.json").exists(), entry["id"])
            self.assertTrue(entry["url"].endswith(f"/plugins/{entry['id']}"))

    def test_each_plugin_registers_and_renders_empty(self):
        for folder in sorted(path for path in COMMUNITY.iterdir() if (path / "plugin.json").exists()):
            with self.subTest(folder.name):
                manifest = read_manifest(folder)
                spec = importlib.util.spec_from_file_location(f"community_{manifest.id}", folder / manifest.entry)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                registry = PluginRegistry()
                registry.register(module.plugin)
                config = validate_config({}, registry)
                screen = module.plugin.module()
                context = RenderContext(datetime.now(timezone.utc), 1.0, config, {}, Message("", ""), SystemStatus())
                # Some of these wait for a feed and some draw their own world and
                # are ready at once. What every one of them owes is a straight
                # answer about whether it is ready, and a frame that is legal.
                self.assertIsInstance(screen.available(context), bool)
                validate_frame(screen.render(context))


def community(name):
    spec = importlib.util.spec_from_file_location(f"community_{name}_test", COMMUNITY / name / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@needs_rackticker
class NameFittingTests(unittest.TestCase):
    def test_tank_names_keep_every_word_and_stay_on_the_panel(self):
        tanks = community("tanks")
        from rackticker import tiny_width
        self.assertEqual(tanks.name_lines("Shasta"), (["Shasta"], False))
        for name in ("Oroville", "New Melones", "Don Pedro", "Waste water"):
            lines, small = tanks.name_lines(name)
            with self.subTest(name=name, lines=lines):
                self.assertTrue(small)
                self.assertEqual(" ".join(lines), name.upper())       # "New Melones" was just "New"
                self.assertTrue(all(tiny_width(line) <= tanks.NAME_ROOM for line in lines))

    def test_a_long_place_name_rests_then_glides_to_its_end_instead_of_looping(self):
        quakes = community("quakes")
        from rackticker import text_width
        resting, distance = quakes._name_stops("Johannesburg", 60)
        self.assertTrue("Johannesburg".startswith(resting))
        self.assertLessEqual(text_width(resting, 1, True), 60)
        self.assertLessEqual(text_width("Johannesburg", 1, True) - distance, 60)


@needs_rackticker
class DeparturesTests(unittest.TestCase):
    def test_long_names_shorten_the_way_boards_do(self):
        departures = community("departures")
        self.assertEqual(departures._fits("MILANO CENTRALE", 70, False, "trenitalia"), "MILANO C.LE")
        self.assertEqual(departures._fits("Genève-Aéroport", 40, True), "Genève")
        self.assertEqual(departures._fits("Eger", 40, True), "Eger")

    def test_american_names_are_not_run_through_italian_abbreviations(self):
        # "Santa"/"San " -> "S." is how a Trenitalia sign shortens Santa Lucia; on an
        # Amtrak or Metrolink board it turned San Diego and Santa Ana into just "S.",
        # which is not a real station and not what any American sign does. Cut back to
        # whole words it came out as a bare "San", which is not one either.
        departures = community("departures")
        self.assertEqual(departures._fits("San Diego", 35, True, "amtrak"), "San Di.")
        self.assertEqual(departures._fits("Santa Ana", 45, True, "metrolink"), "Santa A.")
        self.assertEqual(departures._fits("San Bernardino", 57, True, "metrolink"), "San Berna.")
        self.assertEqual(departures._fits("New York", 30, True, "amtrak"), "NY")

    def test_paired_platforms_fit_the_column(self):
        departures = community("departures")
        self.assertEqual(departures._track_label("43/44"), "43")
        self.assertEqual(departures._track_label("7/8"), "7/8")
        self.assertEqual(departures._track_label("12"), "12")

    def test_station_announces_delays_platforms_and_cancellations(self):
        from zoneinfo import ZoneInfo
        departures = community("departures")
        when = datetime(2026, 9, 18, 17, 5, tzinfo=ZoneInfo("Europe/Rome"))
        row = {"time": when, "delay": 15, "kind": "FR", "number": "9612", "destination": "Milano Centrale",
               "track": "24", "moved": False, "cancelled": False}
        heading, said = departures.notices([row, {**row, "delay": 2}, {**row, "delay": 0, "moved": True},
                                            {**row, "cancelled": True}], "trenitalia")
        self.assertEqual(heading, "AVVISO")
        self.assertEqual(said, ["FR 9612 per MILANO CENTRALE delle 17:05: ritardo 15 minuti",
                                "FR 9612 per MILANO CENTRALE delle 17:05 parte dal binario 24",
                                "FR 9612 per MILANO CENTRALE delle 17:05 è cancellato"])


@needs_rackticker
class BoardLoopTests(unittest.TestCase):
    """A board left up longer than its own cycle must keep boarding, not freeze."""

    def rows(self):
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        start = datetime.now(ZoneInfo("Europe/Rome")) + timedelta(minutes=8)
        return [{"time": start + timedelta(minutes=n * 7), "delay": 15 if n == 0 else 0,
                 "kind": "FR", "number": f"96{n}2", "name": "", "destination": "Milano Centrale",
                 "track": str(10 + n), "moved": n == 1, "cancelled": n == 2}
                for n in range(6)]

    def board(self):
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        from app.core.config import validate_config
        from app.core.models import Message, Snapshot, SystemStatus
        from app.core.plugins import PluginRegistry
        from app.modules.base import RenderContext
        departures = community("departures")
        registry = PluginRegistry(); registry.register(departures.plugin)
        config = validate_config({"plugins": {"departures": {"station": "roma_termini",
                                                            "clock": "station", "times": "station"}},
                                  "modules": {"departures": {"enabled": True}},
                                  "playlist": [{"id": "d", "module": "departures"}]}, registry)
        zone = ZoneInfo("Europe/Rome")
        rows = self.rows()
        snapshot = Snapshot({"roma_termini": {"rows": rows,
                                              "fetched_moment": rows[0]["time"].isoformat(), "live": True}})
        module = departures.Board()
        return lambda t: module.render(RenderContext(datetime.now(zone), t, config,
                                                     {"departures": snapshot}, Message(), SystemStatus(), 1))

    def test_the_board_is_still_moving_long_after_its_announcements(self):
        render = self.board()
        # Far past one full cycle of title, pages and announcements.
        frames = {render(t).tobytes() for t in (120.0, 123.0, 126.0, 129.0, 132.0)}
        self.assertGreater(len(frames), 3, "the board froze after its announcements")

    def test_a_station_with_nothing_left_to_depart_is_skipped(self):
        """A full timetable with every train gone is an empty screen, not a board."""
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        from app.core.config import validate_config
        from app.core.models import Message, Snapshot, SystemStatus
        from app.core.plugins import PluginRegistry
        from app.modules.base import RenderContext
        departures = community("departures")
        registry = PluginRegistry(); registry.register(departures.plugin)
        config = validate_config({"plugins": {"departures": {"station": "roma_termini",
                                                            "clock": "station", "times": "station"}},
                                  "modules": {"departures": {"enabled": True}},
                                  "playlist": [{"id": "d", "module": "departures"}]}, registry)
        zone = ZoneInfo("Europe/Rome")
        gone = datetime.now(zone) - timedelta(hours=3)
        rows = [{"time": gone, "delay": 0, "kind": "FR", "number": "9602", "name": "",
                 "destination": "Milano", "track": "10", "moved": False, "cancelled": False}]
        snapshot = Snapshot({"roma_termini": {"rows": rows, "fetched_moment": gone.isoformat(), "live": True}})
        context = RenderContext(datetime.now(zone), 5.0, config, {"departures": snapshot},
                                Message(), SystemStatus(), 1)
        module = departures.Board()
        self.assertFalse(module.available(context), "a board with nothing upcoming was offered")
        self.assertIsNotNone(module.render(context).getbbox(), "it drew an empty screen")

    def test_it_comes_back_to_the_departures_themselves(self):
        """One full cycle later the board is showing the same page again."""
        departures = community("departures")
        render, rows = self.board(), self.rows()
        _, title, pages, _, spoken = departures.Board()._plan(rows, "trenitalia")
        cycle = title + pages * departures.PAGE_SECONDS + sum(seconds for _, seconds in spoken)
        # A moment inside the pages, after the train has pulled in and the title has gone.
        moment = departures.SCENE_SECONDS + title + 1.0
        self.assertEqual(render(moment).tobytes(), render(moment + cycle).tobytes(),
                         "the board did not come back round to the same page")


@needs_rackticker
class AmtrakTests(unittest.TestCase):
    """Amtrak's own feed, as the board reads it."""

    def run_for(self, **extra):
        return {"trainNum": "580", "routeName": "Pacific Surfliner", "destName": "San Diego Santa Fe Depot",
                "destCode": "SAN", "trainState": "Active",
                "stations": [{"code": "ANA", "schDep": "2026-09-19T15:49:00-07:00",
                              "dep": "2026-09-19T16:01:00-07:00", "platform": "2", "depCmnt": ""}],
                **extra}

    def row(self, run, code="ANA"):
        from zoneinfo import ZoneInfo
        return community("departures")._amtrak_row(run, code, ZoneInfo("America/Los_Angeles"))

    def test_a_departure_carries_its_route_destination_and_delay(self):
        row = self.row(self.run_for())
        self.assertEqual(row["kind"], "SURF")            # the timetable's name for the route
        self.assertEqual(row["number"], "580")
        self.assertEqual(row["destination"], "San Diego")  # not "San Diego Santa Fe Depot"
        self.assertEqual(row["delay"], 12)
        self.assertEqual(row["track"], "2")
        self.assertEqual(row["time"].strftime("%H:%M"), "15:49")

    def test_a_train_that_ends_here_is_an_arrival_and_not_shown(self):
        self.assertIsNone(self.row(self.run_for(destCode="ANA")))

    def test_a_stop_with_no_departure_time_is_not_a_departure(self):
        run = self.run_for()
        run["stations"][0] = {"code": "ANA", "schArr": "2026-09-19T15:48:00-07:00"}
        self.assertIsNone(self.row(run))

    def test_a_train_that_does_not_call_here_is_skipped(self):
        self.assertIsNone(self.row(self.run_for(), code="LAX"))

    def test_a_cancelled_stop_is_marked(self):
        run = self.run_for()
        run["stations"][0]["depCmnt"] = "Cancelled"
        self.assertTrue(self.row(run)["cancelled"])

    def test_an_unlisted_route_still_gets_a_badge(self):
        row = self.row(self.run_for(routeName="Borealis Extra"))
        self.assertTrue(row["kind"])
        self.assertLessEqual(len(row["kind"]), 5)


@needs_rackticker
class BartTests(unittest.TestCase):
    """BART counts in minutes from now; the board works in clock times."""

    PAYLOAD = {"root": {"station": [{"abbr": "EMBR", "etd": [
        {"destination": "Antioch", "estimate": [
            {"minutes": "Leaving", "platform": "2", "color": "YELLOW", "hexcolor": "#ffff33", "delay": "274"},
            {"minutes": "17", "platform": "2", "color": "YELLOW", "hexcolor": "#ffff33", "delay": "0"}]},
        {"destination": "Millbrae", "estimate": [
            {"minutes": "8", "platform": "1", "color": "RED", "hexcolor": "#ff0000", "delay": "0",
             "cancelflag": "1"},
            {"minutes": "", "platform": "1", "color": "RED", "hexcolor": "#ff0000", "delay": "0"}]}]}]}}

    def bart_rows(self):
        import asyncio
        from datetime import datetime
        from zoneinfo import ZoneInfo
        departures = community("departures")
        zone = ZoneInfo("America/Los_Angeles")
        when = datetime(2026, 9, 19, 19, 0, tzinfo=zone)

        class Reply:
            status = 200
            def raise_for_status(self): pass
            async def json(self, content_type=None): return BartTests.PAYLOAD
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False

        class Session:
            def get(self, *args, **kwargs): return Reply()

        return asyncio.run(departures.bart(Session(), "EMBR", when, zone))

    def test_minutes_from_now_become_departure_times(self):
        rows = self.bart_rows()
        times = [row["time"].strftime("%H:%M") for row in rows]
        self.assertEqual(times[:3], ["19:00", "19:17", "19:08"])   # "Leaving" is now

    def test_each_line_keeps_its_own_colour_and_platform(self):
        rows = self.bart_rows()
        self.assertEqual(rows[0]["kind"], "YEL")
        self.assertEqual(rows[0]["color"], "ffff33")
        self.assertEqual(rows[0]["track"], "2")
        self.assertEqual(rows[0]["delay"], 5)        # BART counts delay in seconds
        self.assertTrue(rows[2]["cancelled"])

    def test_a_train_with_no_estimate_is_left_off(self):
        self.assertEqual(len(self.bart_rows()), 3)   # four estimates, one without minutes

    def test_a_pale_line_colour_gets_dark_letters(self):
        """Nothing reads white on BART's yellow."""
        from PIL import Image
        departures = community("departures")
        frame = Image.new("RGB", (128, 9))
        departures._badge(frame, "YEL", 0, 1, "bart", "ffff33")
        ink = {frame.load()[x, y] for x in range(2, 20) for y in range(1, 8)}
        self.assertIn((255, 255, 51), ink)                  # the line's real colour, undimmed
        self.assertTrue(any(sum(c) < 120 for c in ink))     # and dark letters on it


@needs_rackticker
class TubeTests(unittest.TestCase):
    """The Underground counts in seconds to the platform, not clock times."""

    ARRIVALS = [
        {"lineName": "Victoria", "towards": "Brixton", "timeToStation": 540,
         "platformName": "Southbound - Platform 4"},
        {"lineName": "Central", "towards": "Hainault via Newbury Park", "timeToStation": 60,
         "platformName": "Eastbound - Platform 2"},
        {"lineName": "Northern", "towards": "Check Front of Train", "timeToStation": 120,
         "platformName": "Southbound"},
        {"lineName": "Bakerloo", "towards": "Elephant and Castle", "timeToStation": None,
         "platformName": "Southbound - Platform 3"},
    ]

    def board(self):
        import asyncio
        from datetime import datetime
        from zoneinfo import ZoneInfo
        departures = community("departures")
        zone = ZoneInfo("Europe/London")
        when = datetime(2026, 9, 19, 18, 0, tzinfo=zone)

        class Reply:
            def raise_for_status(self): pass
            async def json(self, content_type=None): return TubeTests.ARRIVALS
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False

        class Session:
            def get(self, *args, **kwargs): return Reply()

        return asyncio.run(departures.tfl(Session(), "940GZZLUOXC", when, zone))

    def test_seconds_to_the_platform_become_a_departure_time(self):
        rows = {row["kind"]: row for row in self.board()}
        self.assertEqual(rows["VIC"]["time"].strftime("%H:%M"), "18:09")
        self.assertEqual(rows["CEN"]["time"].strftime("%H:%M"), "18:01")

    def test_each_line_carries_the_colour_it_is_on_the_map(self):
        rows = {row["kind"]: row for row in self.board()}
        self.assertEqual(rows["VIC"]["color"], "0098d8")
        self.assertEqual(rows["CEN"]["color"], "dc241f")

    def test_the_platform_number_is_taken_out_of_the_direction(self):
        rows = {row["kind"]: row for row in self.board()}
        self.assertEqual(rows["VIC"]["track"], "4")
        self.assertEqual(rows["CEN"]["track"], "2")

    def test_a_destination_of_via_somewhere_keeps_only_the_destination(self):
        rows = {row["kind"]: row for row in self.board()}
        self.assertEqual(rows["CEN"]["destination"], "Hainault")

    def test_a_train_that_will_not_say_where_it_is_going_is_left_off(self):
        self.assertNotIn("NOR", {row["kind"] for row in self.board()})

    def test_a_train_with_no_time_is_left_off(self):
        self.assertNotIn("BAK", {row["kind"] for row in self.board()})

    def test_the_northern_line_is_not_drawn_in_black_on_a_black_panel(self):
        departures = community("departures")
        badge, colour = departures.TUBE_LINES["Northern"]
        self.assertEqual(badge, "NOR")
        self.assertGreater(sum(int(colour[i:i + 2], 16) for i in (0, 2, 4)), 120)


@needs_rackticker
class MetrolinkTests(unittest.TestCase):
    """Metrolink answers for every station at once, in milliseconds since the epoch."""

    ROWS = [
        {"PlatformName": "ARTIC", "TrainDesignation": "M1860", "RouteCode": "IEOC LINE",
         "TrainDestination": "San Bernardino - Downtown", "TrainMovementTime": "/Date(1789876140000)/",
         "CalcTrainMovementTime": "/Date(1789876440000)/", "CalculatedStatus": "ON TIME",
         "FormattedTrackDesignation": "Track 1"},
        {"PlatformName": "ARTIC", "TrainDesignation": "A591S", "RouteCode": "PAC SURF",
         "TrainDestination": "LA Union Station", "TrainMovementTime": "/Date(1789877580000)/",
         "CalcTrainMovementTime": "/Date(0)/", "CalculatedStatus": "CANCELLED",
         "FormattedTrackDesignation": "Track 2"},
        {"PlatformName": "FULLERTON", "TrainDesignation": "M1754", "RouteCode": "91/PV Line",
         "TrainDestination": "South Perris", "TrainMovementTime": "/Date(1789876140000)/",
         "CalcTrainMovementTime": "/Date(1789876140000)/", "CalculatedStatus": "ON TIME",
         "FormattedTrackDesignation": "Track 3"},
    ]

    def board(self, platform):
        import asyncio
        from datetime import datetime
        from zoneinfo import ZoneInfo
        departures = community("departures")
        departures._metrolink_cache.update(at=0.0, rows=None)
        zone = ZoneInfo("America/Los_Angeles")

        class Reply:
            def raise_for_status(self): pass
            async def json(self, content_type=None): return MetrolinkTests.ROWS
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False

        class Session:
            def get(self, *args, **kwargs): return Reply()

        return asyncio.run(departures.metrolink(Session(), platform, datetime.now(zone), zone))

    def test_only_the_trains_calling_at_this_platform(self):
        self.assertEqual([row["number"] for row in self.board("FULLERTON")], ["M1754"])

    def test_the_line_keeps_its_own_name_and_the_track_loses_the_word(self):
        row = self.board("ARTIC")[0]
        self.assertEqual(row["kind"], "IEOC")
        self.assertEqual(row["track"], "1")
        self.assertEqual(row["delay"], 5)
        self.assertEqual(row["destination"], "San Bernardino")   # not "- Downtown" as well

    def test_a_placeholder_time_is_not_a_train_twenty_seven_years_late(self):
        cancelled = self.board("ARTIC")[1]
        self.assertEqual(cancelled["delay"], 0)
        self.assertTrue(cancelled["cancelled"])

    def test_a_train_finishing_its_run_here_is_not_a_departure(self):
        self.assertEqual([row["number"] for row in self.board("LAUS")], [])


@needs_rackticker
class OnboardTests(unittest.TestCase):
    """The display above the carriage doors: where the train is, and what it is coming to."""

    # Southwest Chief: stops a hundred miles apart along a line, 12:00 (LA) to 15:00.
    PLACES = {"S0": (34.0, -118.0), "S1": (35.0, -117.0), "S2": (36.0, -116.0), "S3": (37.0, -115.0)}

    def run_for(self, statuses, speed=61.2, position=(34.5, -117.5), fix="2026-09-19T12:20:00-07:00"):
        stations = []
        for index, status in enumerate(statuses):
            hour = 10 + index
            stop = {"code": f"S{index}", "name": f"Stop {index} Station", "status": status,
                    "schArr": f"2026-09-19T{hour:02d}:00:00-07:00", "schDep": f"2026-09-19T{hour:02d}:05:00-07:00"}
            if status != "Enroute" or index >= 2:
                stop.update(arr=f"2026-09-19T{hour:02d}:10:00-07:00", dep=f"2026-09-19T{hour:02d}:15:00-07:00")
            stations.append(stop)
        return {"trainNum": "4", "routeName": "Southwest Chief", "origName": "Los Angeles Union",
                "destName": "Chicago Union Station", "trainState": "Active", "velocity": speed,
                "lat": position[0], "lon": position[1], "lastValTS": fix, "stations": stations}

    def journey(self, statuses, **kwargs):
        onboard = community("onboard")
        return onboard.journey(self.run_for(statuses, **kwargs), self.PLACES)

    def test_the_next_stop_is_the_one_after_the_last_the_train_left(self):
        ride = self.journey(["Departed", "Departed", "Enroute", "Enroute"])
        self.assertEqual(ride["next"], 2)
        self.assertEqual(ride["stops"][2]["name"], "Stop 2")     # "Station" trimmed off the end
        self.assertEqual(ride["to"], "Chicago")
        self.assertEqual(ride["late"], 10)
        self.assertTrue(ride["moving"])
        self.assertEqual(ride["left"], 1)

    def test_stops_the_feed_never_heard_about_are_not_where_the_train_is_heading(self):
        """Amtraker says 'Station', with no times, for stops it has no news of. Live, the
        first ten stops of a train's run read like that, and the screen named the first."""
        onboard = community("onboard")
        run = self.run_for(["Station", "Station", "Departed", "Enroute"])
        for stop in run["stations"][:2]:
            stop.pop("arr", None), stop.pop("dep", None)
        ride = onboard.journey(run, self.PLACES)
        self.assertEqual(ride["next"], 3)
        self.assertFalse(ride["here"])

    def test_a_train_standing_at_a_platform_says_so(self):
        ride = self.journey(["Departed", "Station", "Enroute"], speed=0, position=(35.0, -117.0))
        self.assertEqual(ride["next"], 1)
        self.assertTrue(ride["here"])
        self.assertEqual(ride["late"], 10)                        # measured against when it is due to leave
        # ...but 'Station' on a train doing sixty is the feed being behind, not a train at a platform.
        moving = self.journey(["Departed", "Station", "Enroute"], speed=60)
        self.assertFalse(moving["here"])
        self.assertEqual(moving["next"], 2)

    def test_where_the_train_is_between_two_stops_comes_from_where_it_is(self):
        ride = self.journey(["Departed", "Departed", "Enroute"], position=(35.5, -116.5))
        self.assertTrue(ride["geo"])
        self.assertAlmostEqual(ride["p0"], .5, delta=.02)
        # A position nowhere near the line between the two stops is not trusted.
        lost = self.journey(["Departed", "Departed", "Enroute"], position=(45.0, -90.0))
        self.assertFalse(lost["geo"])

    def test_the_train_is_carried_forward_between_pictures_but_only_for_a_while(self):
        onboard = community("onboard")
        ride = self.journey(["Departed", "Departed", "Enroute"], position=(35.5, -116.5))
        asof = 1_000_000.0
        soon, later = onboard.progress(ride, asof + 60, asof), onboard.progress(ride, asof + 600, asof)
        self.assertGreater(soon, ride["p0"])
        self.assertGreater(later, soon)
        capped = onboard.progress(ride, asof + 5 * 3600, asof)
        self.assertEqual(capped, onboard.progress(ride, asof + 300, asof))     # never runs away on old news

    def test_without_positions_the_timetable_places_the_train(self):
        onboard = community("onboard")
        ride = onboard.journey(self.run_for(["Departed", "Departed", "Enroute"]))     # no station coordinates
        self.assertFalse(ride["geo"])
        middle = (ride["behind"] + ride["arrive"]) / 2
        self.assertAlmostEqual(onboard.progress(ride, middle, 0), .5, delta=.01)
        self.assertEqual(onboard.progress(ride, ride["behind"] - 999, 0), 0.0)

    def test_a_run_with_no_stops_or_no_stops_left_is_not_a_ride(self):
        onboard = community("onboard")
        self.assertIsNone(onboard.journey({"stations": []}))
        self.assertIsNone(self.journey(["Departed", "Departed", "Departed"]))

    def test_a_train_whose_tracker_went_quiet_is_not_one_to_ride(self):
        onboard = community("onboard")
        fresh, quiet = self.run_for(["Departed", "Enroute"]), self.run_for(["Departed", "Enroute"])
        quiet["lastValTS"] = "2026-09-19T05:00:00-07:00"
        now = datetime.fromisoformat("2026-09-19T12:30:00-07:00").timestamp()
        self.assertTrue(onboard.live(fresh, now))
        self.assertFalse(onboard.live(quiet, now))
        self.assertFalse(onboard.live(dict(fresh, trainState="Predeparture"), now))

    def test_the_bar_only_ever_moves_forwards(self):
        onboard = community("onboard")
        ride = self.journey(["Departed", "Departed", "Enroute"])
        screen, shown = onboard.Carriage(), []
        for now, target in ((0, .40), (1, .41), (2, .405), (3, .39), (4, .43)):
            shown.append(screen._smooth(ride, target, now))
        self.assertEqual(shown, sorted(shown))
        self.assertEqual(screen._smooth(dict(ride, next=3), .10, 5), .10)   # a new stop starts a new bar

    def test_lateness_reads_in_words_and_colours(self):
        onboard = community("onboard")
        self.assertEqual(onboard.verdict(0), ("ON TIME", onboard.GREEN))
        self.assertEqual(onboard.verdict(12), ("12M LATE", onboard.AMBER))
        self.assertEqual(onboard.verdict(34), ("34M LATE", onboard.RED))
        self.assertEqual(onboard.verdict(-9), ("9M EARLY", onboard.GREEN))
        self.assertEqual((onboard.duration(45), onboard.duration(75)), ("45M", "1H15M"))

    def test_the_nearest_train_to_home_is_the_one_to_ride(self):
        onboard = community("onboard")
        far = dict(self.journey(["Departed", "Enroute"], position=(45.0, -120.0)), number="1")
        near = dict(self.journey(["Departed", "Enroute"], position=(33.8, -117.9)), number="2")
        self.assertEqual(onboard.nearest([far, near], (33.7, -117.9))["number"], "2")
        self.assertIn(onboard.nearest([far, near], None)["number"], ("1", "2"))

    def test_station_names_lose_what_every_station_has(self):
        onboard = community("onboard")
        self.assertEqual(onboard.short("Los Angeles Union"), "Los Angeles")
        self.assertEqual(onboard.short("New York Penn Station"), "New York")
        self.assertEqual(onboard.short("Emeryville"), "Emeryville")
        self.assertEqual(onboard.short("Oakland-Jack London Square, CA"), "Oakland Jack London Square")

    def test_no_train_running_is_an_answer_not_a_provider_error(self):
        import asyncio
        onboard = community("onboard")

        class Quiet(onboard.Onboard):
            async def _trains(self):
                return "Coast Starlight", ["11"]

            async def _json(self, url):
                return {"11": [dict(self.run_for_test, trainState="Predeparture")]}

            async def _stations(self):
                return {}

        provider = Quiet(type("Context", (), {"settings": {"refresh_seconds": 60, "latitude": 0, "longitude": 0}})())
        provider.run_for_test = self.run_for(["Enroute", "Enroute"])

        async def go():
            try:
                return await provider.fetch()
            finally:
                await provider.close()
        snapshot = asyncio.run(go())
        self.assertIsNone(snapshot.data["ride"])

    def test_the_screen_draws_every_kind_of_stop_name_without_running_off_the_panel(self):
        onboard = community("onboard")
        for name in ("Chemult", "Los Angeles Union", "San Juan Capistrano", "Oakland-Jack London Square",
                     "Winston-Salem"):
            for statuses in (["Departed", "Enroute"], ["Departed", "Station"]):
                with self.subTest(name=name, statuses=statuses):
                    run = self.run_for(statuses + ["Enroute"], speed=0 if statuses[1] == "Station" else 55)
                    run["stations"][statuses.index(statuses[1])]["name"] = name
                    ride = onboard.journey(run, self.PLACES)
                    self.assertIsNotNone(ride)
                    now = datetime.now(timezone.utc)
                    snapshot = Snapshot({"ride": ride, "asof": now.timestamp()}, source="amtraker")
                    registry = PluginRegistry()
                    registry.register(onboard.plugin)
                    config = validate_config({"plugins": {"onboard": {}}}, registry)
                    context = RenderContext(now, 1.0, config, {"onboard": snapshot}, Message("", ""), SystemStatus(), 1)
                    frame = validate_frame(onboard.Carriage().render(context))
                    self.assertIsNotNone(frame.getbbox())
                    # nothing is drawn in the strip of rows between the words and the line, so a
                    # name that ran off the panel or down into the train would show here
                    self.assertEqual(frame.crop((0, 26, 128, 27)).getbbox(), None)


@needs_rackticker
class SurfWaterTests(unittest.TestCase):
    """The sea is a function of depth and time, so it is the same sea however long the rack has been on."""

    def waves(self, size=2.0, surface=16.5):
        surf = community("surf")
        waves = surf.Waves()
        waves.build(surface, size)
        return surf, waves

    def crests(self, waves, t, surface=16.5, period=8.0):
        rows = [waves.surface(c, t, period, surface)[0] for c in range(waves.width)]
        return [c for c in range(1, waves.width - 1) if rows[c] < rows[c - 1] and rows[c] <= rows[c + 1]
                and rows[c] < surface - .3]

    def test_the_water_stays_finite_however_long_it_has_run(self):
        surf, waves = self.waves(3.0)
        for hours in (0, 1, 24, 24 * 365):
            for column in range(waves.width):
                row, lift = waves.surface(column, hours * 3600.0, 13, 16.5)
                self.assertTrue(-5 < row < 40 and -1.5 < lift < 1.5, (hours, column, row, lift))

    def test_crests_travel_towards_the_beach(self):
        surf, waves = self.waves(2.5)
        before = self.crests(waves, 10.0)
        after = self.crests(waves, 10.4)
        self.assertTrue(before and after)
        # every crest on the way in is a little further towards the beach a moment later
        for crest in before:
            nearest = min(after, key=lambda c: abs(c - (crest + 1)))
            self.assertGreaterEqual(nearest, crest, "a crest went backwards, out to sea")

    def test_waves_stand_taller_and_bunch_up_as_the_water_shallows(self):
        surf, waves = self.waves(2.0)
        self.assertGreater(max(waves.amp[25:32]), max(waves.amp[:8]) * 1.5)
        gaps = [b - a for a, b in zip(waves.phase, waves.phase[1:])]
        self.assertGreater(gaps[28], gaps[2] * 1.4, "the wave did not shorten over the rising floor")

    def test_they_break_near_the_beach_and_not_out_at_sea(self):
        surf, waves = self.waves(2.0)
        self.assertFalse(any(waves.broken[:10]))
        self.assertTrue(any(waves.broken[26:34]))

    def test_a_screen_with_a_wave_running_draws_white_water(self):
        surf = community("surf")
        registry = PluginRegistry()
        registry.register(surf.plugin)
        config = validate_config({"plugins": {"surf": {}}}, registry)
        data = {"spot": "Huntington Pier", "height": 3.0, "period": 10, "direction": 225, "water": 74,
                "tide": {"high": True, "time": "2026-09-21 19:54", "then": "2026-09-22 02:06"}}
        screen = surf.Report()
        seen, foam = set(), 0
        for frame in range(240):
            context = RenderContext(datetime(2026, 9, 21, 16, 0), frame / 30, config, {"surf": Snapshot(data)},
                                    Message("", ""), SystemStatus(), 1)
            picture = validate_frame(screen.render(context))
            seen.add(picture.crop((88, 8, 128, 32)).tobytes())
            foam += any(picture.getpixel((x, y)) == surf.FOAM_WHITE for x in range(88, 128) for y in range(8, 32))
        self.assertGreater(len(seen), 150, "the sea barely changed from frame to frame")
        self.assertGreater(foam, 100, "no white water")


@needs_rackticker
class TankWaterTests(unittest.TestCase):
    def test_the_surface_moves_smoothly_and_stays_in_the_tank_however_long_it_runs(self):
        surface = community("tanks").Surface(20, 7)
        worst, previous = 0.0, None
        for _ in range(30 * 60 * 20):                       # twenty minutes at 30 fps
            surface.step(1 / 30)
            self.assertTrue(all(abs(h) < 4 for h in surface.height))
            if previous:
                worst = max(worst, max(abs(a - b) for a, b in zip(previous, surface.height)))
            previous = list(surface.height)
        self.assertLess(worst, .6, "the water jumped between frames")

    def test_a_bump_sets_it_sloshing_and_it_settles(self):
        surface = community("tanks").Surface(20, 3)
        surface.next_bump = 1e9
        surface.step(1 / 30)
        calm = max(abs(h) for h in surface.height)
        surface.bumps.append((surface.clock, 1, 1.5))
        peak = 0.0
        for _ in range(60):
            surface.step(1 / 30)
            peak = max(peak, max(abs(h) for h in surface.height))
        for _ in range(30 * 9):
            surface.step(1 / 30)
        self.assertGreater(peak, calm + .5)
        self.assertFalse(surface.bumps, "the slosh never died away")


@needs_rackticker
class AnalyserTests(unittest.TestCase):
    def run_it(self, seconds, playing=True):
        analyser = community("now_playing").Analyser(10, 6)
        frames = []
        for frame in range(int(seconds * 30)):
            t = frame / 30
            analyser.step(t, t * 2.2, playing, 42)
            frames.append((list(analyser.levels), list(analyser.peaks)))
        return frames

    def test_bars_stay_in_range_bloom_rather_than_flash_and_neighbours_move_together(self):
        frames = self.run_it(30)
        for levels, peaks in frames:
            self.assertTrue(all(0 <= v <= 1 for v in levels))
            self.assertTrue(all(p >= v - 1e-9 for p, v in zip(peaks, levels)))
        rises = [max(b - a for a, b in zip(before[0], after[0])) for before, after in zip(frames, frames[1:])]
        self.assertLess(max(rises), .9, "a bar jumped from nothing to full in a single frame")
        gaps = [abs(a - b) for levels, _ in frames[60:] for a, b in zip(levels, levels[1:])]
        self.assertLess(sum(gaps) / len(gaps), .3, "neighbouring bars were unrelated")

    def test_a_falling_bar_speeds_up_like_a_weight(self):
        analyser = community("now_playing").Analyser(10, 6)
        analyser.levels = [1.0] * 10
        drops = []
        for frame in range(30):
            before = analyser.levels[0]
            analyser.step(frame / 30, 0.0, False, 1)
            drops.append(before - analyser.levels[0])
        self.assertGreater(drops[10], drops[1] * 1.5)


@needs_rackticker
class SurfTideTests(unittest.TestCase):
    """The sea sits where the tide puts it: 0 at dead low, 1 at dead high."""

    def level(self, high, turn, then, now="2026-09-19 18:00"):
        surf = community("surf")
        return surf.Report._level({"high": high, "time": turn, "then": then},
                                  datetime.strptime(now, "%Y-%m-%d %H:%M"))

    def test_the_water_is_nearly_in_an_hour_before_high(self):
        self.assertGreater(self.level(True, "2026-09-19 19:00", "2026-09-20 01:12"), .8)

    def test_the_water_is_nearly_out_an_hour_before_low(self):
        self.assertLess(self.level(False, "2026-09-19 19:00", "2026-09-20 01:12"), .2)

    def test_just_past_low_the_water_is_still_down(self):
        self.assertLess(self.level(True, "2026-09-20 00:00", "2026-09-20 06:12"), .1)

    def test_one_turn_of_the_tide_is_not_enough_to_say(self):
        surf = community("surf")
        self.assertIsNone(surf.Report._level({"high": True, "time": "2026-09-19 19:00", "then": None}))
        self.assertIsNone(surf.Report._level(None))

    def test_nonsense_times_do_not_take_the_screen_down(self):
        surf = community("surf")
        self.assertIsNone(surf.Report._level({"high": True, "time": "later", "then": "much later"}))
        # A second turn before the first would divide by a swing of nothing.
        self.assertIsNone(self.level(True, "2026-09-19 19:00", "2026-09-19 19:00"))


@needs_rackticker
class NowPlayingTests(unittest.TestCase):
    def test_synced_lyrics_follow_the_song(self):
        now_playing = community("now_playing")
        lines = now_playing.synced_lines("[00:37.66]Waiting in a car\n[00:42.39]Waiting for a ride\n[01:10.00]")
        self.assertEqual(lines[0], (37.66, "Waiting in a car"))
        self.assertIsNone(now_playing.current_line(lines, 20))
        self.assertEqual(now_playing.current_line(lines, 40)[0], "Waiting in a car")
        self.assertEqual(now_playing.current_line(lines, 45)[0], "Waiting for a ride")
        self.assertIsNone(now_playing.current_line(lines, 55))   # instrumental: the analyser's turn
