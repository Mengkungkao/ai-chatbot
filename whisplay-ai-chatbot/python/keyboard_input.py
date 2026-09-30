"""A USB or Bluetooth keyboard on the chatbot: type a question, or hold Space to talk.

    letters, Backspace   type a question (shown above the footer)
    Enter                ask it, once the chatbot is idle; on a prompt: allow
    Esc                  clear what was typed; on a prompt: deny;
                         otherwise leave the app, back to MFruit OS
    Space, held          talk, exactly like holding the button
                         (a space, once a question is being typed)

The keys come through MFruit OS's input controller (mfruit_sdk.input), the
same one every MFruit app uses: it reads every keyboard on the board and
ignores keys while another app has the screen. The button itself stays
with the Node core (src/device/display.ts), which already treats a press
as "talk" and counts clicks; the keyboard only speaks the same events to
it -- button_pressed / button_released, and text_input and
approval_answer for what a button cannot do.
"""

from __future__ import annotations

import threading
from typing import Callable

from mfruit_sdk.input import BACK, CHAR, ERASE, SELECT, TALK_END, TALK_START, Action

MAX_QUESTION = 500


class KeyboardQuestions:
    def __init__(self, send: Callable[[dict], None], leave: Callable[[], None],
                 changed: Callable[[], None], idle: Callable[[], bool],
                 approving: Callable[[], bool]):
        self.send = send            # an event for the Node core
        self.leave = leave          # quit the app
        self.changed = changed      # the screen needs redrawing
        self.idle = idle            # the chatbot can take a question now
        self.approving = approving  # an Allow / Deny prompt is up
        self.text: str | None = None
        self._lock = threading.Lock()

    @property
    def typing(self) -> bool:
        return self.text is not None

    def on_action(self, action: Action):
        name = action.name
        if name == TALK_START:
            self.send({"event": "button_pressed"})
            return
        if name == TALK_END:
            self.send({"event": "button_released"})
            return
        if self.approving() and name in (SELECT, BACK):
            self.send({"event": "approval_answer", "approved": name == SELECT})
            return
        if name == CHAR:
            with self._lock:
                text = (self.text or "") + action.char
                if not text.strip():
                    return          # a leading space starts nothing
                self.text = text[:MAX_QUESTION]
        elif name == ERASE:
            with self._lock:
                if self.text is None:
                    return
                self.text = self.text[:-1] or None
        elif name == SELECT:
            with self._lock:
                question = (self.text or "").strip()
                if not question or not self.idle():
                    return          # nothing to ask, or still busy: keep it
                self.text = None
            self.send({"event": "text_input", "text": question})
        elif name == BACK:
            with self._lock:
                typing = self.text is not None
                self.text = None
            if not typing:
                self.leave()
                return
        else:
            return
        self.changed()

    def hints(self, keyboard: bool, double_click: str = "auto-talk") -> list:
        """Footer hints, or [] where the reply needs the whole screen."""
        if self.text is not None:
            return ([("Enter", "ask"), ("Esc", "cancel")] if self.idle()
                    else [("Esc", "cancel")])
        if self.approving() or not self.idle():
            return []
        middle = ("type", "to ask") if keyboard else ("2×", double_click)
        return [("hold", "talk"), middle, ("4×", "exit")]
