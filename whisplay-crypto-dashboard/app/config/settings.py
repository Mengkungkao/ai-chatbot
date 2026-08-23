"""Configuration loading.

Precedence, lowest to highest:
    built-in defaults  <  config.yaml  <  environment variables

Secrets never live in YAML -- they come from the environment (.env).
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

try:  # python-dotenv is optional; the app still runs without it.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - trivial fallback
    def load_dotenv(*_args, **_kwargs):
        return False


PROJECT_ROOT = Path(__file__).resolve().parents[2]

TIMEFRAMES = ("1H", "4H", "1D", "1W", "1Y")

DEFAULTS: dict[str, Any] = {
    "bitcoin": {"symbol": "BTC", "currency": "USD", "default_timeframe": "1D"},
    "refresh": {
        "price_seconds": 10,
        "market_seconds": 60,
        "chart_seconds": 60,
        "global_seconds": 90,
        "top_seconds": 120,
        "fear_greed_seconds": 900,
        "system_seconds": 5,
    },
    "button": {"debounce_ms": 75, "click_window_ms": 400, "long_press_ms": 700},
    "display": {
        "brightness": 80,
        "fps": 20,
        "status_tick_seconds": 20,
        "led_enabled": True,
    },
    "providers": {
        "price": ["binance", "coingecko"],
        "chart": ["binance", "coingecko"],
        "market": ["coingecko"],
        "global": ["coingecko"],
        "top": ["coingecko"],
        "fear_greed": ["alternative_me"],
        "top_count": 5,
    },
    "network": {
        "timeout_seconds": 8,
        "backoff_seconds": [5, 10, 30, 60, 120],
        "offline_after_failures": 2,
        "user_agent": "whisplay-crypto-dashboard/1.0",
    },
    "system": {
        "cache_enabled": True,
        "cache_path": "~/.whisplay-crypto/cache.json",
        "state_path": "~/.whisplay-crypto/state.json",
    },
    "logging": {
        "path": "/var/log/whisplay-crypto/app.log",
        "level": "INFO",
        "max_bytes": 524288,
        "backup_count": 3,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into a copy of ``base``."""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _as_list(value: Any) -> list[str]:
    """Providers may be given as a scalar or a list; normalise to a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


class Settings:
    """Immutable-ish view over merged configuration."""

    def __init__(self, data: dict[str, Any], config_path: Path | None = None):
        self._data = data
        self.config_path = config_path

        self.symbol: str = str(data["bitcoin"]["symbol"]).upper()
        self.currency: str = str(data["bitcoin"]["currency"]).upper()

        timeframe = str(data["bitcoin"]["default_timeframe"]).upper()
        self.default_timeframe: str = timeframe if timeframe in TIMEFRAMES else "1D"

        self.refresh: dict[str, float] = {
            key: float(value) for key, value in data["refresh"].items()
        }
        self.button: dict[str, int] = {
            key: int(value) for key, value in data["button"].items()
        }

        display = data["display"]
        self.brightness: int = max(0, min(100, int(display["brightness"])))
        self.fps: int = max(1, min(30, int(display["fps"])))
        self.status_tick_seconds: float = float(display["status_tick_seconds"])
        self.led_enabled: bool = bool(display["led_enabled"])

        providers = data["providers"]
        self.provider_order: dict[str, list[str]] = {
            key: _as_list(providers.get(key))
            for key in ("price", "chart", "market", "global", "top", "fear_greed")
        }
        self.top_count: int = max(1, min(10, int(providers.get("top_count", 5))))

        network = data["network"]
        self.timeout_seconds: float = float(network["timeout_seconds"])
        self.backoff_seconds: list[float] = [
            float(v) for v in network["backoff_seconds"]
        ] or [5.0]
        self.offline_after_failures: int = max(
            1, int(network.get("offline_after_failures", 2))
        )
        self.user_agent: str = str(network["user_agent"])

        system = data["system"]
        self.cache_enabled: bool = bool(system["cache_enabled"])
        self.cache_path: Path = Path(str(system["cache_path"])).expanduser()
        self.state_path: Path = Path(str(system["state_path"])).expanduser()

        logging_cfg = data["logging"]
        self.log_path: Path = Path(str(logging_cfg["path"])).expanduser()
        self.log_level: str = str(logging_cfg["level"]).upper()
        self.log_max_bytes: int = int(logging_cfg["max_bytes"])
        self.log_backup_count: int = int(logging_cfg["backup_count"])

        # Secrets come from the environment only -- never from config.yaml.
        self.coingecko_api_key: str = os.getenv("COINGECKO_API_KEY", "").strip()
        self.coingecko_api_base: str = os.getenv(
            "COINGECKO_API_BASE", "https://api.coingecko.com/api/v3"
        ).rstrip("/")
        self.binance_api_base: str = os.getenv(
            "BINANCE_API_BASE", "https://api.binance.com"
        ).rstrip("/")
        self.coinmarketcap_api_key: str = os.getenv("COINMARKETCAP_API_KEY", "").strip()

    @property
    def raw(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    @property
    def pair_label(self) -> str:
        return f"{self.symbol}/{self.currency}"


def load_settings(config_path: str | os.PathLike | None = None) -> Settings:
    """Load .env then config.yaml, merged over the built-in defaults."""
    load_dotenv(PROJECT_ROOT / ".env")

    if config_path is None:
        config_path = os.getenv(
            "WHISPLAY_CRYPTO_CONFIG", str(PROJECT_ROOT / "config.yaml")
        )
    path = Path(config_path).expanduser()

    file_data: dict[str, Any] = {}
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            file_data = yaml.safe_load(handle) or {}
        if not isinstance(file_data, dict):
            file_data = {}

    return Settings(_deep_merge(DEFAULTS, file_data), path if path.is_file() else None)
