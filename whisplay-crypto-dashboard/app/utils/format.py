"""Number and time formatting for a 240px-wide screen.

Everything here optimises for glanceability: short strings, consistent
widths, and no misleading precision.
"""

from __future__ import annotations

import time
from datetime import datetime

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "AUD": "A$", "JPY": "¥"}


def currency_symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(str(currency).upper(), "")


def format_price(value, currency: str = "USD", decimals: int | None = None) -> str:
    """Format a spot price, choosing sensible precision for its magnitude."""
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"

    if decimals is None:
        magnitude = abs(number)
        if magnitude >= 1000:
            decimals = 2
        elif magnitude >= 1:
            decimals = 2
        elif magnitude >= 0.01:
            decimals = 4
        else:
            decimals = 6

    return f"{currency_symbol(currency)}{number:,.{decimals}f}"


def format_compact(value, currency: str = "USD") -> str:
    """Abbreviate large money values: 4.21T, 148.2B, 58.2M."""
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"

    symbol = currency_symbol(currency)
    sign = "-" if number < 0 else ""
    number = abs(number)

    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if number >= threshold:
            scaled = number / threshold
            decimals = 2 if scaled < 10 else 1
            return f"{sign}{symbol}{scaled:.{decimals}f}{suffix}"
    return f"{sign}{symbol}{number:,.2f}"


def format_supply(value, unit: str = "") -> str:
    """Abbreviate a coin supply figure (19.9M BTC)."""
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"

    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if number >= threshold:
            scaled = number / threshold
            decimals = 2 if scaled < 10 else 1
            text = f"{scaled:.{decimals}f}{suffix}"
            break
    else:
        text = f"{number:,.0f}"
    return f"{text} {unit}".strip()


def format_percent(value, decimals: int = 2, signed: bool = True) -> str:
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    sign = "+" if (signed and number > 0) else ""
    return f"{sign}{number:.{decimals}f}%"


def trend_of(value) -> int:
    """1 for up, -1 for down, 0 for flat/unknown."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number > 0:
        return 1
    if number < 0:
        return -1
    return 0


def format_clock(timestamp: float | None = None) -> str:
    if timestamp is None:
        timestamp = time.time()
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def format_age(timestamp: float | None, now: float | None = None) -> str:
    """Human-readable age of a data point: 4s, 3m, 2h, 5d."""
    if not timestamp:
        return "never"
    now = now if now is not None else time.time()
    delta = max(0, int(now - timestamp))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


def format_uptime(seconds) -> str:
    """Uptime as 3D 12H / 12H 40M / 40M."""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "--"
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}D {hours}H"
    if hours:
        return f"{hours}H {minutes}M"
    return f"{minutes}M"
