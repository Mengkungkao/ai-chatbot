"""Binance public market data.

No API key, generous rate limits, and sub-second freshness -- which
makes it the default for the fast price lane and for chart candles.
Binance has no notion of market cap or supply, so those calls fall
through to CoinGecko via the aggregator.
"""

from __future__ import annotations

import time

from app.market.provider import (
    ChartSeries,
    MarketDataProvider,
    NotSupportedError,
    PriceQuote,
    BitcoinMarketData,
    downsample,
    register_provider,
)
from app.utils.logger import get_logger
from app.utils.network import NetworkError

log = get_logger("binance")

# Binance quotes crypto against stablecoins, not fiat.
_QUOTE_FOR_FIAT = {"USD": "USDT", "EUR": "EUR", "GBP": "GBP", "AUD": "AUD"}

# timeframe -> (kline interval, number of candles)
_KLINE_PLAN = {
    "1H": ("1m", 60),
    "4H": ("5m", 48),
    "1D": ("15m", 96),
    "1W": ("1h", 168),
    "1Y": ("1d", 365),
}


@register_provider
class BinanceProvider(MarketDataProvider):
    name = "binance"

    @property
    def _symbol(self) -> str:
        quote = _QUOTE_FOR_FIAT.get(self.settings.currency, "USDT")
        return f"{self.settings.symbol}{quote}"

    def _get(self, path: str, params: dict | None = None):
        return self.http.get_json(f"{self.settings.binance_api_base}{path}", params=params)

    def _ticker_24hr(self) -> dict:
        data = self._get("/api/v3/ticker/24hr", {"symbol": self._symbol})
        if not isinstance(data, dict) or "lastPrice" not in data:
            raise NetworkError("binance: unexpected ticker payload")
        return data

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def get_bitcoin_price(self) -> PriceQuote:
        data = self._ticker_24hr()
        return PriceQuote(
            price=self._to_float(data.get("lastPrice")),
            change_24h_pct=self._to_float(data.get("priceChangePercent")),
            timestamp=time.time(),
        )

    def get_bitcoin_market_data(self) -> BitcoinMarketData:
        """Partial data: Binance knows the tape, not the supply.

        The aggregator merges this with CoinGecko's market-cap fields, so
        returning a partially populated record is intentional and useful.
        """
        data = self._ticker_24hr()
        return BitcoinMarketData(
            price=self._to_float(data.get("lastPrice")),
            change_24h_pct=self._to_float(data.get("priceChangePercent")),
            high_24h=self._to_float(data.get("highPrice")),
            low_24h=self._to_float(data.get("lowPrice")),
            volume_24h=self._to_float(data.get("quoteVolume")),
            timestamp=time.time(),
        )

    def get_bitcoin_chart(self, timeframe: str) -> ChartSeries:
        plan = _KLINE_PLAN.get(str(timeframe).upper())
        if plan is None:
            raise NotSupportedError(f"binance: unknown timeframe {timeframe}")
        interval, limit = plan

        rows = self._get(
            "/api/v3/klines",
            {"symbol": self._symbol, "interval": interval, "limit": limit},
        )
        if not isinstance(rows, list) or not rows:
            raise NetworkError("binance: empty kline payload")

        points = []
        for row in rows:
            try:
                # [open_time, open, high, low, close, volume, close_time, ...]
                points.append((float(row[6]) / 1000.0, float(row[4])))
            except (TypeError, ValueError, IndexError):
                continue
        if len(points) < 2:
            raise NetworkError("binance: not enough kline points")

        return ChartSeries(
            timeframe=str(timeframe).upper(),
            points=downsample(points),
            timestamp=time.time(),
        )
