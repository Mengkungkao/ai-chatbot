"""Gesture detection is the entire user interface -- it must be exact."""

import time

import pytest

from app.input.button import DOUBLE, LONG_PRESS, QUAD, SINGLE, TRIPLE, GestureDetector


@pytest.fixture
def detector():
    events = []
    det = GestureDetector(
        events.append, debounce_ms=75, click_window_ms=200, long_press_ms=500
    )
    det.start()
    det.events = events
    yield det
    det.stop()


def click(det, hold=0.04, gap=0.09):
    det.handle_press()
    time.sleep(hold)
    det.handle_release()
    time.sleep(gap)


def settle(det, extra=0.30):
    time.sleep(extra)
    return list(det.events)


@pytest.mark.parametrize(
    "count,expected",
    [(1, SINGLE), (2, DOUBLE), (3, TRIPLE), (4, QUAD)],
)
def test_click_counts(detector, count, expected):
    for _ in range(count):
        click(detector)
    assert settle(detector) == [expected]


def test_short_click_is_not_swallowed_by_debounce():
    """A 30 ms press is a normal human click, not contact bounce."""
    events = []
    det = GestureDetector(events.append, debounce_ms=75, click_window_ms=200)
    det.start()
    try:
        det.handle_press()
        time.sleep(0.03)
        det.handle_release()
        time.sleep(0.35)
        assert events == [SINGLE]
    finally:
        det.stop()


def test_contact_bounce_produces_one_click(detector):
    """Chatter on both edges must collapse into a single click."""
    detector.handle_press()
    for _ in range(5):            # bounce on the press edge
        detector.handle_release()
        detector.handle_press()
    time.sleep(0.05)
    detector.handle_release()
    for _ in range(5):            # bounce on the release edge
        detector.handle_press()
        detector.handle_release()
    assert settle(detector) == [SINGLE]


def test_long_press_is_not_counted_as_a_click(detector):
    """Otherwise the daemon's exit gesture would leave a stray single."""
    detector.handle_press()
    time.sleep(0.55)
    detector.handle_release()
    assert settle(detector) == [LONG_PRESS]


def test_quad_click_fires_without_waiting_out_the_window(detector):
    """HOME must feel instant: quad fires on the 4th release itself."""
    for _ in range(3):
        click(detector)
    detector.handle_press()
    time.sleep(0.04)
    detector.handle_release()
    released_at = time.monotonic()

    while not detector.events and time.monotonic() - released_at < 1.0:
        time.sleep(0.002)
    latency = time.monotonic() - released_at

    assert detector.events == [QUAD]
    # Not merely faster than the window -- effectively immediate.
    assert latency < detector.click_window / 2


def test_debounce_sets_a_floor_on_click_rate(detector):
    """Clicks closer together than debounce_ms are treated as bounce.

    This documents the tradeoff: a 75 ms debounce caps the usable click
    rate at roughly 13/s, far above anything a human can produce, but
    tests must not simulate impossible input.
    """
    for _ in range(4):
        click(detector, hold=0.005, gap=0.005)
    assert settle(detector) == [SINGLE]


def test_release_without_press_is_ignored(detector):
    detector.handle_release()
    assert settle(detector) == []
