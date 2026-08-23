"""Market data service: provider fallback + background refresh scheduling.

One background thread owns all network I/O. The UI thread only ever
reads an immutable snapshot, so rendering can never block on a socket.

Each data lane refreshes on its own cadence and carries its own backoff
ladder, so a rate-limited market call never slows down the price tape.
On failure the previous value is retained and its age is exposed, which
is how the UI can honestly show OFFLINE without blanking the screen.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from app.market.provider import (
    BitcoinMarketData,
    ChartSeries,
    FearGreedIndex,
    GlobalMarketData,
    NotSupportedError,
    PriceQuote,
    TIMEFRAMES,
)
from app.market.registry import build_providers
from app.utils.logger import get_logger
from app.utils.network import Backoff, HttpClient, NetworkError

log = get_logger("market")


@dataclass
class MarketSnapshot:
    """Immutable view of all market data, handed to the UI."""

    price: PriceQuote = field(default_factory=PriceQuote)
    market: BitcoinMarketData = field(default_factory=BitcoinMarketData)
    chart: ChartSeries = field(default_factory=ChartSeries)
    global_data: GlobalMarketData = field(default_factory=GlobalMarketData)
    top: list = field(default_factory=list)
    fear_greed: FearGreedIndex = field(default_factory=FearGreedIndex)

    timeframe: str = "1D"
    online: bool = False
    refreshing: bool = False
    last_success: float = 0.0
    last_error: str = ""
    consecutive_failures: int = 0

    @property
    def best_price(self) -> Optional[float]:
        """Freshest price available, preferring the fast lane."""
        if self.price.price is not None:
            return self.price.price
        return self.market.price

    @property
    def best_change_24h(self) -> Optional[float]:
        if self.price.change_24h_pct is not None:
            return self.price.change_24h_pct
        return self.market.change_24h_pct

    @property
    def has_any_data(self) -> bool:
        return self.best_price is not None


# Cold-start offsets, in seconds. Firing every lane at once makes three
# CoinGecko calls land in the same second and reliably trips its free-tier
# rate limit (observed as 429s on a real Pi boot). Spreading them costs the
# user nothing -- the price lane, which is what they actually look at,
# still fires immediately.
_STARTUP_STAGGER = {
    "price": 0.0,
    "chart": 0.5,
    "market": 1.5,
    "global": 3.0,
    "top": 4.5,
    "fear_greed": 6.0,
}


class _Task:
    """One refresh lane: an interval, a backoff ladder, a due time."""

    def __init__(self, name: str, interval: float, runner: Callable, backoff_ladder):
        self.name = name
        self.interval = max(1.0, float(interval))
        self.runner = runner
        self.backoff = Backoff(backoff_ladder)
        self.next_due = 0.0  # due immediately at startup
        self.last_success = 0.0

    def schedule_success(self, now: float):
        self.backoff.reset()
        self.last_success = time.time()
        self.next_due = now + self.interval

    def schedule_failure(self, now: float) -> float:
        delay = self.backoff.fail()
        # Never retry faster than the normal cadence would have.
        self.next_due = now + max(delay, 1.0)
        return delay

    def due_now(self):
        self.next_due = 0.0


class MarketService:
    """Owns providers, scheduling, caching and connection state."""

    def __init__(
        self,
        settings,
        cache,
        on_change: Callable | None = None,
        timeframe: str | None = None,
    ):
        self.settings = settings
        self.cache = cache
        self._on_change = on_change

        self.http = HttpClient(settings.timeout_seconds, settings.user_agent)

        # Every provider named anywhere in the config, instantiated once.
        names = []
        for order in settings.provider_order.values():
            names.extend(order)
        self._providers = build_providers(names, settings, self.http)
        log.info("providers ready: %s", ", ".join(sorted(self._providers)) or "none")

        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # The persisted timeframe must be known before the cache restore,
        # otherwise we would load the chart for the wrong window.
        requested = str(timeframe or settings.default_timeframe).upper()
        self._timeframe = requested if requested in TIMEFRAMES else settings.default_timeframe
        self._charts: dict = {}  # timeframe -> ChartSeries (in-memory, all TFs)

        self._snapshot = MarketSnapshot(timeframe=self._timeframe)
        self._refresh_pending = False

        self._tasks = [
            _Task("price", settings.refresh["price_seconds"], self._fetch_price,
                  settings.backoff_seconds),
            _Task("market", settings.refresh["market_seconds"], self._fetch_market,
                  settings.backoff_seconds),
            _Task("chart", settings.refresh["chart_seconds"], self._fetch_chart,
                  settings.backoff_seconds),
            _Task("global", settings.refresh["global_seconds"], self._fetch_global,
                  settings.backoff_seconds),
            _Task("top", settings.refresh["top_seconds"], self._fetch_top,
                  settings.backoff_seconds),
            _Task("fear_greed", settings.refresh["fear_greed_seconds"],
                  self._fetch_fear_greed, settings.backoff_seconds),
        ]

        self._restore_from_cache()

    # --- cache ---------------------------------------------------------
    def _restore_from_cache(self):
        """Warm the snapshot from disk so boot shows data immediately."""
        price = self.cache.get("price")
        market = self.cache.get("market")
        global_data = self.cache.get("global")
        fear_greed = self.cache.get("fear_greed")
        top = self.cache.get("top")
        chart = self.cache.get(f"chart:{self._timeframe}")

        with self._lock:
            if price:
                self._snapshot.price = price
            if market:
                self._snapshot.market = market
            if global_data:
                self._snapshot.global_data = global_data
            if fear_greed:
                self._snapshot.fear_greed = fear_greed
            if top:
                self._snapshot.top = top
            if chart:
                self._charts[self._timeframe] = chart
                self._snapshot.chart = chart
            # Cached data is never "live" until a fetch succeeds.
            self._snapshot.online = False
        if any((price, market, chart)):
            log.info("restored cached market data from disk")

    # --- provider fallback ---------------------------------------------
    def _call(self, capability: str, method: str, *args):
        """Try each configured provider in order; first success wins."""
        order = self.settings.provider_order.get(capability) or []
        errors = []
        for name in order:
            provider = self._providers.get(name)
            if provider is None:
                continue
            try:
                result = getattr(provider, method)(*args)
                if result is not None:
                    return result, name
            except NotSupportedError as exc:
                errors.append(f"{name}: unsupported")
                log.debug("%s: %s", name, exc)
            except NetworkError as exc:
                errors.append(f"{name}: {exc}")
                log.warning("%s %s failed: %s", name, capability, exc)
            except Exception as exc:  # a provider bug must not kill the app
                errors.append(f"{name}: {type(exc).__name__}")
                log.exception("%s %s raised unexpectedly", name, capability)
        raise NetworkError("; ".join(errors) or f"no provider for {capability}")

    # --- fetchers ------------------------------------------------------
    def _fetch_price(self):
        quote, source = self._call("price", "get_bitcoin_price")
        with self._lock:
            self._snapshot.price = quote
        self.cache.set("price", quote)
        log.debug("price %.2f via %s", quote.price or 0.0, source)

    def _fetch_market(self):
        data, _ = self._call("market", "get_bitcoin_market_data")
        with self._lock:
            self._snapshot.market = data
        self.cache.set("market", data)

    def _fetch_chart(self):
        with self._lock:
            timeframe = self._timeframe
        series, _ = self._call("chart", "get_bitcoin_chart", timeframe)
        with self._lock:
            self._charts[timeframe] = series
            # Discard if the user switched timeframe mid-request.
            if self._timeframe == timeframe:
                self._snapshot.chart = series
        self.cache.set(f"chart:{timeframe}", series)

    def _fetch_global(self):
        data, _ = self._call("global", "get_global_market_data")
        with self._lock:
            self._snapshot.global_data = data
        self.cache.set("global", data)

    def _fetch_top(self):
        coins, _ = self._call(
            "top", "get_top_cryptocurrencies", self.settings.top_count
        )
        with self._lock:
            self._snapshot.top = coins
        self.cache.set("top", coins)

    def _fetch_fear_greed(self):
        data, _ = self._call("fear_greed", "get_fear_greed_index")
        with self._lock:
            self._snapshot.fear_greed = data
        self.cache.set("fear_greed", data)

    # --- scheduling ----------------------------------------------------
    def _run_task(self, task: _Task, now: float) -> bool:
        """Run one lane. Returns True when the snapshot changed."""
        try:
            task.runner()
        except NetworkError as exc:
            delay = task.schedule_failure(now)
            with self._lock:
                self._snapshot.last_error = str(exc)[:120]
                # Only the price lane governs the LIVE/OFFLINE indicator:
                # it is the one the user is watching.
                if task.name == "price":
                    self._snapshot.consecutive_failures = task.backoff.failures
                    if task.backoff.failures >= self.settings.offline_after_failures:
                        self._snapshot.online = False
            log.warning("%s refresh failed (retry in %.0fs): %s", task.name, delay, exc)
            return task.name == "price"
        except Exception:
            delay = task.schedule_failure(now)
            log.exception("%s refresh crashed (retry in %.0fs)", task.name, delay)
            return False

        task.schedule_success(now)
        with self._lock:
            self._snapshot.last_success = task.last_success
            if task.name == "price":
                self._snapshot.consecutive_failures = 0
                self._snapshot.online = True
                self._snapshot.last_error = ""
        return True

    def _loop(self):
        log.info("market service started")
        while self._running:
            now = time.monotonic()
            changed = False

            for task in self._tasks:
                if not self._running:
                    break
                if task.next_due <= now:
                    changed |= self._run_task(task, time.monotonic())

            with self._lock:
                if self._refresh_pending:
                    self._refresh_pending = False
                    self._snapshot.refreshing = False
                    changed = True

            self.cache.flush()

            if changed and self._on_change:
                try:
                    self._on_change()
                except Exception:
                    log.exception("on_change callback failed")

            # Sleep until the next lane is due, interruptible by wake().
            now = time.monotonic()
            timeout = min((t.next_due for t in self._tasks), default=now + 1.0) - now
            self._wake.wait(max(0.2, min(timeout, 5.0)))
            self._wake.clear()
        log.info("market service stopped")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        now = time.monotonic()
        for task in self._tasks:
            task.next_due = now + _STARTUP_STAGGER.get(task.name, 0.0)
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="market-service", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self.cache.flush(force=True)
        self.http.close()

    # --- public API ----------------------------------------------------
    def snapshot(self) -> MarketSnapshot:
        """Thread-safe copy for the render loop."""
        with self._lock:
            return replace(self._snapshot, top=list(self._snapshot.top))

    @property
    def timeframe(self) -> str:
        with self._lock:
            return self._timeframe

    def set_timeframe(self, timeframe: str) -> bool:
        """Switch chart timeframe; shows cached series instantly if present."""
        timeframe = str(timeframe).upper()
        if timeframe not in TIMEFRAMES:
            return False
        with self._lock:
            if timeframe == self._timeframe:
                return False
            self._timeframe = timeframe
            self._snapshot.timeframe = timeframe
            cached = self._charts.get(timeframe)
            if cached is None:
                # Not seen this session -- try the on-disk cache so a
                # timeframe used before a reboot still paints instantly.
                cached = self.cache.get(f"chart:{timeframe}")
                if cached is not None:
                    self._charts[timeframe] = cached
            # Show the cached series immediately; a refresh is queued below.
            self._snapshot.chart = cached or ChartSeries(timeframe=timeframe)

        for task in self._tasks:
            if task.name == "chart":
                task.due_now()
        self._wake.set()
        log.info("timeframe changed to %s", timeframe)
        return True

    def next_timeframe(self) -> str:
        """Advance through 1H -> 4H -> 1D -> 1W -> 1Y -> 1H."""
        current = self.timeframe
        index = TIMEFRAMES.index(current) if current in TIMEFRAMES else 0
        nxt = TIMEFRAMES[(index + 1) % len(TIMEFRAMES)]
        self.set_timeframe(nxt)
        return nxt

    def request_refresh(self):
        """Force every lane to refresh now (triple-click)."""
        with self._lock:
            self._refresh_pending = True
            self._snapshot.refreshing = True
        for task in self._tasks:
            task.due_now()
        self._wake.set()
        log.info("manual refresh requested")
