"""Authoring tool for the Whisplay face set.

Defines every expression once as a list of primitive shapes on a 100x100 canvas,
then emits both consumers of that definition:

  * ``emoji_svg/<codepoint>.svg`` — static glyphs for the existing emoji lookup
    path (``EmojiUtils.emoji_to_filename``), so any face also works as plain text.
  * ``faces.json`` — the same primitives with role tags, read at runtime by
    ``face_engine.py`` to animate blinking, talking and emotion transitions.

The set is drawn in a kawaii style: glossy black eyes with highlight glints,
thin lashes, pink cheek blush and small coloured mouths on a warm white panel.

Run it after changing any expression:

    python3 face_gen.py                 # writes both outputs in place
    python3 face_gen.py --preview p.png # also writes a contact sheet
"""

import argparse
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SVG_DIR = os.path.join(HERE, "emoji_svg")
JSON_PATH = os.path.join(HERE, "faces.json")

W = H = 100
PANEL_MARGIN = 6
PANEL_RX = 26

# Bezel drawn around the panel: a rounded outline living in the canvas margin,
# clear of the panel edge so the face reads as something mounted in a frame.
FRAME_WIDTH = 2.2   # thin bezel; the ring is an outline, not a housing
FRAME_INSET = 1.2
FRAME_RX = PANEL_RX + (PANEL_MARGIN - (FRAME_INSET + FRAME_WIDTH / 2))

# No ornaments on the bezel: at this size a delicate outline flatters the face,
# where anything perched on the corners just crowds it.
EARS = []

# The face card is a barrel-curved CRT outline rather than a rounded square:
# a superellipse, wider than it is tall. Both the panel and the bezel ring take
# this silhouette, and the face art is clipped to it, so the three always agree.
# --- silhouette ----------------------------------------------------------
# A wide, round cat head. The head is a superellipse and each ear is spliced
# into the crown in walk order, joined at the exact points the crown arc left,
# so the outline stays simple. Ear tips are rounded with a true tangent fillet
# rather than a chopped corner.
SHAPE_NAME = "cat-wide-round"
HEAD_RX, HEAD_RY, HEAD_CY, HEAD_POWER = 47.0, 37.0, 59.0, 0.9
EAR_SPAN = (60.0, 92.0)
EAR_TIP = (77.0, 2.5)
EAR_FILLET = 5.0
SHAPE_STEPS = 280


def head_top(x, rx=HEAD_RX, ry=HEAD_RY, cy=HEAD_CY, power=HEAD_POWER):
    """Y of the head outline directly above ``x`` -- where an ear must attach."""
    u = min(abs(x - 50.0) / rx, 1.0)
    ct = u ** (1.0 / power)
    st = math.sqrt(max(0.0, 1.0 - ct * ct))
    return cy - ry * (st ** power)


def fillet(a, tip, b, radius, steps=14):
    """Round the corner at ``tip`` with an arc tangent to both edges."""
    ax, ay = a[0] - tip[0], a[1] - tip[1]
    bx, by = b[0] - tip[0], b[1] - tip[1]
    la = math.hypot(ax, ay) or 1.0
    lb = math.hypot(bx, by) or 1.0
    ux, uy = ax / la, ay / la
    vx, vy = bx / lb, by / lb
    theta = math.acos(max(-1.0, min(1.0, ux * vx + uy * vy)))
    if theta < 1e-6 or theta > math.pi - 1e-6:
        return [list(tip)]
    half = theta / 2.0
    d = radius / math.tan(half)
    if d >= la or d >= lb:                      # corner too tight for this radius
        return [list(tip)]
    p1 = (tip[0] + ux * d, tip[1] + uy * d)
    p2 = (tip[0] + vx * d, tip[1] + vy * d)
    wx, wy = ux + vx, uy + vy
    lw = math.hypot(wx, wy) or 1.0
    c = (tip[0] + wx / lw * (radius / math.sin(half)),
         tip[1] + wy / lw * (radius / math.sin(half)))
    a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
    a2 = math.atan2(p2[1] - c[1], p2[0] - c[0])
    d_ang = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
    return [[round(c[0] + radius * math.cos(a1 + d_ang * i / steps), 3),
             round(c[1] + radius * math.sin(a1 + d_ang * i / steps), 3)]
            for i in range(steps + 1)]


def shape_points(n=SHAPE_STEPS, fillet_r=EAR_FILLET):
    x0, x1 = EAR_SPAN
    a = [x0, round(head_top(x0), 3)]
    b = [x1, round(head_top(x1), 3)]
    right = [a] + fillet(a, EAR_TIP, b, fillet_r) + [b]
    left = [[100.0 - p[0], p[1]] for p in reversed(right)]
    zones = [(100.0 - x1, 100.0 - x0, left), (x0, x1, right)]

    out, done = [], set()
    for i in range(n):
        t = 2 * math.pi * i / n
        ct, st = math.cos(t), math.sin(t)
        x = 50 + HEAD_RX * math.copysign(abs(ct) ** HEAD_POWER, ct)
        y = HEAD_CY + HEAD_RY * math.copysign(abs(st) ** HEAD_POWER, st)
        z = next((j for j, (lo, hi, _) in enumerate(zones)
                  if lo <= x <= hi and y < HEAD_CY), None)
        if z is None:
            out.append([round(x, 3), round(y, 3)])
            continue
        if z not in done:
            done.add(z)
            pts = zones[z][2]
            if out and x < out[-1][0]:          # walking right-to-left
                pts = list(reversed(pts))
            out.extend([[float(p[0]), float(p[1])] for p in pts])
    return out


SHAPE = shape_points()


def scaled(pts, inset):
    """The silhouette shrunk toward the centre, used for the ring's two edges."""
    f = (50.0 - inset) / 50.0
    return [[round(50 + (x - 50) * f, 3), round(50 + (y - 50) * f, 3)] for x, y in pts]


