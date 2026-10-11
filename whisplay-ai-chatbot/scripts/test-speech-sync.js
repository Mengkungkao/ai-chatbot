// Lip sync from the Node side: the loudness envelope of a clip, and the
// start / envelope / end events the face moves its mouth from.
//
// The mouth must only move while a clip is actually playing, so "end" has to
// follow every "start" (also when the clip is cut off), and nothing may arrive
// for a clip after its "end". The fake sox below plays for 400 ms and dies on
// SIGTERM like the real one; decoding goes to the real sox after 300 ms, as a
// slow board would, so an envelope can arrive after its clip was cut off.
//
// Run against the built output:  node scripts/test-speech-sync.js
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const realSox = execFileSync("sh", ["-c", "command -v sox"]).toString().trim();
const work = fs.mkdtempSync(path.join(os.tmpdir(), "speech-sync-"));
fs.writeFileSync(
  path.join(work, "sox"),
  `#!/bin/bash
for a in "$@"; do
  if [ "$a" = alsa ]; then
    cat > /dev/null
    trap 'exit 143' TERM
    sleep 0.4 & wait $!
    exit 0
  fi
done
sleep 0.3
exec "${realSox}" "$@"
`,
  { mode: 0o755 },
);
process.env.PATH = `${work}:${process.env.PATH}`;
process.env.ASR_SERVER = process.env.ASR_SERVER || "test";
process.env.TTS_SERVER = "piper";            // a WAV voice: buffers are WAV

const dist = path.resolve(__dirname, "..", "dist", "device");
const { envelopeFromPcm, pcmFromWav, speechEnvelope } = require(path.join(dist, "speech-envelope.js"));
const audio = require(path.join(dist, "audio.js"));

