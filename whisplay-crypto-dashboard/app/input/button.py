"""Single-button gesture detection.

The Whisplay HAT has exactly one button, so every interaction is encoded
in how many times it is pressed inside a short window:

    PRESS                          -> wait CLICK_WINDOW -> single
    PRESS PRESS                    -> double
    PRESS PRESS PRESS              -> triple
    PRESS PRESS PRESS PRESS        -> quad (fires immediately)
    PRESS ...held...               -> long_press

Two timing rules make it reliable on real hardware:

* Debounce: a press is only accepted once `debounce_ms` has elapsed
  since the previous accepted release. Releases are accepted whenever a
  press is outstanding. Debouncing the press edge alone is deliberate --
  gating the release edge as well would swallow genuine short clicks,
  which are frequently only 30-60 ms long.
* Click window: after a release we wait `click_window_ms` for another
  click before committing to a gesture. Four clicks short-circuit the
  wait, so returning HOME feels instant.

A held press is never counted as a click, so the daemon's long-press
exit gesture cannot leave a stray single-click queued behind it.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from app.utils.logger import get_logger

log = get_logger("button")

SINGLE = "single"
DOUBLE = "double"
TRIPLE = "triple"
QUAD = "quad"
LONG_PRESS = "long_press"

_GESTURE_BY_COUNT = {1: SINGLE, 2: DOUBLE, 3: TRIPLE, 4: QUAD}
MAX_CLICKS = 4


class GestureDetector:
    """Turns raw press/release edges into named gestures."""

    def __init__(
        self,
        on_gesture: Callable[[str], None],
        debounce_ms: int = 75,
        click_window_ms: int = 400,
        long_press_ms: int = 700,
    ):
        self.on_gesture = on_gesture
        self.debounce = debounce_ms / 1000.0
        self.click_window = click_window_ms / 1000.0
        self.long_press = long_press_ms / 1000.0

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._clicks = 0
        self._deadline = 0.0
        self._press_time = 0.0
        self._last_release = -1e9
        # Inter-click gaps for the run in progress, milliseconds. Logged
        # with the gesture so click_window_ms can be tuned from real data
        # instead of guesswork.
        self._gaps = []
        self._last_click = 0.0
        self._pressed = False
        self._running = False
        self._thread = None

    # --- lifecycle -----------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="gesture-detector", daemon=True
        )
        self._thread.start()

    def stop(self):
        with self._cond:
            self._running = False
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=1.5)

    def attach(self, board):
        """Wire this detector to a Whisplay board's button callbacks."""
        board.on_button_press(self.handle_press)
        board.on_button_release(self.handle_release)

    # --- edges ---------------------------------------------------------
    def handle_press(self, *_args):
        now = time.monotonic()
        with self._cond:
            if self._pressed:
                return  # duplicate press without an intervening release
            if now - self._last_release < self.debounce:
                # Chatter on the release edge re-asserting the contact.
                return
            self._pressed = True
            self._press_time = now

    def handle_release(self, *_args):
        now = time.monotonic()
        emit = None
        with self._cond:
            if not self._pressed:
                return  # release without a matching press (bounce tail)
            self._pressed = False
            self._last_release = now

            held = now - self._press_time
            if held >= self.long_press:
                # A hold is its own gesture and clears any pending clicks.
                self._clicks = 0
                self._deadline = 0.0
                self._gaps = []
                emit = LONG_PRESS
            else:
                # Record the gap from the previous click even when it
                # belonged to an earlier run: a run of lone singles is
                # exactly the symptom of a click_window that is too tight,
                # and the gap is the number needed to fix it.
                if self._last_click:
                    self._gaps.append(int((now - self._last_click) * 1000))
                self._last_click = now
                self._clicks += 1
                if self._clicks >= MAX_CLICKS:
                    emit = _GESTURE_BY_COUNT[MAX_CLICKS]
                    self._clicks = 0
                    self._deadline = 0.0
                    gaps, self._gaps = self._gaps, []
                    self._last_gaps = gaps
                else:
                    self._deadline = now + self.click_window
            self._cond.notify_all()

        if emit:
            self._dispatch(emit)

    # --- worker --------------------------------------------------------
    def _loop(self):
        while True:
            with self._cond:
                if not self._running:
                    return
                if self._deadline <= 0.0:
                    self._cond.wait(timeout=0.5)
                    continue

                remaining = self._deadline - time.monotonic()
                if remaining > 0:
                    self._cond.wait(timeout=remaining)
                    continue

                # Window expired: commit whatever was collected.
                clicks = self._clicks
                self._clicks = 0
                self._deadline = 0.0
                self._last_gaps, self._gaps = self._gaps, []

            gesture = _GESTURE_BY_COUNT.get(clicks)
            if gesture:
                self._dispatch(gesture)

    def _dispatch(self, gesture: str):
        gaps = getattr(self, "_last_gaps", None)
        if gaps:
            log.info(
                "gesture: %s (gaps %s ms, window %d ms)",
                gesture, "/".join(str(g) for g in gaps),
                int(self.click_window * 1000),
            )
        else:
            log.info("gesture: %s", gesture)
        try:
            self.on_gesture(gesture)
        except Exception:
            log.exception("gesture handler failed for %s", gesture)
