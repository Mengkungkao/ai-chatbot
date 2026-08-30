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
# The reference strokes its outline centred on the path, 7 units wide on its
# own canvas. The runtime instead fills the polygon and lays the ring inside
# it, so the polygon has to be the stroke's OUTER edge for the painted head to
# come out the same size and the fill boundary to land in the same place.
# FRAME_WIDTH is set from the mapped stroke once the fit is known.
STROKE_REF = 7.0
FRAME_WIDTH = 3.0   # replaced below with STROKE_REF at face scale
FRAME_INSET = 0.0
FRAME_RX = PANEL_RX + (PANEL_MARGIN - (FRAME_INSET + FRAME_WIDTH / 2))

# No ornaments on the bezel: at this size a delicate outline flatters the face,
# where anything perched on the corners just crowds it.
EARS = []

# The face card is a barrel-curved CRT outline rather than a rounded square:
# a superellipse, wider than it is tall. Both the panel and the bezel ring take
# this silhouette, and the face art is clipped to it, so the three always agree.
# --- silhouette ----------------------------------------------------------
# The head is the reference cat, authored as cubic Beziers on the 313x292
# canvas it was measured on and mapped onto this 100x100 one. Keeping the
# source numbers means this face and the standalone drawing in
# cat-illustration/ stay the same cat rather than two that merely resemble
# each other.
#
# Only the left ear is authored. The right is its mirror across REF_AXIS, so
# the pair cannot drift apart the way two independently measured ears did.
SHAPE_NAME = "cat-reference"

REF_AXIS = 155.0
REF_EAR_OUTER_BASE = (67.0, 105.0)
REF_EAR_OUTER_C1 = (78.0, 84.0)
REF_EAR_OUTER_C2 = (86.0, 62.0)
REF_EAR_TIP = (96.0, 48.5)
REF_EAR_INNER_C1 = (108.0, 62.0)
REF_EAR_INNER_C2 = (120.0, 78.0)
REF_EAR_INNER_BASE = (133.0, 93.0)
REF_VALLEY_C = (146.0, 100.0)

EAR_FILLET = 8.0    # rounds the tips; 0 leaves them sharp
EAR_LIFT = 2.5      # raises the tips to pay for what the fillet cuts away,
                    # so rounding them does not shorten the head
EAR_BOW = 5.0       # bows both edges of each ear outward from its own
                    # centreline, so they swell rather than run straight

TWITCH_DEG = 13.0   # how far one ear swings on a flick
PERK_DEG = 6.0      # both ears, pricked up
SHAPE_STEPS = 26    # samples per Bezier segment

FACE_MARGIN = 0.5   # left at each side once the head fills the width
FACE_CY = 50.0      # where the silhouette is centred vertically
FACE_STRETCH = 1.0  # 1.0 keeps the reference's proportions; raise it to trade
                    # them for height in the square tile


def _dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _rotate(pts, cx, cy, deg):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for x, y in pts:
        dx, dy = x - cx, y - cy
        out.append((cx + dx * ca - dy * sa, cy + dx * sa + dy * ca))
    return out


def _polygon_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def _outset_polygon(pts, dist):
    """Move every vertex outward along its own normal by ``dist``.

    The mirror of the runtime's inset: scaling about the centre would displace
    the ears rather than thicken their outline. Used to turn the reference's
    centred stroke into the outer boundary the runtime fills to.
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
            n1, n2 = edge_normal(p0, p1), edge_normal(p1, p2)
            nx, ny = n1[0] + n2[0], n1[1] + n2[1]
            L = math.hypot(nx, ny)
            if L < 1e-9:
                nx, ny, L = n1[0], n1[1], 1.0
            nx, ny = nx / L, ny / L
            cosang = max(-0.999, min(1.0, n1[0] * n2[0] + n1[1] * n2[1]))
            miter = math.sqrt(max(0.15, (1.0 + cosang) / 2.0))
            step = sign * dist / miter
            out.append([p1[0] + nx * step, p1[1] + ny * step])
        return out

    a, b = build(1.0), build(-1.0)
    # outward is whichever encloses more area
    return a if abs(_polygon_area(a)) > abs(_polygon_area(b)) else b


def _m(p):
    """Mirror a point across the head's axis."""
    return (2 * REF_AXIS - p[0], p[1])