PANEL = "#FFFDF8"      # warm white face card
INK = "#22222A"        # eyes, lashes, line work
BLUSH = "#FF9DB4"
MOUTH = "#E8455F"
MOUTH_IN = "#C42B45"
TONGUE = "#FF7D93"
TEAR = "#6FC3F5"
GREEN = "#9BD94E"
ANGER = "#FF3B5C"
GOLD = "#FFC93D"
# The bezel is a vertical coral-to-rose wash. FRAME is the flat mid tone used
# as a fallback wherever a gradient cannot be drawn (and when the runtime tints
# the ring with a status colour).
FRAME = "#FF9A9A"
FRAME_FROM = "#FFA58C"   # coral at the top
FRAME_TO = "#FF8FA8"     # rose at the bottom
FRAME_INNER = "#FFE3EA"

# Shared geometry so every face sits on the same grid.
EYE_X, EYE_Y = 31, 45
EYE_RX, EYE_RY = 13, 15.5
LASH_Y = 26
BLUSH_X, BLUSH_Y = 14, 64
MOUTH_Y = 72


class Face:
    def __init__(self):
        self.elems = []

    def _add(self, **kw):
        self.elems.append(kw)

    # -- kawaii primitives -------------------------------------------------

    def eye(self, cx, cy, rx, ry, color=INK, glint=True, lid=0.0, role="eye"):
        """Glossy oval eye. ``lid`` (0..1) covers the top for a half-shut look."""
        self._add(t="eye", cx=cx, cy=cy, rx=rx, ry=ry, color=color,
                  glint=glint, lid=lid, panel=PANEL, role=role)

    def oval(self, cx, cy, rx, ry, color=MOUTH, outline=None, stroke=2.5, role=None):
        self._add(t="oval", cx=cx, cy=cy, rx=rx, ry=ry, color=color,
                  outline=outline, stroke=stroke, role=role)

    def hatch(self, cx, cy, w, h, n=3, stroke=2.6, color=BLUSH, role="blush"):
        self._add(t="hatch", cx=cx, cy=cy, w=w, h=h, n=n, stroke=stroke,
                  color=color, role=role)

    def anger(self, cx, cy, size, color=ANGER, role="deco"):
        self._add(t="anger", cx=cx, cy=cy, size=size, color=color, role=role)

    def cat(self, cx, cy, w, h, stroke=4.0, color=INK, role="mouth"):
        self._add(t="cat", cx=cx, cy=cy, w=w, h=h, stroke=stroke, color=color, role=role)

    def tri(self, cx, cy, w, h, color=MOUTH, down=True, role="mouth"):
        self._add(t="tri", cx=cx, cy=cy, w=w, h=h, color=color, down=down, role=role)

    # -- shared primitives -------------------------------------------------

    def pill(self, cx, cy, w, h, rot=0, color=INK, role=None):
        self._add(t="pill", cx=cx, cy=cy, w=w, h=h, rot=rot, color=color, role=role)

    def circle(self, cx, cy, r, color=INK, pupil_r=None, pupil_color=PANEL, role=None):
        self._add(t="circle", cx=cx, cy=cy, r=r, color=color,
                  pupil_r=pupil_r, pupil_color=pupil_color, role=role)

    def arc(self, cx, cy, w, depth, rot=0, stroke=3.4, color=INK, role=None):
        self._add(t="arc", cx=cx, cy=cy, w=w, depth=depth, rot=rot,
                  stroke=stroke, color=color, role=role)

    def curve(self, cx, cy, w, depth, stroke=3.4, color=INK, role=None):
        self.arc(cx, cy, w, depth, rot=0, stroke=stroke, color=color, role=role)

    def flat(self, cx, cy, w, stroke=4.2, color=INK, role=None):
        self._add(t="flat", cx=cx, cy=cy, w=w, stroke=stroke, color=color, role=role)

    def o_mouth(self, cx, cy, r, stroke=3.8, color=INK, role="mouth"):
        self._add(t="o", cx=cx, cy=cy, r=r, stroke=stroke, color=color, role=role)

    def zigzag(self, cx, cy, w, h, n, stroke=3.6, color=INK, role=None):
        self._add(t="zigzag", cx=cx, cy=cy, w=w, h=h, n=n, stroke=stroke,
                  color=color, role=role)

    def heart(self, cx, cy, size, color=MOUTH, role=None):
        self._add(t="heart", cx=cx, cy=cy, size=size, color=color, role=role)

    def star(self, cx, cy, size, color=GOLD, role=None):
        self._add(t="star", cx=cx, cy=cy, size=size, color=color, role=role)

    def drop(self, cx, cy, w, h, color=TEAR, role="deco"):
        self._add(t="drop", cx=cx, cy=cy, w=w, h=h, color=color, role=role)

    def zzz(self, cx, cy, scale=1.0, color=INK, role="deco"):
        self._add(t="zzz", cx=cx, cy=cy, scale=scale, color=color, role=role)

    def blush(self, cx, cy, rx, ry=None, color=BLUSH, opacity=1.0, role="blush"):
        self._add(t="blush", cx=cx, cy=cy, rx=rx, ry=ry if ry else rx * 0.64,
                  color=color, opacity=opacity, role=role)

    def grin(self, cx, cy, w, h, tongue=False, color=INK, inner=MOUTH_IN, role="mouth"):
        self._add(t="grin", cx=cx, cy=cy, w=w, h=h, tongue=tongue, color=color,
                  inner=inner, tongue_color=TONGUE, role=role)

    def caret(self, cx, cy, w, h, down=False, stroke=3.4, color=INK, role=None):
        self._add(t="caret", cx=cx, cy=cy, w=w, h=h, down=down, stroke=stroke,
                  color=color, role=role)

    def x_mark(self, cx, cy, size, stroke=3.2, color=INK, role=None):
        self._add(t="x", cx=cx, cy=cy, size=size, stroke=stroke, color=color, role=role)


def pair(f, method, cx, cy, *args, **kw):
    """Add a shape and its mirror across the vertical centre line."""
    getattr(f, method)(cx, cy, *args, **kw)
    mk = dict(kw)
    if mk.get("rot"):
        mk["rot"] = -mk["rot"]
    if mk.get("down_mirror"):
        mk.pop("down_mirror")
    getattr(f, method)(100 - cx, cy, *args, **mk)


FACES = {}


def emo(name, codepoint, char):
    f = Face()
    FACES[name] = {"cp": codepoint, "char": char, "face": f}
    return f


# --- composition helpers -------------------------------------------------

