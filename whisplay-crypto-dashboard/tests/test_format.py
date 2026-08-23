"""Formatting must never mislead: no fake precision, no fake data."""

from app.utils.format import (
    format_age, format_compact, format_percent, format_price,
    format_supply, format_uptime, trend_of,
)


def test_price_matches_brief():
    assert format_price(112540.32) == "$112,540.32"


def test_price_precision_scales_with_magnitude():
    assert format_price(1.0003) == "$1.00"
    assert format_price(0.0234) == "$0.0234"
    assert format_price(0.00001234) == "$0.000012"


def test_missing_values_render_as_dashes_not_zero():
    # Showing 0.00 for absent data would be a lie; "--" is honest.
    assert format_price(None) == "--"
    assert format_compact(None) == "--"
    assert format_percent(None) == "--"
    assert format_supply(None) == "--"
    assert format_price("not-a-number") == "--"


def test_compact_money():
    assert format_compact(4.21e12) == "$4.21T"
    assert format_compact(148.2e9) == "$148.2B"
    assert format_compact(58.2e6) == "$58.2M"
    assert format_compact(-1.5e9) == "-$1.50B"


def test_percent_is_signed_for_gains_only():
    assert format_percent(2.41) == "+2.41%"
    assert format_percent(-0.43) == "-0.43%"
    assert format_percent(57.4, 1, signed=False) == "57.4%"


def test_supply():
    assert format_supply(19_900_000, "BTC") == "19.9M BTC"
    assert format_supply(21_000_000, "BTC") == "21.0M BTC"


def test_uptime():
    assert format_uptime(3 * 86400 + 12 * 3600) == "3D 12H"
    assert format_uptime(12 * 3600 + 40 * 60) == "12H 40M"
    assert format_uptime(40 * 60) == "40M"


def test_age():
    assert format_age(None) == "never"
    assert format_age(1000.0, now=1045.0) == "45s"
    assert format_age(1000.0, now=1000.0 + 3 * 3600) == "3h"


def test_trend():
    assert trend_of(1.2) == 1
    assert trend_of(-1.2) == -1
    assert trend_of(0) == 0
    assert trend_of(None) == 0