def _ref_curves():
    """The head in reference units: a start point and 11 cubic segments.

    Each segment carries the ear it belongs to -- 0 left, 1 right, None for
    the head itself -- so a flick can rotate one ear and leave the rest alone.
    """
    curves = [
        ((REF_EAR_INNER_C1, REF_EAR_INNER_C2, REF_EAR_INNER_BASE), 0),
        ((REF_VALLEY_C, _m(REF_VALLEY_C), _m(REF_EAR_INNER_BASE)), None),
        ((_m(REF_EAR_INNER_C2), _m(REF_EAR_INNER_C1), _m(REF_EAR_TIP)), 1),
        ((_m(REF_EAR_OUTER_C2), _m(REF_EAR_OUTER_C1), _m(REF_EAR_OUTER_BASE)), 1),
        (((252, 119), (258, 129), (263, 141)), None),   # into the right cheek
        (((269, 163), (268, 187), (250, 206)), None),   # right cheek
        (((238, 224), (197, 236), (155, 236)), None),   # bottom, shallow U
        (((113, 236), (72, 224), (60, 206)), None),     # bottom left
        (((42, 187), (41, 163), (47, 141)), None),      # left cheek
        (((53, 129), (59, 119), REF_EAR_OUTER_BASE), None),
        ((REF_EAR_OUTER_C1, REF_EAR_OUTER_C2, REF_EAR_TIP), 0),
    ]
    start = list(REF_EAR_TIP)
    pts = [[list(c1), list(c2), list(end)] for (c1, c2, end), _ in curves]
    tags = [t for _, t in curves]

    if EAR_LIFT:
        start[1] -= EAR_LIFT
        pts[10][2][1] -= EAR_LIFT           # left tip, the same point as start
        pts[2][2][1] -= EAR_LIFT            # right tip
        for seg, idx in ((10, 1), (0, 0), (2, 1), (3, 0)):
            pts[seg][idx][1] -= EAR_LIFT * 0.5
    if EAR_BOW:
        # Offset each ear edge's controls perpendicular to that edge, away from
        # the ear's own centreline. Perpendicular matters: the inner edges are
        # steeply diagonal, and a sideways push slides along them instead of
        # bowing them.
        ends = {10: (pts[9][2], pts[10][2]), 0: (start, pts[0][2]),
                2: (pts[1][2], pts[2][2]), 3: (pts[2][2], pts[3][2])}
        for seg, outward in ((10, -1), (0, +1), (2, -1), (3, +1)):
            (x0, y0), (x1, y1) = ends[seg]
            dx, dy = x1 - x0, y1 - y0
            m = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / m, dx / m
            if (nx > 0) != (outward > 0):
                nx, ny = -nx, -ny
            for idx in (0, 1):
                pts[seg][idx][0] += EAR_BOW * nx
                pts[seg][idx][1] += EAR_BOW * ny
    return tuple(start), [tuple(tuple(p) for p in c) for c in pts], tags


def _cubic(p0, c1, c2, p1, t):
    m = 1 - t
    return (m ** 3 * p0[0] + 3 * m * m * t * c1[0] + 3 * m * t * t * c2[0] + t ** 3 * p1[0],
            m ** 3 * p0[1] + 3 * m * m * t * c1[1] + 3 * m * t * t * c2[1] + t ** 3 * p1[1])


def _split(seg, t):
    """de Casteljau: cut one cubic into two at parameter t."""
    p0, c1, c2, p1 = seg
    def lerp(a, b):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    a, b, c = lerp(p0, c1), lerp(c1, c2), lerp(c2, p1)
    d, e = lerp(a, b), lerp(b, c)
    f = lerp(d, e)
    return (p0, a, d, f), (f, e, c, p1)


