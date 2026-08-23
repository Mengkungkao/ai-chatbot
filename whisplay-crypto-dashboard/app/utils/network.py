"""HTTP helpers and connectivity tracking.

The dashboard is expected to run for months on a flaky home Wi-Fi link,
so every network call is bounded, every failure is counted, and retries
back off instead of hammering a provider that is already struggling.
"""

from __future__ import annotations

import socket
import threading
import time

import requests

from app.utils.logger import get_logger

log = get_logger("network")


class NetworkError(Exception):
    """Raised for any recoverable data-fetch failure."""


class HttpClient:
    """A small requests wrapper with a shared connection pool."""

    def __init__(self, timeout: float = 8.0, user_agent: str = "whisplay-crypto"):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": user_agent, "Accept": "application/json"}
        )
        # One connection per host is plenty and keeps memory flat.
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=2, pool_maxsize=4, max_retries=0
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        """GET and parse JSON, converting every failure into NetworkError."""
        try:
            response = self._session.get(
                url, params=params, headers=headers, timeout=self.timeout
            )
        except requests.exceptions.Timeout as exc:
            raise NetworkError(f"timeout: {url}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise NetworkError(f"connection failed: {url}") from exc
        except requests.exceptions.RequestException as exc:
            raise NetworkError(f"request failed: {exc}") from exc

        if response.status_code == 429:
            raise NetworkError(f"rate limited (429): {url}")
        if response.status_code >= 500:
            raise NetworkError(f"server error ({response.status_code}): {url}")
        if response.status_code >= 400:
            raise NetworkError(f"client error ({response.status_code}): {url}")

        try:
            return response.json()
        except ValueError as exc:
            raise NetworkError(f"invalid JSON from {url}") from exc

    def close(self):
        try:
            self._session.close()
        except Exception:  # pragma: no cover - best effort
            pass


class Backoff:
    """Exponential backoff over a fixed ladder, e.g. 5/10/30/60/120s."""

    def __init__(self, ladder: list[float]):
        self._ladder = list(ladder) or [5.0]
        self._index = -1
        self.failures = 0

    def reset(self):
        self._index = -1
        self.failures = 0

    def fail(self) -> float:
        """Record a failure and return the delay to wait before retrying."""
        self.failures += 1
        self._index = min(self._index + 1, len(self._ladder) - 1)
        return self._ladder[self._index]

    @property
    def current_delay(self) -> float:
        if self._index < 0:
            return 0.0
        return self._ladder[self._index]


class ConnectivityMonitor:
    """Tracks LAN/Internet/API reachability for the System page.

    Checks are cheap (a TCP connect, not an HTTP round trip) and cached,
    so the System screen can be repainted freely.
    """

    def __init__(self, check_interval: float = 15.0):
        self.check_interval = check_interval
        self._lock = threading.Lock()
        self._last_check = 0.0
        self._wifi = False
        self._internet = False

    @staticmethod
    def _tcp_reachable(host: str, port: int, timeout: float = 2.5) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    @staticmethod
    def _has_local_ip() -> bool:
        """True when a non-loopback address is configured (Wi-Fi is up)."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(1.0)
                # No packets are actually sent for a UDP connect().
                sock.connect(("192.0.2.1", 9))
                return not sock.getsockname()[0].startswith("127.")
        except OSError:
            return False

    def sample(self, force: bool = False) -> dict:
        now = time.monotonic()
        with self._lock:
            stale = force or (now - self._last_check) >= self.check_interval
            if not stale:
                return {"wifi": self._wifi, "internet": self._internet}

        wifi = self._has_local_ip()
        internet = self._tcp_reachable("1.1.1.1", 53) if wifi else False

        with self._lock:
            if internet != self._internet:
                log.info("internet reachability changed: %s", internet)
            self._wifi = wifi
            self._internet = internet
            self._last_check = time.monotonic()
            return {"wifi": wifi, "internet": internet}
