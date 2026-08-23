#!/usr/bin/env python3
"""Render every screen to PNG without Whisplay hardware.

Useful for design iteration on a laptop and for verifying a layout
change before deploying to the Pi.

    python3 tools/preview.py --out /tmp/preview          # live API data
    python3 tools/preview.py --mock --out /tmp/preview   # fixed sample data
    python3 tools/preview.py --mock --offline            # offline styling
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import load_settings
from app.market.cache import MarketCache
from app.market.provider import (
    BitcoinMarketData,
    ChartSeries,
    CoinSummary,
    FearGreedIndex,
    GlobalMarketData,
    PriceQuote,
)
from app.market.service import MarketService, MarketSnapshot
from app.ui import theme
from app.ui.base import RenderContext
from app.ui.bitcoin_screen import BitcoinScreen
from app.ui.crypto_screen import CryptoScreen
from app.ui.market_screen import MarketScreen
from app.ui.statistics_screen import StatisticsScreen
from app.ui.system_screen import SystemScreen
from app.utils.logger import setup_logging
from app.utils.system import SystemMonitor

SCREENS = [
    ("1-bitcoin", BitcoinScreen()),
    ("2-market", MarketScreen()),
    ("3-top", CryptoScreen()),
    ("4-statistics", StatisticsScreen()),
    ("5-system", SystemScreen()),
]


def mock_snapshot(timeframe: str = "1D", online: bool = True) -> MarketSnapshot:
    """Deterministic data matching the figures in the project brief."""
    import math

    now = time.time()
    points = [
        (now - (96 - i) * 900, 112540 + 900 * math.sin(i / 11.0) + i * 12)
        for i in range(96)
    ]
    return MarketSnapshot(
        price=PriceQuote(112540.32, 2.41, now),
        market=BitcoinMarketData(
            price=112540.32, change_24h_pct=2.41, high_24h=114820.0,
            low_24h=108420.0, volume_24h=58.2e9, market_cap=2.24e12,
            market_cap_rank=1, circulating_supply=19_900_000,
            max_supply=21_000_000, ath=126080.0, ath_change_pct=-10.7,
            change_7d_pct=5.4, change_30d_pct=-3.1, timestamp=now,
        ),
        chart=ChartSeries(timeframe, points, now),
        global_data=GlobalMarketData(
            total_market_cap=4.21e12, total_volume_24h=148.2e9,
            btc_dominance=57.4, eth_dominance=12.9,
            stablecoin_market_cap=241.0e9, market_cap_change_24h_pct=1.82,
            active_cryptocurrencies=13500, timestamp=now,
        ),
        top=[
            CoinSummary(1, "BTC", "Bitcoin", 112540.32, 2.41, 2.24e12),
            CoinSummary(2, "ETH", "Ethereum", 4280.11, 1.84, 515e9),
            CoinSummary(3, "USDT", "Tether", 1.0003, 0.01, 140e9),
            CoinSummary(4, "BNB", "BNB", 812.44, 0.72, 118e9),
            CoinSummary(5, "XRP", "XRP", 2.91, -0.43, 165e9),
        ],
        fear_greed=FearGreedIndex(72, "GREED", now),
        timeframe=timeframe,
        online=online,
        last_success=now - (0 if online else 420),
        last_error="" if online else "timeout: api.binance.com",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/whisplay-preview")
    parser.add_argument("--mock", action="store_true", help="use sample data")
    parser.add_argument("--offline", action="store_true", help="render offline state")
    parser.add_argument("--timeframe", default="1D")
    parser.add_argument("--wait", type=float, default=14.0,
                        help="seconds to let live data load")
    args = parser.parse_args()

    settings = load_settings()
    setup_logging(settings)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    service = None
    if args.mock:
        snapshot = mock_snapshot(args.timeframe, online=not args.offline)
    else:
        cache = MarketCache(settings.cache_path, settings.cache_enabled, 0)
        service = MarketService(settings, cache)
        service.set_timeframe(args.timeframe)
        service.start()
        print(f"fetching live data ({args.wait:.0f}s)...")
        time.sleep(args.wait)
        snapshot = service.snapshot()

    monitor = SystemMonitor(0)
    monitor.sample(force=True)
    time.sleep(0.3)

    ctx = RenderContext(
        snapshot=snapshot,
        settings=settings,
        system=monitor.sample(force=True),
        connectivity={"wifi": True, "internet": not args.offline},
        now=time.time(),
        page_count=len(SCREENS),
        board_mode="preview",
    )

    from PIL import Image, ImageDraw

    for index, (name, screen) in enumerate(SCREENS):
        ctx.page_index = index
        image = Image.new("RGB", (theme.SCREEN_WIDTH, theme.SCREEN_HEIGHT), theme.BG)
        draw = ImageDraw.Draw(image)
        screen.render(draw, ctx)
        path = out_dir / f"{name}.png"
        image.save(path)
        print(f"  wrote {path}")

    if service:
        service.stop()

    # Contact sheet: all five screens side by side.
    sheet = Image.new(
        "RGB",
        (theme.SCREEN_WIDTH * len(SCREENS) + 8 * (len(SCREENS) + 1),
         theme.SCREEN_HEIGHT + 16),
        (24, 26, 34),
    )
    for index, (name, _) in enumerate(SCREENS):
        tile = Image.open(out_dir / f"{name}.png")
        sheet.paste(tile, (8 + index * (theme.SCREEN_WIDTH + 8), 8))
    sheet.save(out_dir / "all-screens.png")
    print(f"  wrote {out_dir / 'all-screens.png'}")


if __name__ == "__main__":
    main()
