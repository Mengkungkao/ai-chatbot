import { spawn } from "child_process";
import { readFile } from "fs/promises";
import type { AudioFormat } from "../plugin";
import { TTSResult } from "../type";

/**
 * The loudness of a TTS clip over time, for lip sync: one value from 0 to 100
 * per SPEECH_FRAME_MS of audio. The face opens its mouth on the loud frames and
 * shuts it on the quiet ones, so it moves with the words actually being played
 * rather than with a timer.
 *
 * WAV is read here; anything else (OpenAI's mp3) is decoded by sox, which the
 * player already needs, to 8 kHz mono. That takes ~70 ms for a 5 s clip on a
 * Pi Zero 2 W, in a child process, so the event loop never waits for it.
 */

export const SPEECH_FRAME_MS = 20;
const DECODE_RATE = 8000;
const DECODE_TIMEOUT_MS = 4000;
// Frames this far below the clip's loud parts count as closed-mouth silence.
const GATE_RANGE_DB = 24;
// A clip whose loud parts are quieter than this (about -55 dBFS) is silence.
const SILENCE_RMS = 60;
// Syllables. Running speech barely dips between syllables (2-4 dB), so
// loudness alone holds the mouth half open through a whole phrase. Each frame
// is also compared with its neighbourhood (±SYLLABLE_SPAN frames): louder than
// its surroundings opens the mouth further, quieter closes it, CONTRAST_DB
// per step. Tuned on OpenAI tts-1 "nova" clips to ~3.3 open-and-close swings
// a second, about the syllable rate, from ~2 with loudness alone.
const SYLLABLE_SPAN = 7;
const CONTRAST_DB = 8;
const CONTRAST_BASE = 0.55;

type Pcm = { samples: Int16Array; sampleRate: number };

/** Mouth openness per frame, 0..100, from the clip's own loudness. */
export const envelopeFromPcm = (
  samples: ArrayLike<number>,
  sampleRate: number,
  frameMs: number = SPEECH_FRAME_MS,
): number[] => {
  const frame = Math.max(1, Math.round((sampleRate * frameMs) / 1000));
  const rms: number[] = [];
  for (let i = 0; i < samples.length; i += frame) {
    const end = Math.min(samples.length, i + frame);
    let sum = 0;
    for (let j = i; j < end; j++) sum += samples[j] * samples[j];
    rms.push(Math.sqrt(sum / (end - i)));
  }
  // The 95th percentile, not the peak, sets the scale: one click or plosive
  // should not make every other syllable look like a whisper.
  const voiced = rms.filter((v) => v > 0).sort((a, b) => a - b);
  const ref = voiced.length
    ? voiced[Math.min(voiced.length - 1, Math.floor(voiced.length * 0.95))]
    : 0;
  if (ref < SILENCE_RMS) return rms.map(() => 0);
  const db = rms.map((v) =>
    Math.max(-GATE_RANGE_DB, v > 0 ? 20 * Math.log10(v / ref) : -GATE_RANGE_DB),
  );
  return db.map((d, i) => {
    const from = Math.max(0, i - SYLLABLE_SPAN);
    const to = Math.min(db.length - 1, i + SYLLABLE_SPAN);
    let sum = 0;
    for (let j = from; j <= to; j++) sum += db[j];
    const around = sum / (to - from + 1);
    const gate = Math.max(0, Math.min(1, 1 + d / GATE_RANGE_DB));
    const syllable = Math.max(0, Math.min(1, CONTRAST_BASE + (d - around) / CONTRAST_DB));
    return Math.round(gate * syllable * 100);
  });
};

