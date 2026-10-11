"""Measure the delay from spawning the chatbot's mp3 player (sox) to the sound
reaching the microphone, the way audio.ts plays a TTS clip.

Runs on the board with the chatbot closed. Plays three short beeps.
"""
import array
import os
import subprocess
import sys
import threading
import time

RATE = 16000
CH = 2
DEV_IN = sys.argv[1] if len(sys.argv) > 1 else "hw:whisplaysound,0"
DEV_OUT = sys.argv[2] if len(sys.argv) > 2 else "playback"
BEEP = "/tmp/latency-beep.mp3"
CHAN = int(os.environ.get("CHAN", "0"))

subprocess.run(["sox", "-n", "-r", "24000", "-c", "1", BEEP, "synth", "0.25",
                "sine", "1000", "vol", "0.4"], check=True)
mp3 = open(BEEP, "rb").read()
raw = subprocess.run(["sox", "-q", "-t", "mp3", BEEP, "-t", "raw", "-r", "8000", "-c", "1",
                      "-b", "16", "-e", "signed-integer", "-"],
                     capture_output=True, check=True).stdout
dec = array.array("h")
dec.frombytes(raw)
decoded_onset = next(i for i, v in enumerate(dec) if abs(v) > 1500) / 8000.0
print(f"decoded onset inside the mp3: {decoded_onset * 1000:.1f} ms")

rec = subprocess.Popen(["arecord", "-q", "-D", DEV_IN, "-f", "S16_LE", "-r", str(RATE),
                        "-c", str(CH), "-t", "raw", "--period-size=256",
                        "--buffer-size=2048"], stdout=subprocess.PIPE)
stamps = []          # (monotonic time after read, frames received so far)
samples = array.array("h")
pending = b""
running = True


def reader():
    global pending
    fd = rec.stdout.fileno()
    frames = 0
    while running:
        chunk = os.read(fd, 1024)
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


t = threading.Thread(target=reader, daemon=True)
t.start()
time.sleep(1.2)

spawns = []
for trial in range(3):
    t_spawn = time.monotonic()
    p = subprocess.Popen(["sox", "-q", "-t", "mp3", "-", "-t", "alsa", DEV_OUT, "gain", "2"],
                         stdin=subprocess.PIPE)
    p.stdin.write(mp3)
    p.stdin.close()
    p.wait()
    t_exit = time.monotonic()
    spawns.append((t_spawn, t_exit))
    time.sleep(0.8)

running = False
rec.terminate()
rec.wait()

# wall(sample n) ~= a + n / RATE; the tightest read bounds a from above.
a = min(now - n / RATE for now, n in stamps[5:])
noise_end = int((spawns[0][0] - a) * RATE) - RATE // 10
noise = max(abs(v) for v in samples[RATE // 4:noise_end])
thresh = max(noise * 4, 800)
print(f"peak after spawn {max(abs(v) for v in samples[noise_end:])}")
print(f"noise peak {noise}, threshold {thresh}, reads {len(stamps)}")
for t_spawn, t_exit in spawns:
    start = int((t_spawn - a) * RATE)
    onset = None
    for i in range(start, min(len(samples), start + RATE)):
        if abs(samples[i]) > thresh:
            onset = i
            break
    if onset is None:
        print("no onset found")
        continue
    heard = a + onset / RATE
    lat = heard - t_spawn
    print(f"spawn->heard {lat * 1000:.0f} ms; minus mp3 lead-in {(lat - decoded_onset) * 1000:.0f} ms;"
          f" sox ran {(t_exit - t_spawn) * 1000:.0f} ms")
