"""Display surface: PIL canvas in, RGB565 framebuffer out.

The daemon samples the shared framebuffer continuously, but we only
convert and push a frame when something actually changed. That is what
keeps the Pi Zero idle at a couple of percent CPU instead of burning a
core on redundant redraws.
"""

from __future__ import annotations

import threading

from PIL import Image, ImageDraw

from app.ui import theme
from app.utils.logger import get_logger

log = get_logger("display")

try:
    import numpy as _np
except ImportError:  # pragma: no cover - optional accelerator
    _np = None


def image_to_rgb565(image: Image.Image) -> bytes:
    """Convert an RGB image to big-endian RGB565 bytes.

    numpy does this ~10x faster; the pure-Python path keeps the app
    working on a minimal image where numpy is not installed.
    """
    if _np is not None:
        arr = _np.asarray(image.convert("RGB"), dtype=_np.uint16)
        rgb565 = (
            ((arr[:, :, 0] & 0xF8) << 8)
            | ((arr[:, :, 1] & 0xFC) << 3)
            | (arr[:, :, 2] >> 3)
        )
        return rgb565.astype(">u2").tobytes()

    pixels = image.convert("RGB").tobytes()
    out = bytearray(len(pixels) // 3 * 2)
    for i in range(len(pixels) // 3):
        offset = i * 3
        value = (
            ((pixels[offset] & 0xF8) << 8)
            | ((pixels[offset + 1] & 0xFC) << 3)
            | (pixels[offset + 2] >> 3)
        )
        out[i * 2] = (value >> 8) & 0xFF
        out[i * 2 + 1] = value & 0xFF
    return bytes(out)


class Display:
    """Owns the canvas and the push-to-hardware path."""

    def __init__(self, board, settings):
        self.board = board
        self.settings = settings
        self.width = theme.SCREEN_WIDTH
        self.height = theme.SCREEN_HEIGHT
        self._lock = threading.Lock()
        self._last_led = None
        self.frames_pushed = 0

        try:
            self.board.set_backlight(settings.brightness)
        except Exception:
            log.warning("could not set backlight", exc_info=True)

    def new_canvas(self, background=theme.BG):
        image = Image.new("RGB", (self.width, self.height), background)
        return image, ImageDraw.Draw(image)

    def present(self, image: Image.Image):
        """Push one finished frame to the framebuffer.

        Skipped entirely while another app owns the screen -- writing to
        a framebuffer we have not been granted is both useless and a way
        to spam the log once per frame.
        """
        if not getattr(self.board, "foreground_ready", True):
            return False
        try:
            frame = image_to_rgb565(image)
        except Exception:
            log.exception("RGB565 conversion failed")
            return False

        with self._lock:
            try:
                self.board.draw_image(0, 0, self.width, self.height, frame)
                self.frames_pushed += 1
                return True
            except Exception:
                # A revoked framebuffer surfaces here; the main loop
                # decides whether that is fatal.
                log.warning("framebuffer write failed", exc_info=True)
                return False

    def set_led(self, r: int, g: int, b: int, fade_ms: int = 0):
        """Set the RGB LED, skipping redundant writes."""
        if not self.settings.led_enabled:
            return
        if not getattr(self.board, "foreground_ready", True):
            return
        color = (int(r), int(g), int(b))
        if color == self._last_led:
            return
        self._last_led = color
        try:
            if fade_ms > 0 and hasattr(self.board, "set_rgb_fade"):
                self.board.set_rgb_fade(color[0], color[1], color[2], fade_ms)
            else:
                self.board.set_rgb(*color)
        except Exception:
            log.debug("LED write failed", exc_info=True)

    def set_backlight(self, brightness: int):
        try:
            self.board.set_backlight(max(0, min(100, int(brightness))))
        except Exception:
            log.debug("backlight write failed", exc_info=True)
