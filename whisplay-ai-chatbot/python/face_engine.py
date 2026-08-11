"""Animated face rendering for the Whisplay display.

The face set is authored in ``face_gen.py`` and serialised to ``faces.json`` as a
list of primitive shapes on a 100x100 canvas. This module is the runtime half: it
draws those primitives with PIL and layers a small animation state machine on top
so the character blinks, talks, breathes, and morphs between emotions instead of
snapping between still frames.

Only emoji that exist in ``faces.json`` are handled here. Anything else (tool and
status glyphs such as 🔧 or 📷) returns ``None`` so the caller can fall back to the
regular SVG/text drawing path.
"""

import json
import math
import os
import random
import time

from PIL import Image, ImageDraw

CANVAS = 100.0
DEFAULT_FACES_PATH = os.path.join(os.path.dirname(__file__), "faces.json")

# Animation timing (seconds).
BLINK_MIN_GAP = 2.6
BLINK_MAX_GAP = 6.2
BLINK_CLOSE = 0.055
BLINK_HOLD = 0.035
BLINK_OPEN = 0.075
BLINK_TOTAL = BLINK_CLOSE + BLINK_HOLD + BLINK_OPEN

TRANSITION_TIME = 0.28
BREATHE_PERIOD = 3.4
BREATHE_AMPLITUDE = 1.7  # canvas units

TALK_ATTACK = 0.06  # how quickly the mouth follows its target

# Quantisation steps for the frame cache. Animation is continuous but the eye is
# not, and re-rasterising every micro-step would be wasted work on a Pi.
Q_BLINK = 0.125
Q_MOUTH = 0.125
Q_SQUASH = 0.04

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