/** First channel of a PCM WAV, or null for anything this does not read. */
export const pcmFromWav = (buf: Buffer): Pcm | null => {
  if (
    buf.length < 12 ||
    buf.toString("ascii", 0, 4) !== "RIFF" ||
    buf.toString("ascii", 8, 12) !== "WAVE"
  ) {
    return null;
  }
  let fmt: { format: number; channels: number; rate: number; bits: number } | null = null;
  let offset = 12;
  while (offset + 8 <= buf.length) {
    const id = buf.toString("ascii", offset, offset + 4);
    let size = buf.readUInt32LE(offset + 4);
    const body = offset + 8;
    if (id === "fmt " && body + 16 <= buf.length) {
      fmt = {
        format: buf.readUInt16LE(body),
        channels: buf.readUInt16LE(body + 2),
        rate: buf.readUInt32LE(body + 4),
        bits: buf.readUInt16LE(body + 14),
      };
    } else if (id === "data") {
      if (!fmt || fmt.channels < 1 || fmt.rate <= 0) return null;
      // Streaming writers (piper among them) leave the size as 0 or ~0.
      if (size === 0 || body + size > buf.length) size = buf.length - body;
      const width = fmt.bits / 8;
      const stride = width * fmt.channels;
      const count = Math.floor(size / stride);
      const samples = new Int16Array(count);
      for (let i = 0; i < count; i++) {
        const at = body + i * stride;
        if (fmt.format === 1 && fmt.bits === 16) samples[i] = buf.readInt16LE(at);
        else if (fmt.format === 1 && fmt.bits === 8) samples[i] = (buf[at] - 128) << 8;
        else if (fmt.format === 1 && fmt.bits === 32) samples[i] = buf.readInt32LE(at) >> 16;
        else if (fmt.format === 3 && fmt.bits === 32) {
          samples[i] = Math.max(-32768, Math.min(32767, Math.round(buf.readFloatLE(at) * 32767)));
        } else return null;
      }
      return { samples, sampleRate: fmt.rate };
    }
    offset = body + size + (size & 1);
  }
  return null;
};

/** Decode any clip sox can read to 8 kHz mono; null if sox fails. */
const decodeWithSox = (input: { path?: string; buffer?: Buffer; type: string }): Promise<Pcm | null> =>
  new Promise((resolve) => {
    const source = input.path ? [input.path] : ["-t", input.type, "-"];
    const child = spawn("sox", [
      "-q", ...source,
      "-t", "raw", "-r", `${DECODE_RATE}`, "-c", "1", "-b", "16", "-e", "signed-integer", "-",
    ]);
    const chunks: Buffer[] = [];
    let settled = false;
    const finish = (pcm: Pcm | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(pcm);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish(null);
    }, DECODE_TIMEOUT_MS);
    child.stdout.on("data", (chunk: Buffer) => chunks.push(chunk));
    child.on("error", () => finish(null));
    child.on("close", (code) => {
      if (code !== 0) return finish(null);
      const raw = Buffer.concat(chunks);
      const samples = new Int16Array(Math.floor(raw.length / 2));
      for (let i = 0; i < samples.length; i++) samples[i] = raw.readInt16LE(i * 2);
      finish({ samples, sampleRate: DECODE_RATE });
    });
    child.stdin.on("error", () => {});
    if (input.buffer) child.stdin.end(input.buffer);
    else child.stdin.end();
  });

const loadPcm = async (params: TTSResult, format: AudioFormat): Promise<Pcm | null> => {
  if (params.filePath) {
    if (/\.wav$/i.test(params.filePath)) {
      const pcm = pcmFromWav(await readFile(params.filePath));
      if (pcm) return pcm;
    }
    return decodeWithSox({ path: params.filePath, type: format });
  }
  const buffer = params.base64 ? Buffer.from(params.base64, "base64") : params.buffer;
  if (!buffer) return null;
  if (format === "wav") {
    const pcm = pcmFromWav(buffer);
    if (pcm) return pcm;
  }
  return decodeWithSox({ buffer, type: format });
};

const pending = new WeakMap<TTSResult, Promise<number[] | null>>();
const ready = new WeakMap<TTSResult, number[] | null>();

/**
 * The clip's envelope, worked out once per clip. Calling it as soon as a clip
 * is synthesised means it is usually ready before the clip is played.
 */
export const speechEnvelope = (
  params: TTSResult,
  format: AudioFormat,
): Promise<number[] | null> => {
  let job = pending.get(params);
  if (!job) {
    job = loadPcm(params, format)
      .then((pcm) => (pcm ? envelopeFromPcm(pcm.samples, pcm.sampleRate) : null))
      .catch((error) => {
        console.warn("[Speech] Could not read the clip's loudness:", error?.message || error);
        return null;
      })
      .then((envelope) => {
        ready.set(params, envelope);
        return envelope;
      });
    pending.set(params, job);
  }
  return job;
};

/** The envelope if it is already known; undefined while it is still being made. */
export const readySpeechEnvelope = (params: TTSResult): number[] | null | undefined =>
  ready.has(params) ? ready.get(params) : undefined;
