"""Chess: a live game between strong players, move by move, from Lichess TV.

The board on the left with the last move lit, the players with their titles,
ratings and running clocks on the right, and the move just played in big
letters. When the game ends Lichess features the next one, and the screen
introduces the new players.

From the free, open Lichess TV feed (no account, no key).
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
import json
import time

import aiohttp
from PIL import Image, ImageDraw

from rackticker import Module, Plugin, Provider, Snapshot, draw_text, draw_tiny, text_width, tiny_width

CHANNELS = ("best", "bullet", "blitz", "rapid", "classical", "chess960", "ultraBullet", "bot", "computer")
LIGHT, DARK = (96, 74, 44), (44, 30, 16)
WHITE_PIECE, BLACK_PIECE = (250, 246, 230), (255, 70, 30)
MOVED = (140, 120, 0)
WHITE, GREY, AMBER, GOLD, RED = (236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60), (255, 60, 40)
# Each piece in the 3 × 3 middle of its 4 × 4 square.
SHAPES = {"p": ("...", ".#.", "###"), "n": ("##.", ".##", "###"), "b": (".#.", "###", ".#."),
          "r": ("#.#", "###", "###"), "q": ("#.#", ".#.", "###"), "k": (".#.", "###", "###")}
INTRO = 4.0


def board(fen):
    """{(file 0-7, rank 0-7): piece letter} from the placement part of a FEN."""
    squares = {}
    for row, line in enumerate(fen.split()[0].split("/")):
        file = 0
        for ch in line:
            if ch.isdigit():
                file += int(ch)
            else:
                squares[(file, 7 - row)] = ch
                file += 1
    return squares


def square(name):
    return ord(name[0]) - 97, int(name[1]) - 1


def notation(before, after, move):
    """Short algebraic for a UCI move, from the boards either side of it (no check marks)."""
    if not move or len(move) < 4:
        return ""
    start, end = square(move[:2]), square(move[2:4])
    piece = after.get(end, "").upper()
    if piece == "K" and abs(start[0] - end[0]) == 2:
        return "O-O" if end[0] == 6 else "O-O-O"
    took = end in before or (piece == "P" and start[0] != end[0])
    if len(move) == 5:
        return (f"{move[0]}x" if took else "") + move[2:4] + "=" + move[4].upper()
    if piece == "P":
        return (f"{move[0]}x" if took else "") + move[2:4]
    return piece + ("x" if took else "") + move[2:4]


class Feed(Provider):
    """Keeps one stream open in the background; each round hands over the latest position."""

    def __init__(self, context):
        self.context = context
        self.state, self.task, self.channel = None, None, None

    async def _stream(self, channel):
        url = "https://lichess.org/api/tv/feed" if channel == "best" else f"https://lichess.org/api/tv/{channel}/feed"
        wait = 5
        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=120)
                async with aiohttp.ClientSession(timeout=timeout,
                                                 headers={"User-Agent": "RackTicker chess plugin"}) as session:
                    async with session.get(url) as response:
                        if response.status == 429:
                            await asyncio.sleep(90)
                            continue
                        response.raise_for_status()
                        wait = 5
                        async for raw in response.content:
                            if raw.strip():
                                self._event(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(wait)
            wait = min(120, wait * 2)

    def _event(self, event):
        data = event.get("d") or {}
        now = time.time()
        if event.get("t") == "featured":
            players = {}
            for player in data.get("players") or []:
                user = player.get("user") or {}
                players[player.get("color")] = {"name": user.get("name") or "Anonymous", "title": user.get("title"),
                                                "rating": player.get("rating"), "seconds": player.get("seconds")}
            self.state = {"id": data.get("id"), "orientation": data.get("orientation", "white"), "players": players,
                          "fen": data.get("fen"), "previous": None, "move": None, "san": "", "at": now, "started": now,
                          "clocks": {"white": players.get("white", {}).get("seconds"),
                                     "black": players.get("black", {}).get("seconds")}}
        elif event.get("t") == "fen" and self.state:
            fen = data.get("fen")
            san = notation(board(self.state["fen"]), board(fen), data.get("lm"))
            self.state = {**self.state, "previous": self.state["fen"], "fen": fen, "move": data.get("lm"),
                          "san": san, "at": now, "clocks": {"white": data.get("wc"), "black": data.get("bc")}}

    async def fetch(self):
        channel = self.context.settings["channel"]
        if channel != self.channel or self.task is None or self.task.done():
            if self.task is not None:
                self.task.cancel()
            self.state, self.channel = None, channel
            self.task = asyncio.ensure_future(self._stream(channel))
        return Snapshot(dict(self.state) if self.state else None)

    async def close(self):
        if self.task is not None:
            self.task.cancel()


# --- the screen ------------------------------------------------------------------------------

@lru_cache(maxsize=4)
def board_image(fen, move, flipped):
    image = Image.new("RGB", (32, 32))
    pixels = image.load()
    lit = {square(move[:2]), square(move[2:4])} if move and len(move) >= 4 else set()
    pieces = board(fen)
    for file in range(8):
        for rank in range(8):
            x = (7 - file if flipped else file) * 4
            y = (rank if flipped else 7 - rank) * 4
            color = MOVED if (file, rank) in lit else LIGHT if (file + rank) % 2 else DARK
            for dx in range(4):
                for dy in range(4):
                    pixels[x + dx, y + dy] = color
            piece = pieces.get((file, rank))
            if piece:
                ink = WHITE_PIECE if piece.isupper() else BLACK_PIECE
                for row, line in enumerate(SHAPES[piece.lower()]):
                    for col, cell in enumerate(line):
                        if cell == "#":
                            pixels[x + col, y + row + 1] = ink
    return image


def clock(seconds):
    if seconds is None:
        return ""
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def label(player):
    title = f"{player['title']} " if player.get("title") else ""
    return f"{title}{player['name']}".upper()


class Chess(Module):
    name = "chess"

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _state(self, context):
        snap = context.snapshots.get(self.name)
        return snap.data if snap and snap.data and snap.data.get("fen") else None

    def available(self, context):
        return self._state(context) is not None

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        state = self._state(context)
        if state is None:
            draw_text(frame, "Finding a game", 2, 12, GREY, mixed=True)
            return frame
        ts = context.now.timestamp()
        players = state["players"]
        fresh = ts - state["started"] < INTRO
        if (fresh or context.animation_time < 3) and "white" in players and "black" in players:
            started = int(state["fen"].split()[-1]) <= 1
            self._intro(frame, players, "LICHESS TV: NEW GAME" if fresh and started else "LICHESS TV: NOW PLAYING")
            return frame
        flipped = state["orientation"] == "black"
        frame.paste(board_image(state["fen"], state["move"], flipped), (0, 0))
        to_move = "white" if " w " in state["fen"] else "black"
        top, bottom = ("white", "black") if flipped else ("black", "white")
        x = 35
        for side, y in ((top, 0), (bottom, 25)):
            player = players.get(side) or {"name": "?", "rating": None}
            seconds = state["clocks"].get(side)
            if seconds is not None and side == to_move:
                seconds -= ts - state["at"]
            text = clock(seconds)
            ink = WHITE_PIECE if side == "white" else BLACK_PIECE
            draw_text(frame, text, 128 - text_width(text), y, AMBER if side == to_move else GREY)
            room = 128 - text_width(text) - 3 - x
            name = label(player)
            if tiny_width(name) > room:            # a long name drops its title before anything else
                name = str(player["name"]).upper()
            while tiny_width(name) > room and len(name) > 3:
                name = name[:-1]
            draw_tiny(frame, name, x, y + 1, ink)
        if state["san"]:
            san = state["san"]
            mover = "black" if to_move == "white" else "white"
            scale = 2 if text_width(san, 2, True) <= 128 - 30 - x else 1
            draw_text(frame, san, x, 9 if scale == 2 else 13, WHITE_PIECE if mover == "white" else BLACK_PIECE,
                      scale=scale, smooth=scale == 2, mixed=True)
            number = state["fen"].split()[-1]
            draw_tiny(frame, f"MOVE {number}", 128 - tiny_width(f"MOVE {number}"), 13, GREY)
        return frame

    @staticmethod
    def _intro(frame, players, heading):
        draw_tiny(frame, heading, (128 - tiny_width(heading)) // 2, 0, GREY)
        for index, side in enumerate(("white", "black")):
            player = players[side]
            y = 8 + index * 12
            ink = WHITE_PIECE if side == "white" else BLACK_PIECE
            name = label(player)
            rating = str(player.get("rating") or "")
            if text_width(name) <= 128 - text_width(rating) - 6:
                draw_text(frame, name, 0, y, ink)
            else:                                  # a long name in small letters rather than cut short
                draw_tiny(frame, name, 0, y + 1, ink)
            draw_text(frame, rating, 128 - text_width(rating), y, AMBER)


def validate_settings(settings):
    if settings.get("channel") not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    return settings


plugin = Plugin(
    "chess", "Chess", module=Chess, provider=Feed,
    defaults={"channel": "best"}, choices={"channel": CHANNELS},
    validate_settings=validate_settings,
    help={"channel": "Which Lichess TV channel: best is the top game being played right now"},
)
