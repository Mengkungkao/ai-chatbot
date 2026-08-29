"""Measure the reconstruction against the reference on the points that matter.

Every figure is taken the same way from both images, so the comparison is like
for like rather than a description of what each looks like.
"""

import sys
from collections import deque

from PIL import Image

BG = (183, 241, 255)


def load(path):
    return Image.open(path).convert("RGB")


def isbg(p, tol=40):
    return sum(abs(a - b) for a, b in zip(p, BG)) < tol


def metrics(img):
    W, H = img.size
    px = img.load()
    sil = [[0 if isbg(px[x, y]) else 1 for x in range(W)] for y in range(H)]

    def span(y):
        xs = [x for x in range(W) if sil[y][x]]
        return (min(xs), max(xs)) if xs else None

    rows = [y for y in range(H) if any(sil[y])]
    top, bottom = rows[0], rows[-1]

    # ear tips: the two runs a few rows below the top
    y = top + 2
    runs, run = [], None
    for x in range(W):
        if sil[y][x]:
            if run is None:
                run = x
        elif run is not None:
            runs.append((run, x - 1)); run = None
    if run is not None:
        runs.append((run, W - 1))
    tips = [((a + b) / 2) for a, b in runs if b - a > 3]

    # valley between the ears: the highest fill row on the centre column
    cx = W // 2
    valley = next((y for y in range(top, bottom) if sil[y][cx]), None)

    # head width clear of the whiskers
    widths = {y: (span(y)[1] - span(y)[0] + 1) for y in (140, 150, 215, 225) if span(y)}

    # dark features: eyes and mouth
    dark = [[1 if (not isbg(px[x, y]) and sum(px[x, y]) / 3 < 130) else 0
             for x in range(W)] for y in range(H)]
    seen = [[False] * W for _ in range(H)]
    comps = []
    for y in range(H):
        for x in range(W):
            if dark[y][x] and not seen[y][x]:
                q = deque([(x, y)]); seen[y][x] = True; xs = []; ys = []
                while q:
                    a, b = q.popleft(); xs.append(a); ys.append(b)
                    for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,-1),(1,-1),(-1,1)):
                        nx, ny = a + dx, b + dy
                        if 0 <= nx < W and 0 <= ny < H and dark[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True; q.append((nx, ny))
                if len(xs) > 60:
                    comps.append((len(xs), min(xs), max(xs), min(ys), max(ys)))
    # Eyes are the near-circular blobs in the upper half of the face. Filtering
    # only by size picked up whisker strokes, which are longer than they are tall.
    eyes = sorted([c for c in comps
                   if abs((c[2] - c[1]) - (c[4] - c[3])) < 8      # roughly round
                   and 20 < (c[2] - c[1]) < 45
                   and H * 0.45 < (c[3] + c[4]) / 2 < H * 0.70],  # eye band
                  key=lambda c: c[1])[:2]
    mouth = next((c for c in comps
                  if abs((c[1] + c[2]) / 2 - W / 2) < 30 and 170 < (c[3] + c[4]) / 2 < 205), None)

    m = {"top": top, "bottom": bottom, "tips": [round(t, 1) for t in tips], "valley": valley}
    m.update({f"width@{k}": v for k, v in widths.items()})
    if len(eyes) == 2:
        m["eye_l_x"] = round((eyes[0][1] + eyes[0][2]) / 2, 1)
        m["eye_r_x"] = round((eyes[1][1] + eyes[1][2]) / 2, 1)
        m["eye_y"] = round((eyes[0][3] + eyes[0][4]) / 2, 1)
        m["eye_d"] = eyes[0][2] - eyes[0][1] + 1
        m["eye_gap"] = round(m["eye_r_x"] - m["eye_l_x"], 1)
    if mouth:
        m["mouth_x"] = round((mouth[1] + mouth[2]) / 2, 1)
        m["mouth_y"] = round((mouth[3] + mouth[4]) / 2, 1)
        m["mouth_w"] = mouth[2] - mouth[1] + 1
        m["mouth_h"] = mouth[4] - mouth[3] + 1
    return m


if __name__ == "__main__":
    ref, got = metrics(load(sys.argv[1])), metrics(load(sys.argv[2]))
    keys = [k for k in ref if k in got]
    print(f"{'metric':12s} {'reference':>12s} {'ours':>12s} {'diff':>8s}")
    for k in keys:
        a, b = ref[k], got[k]
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            print(f"{k:12s} {str(a):>12s} {str(b):>12s}")
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            print(f"{k:12s} {a:12.1f} {b:12.1f} {b-a:+8.1f}")
        else:
            print(f"{k:12s} {str(a):>12s} {str(b):>12s}")
