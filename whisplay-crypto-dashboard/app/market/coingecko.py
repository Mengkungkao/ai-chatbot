"""CoinGecko market data.

Covers everything exchange tickers cannot: market capitalisation,
circulating supply, all-time highs, dominance and the top-coins table.
Works without a key on the public API; a demo or pro key simply raises
the rate limit and is read from the environment.
"""

from __future__ import annotations

import time

from app.market.provider import (
    BitcoinMarketData,
    ChartSeries,
    CoinSummary,
    GlobalMarketData,
    MarketDataProvider,
    NotSupportedError,
    PriceQuote,
    downsample,
    register_provider,
)
from app.utils.logger import get_logger
from app.utils.network import NetworkError

log = get_logger("coingecko")

# CoinGecko addresses coins by id, not ticker.
_COIN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "USDC": "usd-coin",
}

# Assets counted toward the stablecoin aggregate on the Market page.
_STABLECOIN_KEYS = ("usdt", "usdc", "dai", "busd", "tusd", "fdusd")

# timeframe -> (days requested, seconds of history to keep)
_CHART_PLAN = {
    "1H": (1, 3600),
    "4H": (1, 4 * 3600),
    "1D": (1, 24 * 3600),
    "1W": (7, 7 * 24 * 3600),
    "1Y": (365, 365 * 24 * 3600),
}


@register_provider
class CoinGeckoProvider(MarketDataProvider):
    name = "coingecko"

    @property
    def _coin_id(self) -> str:
        return _COIN_IDS.get(self.settings.symbol, self.settings.symbol.lower())

    @property
    def _vs(self) -> str:
        return self.settings.currency.lower()

    def _headers(self) -> dict:
        """Attach the key only when one is configured. Never logged."""
        key = self.settings.coingecko_api_key
        if not key:
            return {}
        header = (
            "x-cg-pro-api-key"
            if "pro-api" in self.settings.coingecko_api_base
            else "x-cg-demo-api-key"
        )
        return {header: key}

    def _get(self, path: str, params: dict | None = None):
        return self.http.get_json(
            f"{self.settings.coingecko_api_base}{path}",
            params=params,
            headers=self._headers(),
        )

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def get_bitcoin_price(self) -> PriceQuote:
        data = self._get(
            "/simple/price",
            {
                "ids": self._coin_id,
                "vs_currencies": self._vs,
                "include_24hr_change": "true",
            },
        )
        entry = (data or {}).get(self._coin_id)
        if not isinstance(entry, dict):
            raise NetworkError("coingecko: missing price entry")
        return PriceQuote(
            price=self._to_float(entry.get(self._vs)),
            change_24h_pct=self._to_float(entry.get(f"{self._vs}_24h_change")),
            timestamp=time.time(),
        )

    def _markets_row(self, ids: str, per_page: int = 1, page: int = 1) -> list:
        rows = self._get(
            "/coins/markets",
            {
                "vs_currency": self._vs,
                "ids": ids or None,
                "order": "market_cap_desc",
                "per_page": per_page,
                "page": page,
                "sparkline": "false",
                "price_change_percentage": "24h,7d,30d",
            },
        )
        if not isinstance(rows, list):
            raise NetworkError("coingecko: unexpected markets payload")
        return rows

    def get_bitcoin_market_data(self) -> BitcoinMarketData:
        rows = self._markets_row(self._coin_id)
        if not rows:
            raise NetworkError("coingecko: no market row for coin")
        row = rows[0]
        return BitcoinMarketData(
            price=self._to_float(row.get("current_price")),
            change_24h_pct=self._to_float(row.get("price_change_percentage_24h")),
            high_24h=self._to_float(row.get("high_24h")),
            low_24h=self._to_float(row.get("low_24h")),
            volume_24h=self._to_float(row.get("total_volume")),
            market_cap=self._to_float(row.get("market_cap")),
            market_cap_rank=self._to_int(row.get("market_cap_rank")),
            circulating_supply=self._to_float(row.get("circulating_supply")),
            max_supply=self._to_float(row.get("max_supply")),
            ath=self._to_float(row.get("ath")),
            ath_change_pct=self._to_float(row.get("ath_change_percentage")),
            change_7d_pct=self._to_float(
                row.get("price_change_percentage_7d_in_currency")
            ),
            change_30d_pct=self._to_float(
                row.get("price_change_percentage_30d_in_currency")
            ),
            timestamp=time.time(),
        )

    def get_bitcoin_chart(self, timeframe: str) -> ChartSeries:
        key = str(timeframe).upper()
        plan = _CHART_PLAN.get(key)
        if plan is None:
            raise NotSupportedError(f"coingecko: unknown timeframe {timeframe}")
        days, window_seconds = plan

        data = self._get(
            f"/coins/{self._coin_id}/market_chart",
            {"vs_currency": self._vs, "days": days},
        )
        raw = (data or {}).get("prices")
        if not isinstance(raw, list) or len(raw) < 2:
            raise NetworkError("coingecko: empty chart payload")

        points = []
        for item in raw:
            try:
                points.append((float(item[0]) / 1000.0, float(item[1])))
            except (TypeError, ValueError, IndexError):
                continue
        if len(points) < 2:
            raise NetworkError("coingecko: not enough chart points")

        # CoinGecko's granularity is fixed per days value, so short
        # timeframes are produced by trimming the tail of a 1-day series.
        cutoff = points[-1][0] - window_seconds
        trimmed = [point for point in points if point[0] >= cutoff]
        if len(trimmed) >= 2:
            points = trimmed

        return ChartSeries(
            timeframe=key, points=downsample(points), timestamp=time.time()
        )

    def get_global_market_data(self) -> GlobalMarketData:
        payload = (self._get("/global") or {}).get("data")
        if not isinstance(payload, dict):
            raise NetworkError("coingecko: unexpected global payload")

        vs = self._vs
        total_cap = self._to_float((payload.get("total_market_cap") or {}).get(vs))
        dominance = payload.get("market_cap_percentage") or {}

        # Derived from real dominance figures rather than guessed.
        stablecoin_cap = None
        if total_cap is not None:
            share = sum(
                self._to_float(dominance.get(key)) or 0.0 for key in _STABLECOIN_KEYS
            )
            if share > 0:
                stablecoin_cap = total_cap * share / 100.0

        return GlobalMarketData(
            total_market_cap=total_cap,
            total_volume_24h=self._to_float((payload.get("total_volume") or {}).get(vs)),
            btc_dominance=self._to_float(dominance.get("btc")),
            eth_dominance=self._to_float(dominance.get("eth")),
            stablecoin_market_cap=stablecoin_cap,
            market_cap_change_24h_pct=self._to_float(
                payload.get("market_cap_change_percentage_24h_usd")
            ),
            active_cryptocurrencies=self._to_int(payload.get("active_cryptocurrencies")),
            timestamp=time.time(),
        )

    def get_top_cryptocurrencies(self, limit: int = 5) -> list:
        rows = self._markets_row("", per_page=max(1, min(int(limit), 50)))
        if not rows:
            raise NetworkError("coingecko: empty top-coins payload")

        coins = []
        for row in rows:
            coins.append(
                CoinSummary(
                    rank=self._to_int(row.get("market_cap_rank")),
                    symbol=str(row.get("symbol", "")).upper(),
                    name=str(row.get("name", "")),
                    price=self._to_float(row.get("current_price")),
                    change_24h_pct=self._to_float(
                        row.get("price_change_percentage_24h")
                    ),
                    market_cap=self._to_float(row.get("market_cap")),
                )
            )
        return coins
