"""Tests for the plugins that moved here from RackTicker: F1, prediction markets,
the LED sign and the arcade. They need a RackTicker checkout beside this repository
(`PYTHONPATH=../rackticker`) and skip without one."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import unittest

try:
    from app.core.config import validate_config
    from app.core.models import Snapshot, Message, SystemStatus
    from app.core.plugins import PluginRegistry
    from app.modules.base import RenderContext
    from app.core.renderer import validate_frame
except ImportError:                     # no RackTicker beside us
    validate_config = None

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"


def load(name, plugin):
    spec = importlib.util.spec_from_file_location(name, PLUGINS / plugin / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if validate_config is not None:
    F1 = load("f1_test", "f1")
    MARKETS = load("markets_test", "markets")
    WALL = load("wall_test", "ticker_wall")
    ARCADE = load("arcade_test", "arcade")


@unittest.skipIf(validate_config is None, "clone RackTicker beside this repository to run these")
class MovedPluginTests(unittest.TestCase):
    def test_f1_normalizes_and_renders_next_race(self):
        payload = {"MRData": {"RaceTable": {"Races": [{
            "round": "17", "raceName": "Azerbaijan Grand Prix",
            "date": "2026-09-26", "time": "11:00:00Z",
            "Circuit": {"circuitName": "Baku City Circuit"},
        }]}}}
        row = F1.normalize(payload, "America/Los_Angeles")
        self.assertEqual(row["race"], "AZERBAIJAN GP")
        self.assertIn("BAKU", row["circuit"])
        registry = PluginRegistry()
        registry.register(F1.plugin)
        config = validate_config({"plugins": {"f1": {}}, "modules": {"f1": {"enabled": True}},
                                  "playlist": [{"id": "f1", "module": "f1"}]}, registry)
        context = RenderContext(datetime.now(timezone.utc), 5, config,
                                {"f1": Snapshot(row)}, Message("X", "X"), SystemStatus())
        self.assertIsNotNone(validate_frame(F1.F1Module().render(context)).getbbox())

    def test_market_parsers_accept_public_api_formats(self):
        poly = MARKETS.polymarket_events([{"title": "Will it rain?", "volume24hr": "1200", "markets": [{
            "question": "Will it rain?", "outcomes": '["No", "Yes"]',
            "outcomePrices": '["0.38", "0.62"]', "oneDayPriceChange": 0.05}]}])
        kalshi = MARKETS.kalshi_events({"events": [{"title": "Will the Padres win?", "markets": [
            {"yes_sub_title": "Padres", "yes_bid": 41, "yes_ask": 45, "volume_24h": 800}]}]})
        self.assertTrue(poly[0]["binary"])
        self.assertEqual(round(poly[0]["outcomes"][0]["probability"]), 62)
        self.assertEqual(round(poly[0]["outcomes"][0]["change"]), 5)
        self.assertEqual(round(kalshi[0]["outcomes"][0]["probability"]), 43)
        self.assertEqual(kalshi[0]["source"], "KALSHI")

    def test_ticker_wall_modes_render_without_full_frame_fill(self):
        registry = PluginRegistry()
        registry.register(WALL.plugin)
        config = validate_config({"plugins": {"ticker_wall": {}},
                                  "modules": {"ticker_wall": {"enabled": True}},
                                  "playlist": [{"id": "wall", "module": "ticker_wall"}]}, registry)
        for elapsed in (1, 9, 17):
            wall = WALL.TickerWall()
            # A phrase's first instant can be dark while its letters fly in; the
            # sign must be lit a moment later and never flood the whole panel.
            frames = [validate_frame(wall.render(RenderContext(datetime.now(timezone.utc), moment, config, {},
                                                               Message("X", "X"), SystemStatus())))
                      for moment in (elapsed, elapsed + .4)]
            self.assertTrue(any(frame.getbbox() for frame in frames))
            for frame in frames:
                self.assertLess(sum(pixel != (0, 0, 0) for pixel in frame.get_flattened_data()), 3000)

    def test_new_plugin_settings_are_strict(self):
        with self.assertRaises(ValueError):
            F1.validate({"timezone": "bad/zone", "refresh_seconds": 900})
        with self.assertRaises(ValueError):
            MARKETS.validate({"refresh_seconds": 1, "cycle_seconds": 8})
        with self.assertRaises(ValueError):
            WALL.validate({"mode": "blink", "scene_seconds": 8,
                           "arena_items": "A", "times_square_items": "B", "taqueria_items": "C"})

    def test_all_arcade_games_simulate_canonical_frames(self):
        registry = PluginRegistry(); registry.register(ARCADE.plugin)
        for mode in ARCADE.GAMES:
            config = validate_config({"plugins": {"arcade": {"mode": mode}},
                                      "modules": {"arcade": {"enabled": True}},
                                      "playlist": [{"id": "arcade", "module": "arcade"}]}, registry)
            module, frames = ARCADE.Arcade(), set()
            for step in range(8 * 30):
                context = RenderContext(datetime.now(timezone.utc), step / 30, config, {},
                                        Message(), SystemStatus())
                frame = validate_frame(module.render(context))
                if step >= 5 * 30:
                    frames.add(frame.tobytes())
            self.assertGreater(len(frames), 5, mode)

    def test_pixel_quest_hero_never_gets_stuck(self):
        """A platform ending one column before a step left no headroom to jump it."""
        import random
        for seed in range(40):
            game = ARCADE.Platformer(random.Random(seed))
            best, still = game.x, 0.0
            for _ in range(30 * 90):
                world = game.world
                game.update(1 / 30)
                if game.dead or game.cleared or game.world != world or abs(game.x - best) > 1:
                    best, still = game.x, 0.0
                else:
                    still += 1 / 30
                self.assertLess(still, 4, f"seed {seed}: hero stuck at x={game.x:.1f}")

    def test_retired_arcade_scene_settings_migrate(self):
        registry = PluginRegistry(); registry.register(ARCADE.plugin)
        config = validate_config({"plugins": {"arcade": {"mode": "runner", "scene_seconds": 12}}}, registry)
        self.assertEqual(config["plugins"]["arcade"]["mode"], "auto")


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(validate_config is None, "clone RackTicker beside this repository to run these")
class LinkCardTests(unittest.TestCase):
    def test_a_detail_line_fills_fields_and_abbreviates_big_numbers(self):
        links = load("links_test", "url_data")
        reply = {"bitcoin": {"usd": 80533, "usd_market_cap": 1617671147604.7, "usd_24h_vol": 24312879325.7,
                             "usd_24h_change": -0.867}}
        self.assertEqual(links.detail_line("MCAP {bitcoin.usd_market_cap:short}  VOL {bitcoin.usd_24h_vol:short}", reply),
                         "MCAP 1.6T  VOL 24.3B")
        self.assertEqual(links.detail_line("24H {bitcoin.usd_24h_change:+.1f}%", reply), "24H -0.9%")
        self.assertEqual(links.detail_line("X {bitcoin.nothing}", reply), "X --")
        self.assertEqual(links.number("81,280.50"), 81280.5)
        self.assertIsNone(links.number(True))
