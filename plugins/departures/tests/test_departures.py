from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from PIL import Image

import plugin as departures
from rackticker import text_width

LA = ZoneInfo("America/Los_Angeles")


def row(destination, kind="SB", track="7B", when=datetime(2026, 9, 23, 21, 38, tzinfo=LA), delay=0):
    return {"time": when, "delay": delay, "kind": kind, "number": "310", "name": "", "destination": destination,
            "track": track, "moved": False, "cancelled": False}


class FitTests(unittest.TestCase):
    def test_a_name_is_never_cut_back_to_a_bare_prefix(self):
        """'San Bernardino' on a Metrolink board came out as just 'San'."""
        for name in ("San Bernardino", "Los Alamitos", "New Orleans", "Santa Barbara"):
            for width in (45, 50, 57):   # the narrowest a row gives: a 91/PV badge, a 2-digit track
                fitted = departures._fits(name, width, True, "metrolink")
                with self.subTest(name=name, width=width, fitted=fitted):
                    self.assertLessEqual(text_width(fitted, 1, True), width)
                    self.assertNotIn(fitted.lower(), departures.PREFIXES)

    def test_whole_words_still_win_when_they_say_something(self):
        self.assertEqual(departures._fits("Redlands - University", 57, True, "metrolink"), "Redlands")
        self.assertEqual(departures._fits("San Juan Capistrano", 57, True, "metrolink"), "San Juan")
        self.assertEqual(departures._fits("Los Angeles", 40, True, "metrolink"), "LA")

    def test_a_long_destination_rests_on_whole_letters_then_glides_to_its_last_word(self):
        resting, distance = departures._pan_stops("San Bernardino", 60, True)
        self.assertTrue("San Bernardino".startswith(resting))
        self.assertLessEqual(text_width(resting, 1, True), 60)
        self.assertEqual(distance, text_width("San ", 1, True) + 1)     # "Bernardino" at the column's edge
        self.assertLessEqual(text_width("San Bernardino", 1, True) - distance, 60)
        self.assertEqual(departures._pan(0, distance), 0)
        self.assertEqual(departures._pan(60, distance), distance)

    def test_the_board_shows_all_of_san_bernardino(self):
        """Every letter of the name is on the panel at some point during the page."""
        board = departures.Board()
        rows = [row("San Bernardino"), row("New Orleans", "SUNS", "12", datetime(2026, 9, 23, 22, 0, tzinfo=LA))]
        seen = set()
        for step in range(0, 7 * 30, 3):
            frame = Image.new("RGB", (128, 32))
            board._rows(frame, rows, departures.STYLES["metrolink"], "metrolink", step / 30, 0,
                        LA, board._time_column(rows, "metrolink", LA))
            seen.add(frame.crop((0, 1, 128, 10)).tobytes())
        self.assertGreater(len(seen), 2)     # it moved, and came to rest

    def test_time_column_fits_the_widest_time_on_the_board(self):
        rows = [row("A"), row("B", when=datetime(2026, 9, 23, 22, 0, tzinfo=LA))]
        self.assertEqual(departures.Board._time_column(rows, "metrolink", LA), text_width("10:00") + 4)
        self.assertEqual(departures.Board._time_column(rows[:1], "metrolink", LA), text_width("9:38") + 4)


if __name__ == "__main__":
    unittest.main()
