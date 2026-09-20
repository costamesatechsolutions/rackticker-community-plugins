"""Original pixel interpretations of classic desktop screensavers; no core hooks."""
import math
import random

from PIL import ImageDraw
from rackticker import Module, Plugin, draw_text, new_frame, text_width

MODES = ("pipes", "mystify", "starfield", "badge", "marquee")
COLORS = ((0, 210, 255), (255, 145, 0), (50, 235, 0), (255, 55, 0), (45, 110, 255), (255, 220, 0))
DEFAULTS = {"mode": "rotate", "seconds_per_mode": 16, "speed": 1.0, "seed": 95,
            "message": "HELLO RACK", "star_count": 55}


def validate(settings):
    if settings["mode"] not in ("rotate", *MODES):
        raise ValueError("Choose rotate, pipes, mystify, starfield, badge or marquee")
    for key, low, high in (("seconds_per_mode", 6, 60), ("speed", .25, 2),
                           ("seed", 0, 99999), ("star_count", 15, 100)):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
        if key != "speed" and value != int(value):
            raise ValueError(f"{key} must be a whole number")
    message = settings["message"]
    if not message.strip() or len(message) > 32 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .!?-" for c in message):
        raise ValueError("Message must be 1–32 letters, numbers, spaces or .!?- characters")
    if any(text_width(word.upper(), 2) > 124 for word in message.split()):
        raise ValueError("Each marquee word must fit the panel (at most 10 characters)")


def dim(color, factor):
    return tuple(round(c * factor) for c in color)


def reflect(value, limit):
    return limit - abs(value % (2 * limit) - limit)


def pipe_paths(seed):
    """Bounded self-avoiding lattice walks, projected into a shallow 3D box."""
    rng = random.Random(seed)
    occupied = set()
    paths = []
    for index in range(3):
        start = (index * 5 + 1, rng.randrange(4), rng.randrange(4))
        points = [start]
        occupied.add(start)
        direction = None
        for _ in range(25):
            x, y, z = points[-1]
            choices = []
            for step in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                p = tuple(a + b for a, b in zip((x, y, z), step))
                if 0 <= p[0] <= 14 and 0 <= p[1] <= 3 and 0 <= p[2] <= 3 and p not in occupied:
                    choices.append((p, step))
            if not choices:
                break
            turns = [item for item in choices if item[1] != direction]
            point, direction = rng.choice(turns if turns and rng.random() < .65 else choices)
            points.append(point)
            occupied.add(point)
        paths.append(points)
    return paths


def project(point):
    x, y, z = point
    return 4 + x * 7 + z * 4, 12 + y * 5 - z * 3


