from types import SimpleNamespace
from datetime import datetime, timezone
import unittest

import plugin as chess

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class NotationTests(unittest.TestCase):
    def play(self, before, after, move):
        return chess.notation(chess.board(before), chess.board(after), move)

    def test_moves(self):
        after = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        self.assertEqual(self.play(START, after, "e2e4"), "e4")
        self.assertEqual(self.play(START, "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1", "g1f3"), "Nf3")

    def test_capture_castle_promote(self):
        self.assertEqual(self.play("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1", "4k3/8/8/3P4/8/8/8/4K3 b - - 0 1", "e4d5"),
                         "exd5")
        self.assertEqual(self.play("4k3/8/8/8/8/8/8/4K2R w K - 0 1", "4k3/8/8/8/8/8/8/5RK1 b - - 1 1", "e1g1"), "O-O")
        self.assertEqual(self.play("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "Q3k3/8/8/8/8/8/8/4K3 b - - 0 1", "a7a8q"),
                         "a8=Q")


class FeedTests(unittest.TestCase):
    def test_events_build_the_state(self):
        feed = chess.Feed(SimpleNamespace(settings={"channel": "best"}))
        feed._event({"t": "featured", "d": {"id": "x", "orientation": "white", "fen": START, "players": [
            {"color": "white", "user": {"name": "a", "title": "GM"}, "rating": 3000, "seconds": 60},
            {"color": "black", "user": {"name": "b"}, "rating": 2900, "seconds": 60}]}})
        feed._event({"t": "fen", "d": {"fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
                                       "lm": "e2e4", "wc": 59, "bc": 60}})
        self.assertEqual(feed.state["san"], "e4")
        self.assertEqual(feed.state["clocks"], {"white": 59, "black": 60})
        module = chess.Chess()
        ts = feed.state["started"] + 10
        context = SimpleNamespace(now=datetime.fromtimestamp(ts, timezone.utc), animation_time=5, scene=1,
                                  config={"display": {"fps": 30}, "plugins": {"chess": {"channel": "best"}}},
                                  snapshots={"chess": SimpleNamespace(data=feed.state)})
        frame = module.render(context)
        self.assertIsNotNone(frame.getbbox())
        context.now = datetime.fromtimestamp(feed.state["started"] + 1, timezone.utc)
        self.assertNotEqual(module.render(context).tobytes(), frame.tobytes())   # the new-game card


if __name__ == "__main__":
    unittest.main()
