"""Reusable drawing primitives shared by every screen.

Arrows and status dots are drawn as geometry rather than glyphs so they
render identically no matter which fonts the Pi image happens to ship.
"""

from __future__ import annotations

from app.ui import theme
from app.utils.format import format_percent

HEADER_HEIGHT = 22


def draw_arrow(draw, x: int, y: int, size: int, direction: int, color):
    """Triangle marker. direction: 1 up, -1 down, 0 dash."""
    half = size / 2.0
    if direction > 0:
        draw.polygon(
            [(x + half, y), (x + size, y + size), (x, y + size)], fill=color
        )
    elif direction < 0:
        draw.polygon(
            [(x, y), (x + size, y), (x + half, y + size)], fill=color
        )
    else:
        mid = y + size / 2.0
        draw.rectangle([x, mid - 1, x + size, mid + 1], fill=color)


def draw_status_dot(draw, x: int, y: int, radius: int, online: bool):
    """Filled dot when live, hollow ring when offline."""
    box = [x - radius, y - radius, x + radius, y + radius]
    if online:
        draw.ellipse(box, fill=theme.LIVE)
    else:
        draw.ellipse(box, outline=theme.OFFLINE, width=2)


def draw_header(draw, title: str, online: bool, refreshing: bool = False):
    """Title on the left, connection state on the right."""
    fnt = theme.font(13, bold=True)
    draw.text((8, 4), title.upper(), font=fnt, fill=theme.TEXT)

    if refreshing:
        label, color = "SYNC", theme.WARN
    elif online:
        label, color = "LIVE", theme.LIVE
    else:
        label, color = "OFFLINE", theme.OFFLINE

    small = theme.font(11, bold=True)
    width = theme.text_width(draw, label, small)
    right = theme.SCREEN_WIDTH - 8
    draw.text((right - width, 6), label, font=small, fill=color)

    dot_x = right - width - 10
    if refreshing:
        draw.ellipse([dot_x - 3, 8, dot_x + 3, 14], fill=theme.WARN)
    else:
        draw_status_dot(draw, dot_x, 11, 3, online)

    draw.line(
        [(0, HEADER_HEIGHT), (theme.SCREEN_WIDTH, HEADER_HEIGHT)],
        fill=theme.DIVIDER,
        width=1,
    )


def draw_change(draw, x: int, y: int, value, font_size: int = 16, bold: bool = True):
    """Arrow + signed percentage. Returns the width drawn."""
    color = theme.change_color(value)
    fnt = theme.font(font_size, bold=bold)
    text = format_percent(value)

    if value is None:
        draw.text((x, y), text, font=fnt, fill=theme.TEXT_MUTED)
        return theme.text_width(draw, text, fnt)

    direction = 1 if float(value) > 0 else (-1 if float(value) < 0 else 0)
    arrow_size = max(6, int(font_size * 0.55))
    arrow_y = y + int((font_size - arrow_size) * 0.6)
    draw_arrow(draw, x, arrow_y, arrow_size, direction, color)

    text_x = x + arrow_size + 5
    draw.text((text_x, y), text, font=fnt, fill=color)
    return (text_x + theme.text_width(draw, text, fnt)) - x


def draw_label_value(
    draw, x: int, y: int, label: str, value: str,
    value_color=theme.TEXT, label_size: int = 10, value_size: int = 15,
):
    """A dim caption above a bright value -- the core stat block."""
    draw.text(
        (x, y), label.upper(), font=theme.font(label_size, bold=True),
        fill=theme.TEXT_MUTED,
    )
    draw.text(
        (x, y + label_size + 3), value, font=theme.font(value_size, bold=True),
        fill=value_color,
    )


def draw_panel(draw, box, radius: int = 6, fill=theme.PANEL, outline=None):
    """Rounded panel with a graceful fallback on old Pillow builds."""
    try:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline)
    except AttributeError:  # Pillow < 8.2
        draw.rectangle(box, fill=fill, outline=outline)


def draw_timeframe_strip(draw, y: int, timeframes, selected: str, height: int = 22):
    """Segmented control showing the active chart timeframe."""
    count = len(timeframes)
    margin = 6
    usable = theme.SCREEN_WIDTH - margin * 2
    slot = usable / float(count)

    for index, timeframe in enumerate(timeframes):
        left = margin + index * slot
        right = left + slot - 3
        active = timeframe == selected
        fnt = theme.font(12 if active else 11, bold=True)
        width = theme.text_width(draw, timeframe, fnt)
        center = left + (right - left) / 2.0

        if active:
            draw_panel(
                draw, [left, y, right, y + height], radius=5, fill=theme.ACCENT
            )
            draw.text(
                (center - width / 2.0, y + (height - 14) / 2.0),
                timeframe, font=fnt, fill=(20, 14, 4),
            )
        else:
            draw_panel(
                draw, [left, y, right, y + height], radius=5, fill=theme.PANEL
            )
            draw.text(
                (center - width / 2.0, y + (height - 13) / 2.0),
                timeframe, font=fnt, fill=theme.TEXT_MUTED,
            )


def draw_footer(draw, text: str, color=theme.TEXT_MUTED, y: int | None = None):
    fnt = theme.font(10)
    if y is None:
        y = theme.SCREEN_HEIGHT - 13
    draw.text((8, y), text, font=fnt, fill=color)


def draw_progress_bar(draw, x: int, y: int, width: int, height: int, ratio: float,
                      color=theme.ACCENT, background=theme.PANEL_ALT):
    """Horizontal meter used by the System page."""
    ratio = max(0.0, min(1.0, float(ratio or 0.0)))
    draw_panel(draw, [x, y, x + width, y + height], radius=3, fill=background)
    if ratio > 0:
        filled = max(2, int(width * ratio))
        draw_panel(draw, [x, y, x + filled, y + height], radius=3, fill=color)


def draw_centered(draw, y: int, text: str, fnt, fill=theme.TEXT):
    width = theme.text_width(draw, text, fnt)
    draw.text(((theme.SCREEN_WIDTH - width) / 2.0, y), text, font=fnt, fill=fill)
    return width


def draw_toast(draw, text: str, kind: str = "info"):
    """Transient banner for refresh / error feedback.

    Drawn last, over the page content, near the bottom where it covers
    the least important part of every layout.
    """
    colors = {
        "info": (theme.ACCENT, (26, 16, 4)),
        "success": (theme.UP, (6, 26, 16)),
        "error": (theme.ERROR, (30, 8, 10)),
    }
    accent, background = colors.get(kind, colors["info"])

    fnt = theme.font(12, bold=True)
    text_w = theme.text_width(draw, text, fnt)
    height = 26
    width = min(theme.SCREEN_WIDTH - 16, text_w + 26)
    x0 = (theme.SCREEN_WIDTH - width) / 2.0
    y0 = theme.SCREEN_HEIGHT - height - 30

    draw_panel(
        draw, [x0, y0, x0 + width, y0 + height],
        radius=8, fill=background, outline=accent,
    )
    draw.text(
        (x0 + (width - text_w) / 2.0, y0 + (height - 15) / 2.0),
        text, font=fnt, fill=accent,
    )
