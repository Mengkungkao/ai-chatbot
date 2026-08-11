import subprocess
import os
import sys
import gc
import shutil
import time
import argparse
import urllib.request
from PIL import Image, ImageDraw, ImageFont

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
runtime_dir = os.path.join(project_root, "runtime")
if runtime_dir not in sys.path:
    sys.path.append(runtime_dir)

from whisplay_client import create_whisplay_hardware

try:
    import numpy as np
except ImportError:
    np = None

VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")
LONG_PRESS_SEC = 0.7
DEFAULT_VIDEO_NAME = "whisplay_test.mp4"
DEFAULT_VIDEO_URL = "https://img-storage.pisugar.uk/whisplay_test.mp4"


def get_ffmpeg_cmd(video_path, width, height):
    model = "generic"
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read().lower()
    except:
        pass

    input_args = []
    vf_params = f'scale={width}:{height}:flags=neighbor'

    if 'zero 2' in model or 'raspberry pi 3' in model:
        print(f"Device: {model.strip()} | Mode: Multi-thread")
        input_args = ['-threads', '4']
    elif 'zero' in model:
        print("Device: Pi Zero/W | Mode: HW Accel")
        input_args = ['-vcodec', 'h264_v4l2m2m']
    elif 'raspberry pi 4' in model or 'raspberry pi 5' in model:
        print(f"Device: {model.strip()} | Mode: High-perf")
        input_args = ['-threads', '4']
        vf_params = f'scale={width}:{height}:flags=bicubic'

    # -re paces decoding to the native frame rate. Without it ffmpeg dumps
    # frames as fast as the CPU allows and the video races ahead of the audio.
    return ['ffmpeg', '-re'] + input_args + [
        '-i', video_path,
        '-vf', vf_params,
        '-vcodec', 'rawvideo',
        '-pix_fmt', 'rgb565be',
        '-f', 'image2pipe',
        '-loglevel', 'quiet',
        '-'
    ]


def start_audio_process(video_path):
    # Plays audio via ALSA's default device. Use ffplay or mpv if you have them.
    return subprocess.Popen(
        ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', video_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_process(proc):
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=1)
    except Exception:
        pass


def image_to_rgb565(image):
    if np is not None:
        arr = np.asarray(image.convert("RGB"), dtype=np.uint16)
        packed = ((arr[:, :, 0] & 0xF8) << 8) | ((arr[:, :, 1] & 0xFC) << 3) | (arr[:, :, 2] >> 3)
        return packed.astype('>u2').tobytes()
    frame = bytearray()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = image.getpixel((x, y))
            value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            frame.append((value >> 8) & 0xFF)
            frame.append(value & 0xFF)
    return bytes(frame)


def load_font(size, bold=False):
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


def is_playable(video_path):
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return False
    if not shutil.which("ffprobe"):
        return True
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0 and result.stdout.strip() not in (b'', b'N/A')


def video_duration(video_path):
    if not shutil.which("ffprobe"):
        return 0.0
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def find_videos(video_dir):
    if not os.path.isdir(video_dir):
        return []
    names = [n for n in os.listdir(video_dir) if n.lower().endswith(VIDEO_EXTENSIONS)]
    paths = [os.path.join(video_dir, n) for n in sorted(names)]
    return [p for p in paths if is_playable(p)]


