"""Page 3 -- Top cryptocurrencies by market cap.

The panel is only 240 px wide, so this shows 3-5 assets rather than
trying to be a full table. Rows are fixed-height panels for scannability.
"""

from __future__ import annotations

from app.ui import theme, widgets
from app.ui.base import Screen
from app.utils.format import format_compact, format_price

ROW_HEIGHT = 44
ROW_GAP = 4
FIRST_ROW_Y = 30


class CryptoScreen(Screen):
    name = "top"
    title = "TOP MARKET CAP"

    def render(self, draw, ctx):
        snap = ctx.snapshot
        settings = ctx.settings

        widgets.draw_header(
            draw, "TOP MARKET CAP", snap.online, refreshing=snap.refreshing
        )

        coins = list(snap.top)[: settings.top_count]
        if not coins:
            widgets.draw_centered(
                draw, 120, "NO DATA", theme.font(14, bold=True), fill=theme.TEXT_MUTED
            )
            widgets.draw_centered(
                draw, 142, "Retrying...", theme.font(11), fill=theme.TEXT_MUTED
            )
            return

        # Fit the available vertical space rather than overflowing.
        available = theme.SCREEN_HEIGHT - FIRST_ROW_Y - 6
        max_rows = max(1, available // (ROW_HEIGHT + ROW_GAP))
        coins = coins[:max_rows]

        for index, coin in enumerate(coins):
            self._draw_row(draw, FIRST_ROW_Y + index * (ROW_HEIGHT + ROW_GAP),
                           index, coin, settings)

    def _draw_row(self, draw, y, index, coin, settings):
        widgets.draw_panel(
            draw, [6, y, theme.SCREEN_WIDTH - 6, y + ROW_HEIGHT],
            radius=6, fill=theme.PANEL,
        )

        rank = coin.rank if coin.rank is not None else index + 1
        draw.text(
            (14, y + 7), str(rank),
            font=theme.font(11, bold=True), fill=theme.TEXT_MUTED,
        )

        # Bitcoin keeps the accent colour; everything else is neutral.
        symbol_color = theme.ACCENT if coin.symbol == settings.symbol else theme.TEXT
        draw.text(
            (32, y + 5), coin.symbol,
            font=theme.font(15, bold=True), fill=symbol_color,
        )

        if coin.market_cap is not None:
            draw.text(
                (32, y + 24), format_compact(coin.market_cap, settings.currency),
                font=theme.font(10, bold=True), fill=theme.TEXT_MUTED,
            )

        price_text = format_price(coin.price, settings.currency)
        price_font = theme.fit_font(draw, price_text, 120, (15, 14, 12, 11), bold=True)
        price_width = theme.text_width(draw, price_text, price_font)
        draw.text(
            (theme.SCREEN_WIDTH - 14 - price_width, y + 6),
            price_text, font=price_font, fill=theme.TEXT,
        )

        # Right-align the change block under the price.
        change_font_size = 12
        arrow = max(6, int(change_font_size * 0.55))
        from app.utils.format import format_percent

        change_text = format_percent(coin.change_24h_pct)
        change_width = arrow + 5 + theme.text_width(
            draw, change_text, theme.font(change_font_size, bold=True)
        )
        widgets.draw_change(
            draw, theme.SCREEN_WIDTH - 14 - change_width, y + 25,
            coin.change_24h_pct, font_size=change_font_size,
        )
