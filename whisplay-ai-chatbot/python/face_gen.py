"""Authoring tool for the Whisplay face set.

Defines every expression once as a list of primitive shapes on a 100x100 canvas,
then emits both consumers of that definition:

  * ``emoji_svg/<codepoint>.svg`` — static glyphs for the existing emoji lookup
    path (``EmojiUtils.emoji_to_filename``), so any face also works as plain text.
  * ``faces.json`` — the same primitives with role tags, read at runtime by
    ``face_engine.py`` to animate blinking, talking and emotion transitions.

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
# ``FRAME_INSET`` is the gap from the canvas edge to the outer edge of the ring;
# the radius is grown to keep the ring concentric with the panel corners.
FRAME_WIDTH = 3.0
FRAME_INSET = 1.5
FRAME_RX = PANEL_RX + (PANEL_MARGIN - (FRAME_INSET + FRAME_WIDTH / 2))

BLACK = "#0A0A0A"
WHITE = "#F5F5F0"
BLUE = "#4FB8FF"
PINK = "#FF4D77"
RED = "#FF3B30"
ORANGE = "#FF8C1A"
BLUSH = "#FF7A9C"
MOUTH_IN = "#B32B3E"
TONGUE = "#FF6B81"
FRAME = "#3A4657"  # neutral bezel; the runtime may tint it with the status colour


class Face:
    def __init__(self):
        self.elems = []

    def _add(self, **kw):
        self.elems.append(kw)

    def pill(self, cx, cy, w, h, rot=0, color=WHITE, role=None):
        self._add(t="pill", cx=cx, cy=cy, w=w, h=h, rot=rot, color=color, role=role)

    def circle(self, cx, cy, r, color=WHITE, pupil_r=None, pupil_color=BLACK, role=None):
        self._add(t="circle", cx=cx, cy=cy, r=r, color=color,
                  pupil_r=pupil_r, pupil_color=pupil_color, role=role)

    def arc(self, cx, cy, w, depth, rot=0, stroke=6, color=WHITE, role=None):
        self._add(t="arc", cx=cx, cy=cy, w=w, depth=depth, rot=rot,
                  stroke=stroke, color=color, role=role)

    def curve(self, cx, cy, w, depth, stroke=6, color=WHITE, role=None):
        self.arc(cx, cy, w, depth, rot=0, stroke=stroke, color=color, role=role)

    def flat(self, cx, cy, w, stroke=6, color=WHITE, role=None):
        self._add(t="flat", cx=cx, cy=cy, w=w, stroke=stroke, color=color, role=role)

    def o_mouth(self, cx, cy, r, stroke=5, color=WHITE, role="mouth"):
        self._add(t="o", cx=cx, cy=cy, r=r, stroke=stroke, color=color, role=role)

    def zigzag(self, cx, cy, w, h, n, stroke=5, color=WHITE, role=None):
        self._add(t="zigzag", cx=cx, cy=cy, w=w, h=h, n=n, stroke=stroke,
                  color=color, role=role)

    def heart(self, cx, cy, size, color=WHITE, role=None):
        self._add(t="heart", cx=cx, cy=cy, size=size, color=color, role=role)

    def star(self, cx, cy, size, color=WHITE, role=None):
        self._add(t="star", cx=cx, cy=cy, size=size, color=color, role=role)

    def drop(self, cx, cy, w, h, color=WHITE, role="deco"):
        self._add(t="drop", cx=cx, cy=cy, w=w, h=h, color=color, role=role)

    def zzz(self, cx, cy, scale=1.0, color=WHITE, role="deco"):
        self._add(t="zzz", cx=cx, cy=cy, scale=scale, color=color, role=role)

    def blush(self, cx, cy, rx, ry=None, color=BLUSH, opacity=0.9, role="blush"):
        self._add(t="blush", cx=cx, cy=cy, rx=rx, ry=ry if ry else rx * 0.72,
                  color=color, opacity=opacity, role=role)

    def grin(self, cx, cy, w, h, tongue=False, color=WHITE, inner=MOUTH_IN, role="mouth"):
        self._add(t="grin", cx=cx, cy=cy, w=w, h=h, tongue=tongue, color=color,
                  inner=inner, tongue_color=TONGUE, role=role)

    def caret(self, cx, cy, w, h, down=False, stroke=6, color=WHITE, role=None):
        self._add(t="caret", cx=cx, cy=cy, w=w, h=h, down=down, stroke=stroke,
                  color=color, role=role)

    def x_mark(self, cx, cy, size, stroke=5, color=WHITE, role=None):
        self._add(t="x", cx=cx, cy=cy, size=size, stroke=stroke, color=color, role=role)

    def glint(self, cx, cy, r, color=BLACK, role="eye"):
        self._add(t="circle", cx=cx, cy=cy, r=r, color=color,
                  pupil_r=None, pupil_color=BLACK, role=role)


def pair(f, method, cx, cy, *args, **kw):
    """Add a shape and its mirror across the vertical centre line."""
    getattr(f, method)(cx, cy, *args, **kw)
    mk = dict(kw)
    if mk.get("rot"):
        mk["rot"] = -mk["rot"]
    getattr(f, method)(100 - cx, cy, *args, **mk)


FACES = {}


def emo(name, codepoint, char):
    f = Face()
    FACES[name] = {"cp": codepoint, "char": char, "face": f}
    return f


def blush_pair(f, cy=62, cx=18, r=7.5, opacity=0.9):
    f.blush(cx, cy, r, opacity=opacity)
    f.blush(100 - cx, cy, r, opacity=opacity)


# --- expressions ---------------------------------------------------------
# Eyes are tagged role="eye" so blinks can squash them; the resting mouth is
# role="mouth" so talking can replace it; brows/tears/zzz stay put as "deco".

f = emo("neutral", "1f610", "😐")
blush_pair(f, cy=60)
pair(f, "pill", 30, 43, 15, 30, 0, role="eye")
f.glint(33, 35, 4)
f.glint(73, 35, 4)
f.flat(50, 71, 16, role="mouth")

f = emo("happy", "1f60a", "😊")
blush_pair(f)
pair(f, "circle", 30, 42, 12, role="eye")
f.glint(33.5, 38, 4)
f.glint(73.5, 38, 4)
f.curve(50, 68, 28, 9, role="mouth")

f = emo("joy", "1f604", "😄")
blush_pair(f, cy=64)
pair(f, "caret", 30, 41, 18, 11, stroke=7, role="eye")
f.grin(50, 60, 34, 20)

f = emo("laughing", "1f602", "😂")
blush_pair(f, cy=64)
pair(f, "x_mark", 30, 41, 17, stroke=6, role="eye")
f.grin(50, 59, 36, 22, tongue=True)
f.drop(13, 50, 6, 11, color=BLUE)
f.drop(87, 50, 6, 11, color=BLUE)

f = emo("sad", "1f622", "😢")
blush_pair(f, cy=64)
pair(f, "pill", 30, 46, 13, 24, -10, role="eye")
f.glint(33, 39, 3.5)
f.glint(73, 39, 3.5)
f.curve(50, 76, 24, -9, role="mouth")
f.drop(30, 60, 6, 10, color=BLUE)

f = emo("crying", "1f62d", "😭")
blush_pair(f, cy=66)
pair(f, "caret", 30, 42, 17, 9, down=True, stroke=6, role="eye")
f.grin(50, 66, 26, 17)
f.drop(23, 56, 7, 15, color=BLUE)
f.drop(77, 56, 7, 15, color=BLUE)

f = emo("angry", "1f620", "😠")
f.pill(24, 33, 20, 7, -18, color=RED, role="deco")
f.pill(76, 33, 20, 7, 18, color=RED, role="deco")
f.pill(30, 46, 16, 21, -14, role="eye")
f.pill(70, 46, 16, 21, 14, role="eye")
f.circle(32.5, 49, 4.5, color=ORANGE, role="eye")
f.circle(67.5, 49, 4.5, color=ORANGE, role="eye")
f.flat(50, 72, 14, stroke=7, role="mouth")

f = emo("surprised", "1f62e", "😮")
blush_pair(f, cy=63)
pair(f, "circle", 30, 42, 12, role="eye")
f.glint(34, 37.5, 4.5)
f.glint(74, 37.5, 4.5)
f.o_mouth(50, 74, 7)

f = emo("love", "1f60d", "😍")
blush_pair(f)
pair(f, "heart", 30, 42, 19, color=PINK, role="eye")
f.curve(50, 68, 26, 8, role="mouth")

f = emo("thinking", "1f914", "🤔")
f.blush(18, 62, 7.5)
f.blush(82, 62, 7.5)
f.pill(30, 44, 14, 26, 0, role="eye")
f.glint(33, 37, 3.5)
f.circle(72, 38, 6, role="eye")
f.pill(72, 27, 15, 5, -14, role="deco")
f.curve(53, 72, 15, 3, stroke=6, role="mouth")

f = emo("sleepy", "1f634", "😴")
blush_pair(f, cy=58)
pair(f, "arc", 30, 45, 16, 3, 0, stroke=6, role="eye")
f.o_mouth(50, 72, 6, stroke=5)
f.drop(50, 81, 5, 8, color=BLUE)
f.zzz(80, 22, scale=1.0)

f = emo("confused", "1f615", "😕")
blush_pair(f, cy=62)
f.pill(30, 43, 14, 26, 0, role="eye")
f.glint(33, 36, 3.5)
f.arc(72, 42, 14, 2, 18, stroke=6, role="eye")
f.zigzag(50, 72, 22, 6, 3, role="mouth")

f = emo("excited", "1f929", "🤩")
blush_pair(f, cy=64)
pair(f, "star", 30, 41, 15, role="eye")
f.grin(50, 61, 32, 19)

f = emo("embarrassed", "1f633", "😳")
blush_pair(f, cy=58, cx=20, r=10.5, opacity=0.95)
pair(f, "pill", 30, 45, 11, 17, 0, role="eye")
f.o_mouth(50, 73, 5, stroke=5)

f = emo("worried", "1f61f", "😟")
blush_pair(f, cy=64)
f.pill(33, 29, 15, 5, 16, role="deco")
f.pill(67, 29, 15, 5, -16, role="deco")
pair(f, "pill", 30, 45, 12, 20, 0, role="eye")
f.curve(50, 74, 18, -4, stroke=6, role="mouth")
f.drop(88, 31, 5, 9, color=BLUE)

f = emo("cool", "1f60e", "😎")
pair(f, "pill", 30, 43, 17, 7, 0, role="eye")
f.curve(56, 70, 20, 6, stroke=6, role="mouth")

f = emo("scared", "1f631", "😱")
pair(f, "circle", 30, 40, 13, pupil_r=4, role="eye")
f.blush(50, 71, 10, 13, color=WHITE, opacity=1.0, role="mouth")
f.blush(50, 72, 7.5, 10, color=MOUTH_IN, opacity=1.0, role="mouth")
f.drop(86, 28, 5, 9, color=BLUE)

f = emo("wink", "1f609", "😉")
blush_pair(f)
f.circle(30, 42, 12, role="eye")
f.glint(33.5, 38, 4)
f.caret(70, 43, 15, 8, stroke=6, role="eye")
f.curve(50, 68, 24, 8, role="mouth")


# --- mouth anchor --------------------------------------------------------

def mouth_anchor(elems):
    """Where a talking mouth should be drawn, derived from the resting mouth."""
    mouths = [e for e in elems if e.get("role") == "mouth"]
    if not mouths:
        return None
    e = mouths[0]
    if e["t"] == "grin":
        return {"cx": e["cx"], "cy": e["cy"], "w": e["w"]}
    if e["t"] == "o":
        return {"cx": e["cx"], "cy": e["cy"] - e["r"], "w": e["r"] * 3.4}
    if e["t"] in ("flat", "arc", "zigzag"):
        return {"cx": e["cx"], "cy": e["cy"] - 2, "w": e.get("w", 20) * 1.15}
    if e["t"] == "blush":  # scared uses an oval scream mouth
        return {"cx": e["cx"], "cy": e["cy"] - e["ry"], "w": e["rx"] * 2.2}
    return {"cx": e.get("cx", 50), "cy": e.get("cy", 70), "w": 22}


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
    iw, ih, iy = w * 0.82, h * 0.78, cy + h * 0.12
    di = (f'M {cx - iw/2:.2f} {iy:.2f} L {cx + iw/2:.2f} {iy:.2f} '
          f'A {iw/2:.2f} {ih:.2f} 0 0 1 {cx - iw/2:.2f} {iy:.2f} Z')
    out.append(f'<path d="{di}" fill="{e["inner"]}"/>')
    if e.get("tongue"):
        out.append(f'<ellipse cx="{cx}" cy="{cy + h*0.62:.2f}" rx="{w*0.20:.2f}" '
                   f'ry="{h*0.26:.2f}" fill="{e["tongue_color"]}"/>')
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
              "caret": svg_caret, "x": svg_x}


def svg_frame():
    """The bezel ring, stroked on its centre line like the PIL renderer draws it."""
    c = FRAME_INSET + FRAME_WIDTH / 2
    return (f'<rect x="{c:.2f}" y="{c:.2f}" width="{W - 2*c:.2f}" height="{H - 2*c:.2f}" '
            f'rx="{FRAME_RX:.2f}" fill="none" stroke="{FRAME}" '
            f'stroke-width="{FRAME_WIDTH}"/>')


def render_svg(elems):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'width="{W}" height="{H}">',
             f'<rect x="{PANEL_MARGIN}" y="{PANEL_MARGIN}" width="{W - 2*PANEL_MARGIN}" '
             f'height="{H - 2*PANEL_MARGIN}" rx="{PANEL_RX}" fill="{BLACK}"/>']
    for e in elems:
        parts.append(SVG_RENDER[e["t"]](e))
    # Last, so a tear or a Zzz that strays into the margin sits behind the ring.
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
            "panel": {"margin": PANEL_MARGIN, "rx": PANEL_RX, "fill": BLACK},
            "frame": {"width": FRAME_WIDTH, "inset": FRAME_INSET, "rx": FRAME_RX,
                      "color": FRAME},
        },
        "faces": {},
    }

    for name, data in FACES.items():
        elems = data["face"].elems
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
    cols, cell, pad, label_h = 6, 120, 18, 22
    items = list(spec["faces"].items())
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (cell + pad) + pad,
                              rows * (cell + label_h + pad) + pad), (235, 230, 220))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    for i, (char, face) in enumerate(items):
        img = renderer.draw(char, cell)
        x = pad + (i % cols) * (cell + pad)
        y = pad + (i // cols) * (cell + label_h + pad)
        sheet.paste(img, (x, y), img)
        draw.text((x, y + cell + 3), face["name"], fill=(20, 20, 20), font=font)
    sheet.save(path)
    print(f"wrote preview {path}")


if __name__ == "__main__":
    main()
