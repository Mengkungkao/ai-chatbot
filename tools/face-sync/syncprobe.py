"""On the board, with AI Chatbot open and idle: play clips the way the app does
(sox, mp3 on stdin) while sending the app's UI the same speech messages the
Node core sends, and record the app framebuffer's mouth and the microphone on
one clock. Reports how far the mouth leads (-) or lags (+) the voice.

    python3 syncprobe.py APP_DIR [send_at]

APP_DIR is the active version folder (for its node and speech-envelope.js).
"""
import array
import glob
import json
import os
import socket
import subprocess
import sys
import threading
import time

APP = sys.argv[1]
SEND_AT = len(sys.argv) > 2 and sys.argv[2] == "send_at"
RATE, CH, CHAN = 16000, 2, 1
MOUTH = 0xC148
ROW0, ROW1, W = 30, 140, 240


def envelope(path):
    out = subprocess.run(
        [os.path.join(APP, "runtime/bin/node"), "-e",
         "require(process.argv[1]).speechEnvelope({filePath: process.argv[2], duration: 1}, 'mp3')"
         ".then(e => console.log(JSON.stringify(e)))",
         os.path.join(APP, "dist/device/speech-envelope.js"), path],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


# clips: tone bursts (clean onsets) and two real TTS sentences
subprocess.run(["sox", "-n", "-r", "24000", "-c", "1", "/tmp/probe-bursts.mp3",
                "synth", "0.18", "sine", "400", "vol", "0.5", "pad", "0", "0.22",
                "repeat", "9"], check=True)
clips = ["/tmp/probe-bursts.mp3", "/tmp/tts-sample-0.mp3", "/tmp/tts-sample-1.mp3"]
envs = [envelope(c) for c in clips]

fb = open(max(glob.glob("/tmp/whisplay-fb-whisplay-ai-chatbot-*.bin"), key=os.path.getmtime), "rb")
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


fbs = []


def fb_sampler():
    while running[0]:
        t = time.monotonic()
        fb.seek(ROW0 * W * 2)
        px = array.array("H")
        px.frombytes(fb.read((ROW1 - ROW0) * W * 2))
        if sys.byteorder == "little":
            px.byteswap()
        fbs.append((t, px.count(MOUTH)))
        time.sleep(max(0.0, 0.01 - (time.monotonic() - t)))


threading.Thread(target=reader, daemon=True).start()
threading.Thread(target=fb_sampler, daemon=True).start()
ui = socket.create_connection(("127.0.0.1", 12345))
time.sleep(1.0)
starts = []
for i, (clip, env) in enumerate(zip(clips, envs)):
    data = open(clip, "rb").read()
    dur = len(env) * 20
    ev = {"state": "start", "id": 9000 + i, "duration_ms": dur, "frame_ms": 20, "envelope": env}
    if SEND_AT:
        ev["at"] = time.time() * 1000.0
    t_start = time.monotonic()
    ui.sendall((json.dumps({"speech": ev}) + "\n").encode())
    p = subprocess.Popen(["sox", "-q", "-t", "mp3", "-", "-t", "alsa", "playback", "gain", "2"],
                         stdin=subprocess.PIPE)
    p.stdin.write(data)
    p.stdin.close()
    p.wait()
    ui.sendall((json.dumps({"speech": {"state": "end", "id": 9000 + i}}) + "\n").encode())
    starts.append((t_start, time.monotonic()))
    time.sleep(1.2)
running[0] = False
rec.terminate()
rec.wait()
ui.close()

a = min(now - n / RATE for now, n in stamps[5:])
win = RATE // 100
mic = [(a + i / RATE, (sum(v * v for v in samples[i:i + win]) / win) ** 0.5)
       for i in range(0, len(samples) - win, win)]


def at(series, t):
    lo, hi = 0, len(series) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if series[mid][0] <= t:
            lo = mid
        else:
            hi = mid - 1
    return series[lo][1]


def corr(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sx = sum((v - mx) ** 2 for v in x) ** 0.5
    sy = sum((v - my) ** 2 for v in y) ** 0.5
    return sum((x[k] - mx) * (y[k] - my) for k in range(n)) / (sx * sy or 1)


noise = sorted(v for _, v in mic)[len(mic) // 5]
for (t0, t1), clip in zip(starts, clips):
    grid = [t0 + k * 0.01 for k in range(int((t1 - t0) / 0.01))]
    m = [at(fbs, t) for t in grid]
    s = [at(mic, t) for t in grid]
    pk = sorted(s)[int(len(s) * 0.97)]
    best = max(((lag, corr(s[:len(s) - lag], m[lag:]) if lag >= 0 else corr(s[-lag:], m[:len(m) + lag]))
                for lag in range(-30, 41)), key=lambda x: x[1])
    # onsets: voice crosses 35% of peak after >= 60 ms below 12%
    onsets, quiet = [], 0
    for k, v in enumerate(s):
        if v < pk * 0.12:
            quiet += 1
        else:
            if v > pk * 0.35 and quiet >= 6:
                onsets.append(k)
            if v >= pk * 0.12:
                quiet = 0 if v > pk * 0.35 else quiet
    opens = [k for k in range(1, len(m)) if m[k] > 0 and m[k - 1] == 0]
    lags = sorted((min(opens, key=lambda x: abs(x - o)) - o) * 10 for o in onsets
                  if any(abs(x - o) <= 30 for x in opens))
    shut = [k for k, v in enumerate(s) if v < max(noise * 2, pk * 0.05)]
    print(f"{os.path.basename(clip)}: corr lag {best[0] * 10:+d} ms (r={best[1]:.2f}); "
          f"onset lags {lags} median {lags[len(lags) // 2] if lags else None} ms; "
          f"mouth open in {sum(1 for k in shut if m[k] > 0) * 10} of {len(shut) * 10} ms of silence")
