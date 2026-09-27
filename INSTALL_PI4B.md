# Installing the AI Chatbot ("Jarvis") on a Raspberry Pi 4B

Step-by-step record of installing `whisplay-ai-chatbot` onto the Raspberry Pi 4
Model B, done on **2026-09-05**. This is the exact sequence that was run, including
the two non-obvious fixes (openwakeword version, wake-word phrase) that the stock
instructions don't warn you about.

## Target device

| | |
| --- | --- |
| Host | `meng@192.168.0.83` (SSH key auth) |
| Board | Raspberry Pi 4 Model B Rev 1.5, aarch64 |
| OS | Debian GNU/Linux 13 (trixie) |
| RAM / cores | 3.7 GiB / 4 |
| `sudo` | passwordless |
| Sound card | `card 3: whisplaysound` (Whisplay HAT, already probed) |

> The Pi Zero 2 W (`jarvis@192.168.0.33`) is a *different, older* device. Don't
> confuse the two — the 4B has far more RAM, so none of the Zero's OOM/tsc
> workarounds are needed here.

## What was already in place (prerequisites)

The 4B already had these done, so they are **not** repeated below:

- **Whisplay HAT driver** installed — `~/Whisplay`, sound card registered as
  `whisplaysound`, SPI/I2C/I2S enabled.
- **`whisplay-daemon.service`** installed and `active`. It owns the LCD, buttons
  and LED, and launches apps via its Unix socket `/tmp/whisplay-daemon.sock`.
- A clone of `~/ai-chatbot` (the combined repo), but at an **older commit** with
  no `.env`, no Node, and no build.

If you're starting from a bare Pi, do the driver + daemon first — follow
`Whisplay/README.md` (`sudo bash install_driver.sh` → reboot →
`sudo bash daemon/install_whisplay_daemon_service.sh`).

---

## Step 1 — Get the latest code onto the Pi

The Pi's checkout was behind and its `origin` is a **private** HTTPS GitHub repo
that can't authenticate over a non-interactive SSH session (`git pull` fails with
`could not read Username for 'https://github.com'`). The histories had also
diverged, so a fast-forward wasn't possible.

Instead the working tree was mirrored straight from the up-to-date local checkout
over SSH with `rsync`:

```bash
# run on the local machine that has ai-chatbot at the latest commit
rsync -az -e "ssh" /home/meng/ai-chatbot/ meng@192.168.0.83:/home/meng/ai-chatbot/
```

This brought the Pi to commit `7aacd1f`, which importantly includes
`4d8fc18 update fix the mic rec speaker for pi 4B` — a 4B-specific mic fix.

> Note: `--delete` was intentionally **not** used, to avoid removing anything on
> the Pi. The local checkout had no `node_modules`/`dist`, so nothing heavy was
> copied.

Verify:

```bash
ssh meng@192.168.0.83 'cd ~/ai-chatbot && git log --oneline -1'
# -> 7aacd1f Park DC low so it stops muting a stacked LoRa module
```

## Step 2 — Install dependencies

```bash
ssh meng@192.168.0.83
cd ~/ai-chatbot/whisplay-ai-chatbot
bash install_dependencies.sh
```

This installs (all confirmed working on the 4B):

- **apt packages**: `sox mpg123 libsox-fmt-mp3 ffmpeg`, Python system libs
  (`python3-lgpio`, `python3-numpy`, `python3-pillow`, `python3-opencv`, …),
  `patchelf`, etc. Also patches `libmad` execstack for MP3 support.
- **SPI** enabled via `raspi-config`.
- **Python deps** from `python/requirements.txt` (`--break-system-packages`).
- **Fonts / emoji**: `NotoSansSC-Bold.ttf` + `emoji_svg.zip`.
- **Node.js 20** — on aarch64 this goes through nvm; here it landed on
  `v20.20.2` (npm 10.8.2).
- **yarn** `1.22.22`, then `yarn install` (~110 s) + `patch-package`.
- **`whisplay` CLI** symlinked to `/usr/local/bin/whisplay`.

## Step 3 — Provide the `.env`

The chatbot needs `whisplay-ai-chatbot/.env` (holds API keys; not in git). For
this build it was **copied from the working Zero 2 W** and stack is:

```
ASR_SERVER=openai     # speech -> text  (OpenAI Whisper)
LLM_SERVER=anthropic  # the chat brain  (Claude)
TTS_SERVER=openai     # text  -> speech (OpenAI TTS)
WAKE_WORD_ENABLED=true
ALSA_INPUT_DEVICE=default   # shared (dsnoop) mic so wake-word + recorder coexist
```

How it was copied (relayed through the local machine, secret file shredded after):

```bash
# pull from the Zero 2 W, push to the 4B
ssh jarvis@192.168.0.33 'cat ~/whisplay-ai-chatbot/.env' > /tmp/z.env
cat /tmp/z.env | ssh meng@192.168.0.83 'cat > ~/ai-chatbot/whisplay-ai-chatbot/.env \
  && chmod 600 ~/ai-chatbot/whisplay-ai-chatbot/.env'
shred -u /tmp/z.env
```

