"""Data from a link: put any value from a JSON web address on the panel.

Paste the address and the path to the field (for example `bitcoin.usd`,
`data.0.temperature` or `stats.members`). Up to three values rotate as cards:
your label, the value in big letters, and an optional unit. Each card can also
show a change (an arrow and a percent, green or red) and a line of detail built
from other fields of the same reply, like `MCAP {bitcoin.usd_market_cap:short}`.
No code, no plugin to write. For data that needs a key, use an address that already includes it
(a Home Assistant or Node-RED endpoint on your network works well).
"""
from __future__ import annotations

import asyncio
import math
import re

import aiohttp

from rackticker import (AMBER, GREEN, MUTED, RED, WHITE, Module, Plugin, Provider, Snapshot, draw_text, draw_tiny,
                        new_frame, text_width, tiny_width, triangle)

SLOTS = 3
CARD_SECONDS = 6.0


def pick(data, path):
    """Follow `a.b.0.c` through dicts and lists; None when the path is missing."""
    for part in [piece for piece in re.split(r"[.\[\]]", path) if piece]:
        if isinstance(data, list) and part.lstrip("-").isdigit():
            index = int(part)
            data = data[index] if -len(data) <= index < len(data) else None
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return None
        if data is None:
            return None
    return data


def display(value, decimals):
    if isinstance(value, str):  # many APIs send numbers as text ("81280.50")
        try:
            value = float(value.replace(",", "")) if re.fullmatch(r"-?[\d,]*\.?\d+", value.strip()) else value
        except ValueError:
            pass
    if isinstance(value, bool):
        return "YES" if value else "NO"
    if isinstance(value, (int, float)) and math.isfinite(value):
        number = round(float(value), decimals) if decimals >= 0 else float(value)
        if abs(number) >= 10000:
            return f"{number:,.0f}"
        return f"{number:,.{max(0, decimals)}f}" if decimals >= 0 else f"{number:g}"
    if isinstance(value, (dict, list)):
        return "?"
    return str(value)[:40]


def number(value):
    """A number from a value, or None: APIs send them as text as often as not."""
    if isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", "")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def short(value):
    """1617671147604 -> 1.6T, 24312879325 -> 24.3B."""
    for size, mark in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= size:
            scaled = value / size
            return f"{scaled:.1f}{mark}" if abs(scaled) < 100 else f"{scaled:.0f}{mark}"
    return f"{value:.0f}"


TOKEN = re.compile(r"\{([^{}:]+)(?::([^{}]*))?\}")


def detail_line(template, payload):
    """Fill `{path}` and `{path:short}` / `{path:+.1f}` from the reply; a missing field is '--'."""
    def fill(match):
        raw = pick(payload, match.group(1).strip())
        spec = (match.group(2) or "").strip()
        value = number(raw)
        if raw is None:
            return "--"
        if value is not None and spec == "short":
            return short(value)
        if value is not None and spec:
            try:
                return format(value, spec)
            except ValueError:
                return display(raw, -1)
        return display(raw, -1)
    return TOKEN.sub(fill, template).strip()


