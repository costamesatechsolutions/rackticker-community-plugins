"""Casino: games of chance that play themselves, under the lights.

Plinko: chips drop from the top, rattle down through the pegs and land in the
prize slots along the bottom, with the winnings adding up. Slots: three reels
spin and stop one by one, near misses and all, with the credits counting up on a
win and a light show for a jackpot. Nothing is real money; it is a show.
"""
from __future__ import annotations

from functools import lru_cache
import math
import random

from PIL import Image, ImageDraw

from rackticker import (Module, Plugin, Storyboard, bounce, bulb_border, draw_text, draw_tiny, sprite, tiny_width)

WHITE, GREY, AMBER, GOLD, RED, GREEN, BLUE = ((236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60),
                                              (255, 50, 40), (90, 230, 120), (40, 110, 255))
MODES = ("plinko", "slots")
PLINKO_SECONDS, SLOTS_SECONDS = 24.0, 26.0

# --- Plinko ---------------------------------------------------------------------------------

PEG_ROWS = (4, 7, 10, 13, 16, 19, 22)
PEG_GAP = 7
SLOTS = (100, 500, 1000, 0, 10000, 0, 1000, 500, 100)     # the board on the show
SLOT_WIDTH = 14
SLOT_LEFT = 1
FLOOR = 25
STEP = 1 / 30


def pegs():
    found = []
    for index, y in enumerate(PEG_ROWS):
        offset = 4 if index % 2 else 1
        for x in range(offset, 128, PEG_GAP):
            found.append((x, y))
    return tuple(found)


PEGS = pegs()
PEGS_NEAR = {}      # pegs by the rows a chip could touch them from, so a fall checks a handful, not all 77
for _peg in PEGS:
    for _row in range(_peg[1] - 2, _peg[1] + 3):
        PEGS_NEAR.setdefault(_row, []).append(_peg)


