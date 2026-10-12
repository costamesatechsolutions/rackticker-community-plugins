"""Pocket baseball: a made-up league that is always playing, pitch by pitch.

A game is on whenever you look, run by the clock, so it carries on while the
screen is elsewhere: the diamond with the runners on and the count, the line
score inning by inning, and the play just made. Nine innings take about six
minutes; then the final, and the next two teams take the field.

Outcomes follow big-league rates (strikeouts, walks, singles, home runs, double
plays) so the scores look like real ones.
"""
from __future__ import annotations

from functools import lru_cache
import random

from PIL import Image, ImageDraw

from rackticker import Module, Plugin, draw_text, draw_tiny, text_width, tiny_width

TEAMS = (("TAC", "Costa Mesa Tacos", (255, 176, 40)), ("LBL", "Long Beach Lighthouses", (60, 200, 255)),
         ("HBS", "Huntington Surf", (40, 110, 255)), ("ANA", "Anaheim Oranges", (255, 120, 20)),
         ("IRV", "Irvine Owls", (90, 230, 120)), ("SAW", "Santa Ana Winds", (236, 238, 236)),
         ("NPP", "Newport Pelicans", (255, 214, 60)), ("LGW", "Laguna Waves", (0, 200, 200)))
NAMES = ("Diaz", "Kim", "Lopez", "Smith", "Nguyen", "Ortiz", "Brown", "Tanaka", "Reyes", "Jones", "Park", "Cruz",
         "Miller", "Silva", "Garcia", "Lee", "Moore", "Ramos", "Young", "Castro", "Ward", "Vega", "Hill", "Soto",
         "Banks", "Rojas", "Cole", "Mora", "Fox", "Santos", "Gray", "Ito", "Ruiz", "Wells", "Ford", "Leon")
# Big-league rates per plate appearance (roughly the 2020s).
OUTCOMES = (("K", .222), ("BB", .085), ("HBP", .011), ("1B", .141), ("2B", .044), ("3B", .004), ("HR", .030),
            ("GO", .245), ("FO", .218))
PITCH = .55                    # seconds between pitches
AFTER = 2.6                    # seconds the result stays up
BREAK = 4.0                    # between half innings
FINAL = 45.0                   # the final stays up this long
WHITE, GREY, AMBER, GOLD, RED, GREEN = ((236, 238, 236), (140, 146, 150), (255, 176, 40), (255, 214, 60),
                                        (255, 50, 40), (90, 230, 120))
WORDS = {"K": "STRIKES OUT", "BB": "WALKS", "HBP": "HIT BY PITCH", "1B": "SINGLES", "2B": "DOUBLES",
         "3B": "TRIPLES", "HR": "HOME RUN!", "GO": "GROUNDS OUT", "FO": "FLIES OUT", "DP": "DOUBLE PLAY",
         "SF": "SAC FLY"}


def pitches(rng, outcome):
    """A believable pitch sequence ('B' ball, 'S' strike, 'F' foul, 'X' in play) for an outcome."""
    balls = strikes = 0
    seq = []
    final_balls = 4 if outcome == "BB" else rng.choice((0, 0, 1, 1, 2, 3))
    final_strikes = 3 if outcome == "K" else rng.choice((0, 1, 1, 2, 2))
    while balls < final_balls or strikes < final_strikes:
        if balls < final_balls and (strikes >= final_strikes or rng.random() < .45):
            balls += 1
            seq.append("B")
        else:
            strikes += 1
            seq.append("S" if strikes == 3 or rng.random() < .6 else "F")
        if rng.random() < .12 and strikes == 2 and outcome != "K":
            seq.append("F")
    if outcome not in ("K", "BB"):
        seq.append("H" if outcome == "HBP" else "X")
    return seq


def advance(bases, batter_to, rng, extra=0.0):
    """Runners move up as far as the hit sends the batter, sometimes one more (`extra` chance).

    Returns (new bases, runs scored). Lead runners go first, so nobody passes anyone."""
    new, scored = [False, False, False], 0
    for base in (2, 1, 0):
        if not bases[base]:
            continue
        target = base + batter_to + (1 if rng.random() < extra else 0)
        if target >= 3:
            scored += 1
            continue
        while new[target]:
            target -= 1
        new[target] = True
    if batter_to >= 4:
        scored += 1
    else:
        new[batter_to - 1] = True
    return new, scored


def walk(bases):
    """Ball four or a hit batter: only forced runners move."""
    b1, b2, b3 = bases
    if b1 and b2 and b3:
        return [True, True, True], 1
    if b1 and b2:
        return [True, True, True], 0
    if b1:
        return [True, True, b3], 0
    return [True, b2, b3], 0


INTRO = 5.0                    # the matchup card before the first pitch
SLOT = 480.0                   # each game gets eight minutes on the clock, the final filling what is left
OPENING_DAY = 1767225600       # 2026-01-01


