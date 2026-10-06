"""Bar trivia: the question board over the bar.

A question pages in two lines at a time, the four answers light up with a
countdown bar, then the right one is revealed. Questions come from two free,
key-less sources (Open Trivia DB and The Trivia API); a small built-in set keeps
the screen going when the network is down. Nobody has to play along.
"""
from __future__ import annotations

import hashlib
import html
import json
import random
import time
from collections import deque
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

import aiohttp
from PIL import Image

from rackticker import (AMBER, EFFECTS, GREEN, RED, WHITE, Lettering, Module, Plugin, Provider,
                        Snapshot, Storyboard, bulb_border, draw_text, draw_tiny, ease_out, mix, new_frame,
                        text_width, tiny_width, wrap_text)

OPENTDB = "https://opentdb.com/api.php"
OPENTDB_TOKEN = "https://opentdb.com/api_token.php"
TRIVIA_API = "https://the-trivia-api.com/v2/questions"

# label -> (Open Trivia DB category ids, The Trivia API slug, short label on the panel, colour)
CATEGORIES = {
    "Sports": ([21], "sport_and_leisure", "SPORTS", (255, 150, 0)),
    "Film": ([11], "film_and_tv", "FILM", (60, 150, 255)),
    "Television": ([14], "film_and_tv", "TV", (60, 150, 255)),
    "Music": ([12], "music", "MUSIC", (40, 210, 90)),
    "General knowledge": ([9], "general_knowledge", "GENERAL", (255, 210, 0)),
    "Geography": ([22], "geography", "GEOGRAPHY", (0, 200, 200)),
    "History": ([23], "history", "HISTORY", (230, 120, 40)),
    "Video games": ([15], None, "GAMES", (150, 110, 255)),
    "Food & drink": ([], "food_and_drink", "FOOD & DRINK", (255, 90, 40)),
    "Science": ([17], "science", "SCIENCE", (40, 210, 90)),
    "Celebrities": ([26], None, "CELEBS", (255, 210, 0)),
    "Animals": ([27], None, "ANIMALS", (40, 210, 90)),
    "Art & books": ([25, 10], "arts_and_literature", "ARTS", (150, 110, 255)),
}
DEFAULT_CATEGORIES = ("Sports,Film,Television,Music,General knowledge,Geography,History,"
                      "Video games,Food & drink,Science")
# What the built-in questions call themselves, when it differs from the setting's label.
SHORT_TO_LABEL = {"Science & nature": "Science"}

ROOM = 108            # pixels an answer may use: 128 minus its letter, the margins and the timer column
MAX_QUESTION = 200    # characters; four pages of two lines is already twelve seconds of reading
POOL = 90
LETTERS = "ABCD"
MAX_PAGES = 3
REVEAL = 5.0
LINES, LINE_HEIGHT, PAGE_HEIGHT = 3, 10, 29   # three lines of 5x7 lowercase fill the panel
TEXT_X, TEXT_WIDTH = 5, 120                   # the category stripe takes the first two columns
SLIDE = 0.28
SPLASH_SPEED = 1.8   # the lettering's own timeline runs long; a splash should be a moment
BAD_WORDS = ("picture", "pictured", "image", "photo", "shown", "pictured", "logo", "video", "listen", "audio")


def clean(text):
    text = " ".join(html.unescape(str(text)).split())
    return text if text and all(ord(c) < 0x250 for c in text) else None


def build_question(category, question, correct, wrong, rng):
    """One question dict, or None when it would not read well on the panel."""
    question, correct = clean(question), clean(correct)
    wrong = [clean(w) for w in wrong]
    if not question or not correct or any(w is None for w in wrong):
        return None
    choices = list(dict.fromkeys([correct, *wrong]))
    if len(choices) != 4 or len(question) > MAX_QUESTION:
        return None
    lowered = question.lower()
    if any(f" {word} " in f" {lowered.replace('?', ' ').replace(',', ' ')} " for word in BAD_WORDS):
        return None
    rng.shuffle(choices)
    item = {"id": hashlib.sha1(question.encode()).hexdigest()[:12], "category": category,
            "question": question, "choices": choices, "answer": choices.index(correct)}
    return item if fits(item) else None