class VideoPlayerApp:
    def __init__(self, video_dir):
        self.board = create_whisplay_hardware(
            app_id=os.getenv("WHISPLAY_APP_ID", "whisplay-play-mp4"),
            display_name="Play MP4",
            icon="V",
            use_daemon_default_log=True,
        )
        self.board.set_backlight(100)
        self.width = self.board.LCD_WIDTH
        self.height = self.board.LCD_HEIGHT
        self.video_dir = video_dir
        self.videos = []
        self.selected = 0
        self.running = True
        self.mode = "list"
        self.activate = False
        self.stop_playback = False
        self.button_down_at = 0.0
        self.status = ""

        self.title_font = load_font(20, bold=True)
        self.item_font = load_font(15)
        self.small_font = load_font(12)

        self.board.on_button_press(self._on_press)
        self.board.on_button_release(self._on_release)
        if hasattr(self.board, "on_exit_request"):
            self.board.on_exit_request(self._on_exit)
        if hasattr(self.board, "on_focus_revoked"):
            self.board.on_focus_revoked(self._on_exit)

    def _on_exit(self, _payload=None):
        self.running = False
        self.stop_playback = True

    def _on_press(self):
        self.button_down_at = time.time()

    def _on_release(self):
        held = time.time() - self.button_down_at if self.button_down_at else 0.0
        self.button_down_at = 0.0
        if self.mode == "playing":
            # Only a hold leaves playback; taps must not move the list selection.
            if held >= LONG_PRESS_SEC:
                self.stop_playback = True
            return
        if held >= LONG_PRESS_SEC:
            self.activate = True
        else:
            self.selected = (self.selected + 1) % max(len(self.videos) + 1, 1)

    def _items(self):
        return [os.path.basename(p) for p in self.videos] + ["Back to desktop"]

    def render_list(self):
        items = self._items()
        image = Image.new("RGB", (self.width, self.height), (11, 16, 24))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (12, 16, self.width - 12, self.height - 16),
            radius=18, fill=(20, 28, 40), outline=(40, 55, 72), width=2,
        )
        draw.rounded_rectangle((20, 22, self.width - 20, 56), radius=12, fill=(60, 140, 255))
        draw.text((30, 31), "SELECT VIDEO", fill=(255, 255, 255), font=self.small_font)

        y = 68
        row_h = 30
        visible = (self.height - 118) // row_h
        start = max(0, min(self.selected - visible + 1, len(items) - visible)) if len(items) > visible else 0
        for index in range(start, min(start + visible, len(items))):
            name = items[index]
            is_selected = index == self.selected
            if is_selected:
                draw.rounded_rectangle((20, y - 4, self.width - 20, y + row_h - 8), radius=8, fill=(45, 78, 120))
            label = name if len(name) <= 24 else name[:21] + "..."
            draw.text((30, y), label, fill=(255, 255, 255) if is_selected else (190, 205, 220), font=self.item_font)
            y += row_h

        footer_top = self.height - 66
        draw.rounded_rectangle((20, footer_top, self.width - 20, self.height - 22), radius=12, fill=(28, 37, 50))
        draw.text((28, footer_top + 7), "Tap: next   Hold: play", fill=(150, 205, 255), font=self.small_font)
        draw.text((28, footer_top + 25), self.status or f"{len(self.videos)} video(s) found", fill=(120, 140, 160), font=self.small_font)

        self.board.draw_image(0, 0, self.width, self.height, image_to_rgb565(image))

    def render_message(self, title, message):
        image = Image.new("RGB", (self.width, self.height), (11, 16, 24))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (12, 16, self.width - 12, self.height - 16),
            radius=18, fill=(20, 28, 40), outline=(40, 55, 72), width=2,
        )
        draw.text((24, self.height // 2 - 30), title, fill=(255, 255, 255), font=self.title_font)
        draw.text((24, self.height // 2 + 4), message, fill=(180, 200, 220), font=self.small_font)
        self.board.draw_image(0, 0, self.width, self.height, image_to_rgb565(image))

    def play(self, video_path):
        self.stop_playback = False
        frame_size = self.width * self.height * 2
        buffer = bytearray(frame_size)

        def start_video():
            return subprocess.Popen(
                get_ffmpeg_cmd(video_path, self.width, self.height),
                stdout=subprocess.PIPE,
                bufsize=frame_size,
            )

        process = start_video()
        audio = start_audio_process(video_path)
        gc.collect()
        gc.disable()
        print(f"Playing (loop): {video_path}")
        try:
            while self.running and not self.stop_playback:
                frames_this_run = 0
                while self.running and not self.stop_playback:
                    if process.stdout.readinto(buffer) != frame_size:
                        break
                    frames_this_run += 1
                    self.board.draw_image(0, 0, self.width, self.height, buffer)
                if not self.running or self.stop_playback:
                    break

                # A run that yielded no frames is a decode failure, not end-of-video.
                # Restarting it unconditionally would spin ffmpeg in a tight loop.
                stop_process(process)
                if frames_this_run == 0:
                    print(f"Error: ffmpeg produced no frames for {video_path}")
                    self.status = "Cannot play that file"
                    break

                stop_process(audio)
                process = start_video()
                audio = start_audio_process(video_path)
        finally:
            stop_process(process)
            stop_process(audio)
            gc.enable()

    def refresh_videos(self):
        self.videos = find_videos(self.video_dir)
        if self.selected > len(self.videos):
            self.selected = 0

    def run(self):
        try:
            self.refresh_videos()
            if not self.videos:
                self.render_message("No videos", f"Put a video in {os.path.basename(self.video_dir)}/")
                while self.running:
                    time.sleep(0.2)
                return

            last_drawn = None
            while self.running:
                state = (self.selected, self.status, len(self.videos))
                if state != last_drawn:
                    last_drawn = state
                    self.render_list()
                if self.activate:
                    self.activate = False
                    if self.selected == len(self.videos):
                        print("Back selected, releasing focus")
                        break
                    self.status = ""
                    self.mode = "playing"
                    self.play(self.videos[self.selected])
                    self.mode = "list"
                    # Drop anything queued while the video was on screen.
                    self.activate = False
                    self.stop_playback = False
                    last_drawn = None
                time.sleep(0.05)
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            self.running = False
            if hasattr(self.board, "release_focus"):
                self.board.release_focus()
            self.board.cleanup()
            print("Exit.")


def render_progress(board, width, height, percent, status_text="Downloading..."):
    try:
        image = Image.new("RGB", (width, height), (7, 11, 18))
        draw = ImageDraw.Draw(image)
        font = load_font(14)
        draw.text((20, height // 2 - 40), status_text, fill=(255, 255, 255), font=font)
        bar_w = width - 40
        bar_h = 14
        bar_x = 20
        bar_y = height // 2 - 8
        draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), outline=(100, 180, 255))
        if percent >= 0:
            fill_w = int(bar_w * percent / 100)
            if fill_w > 2:
                draw.rectangle((bar_x + 2, bar_y + 2, bar_x + fill_w - 2, bar_y + bar_h - 2), fill=(60, 140, 255))
            draw.text((bar_x + bar_w // 2 - 20, bar_y + bar_h + 6), f"{percent:.0f}%", fill=(200, 200, 200), font=font)
        else:
            draw.text((bar_x + bar_w // 2 - 30, bar_y + bar_h + 6), "Please wait...", fill=(200, 200, 200), font=font)
        board.draw_image(0, 0, width, height, image_to_rgb565(image))
    except Exception as e:
        print(f"Render progress error: {e}")


def download_video(url, dest_path, board, width, height):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    # Download to a temp file so an interrupted transfer can never leave a
    # truncated video sitting at dest_path looking like a good one.
    part_path = dest_path + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Whisplay/1.0"})
        response = urllib.request.urlopen(req, timeout=30)
        total_size = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        block_size = 8192
        with open(part_path, "wb") as f:
            while True:
                data = response.read(block_size)
                if not data:
                    break
                f.write(data)
                downloaded += len(data)
                if total_size > 0:
                    percent = downloaded / total_size * 100
                    render_progress(board, width, height, percent)
        if total_size > 0 and downloaded != total_size:
            raise IOError(f"incomplete download: got {downloaded} of {total_size} bytes")
        if not is_playable(part_path):
            raise IOError("downloaded file is not a playable video")
        os.replace(part_path, dest_path)
        render_progress(board, width, height, 100, "Download complete")
        return True
    except Exception as e:
        print(f"Download failed: {e}")
        try:
            os.unlink(part_path)
        except OSError:
            pass
        return False


if __name__ == "__main__":
    default_dir = os.path.join(current_dir, "data")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", "-d", default=default_dir, help="directory to scan for videos")
    parser.add_argument("--url", "-u", default=DEFAULT_VIDEO_URL)
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found in PATH.")
        sys.exit(1)

    app = VideoPlayerApp(args.dir)
    try:
        # Only reach out to the network when the folder has nothing playable.
        if not find_videos(args.dir) and args.url:
            print(f"No playable video found, downloading from {args.url}")
            render_progress(app.board, app.width, app.height, 0, "Downloading...")
            download_video(args.url, os.path.join(args.dir, DEFAULT_VIDEO_NAME),
                           app.board, app.width, app.height)
        app.run()
    except Exception as e:
        print(f"Error: {e}")
        try:
            app.board.cleanup()
        except Exception:
            pass
        sys.exit(1)