def eyes(f, cy=EYE_Y, rx=EYE_RX, ry=EYE_RY, glint=True, lid=0.0, color=INK):
    f.eye(EYE_X, cy, rx, ry, color=color, glint=glint, lid=lid)
    f.eye(100 - EYE_X, cy, rx, ry, color=color, glint=glint, lid=lid)


def happy_eyes(f, cy=46, w=22, depth=-11, stroke=4.0):
    """The upward ^^ arcs used for closed, delighted eyes."""
    f.arc(EYE_X, cy, w, depth, stroke=stroke, role="eye")
    f.arc(100 - EYE_X, cy, w, depth, stroke=stroke, role="eye")


def lashes(f, cy=LASH_Y, w=20, depth=-8, stroke=3.0):
    f.arc(EYE_X, cy, w, depth, stroke=stroke, role="deco")
    f.arc(100 - EYE_X, cy, w, depth, stroke=stroke, role="deco")


def brows(f, cy=25, w=19, tilt=16, stroke=3.6, color=INK):
    """Angled brows; positive tilt slants inward (angry)."""
    f.pill(EYE_X - 1, cy, w, stroke, -tilt, color=color, role="deco")
    f.pill(101 - EYE_X, cy, w, stroke, tilt, color=color, role="deco")


def cheeks(f, cy=BLUSH_Y, cx=BLUSH_X, rx=8.6):
    f.blush(cx, cy, rx)
    f.blush(100 - cx, cy, rx)


def hatch_cheeks(f, cy=BLUSH_Y, cx=BLUSH_X, w=13, h=9, n=3):
    f.hatch(cx, cy, w, h, n)
    f.hatch(100 - cx, cy, w, h, n)


# --- expressions ---------------------------------------------------------
# Eyes are role="eye" so blinks can squash them; the resting mouth is
# role="mouth" so talking can replace it; lashes/brows/tears stay as "deco".

f = emo("neutral", "1f610", "😐")
cheeks(f); lashes(f); eyes(f)
f.flat(50, MOUTH_Y, 13, role="mouth")

f = emo("slight_smile", "1f642", "🙂")
cheeks(f); lashes(f); eyes(f)
f.curve(50, MOUTH_Y - 3, 17, 7, role="mouth", stroke=4.2)

f = emo("happy", "1f60a", "😊")
cheeks(f); lashes(f); eyes(f)
f.curve(50, MOUTH_Y - 3, 21, 9, role="mouth", stroke=4.2)

f = emo("joy", "1f604", "😄")
cheeks(f, cy=66); happy_eyes(f)
f.grin(50, 62, 30, 18)

f = emo("grin", "1f601", "😁")
cheeks(f, cy=66); happy_eyes(f)
f.grin(50, 61, 34, 20)

f = emo("laughing_squint", "1f606", "😆")
cheeks(f, cy=66); happy_eyes(f, cy=47, w=24, depth=-13)
f.grin(50, 60, 36, 22)

f = emo("laughing", "1f602", "😂")
cheeks(f, cy=66); happy_eyes(f, cy=47, w=23, depth=-12)
f.grin(50, 60, 34, 21, tongue=True)
f.drop(12, 54, 7, 12); f.drop(88, 54, 7, 12)

f = emo("rofl", "1f923", "🤣")
cheeks(f, cy=66); happy_eyes(f, cy=47, w=24, depth=-13)
f.grin(50, 59, 36, 23, tongue=True)
f.drop(11, 52, 7, 13); f.drop(89, 52, 7, 13)
f.drop(15, 70, 5, 9); f.drop(85, 70, 5, 9)

f = emo("nervous", "1f605", "😅")
cheeks(f, cy=66); happy_eyes(f)
f.grin(50, 62, 28, 17)
f.drop(84, 27, 7, 12)

f = emo("wink", "1f609", "😉")
cheeks(f); lashes(f)
f.eye(EYE_X, EYE_Y, EYE_RX, EYE_RY)
f.arc(100 - EYE_X, 47, 22, -11, stroke=4.0, role="eye")
f.curve(50, MOUTH_Y - 3, 19, 8, role="mouth", stroke=4.2)

f = emo("love", "1f60d", "😍")
cheeks(f, cy=66)
f.heart(EYE_X, 45, 21, color=MOUTH, role="eye")
f.heart(100 - EYE_X, 45, 21, color=MOUTH, role="eye")
f.grin(50, 64, 26, 15)

f = emo("adoring", "1f970", "🥰")
cheeks(f); lashes(f); eyes(f)
f.curve(50, MOUTH_Y - 3, 21, 9, role="mouth", stroke=4.2)
f.heart(12, 30, 13, color=MOUTH); f.heart(88, 30, 13, color=MOUTH)

f = emo("kiss", "1f618", "😘")
cheeks(f); lashes(f)
f.eye(EYE_X, EYE_Y, EYE_RX, EYE_RY)
f.arc(100 - EYE_X, 47, 22, -11, stroke=4.0, role="eye")
f.oval(50, MOUTH_Y - 1, 6, 4.6, role="mouth")
f.heart(84, 66, 14, color=MOUTH)

f = emo("yum", "1f60b", "😋")
cheeks(f, cy=66); happy_eyes(f)
f.grin(50, 63, 26, 15, tongue=True)

f = emo("playful", "1f61c", "😜")
cheeks(f, cy=66); lashes(f)
f.eye(EYE_X, EYE_Y, EYE_RX, EYE_RY)
f.arc(100 - EYE_X, 47, 22, -11, stroke=4.0, role="eye")
f.grin(50, 64, 26, 15, tongue=True)

f = emo("tongue", "1f61b", "😛")
cheeks(f, cy=66); lashes(f); eyes(f)
f.grin(50, 66, 24, 14, tongue=True)

f = emo("excited", "1f929", "🤩")
cheeks(f, cy=66)
f.star(EYE_X, 45, 16, role="eye"); f.star(100 - EYE_X, 45, 16, role="eye")
f.grin(50, 63, 30, 18)

f = emo("cool", "1f60e", "😎")
cheeks(f, cy=66)
f.pill(50, 43, 62, 19, 0, color=INK, role="eye")
f.pill(50, 43, 6, 21, 0, color=PANEL, role="eye")
f.oval(38, 43, 12, 7, color="#4A5568", role="eye")
f.oval(62, 43, 12, 7, color="#4A5568", role="eye")
f.curve(54, MOUTH_Y - 2, 19, 8, role="mouth", stroke=4.2)

