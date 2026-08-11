"""Short HUD-style boot animation for the Whisplay panel.

Concentric rings spin up, a sweep runs round the dial, and the logo settles in
the middle. Everything is drawn procedurally so there is no asset to ship, and
the frame count is kept low because a Pi Zero 2 W spends roughly 14ms per
full-screen RGB565 push.
"""

import math
import os
import time

from PIL import Image, ImageDraw

# HUD palette: bright cyan against near-black, with a dim tier for structure
# that should read as "behind" the active elements.
CYAN = (34, 211, 238)
CYAN_DIM = (16, 96, 122)
CYAN_FAINT = (10, 48, 64)
WHITE = (226, 250, 255)
BG = (0, 0, 0)

DEFAULT_DURATION = float(os.environ.get("BOOT_ANIM_SECONDS", "1.6"))
DEFAULT_FPS = int(os.environ.get("BOOT_ANIM_FPS", "14"))

# What sits in the middle of the rings. Empty means use the logo image;
# otherwise a comma-separated list of words shown in order, e.g. "JARVIS,AI".
BOOT_ANIM_TEXT = os.environ.get("BOOT_ANIM_TEXT", "").strip()
BOOT_ANIM_FONT = os.environ.get(
    "BOOT_ANIM_FONT", os.path.join(os.path.dirname(__file__), "NotoSansSC-Bold.ttf")
)
_FONT_CACHE = {}


def _center_words():
    words = [w.strip() for w in BOOT_ANIM_TEXT.split(",") if w.strip()]
    return words or ["AI"]


