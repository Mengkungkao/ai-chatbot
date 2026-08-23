"""Provider registry.

Importing this module is what populates PROVIDER_REGISTRY. Adding a new
provider means dropping a module next to these and importing it here --
no other file changes.
"""

from __future__ import annotations

from app.market import alternative_me, binance, coingecko  # noqa: F401
from app.market.provider import PROVIDER_REGISTRY
from app.utils.logger import get_logger

log = get_logger("registry")


def build_providers(names, settings, http) -> dict:
    """Instantiate each named provider once, sharing the HTTP client."""
    instances = {}
    for name in names:
        cls = PROVIDER_REGISTRY.get(name)
        if cls is None:
            log.warning("unknown provider in config, ignoring: %s", name)
            continue
        if name not in instances:
            instances[name] = cls(settings, http)
    return instances


def available_providers() -> list:
    return sorted(PROVIDER_REGISTRY)
