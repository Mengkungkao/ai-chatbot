"""Lip sync on the board, from facecap.py's capture: how far the app's mouth
leads or lags the voice heard at the microphone, whether the mouth stays shut
when she is silent, plus a contact sheet and GIF of the captured frames."""
import json
import math
import os
import sys

from PIL import Image

D = sys.argv[1]
cap = json.load(open(os.path.join(D, "cap.json")))
fb, mic = cap["fb"], cap["mic"]
print("events:")
for t, line in cap["events"]:
    if any(k in line for k in ("Playing audio", "completed", "Proactive", "switch to", "TTS time")):
        print(f"  {t - cap['triggered']:7.2f}s  {line[:90]}")
print(f"CPU (chatbot-ui.py): idle {cap['idle_cpu'] * 100:.1f}%  while speaking {cap['speak_cpu'] * 100:.1f}% of one core")

t0 = max(fb[0][0], mic[0][0])
t1 = min(fb[-1][0], mic[-1][0])
STEP = 0.01
grid = [t0 + i * STEP for i in range(int((t1 - t0) / STEP))]


def sample(series, t, hold=True):
    # last value at or before t (a frame stays on screen until replaced)
    lo, hi = 0, len(series) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if series[mid][0] <= t:
            lo = mid
        else:
            hi = mid - 1
    return series[lo][1]


m = [sample(fb, t) for t in grid]
a = [sample(mic, t) for t in grid]
peak = sorted(a)[int(len(a) * 0.97)] or 1
noise = sorted(a)[int(len(a) * 0.2)]
loud = [max(0.0, (v - noise * 1.5)) / peak for v in a]
mpeak = max(m) or 1
mo = [v / mpeak for v in m]


def corr(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (sx * sy or 1)


best = None
for lag in range(-30, 31):          # mouth[t + lag] vs loud[t], lag in 10 ms steps
    if lag >= 0:
        c = corr(loud[:len(loud) - lag], mo[lag:])
    else:
        c = corr(loud[-lag:], mo[:len(mo) + lag])
    if best is None or c > best[1]:
        best = (lag, c)
print(f"mouth vs voice: best correlation {best[1]:.2f} with the mouth {'lagging' if best[0] > 0 else 'leading'} "
      f"by {abs(best[0]) * 10} ms (app framebuffer; the LCD adds the daemon's push)")

# silent stretches: mouth open while the mic hears nothing?
quiet = [i for i, v in enumerate(loud) if v < 0.02]
# allow the jaw's release and the sync lead around each sound
near = set()
for i, v in enumerate(loud):
    if v >= 0.02:
        near.update(range(i - 15, i + 15))
strict_quiet = [i for i in quiet if i not in near]
open_in_quiet = sum(1 for i in strict_quiet if m[i] > 0)
print(f"silent stretches (≥150 ms from any sound): {len(strict_quiet) * 10} ms, mouth open in "
      f"{open_in_quiet * 10} ms of it")
voiced = [i for i, v in enumerate(loud) if v > 0.25]
print(f"loud stretches: {len(voiced) * 10} ms, mouth open in {sum(1 for i in voiced if m[i] > 0) * 10} ms")

# frames -> sheet + gif
frames = []
with open(os.path.join(D, "frames.bin"), "rb") as fh:
    data = fh.read()
pos = 0
size = (140 - 30) * 240 * 2
while pos < len(data):
    nl = data.index(b"\n", pos)
    t = json.loads(data[pos:nl])["t"]
    raw = data[nl + 1:nl + 1 + size]
    pos = nl + 1 + size
    px = bytearray()
    for i in range(0, len(raw), 2):
        v = (raw[i] << 8) | raw[i + 1]
        px += bytes(((v >> 11) << 3, ((v >> 5) & 63) << 2, (v & 31) << 3))
    frames.append((t, Image.frombytes("RGB", (240, 110), bytes(px))))
print(len(frames), "distinct frames captured")
first_play = next((t for t, l in cap["events"] if "Playing audio 1/" in l), frames[0][0])
pick = [f for f in frames if first_play - 0.3 <= f[0] <= first_play + 3.5][:48]
cols = 8
sheet = Image.new("RGB", (cols * 120, ((len(pick) + cols - 1) // cols) * 110), (30, 30, 30))
for i, (t, img) in enumerate(pick):
    sheet.paste(img.crop((60, 0, 180, 110)), ((i % cols) * 120, (i // cols) * 110))
sheet.save(os.path.join(D, "board-sheet.png"))
gif = [img.crop((50, 0, 190, 110)).resize((280, 220), Image.NEAREST) for t, img in frames]
durs = [max(20, int(round((frames[i + 1][0] - frames[i][0]) * 1000))) for i in range(len(frames) - 1)] + [100]
gif[0].save(os.path.join(D, "board.gif"), save_all=True, append_images=gif[1:], duration=durs, loop=0)
print("wrote board-sheet.png, board.gif")
