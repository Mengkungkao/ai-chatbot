"""On the board: wait for the chatbot to start speaking on its own (proactive
chat), then record, on one clock, the app's framebuffer (mouth pixels per
frame, plus raw frames) and the microphone (her voice from the speaker).

    python3 facecap.py OUT_DIR [max_wait_s]

Writes OUT_DIR/cap.json and OUT_DIR/frames.bin (header rows of each frame).
"""
import array
import glob
import json
import os
import subprocess
import sys
import threading
import time

OUT = sys.argv[1]
MAX_WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 420
LOG = os.path.expanduser("~/.whisplay-os/logs/whisplay-ai-chatbot.log")
ROW0, ROW1, W = 30, 140, 240
MOUTH = 0xC148          # faces.json mouth inner #C42B45 in RGB565
RATE, CH, CHAN = 16000, 2, 1
os.makedirs(OUT, exist_ok=True)


def proc_cpu(pattern):
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
    total = 0
    for pid in out:
        try:
            f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
            total += int(f[11]) + int(f[12])
        except OSError:
            pass
    return total / os.sysconf("SC_CLK_TCK")


fb_path = max(glob.glob("/tmp/whisplay-fb-whisplay-ai-chatbot-*.bin"), key=os.path.getmtime)
fb = open(fb_path, "rb")

# idle CPU baseline, 20 s
c0, t0 = proc_cpu("python3 chatbot-ui.py"), time.monotonic()
time.sleep(20)
idle_cpu = (proc_cpu("python3 chatbot-ui.py") - c0) / (time.monotonic() - t0)

log = open(LOG, "r", errors="replace")
log.seek(0, 2)
deadline = time.monotonic() + MAX_WAIT
triggered = None
events = []
while time.monotonic() < deadline:
    line = log.readline()
    if not line:
        time.sleep(0.05)
        continue
    if "Proactive:" in line or "switch to: external_answer" in line or "switch to: answer" in line:
        triggered = time.monotonic()
        events.append((triggered, line.strip()[:120]))
        break
if triggered is None:
    json.dump({"error": "no speech within wait", "idle_cpu": idle_cpu}, open(f"{OUT}/cap.json", "w"))
    sys.exit(1)

rec = subprocess.Popen(["arecord", "-q", "-D", "hw:whisplaysound,0", "-f", "S16_LE", "-r", str(RATE),
                        "-c", str(CH), "-t", "raw", "--period-size=256", "--buffer-size=2048"],
                       stdout=subprocess.PIPE)
stamps, samples, running = [], array.array("h"), [True]


def reader():
    pending, frames, fd = b"", 0, rec.stdout.fileno()
    while running[0]:
        chunk = os.read(fd, 2048)
        now = time.monotonic()
        if not chunk:
            break
        pending += chunk
        usable = len(pending) - len(pending) % (2 * CH)
        block = array.array("h")
        block.frombytes(pending[:usable])
        pending = pending[usable:]
        samples.extend(block[CHAN::CH])
        frames += len(block) // CH
        stamps.append((now, frames))


threading.Thread(target=reader, daemon=True).start()
cpu0, cpu_t0 = proc_cpu("python3 chatbot-ui.py"), time.monotonic()
frames_out = open(f"{OUT}/frames.bin", "wb")
fb_samples = []
saved = 0
last_region = None
done_at = None
end_by = triggered + 40
while time.monotonic() < end_by:
    line = log.readline()
    while line:
        events.append((time.monotonic(), line.strip()[:120]))
        if "Play all audio completed" in line or "switch to: sleep" in line:
            done_at = done_at or time.monotonic()
        line = log.readline()
    if done_at and time.monotonic() > done_at + 2.0:
        break
    t = time.monotonic()
    fb.seek(ROW0 * W * 2)
    region = fb.read((ROW1 - ROW0) * W * 2)
    px = array.array("H")
    px.frombytes(region)
    if sys.byteorder == "little":
        px.byteswap()
    fb_samples.append((t, px.count(MOUTH)))
    if region != last_region and saved < 900:
        frames_out.write(json.dumps({"t": t}).encode() + b"\n" + region)
        saved += 1
        last_region = region
    time.sleep(max(0.0, 0.02 - (time.monotonic() - t)))
speak_cpu = (proc_cpu("python3 chatbot-ui.py") - cpu0) / (time.monotonic() - cpu_t0)
running[0] = False
rec.terminate()
rec.wait()
frames_out.close()
a = min(now - n / RATE for now, n in stamps[5:])
win = RATE // 100   # 10 ms
mic = []
for i in range(0, len(samples) - win, win):
    seg = samples[i:i + win]
    mic.append((a + i / RATE, (sum(v * v for v in seg) / win) ** 0.5))
json.dump({"fb": fb_samples, "mic": mic, "events": events, "idle_cpu": idle_cpu,
           "speak_cpu": speak_cpu, "triggered": triggered, "saved": saved},
          open(f"{OUT}/cap.json", "w"))
print("saved", saved, "frames;", len(fb_samples), "fb samples;", len(mic), "mic windows;",
      f"cpu idle {idle_cpu * 100:.1f}% speaking {speak_cpu * 100:.1f}% of one core")
