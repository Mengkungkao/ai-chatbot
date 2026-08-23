"""Page 4 -- Bitcoin statistics.

Builds a list of available metrics and lays them into a two-column grid,
skipping anything the provider did not return.
"""

from __future__ import annotations

from app.ui import theme, widgets
from app.ui.base import Screen
from app.utils.format import (
    format_compact,
    format_percent,
    format_price,
    format_supply,
)

BLOCK_HEIGHT = 32
COLUMN_X = (8, 126)

# The header spells the asset out when it comfortably fits the width.
FULL_NAMES = {"BTC": "BITCOIN", "ETH": "ETHEREUM", "SOL": "SOLANA", "XRP": "XRP"}


class StatisticsScreen(Screen):
    name = "statistics"
    title = "BITCOIN"

    def render(self, draw, ctx):
        snap = ctx.snapshot
        settings = ctx.settings
        market = snap.market

        widgets.draw_header(
            draw, FULL_NAMES.get(settings.symbol, settings.symbol),
            snap.online, refreshing=snap.refreshing,
        )

        # --- headline price ------------------------------------------------
        price_text = format_price(snap.best_price, settings.currency)
        price_font = theme.fit_font(draw, price_text, 160, (26, 23, 20, 18), bold=True)
        draw.text((8, 28), price_text, font=price_font, fill=theme.TEXT)
        widgets.draw_change(draw, 8, 58, snap.best_change_24h, font_size=13)

        if market.market_cap_rank is not None:
            fnt = theme.font(11, bold=True)
            text = f"RANK #{market.market_cap_rank}"
            width = theme.text_width(draw, text, fnt)
            draw.text(
                (theme.SCREEN_WIDTH - 8 - width, 34),
                text, font=fnt, fill=theme.ACCENT,
            )

        # --- metric grid ----------------------------------------------------
        blocks = self._collect(market, settings)
        if not blocks:
            widgets.draw_centered(
                draw, 150, "NO STATISTICS", theme.font(13, bold=True),
                fill=theme.TEXT_MUTED,
            )
            return

        top = 80
        draw.line(
            [(8, top - 6), (theme.SCREEN_WIDTH - 8, top - 6)],
            fill=theme.DIVIDER, width=1,
        )

        rows_available = (theme.SCREEN_HEIGHT - top - 6) // BLOCK_HEIGHT
        for index, (label, value, color) in enumerate(blocks[: rows_available * 2]):
            col = index % 2
            row = index // 2
            widgets.draw_label_value(
                draw, COLUMN_X[col], top + row * BLOCK_HEIGHT, label, value,
                value_color=color, label_size=9, value_size=14,
            )

    def _collect(self, market, settings) -> list:
        """Ordered by usefulness; None values are dropped entirely."""
        currency = settings.currency
        candidates = [
            ("MARKET CAP", market.market_cap,
             lambda v: format_compact(v, currency), theme.TEXT),
            ("24H VOLUME", market.volume_24h,
             lambda v: format_compact(v, currency), theme.TEXT),
            ("24H HIGH", market.high_24h,
             lambda v: format_price(v, currency, 0), theme.UP),
            ("24H LOW", market.low_24h,
             lambda v: format_price(v, currency, 0), theme.DOWN),
            ("SUPPLY", market.circulating_supply,
             lambda v: format_supply(v, settings.symbol), theme.TEXT),
            ("MAX SUPPLY", market.max_supply,
             lambda v: format_supply(v, settings.symbol), theme.TEXT_DIM),
            ("ALL-TIME HIGH", market.ath,
             lambda v: format_price(v, currency, 0), theme.TEXT),
            ("FROM ATH", market.ath_change_pct,
             lambda v: format_percent(v, 1), None),
            ("7D CHANGE", market.change_7d_pct,
             lambda v: format_percent(v, 1), None),
            ("30D CHANGE", market.change_30d_pct,
             lambda v: format_percent(v, 1), None),
        ]

        blocks = []
        for label, value, formatter, color in candidates:
            if value is None:
                continue
            # A None colour means "colour by direction".
            resolved = color if color is not None else theme.change_color(value)
            blocks.append((label, formatter(value), resolved))
        return blocks
