"""Fear & Greed Index from alternative.me (free, no key)."""

from __future__ import annotations

import time

from app.market.provider import (
    FearGreedIndex,
    MarketDataProvider,
    register_provider,
)
from app.utils.logger import get_logger
from app.utils.network import NetworkError

log = get_logger("alternative_me")

_ENDPOINT = "https://api.alternative.me/fng/"


@register_provider
class AlternativeMeProvider(MarketDataProvider):
    name = "alternative_me"

    def get_fear_greed_index(self) -> FearGreedIndex:
        payload = self.http.get_json(_ENDPOINT, params={"limit": 1, "format": "json"})
        entries = (payload or {}).get("data")
        if not isinstance(entries, list) or not entries:
            raise NetworkError("alternative.me: empty fear/greed payload")

        entry = entries[0]
        try:
            value = int(entry.get("value"))
        except (TypeError, ValueError):
            raise NetworkError("alternative.me: invalid index value")

        return FearGreedIndex(
            value=value,
            classification=str(entry.get("value_classification", "")).upper(),
            timestamp=time.time(),
        )
