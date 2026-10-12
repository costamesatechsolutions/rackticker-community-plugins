"""Algorithms: computer science you can watch.

Sort race: two sorting algorithms, side by side, put the same 64 shuffled bars in
order at the same pace, one comparison or move at a time, and the faster one
wins. Maze: a maze carves itself across the panel, a flood fills out from the
entrance until it finds the exit, the shortest path lights up and a runner takes it.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import random

from PIL import Image, ImageDraw

from rackticker import Module, Plugin, Storyboard, draw_text, draw_tiny, text_width, tiny_width

WHITE, GREY, AMBER, GOLD, RED, GREEN, BLUE = ((236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60),
                                              (255, 50, 40), (90, 230, 120), (40, 110, 255))
MODES = ("sort", "maze")
SORT_SECONDS, MAZE_SECONDS = 26.0, 26.0
BARS = 64
NAMES = {"bubble": "BUBBLE", "insertion": "INSERTION", "selection": "SELECTION", "quick": "QUICKSORT",
         "merge": "MERGE SORT", "heap": "HEAP SORT", "shell": "SHELL SORT", "cocktail": "COCKTAIL"}


# --- sorting: every algorithm records (array, highlighted) after each step -------------------

def record(name, values):
    a = list(values)
    steps = [(bytes(a), ())]

    def note(*marks):
        steps.append((bytes(a), marks))

    n = len(a)
    if name == "bubble":
        for end in range(n - 1, 0, -1):
            swapped = False
            for i in range(end):
                if a[i] > a[i + 1]:
                    a[i], a[i + 1] = a[i + 1], a[i]
                    swapped = True
                note(i, i + 1)
            if not swapped:
                break
    elif name == "cocktail":
        low, high, swapped = 0, n - 1, True
        while swapped:
            swapped = False
            for i in range(low, high):
                if a[i] > a[i + 1]:
                    a[i], a[i + 1], swapped = a[i + 1], a[i], True
                note(i, i + 1)
            high -= 1
            for i in range(high, low, -1):
                if a[i - 1] > a[i]:
                    a[i - 1], a[i], swapped = a[i], a[i - 1], True
                note(i - 1, i)
            low += 1
    elif name == "insertion":
        for i in range(1, n):
            j = i
            while j > 0 and a[j - 1] > a[j]:
                a[j - 1], a[j] = a[j], a[j - 1]
                note(j - 1, j)
                j -= 1
            note(j)
    elif name == "selection":
        for i in range(n - 1):
            low = i
            for j in range(i + 1, n):
                if a[j] < a[low]:
                    low = j
                note(i, j)
            a[i], a[low] = a[low], a[i]
            note(i, low)
    elif name == "quick":
        def quick(lo, hi):
            if lo >= hi:
                return
            pivot, i = a[hi], lo
            for j in range(lo, hi):
                if a[j] < pivot:
                    a[i], a[j] = a[j], a[i]
                    i += 1
                note(j, hi)
            a[i], a[hi] = a[hi], a[i]
            note(i)
            quick(lo, i - 1)
            quick(i + 1, hi)
        quick(0, n - 1)
    elif name == "merge":
        def merge(lo, hi):
            if hi - lo < 2:
                return
            mid = (lo + hi) // 2
            merge(lo, mid)
            merge(mid, hi)
            left, right = a[lo:mid], a[mid:hi]
            i = j = 0
            for k in range(lo, hi):
                if j >= len(right) or (i < len(left) and left[i] <= right[j]):
                    a[k] = left[i]
                    i += 1
                else:
                    a[k] = right[j]
                    j += 1
                note(k)
        merge(0, n)
    elif name == "heap":
        def sift(start, end):
            root = start
            while 2 * root + 1 <= end:
                child = 2 * root + 1
                if child + 1 <= end and a[child] < a[child + 1]:
                    child += 1
                note(root, child)
                if a[root] < a[child]:
                    a[root], a[child] = a[child], a[root]
                    root = child
                else:
                    return
        for start in range((n - 2) // 2, -1, -1):
            sift(start, n - 1)
        for end in range(n - 1, 0, -1):
            a[0], a[end] = a[end], a[0]
            note(0, end)
            sift(0, end - 1)
    elif name == "shell":
        gap = n // 2
        while gap:
            for i in range(gap, n):
                j = i
                while j >= gap and a[j - gap] > a[j]:
                    a[j - gap], a[j] = a[j], a[j - gap]
                    note(j - gap, j)
                    j -= gap
                note(j)
            gap //= 2
    steps.append((bytes(a), ()))
    return steps


@lru_cache(maxsize=4)
def race(seed):
    rng = random.Random(seed)
    values = list(range(1, BARS + 1))
    rng.shuffle(values)
    fast = rng.choice(("quick", "merge", "heap", "shell"))
    other = rng.choice([name for name in NAMES if name != fast])
    left, right = (fast, other) if rng.random() < .5 else (other, fast)
    return left, right, record(left, values), record(right, values)


def bar_color(value):
    """Red through amber, green and cyan to blue: a rainbow with no pinks."""
    stops = ((255, 40, 30), (255, 170, 0), (90, 230, 60), (0, 200, 220), (40, 90, 255))
    position = (value - 1) / (BARS - 1) * (len(stops) - 1)
    low = min(int(position), len(stops) - 2)
    f = position - low
    return tuple(round(a + (b - a) * f) for a, b in zip(stops[low], stops[low + 1]))


# --- the maze ---------------------------------------------------------------------------------

COLS, ROWS = 63, 15          # cells; a cell and its wall are two pixels


@lru_cache(maxsize=2)
def maze(seed):
    """(order the passages were carved in, flood order from the entrance, the shortest path)."""
    rng = random.Random(seed)
    seen = {(0, 0)}
    stack, carved = [(0, 0)], [((0, 0), (0, 0))]
    while stack:
        x, y = stack[-1]
        options = [(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                   if 0 <= x + dx < COLS and 0 <= y + dy < ROWS and (x + dx, y + dy) not in seen]
        if not options:
            stack.pop()
            continue
        nxt = rng.choice(options)
        seen.add(nxt)
        carved.append(((x, y), nxt))
        stack.append(nxt)
    links = {}
    for a, b in carved[1:]:
        links.setdefault(a, []).append(b)
        links.setdefault(b, []).append(a)
    start, goal = (0, rng.randrange(ROWS)), (COLS - 1, rng.randrange(ROWS))
    came, flood, queue = {start: None}, [], deque([start])
    while queue:
        cell = queue.popleft()
        flood.append(cell)
        if cell == goal:
            break
        for nxt in links.get(cell, ()):
            if nxt not in came:
                came[nxt] = cell
                queue.append(nxt)
    path, cell = [], goal
    while cell is not None:
        path.append(cell)
        cell = came[cell]
    return tuple(carved), tuple(flood), tuple(reversed(path)), start, goal


def px(cell):
    return 1 + cell[0] * 2, 1 + cell[1] * 2


def carve(frame, passages):
    """Solid rock, then the passages cut out of it."""
    ImageDraw.Draw(frame).rectangle((0, 0, 127, 30), fill=(40, 70, 150))
    pixels = frame.load()
    for a, b in passages:
        ax, ay = px(a)
        bx, by = px(b)
        pixels[ax, ay] = pixels[bx, by] = pixels[(ax + bx) // 2, (ay + by) // 2] = (0, 0, 0)


@lru_cache(maxsize=2)
def carved_image(seed):
    image = Image.new("RGB", (128, 32))
    carve(image, maze(seed)[0])
    return image


class Algorithms(Module):
    name = "algorithms"

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
            return [(mode, SORT_SECONDS if mode == "sort" else MAZE_SECONDS) for mode in modes]

        self.story.sync(context.animation_time, build, context.scene)
        mode, local, _ = self.story.current(context.animation_time, build) or (modes[0], 0, 0)
        lap = int(context.animation_time // sum(seconds for _, seconds in build(0)))
        seed = self.visit * 1009 + lap * 7
        if mode == "sort":
            self._sort(frame, local, seed)
        else:
            self._maze(frame, local, seed)
        return frame

    @staticmethod
    def _sort(frame, local, seed):
        left, right, left_steps, right_steps = race(seed)
        longest = max(len(left_steps), len(right_steps))
        # Same pace for both, quick enough that the slow one finishes too, never slower than 60 a second.
        pace = max(60.0, longest / (SORT_SECONDS - 6))
        shown = int(max(0.0, local - 1.5) * pace)
        draw = ImageDraw.Draw(frame)
        for side, (name, steps) in enumerate(((left, left_steps), (right, right_steps))):
            x0 = side * 64
            index = min(shown, len(steps) - 1)
            values, marks = steps[index]
            done = shown >= len(steps) - 1
            for i, value in enumerate(values):
                height = round(value / BARS * 24)
                color = WHITE if i in marks and not done else bar_color(value)
                draw.line((x0 + i, 31, x0 + i, 32 - height), fill=color)
            label = NAMES[name]
            if done:
                finished_at = 1.5 + (len(steps) - 1) / pace
                first = len(steps) <= len(left_steps if side else right_steps)
                tag = "WINS" if first else "DONE"
                if not first or int((local - finished_at) * 3) % 2 == 0 or local - finished_at > 3:
                    draw_tiny(frame, f"{label} {tag}", x0 + 1, 0, GOLD if first else GREY)
            else:
                draw_tiny(frame, label, x0 + 1, 0, WHITE)
            if not done:
                count = f"{index:,}"
                draw_tiny(frame, count, x0 + 63 - tiny_width(count), 0, GREY)
        draw.line((63, 6, 63, 31), fill=(0, 0, 0))

    @staticmethod
    def _maze(frame, local, seed):
        carved, flood, path, start, goal = maze(seed)
        draw = ImageDraw.Draw(frame)
        dig_for, flood_for, path_for = 9.0, 6.0, 2.0
        dug = min(len(carved), int(local / dig_for * len(carved)))
        if dug == len(carved):
            frame.paste(carved_image(seed), (0, 0))
        else:
            carve(frame, carved[:dug])
        pixels = frame.load()
        if dug < len(carved):
            hx, hy = px(carved[dug][1])
            draw.rectangle((hx - 1, hy - 1, hx + 1, hy + 1), fill=WHITE)
            return
        # The way in and out.
        sx, sy = px(start)
        gx, gy = px(goal)
        pixels[0, sy] = GREEN
        pixels[127, gy] = RED
        t = local - dig_for
        reached = min(len(flood), int(max(0.0, t) / flood_for * len(flood)))
        for index, cell in enumerate(flood[:reached]):
            x, y = px(cell)
            age = (reached - index) / max(1, len(flood))
            fresh = max(0.0, 1 - age * 4)       # the edge of the flood bright, behind it settling to green
            pixels[x, y] = (round(200 * fresh), round(110 + 145 * fresh), round(40 + 200 * fresh))
        t -= flood_for
        if t < 0:
            return
        lit = min(len(path), int(t / path_for * len(path)) + 1)
        for a, b in zip(path[:lit], path[1:lit]):
            ax, ay = px(a)
            bx, by = px(b)
            draw.line((ax, ay, bx, by), fill=GOLD)
        t -= path_for
        if t > 0:
            runner = min(len(path) - 1, int(t / 5.0 * len(path)))
            x, y = px(path[runner])
            draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=WHITE)
            if runner == len(path) - 1:
                label = f"{len(path)} STEPS"
                draw.rectangle((127 - tiny_width(label) - 2, 0, 127, 6), fill=(0, 0, 0))
                draw_tiny(frame, label, 127 - tiny_width(label), 1, GOLD)


def validate_settings(settings):
    if settings.get("mode") not in ("auto", *MODES):
        raise ValueError("mode must be auto, sort or maze")
    return settings


plugin = Plugin(
    "algorithms", "Algorithms", module=Algorithms,
    defaults={"mode": "auto"}, choices={"mode": ("auto", *MODES)},
    validate_settings=validate_settings,
    help={"mode": "auto shows a sort race then a maze; or pick one"},
)
