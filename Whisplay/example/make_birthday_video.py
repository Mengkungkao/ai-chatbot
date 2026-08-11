#!/usr/bin/env python3
"""Generate a Happy Birthday video sized for the Whisplay screen.

Renders animated frames with PIL and synthesises the melody as a WAV, then
muxes both into an mp4. The Happy Birthday tune is public domain (the
Warner/Chappell copyright claim was invalidated in 2016).
"""

import argparse
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import wave

from PIL import Image, ImageDraw, ImageFont

try:
    import numpy as np
except ImportError:
    np = None

WIDTH = 240
HEIGHT = 280
FPS = 20
SAMPLE_RATE = 22050
BPM = 120

NOTES = {
    'C4': 261.63, 'D4': 293.66, 'E4': 329.63, 'F4': 349.23, 'G4': 392.00,
    'A4': 440.00, 'B4': 493.88, 'C5': 523.25, 'D5': 587.33, 'E5': 659.25,
    'F5': 698.46, 'G5': 783.99,
}

# (note, beats) in 3/4 time.
MELODY = [
    ('G4', 0.75), ('G4', 0.25), ('A4', 1), ('G4', 1), ('C5', 1), ('B4', 2),
    ('G4', 0.75), ('G4', 0.25), ('A4', 1), ('G4', 1), ('D5', 1), ('C5', 2),
    ('G4', 0.75), ('G4', 0.25), ('G5', 1), ('E5', 1), ('C5', 1), ('B4', 1), ('A4', 2),
    ('F5', 0.75), ('F5', 0.25), ('E5', 1), ('C5', 1), ('D5', 1), ('C5', 2),
]

CONFETTI_COLORS = [
    (255, 99, 132), (255, 205, 86), (75, 192, 192), (153, 102, 255),
    (255, 159, 64), (54, 162, 235), (255, 255, 255),
]


