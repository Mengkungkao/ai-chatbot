"""Whisplay board acquisition.

Under the daemon the app never touches SPI or GPIO directly: the daemon
owns the hardware and hands us a shared framebuffer plus a button event
stream. `create_whisplay_hardware()` transparently falls back to direct
`WhisplayBoard` access when the daemon is not running, and this module
adds a third fallback -- a no-op board -- so the dashboard can be
rendered and tested on a development machine.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from app.utils.logger import get_logger

log = get_logger("board")

APP_ID = "whisplay-crypto-dashboard"
DISPLAY_NAME = "BTC Dashboard"
ICON = "BTC"

# Four rapid clicks are the app's HOME gesture, so the daemon's default
# quad-click exit would collide with it. Long press becomes exit instead.
EXIT_GESTURE = "long_press"
PRIORITY = 40

# How often to re-attempt foreground acquisition when another app owns the
# screen. Cheap: one Unix-socket round trip.
FOREGROUND_RETRY_SECONDS = 5.0


def _runtime_candidates() -> list:
    """Where Whisplay's runtime/ directory might live."""
    project_root = Path(__file__).resolve().parents[1]
    candidates = []

    env_path = os.getenv("WHISPLAY_RUNTIME")
    if env_path:
        candidates.append(Path(env_path))

    candidates.extend(
        [
            project_root.parent / "Whisplay" / "runtime",
            Path.home() / "Whisplay" / "runtime",
            Path("/home/pi/Whisplay/runtime"),
            Path("/opt/whisplay/runtime"),
            Path("/usr/local/share/whisplay/runtime"),
        ]
    )
    return candidates


def _import_client():
    """Put Whisplay's runtime on sys.path and import the daemon client."""
    for candidate in _runtime_candidates():
        if not (candidate / "whisplay_client.py").is_file():
            continue
        path = str(candidate)
        if path not in sys.path:
            sys.path.append(path)
        try:
            import whisplay_client  # noqa: WPS433 (runtime path injection)
        except ImportError as exc:
            # Expected off-device: the runtime pulls in spidev/gpiod,
            # which only exist on the Pi. Fall through to headless.
            log.warning("whisplay runtime at %s is unusable: %s", path, exc)
            return None
        log.info("using whisplay runtime at %s", path)
        return whisplay_client
    return None


class NullBoard:
    """Headless stand-in used for development and PNG previews."""

    def __init__(self):
        self.width = 240
        self.height = 280
        self.foreground_ready = True

    def fill_screen(self, color):
        pass

    def draw_image(self, x, y, width, height, pixel_data):
        pass

    def set_backlight(self, brightness):
        pass

    def set_rgb(self, r, g, b):
        pass

    def set_rgb_fade(self, r, g, b, duration_ms=100):
        pass

    def button_pressed(self):
        return False

    def on_button_press(self, callback):
        pass

    def on_button_release(self, callback):
        pass

    def cleanup(self):
        pass


def _start_foreground_retry(proxy, on_acquired=None,
                            interval: float = FOREGROUND_RETRY_SECONDS):
    """Keep asking for the screen until the current app gives it up.

    Without this the app would sit in headless mode forever -- polling
    market APIs while drawing to nothing -- which is exactly what happens
    when it autostarts at boot while the Wi-Fi or another app still owns
    the foreground.
    """

    def loop():
        attempts = 0
        while not getattr(proxy, "foreground_ready", False):
            time.sleep(interval)
            attempts += 1
            try:
                proxy.acquire_foreground(timeout_sec=1.0)
            except Exception:
                continue
            proxy.foreground_ready = True
            log.info("foreground acquired after %d attempt(s)", attempts)
            if on_acquired is not None:
                try:
                    on_acquired()
                except Exception:
                    log.exception("foreground callback failed")
            return

    threading.Thread(target=loop, name="foreground-retry", daemon=True).start()


def acquire_board(
    launch_command: str | None = None,
    launch_cwd: str | None = None,
    on_foreground_acquired=None,
):
    """Return (board, mode).

    mode is one of:
      daemon    foreground held, drawing to the shared framebuffer
      waiting   daemon present but another app owns the screen; retrying
      direct    no daemon, driving the HAT over SPI directly
      headless  no hardware at all (development machine)
    """
    client = _import_client()
    if client is None:
        log.warning("whisplay runtime not found; running headless")
        return NullBoard(), "headless"

    project_root = Path(__file__).resolve().parents[1]
    if launch_command is None:
        launch_command = str(project_root / "run.sh")
    if launch_cwd is None:
        launch_cwd = str(project_root)

    try:
        proxy = client.WhisplayDaemonProxy(
            socket_path=client.DEFAULT_DAEMON_SOCKET_PATH,
            app_id=APP_ID,
            display_name=DISPLAY_NAME,
            icon=ICON,
            launch_command=launch_command,
            launch_cwd=launch_cwd,
            persist=True,
            exit_gesture=EXIT_GESTURE,
            priority=PRIORITY,
            use_daemon_default_log=True,
        )
        daemon_alive = proxy.ping()
    except Exception:
        log.exception("could not talk to the whisplay daemon")
        daemon_alive = False
        proxy = None

    # No daemon: fall back to driving the HAT ourselves.
    if not daemon_alive:
        try:
            board = client.WhisplayBoard()
            log.info("whisplay board acquired in direct mode (no daemon)")
            return board, "direct"
        except Exception:
            log.exception("direct hardware access failed; running headless")
            return NullBoard(), "headless"

    proxy.foreground_ready = False
    try:
        proxy.register()
        proxy.start_event_listener()
    except Exception:
        log.exception("daemon registration failed; running headless")
        return NullBoard(), "headless"

    try:
        proxy.acquire_foreground()
    except Exception as exc:
        # Another app holds the screen. Keep the daemon connection and
        # retry in the background rather than going permanently blind.
        log.warning("foreground unavailable (%s); retrying every %.0fs",
                    exc, FOREGROUND_RETRY_SECONDS)
        _start_foreground_retry(proxy, on_foreground_acquired)
        return proxy, "waiting"

    proxy.foreground_ready = True
    log.info("whisplay board acquired in daemon mode")
    return proxy, "daemon"