def _cached_font(size):
    from PIL import ImageFont

    key = (BOOT_ANIM_FONT, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    try:
        font = ImageFont.truetype(BOOT_ANIM_FONT, size)
    except Exception:
        return None
    _FONT_CACHE[key] = font
    return font


def _fit_font(text, max_width):
    """Largest font size that keeps `text` inside max_width."""
    if not os.path.exists(BOOT_ANIM_FONT):
        return None
    size = 72
    while size > 12:
        font = _cached_font(size)
        if font is None:
            return None
        box = font.getbbox(text)
        if (box[2] - box[0]) <= max_width:
            return font
        size -= 2
    return None


def _draw_center_text(draw, words, t, cx, cy, max_width):
    """Zoom the center word in from small to fit cleanly in the middle."""
    if not words:
        return

    index = 0
    if len(words) > 1:
        span = 1.0 / len(words)
        local = max(0.0, (t - 0.45) / 0.55)
        index = min(len(words) - 1, int(local / span))

    word = words[index]
    font = _fit_font(word, max_width)
    if font is None:
        return

    # Zoom effect: start small, then grow into place.
    scale = 0.18 + 0.82 * _ease_out(min(1.0, max(0.0, t / 0.7)))
    scaled_size = max(10, int(round(font.size * scale)))
    scaled_font = _cached_font(scaled_size)
    if scaled_font is None:
        scaled_font = font

    alpha = _ease_in_out(min(1.0, max(0.0, (t - 0.18) / 0.55)))
    box = draw.textbbox((0, 0), word, font=scaled_font)
    w, h = box[2] - box[0], box[3] - box[1]
    draw.text(
        (cx - w / 2 - box[0], cy - h / 2 - box[1]),
        word,
        font=scaled_font,
        fill=_blend(WHITE, alpha),
    )


def _ease_out(t):
    return 1.0 - pow(1.0 - t, 3)


def _ease_in_out(t):
    return 3 * t * t - 2 * t * t * t


def _blend(color, amount):
    """Fade a colour toward black. Cheaper than per-pixel alpha compositing."""
    amount = max(0.0, min(1.0, amount))
    return tuple(int(round(c * amount)) for c in color)


def _arc_segments(draw, box, start_deg, count, gap_deg, color, width):
    """Dashed ring: `count` equal segments with `gap_deg` of space between."""
    if count <= 0:
        return
    step = 360.0 / count
    span = step - gap_deg
    if span <= 0:
        return
    for i in range(count):
        a0 = start_deg + i * step
        draw.arc(box, a0, a0 + span, fill=color, width=width)


def _ticks(draw, cx, cy, radius, count, length, color, width=1):
    for i in range(count):
        angle = math.radians(i * (360.0 / count))
        ca, sa = math.cos(angle), math.sin(angle)
        draw.line(
            [
                (cx + ca * radius, cy + sa * radius),
                (cx + ca * (radius + length), cy + sa * (radius + length)),
            ],
            fill=color,
            width=width,
        )


def _render_frame(size, t, logo):
    """One frame at progress t (0..1)."""
    width, height = size
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    cx, cy = width / 2.0, height / 2.0

    spin = _ease_out(min(1.0, t / 0.75))          # rings accelerate then hold
    settle = _ease_in_out(max(0.0, (t - 0.55) / 0.45))  # logo arrives late
    grow = _ease_out(min(1.0, t / 0.45))          # radius expands on entry
    ring_fade = 1.0
    if t > 0.68:
        ring_fade = max(0.0, 1.0 - _ease_in_out(min(1.0, (t - 0.68) / 0.32)))

    # Outer ring, simple and cheap.
    r_out = 88 * grow
    if r_out > 6:
        box = [cx - r_out, cy - r_out, cx + r_out, cy + r_out]
        _arc_segments(draw, box, spin * 280, 2, 90, _blend(CYAN_DIM, grow * ring_fade), 2)

    # Middle ring, simpler arc with lower detail.
    r_mid = 62 * grow
    if r_mid > 6:
        box = [cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid]
        _arc_segments(draw, box, -spin * 340 + 10, 3, 80, _blend(CYAN, grow * 0.75 * ring_fade), 2)

    # Inner dial with a pair of short rotating sweep arcs.
    r_in = 44 * grow
    inner_glow = _ease_in_out(min(1.0, max(0.0, (t - 0.18) / 0.48))) * ring_fade
    if r_in > 6:
        box = [cx - r_in, cy - r_in, cx + r_in, cy + r_in]
        sweep_start = spin * 480
        draw.arc(box, sweep_start, sweep_start + 68, fill=_blend(WHITE, grow * inner_glow), width=2)
        draw.arc(box, sweep_start + 150, sweep_start + 220, fill=_blend(CYAN_DIM, grow * inner_glow * 0.7), width=2)

    # Centre glow and piece: words if configured, otherwise the logo image.
    words = _center_words()
    if words:
        glow_alpha = _ease_in_out(min(1.0, max(0.0, (t - 0.18) / 0.34))) * 0.26
        glow_radius = 30 * grow
        if glow_radius > 3:
            draw.ellipse(
                [cx - glow_radius, cy - glow_radius, cx + glow_radius, cy + glow_radius],
                fill=_blend(CYAN_FAINT, glow_alpha),
            )
        _draw_center_text(draw, words, t, cx, cy, min(110, width * 0.5))
    elif logo is not None and settle > 0.01:
        scale = 0.72 + 0.28 * settle
        target = max(1, int(round(logo.width * scale)))
        mark = logo.resize((target, target), Image.LANCZOS)
        faded = Image.new("RGBA", mark.size, (0, 0, 0, 0))
        faded.paste(mark, (0, 0), mark)
        alpha = faded.getchannel("A").point(lambda a: int(a * settle))
        faded.putalpha(alpha)
        image.paste(
            faded,
            (int(cx - faded.width / 2), int(cy - faded.height / 2)),
            faded,
        )

    return image


def _load_logo(logo_path, max_size):
    if not logo_path or not os.path.exists(logo_path):
        return None
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return None
    # Square it off so the centre scale animation stays symmetric.
    side = min(logo.width, logo.height)
    left = (logo.width - side) // 2
    top = (logo.height - side) // 2
    logo = logo.crop((left, top, left + side, top + side))
    return logo.resize((max_size, max_size), Image.LANCZOS)


def play(whisplay, image_utils, logo_path=None,
         duration=DEFAULT_DURATION, fps=DEFAULT_FPS):
    """Draw the boot sequence, then leave the final frame on screen.

    Falls back to doing nothing if the panel is unavailable, so a failure here
    can never stop the app from starting.
    """
    try:
        width, height = whisplay.LCD_WIDTH, whisplay.LCD_HEIGHT
        logo = _load_logo(logo_path, 74)
        frames = max(1, int(duration * fps))
        interval = duration / frames

        whisplay.set_backlight(100)
        if frames <= 1:
            frame = _render_frame((width, height), 1.0, logo)
            whisplay.draw_image(
                0, 0, width, height,
                image_utils.image_to_rgb565(frame, width, height),
            )
            return

        for index in range(frames + 1):
            started = time.time()
            t = min(1.0, index / frames)
            frame = _render_frame((width, height), t, logo)
            whisplay.draw_image(
                0, 0, width, height,
                image_utils.image_to_rgb565(frame, width, height),
            )
            remaining = interval - (time.time() - started)
            if remaining > 0:
                time.sleep(remaining)
    except Exception as error:
        print(f"[BootAnim] skipped: {error}")