f = emo("smirk", "1f60f", "😏")
cheeks(f); eyes(f, lid=0.45)
f.arc(56, MOUTH_Y - 3, 20, 8, rot=-8, stroke=3.4, role="mouth")

f = emo("content", "1f60c", "😌")
cheeks(f); lashes(f); happy_eyes(f, cy=46, w=20, depth=-8)
f.curve(50, MOUTH_Y - 2, 15, 6, role="mouth", stroke=4.2)

f = emo("thinking", "1f914", "🤔")
f.blush(BLUSH_X, BLUSH_Y, 8.6); f.blush(100 - BLUSH_X, BLUSH_Y, 8.6)
f.arc(EYE_X, LASH_Y, 20, -8, stroke=3.0, role="deco")
f.pill(100 - EYE_X, 22, 18, 3.4, -18, color=INK, role="deco")
f.eye(EYE_X, EYE_Y, EYE_RX, EYE_RY)
f.eye(100 - EYE_X, 43, 11, 12.5)
f.arc(54, MOUTH_Y - 1, 15, 5, rot=-10, stroke=3.2, role="mouth")

f = emo("expressionless", "1f611", "😑")
cheeks(f, cy=62); lashes(f)
f.flat(EYE_X, 46, 22, stroke=4.0, role="eye")
f.flat(100 - EYE_X, 46, 22, stroke=4.0, role="eye")
f.flat(50, MOUTH_Y, 12, role="mouth")

f = emo("no_mouth", "1f636", "😶")
cheeks(f); lashes(f); eyes(f)

f = emo("grimace", "1f62c", "😬")
cheeks(f, cy=64); lashes(f); eyes(f, ry=13)
f.oval(50, MOUTH_Y, 15, 6.5, color=PANEL, outline=INK, stroke=3.0, role="mouth")
f.flat(50, MOUTH_Y, 26, stroke=2.6, role="deco")

f = emo("confused", "1f615", "😕")
cheeks(f); lashes(f)
f.eye(EYE_X, EYE_Y, EYE_RX, EYE_RY)
f.eye(100 - EYE_X, 43, 11, 12.5)
f.zigzag(50, MOUTH_Y, 19, 5, 3, role="mouth")

f = emo("worried", "1f61f", "😟")
cheeks(f); brows(f, cy=24, tilt=-15)
eyes(f, ry=14)
f.curve(50, MOUTH_Y + 2, 16, -7, role="mouth", stroke=4.2)

f = emo("slight_frown", "1f641", "🙁")
cheeks(f); lashes(f); eyes(f)
f.curve(50, MOUTH_Y + 2, 17, -7, role="mouth", stroke=4.2)

f = emo("dejected", "1f614", "😔")
cheeks(f, cy=62); brows(f, cy=25, tilt=-13)
eyes(f, cy=47, ry=11, lid=0.5)
f.curve(50, MOUTH_Y + 2, 15, -6, role="mouth", stroke=4.2)

f = emo("sad", "1f622", "😢")
cheeks(f); brows(f, cy=24, tilt=-15)
eyes(f)
f.curve(50, MOUTH_Y + 2, 16, -7, role="mouth", stroke=4.2)
f.drop(20, 62, 7, 12)

f = emo("crying", "1f62d", "😭")
cheeks(f, cy=68); brows(f, cy=24, tilt=-15)
happy_eyes(f, cy=52, w=22, depth=11)
f.grin(50, 66, 26, 16)
f.oval(20, 66, 5.5, 12, color=TEAR); f.oval(80, 66, 5.5, 12, color=TEAR)

f = emo("pleading", "1f97a", "🥺")
cheeks(f, cy=66); brows(f, cy=22, tilt=-14)
eyes(f, cy=46, rx=14.5, ry=17)
f.curve(50, MOUTH_Y + 3, 13, -5, stroke=3.0, role="mouth")

f = emo("flushed", "1f633", "😳")
f.blush(BLUSH_X + 1, 62, 11.5); f.blush(99 - BLUSH_X, 62, 11.5)
lashes(f)
eyes(f, rx=14, ry=16.5)
f.oval(50, MOUTH_Y + 1, 5.5, 4.2, role="mouth")

f = emo("surprised", "1f62e", "😮")
cheeks(f, cy=66); lashes(f); eyes(f)
f.oval(50, MOUTH_Y + 1, 6.5, 8, color=MOUTH_IN, role="mouth")

f = emo("astonished", "1f632", "😲")
cheeks(f, cy=68); lashes(f, cy=24)
eyes(f, cy=43, rx=14, ry=16.5)
f.oval(50, 73, 8.5, 11, color=MOUTH_IN, role="mouth")

f = emo("scared", "1f631", "😱")
brows(f, cy=22, tilt=-16)
eyes(f, cy=43, rx=14.5, ry=17)
f.oval(50, 74, 9, 12, color=MOUTH_IN, role="mouth")
f.drop(86, 30, 6, 11)

f = emo("fearful", "1f628", "😨")
cheeks(f, cy=68); brows(f, cy=23, tilt=-15)
eyes(f, cy=45, rx=13.5, ry=16)
f.oval(50, MOUTH_Y + 2, 7, 8.5, color=MOUTH_IN, role="mouth")
f.drop(85, 28, 6, 11)

f = emo("anxious", "1f630", "😰")
hatch_cheeks(f, cy=64)
brows(f, cy=23, tilt=-15)
eyes(f, cy=45, ry=15)
f.curve(50, MOUTH_Y + 2, 15, -6, role="mouth", stroke=4.2)
f.drop(85, 28, 6, 11); f.drop(14, 30, 5, 9)

f = emo("angry", "1f620", "😠")
cheeks(f, cy=66); brows(f, cy=25, tilt=18, color=INK)
eyes(f, cy=47, ry=14)
f.flat(50, MOUTH_Y + 1, 13, stroke=3.6, role="mouth")
f.anger(80, 24, 13)

f = emo("rage", "1f621", "😡")
cheeks(f, cy=66); brows(f, cy=25, tilt=18, color=ANGER)
eyes(f, cy=47, ry=14, color=ANGER)
f.grin(50, 68, 22, 13, color=ANGER, inner=MOUTH_IN)
f.anger(80, 23, 14); f.anger(20, 23, 12)

