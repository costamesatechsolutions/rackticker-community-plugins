"""Word bot: a robot plays the five-letter word game, out loud, on its own.

It picks a hidden word, then guesses: each letter typed, the tiles flipping
green (right place), gold (in the word, wrong place) or grey (not in it), and
how many words could still be the answer. The share grid fills on the left.
Solved, it says how many tries it took and keeps a running average.

The solver opens with SLATE, then each time picks whichever possible answer
splits the rest best: the same idea as the well-known solvers, small enough for
a Raspberry Pi.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import random

from PIL import Image, ImageDraw

from rackticker import Module, Plugin, Provider, Snapshot, draw_text, draw_tiny, offload, text_width, tiny_width

WORDS = tuple(sorted(set("""
about above actor acute adapt admit adopt adult after again agent agree ahead alarm album alert alike alive allow
alone along alter among angel anger angle angry apart apple apply arena argue arise armor array arrow aside asset
audio avoid awake award aware awful bacon badge badly baker basic basin batch beach beard beast began begin being
below bench berry birth black blade blame blank blast blaze bleed blend bless blind blink block blond blood bloom
board boast bonus boost booth bound brain brake brand brass brave bread break breed brick bride brief bring broad
broke brook brown brush build built bunch burst buyer cabin cable camel candy canoe cargo carry catch cause chain
chair chalk champ charm chart chase cheap check cheek cheer chess chest chief child chili chill choir chose civic
civil claim clash class clean clear clerk click cliff climb clock close cloth cloud clown coach coast cocoa color
comet comic coral couch cough could count court cover crack craft crane crash crawl crazy cream creek crest crime
crisp crops cross crowd crown crude crust cubic curve cycle daily dairy dance dealt death debut decay delay delta
dense depth diary dirty disco ditch dizzy dodge doing donor doubt dough draft drain drama drank drawn dream dress
dried drift drill drink drive drown drums dying eager eagle early earth easel eaten ebony eight elbow elder elect
elite empty enemy enjoy enter entry equal error essay event every exact exist extra fable faint fairy faith false
fancy fault favor feast fence ferry fetch fever fiber field fiery fifth fifty fight final flame flash fleet flesh
float flock flood floor flour fluid flute focus foggy force forge forth forty forum found frame frank fresh fried
front frost fruit fully funny gauge ghost giant given glass gleam globe glory glove going grace grade grain grand
grant grape graph grasp grass grave gravy great greed green greet grief grill grind gripe gross group grove grown
guard guess guest guide guild habit happy harsh haste hatch haunt heart heavy hedge hello hobby honey honor horse
hotel house human humor hurry ideal image imply index inner input irony issue ivory jeans jelly jewel joint joker
jolly judge juice juicy jumbo kayak knack knife knock known koala label labor large laser later laugh layer learn
lease least leave legal lemon level lever light limit linen liver local lodge logic loose lorry lover lower loyal
lucky lunar lunch lying magic major maker mango manor maple march marsh match maybe mayor medal media mercy merit
merry metal meter might mimic minor minus mirth model moist money month moral motor motto mound mount mouse mouth
movie muddy music naive nerve never newly niece night noble noise north noted novel nurse nylon oasis ocean offer
often olive onion opera orbit order organ other otter ought ounce outer owner oxide ozone paint panel panic paper
party pasta patch pause peace peach pearl pedal penny perch phase phone photo piano piece pilot pinch pitch pixel
pizza place plain plane plant plate plaza plead pluck plumb plump point polar porch pouch pound power press price
pride prime print prior prize probe proof proud prove proxy pulse punch pupil puppy purse queen query quest quick
quiet quilt quite quota quote radar radio rainy raise rally ranch range rapid ratio reach react ready realm rebel
refer reign relax relay reply rider ridge rifle right rigid rinse risky rival river roast robin robot rocky rodeo
roger rough round route royal rugby ruler rural salad salon sandy sauce scale scare scarf scene scent scoop scope
score scout scrap screw scrub sense serve setup seven shade shake shall shame shape share shark sharp sheep sheet
shelf shell shift shine shiny shirt shock shore short shout shown sight silly since sixty skate skill skirt skull
slate sleep slice slide slope small smart smell smile smoke snack snake sneak solar solid solve sorry sound south
space spare spark speak spear speed spell spend spice spicy spine spite split spoke spoon sport spray squad stack
staff stage stain stair stake stamp stand stare start state steak steam steel steep steer stick stiff still sting
stock stone stood stool store storm story stove strap straw strip stuck study stuff style sugar suite sunny super
surge swamp swear sweat sweep sweet swept swift swing sword syrup table taken taste teach teeth tempo thank theme
there thick thief thing think third thorn those three threw throw thumb tiger tight timer tired title toast today
token tooth topic torch total touch tough tower toxic trace track trade trail train trait treat trend trial tribe
trick tried troop truck truly trunk trust truth tulip tumor tuner twice twist ultra uncle under unite unity until
upper upset urban usage usual valid value valve vapor vault video vigor vinyl viola viral virus visit vital vivid
vocal voice voter wagon waist waste watch water weary weave wedge weigh weird whale wheat wheel where which while
whisk white whole whose widen width wince windy wiser witch woman world worry worse worst worth would wound woven
wrath wrist write wrong wrote yacht yearn yeast yield young youth zebra
""".split())))
OPENER = "slate"
GREEN, GOLD, MISS = (40, 180, 60), (235, 185, 0), (70, 72, 80)
WHITE, GREY = (236, 238, 236), (140, 146, 150)
TYPE, FLIP, HOLD = .12, .28, 1.0
GUESS_SECONDS = 5 * TYPE + 5 * FLIP + HOLD
CHEER = 3.5


def score(guess, answer):
    """The tiles for a guess: 2 green, 1 gold, 0 grey, with repeated letters counted properly."""
    result = [0] * 5
    left = Counter()
    for i, (g, a) in enumerate(zip(guess, answer)):
        if g == a:
            result[i] = 2
        else:
            left[a] += 1
    for i, g in enumerate(guess):
        if result[i] == 0 and left[g] > 0:
            result[i] = 1
            left[g] -= 1
    return tuple(result)


@lru_cache(maxsize=8)
def solve(answer):
    """[(guess, tiles, words still possible after it)] until it is solved (or six tries)."""
    possible = list(WORDS)
    guess = OPENER
    played = []
    for _ in range(6):
        tiles = score(guess, answer)
        possible = [word for word in possible if score(guess, word) == tiles]
        played.append((guess, tiles, len(possible)))
        if tiles == (2, 2, 2, 2, 2):
            break
        if len(possible) <= 2:
            guess = possible[0]
            continue
        # The candidate whose answers split the rest into the most, smallest groups.
        guess = min(possible, key=lambda word: (max(Counter(score(word, other) for other in possible).values()),
                                                  word))
    return tuple(played)


def solve_many(seed, count):
    """A queue of games, solved ahead in a helper process (a hard one is a fifth of a second on a Pi)."""
    rng = random.Random(seed)
    return [(answer, solve(answer)) for answer in rng.sample(WORDS, count)]


class Games(Provider):
    """No network: keeps a queue of solved games ready, a fresh set each day."""

    def __init__(self, context):
        self.context = context
        self.games, self.day = None, None

    async def fetch(self):
        import time
        day = int(time.time() // 86400)
        if self.games is None or day != self.day:
            self.games = await offload(solve_many, day, 40)
            self.day = day
        return Snapshot(self.games)


def tile_color(value):
    return (MISS, GOLD, GREEN)[value]


class WordBot(Module):
    name = "word_bot"

    def __init__(self):
        self.scene, self.visit = None, 0

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def available(self, context):
        snap = context.snapshots.get(self.name)
        return bool(snap and snap.data)

    def _game(self, context):
        """(answer, its moves, game number, seconds into it, the games before it) for this moment of the visit."""
        if context.scene != self.scene:
            self.scene, self.visit = context.scene, self.visit + 1
        games = context.snapshots[self.name].data
        t, number, history = context.animation_time, 0, []
        while True:
            answer, moves = games[(self.visit * 3 + number) % len(games)]
            length = len(moves) * GUESS_SECONDS + CHEER
            if t < length:
                return answer, moves, number, t, history
            t -= length
            number += 1
            history.append(len(moves))

    def hold(self, context):
        if not self.available(context):
            return False
        answer, moves, number, t, _ = self._game(context)
        return number == 0 and t < len(moves) * GUESS_SECONDS + CHEER

    def render(self, context):
        frame = Image.new("RGB", (128, 32))
        if not self.available(context):
            draw_text(frame, "Thinking", 4, 12, GREY, mixed=True)
            return frame
        answer, moves, number, t, history = self._game(context)
        draw = ImageDraw.Draw(frame)
        done = int(t // GUESS_SECONDS)
        # The share grid: one row per finished guess.
        for row, (guess, tiles, left) in enumerate(moves[:min(done, len(moves))]):
            for col, value in enumerate(tiles):
                x, y = 1 + col * 5, 1 + row * 5
                draw.rectangle((x, y, x + 3, y + 3), fill=tile_color(value))
        for row in range(min(done, len(moves)), 6):
            for col in range(5):
                x, y = 1 + col * 5, 1 + row * 5
                draw.rectangle((x, y, x + 3, y + 3), outline=(40, 42, 48))
        if done >= len(moves):
            self._cheer(frame, moves, t - len(moves) * GUESS_SECONDS, history, answer)
            return frame
        guess, tiles, left = moves[done]
        local = t - done * GUESS_SECONDS
        draw_tiny(frame, f"GUESS {done + 1} OF 6", 29, 0, GREY)
        for col in range(5):
            x = 29 + col * 20
            typed = local >= col * TYPE
            flip_at = 5 * TYPE + col * FLIP
            phase = (local - flip_at) / FLIP
            if phase >= 1:
                color, height = tile_color(tiles[col]), 18
            elif phase > 0:
                height = round(abs(1 - 2 * phase) * 18)
                color = tile_color(tiles[col]) if phase > .5 else (24, 26, 30)
            else:
                color, height = (24, 26, 30), 18
            top = 7 + (18 - height) // 2
            if height:
                draw.rectangle((x, top, x + 17, top + height - 1), fill=color,
                               outline=None if phase > .5 else (90, 92, 100))
            if typed and height >= 14:
                letter = guess[col].upper()
                draw_text(frame, letter, x + (18 - text_width(letter, 2)) // 2, 9, WHITE, scale=2, smooth=True)
        if local > 5 * TYPE + 5 * FLIP:
            text = "SOLVED!" if tiles == (2, 2, 2, 2, 2) else (
                "1 WORD LEFT" if left == 1 else f"{left} WORDS LEFT")
            draw_tiny(frame, text, 128 - tiny_width(text), 27, GREEN if left == 1 else GREY)
        return frame

    @staticmethod
    def _cheer(frame, moves, local, history, answer):
        solved = moves[-1][1] == (2, 2, 2, 2, 2)
        draw = ImageDraw.Draw(frame)
        for col, letter in enumerate(answer.upper()):
            x = 29 + col * 20
            hop = round(4 * max(0.0, 1 - abs((local * 3 - col * .4) % 3 - .5) * 2)) if solved else 0
            draw.rectangle((x, 7 - hop, x + 17, 24 - hop), fill=GREEN if solved else (180, 40, 30))
            draw_text(frame, letter, x + (18 - text_width(letter, 2)) // 2, 9 - hop, WHITE, scale=2, smooth=True)
        tries = len(moves)
        line = (f"GOT IT IN {tries}" if solved else "OUT OF TRIES")
        draw_tiny(frame, line, 29, 0, GREEN if solved else GREY)
        games = history + [tries]
        average = f"AVERAGE {sum(games) / len(games):.2f}" if len(games) > 1 else "FIRST GAME"
        draw_tiny(frame, average, 128 - tiny_width(average), 27, GREY)


plugin = Plugin("word_bot", "Word bot", module=WordBot, provider=Games)
