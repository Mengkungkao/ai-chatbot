import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.config.settings import Settings, DEFAULTS, _deep_merge


@pytest.fixture
def settings():
    return Settings(_deep_merge(DEFAULTS, {}))


@pytest.fixture
def sample_snapshot():
    """A fully populated snapshot matching the figures in the brief."""
    import math
    import time

    from app.market.provider import (
        BitcoinMarketData, ChartSeries, CoinSummary, FearGreedIndex,
        GlobalMarketData, PriceQuote,
    )
    from app.market.service import MarketSnapshot

    now = time.time()
    points = [(now - (96 - i) * 900, 112540 + 900 * math.sin(i / 11.0)) for i in range(96)]
    return MarketSnapshot(
        price=PriceQuote(112540.32, 2.41, now),
        market=BitcoinMarketData(
            price=112540.32, change_24h_pct=2.41, high_24h=114820.0,
            low_24h=108420.0, volume_24h=58.2e9, market_cap=2.24e12,
            market_cap_rank=1, circulating_supply=19_900_000,
            max_supply=21_000_000, ath=126080.0, ath_change_pct=-10.7,
            change_7d_pct=5.4, change_30d_pct=-3.1, timestamp=now,
        ),
        chart=ChartSeries("1D", points, now),
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
        ],
        fear_greed=FearGreedIndex(72, "GREED", now),
        timeframe="1D", online=True, last_success=now,
    )