class Links(Provider):
    def __init__(self, context):
        self.context = context
        self.session = None
        self.values = {}

    async def fetch(self):
        settings = self.context.settings
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),
                                                 headers={"User-Agent": "RackTicker url_data"})

        async def one(slot):
            url = settings[f"url_{slot}"].strip()
            if not url:
                return None
            async with self.session.get(url) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            return payload

        results = await asyncio.gather(*(one(slot) for slot in range(1, SLOTS + 1)), return_exceptions=True)
        cards = []
        for slot, result in zip(range(1, SLOTS + 1), results):
            if not settings[f"url_{slot}"].strip():
                continue
            if isinstance(result, Exception):
                print(f"link {slot}: {type(result).__name__}: {result}")
                result = self.values.get(slot)  # keep the last good reply through a hiccup
            else:
                self.values[slot] = result
            value = pick(result, settings[f"path_{slot}"].strip()) if result is not None else None
            if value is None:
                continue
            change = number(pick(result, settings[f"change_{slot}"].strip())) if settings[f"change_{slot}"].strip() else None
            template = settings[f"detail_{slot}"].strip()
            cards.append({"label": settings[f"label_{slot}"] or f"Value {slot}",
                          "value": display(value, int(settings[f"decimals_{slot}"])),
                          "unit": settings[f"unit_{slot}"], "change": change,
                          "detail": detail_line(template, result) if template else ""})
        return Snapshot(cards)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class Cards(Module):
    name = "url_data"

    def refresh_interval(self, context):
        return 1 / context.config["display"]["fps"]

    def available(self, context):
        snap = context.snapshots.get(self.name)
        return bool(snap and snap.data)

    def render(self, context):
        frame = new_frame()
        snap = context.snapshots.get(self.name)
        cards = snap.data if snap and snap.data else []
        if not cards:
            return frame
        t = context.animation_time
        card = cards[int(t // CARD_SECONDS) % len(cards)]
        local = t % CARD_SECONDS
        draw_text(frame, card["label"], 0, 0, AMBER, mixed=True)
        change = card.get("change")
        if change is not None:
            colour = GREEN if change >= 0 else RED
            words = f"{abs(change):.1f}%"
            triangle(frame, 128 - text_width(words) - 8, 2, change >= 0, colour)
            draw_text(frame, words, 128 - text_width(words), 0, colour)
        value, unit, detail = card["value"], card["unit"], card.get("detail") or ""
        unit_width = text_width(unit) + 3 if unit else 0
        scale = 2 if text_width(value, 2) + unit_width <= 128 else 1
        x = (128 - text_width(value, scale) - unit_width) // 2
        rise = max(0, round((1 - min(1, local / .3)) * 6)) if len(cards) > 1 else 0
        # With a detail line the number moves up to make room for it.
        top = (9 if detail else 12) if scale == 2 else (13 if detail else 16)
        draw_text(frame, value, x, top + rise, WHITE, scale, scale == 2)
        if unit:
            draw_text(frame, unit, x + text_width(value, scale) + 3, top + 7 + rise, MUTED)
        if detail:
            while detail and tiny_width(detail) > 128:
                detail = detail[:-1].rstrip()
            draw_tiny(frame, detail, (128 - tiny_width(detail)) // 2, 26 + rise // 2, MUTED)
        return frame


def validate(settings):
    for slot in range(1, SLOTS + 1):
        url = settings[f"url_{slot}"].strip()
        if url and not url.startswith(("http://", "https://")):
            raise ValueError(f"Link {slot} must start with http:// or https://")
        if not -1 <= settings[f"decimals_{slot}"] <= 6:
            raise ValueError("decimals must be -1 (as is) to 6")
    if not 30 <= settings["refresh_seconds"] <= 3600:
        raise ValueError("refresh_seconds must be 30–3600")


defaults, ui, help_text = {"refresh_seconds": 60}, {"refresh_seconds": {"advanced": True}}, {}
for slot in range(1, SLOTS + 1):
    defaults.update({f"label_{slot}": "", f"url_{slot}": "", f"path_{slot}": "", f"unit_{slot}": "",
                     f"decimals_{slot}": -1, f"change_{slot}": "", f"detail_{slot}": ""})
    ui.update({f"label_{slot}": {"label": f"Card {slot}: label"}, f"url_{slot}": {"label": f"Card {slot}: link"},
               f"path_{slot}": {"label": f"Card {slot}: field"}, f"unit_{slot}": {"label": f"Card {slot}: unit"},
               f"decimals_{slot}": {"label": f"Card {slot}: decimals", "advanced": True},
               f"change_{slot}": {"label": f"Card {slot}: change field (optional)"},
               f"detail_{slot}": {"label": f"Card {slot}: detail line (optional)"}})
defaults.update({"label_1": "Bitcoin",
                 "url_1": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
                          "&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true",
                 "path_1": "bitcoin.usd", "unit_1": "USD", "decimals_1": 0, "change_1": "bitcoin.usd_24h_change",
                 "detail_1": "MCAP {bitcoin.usd_market_cap:short}  VOL {bitcoin.usd_24h_vol:short}"})
help_text = {"path_1": "Where the value is in the JSON, e.g. bitcoin.usd or items.0.price",
             "decimals_1": "-1 shows the number as it comes",
             "change_1": "A field holding a percent change; it shows as an arrow, green up and red down",
             "detail_1": "A line of small print. Put fields in braces: {path} or {path:short} for 1.6T, {path:+.1f} to format"}

plugin = Plugin("url_data", "Data from a link", module=Cards, provider=Links, defaults=defaults,
                validate_settings=validate, help=help_text, ui=ui)
