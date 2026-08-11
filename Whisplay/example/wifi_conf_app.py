#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "runtime"))
if RUNTIME_DIR not in sys.path:
    sys.path.append(RUNTIME_DIR)

from whisplay_client import create_whisplay_hardware

SERVICE_NAME = "sugar-wifi-config.service"
SERVICE_UNIT_PATH = "/etc/systemd/system/sugar-wifi-config.service"
POLL_INTERVAL_SEC = 2.0
LONG_PRESS_SEC = 1.0


def _load_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _rgb565_bytes(image: Image.Image) -> bytes:
    rgb = image.convert("RGB")
    out = bytearray()
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = rgb.getpixel((x, y))
            value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out.append((value >> 8) & 0xFF)
            out.append(value & 0xFF)
    return bytes(out)


def _read_ble_name_key() -> tuple[str, str]:
    name, key = "raspberrypi", "pisugar"
    try:
        with open(SERVICE_UNIT_PATH, "r", encoding="utf-8") as fp:
            text = fp.read()
        name_match = re.search(r"--name\s+(\S+)", text)
        key_match = re.search(r"--key\s+(\S+)", text)
        if name_match:
            name = name_match.group(1)
        if key_match:
            key = key_match.group(1)
    except Exception:
        pass
    return name, key


class WifiConfApp:
    def __init__(self):
        self.board = create_whisplay_hardware(
            app_id=os.getenv("WHISPLAY_APP_ID", "whisplay-wifi-conf"),
            display_name="WiFi Conf",
            icon="BC",
            persist=True,
            exit_gesture="quad_click",
            priority=150,
            use_daemon_default_log=True,
        )
        self.running = True
        self.ble_name, self.ble_key = _read_ble_name_key()
        self.busy = False
        self.status_line = ""
        self._last_state = None
        self._last_poll_at = 0.0
        self._button_down_at = 0.0

        self.title_font = _load_font(22, bold=True)
        self.body_font = _load_font(16)
        self.small_font = _load_font(13)

        self.board.on_button_press(self._on_press)
        self.board.on_button_release(self._on_release)
        if hasattr(self.board, "on_exit_request"):
            self.board.on_exit_request(self._on_exit)
        if hasattr(self.board, "on_focus_revoked"):
            self.board.on_focus_revoked(self._on_revoked)

    def _on_exit(self, _payload=None):
        self.running = False

    def _on_revoked(self, _payload=None):
        self.running = False

    def _on_press(self):
        self._button_down_at = time.time()

    def _on_release(self):
        if self.busy:
            return
        held = time.time() - self._button_down_at if self._button_down_at else 0.0
        self._button_down_at = 0.0
        if held < LONG_PRESS_SEC:
            self._toggle_service()

    def _service_active(self) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", SERVICE_NAME],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() == "active"
        except Exception:
            return False

    def _toggle_service(self):
        self.busy = True
        self.status_line = "Working..."
        self._render(force=True)
        action = "stop" if self._service_active() else "start"
        try:
            result = subprocess.run(
                ["sudo", "-n", "systemctl", action, SERVICE_NAME],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                self.status_line = "BLE stopped" if action == "stop" else "BLE started"
            else:
                self.status_line = (result.stderr or result.stdout or "Failed").strip()[:60]
        except Exception as exc:
            self.status_line = str(exc)[:60]
        self.busy = False
        self._last_poll_at = 0.0

    def _wifi_ssid(self) -> str:
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if line.startswith("yes:"):
                    return line.split(":", 1)[1] or "(hidden)"
        except Exception:
            pass
        return ""

    def _render(self, force: bool = False):
        active = self._service_active()
        ssid = self._wifi_ssid()
        state = (active, ssid, self.status_line, self.busy)
        if not force and state == self._last_state:
            return
        self._last_state = state

        width, height = self.board.LCD_WIDTH, self.board.LCD_HEIGHT
        image = Image.new("RGB", (width, height), (11, 16, 24))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (12, 16, width - 12, height - 16),
            radius=18, fill=(20, 28, 40), outline=(40, 55, 72), width=2,
        )

        accent = (60, 190, 100) if active else (90, 100, 115)
        draw.rounded_rectangle((20, 22, width - 20, 58), radius=12, fill=accent)
        draw.text((30, 31), "WIFI CONFIG (BLE)", fill=(255, 255, 255), font=self.small_font)

        y = 76
        draw.text(
            (24, y),
            "BLE ON" if active else "BLE OFF",
            fill=(120, 230, 150) if active else (200, 90, 90),
            font=self.title_font,
        )
        y += 32

        for line in [
            f"Name: {self.ble_name}",
            f"Key:  {self.ble_key}",
            "",
            f"WiFi: {ssid}" if ssid else "WiFi: not connected",
        ]:
            draw.text((24, y), line, fill=(214, 225, 236), font=self.body_font)
            y += 22

        footer_top = height - 70
        draw.rounded_rectangle((20, footer_top, width - 20, height - 22), radius=12, fill=(28, 37, 50))
        footer = self.status_line or ("Press: turn off" if active else "Press: turn on")
        draw.text((28, footer_top + 8), footer, fill=(150, 205, 255), font=self.small_font)
        draw.text((28, footer_top + 30), "x4 click: back to desktop", fill=(120, 140, 160), font=self.small_font)

        self.board.draw_image(0, 0, width, height, _rgb565_bytes(image))

    def run(self):
        try:
            while self.running:
                now = time.time()
                if now - self._last_poll_at >= POLL_INTERVAL_SEC:
                    self._last_poll_at = now
                    self._render()
                time.sleep(0.2)
        finally:
            self.board.cleanup()


if __name__ == "__main__":
    WifiConfApp().run()
