#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
import re
import struct
import subprocess
import sys
import threading
import time

from PIL import Image, ImageDraw, ImageFont

try:
    import numpy as np
except Exception:
    np = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "runtime"))
DAEMON_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "daemon"))
if RUNTIME_DIR not in sys.path:
    sys.path.append(RUNTIME_DIR)

from whisplay_client import create_whisplay_hardware

SERVICE_NAME = "sugar-wifi-config.service"
SERVICE_UNIT_PATH = "/etc/systemd/system/sugar-wifi-config.service"
POLL_INTERVAL_SEC = 2.0
FRAME_INTERVAL_SEC = 0.08
LONG_PRESS_SEC = 1.0
SSID_MAX_LEN = 32
PASSWORD_MAX_LEN = 63

MARGIN = 14
TEXT_X = 24

MODE_MENU = "menu"
MODE_SCAN = "scan"
MODE_SSID = "ssid"
MODE_PASSWORD = "password"
MODE_CONNECTING = "connecting"
MODE_RESULT = "result"

MENU_TOGGLE_BLE = 0
MENU_SCAN = 1
MENU_EXIT = 2
MENU_COUNT = 3

# Fixed rows around the scanned networks, in list order.
SCAN_LEADING = ("Back", "Type hidden network...")
VISIBLE_SCAN_ROWS = 6
OPEN_SECURITY = {"", "--", "none", "open"}
# First pass shows only what is comfortably in range; Rescan drops the floor.
NEARBY_MIN_SIGNAL = 40


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
    if np is not None:
        pixels = np.asarray(rgb, dtype=np.uint16)
        packed = (
            ((pixels[:, :, 0] & 0xF8) << 8)
            | ((pixels[:, :, 1] & 0xFC) << 3)
            | (pixels[:, :, 2] >> 3)
        )
        return packed.astype(">u2").tobytes()
    out = bytearray()
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = rgb.getpixel((x, y))
            value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out.append((value >> 8) & 0xFF)
            out.append(value & 0xFF)
    return bytes(out)


def _split_nmcli(line: str) -> list[str]:
    """nmcli -t escapes a literal colon inside a field as \\:"""
    fields, current, escaped = [], "", False
    for char in line:
        if escaped:
            current += char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append(current)
            current = ""
        else:
            current += char
    fields.append(current)
    return fields


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


LETTER_KEYCODES = tuple(range(16, 26)) + tuple(range(30, 39)) + tuple(range(44, 51))


def _has_letter_keys(key_bits: str) -> bool:
    """The kernel prints capability bitmaps as unsigned longs, most significant
    word first, so word width follows the userspace long."""
    words = key_bits.split()
    if not words:
        return False
    word_bits = struct.calcsize("l") * 8
    bitmap = 0
    for index, word in enumerate(reversed(words)):
        try:
            bitmap |= int(word, 16) << (word_bits * index)
        except ValueError:
            return False
    return all((bitmap >> code) & 1 for code in LETTER_KEYCODES)


def _keyboard_device_paths() -> list[str]:
    """Anything that reports a full letter row: USB, Bluetooth or virtual.
    HDMI-CEC receivers also claim a kbd handler but only carry remote keys,
    and udev gives them no *-kbd link, so filter on capabilities instead."""
    paths: list[str] = []
    try:
        with open("/proc/bus/input/devices", "r", encoding="utf-8") as fp:
            blocks = fp.read().split("\n\n")
    except OSError:
        return paths
    for block in blocks:
        handlers: list[str] = []
        key_bits = ""
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                handlers = line.split("=", 1)[1].split()
            elif line.startswith("B: KEY="):
                key_bits = line.split("=", 1)[1]
        if "kbd" not in handlers or not _has_letter_keys(key_bits):
            continue
        for token in handlers:
            if token.startswith("event"):
                device = os.path.join("/dev/input", token)
                if device not in paths and os.access(device, os.R_OK):
                    paths.append(device)
    return paths