f = emo("huffing", "1f624", "😤")
cheeks(f, cy=66); brows(f, cy=25, tilt=16)
eyes(f, cy=47, ry=13, lid=0.35)
f.flat(50, MOUTH_Y + 1, 14, stroke=3.6, role="mouth")
f.arc(34, 84, 13, 7, stroke=3.0, color="#9FB3C8", role="deco")
f.arc(66, 84, 13, 7, stroke=3.0, color="#9FB3C8", role="deco")

f = emo("sleepy", "1f634", "😴")
cheeks(f, cy=62)
happy_eyes(f, cy=47, w=21, depth=9)
f.oval(50, MOUTH_Y + 2, 5.5, 6.5, color=MOUTH_IN, role="mouth")
f.zzz(80, 20, scale=1.0)

f = emo("drowsy", "1f62a", "😪")
cheeks(f, cy=62); lashes(f)
eyes(f, cy=47, ry=10, lid=0.55)
f.curve(50, MOUTH_Y + 1, 13, -5, stroke=3.0, role="mouth")
f.oval(78, 60, 6, 8, color=TEAR)

f = emo("drooling", "1f924", "🤤")
cheeks(f, cy=64); happy_eyes(f, cy=46, w=20, depth=-8)
f.curve(50, MOUTH_Y - 2, 18, 8, role="mouth", stroke=4.2)
f.oval(60, 80, 3.6, 6, color=TEAR)

f = emo("nauseated", "1f922", "🤢")
f.blush(BLUSH_X, BLUSH_Y, 8.6, color=GREEN); f.blush(100 - BLUSH_X, BLUSH_Y, 8.6, color=GREEN)
brows(f, cy=24, tilt=-14)
happy_eyes(f, cy=47, w=21, depth=9)
f.oval(50, 74, 11, 8, color=GREEN, role="mouth")
f.oval(50, 82, 7, 6, color=GREEN, role="deco")

f = emo("sick", "1f912", "🤒")
cheeks(f, cy=66, rx=9.5)
brows(f, cy=24, tilt=-13)
eyes(f, cy=47, ry=12, lid=0.4)
f.curve(50, MOUTH_Y + 2, 14, -6, role="mouth", stroke=4.2)
f.pill(50, 22, 42, 7, 0, color="#DCE7F2", role="deco")
f.oval(31, 22, 4.2, 4.2, color=MOUTH, role="deco")

f = emo("dizzy", "1f635", "😵")
cheeks(f, cy=66); lashes(f)
f.x_mark(EYE_X, 46, 18, stroke=4.0, role="eye")
f.x_mark(100 - EYE_X, 46, 18, stroke=4.0, role="eye")
f.zigzag(50, MOUTH_Y, 21, 5, 4, role="mouth")

f = emo("hug", "1f917", "🤗")
cheeks(f, cy=66); happy_eyes(f)
f.grin(50, 63, 28, 17)
f.arc(13, 68, 15, -9, stroke=3.4, role="deco")
f.arc(87, 68, 15, -9, stroke=3.4, role="deco")

f = emo("cat_smile", "1f63a", "😺")
cheeks(f); lashes(f); eyes(f)
f.cat(50, MOUTH_Y - 2, 20, 7)

f = emo("robot", "1f916", "🤖")
f.pill(EYE_X, 45, 20, 12, 0, color=INK, role="eye")
f.pill(100 - EYE_X, 45, 20, 12, 0, color=INK, role="eye")
f.oval(EYE_X, 45, 4, 4, color="#6FE3FF", role="eye")
f.oval(100 - EYE_X, 45, 4, 4, color="#6FE3FF", role="eye")
f.flat(50, MOUTH_Y, 20, stroke=3.6, role="mouth")
f.pill(50, 16, 4, 10, 0, color=INK, role="deco")


# --- cat treatment -------------------------------------------------------
# The 49 expressions are authored for an upright card. The cat head is wider and
# shorter, so rather than redraw every face the treatment is applied once here:
# a muzzle, nose and whiskers go on, and the whole layout is refitted to the new
# head. Set CAT_STYLE = False to ship the plain kawaii faces again.

CAT_STYLE = True
NOSE = "#FF7D93"
WHISKER = "#3A3A44"
INNER_EAR = "#FF9DB4"
CLOSED_MOUTHS = {"flat", "arc", "zigzag"}

# The card layout spans roughly y=20 (lashes) to y=84 (huffing's steam). The cat
# head is shorter, so the face is compressed about its own centre and recentred;
# translating alone pushed the low decorations out through the chin.
SRC_CENTRE, FIT_CENTRE, FIT_YSCALE = 52.0, 59.0, 0.92
FIT_SPREAD, FIT_EYE_GAIN = 1.05, 1.12
FIT_MAX_DX = HEAD_RX * 0.76


def _muzzle(elems):
    """Swap a closed line mouth for an omega muzzle; leave open mouths alone."""
    out, swapped = [], False
    for e in elems:
        if not swapped and e.get("role") == "mouth" and e["t"] in CLOSED_MOUTHS:
            swapped = True
            out.append({"t": "cat", "cx": e.get("cx", 50), "cy": e.get("cy", 70) - 1,
                        "w": max(e.get("w", 16) * 1.15, 17), "h": 6.0,
                        "stroke": 3.8, "color": INK, "role": "mouth"})
            continue
        out.append(e)
    return out


def _nose_and_whiskers(elems):
    mouth_y = next((e.get("cy", 70) for e in elems if e.get("role") == "mouth"), 70.0)
    out = [{"t": "tri", "cx": 50.0, "cy": round(mouth_y - 7.5, 3), "w": 7.0, "h": 5.0,
            "color": NOSE, "down": True, "role": "deco"}]
    for side in (-1, 1):
        for dy, length in ((-3.0, 17.0), (2.0, 19.0), (7.0, 17.0)):
            x0 = 50.0 + side * 20.0
            x1 = x0 + side * length
            out.append({"t": "flat", "cx": round((x0 + x1) / 2, 3),
                        "cy": round(mouth_y + dy - 2.0, 3), "w": abs(x1 - x0),
                        "stroke": 1.9, "color": WHISKER, "role": "deco"})
    return elems + out