def _t_at_dist(seg, dist, from_end, n=160):
    """Parameter t sitting ``dist`` of arc length from one end of ``seg``."""
    pts = [_cubic(*seg, i / n) for i in range(n + 1)]
    acc, total = [0.0], 0.0
    for i in range(1, len(pts)):
        total += _dist(pts[i - 1], pts[i])
        acc.append(total)
    if total <= dist * 1.2:            # too short to give up that much
        dist = total * 0.45
    target = total - dist if from_end else dist
    for i in range(1, len(acc)):
        if acc[i] >= target:
            span = acc[i] - acc[i - 1] or 1.0
            return (i - 1 + (target - acc[i - 1]) / span) / n
    return 1.0


def _arc_blend(a, b):
    """A cubic joining two trimmed ends, curving like a circular arc."""
    q1, q2 = a[3], b[0]
    def unit(v):
        m = math.hypot(*v) or 1.0
        return (v[0] / m, v[1] / m)
    da = unit((q1[0] - a[2][0], q1[1] - a[2][1]))
    db = unit((b[1][0] - q2[0], b[1][1] - q2[1]))
    den = da[0] * db[1] - da[1] * db[0]
    if abs(den) < 1e-9:
        k, apex = 1 / 3, ((q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2)
    else:
        s = ((q2[0] - q1[0]) * db[1] - (q2[1] - q1[1]) * db[0]) / den
        apex = (q1[0] + da[0] * s, q1[1] + da[1] * s)
        turn = abs(math.atan2(den, da[0] * db[0] + da[1] * db[1]))
        k = (4 / 3) * math.tan(turn / 4) / math.tan(turn / 2) if turn > 1e-6 else 2 / 3
    return (q1,
            (q1[0] + (apex[0] - q1[0]) * k, q1[1] + (apex[1] - q1[1]) * k),
            (q2[0] + (apex[0] - q2[0]) * k, q2[1] + (apex[1] - q2[1]) * k),
            q2)


def _fillet_at(segs, tags, i, r):
    """Round the corner where segs[i] meets segs[i + 1]."""
    a, b = segs[i], segs[i + 1]
    a2 = _split(a, _t_at_dist(a, r, from_end=True))[0]
    b2 = _split(b, _t_at_dist(b, r, from_end=False))[1]
    return (segs[:i] + [a2, _arc_blend(a2, b2), b2] + segs[i + 2:],
            tags[:i] + [tags[i], tags[i], tags[i + 1]] + tags[i + 2:])


def _head_segments():
    """The head as cubic segments with both ear tips rounded, ears tagged."""
    start, curves, tags = _ref_curves()
    segs, cur = [], start
    for c1, c2, end in curves:
        segs.append((cur, c1, c2, end))
        cur = end
    if EAR_FILLET > 0:
        # The left tip sits on the seam where the closed path joins itself, so
        # rotate by one segment and both tips become ordinary corners.
        segs, tags = segs[1:] + segs[:1], tags[1:] + tags[:1]
        segs, tags = _fillet_at(segs, tags, 9, EAR_FILLET)   # left tip
        segs, tags = _fillet_at(segs, tags, 1, EAR_FILLET)   # right tip
    return segs, tags


# Both ears pivot about the midpoint of their own base, so a flick swings the
# ear while its junctions with the head stay put.
REF_EAR_PIVOT = ((REF_EAR_OUTER_BASE[0] + REF_EAR_INNER_BASE[0]) / 2.0,
                 (REF_EAR_OUTER_BASE[1] + REF_EAR_INNER_BASE[1]) / 2.0)

_FIT = None


def _fit():
    """Scale and offset taking the reference canvas onto this one.

    Measured once from the untwitched head: if each variant fitted its own
    bounding box, an ear flick would silently resize the whole face.
    """
    global _FIT
    if _FIT is None:
        segs, _ = _head_segments()
        pts = _outset_polygon([_cubic(*s, k / SHAPE_STEPS)
                               for s in segs for k in range(SHAPE_STEPS)],
                              STROKE_REF / 2.0)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        s = (100.0 - 2 * FACE_MARGIN) / (max(xs) - min(xs))
        _FIT = (s, (min(ys) + max(ys)) / 2.0)
    return _FIT


def _to_face(p):
    """A point in reference units, placed on the 100x100 face canvas."""
    s, mid_y = _fit()
    return (50.0 + (p[0] - REF_AXIS) * s,
            FACE_CY + (p[1] - mid_y) * s * FACE_STRETCH)


def shape_points(twitch=(0.0, 0.0)):
    """The head outline as a closed polygon on the 100x100 canvas."""
    segs, tags = _head_segments()
    pts = []
    for seg, tag in zip(segs, tags):
        for k in range(SHAPE_STEPS):
            pts.append((_cubic(*seg, k / SHAPE_STEPS), tag))

    for ear in (0, 1):
        ang = twitch[ear]
        if not ang:
            continue
        pivot = REF_EAR_PIVOT if ear == 0 else _m(REF_EAR_PIVOT)
        idx = [i for i, (_, t) in enumerate(pts) if t == ear]
        moved = _rotate([pts[i][0] for i in idx], pivot[0], pivot[1], ang)
        for i, q in zip(idx, moved):
            pts[i] = (q, ear)

    # The polygon the runtime fills is the stroke's outer edge, so the painted
    # head matches the reference's rather than coming out a stroke smaller.
    ref = _outset_polygon([p for p, _ in pts], STROKE_REF / 2.0)
    out = [[round(v, 3) for v in _to_face(p)] for p in ref]
    # Points closer than this are invisible at any size the display uses, and
    # they make corner measurements meaningless by turning one bend into several.
    dedup = [out[0]]
    for q in out[1:]:
        if _dist(q, dedup[-1]) >= 0.35:
            dedup.append(q)
    if _dist(dedup[0], dedup[-1]) < 0.35:
        dedup.pop()
    return dedup


# The right ear in face coordinates, for the inner-ear triangles and anything
# else that needs to know where the ears sit.
EAR_TIP = _to_face(_m(REF_EAR_TIP))
EAR_SPAN = (_to_face(_m(REF_EAR_INNER_BASE))[0], _to_face(_m(REF_EAR_OUTER_BASE))[0])
HEAD_HALF_W = 50.0 - FACE_MARGIN

SHAPE = shape_points()
FRAME_WIDTH = round(STROKE_REF * _fit()[0], 3)
FRAME_RX = PANEL_RX + (PANEL_MARGIN - (FRAME_INSET + FRAME_WIDTH / 2))


def scaled(pts, inset):
    """The silhouette shrunk toward the centre, used for the ring's two edges."""
    f = (50.0 - inset) / 50.0
    return [[round(50 + (x - 50) * f, 3), round(50 + (y - 50) * f, 3)] for x, y in pts]


PANEL = "#F2F2F2"      # flat off-white head fill, no gradient
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
FRAME = "#777777"        # head outline, medium grey
FRAME_FROM = "#777777"   # flat: the spec calls for one outline colour
FRAME_TO = "#777777"
FRAME_INNER = "#FFE3EA"

# Shared geometry so every face sits on the same grid.
EYE_X, EYE_Y = 26, 45   # further from centre; lashes and brows follow
EYE_RX, EYE_RY = 13, 13
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
# Proper sunglasses rather than one visor bar: two lenses on the eye centres,
# a bridge between them and a stubby arm on each side. Lenses are role="eye" so
# they squash on a blink like everything else; the frame parts stay put.
# A pill's w and h pass through the refit unscaled -- only rx/ry/r do -- so
# these are authored at the size they should finish at. Left as card-sized,
# the lenses stayed 2.5x too big when the eyes shrank, covering most of the
# face and reaching down into the whiskers.
f.pill(EYE_X, 45, 22, 14, 0, color=INK, role="eye")
f.pill(100 - EYE_X, 45, 22, 14, 0, color=INK, role="eye")
f.pill(50, 43, 34, 3.4, 0, color=INK, role="deco")           # bridge
f.pill(7, 41, 10, 3.0, -14, color=INK, role="deco")          # left arm
f.pill(93, 41, 10, 3.0, 14, color=INK, role="deco")          # right arm
f.pill(EYE_X - 6, 40, 8, 2.6, -20, color="#B9C0C8", role="deco")   # lens shine
f.pill(94 - EYE_X, 40, 8, 2.6, -20, color="#B9C0C8", role="deco")
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
# The written spec asks for a minimal kawaii cat: flat fill, one grey outline,
# solid eyes with no highlight, and nothing else. These strip the decoration the
# earlier kawaii set carried. Set False to get the blush and glossy eyes back.
MINIMAL_STYLE = True
EYE_COLOUR = "#555555"
MOUTH_COLOUR = "#666666"
NOSE = "#777777"
WHISKER = "#777777"
# Whiskers used to hang off each face's mouth, so an expression that lifts the
# mouth lifted them into the eyes -- 30 of the 49 faces had one cutting across
# an eye. They now sit at a fixed height, and their width, length and reach all
# come from the reference drawing.
WHISK_REF_W = 6.0      # whisker stroke, against the reference's 7-unit outline
WHISK_REF_LEN = 26.0   # whisker length, in reference units
WHISK_REF_Y = 194.5    # centre of the reference's lower whisker pair
# Drawn at the same ratio to the frame as the reference's, so they read as part
# of the same line work rather than as stray hairs beside it.
WHISK_W = round(WHISK_REF_W * _fit()[0], 3)
WHISK_LEN = round(WHISK_REF_LEN * _fit()[0], 3)
WHISK_ORIGIN_DX = 36.0
WHISK_GAP = 5.0   # vertical gap at the inner ends, so the pair is
                  # two separate strokes rather than a < chevron
WHISK_ANGLES = (-6.0, 18.0)    # two per cheek, splayed as the reference's are
# The reference's band centres on y=194.5, which maps to 72.45 here. But the
# reference has one small fixed eye and these faces do not: pleading's reach
# down to EYE_FLOOR, and a whisker at 69.95 cut across them. Taking whichever
# is lower puts the pair clear of every expression's eyes, whatever its gain,
# while keeping the reference's height wherever that already clears them.
EYE_FLOOR = 70.26      # lowest point any eye reaches, measured across all 49
WHISK_Y = round(max(_to_face((155.0, WHISK_REF_Y))[1],
                    EYE_FLOOR + 1.0 + WHISK_W / 2.0 + WHISK_GAP / 2.0), 3)
INNER_EAR = "#FF9DB4"
CLOSED_MOUTHS = {"flat", "arc", "zigzag"}

# The card layout spans roughly y=20 (lashes) to y=84 (huffing's steam). The cat
# head is shorter, so the face is compressed about its own centre and recentred;
# translating alone pushed the low decorations out through the chin.
#
# These four are solved rather than guessed: they are whatever places the eyes
# and mouth exactly where the reference cat puts its own, once the head has
# been mapped onto this canvas. Change the head and they need re-solving.
# FIT_SPREAD multiplies an element's offset from the centre line, so it is
# solved against EYE_X's distance from 50, not against EYE_X itself.
SRC_CENTRE, FIT_CENTRE, FIT_YSCALE = 52.0, 61.50, 0.375
FIT_SPREAD, FIT_EYE_GAIN = 1.177, 0.498

# Eyes are not one size. A person's eyes widen when startled and narrow when
# cross, and the face reads flat if they never change, so each expression scales
# the base gain. Anything not listed uses the base.
EYE_GAIN_BY_FACE = {
    # thrown wide
    "astonished": 1.34, "scared": 1.32, "pleading": 1.30, "surprised": 1.24,
    "fearful": 1.22, "flushed": 1.16, "anxious": 1.10,
    # soft and open
    "love": 1.16, "adoring": 1.14, "excited": 1.12, "kiss": 1.08, "wink": 1.06,
    # narrowed
    "smirk": 0.80, "huffing": 0.80, "dejected": 0.82, "drowsy": 0.84,
    "angry": 0.88, "rage": 0.88, "cool": 0.90, "expressionless": 0.92,
    "sick": 0.88, "nauseated": 0.90, "content": 0.94, "sleepy": 0.94,
}
FIT_MAX_DX = HEAD_HALF_W * 0.76


def _muzzle(elems):
    """Swap a closed line mouth for an omega muzzle; leave open mouths alone."""
    out, swapped = [], False
    for e in elems:
        if not swapped and e.get("role") == "mouth" and e["t"] in CLOSED_MOUTHS:
            swapped = True
            out.append({"t": "cat", "cx": e.get("cx", 50), "cy": e.get("cy", 70) - 1,
                        "w": max(e.get("w", 16) * 0.85, 12.5), "h": 4.8,
                        "stroke": 3.8, "color": INK, "role": "mouth"})
            continue
        out.append(e)
    return out


def _nose_and_whiskers(elems):
    mouth_y = next((e.get("cy", 70) for e in elems if e.get("role") == "mouth"), 70.0)
    out = [{"t": "tri", "cx": 50.0, "cy": round(mouth_y - 7.5, 3), "w": 7.0, "h": 5.0,
            "color": NOSE, "down": True, "role": "deco"}]
    # Three short whiskers fanning from one point on each cheek, angled up,
    # level and down. Three parallel horizontal lines read as a stave, not a cat.
    for side in (-1, 1):
        ox = 50.0 + side * WHISK_ORIGIN_DX
        oy = WHISK_Y
        for ang in WHISK_ANGLES:
            a = math.radians(ang)
            dx = math.cos(a) * WHISK_LEN * side
            dy = math.sin(a) * WHISK_LEN
            # Each whisker starts from its own point, offset above or below the
            # cheek line. Sharing one origin made the pair meet in a point and
            # read as a < rather than as two whiskers.
            oy_i = oy + (WHISK_GAP / 2.0) * (1 if ang > 0 else -1)
            out.append({"t": "pill", "cx": round(ox + dx / 2, 3),
                        "cy": round(oy_i + dy / 2, 3), "w": WHISK_LEN, "h": WHISK_W,
                        "rot": round(ang * side, 3), "color": WHISKER,
                        # "overlay" survives the silhouette clip and is painted
                        # over the outline, so whiskers cross the head edge the
                        # way a cat's do instead of stopping at the cheek.
                        "role": "overlay"})
    return elems + out


def _refit(elems, eye_gain):
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
                    e[f] = round(e[f] * eye_gain, 3)
            if e["t"] in ("arc", "flat", "caret", "x") and "w" in e:
                e["w"] = round(e["w"] * eye_gain, 3)
        out.append(e)
    return out


def _inner_ears():
    """A smaller triangle inside each ear, set in from the ear's own outline."""
    inner = _to_face(_m(REF_EAR_INNER_BASE))
    outer = _to_face(_m(REF_EAR_OUTER_BASE))
    tip = _to_face(_m(REF_EAR_TIP))
    base_cx = (inner[0] + outer[0]) / 2.0
    base_y = (inner[1] + outer[1]) / 2.0
    h = (base_y - tip[1]) * 0.52
    out = []
    for side in (1, -1):
        cx = base_cx if side == 1 else 100.0 - base_cx
        tx = tip[0] if side == 1 else 100.0 - tip[0]
        out.append({"t": "tri", "cx": round((cx + tx) / 2, 3),
                    "cy": round(tip[1] + h * 0.62, 3),
                    "w": round(abs(outer[0] - inner[0]) * 0.42, 3), "h": round(h, 3),
                    "color": INNER_EAR, "down": False, "role": "deco"})
    return out


def _minimal(elems):
    """Flatten to the spec: solid dark-grey eyes, no highlights, no blush."""
    out = []
    for e in elems:
        if e.get("role") == "blush":
            continue                                   # no cheek colour
        e = dict(e)
        if e.get("role") == "eye":
            e["glint"] = False                         # no highlight
            if e.get("color") not in (None,):
                e["color"] = EYE_COLOUR
        elif e.get("role") == "mouth" and e.get("color"):
            e["color"] = MOUTH_COLOUR
        out.append(e)
    return out


def catify(elems, face_name=""):
    if not CAT_STYLE:
        return elems
    gain = FIT_EYE_GAIN * EYE_GAIN_BY_FACE.get(face_name, 1.0)
    # Nose and whiskers are added AFTER the refit, in final coordinates. Built
    # before it, the refit squashed their centres vertically while leaving their
    # rotation alone, which pinched the pair together until the two whiskers on
    # a cheek crossed over each other.
    built = _nose_and_whiskers(_refit(_muzzle(elems), gain))
    if not MINIMAL_STYLE:
        return built + _inner_ears()
    return _minimal(built)


# Talking mouth shapes, taken from the sixteen faces on the reference sheet.
# Widths are canvas units (the face spans about 100) and heights are scaled from
# the sheet's percentages against a face roughly 73 units tall. The runtime
# picks among these while she speaks instead of scaling one shape, so the mouth
# changes shape the way it does in real speech.
TALK_SHAPES = [
    {"w": 11.0, "h": 7.0,  "name": "small"},
    {"w": 6.5,  "h": 12.0, "name": "narrow"},
    {"w": 18.0, "h": 11.2, "name": "medium"},
    {"w": 24.0, "h": 13.9, "name": "wide"},
    {"w": 18.0, "h": 16.5, "name": "tall"},
]


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
            "shape": {"name": SHAPE_NAME, "points": SHAPE,
                      # The painted head does not fill the square canvas: it
                      # keeps the reference's proportions. Callers size their
                      # layout from this rather than assuming a square.
                      "bbox": [round(min(p[0] for p in SHAPE), 3),
                               round(min(p[1] for p in SHAPE), 3),
                               round(max(p[0] for p in SHAPE), 3),
                               round(max(p[1] for p in SHAPE), 3)]},
            "talk_shapes": TALK_SHAPES,
            # Alternate silhouettes the runtime swaps to for an ear flick.
            "shape_variants": {
                "flick_left": shape_points(twitch=(TWITCH_DEG, 0.0)),
                "flick_right": shape_points(twitch=(0.0, -TWITCH_DEG)),
                "perk": shape_points(twitch=(-PERK_DEG, PERK_DEG)),
            },
        },
        "faces": {},
    }

    for name, data in FACES.items():
        elems = catify(data["face"].elems, name)
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
    clashes = check_whisker_clearance(spec["faces"])
    if clashes:
        print(f"[warn] whisker crosses an eye on: {', '.join(clashes)}")
    else:
        print(f"whisker/eye clearance ok on all {len(spec['faces'])} faces")

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


