"""Blocks: the Bitcoin network building its chain, one block about every ten minutes.

The chain as a row of cubes, newest on the right next to the dashed one being
filled now, each with its age and how many transactions it holds; the latest
block, who mined it and what they were paid; how many transactions are waiting
and what it costs to jump the queue; and the countdown to the next halving.
Watching a public counter, nothing else: no prices, no wallets, no trading.

From mempool.space's free public API.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Provider, Snapshot, Storyboard, bounce, draw_text, draw_tiny, text_width,
                         tiny_width)

API = "https://mempool.space/api"
BLOCKS_EVERY, MEMPOOL_EVERY = 30, 60
HALVING_EVERY = 210000
WHITE, GREY, AMBER, GOLD, GREEN, CYAN = ((236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60),
                                         (90, 230, 120), (60, 200, 255))
ORANGE = (247, 147, 26)
CHAIN, LATEST, QUEUE, HALVING = 9.0, 7.0, 7.0, 6.0
NEW_BLOCK = 12.0


def parse_blocks(rows):
    blocks = []
    for row in rows:
        extras = row.get("extras") or {}
        blocks.append({"height": int(row["height"]), "time": float(row["timestamp"]),
                       "txs": int(row.get("tx_count") or 0), "fill": min(1.0, (row.get("weight") or 0) / 4e6),
                       "pool": ((extras.get("pool") or {}).get("name") or "Unknown"),
                       "reward": (extras.get("reward") or 0) / 1e8, "fees": (extras.get("totalFees") or 0) / 1e8})
    return sorted(blocks, key=lambda block: block["height"])


class Feed(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.data, self.asked, self.top = {}, {"blocks": -1e9, "mempool": -1e9}, None

    async def _json(self, path):
        async with self.session.get(API + path) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def fetch(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),
                                                 headers={"User-Agent": "RackTicker blocks plugin"})
        clock = time.monotonic()
        failures = []
        if clock - self.asked["blocks"] >= BLOCKS_EVERY:
            try:
                blocks = parse_blocks(await self._json("/v1/blocks"))
                if blocks:
                    newest = blocks[-1]["height"]
                    if self.top is not None and newest > self.top and self.context.settings["alert"]:
                        self.context.emit_event("blocks", NEW_BLOCK)
                    self.top = newest
                    self.data["blocks"] = blocks
                self.asked["blocks"] = clock
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError) as exc:
                failures.append(exc)
                self.asked["blocks"] = clock - BLOCKS_EVERY + 15
        if clock - self.asked["mempool"] >= MEMPOOL_EVERY:
            try:
                pool = await self._json("/mempool")
                fees = await self._json("/v1/fees/recommended")
                self.data["waiting"] = int(pool.get("count") or 0)
                self.data["vsize"] = float(pool.get("vsize") or 0)
                self.data["fee"] = fees.get("fastestFee")
                self.data["slow_fee"] = fees.get("hourFee")
                self.asked["mempool"] = clock
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError) as exc:
                failures.append(exc)
                self.asked["mempool"] = clock - MEMPOOL_EVERY + 20
        if failures and not self.data.get("blocks"):
            raise failures[0]
        return Snapshot(dict(self.data))

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# --- the screen ------------------------------------------------------------------------------

def ago(seconds):
    minutes = max(0, int(seconds // 60))
    return "NOW" if minutes < 1 else f"{minutes}M" if minutes < 60 else f"{minutes // 60}H"


def cube(draw, x, y, size, fill, color):
    """A block: a square face with a lit top and a shaded side, filled from the bottom by how full it is."""
    depth = 3
    top = tuple(min(255, round(c * 1.0)) for c in color)
    side = tuple(round(c * .45) for c in color)
    face = tuple(round(c * .7) for c in color)
    draw.polygon(((x, y + depth), (x + depth, y), (x + size + depth, y), (x + size, y + depth)), fill=top)
    draw.polygon(((x + size, y + depth), (x + size + depth, y), (x + size + depth, y + size),
                  (x + size, y + size + depth)), fill=side)
    draw.rectangle((x, y + depth, x + size, y + size + depth), fill=(40, 28, 10))
    level = round((size) * fill)
    if level:
        draw.rectangle((x, y + depth + size - level, x + size, y + size + depth), fill=face)


def thousands(count):
    return f"{count / 1000:.1f}K" if count >= 1000 else str(count)


class Blocks(Module):
    name = "blocks"
    event_priority = 15

    def __init__(self):
        self.story = Storyboard()

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _data(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data and snap.data.get("blocks") else None

    def available(self, context):
        return self._data(context) is not None

    def hold(self, context):
        return self.story.hold()

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        data = self._data(context)
        if data is None:
            draw_text(frame, "Joining the network", 0, 12, GREY, mixed=True)
            return frame
        ts = context.now.timestamp()
        newest = data["blocks"][-1]
        if ts - newest["time"] < NEW_BLOCK + 20 and context.animation_time < NEW_BLOCK:
            self._arrival(frame, data, ts, context.animation_time)
            return frame

        def build(visit):
            cards = [("chain", CHAIN), ("latest", LATEST)]
            if data.get("waiting") is not None:
                cards.append(("queue", QUEUE))
            return cards + [("halving", HALVING)]

        self.story.sync(context.animation_time, build, context.scene)
        card, local, _ = self.story.current(context.animation_time, build) or ("chain", 0, 0)
        getattr(self, "_" + card)(frame, data, ts, local)
        return frame

    @staticmethod
    def _chain(frame, data, ts, local):
        draw = ImageDraw.Draw(frame)
        blocks = data["blocks"][-6:]
        # The block being filled now: dashed, filling with the waiting transactions.
        x = 110
        for i in range(0, 14, 2):
            draw.point((x + i, 10), fill=GREY)
            draw.point((x + i, 23), fill=GREY)
            draw.point((x, 10 + i), fill=GREY)
            draw.point((x + 13, 10 + i), fill=GREY)
        draw_tiny(frame, "NEXT", 128 - tiny_width("NEXT"), 2, GREY)
        if data.get("fee") is not None:
            fee = f"{data['fee']}SAT"
            draw_tiny(frame, fee, 128 - tiny_width(fee), 26, GREY)
        for index, block in enumerate(reversed(blocks)):
            x = 92 - index * 16
            if x < -14:
                break
            color = ORANGE if index else GOLD
            cube(draw, x, 7, 12, block["fill"], color)
            label = ago(ts - block["time"])
            draw_tiny(frame, label, x + 7 - tiny_width(label) // 2, 0, WHITE if index == 0 else GREY)
            count = thousands(block["txs"])
            draw_tiny(frame, count, x + 7 - tiny_width(count) // 2, 26, GREY)

    @staticmethod
    def _latest(frame, data, ts, local):
        block = data["blocks"][-1]
        draw_tiny(frame, "LATEST BLOCK", 0, 0, GREY)
        age = ago(ts - block["time"])
        when = "JUST NOW" if age == "NOW" else f"{age} AGO"
        draw_tiny(frame, when, 128 - tiny_width(when), 0, GREY)
        height = f"{block['height']:,}"
        draw_text(frame, height, 0, 7, GOLD, scale=2, smooth=True)
        reward = f"{block['reward']:.2f} BTC"
        if text_width(height, 2) + tiny_width(reward) + 4 <= 128:
            draw_tiny(frame, reward, 128 - tiny_width(reward), 9, WHITE)
            draw_tiny(frame, "PAID", 128 - tiny_width("PAID"), 15, GREY)
        pool = f"BY {block['pool'].upper()}"
        draw_tiny(frame, pool, 0, 25, CYAN)
        txs = f"{block['txs']:,} TXS"
        if tiny_width(pool) + tiny_width(txs) + 6 <= 128:
            draw_tiny(frame, txs, 128 - tiny_width(txs), 25, WHITE)

    @staticmethod
    def _queue(frame, data, ts, local):
        draw_tiny(frame, "WAITING TO GET IN", 0, 0, GREY)
        waiting = f"{data['waiting']:,}"
        draw_text(frame, waiting, 0, 7, WHITE, scale=2, smooth=True)
        draw_tiny(frame, "TXS", text_width(waiting, 2) + 3, 15, GREY)
        worth = math.ceil(data["vsize"] / 1e6)
        draw_tiny(frame, f"ABOUT {worth} BLOCKS' WORTH", 0, 24, GREY)
        if data.get("fee") is not None:
            fee = f"{data['fee']} SAT/VB"
            draw_tiny(frame, "NEXT BLOCK", 128 - tiny_width("NEXT BLOCK"), 7, GREY)
            draw_tiny(frame, fee, 128 - tiny_width(fee), 14, AMBER)

    @staticmethod
    def _halving(frame, data, ts, local):
        height = data["blocks"][-1]["height"]
        nxt = (height // HALVING_EVERY + 1) * HALVING_EVERY
        left = nxt - height
        when = datetime.fromtimestamp(ts + left * 600, timezone.utc)
        draw_tiny(frame, "NEXT HALVING", 0, 0, GOLD)
        draw_tiny(frame, f"BLOCK {nxt:,}", 128 - tiny_width(f"BLOCK {nxt:,}"), 0, GREY)
        count = f"{left:,}"
        draw_text(frame, count, 0, 7, WHITE, scale=2, smooth=True)
        draw_tiny(frame, "BLOCKS TO GO", text_width(count, 2) + 3, 15, GREY)
        estimate = f"ABOUT {when.strftime('%b %Y').upper()}"
        draw_tiny(frame, estimate, 0, 25, AMBER)
        done = 1 - left / HALVING_EVERY
        draw = ImageDraw.Draw(frame)
        draw.rectangle((70, 26, 127, 29), outline=(80, 80, 90))
        draw.rectangle((71, 27, 71 + round(55 * done * min(1.0, local / 1.5)), 28), fill=GOLD)

    @staticmethod
    def _arrival(frame, data, ts, t):
        """A new block: it drops onto the chain and the screen says who found it."""
        block = data["blocks"][-1]
        draw = ImageDraw.Draw(frame)
        fall = bounce(min(1.0, t / 1.2))
        y = round(-16 + fall * 23)
        cube(draw, 4, y, 16, block["fill"], GOLD)
        draw_tiny(frame, "NEW BLOCK", 30, 1, GOLD if int(t * 3) % 2 or t > 3 else WHITE)
        draw_text(frame, f"{block['height']:,}", 30, 8, WHITE, scale=1)
        draw_tiny(frame, f"BY {block['pool'].upper()}", 30, 18, CYAN)
        draw_tiny(frame, f"{block['txs']:,} TRANSACTIONS", 30, 25, GREY)


plugin = Plugin(
    "blocks", "Blocks", module=Blocks, provider=Feed,
    defaults={"alert": False},
    help={"alert": "Take over the display briefly for every new block (one about every ten minutes)"},
    ui={"alert": {"label": "Show every new block as it lands"}},
)
