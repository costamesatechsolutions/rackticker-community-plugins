import importlib.util
import random
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("bar_trivia_plugin", Path(__file__).parents[1] / "plugin.py")
trivia = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trivia)


class BarTrivia(unittest.TestCase):
    def test_bundled_questions_all_fit(self):
        deck = trivia.bundled()
        self.assertGreaterEqual(len(deck), 30)
        for item in deck:
            self.assertTrue(trivia.fits(item), item["question"])
            self.assertEqual(len(set(item["choices"])), 4)

    def test_answer_index_points_at_the_right_choice(self):
        item = trivia.build_question("Sports", "How many holes are in a round of golf?", "18", ["9", "12", "21"],
                                     random.Random(1))
        self.assertEqual(item["choices"][item["answer"]], "18")

    def test_rejects_picture_questions_and_long_answers(self):
        rng = random.Random(1)
        self.assertIsNone(trivia.build_question("Film", "Which logo is shown?", "A", ["B", "C", "D"], rng))
        self.assertIsNone(trivia.build_question("Film", "Name it?", "A very long answer indeed here",
                                                ["B", "C", "D"], rng))

    def test_pages_never_end_on_an_orphan_line(self):
        pages = trivia.pages_of("Which Disney movie features the song Let It Go?")
        self.assertTrue(all(len(page) == 2 for page in pages[:-1]))
        self.assertGreater(len(pages[-1]), 0)


if __name__ == "__main__":
    unittest.main()


class PerFrameCost(unittest.TestCase):
    def test_available_and_render_stay_cheap_with_a_full_pool(self):
        import time
        from types import SimpleNamespace
        pool = trivia.bundled() * 3
        context = SimpleNamespace(snapshots={"bar_trivia": SimpleNamespace(data={"deck": pool})}, animation_time=7.0,
                                  scene=1, config={"display": {"fps": 30}, "plugins": {"bar_trivia": {
                                      "categories": trivia.DEFAULT_CATEGORIES, "questions_per_visit": 3,
                                      "think_seconds": 10}}})
        module = trivia.Trivia()
        module.render(context)
        start = time.perf_counter()
        for _ in range(200):
            self.assertTrue(module.available(context))
            module.render(context)
        self.assertLess((time.perf_counter() - start) / 200, 0.003)   # the Pi is ~6x slower than this
