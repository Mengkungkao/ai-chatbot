// Regression test: a recorder that ignores SIGINT must still be stopped, and
// the next recording must not start until it has let go of the microphone.
//
// sox ignores a SIGINT that arrives while it is still opening the capture
// device (about 50 ms to 1 s after it starts, measured on an Orange Pi Zero
// 2W). A quick button release sent exactly that, so sox kept recording and
// held the device; every later press failed with "Device or resource busy".
// The fake sox below ignores SIGINT for its whole life and logs when it starts
// and exits.
//
// Run against the built output:  node scripts/test-recorder-stop.js
// Expect PASS. With SIGINT as the only stop signal (the old behaviour) it
// fails: the fake sox is still alive.
const fs = require("fs");
const os = require("os");
const path = require("path");

const work = fs.mkdtempSync(path.join(os.tmpdir(), "recorder-stop-"));
const log = path.join(work, "sox.log");
fs.writeFileSync(
  path.join(work, "sox"),
  `#!/bin/bash
echo "start $$" >> "${log}"
trap '' INT
trap 'echo "exit $$" >> "${log}"; exit 0' TERM
while true; do sleep 0.05; done
`,
  { mode: 0o755 },
);
process.env.PATH = `${work}:${process.env.PATH}`;
process.env.ASR_SERVER = process.env.ASR_SERVER || "test";
process.env.TTS_SERVER = process.env.TTS_SERVER || "test";

const { recordAudioManually } = require(path.resolve(__dirname, "..", "dist", "device", "audio.js"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const events = () =>
  (fs.existsSync(log) ? fs.readFileSync(log, "utf8") : "").trim().split("\n").filter(Boolean);

(async () => {
  let failed = false;
  const first = recordAudioManually(path.join(work, "a.mp3"));
  await sleep(200);           // inside the window where real sox drops SIGINT
  first.stop();
  const second = recordAudioManually(path.join(work, "b.mp3"));   // the next press
  const firstDone = await Promise.race([first.result.then(() => true), sleep(4000).then(() => false)]);
  await sleep(300);
  second.stop();
  await Promise.race([second.result, sleep(4000)]);
  await sleep(300);

  const lines = events();
  console.log(lines.join("\n"));
  const starts = lines.filter((l) => l.startsWith("start"));
  const exits = lines.filter((l) => l.startsWith("exit"));
  const check = (name, ok) => {
    console.log(`${ok ? "ok  " : "FAIL"} ${name}`);
    failed ||= !ok;
  };
  check("the first recorder exited after stop()", firstDone && exits.length >= 1);
  check("the second recorder started only after the first exited",
    starts.length < 2 || lines.indexOf(exits[0]) < lines.indexOf(starts[1]));
  check("no recorder left running", starts.length === exits.length);
  for (const l of starts) {
    try { process.kill(+l.split(" ")[1], "SIGKILL"); } catch {}
  }
  fs.rmSync(work, { recursive: true, force: true });
  console.log(failed ? "FAIL" : "PASS");
  process.exit(failed ? 1 : 0);
})();
