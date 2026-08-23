"""Persistent cache and app state.

Two jobs:

* Keep the last good market data so a boot without Internet still shows
  something useful (clearly marked stale, never presented as live).
* Remember the selected chart timeframe across restarts.

Both write atomically and are throttled, because this runs 24/7 on an
SD card that does not enjoy being written to every ten seconds.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

from app.market.provider import (
    BitcoinMarketData,
    ChartSeries,
    CoinSummary,
    FearGreedIndex,
    GlobalMarketData,
    PriceQuote,
)
from app.utils.logger import get_logger

log = get_logger("cache")

# Cached entry name -> dataclass used to rebuild it.
_ENTRY_TYPES = {
    "price": PriceQuote,
    "market": BitcoinMarketData,
    "global": GlobalMarketData,
    "fear_greed": FearGreedIndex,
}


def _atomic_write_json(path: Path, payload: dict) -> bool:
    """Write via temp file + rename so a power cut cannot corrupt it."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
        return True
    except (OSError, TypeError, ValueError) as exc:
        log.warning("failed to write %s: %s", path, exc)
        return False


def _read_json(path: Path) -> dict:
    try:
        if not path.is_file():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        log.warning("failed to read %s: %s", path, exc)
        return {}


class MarketCache:
    """Last-known-good market data, persisted to disk."""

    def __init__(self, path: Path, enabled: bool = True, min_write_interval: float = 30.0):
        self.path = Path(path)
        self.enabled = enabled
        self.min_write_interval = min_write_interval
        self._lock = threading.Lock()
        self._data: dict = {}
        self._dirty = False
        self._last_write = 0.0
        if self.enabled:
            self._load()

    def _load(self):
        raw = _read_json(self.path)
        if raw:
            self._data = raw
            log.info("loaded cache with %d entries from %s", len(raw), self.path)

    def set(self, key: str, value):
        """Store a dataclass (or list of them) under ``key``."""
        if not self.enabled:
            return
        if isinstance(value, list):
            payload = [asdict(item) if is_dataclass(item) else item for item in value]
        elif is_dataclass(value):
            payload = asdict(value)
        else:
            payload = value
        with self._lock:
            self._data[key] = payload
            self._dirty = True

    def get(self, key: str, default=None):
        """Rebuild a cached entry into its dataclass, or return default."""
        with self._lock:
            raw = self._data.get(key)
        if raw is None:
            return default

        try:
            if key == "top" and isinstance(raw, list):
                return [CoinSummary(**item) for item in raw]
            if key.startswith("chart:") and isinstance(raw, dict):
                series = ChartSeries(**raw)
                series.points = [tuple(point) for point in series.points]
                return series
            entry_type = _ENTRY_TYPES.get(key)
            if entry_type and isinstance(raw, dict):
                return entry_type(**raw)
        except (TypeError, ValueError) as exc:
            # A schema change between versions must not crash the app.
            log.warning("discarding incompatible cache entry %s: %s", key, exc)
            return default
        return default

    def flush(self, force: bool = False):
        """Persist if dirty and the write throttle allows it."""
        if not self.enabled:
            return
        with self._lock:
            if not self._dirty:
                return
            now = time.monotonic()
            if not force and (now - self._last_write) < self.min_write_interval:
                return
            snapshot = dict(self._data)
            self._last_write = now
            self._dirty = False
        _atomic_write_json(self.path, snapshot)


class AppState:
    """Small persisted UI state (currently the chart timeframe)."""

    def __init__(self, path: Path, defaults: dict | None = None):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = dict(defaults or {})
        self._data.update(_read_json(self.path))

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value) -> bool:
        """Set and persist immediately. Returns True when it changed."""
        with self._lock:
            if self._data.get(key) == value:
                return False
            self._data[key] = value
            snapshot = dict(self._data)
        _atomic_write_json(self.path, snapshot)
        return True