def load_font(size, bold=True):
    candidates = []
    if bold:
        candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def synth_melody(path):
    beat_sec = 60.0 / BPM
    samples = []
    for name, beats in MELODY:
        freq = NOTES[name]
        duration = beats * beat_sec
        count = int(duration * SAMPLE_RATE)
        # Short gap between notes so repeated pitches stay distinct.
        gap = int(min(0.04, duration * 0.15) * SAMPLE_RATE)
        tone_count = count - gap
        if np is not None:
            t = np.arange(tone_count) / SAMPLE_RATE
            envelope = np.exp(-3.0 * t / max(duration, 0.001))
            attack = np.minimum(1.0, np.arange(tone_count) / max(SAMPLE_RATE * 0.01, 1))
            wave_data = (
                np.sin(2 * np.pi * freq * t)
                + 0.35 * np.sin(4 * np.pi * freq * t)
                + 0.12 * np.sin(6 * np.pi * freq * t)
            )
            block = wave_data * envelope * attack * 0.30
            samples.append(block)
            samples.append(np.zeros(gap))
        else:
            for i in range(tone_count):
                t = i / SAMPLE_RATE
                envelope = math.exp(-3.0 * t / max(duration, 0.001))
                attack = min(1.0, i / max(SAMPLE_RATE * 0.01, 1))
                value = (
                    math.sin(2 * math.pi * freq * t)
                    + 0.35 * math.sin(4 * math.pi * freq * t)
                    + 0.12 * math.sin(6 * math.pi * freq * t)
                )
                samples.append(value * envelope * attack * 0.30)
            samples.extend([0.0] * gap)

    if np is not None:
        signal = np.concatenate(samples)
        clipped = np.clip(signal, -1.0, 1.0)
        pcm = (clipped * 32767).astype('<i2').tobytes()
        total = len(clipped)
    else:
        pcm = b''.join(struct.pack('<h', int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
        total = len(samples)

    with wave.open(path, 'wb') as fp:
        fp.setnchannels(1)
        fp.setsampwidth(2)
        fp.setframerate(SAMPLE_RATE)
        fp.writeframes(pcm)
    return total / SAMPLE_RATE


def make_background():
    image = Image.new("RGB", (WIDTH, HEIGHT))
    if np is not None:
        rows = np.linspace(0, 1, HEIGHT)[:, None]
        r = (18 + rows * 40).astype(np.uint8)
        g = (12 + rows * 18).astype(np.uint8)
        b = (48 + rows * 70).astype(np.uint8)
        grad = np.repeat(np.dstack([r, g, b]), WIDTH, axis=1)
        return Image.fromarray(grad.astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        draw.line([(0, y), (WIDTH, y)],
                  fill=(int(18 + ratio * 40), int(12 + ratio * 18), int(48 + ratio * 70)))
    return image


def draw_cake(draw, cy, flicker):
    cake_w = 96
    cake_x = (WIDTH - cake_w) // 2
    # plate
    draw.ellipse((cake_x - 14, cy + 34, cake_x + cake_w + 14, cy + 50), fill=(210, 214, 224))
    # body
    draw.rounded_rectangle((cake_x, cy, cake_x + cake_w, cy + 40), radius=6, fill=(238, 165, 190))
    draw.rounded_rectangle((cake_x, cy, cake_x + cake_w, cy + 12), radius=6, fill=(255, 240, 245))
    for i in range(4):
        drip_x = cake_x + 10 + i * 24
        draw.ellipse((drip_x, cy + 6, drip_x + 12, cy + 20), fill=(255, 240, 245))
    # candles
    for i in range(3):
        candle_x = cake_x + 22 + i * 26
        draw.rectangle((candle_x, cy - 20, candle_x + 5, cy), fill=(120, 190, 255))
        flame_h = 9 + flicker[i]
        draw.ellipse(
            (candle_x - 3, cy - 20 - flame_h, candle_x + 8, cy - 18),
            fill=(255, 200, 60),
        )
        draw.ellipse(
            (candle_x - 1, cy - 17 - flame_h // 2, candle_x + 6, cy - 19),
            fill=(255, 250, 210),
        )


def render_frames(duration, name, out_pipe):
    background = make_background()
    title_font = load_font(30)
    name_font = load_font(20)
    small_font = load_font(13, bold=False)

    random.seed(7)
    confetti = []
    for _ in range(46):
        confetti.append({
            'x': random.uniform(0, WIDTH),
            'y': random.uniform(-HEIGHT, HEIGHT),
            'speed': random.uniform(22, 62),
            'size': random.randint(3, 6),
            'color': random.choice(CONFETTI_COLORS),
            'drift': random.uniform(-14, 14),
            'spin': random.uniform(0, 6.28),
        })

    total_frames = int(duration * FPS)
    for frame_index in range(total_frames):
        t = frame_index / FPS
        image = background.copy()
        draw = ImageDraw.Draw(image)

        for piece in confetti:
            y = (piece['y'] + piece['speed'] * t) % (HEIGHT + 40) - 20
            x = (piece['x'] + math.sin(t * 1.4 + piece['spin']) * piece['drift']) % WIDTH
            size = piece['size']
            draw.rectangle((x, y, x + size, y + size * 1.6), fill=piece['color'])

        flicker = [random.randint(0, 4) for _ in range(3)]
        draw_cake(draw, 178, flicker)

        # Title pulses gently so the screen never looks frozen.
        pulse = 1.0 + 0.06 * math.sin(t * 3.2)
        title_color = (255, 236, 150) if int(t * 2) % 2 == 0 else (255, 255, 255)
        for line, base_y, font in (("HAPPY", 44, title_font), ("BIRTHDAY!", 78, title_font)):
            bbox = draw.textbbox((0, 0), line, font=font)
            w = bbox[2] - bbox[0]
            x = (WIDTH - w * pulse) / 2
            y = base_y + math.sin(t * 3.2) * 2
            draw.text((x + 2, y + 2), line, fill=(0, 0, 0), font=font)
            draw.text((x, y), line, fill=title_color, font=font)

        if name:
            label = f"Dear {name}"
            bbox = draw.textbbox((0, 0), label, font=name_font)
            x = (WIDTH - (bbox[2] - bbox[0])) / 2
            draw.text((x, 116), label, fill=(150, 230, 255), font=name_font)

        footer = "Made with Whisplay"
        bbox = draw.textbbox((0, 0), footer, font=small_font)
        draw.text(((WIDTH - (bbox[2] - bbox[0])) / 2, HEIGHT - 26), footer,
                  fill=(160, 175, 195), font=small_font)

        out_pipe.write(image.tobytes())
        if frame_index % 40 == 0:
            print(f"  frame {frame_index}/{total_frames}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="", help="name to greet, e.g. --name Jarvis")
    parser.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "happy_birthday.mp4"))
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found in PATH.")
        return 1

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    audio_path = args.out + ".melody.wav"

    print("Synthesising melody...")
    duration = synth_melody(audio_path)
    print(f"  melody length: {duration:.2f}s")

    cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', '-',
        '-i', audio_path,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '96k',
        '-shortest', '-loglevel', 'error',
        args.out,
    ]
    print("Rendering frames...")
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        render_frames(duration, args.name, process.stdin)
        process.stdin.close()
    except BrokenPipeError:
        print("Error: ffmpeg closed the pipe early.")
    rc = process.wait()
    try:
        os.unlink(audio_path)
    except OSError:
        pass

    if rc != 0 or not os.path.exists(args.out):
        print(f"Error: ffmpeg failed with code {rc}")
        return 1
    print(f"Wrote {args.out} ({os.path.getsize(args.out)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
