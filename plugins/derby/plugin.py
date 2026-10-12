"""Derby night: a horse race on the panel, start to photo finish, on its own.

Every visit is a new race: the tote board with the morning line, the gate, the
field strung out down the stretch with the running order along the bottom, a
photo when it is close, and the official result with what a $2 ticket paid.
Nothing is real money and nothing is bet: it is a show.
"""
from __future__ import annotations

from functools import lru_cache
import math
import random

from PIL import Image, ImageDraw

from rackticker import (Lettering, Module, Particles, Plugin, bulb_border, draw_text, draw_tiny, ease_out, sprite,
                         stamp, text_width, tiny_width)

WHITE, GREY, AMBER, GOLD, RED = (236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60), (255, 60, 40)
GREEN = (90, 230, 120)
RAIL = (200, 200, 190)
# Saddle cloths in post-position order, as at American tracks (8 is pink there; pink washes out on LEDs).
CLOTHS = ((220, 30, 30), (235, 235, 230), (30, 90, 255), (255, 214, 0), (0, 170, 60), (70, 70, 74),
          (255, 120, 0), (0, 200, 200))
NUMBERS = ((255, 255, 255), (0, 0, 0), (255, 255, 255), (0, 0, 0), (255, 255, 255), (255, 214, 0),
           (0, 0, 0), (0, 0, 0))
COATS = ((150, 72, 28), (180, 90, 30), (110, 56, 26), (160, 150, 140), (196, 120, 50))
NAMES = ("THUNDERBOLT", "GOLD RUSH", "LUCKY BREAK", "NEON NIGHTS", "DOUBLE DOWN", "SHOWTIME", "MIDNIGHT",
         "HIGH ROLLER", "SILVER SPUR", "DESERT WIND", "BIG SPENDER", "JACKPOT JOE", "SNAKE EYES", "WILD CARD",
         "LONGSHOT", "PARLAY", "SURF CITY", "RED ROCKET", "RIVER QUEEN", "IRON HORSE", "SUNDANCE", "DARK HORSE",
         "PAYDIRT", "BOXCAR", "QUICK CASH", "ALL IN", "HOUSE MONEY", "BANKROLL", "ACE HIGH", "ROYAL FLUSH",
         "SIDE BET", "HOT STREAK", "RAIN CHECK", "TAQUERIA", "EL CAMINO", "SANTA ANA", "NORTH STAR",
         "LUCKY SEVEN", "SPARK PLUG", "TOP SHELF", "LAST CALL", "HAPPY HOUR", "STARDUST", "BOARDWALK",
         "MOONSHINE", "HIGH NOON", "COPPER PENNY", "BLUE MOON", "FAST LANE", "TUMBLEWEED")
ODDS = ((.8, "4-5"), (1, "1-1"), (1.2, "6-5"), (1.5, "3-2"), (2, "2-1"), (2.5, "5-2"), (3, "3-1"), (3.5, "7-2"),
        (4, "4-1"), (5, "5-1"), (6, "6-1"), (8, "8-1"), (10, "10-1"), (12, "12-1"), (15, "15-1"), (20, "20-1"),
        (30, "30-1"))
FIELD = 8
DISTANCE = 1000            # track pixels from the gate to the wire
STEP = 1 / 30
BOARD, GATE = 8.0, 1.6     # seconds of tote board, seconds in the gate
LEADER_X = 98
CLOCK = 3.9                # race seconds shown per real second, so six furlongs reads like 1:10
RESULT_SECONDS = 7.0
FRAMES = (("....ss.h", ".bbbbbbh", "bbbbbbb.", ".l...l..", "l.....l."),
          ("....ss.h", ".bbbbbbh", "bbbbbbb.", "..l.l...", "..l..l.."),
          ("....ss.h", ".bbbbbbh", "bbbbbbb.", "..ll.l..", ".l....l."))


