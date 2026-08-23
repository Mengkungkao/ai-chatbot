"""Provider fallback, offline behaviour and cache durability."""

import time

import pytest

from app.market.cache import AppState, MarketCache
from app.market.provider import (
    BitcoinMarketData, ChartSeries, CoinSummary, MarketDataProvider,
    NotSupportedError, PriceQuote, downsample,
)
from app.market.service import MarketService
from app.utils.network import Backoff, NetworkError


# --- fakes ------------------------------------------------------------
class FlakyProvider(MarketDataProvider):
    name = "flaky"

    def __init__(self, *_a, **_k):
        self.calls = 0

    def get_bitcoin_price(self):
        self.calls += 1
        raise NetworkError("simulated outage")


class GoodProvider(MarketDataProvider):
    name = "good"

    def __init__(self, *_a, **_k):
        self.calls = 0

    def get_bitcoin_price(self):
        self.calls += 1
        return PriceQuote(112540.32, 2.41, time.time())


class LimitedProvider(MarketDataProvider):
    name = "limited"

    def __init__(self, *_a, **_k):
        pass

    def get_bitcoin_price(self):
        return PriceQuote(1.0, 0.0, time.time())


# --- backoff ----------------------------------------------------------
def test_backoff_follows_the_configured_ladder():
    backoff = Backoff([5, 10, 30, 60, 120])
    assert [backoff.fail() for _ in range(6)] == [5, 10, 30, 60, 120, 120]


def test_backoff_resets_after_success():
    backoff = Backoff([5, 10, 30])
    backoff.fail()
    backoff.fail()
    backoff.reset()
    assert backoff.fail() == 5
    assert backoff.failures == 1


# --- provider fallback -------------------------------------------------
def test_falls_through_to_the_next_provider(settings, monkeypatch):
    settings.provider_order["price"] = ["flaky", "good"]
    service = MarketService(settings, MarketCache("/dev/null", enabled=False))
    flaky, good = FlakyProvider(), GoodProvider()
    service._providers = {"flaky": flaky, "good": good}

    quote, source = service._call("price", "get_bitcoin_price")

    assert source == "good"
    assert quote.price == 112540.32
    assert flaky.calls == 1  # the broken one was genuinely attempted


def test_unsupported_capability_is_skipped_not_fatal(settings):
    settings.provider_order["chart"] = ["limited"]
    service = MarketService(settings, MarketCache("/dev/null", enabled=False))
    service._providers = {"limited": LimitedProvider()}

    with pytest.raises(NetworkError):
        service._call("chart", "get_bitcoin_chart", "1D")


def test_all_providers_failing_raises_rather_than_returning_junk(settings):
    settings.provider_order["price"] = ["flaky"]
    service = MarketService(settings, MarketCache("/dev/null", enabled=False))
    service._providers = {"flaky": FlakyProvider()}

    with pytest.raises(NetworkError):
        service._call("price", "get_bitcoin_price")


# --- offline behaviour --------------------------------------------------
def test_stale_data_is_retained_but_marked_offline(settings, tmp_path):
    """The screen keeps showing the last price -- flagged, never as live."""
    settings.provider_order["price"] = ["flaky"]
    settings.offline_after_failures = 2
    cache = MarketCache(tmp_path / "c.json", enabled=True, min_write_interval=0)
    service = MarketService(settings, cache)
    service._providers = {"flaky": FlakyProvider()}
    service._snapshot.price = PriceQuote(112540.32, 2.41, time.time())
    service._snapshot.online = True

    price_task = next(t for t in service._tasks if t.name == "price")
    service._run_task(price_task, time.monotonic())
    assert service.snapshot().online is True   # one failure is tolerated
    service._run_task(price_task, time.monotonic())

    snap = service.snapshot()
    assert snap.online is False                # now honestly offline
    assert snap.best_price == 112540.32        # but data is still there
    assert "simulated outage" in snap.last_error


def test_timeframe_cycles_in_order(settings):
    service = MarketService(settings, MarketCache("/dev/null", enabled=False))
    service.set_timeframe("1H")
    assert [service.next_timeframe() for _ in range(5)] == [
        "4H", "1D", "1W", "1Y", "1H",
    ]


def test_invalid_timeframe_is_rejected(settings):
    service = MarketService(settings, MarketCache("/dev/null", enabled=False))
    service.set_timeframe("1D")
    assert service.set_timeframe("7X") is False
    assert service.timeframe == "1D"


