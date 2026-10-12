"""Wiki pulse: the world editing Wikipedia, live.

A heartbeat line where every edit to an article is a blip (up for words added,
down for words cut), how many edits a minute, and the article just touched;
then the articles being edited most in the last hour, which is where the news
shows up first; then the brand-new articles.

From Wikipedia's public recent-changes list, asked every ten seconds.
"""
from __future__ import annotations

from collections import Counter, deque
from datetime import datetime
import json
import math
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, draw_text, draw_tiny, offload, text_width,
                         tiny_width)

ASK_EVERY = 10
KEEP = 3600                # an hour of edits for "most edited"
DELAY = 30                 # the pulse plays the edits half a minute behind, so it never runs dry between asks
WHITE, GREY, AMBER, GOLD, RED, GREEN, CYAN = ((236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60),
                                              (255, 60, 40), (90, 230, 120), (60, 200, 255))
LANGUAGES = ("en", "de", "fr", "es", "it", "ja", "pt", "ru", "zh", "nl", "pl", "sv")
PULSE, HOT, NEW = 12.0, 9.0, 7.0
NAME_REST, NAME_SPEED = 1.2, 20


def parse(raw, include_bots):
    """[(id, time, title, bytes changed, is new)] from the API's reply (in a helper process)."""
    payload = json.loads(raw)
    rows = []
    for change in (payload.get("query") or {}).get("recentchanges") or []:
        if change.get("bot") and not include_bots:
            continue
        try:
            at = datetime.fromisoformat(change["timestamp"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            continue
        rows.append((int(change.get("rcid", 0)), at, str(change.get("title", "")),
                     int(change.get("newlen") or 0) - int(change.get("oldlen") or 0), change.get("type") == "new"))
    return rows


class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.edits, self.seen, self.asked, self.key = deque(), set(), -1e9, None

    async def fetch(self):
        settings = self.context.settings
        key = (settings["language"], settings["include_bots"])
        if key != self.key:
            self.edits.clear()
            self.seen.clear()
            self.key = key
        if time.monotonic() - self.asked >= ASK_EVERY:
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5),
                    headers={"User-Agent": "RackTicker/1.0 (https://github.com/costamesatechsolutions/rackticker)"})
            params = {"action": "query", "list": "recentchanges", "rcprop": "title|timestamp|sizes|flags|ids",
                      "rclimit": "250", "rctype": "edit|new", "rcnamespace": "0", "format": "json",
                      "formatversion": "2"}
            try:
                async with self.session.get(f"https://{settings['language']}.wikipedia.org/w/api.php",
                                            params=params) as response:
                    response.raise_for_status()
                    rows = await offload(parse, await response.read(), settings["include_bots"])
                for row in sorted(rows, key=lambda row: row[1]):
                    if row[0] not in self.seen:
                        self.seen.add(row[0])
                        self.edits.append(row)
                self.asked = time.monotonic()
            except (aiohttp.ClientError, TimeoutError, ValueError):
                self.asked = time.monotonic() - ASK_EVERY + 20
                if not self.edits:
                    raise
        cutoff = time.time() - KEEP
        while self.edits and self.edits[0][1] < cutoff:
            self.seen.discard(self.edits.popleft()[0])
        edits = list(self.edits)
        hot = Counter(title for _, _, title, _, _ in edits).most_common(6)
        fresh = [title for _, _, title, _, new in reversed(edits) if new][:6]
        recent = [edit for edit in edits if edit[1] >= time.time() - 240]
        return Snapshot({"recent": recent, "hot": hot, "new": fresh, "language": settings["language"],
                         "span": min(KEEP, time.time() - edits[0][1]) if edits else 0, "count": len(edits)})

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


def _glide(local, distance):
    if distance <= 0:
        return 0
    glide = distance / NAME_SPEED
    phase = local % (2 * (NAME_REST + glide))
    if phase < NAME_REST:
        return 0
    if phase < NAME_REST + glide:
        return round((phase - NAME_REST) * NAME_SPEED)
    if phase < 2 * NAME_REST + glide:
        return distance
    return round(distance - (phase - 2 * NAME_REST - glide) * NAME_SPEED)


def fitted(frame, text, x, y, room, color, local):
    """A title in `room` pixels: whole if it fits, otherwise resting on whole letters, then gliding to its end."""
    if text_width(text, 1, True) <= room:
        draw_text(frame, text, x, y, color, mixed=True)
        return
    full = text_width(text, 1, True)
    stops = [text_width(text[:i], 1, True) + 1 for i in range(1, len(text))]
    distance = min([s for s in stops if full - s <= room] or [full - room])
    resting = text
    while resting and text_width(resting, 1, True) > room:
        resting = resting[:-1]
    shift = _glide(local, distance)
    cell = Image.new("RGB", (room, 9))
    draw_text(cell, resting.rstrip() if shift == 0 else text, -shift, 0, color, mixed=True)
    frame.paste(cell, (x, y))


