"""Provider-agnostic market data interface.

Screens never talk to CoinGecko or Binance directly. They consume the
dataclasses below, which every provider is responsible for producing.
Swapping or adding a provider therefore never touches UI code.

    MarketDataProvider
           |
           +-- CoinGeckoProvider
           +-- BinanceProvider
           +-- AlternativeMeProvider
           +-- (your provider here)

A provider that cannot serve a call raises NotSupportedError, and the
aggregator falls through to the next provider in the configured order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.utils.network import NetworkError

# Chart timeframes, in cycle order. Double-click advances through this.
TIMEFRAMES = ("1H", "4H", "1D", "1W", "1Y")


class NotSupportedError(NetworkError):
    """Raised when a provider does not implement a given capability."""


@dataclass
class PriceQuote:
    """Fast-lane spot price."""

    price: Optional[float] = None
    change_24h_pct: Optional[float] = None
    timestamp: float = 0.0


@dataclass
class BitcoinMarketData:
    """Everything the Bitcoin and Statistics pages can show.

    Any field may be None -- screens must hide missing metrics rather
    than inventing values.
    """

    price: Optional[float] = None
    change_24h_pct: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    market_cap: Optional[float] = None
    market_cap_rank: Optional[int] = None
    circulating_supply: Optional[float] = None
    max_supply: Optional[float] = None
    ath: Optional[float] = None
    ath_change_pct: Optional[float] = None
    change_7d_pct: Optional[float] = None
    change_30d_pct: Optional[float] = None
    timestamp: float = 0.0


@dataclass
class ChartSeries:
    """Historical price series for one timeframe."""

    timeframe: str = "1D"
    points: list = field(default_factory=list)  # list[tuple[float, float]] (ts, price)
    timestamp: float = 0.0

    @property
    def prices(self) -> list:
        return [price for _, price in self.points]

    @property
    def is_usable(self) -> bool:
        return len(self.points) >= 2

    @property
    def change_pct(self) -> Optional[float]:
        """Percentage move across the whole window."""
        if not self.is_usable:
            return None
        first, last = self.points[0][1], self.points[-1][1]
        if not first:
            return None
        return (last - first) / first * 100.0


@dataclass
class GlobalMarketData:
    """Whole-market aggregates for the Market Overview page."""

    total_market_cap: Optional[float] = None
    total_volume_24h: Optional[float] = None
    btc_dominance: Optional[float] = None
    eth_dominance: Optional[float] = None
    stablecoin_market_cap: Optional[float] = None
    market_cap_change_24h_pct: Optional[float] = None
    active_cryptocurrencies: Optional[int] = None
    timestamp: float = 0.0


@dataclass
class CoinSummary:
    """One row on the Top Cryptocurrencies page."""

    rank: Optional[int] = None
    symbol: str = ""
    name: str = ""
    price: Optional[float] = None
    change_24h_pct: Optional[float] = None
    market_cap: Optional[float] = None


@dataclass
class FearGreedIndex:
    value: Optional[int] = None
    classification: str = ""
    timestamp: float = 0.0


class MarketDataProvider:
    """Interface every provider implements.

    Default implementations raise NotSupportedError so a provider only
    needs to override the calls it can actually serve.
    """

    name = "base"

    def __init__(self, settings, http):
        self.settings = settings
        self.http = http

    # --- capabilities -------------------------------------------------
    def get_bitcoin_price(self) -> PriceQuote:
        raise NotSupportedError(f"{self.name} cannot serve get_bitcoin_price")

    def get_bitcoin_market_data(self) -> BitcoinMarketData:
        raise NotSupportedError(f"{self.name} cannot serve get_bitcoin_market_data")

    def get_bitcoin_chart(self, timeframe: str) -> ChartSeries:
        raise NotSupportedError(f"{self.name} cannot serve get_bitcoin_chart")

    def get_global_market_data(self) -> GlobalMarketData:
        raise NotSupportedError(f"{self.name} cannot serve get_global_market_data")

    def get_top_cryptocurrencies(self, limit: int = 5) -> list:
        raise NotSupportedError(f"{self.name} cannot serve get_top_cryptocurrencies")

    def get_fear_greed_index(self) -> FearGreedIndex:
        raise NotSupportedError(f"{self.name} cannot serve get_fear_greed_index")


# Populated by app.market.registry to avoid import cycles.
PROVIDER_REGISTRY: dict = {}


def register_provider(cls):
    """Class decorator that adds a provider to the registry."""
    PROVIDER_REGISTRY[cls.name] = cls
    return cls


def downsample(points: list, max_points: int = 240) -> list:
    """Evenly thin a series so the renderer never walks huge lists.

    The chart is ~230 px wide, so more than a few hundred points costs
    CPU without adding a single visible pixel. First and last points are
    always preserved so the window boundaries stay accurate.
    """
    if max_points < 2 or len(points) <= max_points:
        return points
    step = len(points) / float(max_points)
    thinned = [points[int(i * step)] for i in range(max_points)]
    if thinned[-1] != points[-1]:
        thinned[-1] = points[-1]
    return thinned
