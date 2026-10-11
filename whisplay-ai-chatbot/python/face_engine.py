"""Animated face rendering for the Whisplay display.

The face set is authored in ``face_gen.py`` and serialised to ``faces.json`` as a
list of primitive shapes on a 100x100 canvas. This module is the runtime half: it
draws those primitives with PIL and layers an animation state machine on top so
the character blinks, looks around, tilts its head, breathes, morphs between
emotions and moves its mouth in time with the voice that is actually playing.

The mouth is driven by speech clips (``start_speech``/``end_speech``), each with
the loudness envelope of the audio being played, never by the status text: the
mouth opens on syllables, shuts in the gaps between words and stays shut while
the device is listening.

Only emoji that exist in ``faces.json`` are handled here. Anything else (tool and
status glyphs such as 🔧 or 📷) returns ``None`` so the caller can fall back to the
regular SVG/text drawing path.
"""

import bisect
import json
import math
import os
import random
import time
from collections import OrderedDict

from PIL import Image, ImageDraw

CANVAS = 100.0
DEFAULT_FACES_PATH = os.path.join(os.path.dirname(__file__), "faces.json")

# Behaviour modes, reported by the UI from the chatbot's status. Speaking is not
# reported: it is whenever a speech clip is playing, and it wins over every mode
# except listening, which always keeps the mouth shut.
IDLE = "idle"
LISTENING = "listening"
THINKING = "thinking"
SPEAKING = "speaking"

# Blinks (seconds). A quick blink, the cat's slow "I trust you" blink, and the
# gap between blinks per mode: an attentive listener blinks less, a thinker more.
QUICK_BLINK = (0.055, 0.035, 0.075)        # close, hold, open
SLOW_BLINK = (0.30, 0.40, 0.36)
BLINK_GAPS = {IDLE: (2.6, 6.2), LISTENING: (3.6, 7.5),
              THINKING: (1.8, 4.2), SPEAKING: (2.0, 5.0)}
DOUBLE_BLINK_CHANCE = 0.18
DOUBLE_BLINK_GAP = 0.12
SLOW_BLINK_EVERY = (22.0, 45.0)            # idle only

TRANSITION_TIME = 0.28

# Breathing: (period s, amplitude in canvas units) per mode.
BREATH = {IDLE: (3.4, 1.7), LISTENING: (4.2, 1.1),
          THINKING: (3.0, 1.4), SPEAKING: (3.4, 0.7)}

# Lip sync. The mouth follows the clip's loudness through a fast attack and a
# slightly slower release, the way a jaw does, and is drawn shut below
# MOUTH_CLOSED_BELOW so the pauses between words read as pauses.
MOUTH_ATTACK = 0.025
MOUTH_RELEASE = 0.035
MOUTH_CLOSED_BELOW = 0.16
SYLLABLE_ONSET = 0.30          # rising through this after a pause is a new syllable
TALK_SHAPE_HOLD = 0.07         # shortest time one mouth shape is shown
# Mouth shapes by loudness band; consecutive syllables alternate between the two
# in a band, so a run of similar syllables does not look like one held vowel.
SHAPE_BANDS = ((0.34, ("small", "narrow")), (0.58, ("medium", "narrow")),
               (0.80, ("wide", "medium")), (2.00, ("tall", "wide")))
SPEAK_BOB_PX = 1.6             # the head lifts a little on loud syllables
ENVELOPE_WAIT = 0.30           # a clip waits this long for its envelope
SPEECH_GRACE = 1.5             # past a clip's length before it is presumed over

# Gaze: where the eyes look, in canvas units. Saccades are near-instant, as real
# ones are, which also keeps the frame cache small.
GAZE_SACCADE = 0.06
IDLE_GLANCES = ((-3.2, 0.0), (3.2, 0.0), (-2.6, -2.0), (2.6, -2.0),
                (0.0, 0.8), (-1.8, 0.6), (1.8, 0.6))
THINK_GLANCES = ((2.8, -2.6), (-2.8, -2.6), (0.0, -3.0))
GAZE_BLINK_CHANCE = 0.3        # a big look-away sometimes takes a blink with it
LISTEN_EYE_SCALE = 1.07        # eyes a touch wider while listening

# Head tilt (degrees, positive is anticlockwise), sprung so it settles with a
# small overshoot instead of sliding into place.
TILT_LISTEN = 4.5
TILT_THINK = 2.5
TILT_CURIOUS = 3.0
TILT_CURIOUS_EVERY = (10.0, 22.0)
TILT_CURIOUS_HOLD = (1.2, 2.4)
TILT_SPRING = 140.0
TILT_DAMPING = 15.0
TILT_PAD = 0.07                # fraction of the tile a tilt can reach past it

# Quantisation steps for the frame cache. Animation is continuous but the eye is
# not, and re-rasterising every micro-step would be wasted work on a Pi.
Q_BLINK = 0.125
Q_MOUTH = 0.1
Q_SQUASH = 0.04
Q_GAZE = 0.5
Q_EYE_SCALE = 0.035
Q_TILT = 0.5
FRAME_CACHE = 320
TILT_CACHE = 64

# The frame is a thin ring, and PIL does not antialias, so it is drawn on an
# oversampled mask and shrunk down. Everything else is chunky enough not to care.
FRAME_SUPERSAMPLE = 3


def _rgb(hexcolor):
    hexcolor = hexcolor.lstrip("#")
    return tuple(int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))


def _as_rgb(color):
    """Accept either ``#RRGGBB`` or an ``(r, g, b)`` tuple."""
    if isinstance(color, str):
        return _rgb(color)
    return tuple(int(c) for c in color[:3])


def _quantise(value, step):
    return round(value / step) * step


