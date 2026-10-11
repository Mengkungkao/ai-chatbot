# Face lip-sync measurements (on the board)

Tools used to tune `WHISPLAY_FACE_SYNC_MS` and the speech envelope on a Pi
Zero 2 W with the Whisplay HAT (2026-10-11). They run on the board, need the
HAT's speaker and microphone (`hw:whisplaysound,0`, right channel), and are not
part of the app package.

| Script | What it measures | Needs |
|---|---|---|
| `latency_probe.py` | delay from spawning the app's mp3 player (sox) to the sound at the mic | AI Chatbot closed (the mic is exclusive) |
| `syncprobe.py APP_DIR [send_at]` | plays tone bursts and two TTS clips the way the app does, sends the app's UI the same `speech` messages, reports how far the mouth in the app framebuffer leads (-) or lags (+) the voice | AI Chatbot open and idle; `/tmp/tts-sample-0.mp3` and `-1.mp3` (any speech mp3s) |
| `facecap.py OUT [wait_s]` | waits for the chatbot to speak on its own (proactive chat), records framebuffer mouth pixels and the mic on one clock | AI Chatbot open, proactive chat on |
| `analyse.py OUT` (dev machine) | lag, mouth open in silence, contact sheet and GIF from a `facecap.py` capture | Pillow |

The framebuffer read is the app's (`/tmp/whisplay-fb-whisplay-ai-chatbot-*.bin`),
not the panel: whisplay-daemon copies it to the LCD afterwards (at most 20
frames a second), which these tools cannot see.