class RetroSavers(Module):
    name = "retro_savers"

    def __init__(self):
        self._pipe_key = None
        self._paths = []
        self._stars_key = None
        self._stars = []
        self._scene = None
        self._visit = 0
        self._last_time = None
        self._last_mode = 0

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def mode_at(self, context, settings):
        # A short playlist slot still gets a different saver next time around.
        scene = getattr(context, "scene", 0)
        t = context.animation_time
        if self._scene is not None and (scene != self._scene or (self._last_time is not None and t < self._last_time)):
            self._visit = (self._last_mode + 1) % len(MODES)
        self._scene, self._last_time = scene, t
        index = (self._visit + int(t // settings["seconds_per_mode"])) % len(MODES)
        self._last_mode = index
        return MODES[index] if settings["mode"] == "rotate" else settings["mode"]

    def render(self, context):
        settings = context.config["plugins"][self.name]
        mode = self.mode_at(context, settings)
        t = context.animation_time * settings["speed"]
        frame = new_frame()
        getattr(self, "_" + mode)(frame, t, settings)
        return frame

    def _pipes(self, frame, t, settings):
        epoch, local = divmod(t, 18)
        key = (int(settings["seed"]), int(epoch))
        if key != self._pipe_key:
            self._paths = pipe_paths(key[0] + key[1] * 1009)
            self._pipe_key = key
        draw = ImageDraw.Draw(frame)
        segments = []
        for index, path in enumerate(self._paths):
            count = max(0, local * 1.8 - index * 2)
            # Keep something visible even on the very first frame.
            count = max(.25, count)
            for j in range(min(len(path) - 1, math.ceil(count))):
                a, b = path[j], path[j + 1]
                fraction = min(1, count - j)
                tip = tuple(v + (w - v) * fraction for v, w in zip(a, b))
                segments.append(((a[2] + tip[2]) / 2, project(a), project(tip), COLORS[index]))
        # Far layers first; dark edge, body and specular glint make round pipes.
        for _, a, b, color in sorted(segments, key=lambda segment: segment[0], reverse=True):
            draw.line((*a, *b), fill=dim(color, .28), width=4)
            draw.line((*a, *b), fill=color, width=2)
            draw.line((a[0] - 1, a[1] - 1, b[0] - 1, b[1] - 1), fill=dim(color, .65), width=1)
            draw.ellipse((b[0] - 1, b[1] - 1, b[0] + 1, b[1] + 1), fill=color)
            draw.point((round(b[0] - 1), round(b[1] - 1)), fill=(220, 245, 200))
        # The original-style clear is an intentional cut to a fresh set of pipes.

    def _mystify(self, frame, t, settings):
        draw = ImageDraw.Draw(frame)
        phase = settings["seed"] * .13
        for trail in range(10, -1, -1):
            moment = t - trail * .12
            for shape in range(2):
                vertices = []
                for corner in range(4):
                    offset = phase + corner * 2.17 + shape * 4
                    x = 3 + reflect(moment * (11 + corner * 2) + offset * 13, 121)
                    y = 2 + reflect(moment * (4 + corner * .7) + offset * 3, 27)
                    vertices.append((round(x), round(y)))
                color = COLORS[(shape * 2 + int(t // 20)) % len(COLORS)]
                draw.line(vertices + [vertices[0]], fill=dim(color, .20 + .80 * (1 - trail / 11)), width=1)

    def _starfield(self, frame, t, settings):
        key = (settings["seed"], settings["star_count"])
        if key != self._stars_key:
            rng = random.Random(key[0])
            self._stars = [(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.random()) for _ in range(int(key[1]))]
            self._stars_key = key
        draw = ImageDraw.Draw(frame)
        for sx, sy, phase in self._stars:
            z = 1.05 - (phase + t * .22) % 1
            x, y = 64 + sx * 36 / z, 16 + sy * 13 / z
            if 0 <= x < 128 and 0 <= y < 32:
                previous = z + .025
                tail = (round(64 + sx * 36 / previous), round(16 + sy * 13 / previous))
                level = min(255, int(65 + (1 - z) * 220))
                draw.line((*tail, round(x), round(y)), fill=(level // 2, level, level))
                if z < .25:
                    draw.point((round(x), round(y)), fill=(255, 255, 255))

    def _badge(self, frame, t, settings):
        draw = ImageDraw.Draw(frame)
        x, y = round(reflect(t * 11, 106)), round(reflect(t * 4, 13))
        # Original four-pane pixel badge, not a copied Microsoft image or asset.
        for index, color in enumerate(((255, 65, 0), (70, 220, 0), (0, 120, 255), (255, 200, 0))):
            dx, dy = (index % 2) * 11, (index // 2) * 9
            draw.polygon([(x + dx, y + dy + 1), (x + dx + 8, y + dy),
                          (x + dx + 8, y + dy + 7), (x + dx, y + dy + 8)], fill=color)

    def _marquee(self, frame, t, settings):
        pages = []
        for word in settings["message"].upper().split():
            if pages and text_width(pages[-1] + " " + word, 2) <= 124:
                pages[-1] += " " + word
            else:
                pages.append(word)
        message = pages[int(t // 6) % len(pages)]
        width = text_width(message, 2)
        x = round(reflect(t * 14, max(1, 126 - width))) + 1
        y = 1 + round(reflect(t * 2.5, 15))
        draw_text(frame, message, x, y, COLORS[int(t // 9) % len(COLORS)], scale=2, smooth=True)


plugin = Plugin("retro_savers", "Retro Screensavers", module=RetroSavers,
    defaults=DEFAULTS, validate_settings=validate,
    choices={"mode": ("rotate", *MODES)},
    help={"mode": "Original pixel interpretations: 3D pipes, Mystify, starfield, bouncing badge and marquee.",
          "seconds_per_mode": "Rotate also advances between playlist visits, so short slots show every saver.",
          "message": "Marquee text, up to 32 characters. Long phrases page at word boundaries.",
          "seed": "Changes the pipe routes and starfield; no network or external assets."},
    ui={"seconds_per_mode": {"type": "slider", "min": 6, "max": 60, "step": 1, "unit": "s"},
        "speed": {"type": "slider", "min": .25, "max": 2, "step": .25},
        "star_count": {"type": "slider", "min": 15, "max": 100, "step": 1},
        "seed": {"advanced": True}})