class WikiPulse(Module):
    name = "wiki_pulse"

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _data(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data and snap.data.get("recent") else None

    def available(self, context):
        return self._data(context) is not None

    def hold(self, context):
        return self.story.hold()

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        data = self._data(context)
        if data is None:
            draw_text(frame, "Listening", 4, 12, GREY, mixed=True)
            return frame

        def build(visit):
            cards = [("pulse", PULSE)]
            if data["hot"] and data["hot"][0][1] > 1:
                cards.append(("hot", HOT))
            if data["new"]:
                cards.append(("new", NEW))
            return cards

        self.story.sync(context.animation_time, build, context.scene)
        card, local, _ = self.story.current(context.animation_time, build) or ("pulse", 0, 0)
        getattr(self, "_" + card)(frame, data, context.now.timestamp(), local)
        return frame

    @staticmethod
    def _pulse(frame, data, ts, local):
        """The last minute as a heartbeat, played half a minute behind real time."""
        now = ts - DELAY
        draw = ImageDraw.Draw(frame)
        base = 14
        draw.line((0, base, 127, base), fill=(0, 70, 30))
        latest = None
        per_minute = sum(1 for edit in data["recent"] if now - 60 <= edit[1] <= now)
        for _, at, title, change, new in data["recent"]:
            age = now - at
            if age < 0 or age > 64:
                continue
            x = 127 - round(age * 2)
            height = min(7, 1 + round(math.log10(abs(change) + 1) * 2))
            color = GOLD if new else GREEN if change >= 0 else RED
            top = base - height if change >= 0 else base + 1
            bottom = base - 1 if change >= 0 else base + height
            if age < 1.2:
                color = WHITE
            draw.line((x, top, x, bottom), fill=color)
            if latest is None or at > latest[1]:
                latest = (title, at, change, new)
        label = f"{data['language'].upper()} WIKIPEDIA LIVE"
        draw_tiny(frame, label, 0, 0, GREY)
        rate = f"{per_minute} EDITS/MIN"
        draw_tiny(frame, rate, 128 - tiny_width(rate), 0, AMBER)
        if latest:
            title, at, change, new = latest
            sign = f"+{change}" if change >= 0 else str(change)
            tag = "NEW" if new else sign
            fitted(frame, title, 0, 23, 127 - tiny_width(tag) - 3, WHITE, local)
            draw_tiny(frame, tag, 128 - tiny_width(tag), 25, GOLD if new else GREEN if change >= 0 else RED)

    @staticmethod
    def _hot(frame, data, ts, local):
        span = round(data["span"] / 60)
        head = "MOST EDITED, LAST HOUR" if span >= 55 else f"MOST EDITED, LAST {max(1, span)} MIN"
        draw_tiny(frame, head, 0, 0, GOLD)
        page = int(local / (HOT / 2)) % 2
        rows = data["hot"][page * 2:page * 2 + 2] or data["hot"][:2]
        for index, (title, count) in enumerate(rows):
            y = 8 + index * 12
            label = f"{count}×"
            draw_tiny(frame, label, 128 - tiny_width(label), y + 1, AMBER)
            fitted(frame, title, 0, y, 127 - tiny_width(label) - 3, WHITE, local % (HOT / 2))

    @staticmethod
    def _new(frame, data, ts, local):
        draw_tiny(frame, "BRAND-NEW ARTICLES", 0, 0, GOLD)
        page = int(local / (NEW / 2)) % 2
        rows = data["new"][page * 2:page * 2 + 2] or data["new"][:2]
        for index, title in enumerate(rows):
            fitted(frame, title, 0, 8 + index * 12, 128, CYAN, local % (NEW / 2))


def validate_settings(settings):
    if settings.get("language") not in LANGUAGES:
        raise ValueError(f"language must be one of {', '.join(LANGUAGES)}")
    return settings


plugin = Plugin(
    "wiki_pulse", "Wiki pulse", module=WikiPulse, provider=Feed,
    defaults={"language": "en", "include_bots": False}, choices={"language": LANGUAGES},
    validate_settings=validate_settings,
    help={"language": "Which Wikipedia: en, de, fr, es, ja…",
          "include_bots": "Count the robots that tidy articles too (many more, mostly tiny edits)"},
)