@lru_cache(maxsize=4)
def race(seed):
    """Everything about one race, decided by its seed: the field, the odds and every stride."""
    rng = random.Random(seed)
    names = rng.sample(NAMES, FIELD)
    ability = [rng.gauss(0, 1) for _ in range(FIELD)]
    style = [rng.choice(("front", "stalk", "close")) for _ in range(FIELD)]
    weights = [math.exp(.62 * a) for a in ability]
    total = sum(weights)
    odds = []
    for weight in weights:
        fair = (1 - weight / total) / (weight / total) * 1.18   # the track's cut
        odds.append(min(ODDS, key=lambda pair: abs(math.log(pair[0]) - math.log(max(fair, .8)))))
    # The race itself: each horse's speed wanders, front runners fade, closers kick.
    waves = [[(rng.uniform(.6, 1.6), rng.uniform(0, 6.3)) for _ in range(3)] for _ in range(FIELD)]
    luck = [rng.gauss(0, .7) for _ in range(FIELD)]
    positions = [[0.0] for _ in range(FIELD)]
    finish = [None] * FIELD
    t = 0.0
    while any(time is None for time in finish) and t < 40:
        t += STEP
        for horse in range(FIELD):
            here = positions[horse][-1]
            progress = here / DISTANCE
            shape = {"front": .06 - .11 * progress, "stalk": .01 + .02 * math.sin(progress * 3),
                     "close": -.05 + .12 * max(0.0, progress - .45) / .55}[style[horse]]
            wobble = sum(.022 * math.sin(f * t + p) for f, p in waves[horse])
            speed = 55 * (1 + .011 * ability[horse] + .02 * luck[horse] + shape + wobble)
            if t < .5:
                speed *= t / .5 + .2
            positions[horse].append(here + speed * STEP)
            if finish[horse] is None and positions[horse][-1] >= DISTANCE:
                over = positions[horse][-1] - DISTANCE
                finish[horse] = t - over / speed
    order = sorted(range(FIELD), key=lambda horse: finish[horse])
    return {"names": names, "odds": odds, "positions": positions, "finish": finish, "order": order,
            "coats": [rng.choice(COATS) for _ in range(FIELD)], "number": rng.randint(1, 9)}


def where(info, horse, t):
    steps = info["positions"][horse]
    index = t / STEP
    low = min(len(steps) - 1, int(index))
    high = min(len(steps) - 1, low + 1)
    return steps[low] + (steps[high] - steps[low]) * (index - low)


def payouts(info):
    """What $2 paid to win, place and show, from the morning line (the tote's own rounding to 20 cents)."""
    def price(value):
        return max(2.1, math.floor(value * 5) / 5)
    first, second, third = info["order"][:3]
    win = 2 + 2 * info["odds"][first][0]
    return (price(win), price(2 + 2 * info["odds"][second][0] * .45), price(2 + 2 * info["odds"][third][0] * .28))


def race_clock(seconds):
    shown = seconds * CLOCK
    return f"{int(shown // 60)}:{shown % 60:05.2f}"


def cloth(frame, horse, x, y):
    """A saddle-cloth number: a 7 × 7 block in the post colour with the number on it."""
    ImageDraw.Draw(frame).rectangle((x, y, x + 6, y + 6), fill=CLOTHS[horse])
    draw_tiny(frame, str(horse + 1), x + 2, y + 1, NUMBERS[horse])


@lru_cache(maxsize=64)
def horse_sprite(horse, coat, step):
    return sprite(FRAMES[step], {"b": coat, "h": coat, "l": tuple(round(c * .7) for c in coat), "s": CLOTHS[horse]})


