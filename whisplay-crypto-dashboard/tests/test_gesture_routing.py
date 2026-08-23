"""The gesture -> action mapping is the whole UI contract.

`handle_gesture` only dispatches to methods on self, so it can be bound to
a stub. That keeps this a fast unit test with no hardware, no network and
no writes to the user's home directory.
"""

import pytest

from app.input.button import DOUBLE, LONG_PRESS, QUAD, SINGLE, TRIPLE
from app.main import DashboardApp


class _Router:
    """Records which action a gesture dispatched to."""

    def __init__(self):
        self.calls = []

    def cycle_timeframe(self):
        self.calls.append("timeframe")

    def next_page(self):
        self.calls.append("page")

    def go_home(self):
        self.calls.append("home")

    def force_refresh(self):
        self.calls.append("refresh")

    def request_exit(self):
        self.calls.append("exit")


@pytest.mark.parametrize(
    "gesture,expected",
    [
        (SINGLE, "timeframe"),      # 1 press  -> change timeframe
        (LONG_PRESS, "page"),       # hold     -> next page
        (DOUBLE, "home"),           # 2 press  -> home
        (TRIPLE, "refresh"),        # 3 press  -> refresh
        (QUAD, "exit"),             # 4 press  -> leave the app
    ],
)
def test_gesture_mapping(gesture, expected):
    router = _Router()
    DashboardApp.handle_gesture(router, gesture)
    assert router.calls == [expected]


def test_single_click_does_not_change_page():
    """Regression: timeframe changes used to jump to the chart.

    With single click as the most frequent gesture, that would make every
    page other than the chart impossible to stay on.
    """
    import inspect

    source = inspect.getsource(DashboardApp.cycle_timeframe)
    assert "page_index" not in source


def test_every_gesture_is_routed():
    """No gesture may silently do nothing."""
    for gesture in (SINGLE, DOUBLE, TRIPLE, QUAD, LONG_PRESS):
        router = _Router()
        DashboardApp.handle_gesture(router, gesture)
        assert router.calls, f"{gesture} is unrouted"


def test_app_owns_every_gesture():
    """exit_gesture must be 'none' or the daemon steals hold/quad."""
    import json
    from pathlib import Path

    from app.board import EXIT_GESTURE

    assert EXIT_GESTURE == "none"
    manifest = json.loads(
        (Path(__file__).resolve().parents[1]
         / "packaging" / "whisplay-crypto-dashboard.json").read_text()
    )
    assert manifest["exit_gesture"] == "none"
