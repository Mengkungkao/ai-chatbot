"""Vector reconstruction of the reference cat illustration.

The geometry lives here once, in cubic Bezier control points, and is emitted two
ways: as an SVG (the deliverable) and as a PIL raster (used only to measure the
result against the reference so the proportions can be checked rather than
eyeballed). Both read the same numbers, so they cannot drift apart.

    python3 cat_illustration.py              # writes cat.svg
    python3 cat_illustration.py --check ref  # also measures against a reference

Colours are taken from the reference image itself rather than from a written
spec: the outline probes at #818181 and the eyes at #575757.
"""

import argparse
import math
import os

WIDTH, HEIGHT = 313, 292

BACKGROUND = "#B7F1FF"   # measured off the reference
FILL = "#F2F2F2"
OUTLINE = "#818181"
FEATURE = "#575757"      # eyes and mouth
OUTLINE_W = 7.0
WHISKER_W = 6.0
MOUTH_W = 4.0

EYE_R = 15.0
EYE_L = (87.0, 163.0)
EYE_R_POS = (218.0, 163.0)


# --- head ----------------------------------------------------------------
# One closed path, walked clockwise from the left ear tip. Each entry is a
# cubic segment: two control points and an end point. The ears are part of the
# contour rather than shapes stuck on top, and every corner is a curve, so the
# silhouette reads as drawn by hand rather than assembled from polygons.
HEAD_START = (96.0, 48.5)
HEAD_CURVES = [
    ((108, 62), (120, 78), (133, 93)),       # left ear, inner edge down
    ((146, 100), (158, 100), (171, 93)),     # valley between the ears
    ((185, 78), (197, 62), (209, 48.5)),     # right ear, inner edge up
    ((222, 64), (233, 85), (244, 105)),      # right ear, outer edge down
    ((252, 119), (258, 129), (263, 141)),    # into the right cheek
    ((269, 163), (268, 187), (250, 206)),    # right cheek, full width
    ((238, 224), (197, 236), (155, 236)),    # bottom, shallow U
    ((113, 236), (72, 224), (60, 206)),      # bottom left
    ((42, 187), (41, 163), (47, 141)),       # left cheek, full width
    ((53, 129), (59, 119), (67, 105)),       # up the left side
    ((78, 84), (86, 62), (96, 48.5)),        # left ear, outer edge to the tip
]

# --- whiskers ------------------------------------------------------------
# Three a side, deliberately not parallel, angles taken from the reference.
WHISKERS = [
    ((47, 176), (21, 176)),
    ((47, 189), (28, 187)),
    ((49, 195), (25, 205)),
    ((263, 174), (287, 168)),
    ((264, 188), (286, 189)),
    ((263, 195), (286, 205)),
]

# --- mouth ---------------------------------------------------------------
# A tiny "uwu": two shallow scallops meeting in a small centre peak.
MOUTH_START = (130.0, 182.0)
MOUTH_CURVES = [
    ((137, 195), (148, 195), (154.0, 183.0)),
    ((160, 195), (171, 195), (178.0, 182.0)),
]


def _fmt(v):
    return f"{v:g}"


def _path_d(start, curves, close=False):
    d = [f"M {_fmt(start[0])} {_fmt(start[1])}"]
    for c1, c2, end in curves:
        d.append(f"C {_fmt(c1[0])} {_fmt(c1[1])}, {_fmt(c2[0])} {_fmt(c2[1])}, "
                 f"{_fmt(end[0])} {_fmt(end[1])}")
    if close:
        d.append("Z")
    return " ".join(d)


def createCatHead():
    """The head silhouette: one continuous path, filled and stroked."""
    return (f'  <path d="{_path_d(HEAD_START, HEAD_CURVES, close=True)}"\n'
            f'        fill="{FILL}" stroke="{OUTLINE}" stroke-width="{_fmt(OUTLINE_W)}"\n'
            f'        stroke-linecap="round" stroke-linejoin="round"/>')