@lru_cache(maxsize=2)
def game(number):
    """The whole game for slot `number`, decided by its seed: plate appearances with their timings."""
    rng = random.Random(number * 7919 + 17)
    away, home = rng.sample(range(len(TEAMS)), 2)
    lineups = {side: rng.sample(NAMES, 9) for side in ("away", "home")}
    boost = {"away": rng.uniform(-.02, .02), "home": rng.uniform(-.02, .02)}
    score, hits = {"away": 0, "home": 0}, {"away": 0, "home": 0}
    line, batter = {"away": [], "home": []}, {"away": 0, "home": 0}
    plays, t, inning, over = [], INTRO, 0, False
    while not over:
        inning += 1
        for side in ("away", "home"):
            if side == "home" and inning >= 9 and score["home"] > score["away"]:
                line["home"].append("X")          # the home team needn't bat
                over = True
                break
            outs, bases, runs = 0, [False, False, False], 0
            while outs < 3:
                roll, total, outcome = rng.random(), 0.0, "FO"
                for name, rate in OUTCOMES:
                    total += rate + (boost[side] / 3 if name in ("1B", "2B", "HR") else 0)
                    if roll < total:
                        outcome = name
                        break
                scored = 0
                if outcome in ("BB", "HBP"):
                    bases, scored = walk(bases)
                elif outcome in ("1B", "2B", "3B", "HR"):
                    bases, scored = advance(bases, {"1B": 1, "2B": 2, "3B": 3, "HR": 4}[outcome], rng,
                                            .45 if outcome in ("1B", "2B") else 0)
                elif outcome == "K":
                    outs += 1
                elif outcome == "GO":
                    if bases[0] and outs < 2 and rng.random() < .45:
                        outcome, outs, bases = "DP", outs + 2, [False, bases[1], bases[2]]
                    else:
                        outs += 1
                        if outs < 3:                 # runners move up a base on the ground ball
                            moved, scored = advance(bases, 1, rng)
                            bases = [False, moved[1], moved[2]]
                elif outcome == "FO":
                    outs += 1
                    if outs < 3 and bases[2] and rng.random() < .55:
                        outcome, scored, bases = "SF", 1, [bases[0], bases[1], False]
                score[side] += scored
                runs += scored
                hits[side] += outcome in ("1B", "2B", "3B", "HR")
                seq = pitches(rng, outcome)
                plays.append({"t": t, "inning": inning, "side": side, "batter": lineups[side][batter[side]],
                              "outcome": outcome, "pitches": "".join(seq), "outs": min(outs, 3),
                              "bases": tuple(bases), "scored": scored, "score": dict(score),
                              "line": {k: list(v) for k, v in line.items()}, "runs": runs})
                t += len(seq) * PITCH + AFTER
                batter[side] = (batter[side] + 1) % 9
                if side == "home" and inning >= 9 and score["home"] > score["away"]:
                    break                            # walk-off
            line[side].append(runs)
            t += BREAK
        if inning >= 9 and score["home"] != score["away"] or inning >= 12:
            over = True
    # A long game is played a little faster so the final still gets its time on the clock.
    pace = min(1.0, (SLOT - FINAL) / t)
    for play in plays:
        play["t"] *= pace
    return {"away": away, "home": home, "plays": plays, "line": line, "score": score, "hits": hits,
            "length": t * pace, "innings": inning, "pace": pace}


def fit_name(name, room):
    """The team's full name if it fits, otherwise its nickname ("Long Beach Lighthouses" -> "Lighthouses")."""
    if text_width(name, 1, True) <= room:
        return name
    return name.split()[-1]