def fits(item):
    """Every answer on one line beside its letter, so nothing is ever cut off."""
    return (all(text_width(choice) <= ROOM for choice in item["choices"])
            and len(question_lines(item["question"])) <= 3 * MAX_PAGES)


def label_of(name):
    name = SHORT_TO_LABEL.get(name, name)
    return name if name in CATEGORIES else "General knowledge"


def bundled():
    rng = random.Random()
    try:
        raw = json.loads((Path(__file__).parent / "questions.json").read_text())
    except (OSError, ValueError):
        return []
    items = (build_question(label_of(row["category"]), row["question"], row["correct"], row["wrong"], rng)
             for row in raw)
    return [item for item in items if item]


def selected(settings):
    wanted = [name.strip() for name in str(settings["categories"]).split(",")]
    return [name for name in CATEGORIES if name in wanted] or list(CATEGORIES)


class Feed(Provider):
    """Keeps a rolling pool of fresh questions; one request per ask, politely spaced."""

    def __init__(self, context):
        self.context = context
        self.session = None
        self.pool = bundled()
        self.known = {item["id"] for item in self.pool}
        self.token = None
        self.cursor = 0
        self.turn = 0
        self.next_ask = 0.0
        self.live = 0

    async def fetch(self):
        if time.monotonic() >= self.next_ask:
            try:
                await self._ask()
            except Exception:   # any bad reply or network hiccup: keep the pool, try again later
                self.next_ask = time.monotonic() + 45
        return Snapshot({"deck": list(self.pool)})

    async def _ask(self):
        settings = self.context.settings
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        source = settings["source"]
        self.turn += 1
        use_api = source == "The Trivia API" or (source == "both" and self.turn % 2 == 0)
        names = [n for n in selected(settings) if CATEGORIES[n][1 if use_api else 0]]
        if not names:
            use_api, names = not use_api, [n for n in selected(settings) if CATEGORIES[n][0 if use_api else 1]]
        fresh = await (self._trivia_api(names, settings) if use_api else self._opentdb(names, settings))
        added = 0
        for item in fresh:
            if item["id"] not in self.known:
                self.known.add(item["id"])
                self.pool.append(item)
                added += 1
        self.live += added
        if len(self.pool) > POOL:
            del self.pool[:len(self.pool) - POOL]
        if len(self.known) > 2000:
            self.known = {item["id"] for item in self.pool}
        # Quick while the pool is still mostly built-in, then a calm top-up: the board only
        # needs new questions as fast as people watch them.
        self.next_ask = time.monotonic() + (7 if self.live < 40 else 90)

    async def _opentdb(self, names, settings):
        if self.token is None:
            async with self.session.get(OPENTDB_TOKEN, params={"command": "request"}) as response:
                self.token = (await response.json(content_type=None)).get("token")
            self.next_ask = time.monotonic() + 6   # the token request counts toward the 1 per 5 s limit
            return []
        self.cursor += 1
        name = names[self.cursor % len(names)]
        ids = CATEGORIES[name][0]
        params = {"amount": 10, "type": "multiple", "encode": "url3986", "category": ids[self.cursor // len(names) % len(ids)]}
        if self.token:
            params["token"] = self.token
        if settings["difficulty"] != "any":
            params["difficulty"] = settings["difficulty"]
        async with self.session.get(OPENTDB, params=params) as response:
            payload = await response.json(content_type=None)
        code = payload.get("response_code")
        if code in (3, 4):      # token unknown, or every question in that category has been served
            self.token = None
            return []
        if code != 0:
            raise ValueError(f"Open Trivia DB said {code}")
        rng = random.Random()
        out = []
        for row in payload["results"]:
            item = build_question(name, unquote(row["question"]), unquote(row["correct_answer"]),
                                  [unquote(w) for w in row["incorrect_answers"]], rng)
            if item:
                out.append(item)
        return out

    async def _trivia_api(self, names, settings):
        slugs = sorted({CATEGORIES[n][1] for n in names})
        by_slug = {CATEGORIES[n][1]: n for n in reversed(names)}
        params = {"limit": 20, "categories": ",".join(slugs)}
        if settings["difficulty"] != "any":
            params["difficulties"] = settings["difficulty"]
        async with self.session.get(TRIVIA_API, params=params) as response:
            response.raise_for_status()
            rows = await response.json(content_type=None)
        rng = random.Random()
        out = []
        for row in rows:
            item = build_question(by_slug.get(row.get("category"), "General knowledge"), row["question"]["text"],
                                  row["correctAnswer"], row["incorrectAnswers"], rng)
            if item:
                out.append(item)
        return out

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


def question_lines(text):
    """Whole-word lines that fit beside the category stripe, re-wrapped narrower when
    the last page would otherwise hold a lone line."""
    lines = wrap_text(text, TEXT_WIDTH, 1, True)
    if len(lines) > 3 and len(lines) % 3 == 1:
        for width in range(TEXT_WIDTH - 4, 70, -4):
            narrower = wrap_text(text, width, 1, True)
            if len(narrower) % 3 != 1 and len(narrower) <= len(lines) + 2:
                return narrower
    return lines


@lru_cache(maxsize=64)
def pages_of(text):
    lines = question_lines(text)
    return tuple(tuple(lines[i:i + LINES]) for i in range(0, len(lines), LINES))


def page_seconds(lines):
    return 1.8 + 0.34 * sum(len(line.split()) for line in lines)


@lru_cache(maxsize=96)
def page_image(lines, category):
    """One page of the question, with its category in the corner when there is room."""
    cell = Image.new("RGB", (128, PAGE_HEIGHT))
    for index, line in enumerate(lines):
        draw_text(cell, line, TEXT_X, index * LINE_HEIGHT, WHITE, mixed=True)
    if len(lines) < LINES:
        _, _, short, color = CATEGORIES[category]
        draw_tiny(cell, short, TEXT_X, PAGE_HEIGHT - 5, color)
    return cell


def question_seconds(item, think, intro):
    return intro + sum(page_seconds(page) for page in pages_of(item["question"])) + think + REVEAL


class Trivia(Module):
    name = "bar_trivia"

    def __init__(self):
        self.board = Storyboard(resume=False)
        self.shown = deque(maxlen=400)
        self.last_category = None

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _deck(self, context):
        snap = context.snapshots.get(self.name)
        # The provider only pools questions that fit; measuring them again here, every frame, stalled a Pi.
        return snap.data["deck"] if snap and snap.data else []

    def available(self, context):
        return bool(self._deck(context))

    def _build(self, context):
        settings = context.config["plugins"][self.name]

        def build(_visit):
            deck = self._deck(context)
            if not deck:
                return []
            wanted = set(selected(settings))
            deck = [item for item in deck if item["category"] in wanted] or deck
            unseen = [item for item in deck if item["id"] not in self.shown] or deck
            picks = []
            for _ in range(min(int(settings["questions_per_visit"]), len(unseen))):
                pool = [item for item in unseen if item not in picks]
                varied = [item for item in pool if item["category"] != self.last_category] or pool
                picks.append(random.choice(varied))
                self.last_category = picks[-1]["category"]
            self.shown.extend(item["id"] for item in picks)
            rng = random.Random()
            splash = Lettering("TRIVIA", rng.choice(EFFECTS), ((255, 178, 89), (90, 200, 255)), "alternate",
                               rng.randrange(1 << 30))
            items = []
            for number, item in enumerate(picks):
                intro = splash.duration / SPLASH_SPEED if number == 0 else 0
                items.append(({"q": item, "number": number + 1, "count": len(picks), "intro": intro,
                               "splash": splash, "think": float(settings["think_seconds"])},
                              question_seconds(item, float(settings["think_seconds"]), intro)))
            return items
        return build

    def _current(self, context):
        build = self._build(context)
        self.board.sync(context.animation_time, build, context.scene)
        return self.board.current(context.animation_time, build)

    def hold(self, context):
        return bool(self._current(context)) and self.board.hold()

    def render(self, context):
        frame = new_frame()
        current = self._current(context)
        if not current:
            return frame
        step, local, _ = current
        item, think, intro = step["q"], step["think"], step["intro"]
        pages = pages_of(item["question"])
        reading = sum(page_seconds(page) for page in pages)
        if local < intro:
            step["splash"].draw(frame, local * SPLASH_SPEED)
            bulb_border(frame, context.animation_time, (AMBER, WHITE))
            return frame
        local -= intro
        if local < reading:
            self._question(frame, step, pages, local)
        elif local < reading + think:
            self._choices(frame, item, local - reading, think)
        else:
            self._reveal(frame, item, local - reading - think, context.animation_time)
        return frame

    @staticmethod
    def _question(frame, step, pages, local):
        category = step["q"]["category"]
        start, index = 0.0, 0
        for index, page in enumerate(pages):
            if local < start + page_seconds(page):
                break
            start += page_seconds(page)
        into = local - start
        image = page_image(pages[index], category)
        if into >= SLIDE:
            frame.paste(image, (0, 1))
        else:
            # Each page rolls up from below as the last one rolls away.
            shift = round(PAGE_HEIGHT * ease_out(into / SLIDE))
            if index:
                frame.paste(page_image(pages[index - 1], category), (0, 1 - shift))
            frame.paste(image, (0, 1 + PAGE_HEIGHT - shift))
        frame.paste(CATEGORIES[category][3], (0, 0, 2, 32))

    @staticmethod
    def _choices(frame, item, local, think):
        for index, choice in enumerate(item["choices"]):
            if local < index * .18:
                continue
            y = index * 8
            draw_text(frame, LETTERS[index], 2, y, AMBER)
            draw_text(frame, choice, 12, y, WHITE)
        # A column down the right edge that drains toward the bottom: it cannot be mistaken
        # for an underline on the last answer, and it moves a row at a time.
        left = max(0.0, 1 - local / think)
        color = mix(RED, GREEN, min(1.0, left * 2.2)) if left < .45 else GREEN
        height = round(32 * left)
        if height:
            frame.paste(color, (124, 32 - height, 128, 32))

    @staticmethod
    def _reveal(frame, item, local, t):
        bulb_border(frame, t, (GREEN, WHITE))
        draw_tiny(frame, "THE ANSWER", (128 - tiny_width("THE ANSWER")) // 2, 4, GREEN)
        answer = item["choices"][item["answer"]]
        letter = LETTERS[item["answer"]]
        color = mix((0, 0, 0), WHITE, ease_out(local / .4))
        gold = mix((0, 0, 0), AMBER, ease_out(local / .4))
        gap = 9
        if text_width(answer, 2, True) + 5 + gap <= 120:
            x = (128 - (5 + gap + text_width(answer, 2, True))) // 2
            draw_text(frame, letter, x, 16, gold)
            draw_text(frame, answer, x + 5 + gap, 12, color, 2, True, True)
            return
        lines = wrap_text(answer, 100, 1, True)[:2]
        top = 12 if len(lines) == 1 else 10
        draw_text(frame, letter, 8, 14, gold)
        for number, line in enumerate(lines):
            draw_text(frame, line, 8 + 5 + gap, top + number * 9, color, mixed=True)


def validate(settings):
    if not 1 <= settings["questions_per_visit"] <= 10:
        raise ValueError("questions per visit must be 1-10")
    if not 4 <= settings["think_seconds"] <= 30:
        raise ValueError("think time must be 4-30 seconds")


plugin = Plugin(
    "bar_trivia", "Bar trivia", module=Trivia, provider=Feed,
    defaults={"categories": DEFAULT_CATEGORIES, "difficulty": "any", "questions_per_visit": 3,
              "think_seconds": 10, "source": "both"},
    choices={"difficulty": ("any", "easy", "medium", "hard"), "source": ("both", "Open Trivia DB", "The Trivia API")},
    help={"categories": "Which kinds of question to ask",
          "think_seconds": "How long the four answers stay up before the reveal",
          "source": "Open Trivia DB (CC BY-SA) and The Trivia API (free for non-commercial use) need no key"},
    ui={"categories": {"type": "multi", "options": list(CATEGORIES), "label": "Categories"},
        "questions_per_visit": {"type": "slider", "min": 1, "max": 10, "step": 1, "label": "Questions per visit"},
        "think_seconds": {"type": "slider", "min": 4, "max": 30, "step": 1, "unit": "s", "label": "Time to answer"},
        "source": {"advanced": True}},
    validate_settings=validate,
)