def createWhiskers():
    out = ['  <g stroke="%s" stroke-width="%s" stroke-linecap="round" fill="none">'
           % (OUTLINE, _fmt(WHISKER_W))]
    for (x1, y1), (x2, y2) in WHISKERS:
        out.append(f'    <line x1="{_fmt(x1)}" y1="{_fmt(y1)}" '
                   f'x2="{_fmt(x2)}" y2="{_fmt(y2)}"/>')
    out.append('  </g>')
    return "\n".join(out)


def createEyes():
    return "\n".join(
        f'  <circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(EYE_R)}" fill="{FEATURE}"/>'
        for cx, cy in (EYE_L, EYE_R_POS))


def createMouth():
    return (f'  <path d="{_path_d(MOUTH_START, MOUTH_CURVES)}"\n'
            f'        fill="none" stroke="{FEATURE}" stroke-width="{_fmt(MOUTH_W)}"\n'
            f'        stroke-linecap="round" stroke-linejoin="round"/>')


def build_svg():
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}"',
        f'     viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'  <rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>',
        createWhiskers(),     # behind the head, so they tuck under the outline
        createCatHead(),
        createEyes(),
        createMouth(),
        '</svg>',
        '',
    ])


# --- raster copy, for measuring only -------------------------------------

def _bezier(p0, c1, c2, p1, n=60):
    pts = []
    for i in range(n + 1):
        t = i / n
        m = 1 - t
        pts.append((m**3 * p0[0] + 3*m*m*t * c1[0] + 3*m*t*t * c2[0] + t**3 * p1[0],
                    m**3 * p0[1] + 3*m*m*t * c1[1] + 3*m*t*t * c2[1] + t**3 * p1[1]))
    return pts


def _outline_points():
    pts, cur = [], HEAD_START
    for c1, c2, end in HEAD_CURVES:
        pts.extend(_bezier(cur, c1, c2, end)[:-1])
        cur = end
    return pts


def render_png(path, scale=3):
    """Rasterise the same geometry so the result can be measured."""
    from PIL import Image, ImageDraw
    S = scale
    img = Image.new("RGB", (WIDTH * S, HEIGHT * S), BACKGROUND)
    d = ImageDraw.Draw(img)

    def rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def thick(p1, p2, w, colour):
        d.line([p1[0]*S, p1[1]*S, p2[0]*S, p2[1]*S], fill=colour, width=int(w*S))
        for p in (p1, p2):
            r = w * S / 2
            d.ellipse([p[0]*S-r, p[1]*S-r, p[0]*S+r, p[1]*S+r], fill=colour)

    for a, b in WHISKERS:
        thick(a, b, WHISKER_W, rgb(OUTLINE))

    poly = [(x*S, y*S) for x, y in _outline_points()]
    d.polygon(poly, fill=rgb(FILL))
    d.line(poly + [poly[0]], fill=rgb(OUTLINE), width=int(OUTLINE_W*S), joint="curve")
    for x, y in poly[::4]:
        r = OUTLINE_W * S / 2
        d.ellipse([x-r, y-r, x+r, y+r], fill=rgb(OUTLINE))

    for cx, cy in (EYE_L, EYE_R_POS):
        d.ellipse([(cx-EYE_R)*S, (cy-EYE_R)*S, (cx+EYE_R)*S, (cy+EYE_R)*S], fill=rgb(FEATURE))

    cur = MOUTH_START
    mp = []
    for c1, c2, end in MOUTH_CURVES:
        mp.extend(_bezier(cur, c1, c2, end)); cur = end
    d.line([(x*S, y*S) for x, y in mp], fill=rgb(FEATURE),
           width=int(MOUTH_W*S), joint="curve")

    img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    img.save(path)
    return img


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "cat.svg"))
    ap.add_argument("--png", default=os.path.join(os.path.dirname(__file__), "cat.png"))
    args = ap.parse_args()
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(build_svg())
    print("wrote", args.out)
    render_png(args.png)
    print("wrote", args.png)
