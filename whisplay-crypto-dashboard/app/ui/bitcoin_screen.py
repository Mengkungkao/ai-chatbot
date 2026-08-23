r"""Page 1 -- Bitcoin home.

    +----------------------+
    | BTC/USD       LIVE * |
    |                      |
    | $112,540.32          |
    | ^ +2.41%    H/L      |
    |                      |
    |      /\              |
    |    /    \/\          |
    |  /          \        |
    |                      |
    | 1H  4H  1D  1W  1Y   |
    +----------------------+

The price is the largest element on the screen; everything else is
subordinate to it.
"""

from __future__ import annotations

from app.chart.renderer import render_chart
from app.market.provider import TIMEFRAMES
from app.ui import theme, widgets
from app.ui.base import Screen
from app.utils.format import (
    format_age,
    format_clock,
    format_compact,
    format_price,
)

PRICE_SIZES = (34, 30, 27, 24, 21)


class BitcoinScreen(Screen):
    name = "bitcoin"
    title = "BTC/USD"

    def render(self, draw, ctx):
        snap = ctx.snapshot
        settings = ctx.settings

        widgets.draw_header(
            draw, settings.pair_label, snap.online, refreshing=snap.refreshing
        )

        # --- price ------------------------------------------------------
        price_text = format_price(snap.best_price, settings.currency)
        price_font = theme.fit_font(draw, price_text, 224, PRICE_SIZES, bold=True)
        price_color = theme.TEXT if snap.has_any_data else theme.TEXT_MUTED
        draw.text((8, 28), price_text, font=price_font, fill=price_color)

        # --- 24h change + high/low --------------------------------------
        widgets.draw_change(draw, 8, 68, snap.best_change_24h, font_size=17)

        market = snap.market
        if market.high_24h is not None and market.low_24h is not None:
            fnt = theme.font(10, bold=True)
            high = format_compact(market.high_24h, settings.currency)
            low = format_compact(market.low_24h, settings.currency)
            text = f"H {high}   L {low}"
            width = theme.text_width(draw, text, fnt)
            draw.text(
                (theme.SCREEN_WIDTH - 8 - width, 72),
                text, font=fnt, fill=theme.TEXT_MUTED,
            )

        # --- chart -------------------------------------------------------
        render_chart(
            draw, snap.chart, (0, 94, theme.SCREEN_WIDTH - 6, 210),
            currency=settings.currency,
        )

        # --- window performance -----------------------------------------
        change = snap.chart.change_pct if snap.chart is not None else None
        if change is not None:
            fnt = theme.font(10, bold=True)
            label = f"{snap.timeframe} CHANGE"
            draw.text((8, 216), label, font=fnt, fill=theme.TEXT_MUTED)
            widgets.draw_change(draw, 8 + theme.text_width(draw, label, fnt) + 8,
                                214, change, font_size=12)

        if market.volume_24h is not None:
            fnt = theme.font(10, bold=True)
            text = f"VOL {format_compact(market.volume_24h, settings.currency)}"
            width = theme.text_width(draw, text, fnt)
            draw.text(
                (theme.SCREEN_WIDTH - 8 - width, 216),
                text, font=fnt, fill=theme.TEXT_DIM,
            )

        # --- timeframe selector ------------------------------------------
        widgets.draw_timeframe_strip(draw, 236, TIMEFRAMES, snap.timeframe, height=22)

        # --- footer -------------------------------------------------------
        if snap.online:
            footer = f"UPDATED {format_clock(snap.last_success)}"
            color = theme.TEXT_MUTED
        elif snap.last_success:
            footer = f"OFFLINE  LAST {format_clock(snap.last_success)} ({format_age(snap.last_success, ctx.now)} AGO)"
            color = theme.WARN
        else:
            footer = "CONNECTING..."
            color = theme.TEXT_MUTED
        widgets.draw_footer(draw, footer, color=color, y=theme.SCREEN_HEIGHT - 14)
