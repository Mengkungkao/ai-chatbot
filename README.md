# ai-chatbot — Jarvis on Whisplay

A pocket AI companion built on a Raspberry Pi Zero 2 W with a PiSugar Whisplay HAT
(LCD, speaker, mic). This repo is a personal workspace combining two upstream
PiSugar projects with a set of custom changes that turn the stock chatbot demo
into a wake-word-driven companion nicknamed "Jarvis."

## Repo layout

- **[Whisplay/](Whisplay/)** — the Whisplay HAT driver, on-device daemon
  (`daemon/whisplay_daemon.py`) and its app framework. The daemon owns the LCD,
  buttons, LED, and a Unix-socket JSON-RPC protocol (`/tmp/whisplay-daemon.sock`)
  that apps use to register, request foreground, and draw to the screen.
- **[whisplay-ai-chatbot/](whisplay-ai-chatbot/)** — the AI chatbot app itself
  (Node/TypeScript core + Python UI/audio layer), registered with the daemon as
  one of its launchable apps.

Both are normal upstream PiSugar projects (see their own READMEs for full
install docs); this repo layers the customizations described below on top and
is deployed straight to the Pi over SSH.

## What's customized here

**Persona & proactive behavior**
- Flirty, talkative persona with "her own thoughts" (`src/config/llm-config.ts`)
- Speaks unprompted on a randomized idle timer (`src/core/proactive-chat.ts`),
  not just in response to being spoken to
- Triple-press the hardware button to toggle auto-talk on/off, with a live LED
  indicator in the status bar (`python/status-bar-icon/autotalk_icon.py`)

**Wake word ("hey jarvis")**
- Hands-free wake word via openwakeword (`python/wakeword.py`), sharing the mic
  with the chatbot's own recorder through a dsnoop ALSA device so both can
  listen at once
- Short wake chime instead of a long tone sequence, with a settle delay so the
  chime itself is never mistaken for speech
- Speech-onset detection (`recordAwaitingSpeech` in `src/device/audio.ts`) so
  "Listening…" doesn't sit and wait forever if nobody follows up — it gives up
  and quietly returns to waiting for the wake word instead of nagging
- Dynamic voice-detection threshold that calibrates to ambient room noise
  (`src/device/voice-detect.ts`)

**LLM / voice pipeline**
- Anthropic Claude integration (`src/cloud-api/anthropic/`), model-generation-aware
  thinking/effort config, correct context-window sizing per model
- ASR language pinning and hallucination filtering (`src/utils/asr-filter.ts`)
  so quiet/short audio doesn't get mistranscribed in the wrong script
- TTS sentence-splitting tuned to avoid choppy, unnatural playback breaks

**Display / UI**
- Procedural animated boot sequence (`python/boot_animation.py`) — HUD-style
  spinning rings and center text, drawn frame-by-frame instead of a static logo
- Word-aware text wrapping, emoji status glyphs, centered text, and a face-render
  cache that cut idle UI CPU usage substantially
- Daemon home screen retitled "Home"; the "Run Test" demo app removed from the
  launcher

**Whisplay daemon / example apps**
- `Whisplay/example/play_mp4.py` rewritten: atomic downloads, no infinite
  restart loop on bad video, correct playback speed
- Procedural "Happy Birthday" video generator (`make_birthday_video.py`) with a
  synthesized melody, no external assets

## Building & deploying

Follow **[whisplay-ai-chatbot/README.md](whisplay-ai-chatbot/README.md)** for
the full install/build/run steps (drivers, `.env` setup, `build.sh`,
`run_chatbot.sh`). A few things specific to this deployment:

- The Pi Zero 2 W has very little RAM, so `bash build.sh` alone was OOM-killing
  `tsc`. The `build` script in `package.json` now runs TypeScript with
  `NODE_OPTIONS=--max-old-space-size=1024` for exactly this reason — don't
  strip that out when touching the build script.
- The app is launched/relaunched through the daemon's Unix socket
  (`app.launch` / `app.list` on `/tmp/whisplay-daemon.sock`), not by running
  `node dist/index.js` directly.
- If the app crashes, its Python children (`chatbot-ui.py`, `wakeword.py`)
  don't always get cleaned up reliably and can survive as orphans holding the
  mic or the display socket port. If a fresh launch behaves strangely (blank
  screen, `ECONNREFUSED` on the local display socket, mic seemingly dead),
  check for and kill orphaned `chatbot-ui.py`/`wakeword.py` processes before
  assuming it's a config problem.

## Configuration notes

`.env` (Pi-only, not committed) drives most of the above. Beyond the template's
defaults, this build relies on:

| Variable | Purpose |
| --- | --- |
| `LLM_SERVER=anthropic`, `ANTHROPIC_LLM_MODEL` | Claude as the chat backend |
| `WAKE_WORD_ENABLED`, `WAKE_WORDS`, `WAKE_WORD_THRESHOLD` | Wake-word listener |
| `PROACTIVE_CHAT_ENABLED`, `PROACTIVE_CHAT_MIN_IDLE_SEC` / `MAX` | Unprompted speech timer |
| `ALSA_INPUT_DEVICE=default` | Shared (dsnoop) mic device so wake-word + recorder can coexist |
| `VOICE_DETECT_LEVEL`, `VOICE_DETECT_LEVEL_MAX`, `VOICE_DETECT_SMOOTHING` | Voice-onset sensitivity tuning — keep the ceiling capped low or the auto-calibration drifts too high to reliably catch speech |
| `WAKE_SPEECH_START_SEC` | How long to wait for speech to start after the wake chime before giving up |
| `OPENAI_ASR_LANGUAGE` | Pins ASR language to avoid misdetection on quiet audio |
| `BOOT_ANIM_TEXT` | Word(s) shown in the center of the boot animation |

## License

Both upstream projects are GPL-3.0; see [Whisplay/LICENSE](Whisplay/LICENSE)
and [whisplay-ai-chatbot's license notice](whisplay-ai-chatbot/README.md#license).