def _ease_in_out(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


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

    def has(self, char):
        return char in self.faces

    # -- primitive drawing -------------------------------------------------
    # All primitives are authored on a 100x100 canvas; ``k`` scales to pixels.

    def _pill(self, img, e, k):
        w, h = max(e["w"] * k, 1), max(e["h"] * k, 1)
        layer = Image.new("RGBA", (int(w) + 4, int(h) + 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle([2, 2, w + 1, h + 1], radius=min(w, h) / 2,
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

    def _draw_elem(self, img, e, k):
        fn = {
            "pill": self._pill, "circle": self._circle, "arc": self._arc,
            "flat": self._flat, "o": self._o, "zigzag": self._zigzag,
            "heart": self._heart, "star": self._star, "drop": self._drop,
            "zzz": self._zzz, "blush": self._blush, "grin": self._grin,
            "caret": self._caret, "x": self._x,
        }.get(e["t"])
        if fn:
            fn(img, e, k)

    # -- frame composition -------------------------------------------------

    def _draw_frame(self, img, size, k, color=None):
        """Stroke the bezel ring around the panel."""
        if not self.frame:
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
        ring = Image.new("RGBA", (size, size),
                         _as_rgb(color or self.frame.get("color", "#3A4657")) + (255,))
        ring.putalpha(mask.resize((size, size), Image.LANCZOS))
        img.alpha_composite(ring)

    def draw(self, char, size, blink=0.0, mouth_open=0.0, frame_color=None):
        """Render one face frame at ``size`` pixels square."""
        face = self.faces.get(char)
        if face is None:
            return None
        k = size / CANVAS
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        m = self.panel_margin * k
        d.rounded_rectangle([m, m, size - m, size - m], radius=self.panel_rx * k,
                            fill=_rgb(self.panel_fill) + (255,))

        elems = face["elems"]
        eyes = [e for e in elems if e.get("role") == "eye"]
        mouth = [e for e in elems if e.get("role") == "mouth"]
        rest = [e for e in elems if e.get("role") not in ("eye", "mouth")]

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
            h = 2.5 + 15.0 * mouth_open
            self._grin(img, {
                "cx": anchor["cx"], "cy": anchor["cy"] - h * 0.18,
                "w": anchor["w"] * (0.78 + 0.22 * mouth_open), "h": h,
                "color": anchor.get("color", "#F5F5F0"),
                "inner": anchor.get("inner", "#B32B3E"),
            }, k)
        else:
            for e in mouth:
                self._draw_elem(img, e, k)

        # Last, so a tear or a Zzz that strays into the margin sits behind it.
        self._draw_frame(img, size, k, frame_color)
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
            w = e.get("w") or (e.get("r", 6) * 2) or (e.get("size", 12))
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            self._stroke(layer, [(cx - w * 0.55, cy), (cx + w * 0.55, cy)],
                         4.5, e.get("color", "#F5F5F0"), k)
            if alpha < 1.0:
                layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
            img.alpha_composite(layer)


class FaceAnimator:
    """Drives blinking, talking, breathing and emotion transitions."""

    def __init__(self, renderer, size=40, emotion=None, idle_motion=True):
        self.renderer = renderer
        self.size = size
        self.idle_motion = idle_motion
        self.current = emotion if emotion and renderer.has(emotion) else None
        self.previous = None
        self.transition_start = None
        self.talking = False
        self.frame_color = None  # None keeps the neutral bezel from faces.json
        self._mouth = 0.0
        self._blink_start = None
        self._next_blink = time.time() + random.uniform(BLINK_MIN_GAP, BLINK_MAX_GAP)
        self._cache = {}
        self._t0 = time.time()

    # -- state ------------------------------------------------------------

    def set_emotion(self, char, now=None):
        """Point the face at a new emotion. Returns True if it is animatable."""
        if not self.renderer.has(char):
            self.current = None
            return False
        if char == self.current:
            return True
        if now is None:
            now = time.time()
        if self.current is not None:
            self.previous = self.current
            self.transition_start = now
        self.current = char
        return True

    def set_talking(self, talking):
        self.talking = bool(talking)

    def set_frame_color(self, color):
        """Tint the bezel, e.g. with the status colour. ``None`` restores default."""
        color = _as_rgb(color) if color else None
        if color != self.frame_color:
            # Every cached frame carries the old ring, so none of them are worth
            # keeping. Dropping them also stops a long session from filling the
            # cache with one dead colour per status change.
            self._cache.clear()
            self.frame_color = color

    def active(self):
        """True while the face still has motion to render."""
        if self.current is None:
            return False
        if self.transition_start is not None:
            return True
        if self.talking:
            return True
        if self._blink_start is not None:
            return True
        return self.idle_motion

    # -- per-frame parameters ---------------------------------------------

    def _blink_amount(self, now):
        if self._blink_start is None:
            if now >= self._next_blink:
                self._blink_start = now
            else:
                return 0.0
        t = now - self._blink_start
        if t >= BLINK_TOTAL:
            self._blink_start = None
            self._next_blink = now + random.uniform(BLINK_MIN_GAP, BLINK_MAX_GAP)
            return 0.0
        if t < BLINK_CLOSE:
            return _ease_in_out(t / BLINK_CLOSE)
        if t < BLINK_CLOSE + BLINK_HOLD:
            return 1.0
        return 1.0 - _ease_in_out((t - BLINK_CLOSE - BLINK_HOLD) / BLINK_OPEN)

    def _talk_amount(self, now):
        if not self.talking:
            target = 0.0
        else:
            # Two incommensurate sines read as speech rather than a metronome.
            a = math.sin(2 * math.pi * 5.4 * now)
            b = math.sin(2 * math.pi * 3.1 * now + 1.7)
            target = max(0.0, 0.55 + 0.32 * a + 0.18 * b)
            target = min(1.0, target)
        self._mouth += (target - self._mouth) * TALK_ATTACK * 8.0
        return max(0.0, min(1.0, self._mouth))

    def _breathe_offset(self, now):
        if not self.idle_motion:
            return 0.0
        return BREATHE_AMPLITUDE * math.sin(2 * math.pi * (now - self._t0) / BREATHE_PERIOD)

    # -- rendering ---------------------------------------------------------

    def _cached(self, char, blink, mouth):
        key = (char, self.size, round(blink, 3), round(mouth, 3), self.frame_color)
        img = self._cache.get(key)
        if img is None:
            img = self.renderer.draw(char, self.size, blink=blink, mouth_open=mouth,
                                     frame_color=self.frame_color)
            if img is not None and len(self._cache) < 512:
                self._cache[key] = img
        return img

    def render(self, now=None):
        """Return ``(RGBA image or None, vertical offset in px, animation_active)``."""
        if self.current is None:
            return None, 0.0, False
        if now is None:
            now = time.time()

        blink = self._blink_amount(now)
        mouth = self._talk_amount(now)
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

        img = self._cached(char, _quantise(blink, Q_BLINK), _quantise(mouth, Q_MOUTH))
        if img is None:
            return None, 0.0, False

        squash = _quantise(squash, Q_SQUASH)
        if squash < 0.999:
            new_h = max(int(self.size * squash), 1)
            img = img.resize((self.size, new_h), Image.BILINEAR)

        offset_y = self._breathe_offset(now) * (self.size / CANVAS) + dip
        return img, offset_y, self.active()


def load_renderer(path=None):
    """Load the face spec, or return ``None`` if it is unavailable."""
    path = path or DEFAULT_FACES_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return FaceRenderer(json.load(fh))
    except (OSError, ValueError) as exc:
        print(f"[FaceEngine] could not load {path}: {exc}")
        return None