@lru_cache(maxsize=64)
def drop(seed):
    """One chip's whole fall, decided by its seed: [(x, y)] every frame, and the slot it lands in."""
    rng = random.Random(seed)
    x, y = rng.uniform(4, 124), -2.0
    vx, vy = rng.uniform(-3, 3), 0.0
    path = []
    for _ in range(400):
        vy += 60 * STEP
        x += vx * STEP
        y += vy * STEP
        for px, py in PEGS_NEAR.get(round(y), ()):
            dx, dy = x - px, y - py
            distance = math.hypot(dx, dy)
            if distance < 1.6 and dy < .6:
                nx, ny = (dx, dy) if distance > 1e-6 else (rng.choice((-1, 1)), -.2)
                length = math.hypot(nx, ny)
                nx, ny = nx / length, ny / length
                dot = vx * nx + vy * ny
                if dot < 0:
                    vx, vy = (vx - 1.5 * dot * nx) * .7, (vy - 1.5 * dot * ny) * .55
                    vx += rng.uniform(-6, 6)
                x, y = px + nx * 1.6, py + ny * 1.6
        if x < 1:
            x, vx = 1, abs(vx) * .5
        if x > 126:
            x, vx = 126, -abs(vx) * .5
        vx *= .995
        path.append((x, y))
        if y >= FLOOR + 3:
            break
    slot = min(len(SLOTS) - 1, max(0, int((x - SLOT_LEFT) // SLOT_WIDTH)))
    return tuple(path), slot


PARTY = ((255, 214, 60), (255, 50, 40), (90, 230, 120), (40, 110, 255), (60, 220, 255), (255, 140, 30))


def party(step):
    """Saturated casino colours in turn (no pinks or purples: they wash out on LEDs)."""
    return PARTY[int(step) % len(PARTY)]


def prize_color(value):
    return {0: (90, 90, 96), 100: GREEN, 500: BLUE, 1000: AMBER, 10000: GOLD}[value]


# --- Slots ----------------------------------------------------------------------------------

SYMBOLS = {
    "cherry": (("....gg..", "...g....", "..g.g...", ".rr..rr.", "rrrr.rrr", "rrrr.rrr", ".rr..rr.", "........"),
               {"g": (60, 200, 60), "r": (240, 30, 40)}),
    "lemon": (("........", "..yyyy..", ".yyyyyy.", "yyyyyyyy", "yyyyyyyy", ".yyyyyy.", "..yyyy..", "........"),
              {"y": (255, 220, 0)}),
    "bell": (("...yy...", "..yyyy..", "..yyyy..", ".yyyyyy.", ".yyyyyy.", "yyyyyyyy", "...oo...", "........"),
             {"y": (255, 190, 0), "o": (200, 120, 0)}),
    "bar": (("........", "wwwwwwww", "w......w", "w.bbbb.w", "w.bbbb.w", "w......w", "wwwwwwww", "........"),
            {"w": (236, 238, 236), "b": (40, 90, 255)}),
    "seven": (("rrrrrrrr", "rrrrrrrr", ".....rr.", "....rr..", "...rr...", "..rr....", "..rr....", "..rr...."),
              {"r": (255, 40, 30)}),
    "diamond": (("........", "..cccc..", ".cwccwc.", "cccccccc", ".cccccc.", "..cccc..", "...cc...", "........"),
                {"c": (40, 210, 255), "w": (220, 250, 255)}),
}
STRIP = ("cherry", "lemon", "bell", "cherry", "bar", "lemon", "seven", "cherry", "bell", "diamond", "lemon", "bar",
         "cherry", "bell", "lemon", "seven", "cherry", "bar")
PAYS = {"seven": 500, "diamond": 250, "bar": 100, "bell": 50, "lemon": 20, "cherry": 10}
CELL = 11                       # pixels per symbol on the reel
REELS_X = (40, 64, 88)
SPIN_START, SPIN_STOPS = .3, (1.6, 2.3, 3.1)
SPIN_LENGTH = 6.5               # one spin, start to the end of its payout


def symbol_image(name, scale=2):
    art, palette = SYMBOLS[name]
    image = sprite(art, palette)
    return image.resize((image.width * scale, image.height * scale), Image.NEAREST) if scale != 1 else image


@lru_cache(maxsize=32)
def spin(seed):
    """Where each reel stops (a strip index) and what it pays, with a jackpot now and then."""
    rng = random.Random(seed)
    roll = rng.random()
    if roll < .05:
        target = "seven"
        stops = [rng.choice([i for i, s in enumerate(STRIP) if s == target]) for _ in range(3)]
    elif roll < .3:
        target = rng.choice(("cherry", "lemon", "bell", "bar", "diamond"))
        stops = [rng.choice([i for i, s in enumerate(STRIP) if s == target]) for _ in range(3)]
    elif roll < .5:                 # the near miss: two sevens and one just off the line
        sevens = [i for i, s in enumerate(STRIP) if s == "seven"]
        stops = [rng.choice(sevens), rng.choice(sevens), (rng.choice(sevens) + 1) % len(STRIP)]
    else:
        stops = [rng.randrange(len(STRIP)) for _ in range(3)]
    names = [STRIP[stop] for stop in stops]
    win = PAYS[names[0]] if names[0] == names[1] == names[2] else (
        5 if names.count("cherry") == 2 else 2 if "cherry" in names else 0)
    return tuple(stops), win, names[0] == names[1] == names[2] == "seven"


def reel_offset(stop, t, stop_at, turns):
    """How far the reel has turned (in symbols) at time t: fast, then easing onto its stop with a bounce."""
    final = stop + turns * len(STRIP)
    if t >= stop_at + .35:
        return float(final)
    if t >= stop_at:
        return final - .25 * (1 - bounce((t - stop_at) / .35))
    speed = 14.0
    spun = max(0.0, t - SPIN_START) * speed
    return min(final - .25, spun) if t > stop_at - .4 else spun


@lru_cache(maxsize=40)
def reel_strip(base, dim):
    """Four symbols stacked, the one before `base` on top, for the reel window to slide over."""
    strip = Image.new("RGB", (16, 64))
    for row in range(4):
        image = symbol_image(STRIP[(base + row - 1) % len(STRIP)])
        strip.paste(image, (0, row * 16))
    return Image.eval(strip, lambda v: v // 2) if dim else strip


class Casino(Module):
    name = "casino"

    def __init__(self):
        self.story = Storyboard()
        self.scene, self.visit = None, 0

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def hold(self, context):
        return self.story.hold()

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        settings = context.config["plugins"][self.name]
        if context.scene != self.scene:
            self.scene, self.visit = context.scene, self.visit + 1
        modes = MODES if settings["mode"] == "auto" else (settings["mode"],)

        def build(visit):
            return [(mode, PLINKO_SECONDS if mode == "plinko" else SLOTS_SECONDS) for mode in modes]

        self.story.sync(context.animation_time, build, context.scene)
        mode, local, _ = self.story.current(context.animation_time, build) or (modes[0], 0, 0)
        seed = self.visit * 7919 + int(context.animation_time // (PLINKO_SECONDS + SLOTS_SECONDS)) * 104729
        if mode == "plinko":
            self._plinko(frame, local, seed)
        else:
            self._slots(frame, local, seed)
        return frame

    @staticmethod
    def _plinko(frame, local, seed):
        pixels = frame.load()
        for x, y in PEGS:
            pixels[x, y] = (120, 120, 130)
        draw = ImageDraw.Draw(frame)
        # The prize slots: dividers and their values.
        for index, value in enumerate(SLOTS):
            x = SLOT_LEFT + index * SLOT_WIDTH
            draw.line((x - 1, FLOOR, x - 1, 31), fill=(70, 70, 80))
            label = "10K" if value == 10000 else "1K" if value == 1000 else str(value)
            draw_tiny(frame, label, x + (SLOT_WIDTH - 1 - tiny_width(label)) // 2, 27, prize_color(value))
        draw.line((SLOT_LEFT + len(SLOTS) * SLOT_WIDTH - 1, FLOOR, SLOT_LEFT + len(SLOTS) * SLOT_WIDTH - 1, 31),
                  fill=(70, 70, 80))
        # Chips drop one after another; each lands and lights its slot.
        total = 0
        interval = .9
        count = int(min(local, PLINKO_SECONDS - 3) / interval) + 1
        flashes = []
        for chip in range(count):
            started = chip * interval
            path, slot = drop(seed + chip)
            index = int((local - started) / STEP)
            color = party(chip)
            if index < len(path):
                x, y = path[index]
                if y >= 0:
                    draw.rectangle((round(x) - 1, round(y) - 1, round(x), round(y)), fill=color)
            else:
                total += SLOTS[slot]
                since = local - started - len(path) * STEP
                if since < .8:
                    flashes.append((slot, since))
        for slot, since in flashes:
            if int(since * 8) % 2 == 0:
                x = SLOT_LEFT + slot * SLOT_WIDTH
                draw.rectangle((x, FLOOR, x + SLOT_WIDTH - 2, 26), fill=prize_color(SLOTS[slot]))
        banner = f"${total:,}"
        draw.rectangle((0, 0, tiny_width(banner) + 2, 4), fill=(0, 0, 0))
        draw_tiny(frame, banner, 1, 0, GOLD)
        draw_tiny(frame, "PLINKO", 127 - tiny_width("PLINKO"), 0, GREY)

    def _slots(self, frame, local, seed):
        spins = int(local // SPIN_LENGTH)
        credits = 1000
        for earlier in range(spins):
            stops, win, _ = spin(seed + earlier)
            credits += win * 5 - 5
        t = local - spins * SPIN_LENGTH
        stops, win, jackpot = spin(seed + spins)
        draw = ImageDraw.Draw(frame)
        # The cabinet: a lit frame round the reels, the credit meter on the left.
        lights = ((255, 176, 40), (120, 50, 0)) if not (jackpot and t > SPIN_STOPS[-1] + .4) else \
            (party(t * 4), party(t * 4 + 3))
        bulb_border(frame, local, lights, spacing=3, speed=10 if t > SPIN_STOPS[-1] else 4)
        draw_tiny(frame, "CREDITS", 3, 5, GREY)
        paid = win * 5 if t > SPIN_STOPS[-1] + .5 else 0
        counting = min(1.0, max(0.0, (t - SPIN_STOPS[-1] - .5) / 1.5))
        shown = credits - 5 + round(paid * counting)
        draw_text(frame, f"{shown:,}", 3, 12, GOLD if counting > 0 and paid else WHITE)
        draw_tiny(frame, "BET 5", 3, 23, GREY)
        for reel, x in enumerate(REELS_X):
            draw.rectangle((x - 2, 3, x + 17, 28), fill=(18, 18, 22))
            offset = reel_offset(stops[reel], t, SPIN_STOPS[reel], 3 + reel)
            moving = SPIN_START < t < SPIN_STOPS[reel] - .1
            base = math.floor(offset)
            strip = reel_strip(base % len(STRIP), moving)
            top = round((1 + offset - base) * 16) - 4
            frame.paste(strip.crop((0, top, 16, top + 24)), (x, 4))
        if t > SPIN_STOPS[-1] + .3 and win:
            if int(t * 6) % 2:
                draw.line((REELS_X[0] - 2, 16, REELS_X[-1] + 17, 16), fill=RED)
        right = REELS_X[-1] + 20
        if t > SPIN_STOPS[-1] + .5:
            if jackpot:
                draw_tiny(frame, "JACK", right, 6, party(t * 6))
                draw_tiny(frame, "POT!", right, 13, party(t * 6 + 2))
                draw_tiny(frame, f"{win * 5}", right, 21, GOLD)
            elif win:
                draw_tiny(frame, "WIN", right, 8, GREEN)
                draw_tiny(frame, f"{win * 5}", right, 16, GOLD)
            elif sorted(STRIP[s] for s in stops[:2]) == ["seven", "seven"]:
                draw_tiny(frame, "SO", right, 8, AMBER)
                draw_tiny(frame, "CLOSE", right, 15, AMBER)


def validate_settings(settings):
    if settings.get("mode") not in ("auto", *MODES):
        raise ValueError("mode must be auto, plinko or slots")
    return settings


plugin = Plugin(
    "casino", "Casino", module=Casino,
    defaults={"mode": "auto"}, choices={"mode": ("auto", *MODES)},
    validate_settings=validate_settings,
    help={"mode": "auto plays Plinko then the slots; or pick one"},
)