def _refit(elems):
    """Fit the card layout into the wider, shorter head."""
    out = []
    for e in elems:
        e = dict(e)
        if "cx" in e:
            dx = (e["cx"] - 50) * FIT_SPREAD
            # Cap the offset at the head's usable half-width, or spreading flings
            # the outermost decorations (adoring's hearts) past the cheeks.
            e["cx"] = round(50 + max(-FIT_MAX_DX, min(FIT_MAX_DX, dx)), 3)
        if "cy" in e:
            e["cy"] = round(FIT_CENTRE + (e["cy"] - SRC_CENTRE) * FIT_YSCALE, 3)
        if e.get("role") == "eye":
            for f in ("rx", "ry", "r", "size"):
                if isinstance(e.get(f), (int, float)):
                    e[f] = round(e[f] * FIT_EYE_GAIN, 3)
            if e["t"] in ("arc", "flat", "caret", "x") and "w" in e:
                e["w"] = round(e["w"] * FIT_EYE_GAIN, 3)
        out.append(e)
    return out


def _inner_ears():
    x0, x1 = EAR_SPAN
    base_y = head_top((x0 + x1) / 2)
    h = (base_y - EAR_TIP[1]) * 0.52
    out = []
    for side in (1, -1):
        cx = (x0 + x1) / 2 if side == 1 else 100.0 - (x0 + x1) / 2
        tx = EAR_TIP[0] if side == 1 else 100.0 - EAR_TIP[0]
        out.append({"t": "tri", "cx": round((cx + tx) / 2, 3),
                    "cy": round(EAR_TIP[1] + EAR_FILLET * 0.55 + h * 0.62, 3),
                    "w": round((x1 - x0) * 0.42, 3), "h": round(h, 3),
                    "color": INNER_EAR, "down": False, "role": "deco"})
    return out


def catify(elems):
    if not CAT_STYLE:
        return elems
    return _refit(_nose_and_whiskers(_muzzle(elems))) + _inner_ears()


# --- mouth anchor --------------------------------------------------------

def mouth_anchor(elems):
    """Where a talking mouth should be drawn, derived from the resting mouth."""
    mouths = [e for e in elems if e.get("role") == "mouth"]
    if not mouths:
        return {"cx": 50, "cy": MOUTH_Y - 4, "w": 24, "color": INK, "inner": MOUTH_IN}
    e = mouths[0]
    base = {"color": INK, "inner": MOUTH_IN}
    if e["t"] == "grin":
        base.update(cx=e["cx"], cy=e["cy"], w=e["w"])
    elif e["t"] == "o":
        base.update(cx=e["cx"], cy=e["cy"] - e["r"], w=e["r"] * 3.4)
    elif e["t"] == "oval":
        base.update(cx=e["cx"], cy=e["cy"] - e["ry"], w=max(e["rx"] * 2.6, 18))
    elif e["t"] in ("flat", "arc", "zigzag", "cat"):
        base.update(cx=e["cx"], cy=e["cy"] - 3, w=e.get("w", 20) * 1.25)
    else:
        base.update(cx=e.get("cx", 50), cy=e.get("cy", MOUTH_Y) - 3, w=22)
    return base


# --- SVG output ----------------------------------------------------------

def svg_pill(e):
    x, y = e["cx"] - e["w"] / 2, e["cy"] - e["h"] / 2
    t = f' transform="rotate({e["rot"]} {e["cx"]} {e["cy"]})"' if e.get("rot") else ""
    return (f'<rect x="{x:.2f}" y="{y:.2f}" width="{e["w"]}" height="{e["h"]}" '
            f'rx="{min(e["w"], e["h"]) / 2:.2f}" fill="{e["color"]}"{t}/>')


def svg_circle(e):
    out = [f'<circle cx="{e["cx"]}" cy="{e["cy"]}" r="{e["r"]}" fill="{e["color"]}"/>']
    if e.get("pupil_r"):
        out.append(f'<circle cx="{e["cx"]}" cy="{e["cy"]}" r="{e["pupil_r"]}" '
                   f'fill="{e["pupil_color"]}"/>')
    return "".join(out)


