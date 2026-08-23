"""Page 5 -- System status.

A diagnostics page for a device that is expected to run unattended for
months: link state, API health, load, thermals and uptime, without
needing to SSH in.
"""

from __future__ import annotations

from app.ui import theme, widgets
from app.ui.base import Screen
from app.utils.format import format_age, format_clock, format_uptime

CHECK_ROW_HEIGHT = 19

# "TEMP" is the widest meter label, so the value column starts clear of it.
VALUE_X = 52
BAR_X = 92


class SystemScreen(Screen):
    name = "system"
    title = "SYSTEM"

    def render(self, draw, ctx):
        snap = ctx.snapshot
        stats = ctx.system or {}
        conn = ctx.connectivity or {}

        widgets.draw_header(draw, "SYSTEM", snap.online, refreshing=snap.refreshing)

        y = 30
        y = self._draw_checks(draw, y, conn, snap)
        y += 6
        y = self._draw_meters(draw, y, stats)
        y += 4
        self._draw_footer_block(draw, y, ctx, stats, snap)

    # --- connectivity checks ------------------------------------------
    def _draw_checks(self, draw, y, conn, snap):
        checks = (
            ("WIFI", bool(conn.get("wifi"))),
            ("INTERNET", bool(conn.get("internet"))),
            ("API", bool(snap.online)),
        )
        label_font = theme.font(12, bold=True)

        for index, (label, ok) in enumerate(checks):
            row_y = y + index * CHECK_ROW_HEIGHT
            draw.text((8, row_y), label, font=label_font, fill=theme.TEXT_DIM)

            state = "OK" if ok else "FAIL"
            color = theme.LIVE if ok else theme.ERROR
            width = theme.text_width(draw, state, label_font)
            right = theme.SCREEN_WIDTH - 8
            draw.text((right - width, row_y), state, font=label_font, fill=color)
            draw.ellipse(
                [right - width - 14, row_y + 4, right - width - 8, row_y + 10],
                fill=color,
            )

        return y + len(checks) * CHECK_ROW_HEIGHT

    # --- resource meters ------------------------------------------------
    def _draw_meters(self, draw, y, stats):
        draw.line(
            [(8, y), (theme.SCREEN_WIDTH - 8, y)], fill=theme.DIVIDER, width=1
        )
        y += 8

        meters = (
            ("CPU", stats.get("cpu_percent"), "%", 100.0, theme.ACCENT),
            ("RAM", stats.get("memory_percent"), "%", 100.0, theme.ACCENT),
            ("TEMP", stats.get("temperature_c"), "C", 85.0, None),
        )
        label_font = theme.font(11, bold=True)

        for label, value, unit, scale, color in meters:
            draw.text((8, y), label, font=label_font, fill=theme.TEXT_MUTED)

            if value is None:
                draw.text((VALUE_X, y), "--", font=label_font, fill=theme.TEXT_MUTED)
                y += 22
                continue

            if color is None:  # temperature is colour-coded by severity
                color = (
                    theme.LIVE if value < 60
                    else theme.WARN if value < 75
                    else theme.ERROR
                )

            text = f"{value:.0f}{unit}"
            draw.text((VALUE_X, y), text, font=label_font, fill=theme.TEXT)
            widgets.draw_progress_bar(
                draw, BAR_X, y + 3, theme.SCREEN_WIDTH - BAR_X - 8, 7,
                value / scale, color=color,
            )
            y += 22

        return y

    # --- uptime / versions ----------------------------------------------
    def _draw_footer_block(self, draw, y, ctx, stats, snap):
        draw.line(
            [(8, y), (theme.SCREEN_WIDTH - 8, y)], fill=theme.DIVIDER, width=1
        )
        y += 8

        widgets.draw_label_value(
            draw, 8, y, "UPTIME",
            format_uptime(stats.get("uptime_seconds")),
            value_color=theme.TEXT, label_size=9, value_size=14,
        )
        widgets.draw_label_value(
            draw, 126, y, "APP RAM",
            f"{stats.get('app_memory_mb'):.0f} MB"
            if stats.get("app_memory_mb") is not None else "--",
            value_color=theme.TEXT, label_size=9, value_size=14,
        )
        y += 32

        if snap.last_success:
            updated = f"{format_clock(snap.last_success)} ({format_age(snap.last_success, ctx.now)} ago)"
        else:
            updated = "never"
        widgets.draw_label_value(
            draw, 8, y, "UPDATED", updated,
            value_color=theme.TEXT_DIM, label_size=9, value_size=12,
        )
        y += 28

        # Last error is the single most useful field when something breaks.
        if snap.last_error:
            draw.text(
                (8, y), "LAST ERROR",
                font=theme.font(9, bold=True), fill=theme.TEXT_MUTED,
            )
            fnt = theme.font(10)
            message = snap.last_error
            while message and theme.text_width(draw, message, fnt) > theme.SCREEN_WIDTH - 16:
                message = message[:-1]
            draw.text((8, y + 12), message, font=fnt, fill=theme.ERROR)
        else:
            draw.text(
                (8, y), f"MODE {ctx.board_mode.upper()}",
                font=theme.font(9, bold=True), fill=theme.TEXT_MUTED,
            )