class Derby(Module):
    name = "derby"

    def __init__(self):
        self.scene, self.races, self.seed = None, 0, 0

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def _race(self, context):
        if context.scene != self.scene:
            self.scene = context.scene
            self.races += 1
            self.seed = hash((int(context.now.timestamp()) // 60, self.races, context.scene)) & 0xFFFFFFFF
        return race(self.seed)

    def _length(self, info):
        winner, second = info["order"][:2]
        photo = info["finish"][second] - info["finish"][winner] < .05
        return BOARD + GATE + info["finish"][winner] + (2.6 if photo else 1.6) + RESULT_SECONDS, photo

    def hold(self, context):
        info = self._race(context)
        return context.animation_time < self._length(info)[0]

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        info = self._race(context)
        t = context.animation_time
        total, photo = self._length(info)
        winner = info["order"][0]
        won_at = BOARD + GATE + info["finish"][winner]
        stretch = won_at + (2.6 if photo else 1.6)
        if t < BOARD:
            self._board(frame, info, t)
        elif t < stretch:
            race_t = max(0.0, t - BOARD - GATE)
            if photo and t >= won_at + .3:
                race_t = info["finish"][winner] + .05   # the photo: frozen at the wire
            self._race_view(frame, info, race_t, t - BOARD, photo and t >= won_at + .3)
        else:
            self._results(frame, info, t - stretch)
        return frame

    def _board(self, frame, info, t):
        if t < 2.4:
            title = Lettering(f"RACE {info['number']}", "drop", ((255, 176, 40),), seed=info["number"], hold=.6, y=2)
            title.draw(frame, t)
            if t > .8:
                label = "6 FURLONGS  •  POST TIME"
                draw_tiny(frame, label, (128 - tiny_width(label)) // 2, 25, GREY)
            return
        page = 0 if t < 5.2 else 1
        local = t - (2.4 if page == 0 else 5.2)
        for row in range(4):
            horse = page * 4 + row
            if local < row * .12:
                continue
            y = row * 8 + 1
            cloth(frame, horse, 0, y)
            draw_text(frame, info["names"][horse], 10, y, WHITE)
            odds = info["odds"][horse][1]
            draw_text(frame, odds, 128 - text_width(odds), y, AMBER)

    def _race_view(self, frame, info, race_t, since_gate, frozen):
        spots = [where(info, horse, race_t) for horse in range(FIELD)]
        leader = max(spots)
        camera = max(0.0, leader - LEADER_X)
        draw = ImageDraw.Draw(frame)
        # Rails: posts every 12 track pixels sliding past.
        for post in range(-int(camera) % 12 - 12, 128, 12):
            draw.line((post, 0, post + 5, 0), fill=RAIL)
            draw.line((post, 23, post + 5, 23), fill=(110, 110, 104))
        for marker, label in ((DISTANCE * .5, "1/2"), (DISTANCE * .75, "1/4")):
            x = round(marker - camera)
            if 0 <= x < 128:
                draw.line((x, 1, x, 3), fill=RED)
                draw_tiny(frame, label, x + 2, 1, GREY)
        wire = round(DISTANCE - camera)
        if 0 <= wire < 128:
            for y in range(1, 23):
                frame.putpixel((wire, y), WHITE if y % 2 else RED)
        if since_gate < GATE:   # the gate: stalls, then the doors open
            for lane in range(FIELD + 1):
                y = 1 + lane * 2.6
                draw.line((2, round(y), 11, round(y)), fill=(120, 120, 110))
            if since_gate < GATE - .25:
                draw.line((12, 1, 12, 22), fill=GREEN)
        for horse in range(FIELD):
            x = 3 + spots[horse] - camera
            stride = 0 if frozen or race_t <= 0 else int(race_t * 12 + horse) % 3
            stamp(frame, horse_sprite(horse, info["coats"][horse], stride), x, 1 + horse * 2.4)
        # The running order along the bottom, and the race clock.
        order = sorted(range(FIELD), key=lambda horse: -spots[horse])
        if race_t >= info["finish"][info["order"][0]]:
            done = [horse for horse in info["order"] if info["finish"][horse] <= race_t]
            order = done + [horse for horse in order if horse not in done]
        if frozen:   # the camera flashes, the board waits for the stewards
            if self._flash(info, since_gate):
                frame.paste((255, 255, 255), (0, 0, 128, 23))
            if int(since_gate * 3) % 3:
                draw_text(frame, "PHOTO FINISH", (128 - text_width("PHOTO FINISH")) // 2, 25, WHITE)
            return
        for place, horse in enumerate(order):
            cloth(frame, horse, place * 8, 25)
        if since_gate < GATE + 1.2 and since_gate >= GATE - .25:
            draw_tiny(frame, "AND THEY'RE OFF", 66, 26, GOLD)
        else:
            clock = race_clock(min(race_t, info["finish"][info["order"][0]]))
            draw_tiny(frame, clock, 128 - tiny_width(clock), 26, WHITE)

    @staticmethod
    def _flash(info, since_gate):
        frozen_at = GATE + info["finish"][info["order"][0]] + .3
        return since_gate - frozen_at < .07

    def _results(self, frame, info, local):
        if local < 1.8:   # the board lights up: OFFICIAL
            bulb_border(frame, local, ((255, 176, 40), (90, 40, 0)), spacing=3, speed=8)
            if int(local * 4) % 4 != 3:
                draw_text(frame, "OFFICIAL", (128 - text_width("OFFICIAL", 2)) // 2, 9, GREEN, scale=2, smooth=True)
            return
        local -= 1.8
        prices = payouts(info)
        for place in range(3):
            if local < place * .3:
                continue
            horse = info["order"][place]
            y = 1 + place * 11
            cloth(frame, horse, 0, y)
            draw_text(frame, info["names"][horse], 10, y, WHITE)
            price = f"${prices[place]:.2f}"
            draw_text(frame, price, 128 - text_width(price), y, GOLD if place == 0 else AMBER)


plugin = Plugin("derby", "Derby night", module=Derby)
