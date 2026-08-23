"""Local system metrics for the System Status page.

Reads /proc and /sys directly so psutil stays optional -- one less
dependency to build from source on a Pi Zero. Every reader degrades to
None rather than raising, because a diagnostics page that crashes the
app is worse than a diagnostics page with a blank field.
"""

from __future__ import annotations

import os
import time

from app.utils.logger import get_logger

log = get_logger("system")

_THERMAL_PATHS = (
    "/sys/class/thermal/thermal_zone0/temp",
    "/sys/devices/virtual/thermal/thermal_zone0/temp",
)


class SystemMonitor:
    """Samples CPU, memory, temperature and uptime with light caching."""

    def __init__(self, min_interval: float = 2.0):
        self.min_interval = min_interval
        self._last_sample = 0.0
        self._cached: dict = {}
        self._prev_cpu = None
        self._started = time.time()

    # --- individual readers -------------------------------------------
    def _cpu_percent(self):
        """CPU load from the delta between two /proc/stat reads."""
        try:
            with open("/proc/stat", "r", encoding="ascii") as handle:
                fields = handle.readline().split()
            values = [float(v) for v in fields[1:8]]
        except (OSError, ValueError, IndexError):
            return None

        idle = values[3] + (values[4] if len(values) > 4 else 0.0)
        total = sum(values)

        previous = self._prev_cpu
        self._prev_cpu = (total, idle)
        if previous is None:
            return None  # need two samples for a delta

        total_delta = total - previous[0]
        idle_delta = idle - previous[1]
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))

    @staticmethod
    def _memory():
        """(used_percent, used_mb, total_mb) from /proc/meminfo."""
        try:
            info = {}
            with open("/proc/meminfo", "r", encoding="ascii") as handle:
                for line in handle:
                    key, _, rest = line.partition(":")
                    info[key] = float(rest.strip().split()[0])  # kB
        except (OSError, ValueError, IndexError):
            return None, None, None

        total = info.get("MemTotal")
        available = info.get("MemAvailable")
        if not total:
            return None, None, None
        if available is None:
            available = info.get("MemFree", 0.0) + info.get("Cached", 0.0)

        used = total - available
        return (used / total) * 100.0, used / 1024.0, total / 1024.0

    @staticmethod
    def _temperature():
        for path in _THERMAL_PATHS:
            try:
                with open(path, "r", encoding="ascii") as handle:
                    raw = float(handle.read().strip())
                # Kernel reports millidegrees on the Pi.
                return raw / 1000.0 if raw > 1000 else raw
            except (OSError, ValueError):
                continue
        return None

    @staticmethod
    def _uptime():
        try:
            with open("/proc/uptime", "r", encoding="ascii") as handle:
                return float(handle.read().split()[0])
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def process_memory_mb():
        """Resident set size of this process, in MB."""
        try:
            with open("/proc/self/statm", "r", encoding="ascii") as handle:
                pages = float(handle.read().split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE") / (1024.0 * 1024.0)
        except (OSError, ValueError, IndexError, AttributeError):
            return None

    # --- public --------------------------------------------------------
    def sample(self, force: bool = False) -> dict:
        now = time.monotonic()
        if not force and self._cached and (now - self._last_sample) < self.min_interval:
            return self._cached

        memory_pct, memory_used, memory_total = self._memory()
        self._cached = {
            "cpu_percent": self._cpu_percent(),
            "memory_percent": memory_pct,
            "memory_used_mb": memory_used,
            "memory_total_mb": memory_total,
            "temperature_c": self._temperature(),
            "uptime_seconds": self._uptime(),
            "app_uptime_seconds": time.time() - self._started,
            "app_memory_mb": self.process_memory_mb(),
        }
        self._last_sample = now
        return self._cached