def _make_keyboard_reader():
    """Reuse the daemon's evdev reader so the key map and hotplug loop stay
    shared, but narrow the device list to real keyboards."""
    module_path = os.path.join(DAEMON_DIR, "internal_apps", "keyboard.py")
    try:
        spec = importlib.util.spec_from_file_location("whisplay_external_keyboard", module_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return None

    class _AppKeyboardReader(module.ExternalKeyboardReader):
        def _candidate_paths(self) -> list[str]:
            return _keyboard_device_paths()

    return _AppKeyboardReader()


class WifiConfigApp:
    def __init__(self):
        self.board = create_whisplay_hardware(
            app_id=os.getenv("WHISPLAY_APP_ID", "whisplay-wifi-config"),
            display_name="WiFi Config",
            icon="WC",
            persist=True,
            exit_gesture="quad_click",
            priority=150,
            use_daemon_default_log=True,
        )
        self.running = True
        self.ble_name, self.ble_key = _read_ble_name_key()

        self.lock = threading.RLock()
        self.mode = MODE_MENU
        self.menu_index = MENU_TOGGLE_BLE
        self.ssid_buffer = ""
        self.password_buffer = ""
        self.status_line = ""
        self.busy = False

        self.networks: list[dict] = []
        self.scan_index = 0
        self.scan_window = 0
        self.scan_wide = False
        self.password_return = MODE_SCAN
        self.password_known_secured = False
        self.connect_ssid = ""
        self.connect_started_at = 0.0
        self.result_ok = False
        self.result_message = ""

        self.ble_active = False
        self.wifi_ssid = ""
        self.wifi_ip = ""
        self.keyboard_ready = False

        self._last_state = None
        self._last_poll_at = 0.0
        self._button_down_at = 0.0

        self.title_font = _load_font(20, bold=True)
        self.body_font = _load_font(15)
        self.row_font = _load_font(14)
        self.small_font = _load_font(12)

        self.keyboard = _make_keyboard_reader()
        self.can_sudo = self._probe_sudo()
        self.can_scan_wide = self._probe_scan_privilege()

        self.board.on_button_press(self._on_press)
        self.board.on_button_release(self._on_release)
        if hasattr(self.board, "on_exit_request"):
            self.board.on_exit_request(self._on_exit)
        if hasattr(self.board, "on_focus_revoked"):
            self.board.on_focus_revoked(self._on_revoked)

    # ---------- lifecycle ----------

    def _on_exit(self, _payload=None):
        self.running = False

    def _on_revoked(self, _payload=None):
        self.running = False

    # ---------- button ----------

    def _on_press(self):
        self._button_down_at = time.time()

    def _on_release(self):
        held = time.time() - self._button_down_at if self._button_down_at else 0.0
        self._button_down_at = 0.0
        with self.lock:
            if self.busy:
                return
            if self.mode == MODE_MENU:
                if held >= LONG_PRESS_SEC:
                    self._activate_menu_item()
                else:
                    self.menu_index = (self.menu_index + 1) % MENU_COUNT
                return
            if self.mode == MODE_SCAN:
                if held >= LONG_PRESS_SEC:
                    self._activate_scan_row()
                else:
                    self._move_scan(1)
                return
            if self.mode == MODE_RESULT:
                self._dismiss_result()
                return
            if self.mode == MODE_CONNECTING:
                return
            if held >= LONG_PRESS_SEC:
                self._cancel_entry()

    # ---------- keyboard ----------

    def _on_key(self, action):
        with self.lock:
            if self.busy:
                return
            if self.mode == MODE_MENU:
                self._menu_key(action)
            elif self.mode == MODE_SCAN:
                self._scan_key(action)
            elif self.mode == MODE_RESULT:
                self._dismiss_result()
            elif self.mode == MODE_CONNECTING:
                return
            else:
                self._entry_key(action)

    def _menu_key(self, action):
        if action == "up":
            self.menu_index = (self.menu_index - 1) % MENU_COUNT
        elif action == "down":
            self.menu_index = (self.menu_index + 1) % MENU_COUNT
        elif action == "submit":
            self._activate_menu_item()
        elif action == "cancel":
            self.running = False

    def _scan_key(self, action):
        if action == "up":
            self._move_scan(-1)
        elif action == "down":
            self._move_scan(1)
        elif action == "submit":
            self._activate_scan_row()
        elif action == "cancel":
            self._leave_scan()

    def _scan_row_count(self) -> int:
        return len(SCAN_LEADING) + len(self.networks) + 1  # + the trailing rescan

    def _move_scan(self, delta: int):
        total = self._scan_row_count()
        if total <= 0:
            return
        self.scan_index = (self.scan_index + delta) % total
        if self.scan_index < self.scan_window:
            self.scan_window = self.scan_index
        elif self.scan_index >= self.scan_window + VISIBLE_SCAN_ROWS:
            self.scan_window = self.scan_index - VISIBLE_SCAN_ROWS + 1
        self.scan_window = max(0, min(self.scan_window, max(0, total - VISIBLE_SCAN_ROWS)))

    def _leave_scan(self):
        self.mode = MODE_MENU
        self.status_line = ""

    def _activate_scan_row(self):
        index = self.scan_index
        if index == 0:
            self._leave_scan()
            return
        if index == 1:
            self.mode = MODE_SSID
            self.ssid_buffer = ""
            self.password_buffer = ""
            self.password_return = MODE_SSID
            self.status_line = "Type the network name"
            return
        position = index - len(SCAN_LEADING)
        if position >= len(self.networks):
            self.status_line = "Scanning wider range..."
            self._spawn("wifi-scan", lambda: self._scan(wide=True))
            return
        network = self.networks[position]
        self.ssid_buffer = network["ssid"]
        self.password_buffer = ""
        if network["security"].strip().lower() in OPEN_SECURITY:
            self._start_connect(network["ssid"], "")
            return
        self.password_return = MODE_SCAN
        self.password_known_secured = True
        self.mode = MODE_PASSWORD
        self.status_line = ""

    def _dismiss_result(self):
        if self.result_ok or not self.networks:
            self.mode = MODE_MENU
        else:
            self.mode = MODE_SCAN
        self.result_message = ""
        self.status_line = ""

    def _entry_key(self, action):
        if action == "cancel":
            self._cancel_entry()
            return
        if action == "backspace":
            if self.mode == MODE_SSID:
                self.ssid_buffer = self.ssid_buffer[:-1]
            else:
                self.password_buffer = self.password_buffer[:-1]
            return
        if action == "submit":
            self._submit_entry()
            return
        if isinstance(action, tuple) and len(action) == 2 and action[0] == "char":
            if self.mode == MODE_SSID:
                if len(self.ssid_buffer) < SSID_MAX_LEN:
                    self.ssid_buffer += action[1]
            elif len(self.password_buffer) < PASSWORD_MAX_LEN:
                self.password_buffer += action[1]

    # ---------- menu actions ----------

    def _activate_menu_item(self):
        if self.menu_index == MENU_TOGGLE_BLE:
            self.status_line = "Working..."
            self._spawn("ble-toggle", self._toggle_service)
        elif self.menu_index == MENU_SCAN:
            self.mode = MODE_SCAN
            self.scan_index = len(SCAN_LEADING) if self.networks else 0
            self.scan_window = 0
            self.status_line = "Checking nearby..."
            self._spawn("wifi-scan", lambda: self._scan(wide=False))
        elif self.menu_index == MENU_EXIT:
            self.running = False

    def _cancel_entry(self):
        if self.mode == MODE_PASSWORD:
            self.password_buffer = ""
            self.mode = self.password_return
            self.status_line = "" if self.mode == MODE_SCAN else "Type the network name"
            return
        self.mode = MODE_SCAN if self.networks else MODE_MENU
        self.ssid_buffer = ""
        self.password_buffer = ""
        self.status_line = ""

    def _submit_entry(self):
        if self.mode == MODE_SSID:
            if not self.ssid_buffer.strip():
                self.status_line = "SSID cannot be empty"
                return
            self.mode = MODE_PASSWORD
            self.password_return = MODE_SSID
            self.password_known_secured = False
            self.password_buffer = ""
            self.status_line = "Blank = open network"
            return
        self._start_connect(self.ssid_buffer.strip(), self.password_buffer)

    # ---------- workers ----------

    def _spawn(self, name: str, target):
        with self.lock:
            if self.busy:
                return
            self.busy = True
        threading.Thread(target=self._run_worker, args=(target,), name=name, daemon=True).start()

    def _run_worker(self, target):
        try:
            target()
        except Exception as exc:
            with self.lock:
                self.status_line = str(exc)[:60]
        finally:
            with self.lock:
                self.busy = False
                self._last_poll_at = 0.0

    def _probe_sudo(self) -> bool:
        try:
            return subprocess.run(
                ["sudo", "-n", "true"], capture_output=True, timeout=5
            ).returncode == 0
        except Exception:
            return False

    def _probe_scan_privilege(self) -> bool:
        """Whether a real sweep is possible at all. Without root and without
        polkit saying yes, NetworkManager still answers a rescan request - it
        just answers it from the cache, so this has to be asked up front."""
        if self.can_sudo:
            return True
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "permission,value", "general", "permissions"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return False
        for line in result.stdout.splitlines():
            fields = _split_nmcli(line)
            if len(fields) >= 2 and fields[0].endswith("wifi.scan"):
                return fields[1].strip() == "yes"
        return False

    def _short_error(self, text: str) -> str:
        lowered = text.lower()
        if not self.can_sudo and ("authentication" in lowered or "not authorized" in lowered):
            return "Needs root - see sudoers setup"
        return text.replace("Error: ", "")

    def _run_privileged(self, args: list[str], timeout: float):
        """Root first, deliberately. A daemon child has no login session for
        polkit to authenticate against, and NetworkManager does not fail
        loudly when it lacks authorisation: an unprivileged
        `wifi list --rescan yes` exits 0 and returns the stale cache, so
        there is no error to retry on. systemd is honest about it
        ("Interactive authentication required"), NetworkManager is not."""
        if self.can_sudo:
            try:
                result = subprocess.run(
                    ["sudo", "-n", *args], capture_output=True, text=True, timeout=timeout
                )
            except subprocess.TimeoutExpired:
                raise
            blob = f"{result.stdout} {result.stderr}".lower()
            if result.returncode == 0 or "sudo:" not in blob:
                return result
            # sudoers refused this specific command; try as ourselves.
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

    def _toggle_service(self):
        action = "stop" if self._service_active() else "start"
        result = self._run_privileged(["systemctl", action, SERVICE_NAME], timeout=15)
        with self.lock:
            if result.returncode == 0:
                self.status_line = "BLE stopped" if action == "stop" else "BLE started"
            else:
                self.status_line = self._short_error(
                    (result.stderr or result.stdout or "Failed").strip()
                )[:60]

    def _start_connect(self, ssid: str, password: str):
        self.mode = MODE_CONNECTING
        self.connect_ssid = ssid
        self.connect_started_at = time.time()
        self.password_buffer = ""
        self.status_line = ""
        self._spawn("wifi-connect", lambda: self._connect(ssid, password))

    def _parse_networks(self, output: str) -> list[dict]:
        strongest: dict[str, dict] = {}
        for line in output.splitlines():
            fields = _split_nmcli(line)
            if len(fields) < 4:
                continue
            in_use, ssid, signal, security = fields[0], fields[1], fields[2], fields[3]
            if not ssid:
                continue
            try:
                strength = int(signal)
            except ValueError:
                strength = 0
            active = in_use.strip() == "*"
            known = strongest.get(ssid)
            if known is None:
                strongest[ssid] = {
                    "ssid": ssid,
                    "signal": strength,
                    "security": security,
                    "active": active,
                }
            else:
                # One SSID, several BSSIDs: take the best signal, but the
                # in-use flag belongs to the SSID even when a weaker radio
                # carries it.
                known["active"] = known["active"] or active
                if strength > known["signal"]:
                    known["signal"] = strength
                    known["security"] = security
        return sorted(strongest.values(), key=lambda n: (not n["active"], -n["signal"]))

    def _scan(self, wide: bool):
        """Two tiers. The first pass reads NetworkManager's cached scan: no
        radio sweep, so it costs no power and lands instantly, then keeps only
        what is comfortably in range. Rescan forces a real sweep and shows
        everything. An empty first pass escalates on its own, so entering the
        list never dead-ends on a cold or stale cache."""
        args = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"]

        if wide:
            sweep = ["--rescan", "yes"] if self.can_scan_wide else ["--rescan", "no"]
            found = self._parse_networks(
                self._run_privileged(args + sweep, timeout=45 if self.can_scan_wide else 20).stdout
            )
        else:
            # --rescan defaults to "auto", which still sweeps when the cache is
            # older than 30s. "no" is what actually keeps the radio idle.
            cached = self._parse_networks(
                self._run_privileged(args + ["--rescan", "no"], timeout=20).stdout
            )
            found = [n for n in cached if n["signal"] >= NEARBY_MIN_SIGNAL]
            # Nothing to choose from - only the network we are already on, or
            # nothing at all - means the cache is too cold to be useful.
            if not any(not n["active"] for n in found):
                wide = True
                found = self._parse_networks(
                    self._run_privileged(args + ["--rescan", "yes"], timeout=45).stdout
                )

        with self.lock:
            self.networks = found
            self.scan_wide = wide
            if found:
                if not wide:
                    self.status_line = f"{len(found)} nearby"
                elif self.can_scan_wide:
                    self.status_line = f"{len(found)} networks"
                else:
                    self.status_line = f"{len(found)} cached (needs root)"
                self.scan_index = len(SCAN_LEADING)
            else:
                self.status_line = "No networks found"
                self.scan_index = 0
            self.scan_window = 0
            self._move_scan(0)

    def _connect(self, ssid: str, password: str):
        args = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        if not self._ssid_visible(ssid):
            args += ["hidden", "yes"]
        try:
            result = self._run_privileged(args, timeout=90)
            ok = result.returncode == 0
            message = (result.stdout if ok else (result.stderr or result.stdout)).strip()
        except Exception as exc:
            ok, message = False, str(exc)
        with self.lock:
            self.result_ok = ok
            self.result_message = (
                message if ok else self._short_error(message or "Failed")
            ) or ("Connected" if ok else "Failed")
            self.mode = MODE_RESULT
            self.status_line = ""
            if ok:
                self.ssid_buffer = ""

    # ---------- status ----------

    def _service_active(self) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", SERVICE_NAME],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() == "active"
        except Exception:
            return False

    def _ssid_visible(self, ssid: str) -> bool:
        with self.lock:
            if self.networks:
                return any(network["ssid"] == ssid for network in self.networks)
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "SSID", "device", "wifi", "list"],
                capture_output=True, text=True, timeout=10,
            )
            return any(line.replace("\\:", ":") == ssid for line in result.stdout.splitlines())
        except Exception:
            return True

    def _wifi_state(self) -> tuple[str, str]:
        ssid, ipv4 = "", ""
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if line.startswith("yes:"):
                    ssid = line.split(":", 1)[1] or "(hidden)"
                    break
        except Exception:
            pass
        if ssid:
            try:
                result = subprocess.run(
                    ["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", "wlan0"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    if ":" in line:
                        ipv4 = line.split(":", 1)[1].split("/")[0].strip()
                        if ipv4:
                            break
            except Exception:
                pass
        return ssid, ipv4

    def _poll_status(self):
        active = self._service_active()
        ssid, ipv4 = self._wifi_state()
        keyboard_ready = bool(_keyboard_device_paths())
        with self.lock:
            self.ble_active = active
            self.wifi_ssid = ssid
            self.wifi_ip = ipv4
            self.keyboard_ready = keyboard_ready

    # ---------- rendering ----------

    def _snapshot(self) -> dict:
        with self.lock:
            return {
                "mode": self.mode,
                "menu_index": self.menu_index,
                "ssid": self.ssid_buffer,
                "password_len": len(self.password_buffer),
                "status": self.status_line,
                "busy": self.busy,
                "ble_active": self.ble_active,
                "wifi_ssid": self.wifi_ssid,
                "wifi_ip": self.wifi_ip,
                "keyboard_ready": self.keyboard_ready,
                "password_known_secured": self.password_known_secured,
                "scan_index": self.scan_index,
                "scan_window": self.scan_window,
                "scan_wide": self.scan_wide,
                "networks": tuple(
                    (
                        n["ssid"],
                        n["signal"],
                        n["active"],
                        n["security"].strip().lower() in OPEN_SECURITY,
                    )
                    for n in self.networks
                ),
                "connect_ssid": self.connect_ssid,
                "result_ok": self.result_ok,
                "result_message": self.result_message,
                # Drives the sweep animation and the elapsed counter.
                "phase": int(time.time() * 8) % 24 if self.mode == MODE_CONNECTING else 0,
                "elapsed": int(time.time() - self.connect_started_at)
                if self.mode == MODE_CONNECTING and self.connect_started_at
                else 0,
            }

    def _render(self, force: bool = False):
        state = self._snapshot()
        key = tuple(sorted(state.items()))
        if not force and key == self._last_state:
            return
        self._last_state = key

        width, height = self.board.LCD_WIDTH, self.board.LCD_HEIGHT
        image = Image.new("RGB", (width, height), (11, 16, 24))
        draw = ImageDraw.Draw(image)

        accent = (60, 190, 100) if state["ble_active"] else (90, 100, 115)
        draw.rounded_rectangle((MARGIN, 10, width - MARGIN, 44), radius=12, fill=accent)
        draw.text((TEXT_X, 18), "WIFI CONFIG", fill=(255, 255, 255), font=self.title_font)

        mode = state["mode"]
        if mode == MODE_MENU:
            self._render_menu(draw, width, height, state)
        elif mode == MODE_SCAN:
            self._render_scan(draw, width, height, state)
        elif mode == MODE_CONNECTING:
            self._render_connecting(draw, width, height, state)
        elif mode == MODE_RESULT:
            self._render_result(draw, width, height, state)
        else:
            self._render_entry(draw, width, height, state)

        self._render_footer(draw, width, height, state)
        self.board.draw_image(0, 0, width, height, _rgb565_bytes(image))

    def _fit(self, draw, text: str, font, max_width: float) -> str:
        if draw.textlength(text, font=font) <= max_width:
            return text
        while text and draw.textlength(text + "...", font=font) > max_width:
            text = text[:-1]
        return text + "..."

    def _render_menu(self, draw, width, height, state):
        text_width = width - 2 * TEXT_X
        draw.rounded_rectangle((MARGIN, 52, width - MARGIN, 142), radius=12, fill=(20, 28, 40))
        draw.text(
            (TEXT_X, 58),
            "BLE ON" if state["ble_active"] else "BLE OFF",
            fill=(120, 230, 150) if state["ble_active"] else (200, 90, 90),
            font=self.title_font,
        )
        # Fixed line count keeps the card from resizing when the IP appears.
        details = [
            f"Name: {self.ble_name}",
            f"Key:  {self.ble_key}",
            f"WiFi: {state['wifi_ssid'] or 'not connected'}",
            f"IP:   {state['wifi_ip'] or '-'}",
        ]
        y = 84
        for line in details:
            draw.text((TEXT_X, y), self._fit(draw, line, self.small_font, text_width),
                      fill=(214, 225, 236), font=self.small_font)
            y += 14

        items = [
            ("Turn BLE off" if state["ble_active"] else "Turn BLE on", ""),
            ("Scan networks", "kbd" if state["keyboard_ready"] else "no kbd"),
            ("Back to desktop", ""),
        ]
        y = 150
        for index, (label, meta) in enumerate(items):
            selected = index == state["menu_index"]
            if selected:
                draw.rounded_rectangle((MARGIN, y, width - MARGIN, y + 26), radius=8, fill=(38, 62, 92))
            meta_width = draw.textlength(meta, font=self.small_font) if meta else 0
            meta_x = width - TEXT_X - meta_width
            draw.text(
                (TEXT_X, y + 6),
                self._fit(draw, label, self.row_font, meta_x - TEXT_X - 8),
                fill=(255, 255, 255) if selected else (170, 186, 204),
                font=self.row_font,
            )
            if meta:
                draw.text(
                    (meta_x, y + 9), meta,
                    fill=(140, 190, 240) if selected else (100, 116, 134),
                    font=self.small_font,
                )
            y += 28

    def _wrap(self, draw, text: str, font, max_width: float, max_lines: int) -> list[str]:
        lines, current = [], ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = word
                if len(lines) == max_lines:
                    break
            else:
                current = candidate
        if current and len(lines) < max_lines:
            lines.append(current)
        return [self._fit(draw, line, font, max_width) for line in lines]

    def _render_scan(self, draw, width, height, state):
        networks = state["networks"]
        wide = state["scan_wide"]
        lead_count = len(SCAN_LEADING)
        rows = [(name, "") for name in SCAN_LEADING]
        rows += [
            (ssid, "now" if active else (f"{signal}% open" if is_open else f"{signal}%"))
            for ssid, signal, active, is_open in networks
        ]
        rows.append(("Rescan" if wide else "Rescan wider range", ""))
        last_network = lead_count + len(networks) - 1

        draw.text((TEXT_X, 50), "All networks" if wide else "Nearby",
                  fill=(130, 180, 230), font=self.small_font)
        counter = f"{state['scan_index'] + 1}/{len(rows)}"
        draw.text((width - TEXT_X - draw.textlength(counter, font=self.small_font), 50),
                  counter, fill=(100, 116, 134), font=self.small_font)

        y = 66
        window = state["scan_window"]
        for offset in range(VISIBLE_SCAN_ROWS):
            index = window + offset
            if index >= len(rows):
                break
            label, meta = rows[index]
            selected = index == state["scan_index"]
            if selected:
                draw.rounded_rectangle((MARGIN, y, width - MARGIN, y + 26), radius=8, fill=(38, 62, 92))
            meta_width = draw.textlength(meta, font=self.small_font) if meta else 0
            meta_x = width - TEXT_X - meta_width
            is_action = index < lead_count or index > last_network
            draw.text(
                (TEXT_X, y + 6),
                self._fit(draw, label, self.row_font, meta_x - TEXT_X - 8),
                fill=(255, 255, 255) if selected else ((150, 166, 184) if is_action else (170, 186, 204)),
                font=self.row_font,
            )
            if meta:
                draw.text((meta_x, y + 9), meta,
                          fill=(120, 230, 150) if meta == "now" else
                               ((140, 190, 240) if selected else (100, 116, 134)),
                          font=self.small_font)
            y += 28
            # Rules fence the network list off from the fixed rows.
            if networks and index in (lead_count - 1, last_network):
                draw.line((MARGIN, y + 2, width - MARGIN, y + 2), fill=(48, 62, 80), width=1)
                y += 4

    def _render_connecting(self, draw, width, height, state):
        text_width = width - 2 * TEXT_X
        draw.text((TEXT_X, 62), "Connecting", fill=(120, 200, 255), font=self.title_font)
        draw.text((TEXT_X, 94),
                  self._fit(draw, state["connect_ssid"] or "network", self.body_font, text_width),
                  fill=(255, 255, 255), font=self.body_font)

        track_top, track_height = 130, 10
        span = width - 2 * MARGIN
        draw.rounded_rectangle((MARGIN, track_top, width - MARGIN, track_top + track_height),
                               radius=5, fill=(24, 34, 48))
        segment = span // 3
        travel = (state["phase"] / 24.0) * (span + segment) - segment
        left = MARGIN + max(0, travel)
        right = MARGIN + min(span, travel + segment)
        if right > left:
            draw.rounded_rectangle((left, track_top, right, track_top + track_height),
                                   radius=5, fill=(60, 190, 100))

        draw.text((TEXT_X, 156), f"{state['elapsed']}s elapsed",
                  fill=(150, 166, 184), font=self.small_font)
        draw.text((TEXT_X, 178), "Asking NetworkManager to join",
                  fill=(118, 136, 156), font=self.small_font)
        draw.text((TEXT_X, 194), "this network. This can take a",
                  fill=(118, 136, 156), font=self.small_font)
        draw.text((TEXT_X, 210), "few seconds.", fill=(118, 136, 156), font=self.small_font)

    def _render_result(self, draw, width, height, state):
        text_width = width - 2 * TEXT_X
        ok = state["result_ok"]
        draw.rounded_rectangle((MARGIN, 56, width - MARGIN, 122), radius=12,
                               fill=(18, 40, 28) if ok else (44, 22, 26))
        draw.text((TEXT_X, 64), "Connected" if ok else "Not connected",
                  fill=(120, 230, 150) if ok else (240, 120, 120), font=self.title_font)
        draw.text((TEXT_X, 96),
                  self._fit(draw, state["connect_ssid"] or "", self.body_font, text_width),
                  fill=(214, 225, 236), font=self.body_font)

        y = 136
        for line in self._wrap(draw, state["result_message"], self.small_font, text_width, 5):
            draw.text((TEXT_X, y), line, fill=(150, 166, 184), font=self.small_font)
            y += 16

    def _render_entry(self, draw, width, height, state):
        entering_ssid = state["mode"] == MODE_SSID
        text_width = width - 2 * TEXT_X

        draw.text(
            (TEXT_X, 52),
            "Hidden network" if entering_ssid else "Password",
            fill=(130, 180, 230), font=self.small_font,
        )
        chip = "kbd" if state["keyboard_ready"] else "no kbd"
        draw.text(
            (width - TEXT_X - draw.textlength(chip, font=self.small_font), 52), chip,
            fill=(120, 230, 150) if state["keyboard_ready"] else (255, 180, 90),
            font=self.small_font,
        )

        draw.rounded_rectangle((MARGIN, 70, width - MARGIN, 118), radius=12, fill=(18, 28, 42))
        draw.text((TEXT_X, 76), "SSID" if entering_ssid else "Password",
                  fill=(255, 255, 255), font=self.small_font)
        if entering_ssid:
            typed = bool(state["ssid"])
            value = state["ssid"][-22:] if typed else "<empty>"
        else:
            typed = state["password_len"] > 0
            value = "*" * min(state["password_len"], 22) if typed else (
                "<empty>" if state["password_known_secured"] else "<open network>"
            )
        draw.text((TEXT_X, 92), value,
                  fill=(120, 255, 140) if typed else (110, 124, 140), font=self.body_font)

        if not entering_ssid and state["ssid"]:
            draw.text((TEXT_X, 124),
                      self._fit(draw, f"for {state['ssid']}", self.small_font, text_width),
                      fill=(150, 166, 184), font=self.small_font)

        draw.line((MARGIN, 144, width - MARGIN, 144), fill=(48, 62, 80), width=1)
        guide = [
            ("Enter", "next" if entering_ssid else "connect"),
            ("Esc", "back"),
            ("Backspace", "delete"),
            ("Hold button", "cancel"),
        ]
        y = 154
        for name, meaning in guide:
            draw.text((TEXT_X, y), name, fill=(214, 225, 236), font=self.small_font)
            draw.text((TEXT_X + 92, y), meaning, fill=(118, 136, 156), font=self.small_font)
            y += 18

    def _render_footer(self, draw, width, height, state):
        """The quad-click exit gesture stays live in the daemon; it just no
        longer takes up a line on screen."""
        top = height - 36
        draw.line((MARGIN, top, width - MARGIN, top), fill=(48, 62, 80), width=1)
        footer = state["status"]
        if not footer:
            mode = state["mode"]
            if mode == MODE_CONNECTING:
                footer = "Please wait"
            elif mode == MODE_RESULT:
                footer = "Press to continue"
            elif state["busy"]:
                footer = "working..."
            elif mode in (MODE_MENU, MODE_SCAN):
                footer = "Press: next   Hold: select"
            else:
                footer = "Type on the USB keyboard"
        draw.text((TEXT_X, top + 10), self._fit(draw, footer, self.small_font, width - 2 * TEXT_X),
                  fill=(156, 214, 255), font=self.small_font)

    # ---------- main loop ----------

    def run(self):
        if self.keyboard is not None:
            self.keyboard.start(self._on_key)
        try:
            while self.running:
                now = time.time()
                if now - self._last_poll_at >= POLL_INTERVAL_SEC:
                    self._last_poll_at = now
                    self._poll_status()
                self._render()
                time.sleep(FRAME_INTERVAL_SEC)
        finally:
            if self.keyboard is not None:
                self.keyboard.stop()
            self.board.cleanup()


if __name__ == "__main__":
    WifiConfigApp().run()