def check_whisker_clearance(faces):
    """Whiskers must not cut across any eye, on any expression.

    They used to hang off the mouth, which drifts with the expression, and 30
    of the 49 faces ended up with one crossing an eye. The placement is fixed
    now, but eye sizes still vary per expression, so this keeps the guarantee
    honest rather than leaving it to the constants staying in step.
    """
    bad = []
    for face in faces.values():
        whiskers = [e for e in face["elems"]
                    if e.get("role") == "overlay" and e["t"] == "pill"]
        eyes = [e for e in face["elems"] if e.get("role") == "eye"]
        for w in whiskers:
            a = math.radians(w["rot"])
            hx, hy = math.cos(a) * w["w"] / 2, math.sin(a) * w["w"] / 2
            for e in eyes:
                rx = e["rx"] if e.get("rx") is not None else e.get("w", 0) / 2
                ry = e["ry"] if e.get("ry") is not None else e.get("h", 0) / 2
                for i in range(41):
                    t = i / 40.0
                    px = w["cx"] - hx + 2 * hx * t
                    py = w["cy"] - hy + 2 * hy * t
                    d = math.hypot(max(0.0, abs(px - e["cx"]) - rx),
                                   max(0.0, abs(py - e["cy"]) - ry))
                    if d - w["h"] / 2 < 0:
                        bad.append(face["name"])
                        break
    return sorted(set(bad))


if __name__ == "__main__":
    main()
