import os
import sys
import time
import signal
import subprocess
import numpy as np

try:
    from openwakeword.model import Model
except Exception as e:
    print(f"[WakeWord] Failed to import openwakeword: {e}", file=sys.stderr)
    sys.exit(1)


def parse_list(value: str):
    return [item.strip() for item in value.split(",") if item.strip()]


def bundled_model_dir():
    """Where openwakeword keeps the pretrained .onnx models it ships with."""
    import openwakeword

    return os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")


def resolve_model_paths(wake_words):
    """Map wake word names onto the bundled model files.

    openwakeword 0.4.0 takes file paths rather than model names, and it is the
    newest release installable on Python 3.13 (0.5+ needs tflite-runtime, which
    has no wheel for it). Names like "hey_jarvis" therefore have to be resolved
    to "<pkg>/resources/models/hey_jarvis_v0.1.onnx" ourselves.
    """
    directory = bundled_model_dir()
    if not os.path.isdir(directory):
        return []
    available = sorted(f for f in os.listdir(directory) if f.endswith(".onnx"))
    paths = []
    for name in wake_words:
        stem = name[:-5] if name.endswith(".onnx") else name
        match = next(
            (f for f in available if f == f"{stem}.onnx" or f.startswith(f"{stem}_v")),
            None,
        )
        if match:
            paths.append(os.path.join(directory, match))
        else:
            usable = [
                f.split("_v")[0]
                for f in available
                if f not in ("embedding_model.onnx", "melspectrogram.onnx", "silero_vad.onnx")
            ]
            print(
                f"[WakeWord] No bundled model for '{name}'. Available: {sorted(set(usable))}",
                file=sys.stderr,
            )
    return paths


def load_model(wake_words, model_paths):
    """Build the Model across openwakeword API versions.

    0.5+ accepts `wakeword_models`; 0.4.0 accepts `wakeword_model_paths` and
    needs real file paths.
    """
    explicit = list(model_paths)
    try:
        return Model(wakeword_models=explicit or wake_words)
    except TypeError:
        pass  # older signature, fall through
    except Exception as error:
        print(f"[WakeWord] Failed to initialize model: {error}", file=sys.stderr)
        return None

    paths = explicit or resolve_model_paths(wake_words)
    if not paths:
        print("[WakeWord] No usable wake word models found.", file=sys.stderr)
        return None
    try:
        print(f"[WakeWord] Loading models: {[os.path.basename(p) for p in paths]}")
        return Model(wakeword_model_paths=paths)
    except Exception as error:
        print(f"[WakeWord] Failed to initialize model: {error}", file=sys.stderr)
        return None


def main():
    wake_words = parse_list(os.getenv("WAKE_WORDS", ""))
    model_paths = parse_list(os.getenv("WAKE_WORD_MODEL_PATHS", ""))
    threshold = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
    cooldown_sec = float(os.getenv("WAKE_WORD_COOLDOWN_SEC", "1.5"))

    if not wake_words and not model_paths:
        wake_words = ["hey_jarvis"]
        
    print(f"[WakeWord] Using wake words: {wake_words}")

    model = load_model(wake_words, model_paths)
    if model is None:
        sys.exit(1)

    sox_cmd = [
        "sox",
        "-t",
        "alsa",
        "default",
        "-r",
        "16000",
        "-b",
        "16",
        "-e",
        "signed-integer",
        "-c",
        "1",
        "-t",
        "raw",
        "-",
    ]

    process = subprocess.Popen(
        sox_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def cleanup(*_):
        try:
            process.terminate()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    last_trigger = 0.0
    chunk_samples = 1280
    chunk_bytes = chunk_samples * 2

    print("[WakeWord] READY", flush=True)

    while True:
        if process.stdout is None:
            time.sleep(0.1)
            continue
        data = process.stdout.read(chunk_bytes)
        if not data or len(data) < chunk_bytes:
            time.sleep(0.01)
            continue

        audio = np.frombuffer(data, dtype=np.int16)
        try:
            prediction = model.predict(audio)
        except Exception:
            continue

        now = time.time()
        if now - last_trigger < cooldown_sec:
            continue

        for keyword, score in prediction.items():
            if score >= threshold:
                last_trigger = now
                print(f"WAKE {keyword} {score:.3f}", flush=True)
                break


if __name__ == "__main__":
    main()
