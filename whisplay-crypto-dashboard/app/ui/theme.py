"""Colour palette, fonts and text helpers for the 240x280 panel.

Design rules, in priority order: large readable numbers, high contrast,
minimal text, clear hierarchy. Bitcoin orange is the accent so the
device reads as a dedicated BTC instrument rather than a generic dash.
"""

from __future__ import annotations

import os

from PIL import ImageFont

SCREEN_WIDTH = 240
SCREEN_HEIGHT = 280

# --- palette (RGB) ----------------------------------------------------
BG = (8, 10, 16)
PANEL = (19, 23, 33)
PANEL_ALT = (26, 31, 44)
GRID = (34, 40, 55)
DIVIDER = (40, 47, 64)

TEXT = (237, 241, 249)
TEXT_DIM = (166, 176, 196)
TEXT_MUTED = (110, 120, 142)

ACCENT = (247, 147, 26)        # Bitcoin orange
ACCENT_DIM = (139, 86, 24)

UP = (38, 209, 125)
DOWN = (241, 78, 90)
FLAT = (150, 158, 178)

LIVE = (46, 214, 130)
OFFLINE = (154, 162, 184)
WARN = (245, 183, 66)
ERROR = (241, 78, 90)

FEAR = (241, 78, 90)
NEUTRAL = (245, 183, 66)
GREED = (38, 209, 125)

_FONT_CANDIDATES = {
    False: (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ),
    True: (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ),
}

_font_cache: dict = {}


def font(size: int, bold: bool = False):
    """Return a cached TrueType font, falling back to PIL's default."""
    key = (int(size), bool(bold))
    cached = _font_cache.get(key)
    if cached is not None:
        return cached

    for path in _FONT_CANDIDATES[bool(bold)]:
        if os.path.exists(path):
            try:
                loaded = ImageFont.truetype(path, size=int(size))
                _font_cache[key] = loaded
                return loaded
            except OSError:
                continue

    loaded = ImageFont.load_default()
    _font_cache[key] = loaded
    return loaded


def text_size(draw, text: str, fnt) -> tuple:
    """(width, height) of ``text``, across Pillow versions."""
    if not text:
        return (0, 0)
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
        return (right - left, bottom - top)
    except AttributeError:  # Pillow < 8
        return fnt.getsize(text)


def text_width(draw, text: str, fnt) -> int:
    return text_size(draw, text, fnt)[0]


def fit_font(draw, text: str, max_width: int, sizes, bold: bool = True):
    """Largest font from ``sizes`` (descending) whose text fits the width."""
    chosen = font(sizes[-1], bold)
    for size in sizes:
        candidate = font(size, bold)
        if text_width(draw, text, candidate) <= max_width:
            return candidate
        chosen = candidate
    return chosen


def change_color(value) -> tuple:
    """Green up, red down, grey flat/unknown."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return FLAT
    if number > 0:
        return UP
    if number < 0:
        return DOWN
    return FLAT


def fear_greed_color(value) -> tuple:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return TEXT_DIM
    if number <= 25:
        return FEAR
    if number <= 45:
        return (240, 130, 70)
    if number <= 55:
        return NEUTRAL
    if number <= 75:
        return (150, 200, 90)
    return GREED