class PocketBaseball(Module):
    name = "pocket_baseball"

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    @staticmethod
    def _now(ts):
        """(game number, seconds into it): a new game every eight minutes since opening day."""
        number, left = divmod(ts - OPENING_DAY, SLOT)
        return int(number), left

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        number, t = self._now(context.now.timestamp())
        g = game(number)
        plays = g["plays"]
        if t >= g["length"]:
            self._final(frame, g, SLOT - t)
            return frame
        if t < INTRO:
            self._matchup(frame, g)
            return frame
        index = max(0, max((i for i, play in enumerate(plays) if play["t"] <= t), default=0))
        play = plays[index]
        local = (t - play["t"]) / g["pace"]
        thrown = min(len(play["pitches"]), int(local / PITCH) + 1)
        decided = local >= len(play["pitches"]) * PITCH
        before = plays[index - 1] if index and plays[index - 1]["side"] == play["side"] and \
            plays[index - 1]["inning"] == play["inning"] else None
        outs = play["outs"] if decided else (before["outs"] if before else 0)
        bases = play["bases"] if decided else (before["bases"] if before else (False, False, False))
        score = play["score"] if decided else (before["score"] if before else
                                                (plays[index - 1]["score"] if index else {"away": 0, "home": 0}))
        balls = sum(1 for p in play["pitches"][:thrown] if p == "B")
        strikes = min(2 if not decided or play["outcome"] != "K" else 3,
                      sum(1 for p in play["pitches"][:thrown] if p in "SF"))
        self._diamond(frame, bases, outs, play, local, decided)
        self._line(frame, g, play, score, decided)
        x = 36
        team = TEAMS[g[play["side"]]]
        if decided:
            words = WORDS[play["outcome"]]
            color = GOLD if play["outcome"] == "HR" else GREEN if play["scored"] else WHITE
            draw_text(frame, play["batter"], x, 15, team[2], mixed=True)
            draw_tiny(frame, words, x, 26, color)
            if play["scored"]:
                runs = f"+{play['scored']} RUN" + ("S" if play["scored"] > 1 else "")
                draw_tiny(frame, runs, 128 - tiny_width(runs), 26, GREEN)
        else:
            draw_text(frame, play["batter"], x, 15, team[2], mixed=True)
            count = f"{balls}-{strikes}"
            draw_text(frame, count, 128 - text_width(count), 15, WHITE)
            pitch = play["pitches"][thrown - 1] if thrown else ""
            call = {"B": "BALL", "S": "STRIKE", "F": "FOUL", "X": "IN PLAY", "H": "HIT BY PITCH"}.get(pitch, "")
            if local - (thrown - 1) * PITCH > .25:
                draw_tiny(frame, call, x, 26, RED if pitch == "S" else GREY)
            half = ("TOP " if play["side"] == "away" else "BOT ") + str(play["inning"])
            draw_tiny(frame, half, 128 - tiny_width(half), 26, GREY)
        return frame

    @staticmethod
    def _diamond(frame, bases, outs, play, local, decided):
        draw = ImageDraw.Draw(frame)
        draw.line((16, 28, 28, 16), fill=(70, 120, 60))
        draw.line((28, 16, 16, 4), fill=(70, 120, 60))
        draw.line((16, 4, 4, 16), fill=(70, 120, 60))
        draw.line((4, 16, 16, 28), fill=(70, 120, 60))
        for occupied, (x, y) in zip(bases, ((28, 16), (16, 4), (4, 16))):
            draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill=GOLD if occupied else (40, 44, 48),
                           outline=(120, 120, 120))
        draw.rectangle((15, 27, 17, 29), fill=WHITE)
        # The pitch: the ball travels from the mound to the plate.
        if not decided:
            into = (local % PITCH) / PITCH
            if into < .6:
                y = 17 + round(into / .6 * 10)
                draw.point((16, y), fill=WHITE)
        elif play["outcome"] in ("HR", "2B", "3B", "1B", "FO", "SF") and local - len(play["pitches"]) * PITCH < 1.2:
            fly = (local - len(play["pitches"]) * PITCH) / 1.2
            tx = {"HR": 31, "3B": 30, "2B": 2, "1B": 24, "FO": 10, "SF": 22}[play["outcome"]]
            x = round(16 + (tx - 16) * fly)
            y = round(27 - 27 * fly + 10 * fly * fly) if play["outcome"] != "HR" else round(27 - 30 * fly)
            if 0 <= y < 32:
                draw.point((x, y), fill=GOLD if play["outcome"] == "HR" else WHITE)
        for i in range(3):
            draw.ellipse((24 + i * 3, 27, 25 + i * 3, 28), fill=RED if i < outs else (50, 50, 56))

    @staticmethod
    def _line(frame, g, play, score, decided):
        """The line score: inning runs so far, then total runs."""
        x0 = 36
        for row, side in enumerate(("away", "home")):
            code, _, color = TEAMS[g[side]]
            y = 1 + row * 6
            draw_tiny(frame, code, x0, y, color)
            line = list(play["line"][side])
            if side == play["side"]:
                line.append(play["runs"] if decided else play["runs"] - play["scored"])
            start = max(0, len(line) - 9)
            for i, runs in enumerate(line[start:]):
                draw_tiny(frame, str(runs), x0 + 15 + i * 6, y, WHITE if runs else GREY)
            total = str(score[side])
            draw_tiny(frame, total, 127 - tiny_width(total), y, GOLD)

    @staticmethod
    def _final(frame, g, until_next):
        draw_tiny(frame, "FINAL" + ("" if g["innings"] == 9 else f" / {g['innings']}"), 0, 0, GOLD)
        for row, side in enumerate(("away", "home")):
            _, name, color = TEAMS[g[side]]
            y = 8 + row * 12
            runs = str(g["score"][side])
            room = 128 - text_width(runs) - 4
            draw_text(frame, fit_name(name, room), 0, y, color, mixed=True)
            draw_text(frame, runs, 128 - text_width(runs), y, WHITE)
        seconds = max(0, int(until_next))
        nxt = f"NEXT GAME {seconds // 60}:{seconds % 60:02d}"
        draw_tiny(frame, nxt, 128 - tiny_width(nxt), 0, GREY)

    @staticmethod
    def _matchup(frame, g):
        draw_tiny(frame, "PLAY BALL", (128 - tiny_width("PLAY BALL")) // 2, 0, GOLD)
        for row, side in enumerate(("away", "home")):
            _, name, color = TEAMS[g[side]]
            text = fit_name(name, 128 - 14)
            draw_text(frame, text, 0, 8 + row * 12, color, mixed=True)
            draw_tiny(frame, "AT" if row == 0 else "", 120, 13, GREY)


plugin = Plugin("pocket_baseball", "Pocket baseball", module=PocketBaseball)