def svg_eye(e):
    cx, cy, rx, ry = e["cx"], e["cy"], e["rx"], e["ry"]
    out = [f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{e["color"]}"/>']
    if e.get("lid"):
        lid_h = 2 * ry * e["lid"]
        out.append(f'<rect x="{cx - rx - 1:.2f}" y="{cy - ry - 1:.2f}" '
                   f'width="{2 * rx + 2:.2f}" height="{lid_h:.2f}" fill="{e["panel"]}"/>')
        out.append(f'<line x1="{cx - rx:.2f}" y1="{cy - ry + lid_h:.2f}" '
                   f'x2="{cx + rx:.2f}" y2="{cy - ry + lid_h:.2f}" '
                   f'stroke="{e["color"]}" stroke-width="3" stroke-linecap="round"/>')
    if e.get("glint"):
        gy = cy - ry * 0.38 + (2 * ry * e.get("lid", 0)) * 0.5
        out.append(f'<circle cx="{cx - rx * 0.34:.2f}" cy="{gy:.2f}" '
                   f'r="{rx * 0.36:.2f}" fill="#FFFFFF"/>')
        out.append(f'<circle cx="{cx + rx * 0.36:.2f}" cy="{cy + ry * 0.34:.2f}" '
                   f'r="{rx * 0.17:.2f}" fill="#FFFFFF"/>')
    return "".join(out)


def svg_oval(e):
    s = (f'<ellipse cx="{e["cx"]}" cy="{e["cy"]}" rx="{e["rx"]}" ry="{e["ry"]}" '
         f'fill="{e["color"]}"')
    if e.get("outline"):
        s += f' stroke="{e["outline"]}" stroke-width="{e["stroke"]}"'
    return s + "/>"


def svg_hatch(e):
    cx, cy, w, h, n = e["cx"], e["cy"], e["w"], e["h"], e["n"]
    step = w / max(n - 1, 1)
    x0 = cx - w / 2
    out = []
    for i in range(n):
        x = x0 + i * step
        out.append(f'<line x1="{x:.2f}" y1="{cy + h/2:.2f}" x2="{x + h*0.45:.2f}" '
                   f'y2="{cy - h/2:.2f}" stroke="{e["color"]}" '
                   f'stroke-width="{e["stroke"]}" stroke-linecap="round"/>')
    return "".join(out)


def svg_anger(e):
    cx, cy, s = e["cx"], e["cy"], e["size"] / 2
    d = (f"M {cx-s} {cy-s} L {cx-s*0.25} {cy-s*0.35} L {cx} {cy-s} "
         f"L {cx+s*0.25} {cy-s*0.35} L {cx+s} {cy-s} L {cx+s*0.35} {cy} "
         f"L {cx+s} {cy+s} L {cx+s*0.25} {cy+s*0.35} L {cx} {cy+s} "
         f"L {cx-s*0.25} {cy+s*0.35} L {cx-s} {cy+s} L {cx-s*0.35} {cy} Z")
    return f'<path d="{d}" fill="{e["color"]}"/>'


def svg_cat(e):
    cx, cy, w, h = e["cx"], e["cy"], e["w"], e["h"]
    q = w / 4
    d = (f"M {cx-w/2:.2f} {cy:.2f} Q {cx-q:.2f} {cy+h:.2f} {cx:.2f} {cy:.2f} "
         f"Q {cx+q:.2f} {cy+h:.2f} {cx+w/2:.2f} {cy:.2f}")
    return (f'<path d="{d}" fill="none" stroke="{e["color"]}" '
            f'stroke-width="{e["stroke"]}" stroke-linecap="round"/>')


def svg_tri(e):
    cx, cy, w, h = e["cx"], e["cy"], e["w"], e["h"]
    if e.get("down"):
        pts = f"{cx-w/2:.2f},{cy-h/2:.2f} {cx+w/2:.2f},{cy-h/2:.2f} {cx:.2f},{cy+h/2:.2f}"
    else:
        pts = f"{cx-w/2:.2f},{cy+h/2:.2f} {cx+w/2:.2f},{cy+h/2:.2f} {cx:.2f},{cy-h/2:.2f}"
    return f'<polygon points="{pts}" fill="{e["color"]}"/>'


def svg_arc(e):
    cx, cy, w = e["cx"], e["cy"], e["w"]
    d = f'M {cx - w/2:.2f} {cy:.2f} Q {cx:.2f} {cy + e["depth"]:.2f} {cx + w/2:.2f} {cy:.2f}'
    t = f' transform="rotate({e["rot"]} {cx} {cy})"' if e.get("rot") else ""
    return (f'<path d="{d}" stroke="{e["color"]}" stroke-width="{e["stroke"]}" '
            f'fill="none" stroke-linecap="round"{t}/>')


def svg_flat(e):
    return (f'<line x1="{e["cx"] - e["w"]/2:.2f}" y1="{e["cy"]}" '
            f'x2="{e["cx"] + e["w"]/2:.2f}" y2="{e["cy"]}" stroke="{e["color"]}" '
            f'stroke-width="{e["stroke"]}" stroke-linecap="round"/>')


def svg_o(e):
    return (f'<circle cx="{e["cx"]}" cy="{e["cy"]}" r="{e["r"]}" fill="none" '
            f'stroke="{e["color"]}" stroke-width="{e["stroke"]}"/>')


def svg_zigzag(e):
    cx, cy, w, h, n = e["cx"], e["cy"], e["w"], e["h"], e["n"]
    x0, step = cx - w / 2, w / n
    pts = " ".join(f"{x0 + i*step:.2f},{cy + (h/2 if i % 2 == 0 else -h/2):.2f}"
                   for i in range(n + 1))
    return (f'<polyline points="{pts}" fill="none" stroke="{e["color"]}" '
            f'stroke-width="{e["stroke"]}" stroke-linecap="round" stroke-linejoin="round"/>')


def svg_heart(e):
    cx, cy, s = e["cx"], e["cy"], e["size"]
    d = (f"M {cx} {cy + s*0.32} C {cx - s*0.7} {cy - s*0.18}, {cx - s*0.32} {cy - s*0.62}, "
         f"{cx} {cy - s*0.22} C {cx + s*0.32} {cy - s*0.62}, {cx + s*0.7} {cy - s*0.18}, "
         f"{cx} {cy + s*0.32} Z")
    return f'<path d="{d}" fill="{e["color"]}"/>'


def svg_star(e):
    cx, cy, s = e["cx"], e["cy"], e["size"]
    pts = []
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        r = s if i % 2 == 0 else s * 0.42
        pts.append(f"{cx + r*math.cos(ang):.2f},{cy + r*math.sin(ang):.2f}")
    return f'<polygon points="{" ".join(pts)}" fill="{e["color"]}"/>'


def svg_drop(e):
    cx, cy, w, h = e["cx"], e["cy"], e["w"], e["h"]
    d = (f"M {cx} {cy - h/2} C {cx + w/2} {cy - h*0.05}, {cx + w/2} {cy + h*0.42}, "
         f"{cx} {cy + h/2} C {cx - w/2} {cy + h*0.42}, {cx - w/2} {cy - h*0.05}, "
         f"{cx} {cy - h/2} Z")
    return f'<path d="{d}" fill="{e["color"]}"/>'


def svg_zzz(e):
    cx, cy, s, color = e["cx"], e["cy"], e["scale"], e["color"]
    out = []
    for i, mult in enumerate((0.6, 0.85, 1.15)):
        size = 6 * s * mult
        x, y = cx - i * 7 * s, cy + i * 8 * s
        half = size / 2
        out.append(f'<path d="M {x-half} {y-half} L {x+half} {y-half} L {x-half} {y+half} '
                   f'L {x+half} {y+half}" stroke="{color}" stroke-width="2.4" fill="none" '
                   f'stroke-linecap="round" stroke-linejoin="round"/>')
    return "".join(out)


def svg_blush(e):
    return (f'<ellipse cx="{e["cx"]}" cy="{e["cy"]}" rx="{e["rx"]}" ry="{e["ry"]}" '
            f'fill="{e["color"]}" fill-opacity="{e["opacity"]}"/>')


def svg_grin(e):
    cx, cy, w, h = e["cx"], e["cy"], e["w"], e["h"]
    d = (f'M {cx - w/2:.2f} {cy:.2f} L {cx + w/2:.2f} {cy:.2f} '
         f'A {w/2:.2f} {h:.2f} 0 0 1 {cx - w/2:.2f} {cy:.2f} Z')
    out = [f'<path d="{d}" fill="{e["color"]}"/>']
    iw, ih, iy = w * 0.84, h * 0.8, cy + h * 0.1
    di = (f'M {cx - iw/2:.2f} {iy:.2f} L {cx + iw/2:.2f} {iy:.2f} '
          f'A {iw/2:.2f} {ih:.2f} 0 0 1 {cx - iw/2:.2f} {iy:.2f} Z')
    out.append(f'<path d="{di}" fill="{e["inner"]}"/>')
    if e.get("tongue"):
        out.append(f'<ellipse cx="{cx}" cy="{cy + h*0.62:.2f}" rx="{w*0.22:.2f}" '
                   f'ry="{h*0.28:.2f}" fill="{e["tongue_color"]}"/>')
    return "".join(out)


def svg_caret(e):
    cx, cy, w, h = e["cx"], e["cy"], e["w"], e["h"]
    tip = cy + h / 2 if e.get("down") else cy - h / 2
    base = cy - h / 2 if e.get("down") else cy + h / 2
    pts = f"{cx - w/2:.2f},{base:.2f} {cx:.2f},{tip:.2f} {cx + w/2:.2f},{base:.2f}"
    return (f'<polyline points="{pts}" fill="none" stroke="{e["color"]}" '
            f'stroke-width="{e["stroke"]}" stroke-linecap="round" stroke-linejoin="round"/>')


def svg_x(e):
    cx, cy, s = e["cx"], e["cy"], e["size"] / 2
    return (f'<path d="M {cx-s:.2f} {cy-s:.2f} L {cx+s:.2f} {cy+s:.2f} '
            f'M {cx+s:.2f} {cy-s:.2f} L {cx-s:.2f} {cy+s:.2f}" stroke="{e["color"]}" '
            f'stroke-width="{e["stroke"]}" stroke-linecap="round"/>')


SVG_RENDER = {"pill": svg_pill, "circle": svg_circle, "arc": svg_arc, "flat": svg_flat,
              "o": svg_o, "zigzag": svg_zigzag, "heart": svg_heart, "star": svg_star,
              "drop": svg_drop, "zzz": svg_zzz, "blush": svg_blush, "grin": svg_grin,
              "caret": svg_caret, "x": svg_x, "eye": svg_eye, "oval": svg_oval,
              "hatch": svg_hatch, "anger": svg_anger, "cat": svg_cat, "tri": svg_tri}


def _pts_attr(pts):
    return " ".join(f"{x},{y}" for x, y in pts)


def _path_d(pts):
    d = f"M {pts[0][0]} {pts[0][1]} " + " ".join(f"L {x} {y}" for x, y in pts[1:])
    return d + " Z"


def svg_frame():
    """The bezel as a single even-odd path between the silhouette's two edges."""
    outer = scaled(SHAPE, FRAME_INSET)
    inner = scaled(SHAPE, FRAME_INSET + FRAME_WIDTH)
    return (
        f'<defs><linearGradient id="bezel" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{FRAME_FROM}"/>'
        f'<stop offset="1" stop-color="{FRAME_TO}"/></linearGradient></defs>'
        f'<path d="{_path_d(outer)} {_path_d(inner)}" fill="url(#bezel)" '
        f'fill-rule="evenodd"/>'
    )


def render_svg(elems):
    outer = scaled(SHAPE, FRAME_INSET)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'width="{W}" height="{H}">',
             # Everything the face draws is clipped to the silhouette, so a
             # blush or a tear near the edge cannot spill outside the card.
             f'<clipPath id="card"><polygon points="{_pts_attr(outer)}"/></clipPath>',
             f'<g clip-path="url(#card)">',
             f'<polygon points="{_pts_attr(outer)}" fill="{PANEL}"/>']
    for e in elems:
        parts.append(SVG_RENDER[e["t"]](e))
    parts.append("</g>")
    parts.append(svg_frame())
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Generate the Whisplay face set.")
    ap.add_argument("--svg-dir", default=SVG_DIR)
    ap.add_argument("--json", default=JSON_PATH)
    ap.add_argument("--preview", help="also write a labelled contact sheet PNG")
    args = ap.parse_args()

    os.makedirs(args.svg_dir, exist_ok=True)
    spec = {
        "meta": {
            "canvas": W,
            "panel": {"margin": PANEL_MARGIN, "rx": PANEL_RX, "fill": PANEL},
            "frame": {"width": FRAME_WIDTH, "inset": FRAME_INSET, "rx": FRAME_RX,
                      "color": FRAME, "inner_color": FRAME_INNER, "ears": EARS,
                      "gradient": {"from": FRAME_FROM, "to": FRAME_TO}},
            "ink": INK,
            "shape": {"name": SHAPE_NAME, "points": SHAPE},
        },
        "faces": {},
    }

    for name, data in FACES.items():
        elems = catify(data["face"].elems)
        with open(os.path.join(args.svg_dir, data["cp"] + ".svg"), "w", encoding="utf-8") as fh:
            fh.write(render_svg(elems))
        spec["faces"][data["char"]] = {
            "name": name,
            "codepoint": data["cp"],
            "mouth_anchor": mouth_anchor(elems),
            "elems": elems,
        }

    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=1)

    print(f"wrote {len(FACES)} SVGs to {args.svg_dir}")
    print(f"wrote {args.json}")

    if args.preview:
        write_preview(spec, args.preview)


def write_preview(spec, path):
    from PIL import Image, ImageDraw, ImageFont
    import face_engine

    renderer = face_engine.FaceRenderer(spec)
    cols, cell, pad, label_h = 8, 104, 14, 20
    items = list(spec["faces"].items())
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (cell + pad) + pad,
                              rows * (cell + label_h + pad) + pad), (38, 38, 44))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except OSError:
        font = ImageFont.load_default()
    for i, (char, face) in enumerate(items):
        img = renderer.draw(char, cell)
        x = pad + (i % cols) * (cell + pad)
        y = pad + (i // cols) * (cell + label_h + pad)
        sheet.paste(img, (x, y), img)
        draw.text((x, y + cell + 3), face["name"], fill=(235, 235, 235), font=font)
    sheet.save(path)
    print(f"wrote preview {path}")


if __name__ == "__main__":
    main()
