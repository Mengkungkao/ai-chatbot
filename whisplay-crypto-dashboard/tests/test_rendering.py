"""Screens must render without exceptions for every data condition.

A dashboard that runs 24/7 will eventually meet every one of these
states, and none of them may take the device down.
"""

import time

import pytest
from PIL import Image, ImageDraw

from app.chart.renderer import render_chart, render_sparkline
from app.market.provider import ChartSeries, CoinSummary
from app.market.service import MarketSnapshot
from app.ui import theme
from app.ui.base import RenderContext
from app.ui.bitcoin_screen import BitcoinScreen
from app.ui.crypto_screen import CryptoScreen
from app.ui.display import image_to_rgb565
from app.ui.market_screen import MarketScreen
from app.ui.statistics_screen import StatisticsScreen
from app.ui.system_screen import SystemScreen

ALL_SCREENS = [
    BitcoinScreen(), MarketScreen(), CryptoScreen(),
    StatisticsScreen(), SystemScreen(),
]


def make_ctx(settings, snapshot=None, **overrides):
    base = dict(
        snapshot=snapshot if snapshot is not None else MarketSnapshot(),
        settings=settings,
        system={},
        connectivity={},
        now=time.time(),
        board_mode="test",
    )
    base.update(overrides)
    return RenderContext(**base)


def render(screen, ctx):
    image = Image.new("RGB", (theme.SCREEN_WIDTH, theme.SCREEN_HEIGHT), theme.BG)
    screen.render(ImageDraw.Draw(image), ctx)
    return image


@pytest.mark.parametrize("screen", ALL_SCREENS, ids=lambda s: s.name)
def test_renders_with_no_data_at_all(settings, screen):
    """Cold boot with no network: every page must still paint."""
    render(screen, make_ctx(settings))


@pytest.mark.parametrize("screen", ALL_SCREENS, ids=lambda s: s.name)
def test_renders_offline_with_stale_data(settings, screen, sample_snapshot):
    sample_snapshot.online = False
    sample_snapshot.last_success = time.time() - 3600
    sample_snapshot.last_error = "timeout: api.binance.com"
    render(screen, make_ctx(settings, sample_snapshot))


@pytest.mark.parametrize("screen", ALL_SCREENS, ids=lambda s: s.name)
def test_renders_with_full_live_data(settings, screen, sample_snapshot):
    render(screen, make_ctx(settings, sample_snapshot))


@pytest.mark.parametrize("screen", ALL_SCREENS, ids=lambda s: s.name)
def test_renders_with_partial_data(settings, screen, sample_snapshot):
    """Provider returned some fields but not others -- must not crash."""
    sample_snapshot.market.market_cap = None
    sample_snapshot.market.circulating_supply = None
    sample_snapshot.market.ath = None
    sample_snapshot.global_data.btc_dominance = None
    sample_snapshot.global_data.total_market_cap = None
    sample_snapshot.fear_greed.value = None
    sample_snapshot.chart = ChartSeries("1D", [])
    render(screen, make_ctx(settings, sample_snapshot))


def test_output_is_exactly_one_framebuffer(settings, sample_snapshot):
    """The daemon contract: 240x280 RGB565 = 134,400 bytes."""
    image = render(BitcoinScreen(), make_ctx(settings, sample_snapshot))
    assert image.size == (240, 280)
    assert len(image_to_rgb565(image)) == 240 * 280 * 2


def test_rgb565_encoding_is_big_endian():
    image = Image.new("RGB", (1, 1), (255, 0, 0))
    assert image_to_rgb565(image) == b"\xf8\x00"
    image = Image.new("RGB", (1, 1), (0, 0, 255))
    assert image_to_rgb565(image) == b"\x00\x1f"


def test_screens_never_render_a_missing_metric_as_zero(settings, sample_snapshot):
    """A blank field is honest; a fabricated 0 is not."""
    sample_snapshot.market.market_cap = None
    image = render(StatisticsScreen(), make_ctx(settings, sample_snapshot))
    stats = StatisticsScreen()._collect(sample_snapshot.market, settings)
    labels = [label for label, _, _ in stats]
    assert "MARKET CAP" not in labels
    assert image is not None


def test_top_screen_clamps_to_the_visible_row_count(settings, sample_snapshot):
    sample_snapshot.top = [
        CoinSummary(i, f"C{i}", f"Coin {i}", 1.0 * i, 0.5, 1e9) for i in range(1, 21)
    ]
    render(CryptoScreen(), make_ctx(settings, sample_snapshot))


# --- chart ---------------------------------------------------------------
def test_chart_draws_with_real_series():
    image = Image.new("RGB", (240, 280), theme.BG)
    points = [(float(i), 112000.0 + i) for i in range(96)]
    assert render_chart(ImageDraw.Draw(image), ChartSeries("1D", points), (0, 90, 236, 205))


def test_chart_placeholder_when_empty():
    image = Image.new("RGB", (240, 280), theme.BG)
    draw = ImageDraw.Draw(image)
    assert render_chart(draw, ChartSeries("1D", []), (0, 90, 236, 205)) is False
    assert render_chart(draw, None, (0, 90, 236, 205)) is False


def test_flat_series_does_not_divide_by_zero():
    """Every price identical -- a real case for stablecoins."""
    image = Image.new("RGB", (240, 280), theme.BG)
    points = [(float(i), 1.0) for i in range(50)]
    assert render_chart(ImageDraw.Draw(image), ChartSeries("1D", points), (0, 90, 236, 205))


def test_two_point_series_is_enough():
    image = Image.new("RGB", (240, 280), theme.BG)
    points = [(0.0, 100.0), (1.0, 101.0)]
    assert render_chart(ImageDraw.Draw(image), ChartSeries("1H", points), (0, 90, 236, 205))


def test_sparkline():
    image = Image.new("RGB", (240, 280), theme.BG)
    points = [(float(i), 100.0 + i) for i in range(30)]
    assert render_sparkline(ImageDraw.Draw(image), ChartSeries("1D", points), (0, 0, 60, 20))
    assert render_sparkline(ImageDraw.Draw(image), ChartSeries("1D", []), (0, 0, 60, 20)) is False