def _polygon_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def _offset_polygon(pts, dist):
    """Move every vertex inward along its own normal by ``dist``.

    Insetting by scaling about the centre is wrong for a shape with features
    far from that centre: an ear gets displaced toward the middle rather than
    having its outline thinned, which collapses the ring across it. Offsetting
    along the local normal keeps the band a constant width everywhere.
    """
    n = len(pts)
    if n < 3:
        return list(pts)

    def edge_normal(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        return (dy / L, -dx / L)

    def build(sign):
        out = []
        for i in range(n):
            p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
            n1 = edge_normal(p0, p1)
            n2 = edge_normal(p1, p2)
            nx, ny = n1[0] + n2[0], n1[1] + n2[1]
            L = math.hypot(nx, ny)
            if L < 1e-9:
                nx, ny, L = n1[0], n1[1], 1.0
            nx, ny = nx / L, ny / L
            # miter: a sharp corner needs to travel further to keep the width
            cosang = max(-0.999, min(1.0, n1[0] * n2[0] + n1[1] * n2[1]))
            miter = math.sqrt(max(0.15, (1.0 + cosang) / 2.0))
            step = sign * dist / miter
            out.append([p1[0] + nx * step, p1[1] + ny * step])
        return out

    a = build(1.0)
    b = build(-1.0)
    # the inward one is whichever encloses less area
    return a if abs(_polygon_area(a)) < abs(_polygon_area(b)) else b


def shape_height_ratio(default=1.0):
    """Painted height of the head as a fraction of its width.

    The face canvas is square but the head is not, so a caller that reserves a
    square of screen for it wastes a band top and bottom. Reading the real
    bounding box lets the layout follow the head instead.
    """
    try:
        with open(DEFAULT_FACES_PATH, "r", encoding="utf-8") as fh:
            x0, y0, x1, y1 = json.load(fh)["meta"]["shape"]["bbox"]
        return (y1 - y0) / (x1 - x0)
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return default


def _ease_in_out(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _eye_extent(e):
    """Half width and half height of an eye-like primitive."""
    rx = (e.get("rx") if e.get("rx") is not None
          else e.get("r") if e.get("r") is not None else e.get("w", e.get("size", 0)) / 2)
    ry = (e.get("ry") if e.get("ry") is not None
          else e.get("r") if e.get("r") is not None else e.get("h", e.get("size", 0)) / 2)
    return rx, ry


def _moved_eye(e, dx, dy, scale):
    e = dict(e)
    e["cx"] = e["cx"] + dx
    e["cy"] = e["cy"] + dy
    if scale != 1.0 and e["t"] in ("eye", "circle", "oval"):
        for k in ("rx", "ry", "r"):
            if e.get(k) is not None:
                e[k] = e[k] * scale
    return e


def _whiskers_clear(eyes, whiskers):
    """True when no whisker crosses an eye (face_gen's check, at runtime)."""
    for w in whiskers:
        a = math.radians(w.get("rot", 0))
        hx, hy = math.cos(a) * w["w"] / 2, math.sin(a) * w["w"] / 2
        for e in eyes:
            rx, ry = _eye_extent(e)
            for i in range(21):
                t = i / 20.0
                px = w["cx"] - hx + 2 * hx * t
                py = w["cy"] - hy + 2 * hy * t
                d = math.hypot(max(0.0, abs(px - e["cx"]) - rx),
                               max(0.0, abs(py - e["cy"]) - ry))
                if d - w["h"] / 2 < 0:
                    return False
    return True


class FaceRenderer:
    """Draws a single face frame from the JSON primitive spec."""

    def __init__(self, spec):
        self.meta = spec.get("meta", {})
        self.faces = spec.get("faces", {})
        panel = self.meta.get("panel", {})
        self.panel_margin = panel.get("margin", 6)
        self.panel_rx = panel.get("rx", 26)
        self.panel_fill = panel.get("fill", "#0A0A0A")
        frame = self.meta.get("frame") or {}
        self.frame = frame if frame.get("width", 0) > 0 else None
        self.ink = self.meta.get("ink", "#22222A")
        # Silhouette shared by the panel, the content clip and the bezel ring.
        # Absent (older specs) the card falls back to the rounded rectangle.
        shape = self.meta.get("shape") or {}
        self.shape = shape.get("points") or None
        # Alternate silhouettes (an ear flicked, both pricked up) the animator
        # swaps to for a moment. Masks are cached per (size, variant).
        self.shape_variants = self.meta.get("shape_variants") or {}
        # Mouth shapes cycled through while talking, measured off the reference
        # sheet. Empty falls back to scaling the single resting mouth.
        self.talk_shapes = self.meta.get("talk_shapes") or []
        self._shape_cache = {}
        self._gaze_cache = {}

    def has(self, char):
        return char in self.faces

    def talk_shape_index(self, name):
        for i, sh in enumerate(self.talk_shapes):
            if sh.get("name") == name:
                return i
        return None

    def safe_gaze(self, char, dx, dy, scale=1.0):
        """The nearest ``(dx, dy, scale)`` that keeps this face's eyes clear.

        Whiskers sit just under the eyes, and the biggest eyes (pleading) have
        barely a unit to spare, so a downward glance or a widened eye can push
        an eye into a whisker. Each request is checked once per face and backed
        off in steps: first the widening, then the downward part, then half the
        sideways part.
        """
        key = (char, dx, dy, scale)
        hit = self._gaze_cache.get(key)
        if hit is not None:
            return hit
        face = self.faces.get(char)
        result = (0.0, 0.0, 1.0)
        if face is not None:
            eyes = [e for e in face["elems"] if e.get("role") == "eye"]
            whiskers = [e for e in face["elems"]
                        if e.get("role") == "overlay" and e["t"] == "pill"]
            for cand in ((dx, dy, scale), (dx, dy, 1.0), (dx, min(dy, 0.0), 1.0),
                         (dx / 2.0, min(dy, 0.0), 1.0), (0.0, min(dy, 0.0), 1.0)):
                moved = [_moved_eye(e, *cand) for e in eyes]
                if _whiskers_clear(moved, whiskers):
                    result = cand
                    break
        self._gaze_cache[key] = result
        return result

    # -- primitive drawing -------------------------------------------------
    # All primitives are authored on a 100x100 canvas; ``k`` scales to pixels.

    def _pill(self, img, e, k):
        w, h = max(e["w"] * k, 1), max(e["h"] * k, 1)
        layer = Image.new("RGBA", (int(w) + 4, int(h) + 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        # A pill is a stadium unless it names its own corner radius. r=0 gives
        # a hard rectangle, which is what blocky pixel-art shapes need.
        radius = e["r"] * k if e.get("r") is not None else min(w, h) / 2
        d.rounded_rectangle([2, 2, w + 1, h + 1], radius=max(0, min(radius, min(w, h) / 2)),
                            fill=_rgb(e["color"]) + (255,))
        rot = e.get("rot", 0)
        if rot:
            layer = layer.rotate(-rot, expand=True, resample=Image.BICUBIC)
        img.alpha_composite(layer, (int(e["cx"] * k - layer.width / 2),
                                    int(e["cy"] * k - layer.height / 2)))

    def _circle(self, img, e, k):
        d = ImageDraw.Draw(img)
        cx, cy = e["cx"] * k, e["cy"] * k
        rx = e["r"] * k
        ry = e.get("ry", e["r"]) * k
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=_rgb(e["color"]) + (255,))
        if e.get("pupil_r"):
            pr = e["pupil_r"] * k
            d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr],
                      fill=_rgb(e.get("pupil_color", "#0A0A0A")) + (255,))

    def _stroke(self, img, pts, stroke, color, k):
        sw = max(stroke * k, 1)
        scaled = [(x * k, y * k) for x, y in pts]
        d = ImageDraw.Draw(img)
        fill = _rgb(color) + (255,)
        if len(scaled) > 1:
            d.line(scaled, fill=fill, width=int(sw), joint="curve")
        r = sw / 2
        for x, y in (scaled[0], scaled[-1]):
            d.ellipse([x - r, y - r, x + r, y + r], fill=fill)

    def _arc(self, img, e, k, n=24):
        cx, cy, w, depth = e["cx"], e["cy"], e["w"], e["depth"]
        x0, x1 = cx - w / 2, cx + w / 2
        pts = []
        for i in range(n + 1):
            t = i / n
            x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
            y = (1 - t) ** 2 * cy + 2 * (1 - t) * t * (cy + depth) + t ** 2 * cy
            pts.append((x, y))
        rot = e.get("rot", 0)
        if rot:
            a = math.radians(rot)
            pts = [(cx + (x - cx) * math.cos(a) - (y - cy) * math.sin(a),
                    cy + (x - cx) * math.sin(a) + (y - cy) * math.cos(a)) for x, y in pts]
        self._stroke(img, pts, e["stroke"], e["color"], k)

    def _flat(self, img, e, k):
        self._stroke(img, [(e["cx"] - e["w"] / 2, e["cy"]), (e["cx"] + e["w"] / 2, e["cy"])],
                     e["stroke"], e["color"], k)

    def _o(self, img, e, k):
        d = ImageDraw.Draw(img)
        cx, cy, r = e["cx"] * k, e["cy"] * k, e["r"] * k
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=_rgb(e["color"]) + (255,),
                  width=max(int(e["stroke"] * k), 1))

    def _zigzag(self, img, e, k):
        cx, cy, w, h, n = e["cx"], e["cy"], e["w"], e["h"], e["n"]
        x0, step = cx - w / 2, w / n
        pts = [(x0 + i * step, cy + (h / 2 if i % 2 == 0 else -h / 2)) for i in range(n + 1)]
        self._stroke(img, pts, e["stroke"], e["color"], k)

    def _heart(self, img, e, k):
        d = ImageDraw.Draw(img)
        cx, cy, s = e["cx"] * k, e["cy"] * k, e["size"] * k
        fill = _rgb(e["color"]) + (255,)
        r = s * 0.34
        d.ellipse([cx - r * 1.9, cy - r * 1.3, cx - r * 0.1, cy + r * 0.9], fill=fill)
        d.ellipse([cx + r * 0.1, cy - r * 1.3, cx + r * 1.9, cy + r * 0.9], fill=fill)
        d.polygon([(cx - r * 1.8, cy + r * 0.3), (cx + r * 1.8, cy + r * 0.3),
                   (cx, cy + r * 2.1)], fill=fill)

    def _star(self, img, e, k):
        d = ImageDraw.Draw(img)
        cx, cy, s = e["cx"] * k, e["cy"] * k, e["size"] * k
        pts = []
        for i in range(8):
            ang = math.pi / 4 * i - math.pi / 2
            r = s if i % 2 == 0 else s * 0.42
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        d.polygon(pts, fill=_rgb(e["color"]) + (255,))

    def _drop(self, img, e, k):
        d = ImageDraw.Draw(img)
        cx, cy = e["cx"] * k, e["cy"] * k
        w, h = e["w"] * k, e["h"] * k
        fill = _rgb(e["color"]) + (255,)
        d.ellipse([cx - w / 2, cy - h * 0.05, cx + w / 2, cy + h / 2], fill=fill)
        d.polygon([(cx - w / 2 * 0.9, cy), (cx + w / 2 * 0.9, cy), (cx, cy - h / 2)], fill=fill)

    def _zzz(self, img, e, k):
        cx, cy, s, color = e["cx"], e["cy"], e["scale"], e["color"]
        for i, mult in enumerate((0.6, 0.85, 1.15)):
            size = 6 * s * mult
            x, y = cx - i * 7 * s, cy + i * 8 * s
            half = size / 2
            self._stroke(img, [(x - half, y - half), (x + half, y - half),
                               (x - half, y + half), (x + half, y + half)], 2.4, color, k)

    def _blush(self, img, e, k):
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx, cy = e["cx"] * k, e["cy"] * k
        rx, ry = e["rx"] * k, e["ry"] * k
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry],
                  fill=_rgb(e["color"]) + (int(255 * e.get("opacity", 0.9)),))
        img.alpha_composite(layer)

    def _dome_pts(self, cx, cy, w, h, n=28):
        pts = [(cx - w / 2, cy), (cx + w / 2, cy)]
        for i in range(1, n):
            ang = math.pi * i / n
            pts.append((cx + (w / 2) * math.cos(ang), cy + h * math.sin(ang)))
        return pts

    def _grin(self, img, e, k):
        d = ImageDraw.Draw(img)
        cx, cy = e["cx"] * k, e["cy"] * k
        w, h = e["w"] * k, e["h"] * k
        d.polygon(self._dome_pts(cx, cy, w, h), fill=_rgb(e["color"]) + (255,))
        inner = e.get("inner")
        if inner and h > 3:
            d.polygon(self._dome_pts(cx, cy + h * 0.12, w * 0.82, h * 0.78),
                      fill=_rgb(inner) + (255,))
        if e.get("tongue") and h > 6:
            ty, trx, try_ = cy + h * 0.62, w * 0.20, h * 0.26
            d.ellipse([cx - trx, ty - try_, cx + trx, ty + try_],
                      fill=_rgb(e.get("tongue_color", "#FF6B81")) + (255,))

    def _caret(self, img, e, k):
        cx, cy, w, h = e["cx"], e["cy"], e["w"], e["h"]
        tip = cy + h / 2 if e.get("down") else cy - h / 2
        base = cy - h / 2 if e.get("down") else cy + h / 2
        self._stroke(img, [(cx - w / 2, base), (cx, tip), (cx + w / 2, base)],
                     e["stroke"], e["color"], k)

    def _x(self, img, e, k):
        cx, cy, s = e["cx"], e["cy"], e["size"] / 2
        self._stroke(img, [(cx - s, cy - s), (cx + s, cy + s)], e["stroke"], e["color"], k)
        self._stroke(img, [(cx + s, cy - s), (cx - s, cy + s)], e["stroke"], e["color"], k)

    def _eye(self, img, e, k):
        """Glossy oval eye: dark body, optional lid, highlight glints."""
        d = ImageDraw.Draw(img)
        cx, cy = e["cx"] * k, e["cy"] * k
        rx, ry = e["rx"] * k, e["ry"] * k
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=_as_rgb(e["color"]) + (255,))
        lid = e.get("lid") or 0.0
        if lid > 0:
            lid_h = 2 * ry * lid
            d.rectangle([cx - rx - 1, cy - ry - 1, cx + rx + 1, cy - ry + lid_h],
                        fill=_as_rgb(e.get("panel", self.panel_fill)) + (255,))
            self._stroke(img, [(e["cx"] - e["rx"], e["cy"] - e["ry"] + lid_h / k),
                               (e["cx"] + e["rx"], e["cy"] - e["ry"] + lid_h / k)],
                         3.0, e["color"], k)
        if e.get("glint"):
            gy = cy - ry * 0.38 + (2 * ry * lid) * 0.5
            gr = rx * 0.36
            d.ellipse([cx - rx * 0.34 - gr, gy - gr, cx - rx * 0.34 + gr, gy + gr],
                      fill=(255, 255, 255, 255))
            sr = rx * 0.17
            sx, sy = cx + rx * 0.36, cy + ry * 0.34
            d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(255, 255, 255, 255))

    def _oval(self, img, e, k):
        d = ImageDraw.Draw(img)
        cx, cy = e["cx"] * k, e["cy"] * k
        rx, ry = e["rx"] * k, e["ry"] * k
        box = [cx - rx, cy - ry, cx + rx, cy + ry]
        if e.get("outline"):
            d.ellipse(box, fill=_as_rgb(e["color"]) + (255,),
                      outline=_as_rgb(e["outline"]) + (255,),
                      width=max(int(e.get("stroke", 2.5) * k), 1))
        else:
            d.ellipse(box, fill=_as_rgb(e["color"]) + (255,))

    def _hatch(self, img, e, k):
        cx, cy, w, h, n = e["cx"], e["cy"], e["w"], e["h"], e["n"]
        step = w / max(n - 1, 1)
        x0 = cx - w / 2
        for i in range(n):
            x = x0 + i * step
            self._stroke(img, [(x, cy + h / 2), (x + h * 0.45, cy - h / 2)],
                         e["stroke"], e["color"], k)

    def _anger(self, img, e, k):
        d = ImageDraw.Draw(img)
        cx, cy, s = e["cx"], e["cy"], e["size"] / 2
        pts = [(cx - s, cy - s), (cx - s * 0.25, cy - s * 0.35), (cx, cy - s),
               (cx + s * 0.25, cy - s * 0.35), (cx + s, cy - s),
               (cx + s * 0.35, cy), (cx + s, cy + s),
               (cx + s * 0.25, cy + s * 0.35), (cx, cy + s),
               (cx - s * 0.25, cy + s * 0.35), (cx - s, cy + s), (cx - s * 0.35, cy)]
        d.polygon([(x * k, y * k) for x, y in pts], fill=_as_rgb(e["color"]) + (255,))

    def _cat(self, img, e, k, n=14):
        """The ω mouth: two shallow scallops side by side."""
        cx, cy, w, h = e["cx"], e["cy"], e["w"], e["h"]
        pts = []
        for half in (-1, 1):
            hx = cx + half * w / 4
            x0, x1 = hx - w / 4, hx + w / 4
            for i in range(n + 1):
                t = i / n
                x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * hx + t ** 2 * x1
                y = (1 - t) ** 2 * cy + 2 * (1 - t) * t * (cy + h) + t ** 2 * cy
                pts.append((x, y))
        self._stroke(img, pts, e["stroke"], e["color"], k)

    def _tri(self, img, e, k):
        d = ImageDraw.Draw(img)
        cx, cy, w, h = e["cx"], e["cy"], e["w"], e["h"]
        if e.get("down"):
            pts = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx, cy + h / 2)]
        else:
            pts = [(cx - w / 2, cy + h / 2), (cx + w / 2, cy + h / 2), (cx, cy - h / 2)]
        d.polygon([(x * k, y * k) for x, y in pts], fill=_as_rgb(e["color"]) + (255,))

    def _draw_elem(self, img, e, k):
        fn = {
            "pill": self._pill, "circle": self._circle, "arc": self._arc,
            "flat": self._flat, "o": self._o, "zigzag": self._zigzag,
            "heart": self._heart, "star": self._star, "drop": self._drop,
            "zzz": self._zzz, "blush": self._blush, "grin": self._grin,
            "caret": self._caret, "x": self._x, "eye": self._eye,
            "oval": self._oval, "hatch": self._hatch, "anger": self._anger,
            "cat": self._cat, "tri": self._tri,
        }.get(e["t"])
        if fn:
            fn(img, e, k)

    # -- frame composition -------------------------------------------------

    def _paint_ring(self, img, size, mask, color=None):
        """Fill a ring mask with the bezel gradient, or a solid status tint."""
        grad = self.frame.get("gradient")
        if grad and not color:
            top, bottom = _as_rgb(grad["from"]), _as_rgb(grad["to"])
            ring = Image.new("RGBA", (size, size))
            rd = ImageDraw.Draw(ring)
            span = max(size - 1, 1)
            for y in range(size):
                t = y / span
                rd.line([(0, y), (size, y)],
                        fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
        else:
            ring = Image.new("RGBA", (size, size),
                             _as_rgb(color or self.frame.get("color", "#3A4657")) + (255,))
        ring.putalpha(mask)
        img.alpha_composite(ring)

    def _shape_masks(self, size, variant=None):
        """``(card, ring)`` masks for the silhouette, built once per size.

        Both are rasterised supersampled and combined before the downscale, so
        the ring's two edges stay as clean as the panel's.
        """
        key = (size, variant)
        hit = self._shape_cache.get(key)
        if hit is not None:
            return hit
        points = self.shape_variants.get(variant) if variant else self.shape
        if not points:
            points = self.shape
        if not points:
            self._shape_cache[key] = (None, None)
            return None, None
        s = FRAME_SUPERSAMPLE
        big = size * s
        k = big / CANVAS
        inset = self.frame.get("inset", 0.0) if self.frame else 0.0
        width = self.frame.get("width", 0.0) if self.frame else 0.0

        def poly(shrink):
            pts = _offset_polygon(points, shrink) if shrink > 0 else points
            m = Image.new("L", (big, big), 0)
            ImageDraw.Draw(m).polygon([(x * k, y * k) for x, y in pts], fill=255)
            return m

        outer = poly(inset)
        card = outer.resize((size, size), Image.LANCZOS)
        ring = None
        if width > 0:
            r = outer.copy()
            r.paste(0, (0, 0), poly(inset + width))
            ring = r.resize((size, size), Image.LANCZOS)
        self._shape_cache[key] = (card, ring)
        return card, ring

    def _draw_frame(self, img, size, k, color=None, variant=None):
        """Stroke the bezel ring around the panel."""
        if not self.frame:
            return
        _, shaped_ring = self._shape_masks(size, variant)
        if shaped_ring is not None:
            self._paint_ring(img, size, shaped_ring, color)
            return
        s = FRAME_SUPERSAMPLE
        width = max(self.frame["width"] * k * s, 1.0)
        centre = self.frame.get("inset", 1.5) * k * s + width / 2
        big = size * s
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [centre, centre, big - centre - 1, big - centre - 1],
            radius=max(self.frame.get("rx", self.panel_rx) * k * s, 0),
            outline=255, width=max(int(round(width)), 1))
        # Painting a solid colour through the shrunken mask keeps the ring free
        # of the dark fringe a downscaled RGBA layer would leave behind.
        grad = self.frame.get("gradient")
        if grad and not color:
            # Vertical wash down the bezel. Painted as a full tile and then cut
            # by the ring mask, which keeps the edge as clean as the flat fill.
            top, bottom = _as_rgb(grad["from"]), _as_rgb(grad["to"])
            ring = Image.new("RGBA", (size, size))
            rd = ImageDraw.Draw(ring)
            span = max(size - 1, 1)
            for y in range(size):
                t = y / span
                rd.line([(0, y), (size, y)],
                        fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
        else:
            ring = Image.new("RGBA", (size, size),
                             _as_rgb(color or self.frame.get("color", "#3A4657")) + (255,))
        ring.putalpha(mask.resize((size, size), Image.LANCZOS))
        img.alpha_composite(ring)

    def draw(self, char, size, blink=0.0, mouth_open=0.0, frame_color=None,
             shape_variant=None, talk_shape=0, gaze=(0.0, 0.0), eye_scale=1.0):
        """Render one face frame at ``size`` pixels square.

        ``gaze`` moves the eyes (and, by less, the brows) in canvas units;
        ``eye_scale`` widens round eyes. Both are clamped by ``safe_gaze``.
        """
        face = self.faces.get(char)
        if face is None:
            return None
        k = size / CANVAS
        gx, gy, eye_scale = self.safe_gaze(char, gaze[0], gaze[1], eye_scale)
        card, _ = self._shape_masks(size, shape_variant)
        if card is not None:
            # The card is a silhouette, so the panel is painted full bleed and
            # everything is cut to shape at the end. That way a blush or a tear
            # near the rim is clipped by the card instead of floating outside it.
            img = Image.new("RGBA", (size, size), _as_rgb(self.panel_fill) + (255,))
        else:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            m = self.panel_margin * k
            d.rounded_rectangle([m, m, size - m, size - m], radius=self.panel_rx * k,
                                fill=_rgb(self.panel_fill) + (255,))

        elems = face["elems"]
        eyes = [e for e in elems if e.get("role") == "eye"]
        mouth = [e for e in elems if e.get("role") == "mouth"]
        overlay = [e for e in elems if e.get("role") == "overlay"]
        rest = [e for e in elems if e.get("role") not in ("eye", "mouth", "overlay")]
        if gx or gy or eye_scale != 1.0:
            eyes = [_moved_eye(e, gx, gy, eye_scale) for e in eyes]
            # Brows ride along, by less: looking up lifts them, which is most
            # of what makes a glance upward read as thought.
            rest = [_moved_eye(e, gx * 0.35, gy * 0.45, 1.0) if e.get("role") == "brow" else e
                    for e in rest]

        for e in rest:
            self._draw_elem(img, e, k)

        # Eyes live on their own layer so a blink can squash them vertically
        # without disturbing brows, blush or tears.
        if eyes:
            if blink <= 0.02:
                for e in eyes:
                    self._draw_elem(img, e, k)
            else:
                layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                for e in eyes:
                    self._draw_elem(layer, e, k)
                pivot = sum(e["cy"] for e in eyes) / len(eyes) * k
                self._paste_squashed(img, layer, pivot, 1.0 - blink)
                if blink > 0.55:
                    self._draw_closed_eyes(img, eyes, k, blink)

        # Mouth: when talking, morph the resting mouth into an open grin.
        anchor = face.get("mouth_anchor")
        if mouth_open > 0.12 and anchor:
            if self.talk_shapes:
                sh = self.talk_shapes[talk_shape % len(self.talk_shapes)]
                # The chosen shape still opens and closes, so speech reads as
                # movement rather than a slideshow of fixed mouths.
                h = sh["h"] * (0.35 + 0.65 * mouth_open)
                w = sh["w"] * (0.85 + 0.15 * mouth_open)
            else:
                h = 2.5 + 15.0 * mouth_open
                w = anchor["w"] * (0.78 + 0.22 * mouth_open)
            self._grin(img, {
                "cx": anchor["cx"], "cy": anchor["cy"] - h * 0.18,
                "w": w, "h": h,
                "color": anchor.get("color", "#F5F5F0"),
                "inner": anchor.get("inner", "#B32B3E"),
            }, k)
        else:
            for e in mouth:
                self._draw_elem(img, e, k)

        if card is not None:
            clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            clipped.paste(img, (0, 0), card)
            img = clipped

        # Last, so a tear or a Zzz that strays into the margin sits behind it.
        self._draw_frame(img, size, k, frame_color, shape_variant)

        # Overlay elements are drawn after the clip and after the outline, so
        # whiskers extend past the head edge and lie across the frame.
        for e in overlay:
            self._draw_elem(img, e, k)
        return img

    def _paste_squashed(self, img, layer, pivot_y, factor):
        factor = max(factor, 0.02)
        new_h = max(int(layer.height * factor), 1)
        squashed = layer.resize((layer.width, new_h), Image.BILINEAR)
        img.alpha_composite(squashed, (0, int(pivot_y - new_h / 2)))

    def _draw_closed_eyes(self, img, eyes, k, blink):
        """At the bottom of a blink, replace the squashed shape with a clean lid."""
        alpha = min(1.0, (blink - 0.55) / 0.45)
        seen = []
        for e in eyes:
            cx, cy = e["cx"], e["cy"]
            if any(abs(cx - sx) < 4 and abs(cy - sy) < 6 for sx, sy in seen):
                continue
            seen.append((cx, cy))
            w = (e.get("w") or (e.get("rx", 0) * 2) or (e.get("r", 0) * 2)
                 or e.get("size", 12))
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            # A shut kawaii eye is a shallow upward arc, not a flat dash.
            self._arc(layer, {"cx": cx, "cy": cy + w * 0.10, "w": w * 1.05,
                              "depth": -w * 0.34, "stroke": 3.6,
                              "color": e.get("color", self.ink)}, k)
            if alpha < 1.0:
                layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
            img.alpha_composite(layer)


class SpeechTrack:
    """One clip of speech being played, aligned to when it started.

    ``envelope`` is the clip's loudness, 0..100 per ``frame_s`` seconds, worked
    out from the audio itself by the Node core. A clip that has none yet keeps
    the mouth shut for ENVELOPE_WAIT (the envelope is usually on its way) and
    then falls back to made-up syllables, so speech never plays to a still face.
    """

    def __init__(self, track_id, start, duration, envelope=None, frame_s=0.02):
        self.id = track_id
        self.start = start
        self.duration = max(0.0, float(duration or 0.0))
        self.frame_s = max(0.005, float(frame_s or 0.02))
        self.envelope = None
        if envelope:
            try:
                self.envelope = [max(0.0, min(1.0, float(v) / 100.0)) for v in envelope]
            except (TypeError, ValueError):
                self.envelope = None
        self._syllables = None

    def with_envelope(self, envelope, frame_s):
        return SpeechTrack(self.id, self.start, self.duration, envelope, frame_s)

    def expired(self, now):
        return now > self.start + self.duration + SPEECH_GRACE

    def level(self, now):
        t = now - self.start
        if t < 0:
            return 0.0
        env = self.envelope
        if env:
            pos = t / self.frame_s
            i = int(pos)
            if i >= len(env):
                return 0.0
            if i == len(env) - 1:
                return env[i]
            return env[i] + (env[i + 1] - env[i]) * (pos - i)
        if t < ENVELOPE_WAIT or t > self.duration:
            return 0.0
        return self._synthetic(t)

    def _synthetic(self, t):
        if self._syllables is None:
            rng = random.Random(str(self.id))
            starts, sylls, at = [], [], ENVELOPE_WAIT
            while at < self.duration:
                on = rng.uniform(0.11, 0.24)
                starts.append(at)
                sylls.append((on, rng.uniform(0.45, 1.0)))
                # mostly a short gap between syllables, now and then a phrase break
                at += on + (rng.uniform(0.25, 0.45) if rng.random() < 0.12
                            else rng.uniform(0.03, 0.09))
            self._syllables = (starts, sylls)
        starts, sylls = self._syllables
        i = bisect.bisect_right(starts, t) - 1
        if i < 0:
            return 0.0
        on, peak = sylls[i]
        p = (t - starts[i]) / on
        if p >= 1.0:
            return 0.0
        return peak * math.sin(math.pi * p) ** 0.7


class FaceAnimator:
    """Drives blinking, gaze, head tilt, breathing, lip sync and transitions."""

    def __init__(self, renderer, size=40, emotion=None, idle_motion=True,
                 speech_sync=0.03, clock=time.time, rng=None):
        self.renderer = renderer
        self.size = size
        self.idle_motion = idle_motion
        # Seconds the mouth runs ahead of the moment a clip was announced:
        # covers the player's start-up, the frame's trip to the panel and the
        # jaw's own smoothing, so the mouth is open when the sound is heard.
        self.speech_sync = speech_sync
        self.clock = clock
        self.rng = rng or random.Random()
        now = clock()
        self.current = emotion if emotion and renderer.has(emotion) else None
        self.previous = None
        self.transition_start = None
        self.frame_color = None  # None keeps the neutral bezel from faces.json
        self.mode = IDLE
        self._mode_since = now
        self._last_now = now

        self._speech = None          # SpeechTrack, replaced whole (socket thread)
        self._mouth = 0.0
        self._quiet = True
        self._syllable = 0
        self._shape = None
        self._shape_at = 0.0

        self._blink_start = None
        self._blink_profile = QUICK_BLINK
        self._next_blink = now + self.rng.uniform(*BLINK_GAPS[IDLE])
        self._double_pending = False
        self._next_slow_blink = now + self.rng.uniform(*SLOW_BLINK_EVERY)

        self._gaze_from = (0.0, 0.0)
        self._gaze_to = (0.0, 0.0)
        self._gaze_at = now
        self._next_gaze = now + self.rng.uniform(1.5, 3.5)
        self._glancing = False
        self._eye_scale = 1.0

        self._tilt = 0.0
        self._tilt_vel = 0.0
        self._listen_side = 1.0 if self.rng.random() < 0.5 else -1.0
        self._curious_side = 0.0
        self._curious_until = 0.0
        self._next_curious = now + self.rng.uniform(*TILT_CURIOUS_EVERY)

        self._breath_phase = 0.0
        self._breath_amp = BREATH[IDLE][1]

        self._frames = OrderedDict()
        self._tilted = OrderedDict()
        self.last_key = None

    # -- state ------------------------------------------------------------

    def set_emotion(self, char, now=None):
        """Point the face at a new emotion. Returns True if it is animatable."""
        if not self.renderer.has(char):
            self.current = None
            return False
        if char == self.current:
            return True
        if now is None:
            now = self.clock()
        if self.current is not None:
            self.previous = self.current
            self.transition_start = now
        self.current = char
        return True

    def set_mode(self, mode, now=None):
        """Tell the face what the chatbot is doing: idle, listening or thinking."""
        if mode not in (IDLE, LISTENING, THINKING):
            mode = IDLE
        if mode == self.mode:
            return
        if now is None:
            now = self.clock()
        self.mode = mode
        self._mode_since = now
        self._next_gaze = now        # look somewhere fitting straight away
        if mode == LISTENING:
            # Nothing she says can be playing while she listens. A clip that
            # was cut off by the button must not keep the mouth going.
            self._speech = None
            self._mouth = 0.0
            self._listen_side = -self._listen_side
            self._next_blink = max(self._next_blink, now + 0.8)

    def start_speech(self, track_id, duration_ms, envelope=None, frame_ms=20, now=None, at=None):
        """A clip has just been handed to the speaker.

        ``at`` is when the sender handed it over, on this clock. The message
        can reach the UI thread a good 100 ms late while a full screen is being
        drawn, and the mouth must not inherit that delay, so ``at`` wins over
        the arrival time unless it is implausible (more than 2 s off).
        """
        if now is None:
            now = self.clock()
        if self.mode == LISTENING:
            return
        began = now
        if at is not None:
            try:
                at = float(at)
                if abs(now - at) < 2.0:
                    began = at
            except (TypeError, ValueError):
                pass
        self._speech = SpeechTrack(track_id, began - self.speech_sync,
                                   (duration_ms or 0) / 1000.0, envelope,
                                   (frame_ms or 20) / 1000.0)

    def update_speech(self, track_id, envelope, frame_ms=20):
        """The envelope for a clip that started without one."""
        track = self._speech
        if track is not None and track.id == track_id and envelope:
            self._speech = track.with_envelope(envelope, (frame_ms or 20) / 1000.0)

    def end_speech(self, track_id=None):
        track = self._speech
        if track is not None and (track_id is None or track.id == track_id):
            self._speech = None

    @property
    def speaking(self):
        track = self._speech
        return (track is not None and self.mode != LISTENING
                and not track.expired(self.clock()))

    def set_frame_color(self, color):
        """Tint the bezel, e.g. with the status colour. ``None`` restores default."""
        color = _as_rgb(color) if color else None
        if color != self.frame_color:
            # Every cached frame carries the old ring, so none of them are worth
            # keeping. Dropping them also stops a long session from filling the
            # cache with one dead colour per status change.
            self._frames.clear()
            self._tilted.clear()
            self.frame_color = color

    def active(self, now=None):
        """True while the face still has motion to render."""
        if self.current is None:
            return False
        if now is None:
            now = self.clock()
        if self.idle_motion:
            return True
        return (self.transition_start is not None or self.speaking
                or self._mouth > 0.01 or self._blink_start is not None
                or now - self._gaze_at < GAZE_SACCADE
                or abs(self._tilt - self._tilt_target(now)) > 0.05
                or abs(self._tilt_vel) > 0.1)

    # -- per-frame parameters ---------------------------------------------

    def _effective_mode(self, now):
        track = self._speech
        if track is not None and track.expired(now):
            self._speech = None
            track = None
        if self.mode == LISTENING:
            return LISTENING
        if track is not None:
            return SPEAKING
        return self.mode

    def _blink_amount(self, now, mode):
        if self._blink_start is None:
            if now < self._next_blink:
                return 0.0
            self._blink_start = now
            slow = mode == IDLE and self.idle_motion and now >= self._next_slow_blink
            self._blink_profile = SLOW_BLINK if slow else QUICK_BLINK
            if slow:
                self._next_slow_blink = now + self.rng.uniform(*SLOW_BLINK_EVERY)
                self._double_pending = False
            else:
                self._double_pending = (not self._double_pending
                                        and self.rng.random() < DOUBLE_BLINK_CHANCE)
        close, hold, open_ = self._blink_profile
        t = now - self._blink_start
        if t >= close + hold + open_:
            self._blink_start = None
            if self._double_pending:
                self._next_blink = now + DOUBLE_BLINK_GAP
            else:
                self._next_blink = now + self.rng.uniform(*BLINK_GAPS[mode])
            return 0.0
        if t < close:
            return _ease_in_out(t / close)
        if t < close + hold:
            return 1.0
        return 1.0 - _ease_in_out((t - close - hold) / open_)

    def _pick_gaze(self, now, mode):
        """Choose the next place to look and how long to keep looking there."""
        rng = self.rng
        if mode == LISTENING:
            # On you, with the small drift of someone actually paying attention.
            return (rng.choice((-0.5, 0.0, 0.5)), 0.0), rng.uniform(1.2, 2.8)
        if mode == THINKING:
            options = [g for g in THINK_GLANCES if g != self._gaze_to] or THINK_GLANCES
            return rng.choice(options), rng.uniform(0.9, 2.2)
        if mode == SPEAKING:
            if not self._glancing and rng.random() < 0.25:
                return rng.choice(IDLE_GLANCES[:4]), rng.uniform(0.35, 0.8)
            return (0.0, 0.0), rng.uniform(1.5, 3.5)
        if not self.idle_motion:
            return (0.0, 0.0), 3600.0
        if not self._glancing and rng.random() < 0.5:
            return rng.choice(IDLE_GLANCES), rng.uniform(0.6, 1.6)
        return (0.0, 0.0), rng.uniform(1.4, 4.5)

    def _gaze(self, now, mode):
        if now >= self._next_gaze:
            target, hold = self._pick_gaze(now, mode)
            self._glancing = target != (0.0, 0.0) and mode in (IDLE, SPEAKING)
            current = self._gaze_value(now)
            if target != self._gaze_to:
                jump = math.hypot(target[0] - current[0], target[1] - current[1])
                if (jump > 3.0 and self._blink_start is None
                        and self.rng.random() < GAZE_BLINK_CHANCE):
                    self._next_blink = now
                self._gaze_from = current
                self._gaze_to = target
                self._gaze_at = now
            self._next_gaze = now + hold
        gx, gy = self._gaze_value(now)
        return (_quantise(gx, Q_GAZE), _quantise(gy, Q_GAZE))

    def _gaze_value(self, now):
        p = _ease_in_out((now - self._gaze_at) / GAZE_SACCADE)
        (x0, y0), (x1, y1) = self._gaze_from, self._gaze_to
        return (x0 + (x1 - x0) * p, y0 + (y1 - y0) * p)

    def _tilt_target(self, now):
        mode = self._effective_mode(now)
        if mode == LISTENING:
            return TILT_LISTEN * self._listen_side
        if mode == THINKING:
            gx = self._gaze_to[0]
            return -TILT_THINK if gx > 0 else TILT_THINK if gx < 0 else 0.0
        if mode == IDLE and self.idle_motion:
            if now >= self._next_curious and now >= self._curious_until:
                self._curious_side = 1.0 if self.rng.random() < 0.5 else -1.0
                self._curious_until = now + self.rng.uniform(*TILT_CURIOUS_HOLD)
                self._next_curious = self._curious_until + self.rng.uniform(*TILT_CURIOUS_EVERY)
            if now < self._curious_until:
                return TILT_CURIOUS * self._curious_side
        return 0.0

    def _step_tilt(self, now, dt):
        target = self._tilt_target(now)
        steps = max(1, int(math.ceil(dt / 0.016)))
        h = dt / steps
        for _ in range(steps):
            acc = TILT_SPRING * (target - self._tilt) - TILT_DAMPING * self._tilt_vel
            self._tilt_vel += acc * h
            self._tilt += self._tilt_vel * h
        if abs(target - self._tilt) < 0.05 and abs(self._tilt_vel) < 0.1:
            self._tilt, self._tilt_vel = target, 0.0
        return _quantise(self._tilt, Q_TILT)

    def _step_mouth(self, now, dt, mode):
        if mode == LISTENING:
            self._mouth = 0.0
            self._quiet = True
            return 0.0
        track = self._speech
        level = track.level(now) if (track is not None and mode == SPEAKING) else 0.0
        if dt > 0:
            tau = MOUTH_ATTACK if level > self._mouth else MOUTH_RELEASE
            self._mouth += (level - self._mouth) * (1.0 - math.exp(-dt / tau))
        if self._mouth < 0.005:
            self._mouth = 0.0
        return self._mouth

    def _talk_shape(self, mouth, now):
        """Pick the mouth shape for this loudness; None means drawn shut."""
        if mouth < MOUTH_CLOSED_BELOW or not self.renderer.talk_shapes:
            self._quiet = True
            return None
        if self._quiet and mouth >= SYLLABLE_ONSET:
            self._quiet = False
            self._syllable += 1
        names = next(n for limit, n in SHAPE_BANDS if mouth < limit)
        index = self.renderer.talk_shape_index(names[self._syllable % len(names)])
        if index is None:
            index = self._syllable % len(self.renderer.talk_shapes)
        if self._shape is not None and index != self._shape and now - self._shape_at < TALK_SHAPE_HOLD:
            return self._shape
        if index != self._shape:
            self._shape, self._shape_at = index, now
        return index

    def _eye_scale_step(self, mode, dt):
        target = LISTEN_EYE_SCALE if mode == LISTENING else 1.0
        if dt > 0:
            self._eye_scale += (target - self._eye_scale) * (1.0 - math.exp(-dt / 0.08))
        # Steps counted from 1.0, so the resting eye is exactly the drawn one.
        return round(1.0 + _quantise(self._eye_scale - 1.0, Q_EYE_SCALE), 3)

    def _breathe_offset(self, mode, dt):
        if not self.idle_motion:
            return 0.0
        period, amp = BREATH[mode]
        self._breath_phase = (self._breath_phase + 2 * math.pi * dt / period) % (2 * math.pi)
        if dt > 0:
            self._breath_amp += (amp - self._breath_amp) * (1.0 - math.exp(-dt / 0.5))
        return self._breath_amp * math.sin(self._breath_phase)

    # -- rendering ---------------------------------------------------------

    def _frame(self, key):
        img = self._frames.get(key)
        if img is not None:
            self._frames.move_to_end(key)
            return img
        char, blink, mouth, shape, gaze, eye_scale = key
        img = self.renderer.draw(char, self.size, blink=blink, mouth_open=mouth,
                                 frame_color=self.frame_color,
                                 talk_shape=shape if shape is not None else 0,
                                 gaze=gaze, eye_scale=eye_scale)
        if img is not None:
            self._frames[key] = img
            if len(self._frames) > FRAME_CACHE:
                self._frames.popitem(last=False)
        return img

    def _tilted_frame(self, key, img, angle):
        tkey = (key, angle)
        hit = self._tilted.get(tkey)
        if hit is not None:
            self._tilted.move_to_end(tkey)
            return hit
        # Bilinear costs ~6 ms on a Pi Zero 2 W, so tilted frames are cached:
        # a held tilt is free, only the swing into it is paid for.
        out = img.rotate(angle, resample=Image.BILINEAR, expand=True)
        self._tilted[tkey] = out
        if len(self._tilted) > TILT_CACHE:
            self._tilted.popitem(last=False)
        return out

    def render(self, now=None):
        """Return ``(RGBA image or None, vertical offset in px, animation_active)``.

        The image is the face, centred on the tile; while the head is tilted it
        is larger than ``size`` (by at most ``pad`` on each side), so callers
        centre it rather than pasting it at the tile's corner.
        """
        if self.current is None:
            return None, 0.0, False
        if now is None:
            now = self.clock()
        dt = max(0.0, min(0.2, now - self._last_now))
        self._last_now = now

        mode = self._effective_mode(now)
        blink = self._blink_amount(now, mode)
        mouth = self._step_mouth(now, dt, mode)
        shape = self._talk_shape(mouth, now)
        gaze = self._gaze(now, mode)
        eye_scale = self._eye_scale_step(mode, dt)
        angle = self._step_tilt(now, dt)
        breathe = self._breathe_offset(mode, dt)
        squash = 1.0
        char = self.current
        dip = 0.0

        if self.transition_start is not None:
            t = (now - self.transition_start) / TRANSITION_TIME
            if t >= 1.0:
                self.transition_start = None
                self.previous = None
            else:
                if t < 0.5:
                    p = _ease_in_out(t / 0.5)
                    char = self.previous or self.current
                    blink = max(blink, p)
                else:
                    p = 1.0 - _ease_in_out((t - 0.5) / 0.5)
                    blink = max(blink, p)
                squash = 1.0 - 0.13 * (1.0 - abs(2 * t - 1))
                dip = 2.4 * (1.0 - abs(2 * t - 1))

        drawn_mouth = _quantise(mouth, Q_MOUTH) if shape is not None else 0.0
        key = (char, _quantise(blink, Q_BLINK), drawn_mouth,
               shape if shape is not None else None, gaze, eye_scale)
        img = self._frame(key)
        if img is None:
            return None, 0.0, False

        squash = _quantise(squash, Q_SQUASH)
        if squash < 0.999:
            new_h = max(int(self.size * squash), 1)
            img = img.resize((self.size, new_h), Image.BILINEAR)
            key = key + (squash,)
        if abs(angle) >= Q_TILT:
            img = self._tilted_frame(key, img, angle)
            key = key + (angle,)
        self.last_key = key

        k = self.size / CANVAS
        offset_y = breathe * k + dip - SPEAK_BOB_PX * mouth
        return img, offset_y, self.active(now)

    @property
    def pad(self):
        """Pixels a tilted face can reach past each side of its tile."""
        return int(math.ceil(self.size * TILT_PAD))


def load_renderer(path=None):
    """Load the face spec, or return ``None`` if it is unavailable."""
    path = path or DEFAULT_FACES_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return FaceRenderer(json.load(fh))
    except (OSError, ValueError) as exc:
        print(f"[FaceEngine] could not load {path}: {exc}")
        return None
