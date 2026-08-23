"""Page 2 -- Market Overview.

Metrics are laid out from a list built at render time, so any figure the
provider could not supply is simply absent rather than shown as zero or
a placeholder. The layout closes up around whatever is missing.
"""

from __future__ import annotations

from app.ui import theme, widgets
from app.ui.base import Screen
from app.utils.format import format_compact, format_percent, format_price

FNG_LABEL_MAX = 12


class MarketScreen(Screen):
    name = "market"
    title = "MARKET"

    def render(self, draw, ctx):
        snap = ctx.snapshot
        settings = ctx.settings
        gd = snap.global_data

        widgets.draw_header(draw, "MARKET", snap.online, refreshing=snap.refreshing)

        y = 30

        # --- headline: total market cap ----------------------------------
        if gd.total_market_cap is not None:
            draw.text(
                (8, y), "TOTAL MARKET CAP",
                font=theme.font(10, bold=True), fill=theme.TEXT_MUTED,
            )
            cap_text = format_compact(gd.total_market_cap, settings.currency)
            cap_font = theme.fit_font(draw, cap_text, 150, (30, 26, 23, 20), bold=True)
            draw.text((8, y + 13), cap_text, font=cap_font, fill=theme.TEXT)

            if gd.market_cap_change_24h_pct is not None:
                widgets.draw_change(
                    draw, 8 + theme.text_width(draw, cap_text, cap_font) + 10,
                    y + 22, gd.market_cap_change_24h_pct, font_size=13,
                )
            y += 50
        else:
            y += 4

        # --- paired metrics ----------------------------------------------
        pairs = []
        if gd.total_volume_24h is not None:
            pairs.append(("24H VOLUME", format_compact(gd.total_volume_24h, settings.currency), theme.TEXT))
        if gd.btc_dominance is not None:
            pairs.append(("BTC DOM", format_percent(gd.btc_dominance, 1, signed=False), theme.ACCENT))
        if gd.eth_dominance is not None:
            pairs.append(("ETH DOM", format_percent(gd.eth_dominance, 1, signed=False), theme.TEXT))
        if gd.stablecoin_market_cap is not None:
            pairs.append(("STABLECOINS", format_compact(gd.stablecoin_market_cap, settings.currency), theme.TEXT))

        column_x = (8, 126)
        for index, (label, value, color) in enumerate(pairs[:6]):
            col = index % 2
            row = index // 2
            widgets.draw_label_value(
                draw, column_x[col], y + row * 36, label, value,
                value_color=color, label_size=10, value_size=16,
            )
        if pairs:
            y += ((len(pairs[:6]) + 1) // 2) * 36 + 4

        # --- fear & greed --------------------------------------------------
        fng = snap.fear_greed
        if fng.value is not None:
            self._draw_fear_greed(draw, y, fng)
            y += 44

        # --- BTC / ETH quick quotes ----------------------------------------
        self._draw_coin_rows(draw, y, ctx)

        if not snap.has_any_data and gd.total_market_cap is None:
            widgets.draw_centered(
                draw, 130, "NO MARKET DATA", theme.font(13, bold=True),
                fill=theme.TEXT_MUTED,
            )
            widgets.draw_centered(
                draw, 150, "Retrying...", theme.font(11), fill=theme.TEXT_MUTED,
            )

    def _draw_fear_greed(self, draw, y, fng):
        color = theme.fear_greed_color(fng.value)
        draw.text(
            (8, y), "FEAR / GREED",
            font=theme.font(10, bold=True), fill=theme.TEXT_MUTED,
        )
        value_font = theme.font(20, bold=True)
        draw.text((8, y + 13), str(fng.value), font=value_font, fill=color)

        label = (fng.classification or "")[:FNG_LABEL_MAX]
        draw.text(
            (8 + theme.text_width(draw, str(fng.value), value_font) + 8, y + 19),
            label, font=theme.font(12, bold=True), fill=color,
        )

        # 0-100 meter
        widgets.draw_progress_bar(
            draw, 8, y + 37, theme.SCREEN_WIDTH - 16, 5,
            (fng.value or 0) / 100.0, color=color,
        )

    def _draw_coin_rows(self, draw, y, ctx):
        """BTC and ETH spot quotes, from the top-coins table."""
        snap = ctx.snapshot
        if y > theme.SCREEN_HEIGHT - 34:
            return

        wanted = ("BTC", "ETH")
        rows = [coin for coin in snap.top if coin.symbol in wanted]
        if not rows and snap.best_price is not None:
            fnt = theme.font(12, bold=True)
            draw.text((8, y), ctx.settings.symbol, font=fnt, fill=theme.ACCENT)
            draw.text(
                (46, y), format_price(snap.best_price, ctx.settings.currency),
                font=fnt, fill=theme.TEXT,
            )
            widgets.draw_change(draw, 150, y, snap.best_change_24h, font_size=12)
            return

        for index, coin in enumerate(rows[:2]):
            row_y = y + index * 20
            if row_y > theme.SCREEN_HEIGHT - 16:
                break
            fnt = theme.font(12, bold=True)
            color = theme.ACCENT if coin.symbol == "BTC" else theme.TEXT_DIM
            draw.text((8, row_y), coin.symbol, font=fnt, fill=color)
            draw.text(
                (46, row_y), format_price(coin.price, ctx.settings.currency),
                font=fnt, fill=theme.TEXT,
            )
            widgets.draw_change(draw, 150, row_y, coin.change_24h_pct, font_size=12)
