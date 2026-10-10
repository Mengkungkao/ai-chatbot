"""Shown by run.sh instead of the chatbot while its API keys are missing.

mFruit OS keeps the app's .env in its data folder (WHISPLAY_OS_APP_DATA), so
the keys survive updates; the Fruit Store cannot ask for them on this screen.
Any press, or mFruit OS asking the app to leave, exits.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mfruit_sdk.ui import Canvas, footer, status_bar, to_rgb565  # noqa: E402
from mfruit_sdk.ui.theme import SCREEN_W  # noqa: E402
from whisplay_client import create_whisplay_hardware  # noqa: E402


def lines_for(path: str) -> list:
    """The .env path in pieces that fit the screen, split after slashes."""
    home = os.path.expanduser("~")
    shown = "~" + path[len(home):] if path.startswith(home + os.sep) else path
    pieces, line = [], ""
    for part in shown.split("/"):
        piece = part + "/"
        if line and len(line) + len(piece) > 24:
            pieces.append(line)
            line = ""
        line += piece
    pieces.append(line.rstrip("/"))
    return pieces


def render(path: str) -> Canvas:
    c = Canvas()
    t = c.theme
    status_bar(c, "AI Chatbot")
    y = 64
    c.text(SCREEN_W // 2, y, "Add your API keys", 18, "bold", t.warning, anchor="ma")
    y += 34
    for line in ("Copy your .env file", "over SSH to:"):
        c.text(SCREEN_W // 2, y, line, 13, "regular", t.text_muted, anchor="ma")
        y += 18
    y += 6
    for line in lines_for(path):
        c.text(SCREEN_W // 2, y, line, 13, "semibold", t.text, anchor="ma")
        y += 18
    y += 6
    c.text(SCREEN_W // 2, y, "then open AI Chatbot again.", 13, "regular", t.text_muted,
           anchor="ma")
    footer(c, [("tap", "exit")])
    return c


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else ".env"
    print(f"[AI Chatbot] no API keys: {path} is missing", flush=True)
    board = create_whisplay_hardware()
    leave = threading.Event()
    for hook in ("on_button_release", "on_exit_request"):
        if hasattr(board, hook):
            getattr(board, hook)(leave.set)
    if hasattr(board, "on_focus_revoked"):
        board.on_focus_revoked(lambda _payload=None: leave.set())
    frame = render(path)
    board.draw_image(0, 0, frame.width, frame.height, to_rgb565(frame.image))
    leave.wait()
    if hasattr(board, "cleanup"):
        board.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