You need at minimum an **Anthropic API key** (`ANTHROPIC_API_KEY`) and an
**OpenAI API key** (`OPENAI_API_KEY`) set inside it. Alternatively run the wizard:
`whisplay configure`.

## Step 4 — Build

```bash
cd ~/ai-chatbot/whisplay-ai-chatbot
bash build.sh
```

Run it as the normal user, not with `sudo` — Node is in the user's `~/.nvm`,
so root gets `npm: command not found`. (`build.sh` now re-runs itself as
`$SUDO_USER` if you do use sudo.)

`build.sh` runs `tsc` (→ `dist/index.js`) and then
`scripts/register-whisplay-daemon-app.js`, which registers the app with the
daemon. After this you should see:

```
[DaemonRegister] app registered to whisplay-daemon
```

and `~/.whisplay-daemon/app/whisplay-ai-chatbot.json` exists. The app now shows
up in the daemon launcher as **"AI Chatbot"**.

## Step 5 — Fix the wake word (two gotchas)

With `WAKE_WORD_ENABLED=true`, the first launch failed with
`No module named 'openwakeword'`, then — after a naive install — with
`No bundled model for 'jarvis'`. Two fixes were needed.

### 5a. Install the *right* openwakeword version

`openwakeword >= 0.5` depends on `tflite-runtime`, which has **no wheel for
Python 3.13** (the Pi runs 3.13.5), so `pip install openwakeword` fails. Pin to
the last version that works on 3.13, matching the Zero 2 W:

```bash
pip install --break-system-packages "openwakeword==0.4.0"
```

This also pulls `onnxruntime` (1.29.0) for the bundled `.onnx` models.

### 5b. Use a wake phrase that has a bundled model

The copied `.env` had `WAKE_WORDS=jarvis`, but openwakeword only ships a
**`hey_jarvis`** model — "jarvis" resolves to nothing and the listener exits.
Change it to the phrase that has a model:

```bash
sed -i 's/^WAKE_WORDS=jarvis/WAKE_WORDS=hey_jarvis/' \
  ~/ai-chatbot/whisplay-ai-chatbot/.env
```

The wake phrase is now **"hey jarvis"**. (The Zero 2 W has the same latent
`jarvis` misconfig — it just falls back to press-to-talk there.)

## Step 6 — Launch & verify

The daemon owns the screen, so the app is launched **through the daemon**, not by
running `run_chatbot.sh` directly (which self-disables when the daemon is active).
On the device you'd long-press to launch "AI Chatbot"; programmatically:

```bash
python3 - <<'PY'
import socket, json
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect("/tmp/whisplay-daemon.sock")
s.sendall((json.dumps({"cmd": "app.launch",
                       "payload": {"app_id": "whisplay-ai-chatbot"}}) + "\n").encode())
print(s.makefile("r").readline().strip())
PY
```

Logs stream to `~/ai-chatbot/whisplay-ai-chatbot/chatbot.log`
(`tail -f chatbot.log`). A healthy start shows:

```
Using sound card: whisplaysound
Current ASR Server: openai
Current LLM Server: anthropic
Current TTS Server: openai
[Plugin] Activated: Anthropic Claude LLM (llm:anthropic)
[Plugin] Activated: OpenAI ASR (asr:openai)
[Plugin] Activated: OpenAI TTS (tts:openai)
ChatBot started.
[WakeWord] Loading models: ['hey_jarvis_v0.1.onnx']
[WakeWord] READY
[LCD] Initialization finished: 240x280
```

**Final verified state (2026-09-05):** app running and foreground on the device;
processes `node dist/index.js`, `chatbot-ui.py`, and `wakeword.py` all alive;
"hey jarvis" wake word READY; proactive chat enabled (speaks every 120–300 s of
quiet). Press-and-hold the button to talk, or say **"hey jarvis"** hands-free.

---

## Operating notes

- **Restart the app cleanly** (children don't always get reaped on their own):
  ```bash
  pkill -f dist/index.js; pkill -f chatbot-ui.py; pkill -f wakeword.py
  # then re-launch via the daemon socket (Step 6)
  ```
  If a fresh launch misbehaves (blank screen, `ECONNREFUSED` on the local display
  socket, dead mic), suspect orphaned `chatbot-ui.py`/`wakeword.py` first.
- **Change settings**: edit `.env` (or `whisplay configure`), then restart the app.
- **Exit on the device**: 4 rapid button clicks (`exit_gesture: quad_click`).
- **Autostart on boot**: not set up. The daemon shows its launcher on boot; launch
  the chatbot from there. Don't run `startup.sh` while the daemon is installed —
  it deliberately refuses (the daemon manages apps instead of a standalone
  `chatbot.service`).
- **Update later**: `whisplay update` pulls + rebuilds — but note the private-repo
  auth caveat from Step 1; re-`rsync` from the local checkout if `git pull` can't
  authenticate.