# --- cache --------------------------------------------------------------
def test_cache_survives_a_restart(tmp_path):
    path = tmp_path / "cache.json"
    cache = MarketCache(path, enabled=True, min_write_interval=0)
    cache.set("price", PriceQuote(112540.32, 2.41, 1000.0))
    cache.set("market", BitcoinMarketData(price=112540.32, market_cap=2.24e12))
    cache.set("chart:1D", ChartSeries("1D", [(1.0, 2.0), (3.0, 4.0)], 5.0))
    cache.set("top", [CoinSummary(1, "BTC", "Bitcoin", 112540.32, 2.41, 2.24e12)])
    cache.flush(force=True)

    reloaded = MarketCache(path, enabled=True, min_write_interval=0)
    assert reloaded.get("price").price == 112540.32
    assert reloaded.get("market").market_cap == 2.24e12
    assert reloaded.get("chart:1D").points == [(1.0, 2.0), (3.0, 4.0)]
    assert reloaded.get("top")[0].symbol == "BTC"


def test_corrupt_cache_is_ignored_not_fatal(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{ this is not json")
    cache = MarketCache(path, enabled=True)
    assert cache.get("price") is None


def test_cache_entry_from_an_older_schema_is_discarded(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text('{"price": {"price": 1.0, "removed_field": 9}}')
    cache = MarketCache(path, enabled=True)
    assert cache.get("price") is None  # discarded, not crashed


def test_state_persists_selected_timeframe(tmp_path):
    path = tmp_path / "state.json"
    state = AppState(path, {"timeframe": "1D"})
    assert state.set("timeframe", "4H") is True
    assert state.set("timeframe", "4H") is False  # no redundant SD write
    assert AppState(path, {"timeframe": "1D"}).get("timeframe") == "4H"


# --- helpers ------------------------------------------------------------
def test_downsample_preserves_window_boundaries():
    points = [(float(i), float(i)) for i in range(1000)]
    thinned = downsample(points, 100)
    assert len(thinned) == 100
    assert thinned[0] == points[0]
    assert thinned[-1] == points[-1]


def test_downsample_leaves_short_series_alone():
    points = [(1.0, 1.0), (2.0, 2.0)]
    assert downsample(points, 100) is points


def test_chart_change_percentage():
    series = ChartSeries("1D", [(0.0, 100.0), (1.0, 110.0)])
    assert series.change_pct == pytest.approx(10.0)
    assert ChartSeries("1D", []).change_pct is None


def test_persisted_timeframe_restores_its_cached_chart(settings, tmp_path):
    """After a reboot the saved timeframe must paint from cache at once.

    Regression: the service used to restore the *config default* chart,
    so a user whose saved timeframe differed saw an empty chart on boot.
    """
    cache = MarketCache(tmp_path / "c.json", enabled=True, min_write_interval=0)
    cache.set("chart:1W", ChartSeries("1W", [(1.0, 100.0), (2.0, 110.0)], 3.0))
    cache.flush(force=True)

    settings.default_timeframe = "1D"          # config says 1D
    service = MarketService(settings, cache, timeframe="1W")   # user saved 1W

    assert service.timeframe == "1W"
    assert service.snapshot().chart.timeframe == "1W"
    assert service.snapshot().chart.is_usable


def test_switching_to_a_timeframe_seen_before_reboot_uses_disk_cache(settings, tmp_path):
    cache = MarketCache(tmp_path / "c.json", enabled=True, min_write_interval=0)
    cache.set("chart:1Y", ChartSeries("1Y", [(1.0, 50.0), (2.0, 60.0)], 3.0))
    cache.flush(force=True)

    service = MarketService(settings, cache, timeframe="1D")
    service.set_timeframe("1Y")

    assert service.snapshot().chart.is_usable  # painted instantly, not blank


def test_bad_persisted_timeframe_falls_back_to_default(settings, tmp_path):
    cache = MarketCache(tmp_path / "c.json", enabled=False)
    service = MarketService(settings, cache, timeframe="NONSENSE")
    assert service.timeframe == settings.default_timeframe


def test_startup_staggers_lanes_to_avoid_rate_limits(settings):
    """Regression: a cold boot fired 3 CoinGecko calls in one second.

    Observed on a real Pi as three simultaneous 429s. The price lane must
    still be immediate -- it is the number the user is looking at.
    """
    import time as _time

    from app.market.service import _STARTUP_STAGGER

    service = MarketService(settings, MarketCache("/dev/null", enabled=False))
    service._running = False          # do not actually spin the thread
    now = _time.monotonic()
    for task in service._tasks:
        task.next_due = now + _STARTUP_STAGGER.get(task.name, 0.0)

    due = {t.name: t.next_due - now for t in service._tasks}
    assert due["price"] == 0.0                       # immediate
    coingecko_lanes = sorted(due[n] for n in ("market", "global", "top"))
    gaps = [b - a for a, b in zip(coingecko_lanes, coingecko_lanes[1:])]
    assert all(gap >= 1.0 for gap in gaps)           # never bunched up
