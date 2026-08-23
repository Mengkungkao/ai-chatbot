"""Screen base class and the render context passed to every screen."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RenderContext:
    """Everything a screen may need for one frame.

    Screens are pure renderers: they read this and draw. They never call
    the network, never mutate state, and never block.
    """

    snapshot: object                      # MarketSnapshot
    settings: object                      # Settings
    system: dict = field(default_factory=dict)
    connectivity: dict = field(default_factory=dict)
    now: float = 0.0
    page_index: int = 0
    page_count: int = 1
    toast: Optional[str] = None           # transient banner text
    toast_kind: str = "info"              # info | success | error
    board_mode: str = "headless"


class Screen:
    """A single dashboard page."""

    name = "screen"
    title = "SCREEN"

    def render(self, draw, ctx: RenderContext):
        raise NotImplementedError

    def on_enter(self, ctx: RenderContext):
        """Optional hook when the screen becomes visible."""

    def on_exit(self, ctx: RenderContext):
        """Optional hook when the screen is left."""
