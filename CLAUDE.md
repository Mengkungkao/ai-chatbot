# ai-chatbot

The code is in `whisplay-ai-chatbot/`; its agent documentation is
`whisplay-ai-chatbot/AGENTS.md` -- read it first. `Whisplay/` is the
PiSugar Whisplay driver checkout: do not edit it here.

- It is an MFruit OS app: **follow `.claude/rules/mfruit-os-app.md`**.
- The Python UI (`whisplay-ai-chatbot/python/chatbot-ui.py`) draws MFruit
  OS's status bar and footer from the vendored SDK
  (`whisplay-ai-chatbot/python/mfruit_sdk/`, never edited here; change
  `~/MFruitOS/mfruitos/sdk` and run
  `~/MFruitOS/scripts/sdk-sync.sh ~/ai-chatbot/whisplay-ai-chatbot/python`).
- The keyboard goes through the SDK's input controller
  (`python/keyboard_input.py`); the button stays with the Node core
  (`src/device/display.ts`), which already follows MFruit OS's talk-screen
  gestures. See AGENTS.md, "MFruit OS app".
- Tests: `cd whisplay-ai-chatbot/python && python3 -m pytest -q test/test_keyboard_input.py`;
  TypeScript: `bash build.sh` (or `npx tsc --noEmit`).
