"""The keyboard on the chatbot: typed questions, Space to talk, Esc, prompts.

    cd python && python3 -m pytest -q test/test_keyboard_input.py

Keys go through mFruit OS's real input controller (mfruit_sdk), fed key
events directly, so ownership and the Space-while-typing rule are the
ones the device uses.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from mfruit_sdk.input import InputController  # noqa: E402
from mfruit_sdk.keys import DOWN, UP, KeyEvent  # noqa: E402

from keyboard_input import MAX_QUESTION, KeyboardQuestions  # noqa: E402

CODES = {"enter": 28, "escape": 1, "backspace": 14, "space": 57}


class Chatbot:
    """What chatbot-ui.py wires the keyboard to."""

    def __init__(self):
        self.sent, self.left, self.redraws = [], 0, 0
        self.idle, self.approving, self.has_screen = True, False, True
        self.keys = KeyboardQuestions(send=self.sent.append, leave=self.leave,
                                      changed=self.redraw, idle=lambda: self.idle,
                                      approving=lambda: self.approving)
        self.input = InputController(self.keys.on_action, talk=lambda: True,
                                     typing=lambda: self.keys.typing,
                                     active=lambda: self.has_screen,
                                     keyboard=False, threaded=False)

    def leave(self):
        self.left += 1

    def redraw(self):
        self.redraws += 1

    def key(self, name, action=DOWN):
        self.input.key_event(KeyEvent("key", name, action, CODES[name]))

    def type(self, text):
        for char in text:
            if char == " ":
                self.key("space")
                self.key("space", UP)
            else:
                self.input.key_event(KeyEvent("char", char, DOWN, 30))


@pytest.fixture
def bot():
    return Chatbot()


def test_a_typed_question_is_sent_on_enter(bot):
    bot.type("how tall is it")
    assert bot.keys.text == "how tall is it"
    bot.key("backspace")
    bot.key("enter")
    assert bot.sent == [{"event": "text_input", "text": "how tall is i"}]
    assert bot.keys.text is None and bot.redraws


def test_space_held_talks_like_the_button(bot):
    bot.key("space")
    bot.key("space", UP)
    assert bot.sent == [{"event": "button_pressed"}, {"event": "button_released"}]


def test_space_is_a_space_once_typing(bot):
    bot.type("a b")
    assert bot.keys.text == "a b"
    assert {"event": "button_pressed"} not in bot.sent


def test_a_question_waits_while_the_chatbot_is_busy(bot):
    bot.idle = False
    bot.type("next question")
    bot.key("enter")
    assert bot.sent == [] and bot.keys.text == "next question"   # kept, not lost
    bot.idle = True
    bot.key("enter")
    assert bot.sent == [{"event": "text_input", "text": "next question"}]


def test_escape_clears_then_leaves(bot):
    bot.type("oops")
    bot.key("escape")
    assert bot.keys.text is None and bot.left == 0
    bot.key("escape")
    assert bot.left == 1


def test_enter_and_escape_answer_a_prompt(bot):
    bot.approving = True
    bot.key("enter")
    bot.key("escape")
    assert bot.sent == [{"event": "approval_answer", "approved": True},
                        {"event": "approval_answer", "approved": False}]
    assert bot.left == 0


def test_nothing_while_another_app_has_the_screen(bot):
    bot.has_screen = False
    bot.type("hello")
    bot.key("enter")
    bot.key("escape")
    assert bot.sent == [] and bot.keys.text is None and bot.left == 0


def test_a_question_is_capped(bot):
    for _ in range(MAX_QUESTION + 20):
        bot.input.key_event(KeyEvent("char", "x", DOWN, 45))
    assert len(bot.keys.text) == MAX_QUESTION


def test_footer_hints(bot):
    assert bot.keys.hints(keyboard=True) == [("hold", "talk"), ("type", "to ask"), ("4×", "exit")]
    assert bot.keys.hints(keyboard=False, double_click="camera")[1] == ("2×", "camera")
    bot.type("q")
    assert bot.keys.hints(keyboard=True) == [("Enter", "ask"), ("Esc", "cancel")]
    bot.idle = False
    assert bot.keys.hints(keyboard=True) == [("Esc", "cancel")]
    bot.keys.text = None
    assert bot.keys.hints(keyboard=True) == []           # answering: the reply needs the room
