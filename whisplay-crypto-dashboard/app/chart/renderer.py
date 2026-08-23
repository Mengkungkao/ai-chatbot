r"""Lightweight price chart renderer.

Deliberately hand-rolled: a charting library would pull in numpy/agg
stacks and cost far more CPU and RAM than a Pi Zero 2 W can spare for
what is ultimately a polyline. Rendering one frame is a single pass over
at most ~240 points.

Layout:

    $112.8K |       /\
            |      /  \
    $112.5K |  /\_/    \
            | /         \
    $112.2K |/
            +---------------
              60 MINUTES
"""

from __future__ import annotations

from app.ui import theme
from app.utils.format import format_compact

# Human label for the x-axis window.
WINDOW_LABELS = {
    "1H": "60 MINUTES",
    "4H": "4 HOURS",
    "1D": "24 HOURS",
    "1W": "7 DAYS",
    "1Y": "12 MONTHS",
}

GUTTER_WIDTH = 42  # space reserved for y-axis price labels


def _blend(color, background, alpha: float) -> tuple:
    """Cheap alpha blend -- avoids compositing a second RGBA layer."""
    return tuple(
        int(background[i] + (color[i] - background[i]) * alpha) for i in range(3)
    )


def _compact_label(value, currency: str) -> str:
    """Axis labels stay short: $112.5K rather than $112,540.32."""
    return format_compact(value, currency)


def render_chart(
    draw,
    series,
    box,
    currency: str = "USD",
    show_axis: bool = True,
    show_window_label: bool = True,
    line_width: int = 2,
):
    """Draw ``series`` into ``box`` = (x0, y0, x1, y1).

    Returns True when a chart was drawn, False when a placeholder was.
    """
    x0, y0, x1, y1 = box

    if series is None or not getattr(series, "is_usable", False):
        _draw_placeholder(draw, box)
        return False

    points = series.points
    prices = [price for _, price in points]
    low, high = min(prices), max(prices)

    plot_x0 = x0 + (GUTTER_WIDTH if show_axis else 2)
    plot_x1 = x1
    plot_y0 = y0
    plot_y1 = y1 - (12 if show_window_label else 0)

    if plot_x1 - plot_x0 < 10 or plot_y1 - plot_y0 < 10:
        return False

    # A perfectly flat series would divide by zero; give it a band.
    span = high - low
    if span <= 0:
        span = max(abs(high) * 0.001, 1e-6)
        low -= span / 2.0
        high += span / 2.0

    # Headroom so the line never touches the frame edges.
    padding = span * 0.12
    low -= padding
    high += padding
    span = high - low

    trend_up = points[-1][1] >= points[0][1]
    line_color = theme.UP if trend_up else theme.DOWN
    fill_color = _blend(line_color, theme.BG, 0.20)

    # --- map data to pixels (single pass) -----------------------------
    count = len(points)
    step = (plot_x1 - plot_x0) / float(count - 1)
    height = plot_y1 - plot_y0
    pixels = []
    for index, (_, price) in enumerate(points):
        px = plot_x0 + index * step
        py = plot_y1 - ((price - low) / span) * height
        pixels.append((px, py))

    # --- grid ---------------------------------------------------------
    if show_axis:
        for fraction in (0.0, 0.5, 1.0):
            gy = plot_y1 - fraction * height
            draw.line([(plot_x0, gy), (plot_x1, gy)], fill=theme.GRID, width=1)
            label = _compact_label(low + span * fraction, currency)
            fnt = theme.font(9, bold=True)
            width = theme.text_width(draw, label, fnt)
            ly = min(max(gy - 5, plot_y0), plot_y1 - 9)
            draw.text(
                (plot_x0 - 5 - width, ly), label, font=fnt, fill=theme.TEXT_MUTED
            )
        draw.line(
            [(plot_x0, plot_y0), (plot_x0, plot_y1)], fill=theme.DIVIDER, width=1
        )

    # --- area fill ----------------------------------------------------
    draw.polygon(
        pixels + [(plot_x1, plot_y1), (plot_x0, plot_y1)], fill=fill_color
    )

    # --- price line ---------------------------------------------------
    draw.line(pixels, fill=line_color, width=line_width, joint="curve")

    # --- last-price marker --------------------------------------------
    last_x, last_y = pixels[-1]
    draw.ellipse(
        [last_x - 3, last_y - 3, last_x + 3, last_y + 3],
        fill=line_color,
        outline=theme.BG,
    )

    if show_window_label:
        label = WINDOW_LABELS.get(series.timeframe, series.timeframe)
        fnt = theme.font(9, bold=True)
        width = theme.text_width(draw, label, fnt)
        center = plot_x0 + (plot_x1 - plot_x0) / 2.0
        draw.text(
            (center - width / 2.0, plot_y1 + 3), label,
            font=fnt, fill=theme.TEXT_MUTED,
        )

    return True


def _draw_placeholder(draw, box):
    """Shown while the first candles are still loading, or offline."""
    x0, y0, x1, y1 = box
    fnt = theme.font(11, bold=True)
    text = "CHART UNAVAILABLE"
    width = theme.text_width(draw, text, fnt)
    draw.line([(x0 + 4, y1 - 1), (x1, y1 - 1)], fill=theme.GRID, width=1)
    draw.text(
        (x0 + (x1 - x0 - width) / 2.0, y0 + (y1 - y0) / 2.0 - 6),
        text, font=fnt, fill=theme.TEXT_MUTED,
    )


def render_sparkline(draw, series, box, color=None, line_width: int = 1):
    """Tiny axis-free line for compact rows (future multi-coin pages)."""
    if series is None or not getattr(series, "is_usable", False):
        return False
    x0, y0, x1, y1 = box
    prices = [price for _, price in series.points]
    low, high = min(prices), max(prices)
    span = (high - low) or 1e-6

    count = len(series.points)
    step = (x1 - x0) / float(count - 1)
    pixels = [
        (x0 + i * step, y1 - ((price - low) / span) * (y1 - y0))
        for i, price in enumerate(prices)
    ]
    if color is None:
        color = theme.UP if prices[-1] >= prices[0] else theme.DOWN
    draw.line(pixels, fill=color, width=line_width)
    return True
