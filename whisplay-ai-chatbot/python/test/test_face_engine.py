"""The animated face: lip sync, listening, gaze, tilt and the frame cache.

    cd python && python3 -m pytest -q test/test_face_engine.py

The mouth must move only while a clip of her voice is playing, follow that
clip's loudness, and stay shut while she listens. Time is a fake clock and
randomness is seeded, so every run sees the same frames.
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import face_engine  # noqa: E402
from face_engine import IDLE, LISTENING, THINKING  # noqa: E402

FPS = 20
SIZE = 96          # chatbot-ui.FACE_TILE
MOTION_PAD = 9     # chatbot-ui.FACE_MOTION_PAD


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(scope="module")
def renderer():
    r = face_engine.load_renderer()
    assert r is not None, "faces.json missing"
    return r


def make(renderer, sync=0.0, emotion="😐", seed=1):
    clock = Clock()
    face = face_engine.FaceAnimator(renderer, size=SIZE, speech_sync=sync,
                                    clock=clock, rng=random.Random(seed))
    face.set_emotion(emotion)
    face.render()
    return face, clock


def run(face, clock, seconds):
    """Render ``seconds`` of frames; return the drawn mouth openness per frame."""
    mouths = []
    for _ in range(int(round(seconds * FPS))):
        clock.t += 1.0 / FPS
        img, _, _ = face.render()
        assert img is not None
        mouths.append(face.last_key[2])
    return mouths


# 0.4 s loud, 0.3 s silent, 0.4 s loud, at 20 ms a frame
ENVELOPE = [90] * 20 + [0] * 15 + [90] * 20


def test_mouth_shut_without_speech_in_every_mode(renderer):
    face, clock = make(renderer)
    for mode in (IDLE, LISTENING, THINKING, IDLE):
        face.set_mode(mode)
        assert max(run(face, clock, 2.0)) == 0.0, mode


def test_status_alone_never_moves_the_mouth(renderer):
    # "answering..." used to be enough to flap the mouth for the whole time
    # the reply was being written. Now nothing but a clip opens it.
    face, clock = make(renderer)
    face.set_mode(THINKING)
    assert max(run(face, clock, 3.0)) == 0.0
    assert not face.speaking


def test_mouth_follows_the_clip(renderer):
    face, clock = make(renderer)
    face.start_speech(1, len(ENVELOPE) * 20, ENVELOPE, 20)
    mouths = run(face, clock, 1.1)
    # frame i is drawn at (i + 1) * 50 ms
    loud_a, gap, loud_b = mouths[1:7], mouths[9:13], mouths[14:21]
    assert min(loud_a) >= 0.5 and min(loud_b) >= 0.5, mouths
    assert max(gap) == 0.0, mouths          # shut in the pause between words
    assert face.speaking


def test_mouth_shuts_when_the_clip_ends(renderer):
    face, clock = make(renderer)
    face.start_speech(1, 2000, [90] * 100, 20)
    assert min(run(face, clock, 0.5)[2:]) > 0.5
    face.end_speech(1)
    after = run(face, clock, 0.5)
    assert after[3:] == [0.0] * (len(after) - 3), after
    assert not face.speaking


def test_end_of_an_older_clip_is_ignored(renderer):
    face, clock = make(renderer)
    face.start_speech(1, 2000, [90] * 100, 20)
    face.start_speech(2, 2000, [90] * 100, 20)
    face.end_speech(1)
    assert face.speaking
    assert min(run(face, clock, 0.5)[2:]) > 0.5


def test_listening_shuts_the_mouth_at_once(renderer):
    face, clock = make(renderer)
    face.start_speech(1, 5000, [90] * 250, 20)
    assert run(face, clock, 0.4)[-1] > 0.5
    face.set_mode(LISTENING)          # the button cut her off
    assert max(run(face, clock, 1.0)) == 0.0
    # and nothing she might still be sent while listening opens it
    face.start_speech(2, 5000, [90] * 250, 20)
    assert max(run(face, clock, 1.0)) == 0.0
    assert not face.speaking


def test_a_clip_that_is_never_ended_runs_out(renderer):
    face, clock = make(renderer)
    face.start_speech(1, 1000, [90] * 50, 20)
    run(face, clock, 1.0 + face_engine.SPEECH_GRACE + 0.2)
    assert not face.speaking
    assert max(run(face, clock, 1.0)) == 0.0


def test_late_envelope(renderer):
    """Without an envelope the mouth waits, then makes up syllables, then
    follows the real envelope once it arrives."""
    face, clock = make(renderer)
    face.start_speech(7, 3000, None, 20)
    waiting = run(face, clock, face_engine.ENVELOPE_WAIT - 0.05)
    assert max(waiting) == 0.0
    made_up = run(face, clock, 1.0)
    assert max(made_up) > 0.3 and min(made_up) == 0.0
    face.update_speech(7, [0] * 150, 20)     # the clip is silent from here on
    assert max(run(face, clock, 1.0)[3:]) == 0.0


def test_sync_runs_the_mouth_ahead(renderer):
    # A clip silent for its first 200 ms. With 100 ms of sync the mouth must
    # be open by 150 ms after the announcement; with none it must not.
    env = [0] * 10 + [90] * 40
    opened = {}
    for sync in (0.0, 0.1):
        face, clock = make(renderer, sync=sync)
        face.start_speech(1, 1000, env, 20)
        opened[sync] = run(face, clock, 0.15)[-1] > 0.3
    assert opened == {0.0: False, 0.1: True}


def test_listening_tilts_and_widens_the_eyes(renderer):
    face, clock = make(renderer)
    face.set_mode(LISTENING)
    run(face, clock, 1.0)
    assert abs(face._tilt) == pytest.approx(face_engine.TILT_LISTEN, abs=0.3)
    assert face.last_key[5] > 1.0
    face.set_mode(IDLE)
    run(face, clock, 1.0)
    assert face.last_key[5] == 1.0


def test_gaze_never_puts_an_eye_on_a_whisker(renderer):
    targets = set(face_engine.IDLE_GLANCES) | set(face_engine.THINK_GLANCES)
    targets |= {(-0.5, 0.0), (0.0, 0.0), (0.5, 0.0)}
    honoured = 0
    for char, face in renderer.faces.items():
        eyes = [e for e in face["elems"] if e.get("role") == "eye"]
        whiskers = [e for e in face["elems"]
                    if e.get("role") == "overlay" and e["t"] == "pill"]
        for dx, dy in targets:
            for scale in (1.0, face_engine.LISTEN_EYE_SCALE):
                got = renderer.safe_gaze(char, dx, dy, scale)
                moved = [face_engine._moved_eye(e, *got) for e in eyes]
                assert face_engine._whiskers_clear(moved, whiskers), (char, got)
                honoured += got == (dx, dy, scale)
    # the clamp is a safety net, not the normal case
    assert honoured >= 0.9 * len(renderer.faces) * len(targets) * 2


def test_face_stays_inside_its_repaint_band(renderer):
    """The UI pushes only the tile plus padding each idle frame; a face that
    moved outside it would be clipped or leave a trail."""
    face, clock = make(renderer)
    height = round(SIZE * face_engine.shape_height_ratio())
    pad_y = (SIZE - height) // 2
    band_top, band_bottom = pad_y - MOTION_PAD, pad_y + height + MOTION_PAD
    side = face.pad
    worst = []
    script = [(LISTENING, None), (THINKING, "🤔"), (IDLE, "😊"), (LISTENING, "😮"), (IDLE, "😐")]
    for mode, emotion in script * 2:
        face.set_mode(mode)
        if emotion:
            face.set_emotion(emotion)
        if mode == IDLE:
            face.start_speech(1, 1500, [100, 0, 60, 100] * 20, 20)
        for _ in range(40):
            clock.t += 1.0 / FPS
            img, offset, _ = face.render()
            x = (SIZE - img.width) // 2
            y = int(round(offset)) + (SIZE - img.height) // 2
            left, top, right, bottom = img.getchannel("A").getbbox()
            worst.append((y + top - band_top, band_bottom - (y + bottom),
                          x + left + side, SIZE + side - (x + right)))
    assert min(min(w) for w in worst) >= 0, worst


def test_caches_stay_bounded(renderer):
    face, clock = make(renderer, seed=3)
    rng = random.Random(5)
    chars = list(renderer.faces)
    for i in range(1500):
        if i % 40 == 0:
            face.set_mode(rng.choice((IDLE, LISTENING, THINKING)))
            face.set_emotion(rng.choice(chars))
            face.start_speech(i, 1500, [rng.randint(0, 100) for _ in range(75)], 20)
        clock.t += 1.0 / FPS
        face.render()
    assert len(face._frames) <= face_engine.FRAME_CACHE
    assert len(face._tilted) <= face_engine.TILT_CACHE


def test_a_late_message_is_timed_from_its_own_clock(renderer):
    # The clip went to the player 250 ms before its "start" reached the UI
    # (the UI thread was busy drawing). Its first 200 ms are silent: timed
    # from arrival the mouth would stay shut for 200 ms; timed from ``at`` it
    # must already be open.
    env = [0] * 10 + [90] * 40
    face, clock = make(renderer)
    face.start_speech(1, 1000, env, 20, at=clock.t - 0.25)
    assert run(face, clock, 0.1)[-1] > 0.3
    # and an implausible ``at`` (a clock jump) falls back to arrival time
    face, clock = make(renderer)
    face.start_speech(1, 1000, env, 20, at=clock.t - 60)
    assert max(run(face, clock, 0.15)) == 0.0