let failed = false;
const check = (name, ok, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${ok || !detail ? "" : `: ${detail}`}`);
  failed ||= !ok;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const RATE = 8000;
// 300 ms loud, 200 ms silent, 300 ms 12 dB quieter, 200 ms at -40 dB
const tone = (ms, amp) =>
  Array.from({ length: (RATE * ms) / 1000 }, (_, i) => Math.round(amp * Math.sin((2 * Math.PI * 220 * i) / RATE)));
const signal = [...tone(300, 16000), ...tone(200, 0), ...tone(300, 4000), ...tone(200, 160)];

const wav = (samples, { rate = RATE, streamed = false } = {}) => {
  const data = Buffer.alloc(samples.length * 2);
  samples.forEach((v, i) => data.writeInt16LE(v, i * 2));
  const head = Buffer.alloc(44);
  head.write("RIFF", 0);
  head.writeUInt32LE(streamed ? 0xffffffff : 36 + data.length, 4);
  head.write("WAVEfmt ", 8);
  head.writeUInt32LE(16, 16);
  head.writeUInt16LE(1, 20);
  head.writeUInt16LE(1, 22);
  head.writeUInt32LE(rate, 24);
  head.writeUInt32LE(rate * 2, 28);
  head.writeUInt16LE(2, 32);
  head.writeUInt16LE(16, 34);
  head.write("data", 36);
  head.writeUInt32LE(streamed ? 0 : data.length, 40);
  return Buffer.concat([head, data]);
};

const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;

(async () => {
  // -- the envelope ---------------------------------------------------------
  const env = envelopeFromPcm(signal, RATE);
  check("one value per 20 ms", env.length === 50, `${env.length}`);
  const loud = mean(env.slice(2, 13));
  const gap = env.slice(16, 25);
  const quiet = mean(env.slice(28, 38));
  const faint = env.slice(42, 50);
  check("loud speech opens the mouth", loud >= 55, `${loud}`);
  check("silence between words shuts it", Math.max(...gap) === 0, gap.join(","));
  check("quieter speech opens it less", quiet > 5 && quiet < loud, `${quiet} vs ${loud}`);
  check("near-silence shuts it", Math.max(...faint) === 0, faint.join(","));
  check("a silent clip stays shut", Math.max(...envelopeFromPcm(tone(500, 20), RATE)) === 0);

  const parsed = pcmFromWav(wav(signal));
  check("WAV is read in-process",
    parsed && parsed.sampleRate === RATE && parsed.samples.length === signal.length &&
    parsed.samples[123] === signal[123]);
  const streamedWav = pcmFromWav(wav(signal, { streamed: true }));
  check("a streamed WAV (no sizes) is read too", streamedWav && streamedWav.samples.length === signal.length);
  check("not a WAV is left to sox", pcmFromWav(Buffer.from("ID3 not a wav at all")) === null);

  // sox decodes anything else; FLAC stands in for mp3 here (same code path)
  const flac = path.join(work, "clip.flac");
  fs.writeFileSync(path.join(work, "clip.wav"), wav(signal));
  execFileSync(realSox, [path.join(work, "clip.wav"), flac]);
  const decoded = await speechEnvelope({ filePath: flac, duration: 1000 }, "mp3");
  check("sox-decoded clips get the same envelope",
    decoded && decoded.length === env.length && decoded.every((v, i) => Math.abs(v - env[i]) <= 3),
    JSON.stringify(decoded));

  // -- the events -----------------------------------------------------------
  const events = [];
  audio.onSpeech((e) => events.push({ ...e, at: Date.now() }));
  const clip = () => ({ buffer: wav(signal), duration: 1000 });

  // prepared ahead (as ChatFlow does on synthesis): the envelope rides on start
  const ready = clip();
  audio.prepareSpeech(ready);
  await sleep(200);
  const handedOver = Date.now();
  await audio.playAudioData(ready);
  let mine = events.splice(0);
  check("start says when the clip went to the player",
    typeof mine[0]?.at === "number" && Math.abs(mine[0].at - handedOver) < 50,
    `${mine[0]?.at} vs ${handedOver}`);
  check("a prepared clip starts with its envelope, then ends",
    mine.length === 2 && mine[0].state === "start" && mine[0].envelope?.length === 50 &&
    mine[1].state === "end" && mine[1].id === mine[0].id,
    JSON.stringify(mine.map((e) => e.state)));

  // not prepared: start goes out at once, the envelope follows before the end
  await audio.playAudioData(clip());
  mine = events.splice(0);
  check("an unprepared clip gets its envelope while it plays",
    mine.map((e) => e.state).join(",") === "start,envelope,end" &&
    !mine[0].envelope && mine[1].envelope.length === 50 && mine.every((e) => e.id === mine[0].id),
    JSON.stringify(mine.map((e) => e.state)));

  // cut off by the button: the end must come promptly, and nothing after it,
  // not even the envelope sox is still working out (24-bit: not read here)
  execFileSync(realSox, [path.join(work, "clip.wav"), "-b", "24", path.join(work, "clip24.wav")]);
  const cut = audio.playAudioData({ buffer: fs.readFileSync(path.join(work, "clip24.wav")), duration: 1000 });
  await sleep(100);
  const stoppedAt = Date.now();
  audio.stopPlaying();
  await cut.catch(() => {});
  await sleep(600);
  mine = events.splice(0);
  const end = mine.find((e) => e.state === "end");
  check("a clip cut off still ends, at once", end && end.at - stoppedAt < 150,
    end ? `${end.at - stoppedAt} ms` : "no end");
  check("nothing follows a clip's end", end && mine.indexOf(end) === mine.length - 1,
    JSON.stringify(mine.map((e) => e.state)));

  await audio.playAudioData({ duration: 0 });
  check("an empty clip says nothing", events.length === 0, JSON.stringify(events));

  fs.rmSync(work, { recursive: true, force: true });
  console.log(failed ? "FAIL" : "PASS");
  process.exit(failed ? 1 : 0);
})();
