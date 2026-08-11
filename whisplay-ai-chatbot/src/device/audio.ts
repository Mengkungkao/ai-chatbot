import { spawn, ChildProcess } from "child_process";
import { readFileSync, statSync } from "fs";
import { isEmpty, noop, set } from "lodash";
import dotenv from "dotenv";
import { ttsServer, asrServer } from "../cloud-api/server";
import { pluginRegistry } from "../plugin";
import type { ASRPlugin, TTSPlugin, AudioFormat } from "../plugin";
import { ASRServer, TTSResult, TTSServer } from "../type";
import { webAudioBridge } from "./web-audio-bridge";

export { getDynamicVoiceDetectLevel } from "./voice-detect";

dotenv.config();

const detectWhisplaySoundCardRef = (): string | undefined => {
  try {
    const cards = readFileSync("/proc/asound/cards", "utf8");
    const line = cards
      .split("\n")
      .find((item) => /whisplaysound|wm8960soundcard|es8389soundcard/i.test(item));
    const nameMatch = line?.match(/\[([^\]]+)\]/);
    if (nameMatch?.[1]) {
      return nameMatch[1].trim();
    }
    const indexMatch = line?.match(/^\s*(\d+)\s+\[/);
    return indexMatch?.[1];
  } catch (e) {
    return undefined;
  }
};

const soundCardRef =
  process.env.SOUND_CARD_NAME ||
  process.env.SOUND_CARD_INDEX ||
  detectWhisplaySoundCardRef();
const defaultAlsaInputDevice = soundCardRef ? `hw:${soundCardRef},0` : "default";
const defaultAlsaOutputDevice = soundCardRef === "whisplaysound"
  ? "playback"
  : soundCardRef
    ? `plughw:${soundCardRef},0`
    : "default";
const alsaInputDevice = process.env.ALSA_INPUT_DEVICE || defaultAlsaInputDevice;
const alsaOutputDevice = process.env.ALSA_OUTPUT_DEVICE || defaultAlsaOutputDevice;
const normalizeAudioFormat = (value: string | undefined, fallback: AudioFormat): AudioFormat => {
  const normalized = (value || "").toLowerCase();
  return normalized === "wav" || normalized === "mp3" ? normalized : fallback;
};

const defaultTtsAudioFormat: AudioFormat = [TTSServer.gemini, TTSServer.piper].includes(ttsServer)
  ? "wav"
  : "mp3";

const selectedTtsPlugin = pluginRegistry.getPlugin("tts", ttsServer) as TTSPlugin | undefined;
const ttsAudioFormat: AudioFormat = normalizeAudioFormat(
  selectedTtsPlugin?.audioFormat,
  defaultTtsAudioFormat,
);

const useWavPlayer = ttsAudioFormat === "wav";
const MP3_SOX_GAIN_DB = "2";

const defaultAsrAudioFormat: AudioFormat = [
  ASRServer.vosk,
  ASRServer.whisper,
  ASRServer.whisperhttp,
  ASRServer.fasterwhisper,
  ASRServer.llm8850whisper,
].includes(asrServer)
  ? "wav"
  : "mp3";

const selectedAsrPlugin = pluginRegistry.getPlugin("asr", asrServer) as ASRPlugin | undefined;

export const recordFileFormat: AudioFormat = normalizeAudioFormat(
  selectedAsrPlugin?.audioFormat,
  defaultAsrAudioFormat,
);

function startPlayerProcess() {
  return null;
}

let recordingProcessList: ChildProcess[] = [];
let currentRecordingReject: (reason?: any) => void = noop;

const removeRecordingProcess = (child: ChildProcess): void => {
  recordingProcessList = recordingProcessList.filter((item) => item !== child);
};

const killRecordingProcess = (child: ChildProcess): void => {
  console.log("Killing recording process", child.pid);
  try {
    child.kill("SIGINT");
  } catch (e) { }
  removeRecordingProcess(child);
};

const killAllRecordingProcesses = (): void => {
  recordingProcessList.forEach((child) => {
    killRecordingProcess(child);
  });
  recordingProcessList.length = 0;
};

// Length of the wake blip in seconds. Short enough to be a tick rather than a
// jingle, so listening can start almost immediately.
const CHIME_SECONDS = process.env.WAKE_CHIME_SECONDS || "0.06";

export const playWakeupChime = (): Promise<void> => {
  return new Promise((resolve) => {
    let finished = false;
    const done = () => {
      if (finished) {
        return;
      }
      finished = true;
      resolve();
    };

    //     play -n \
    // synth 0.10 sine 720 vol 0.4 : \
    // synth 0.12 sine 980 vol 0.35 : \
    // synth 0.14 sine 1320 vol 0.3 \
    // fade q 0.02 0.30 0.08 gain -30

    // One short blip rather than the old three-tone run. The chime is dead time
    // before she can hear you, and every millisecond of it also has to be kept
    // out of the recording.
    const chimeProcess = spawn("sox", [
      "-q",
      "-n",
      "-t",
      "alsa",
      alsaOutputDevice,
      "synth",
      CHIME_SECONDS,
      "sine",
      "1040",
      "vol",
      "0.35",
      "fade",
      "q",
      "0.005",
      CHIME_SECONDS,
      "0.02",
      "gain",
      "-30",
    ]);

    chimeProcess.on("error", done);
    chimeProcess.on("exit", done);

    // Safety net if sox never reports exit; well clear of the blip itself but
    // short enough that a stuck chime cannot stall listening for long.
    setTimeout(done, 600);
  });
};

const recordAudio = async (
  outputPath: string,
  duration: number = 10,
  voiceDetectLevel: number = 30,
): Promise<string> => {
  // Delegate to browser microphone when web audio is enabled and a client is connected.
  if (webAudioBridge.isAvailable()) {
    console.log(`[WebAudio] Starting browser recording, max ${duration} seconds...`);
    return webAudioBridge.startRecording(outputPath, duration);
  }

  return new Promise((resolve, reject) => {
    const args = [
      "-t",
      "alsa",
      alsaInputDevice,
      "-t",
      recordFileFormat,
      "-c",
      "1",
      "-r",
      "16000",
      outputPath,
      "silence",
      "1",
      "0.1",
      `${voiceDetectLevel}%`,
      "1",
      "0.7",
      `${voiceDetectLevel}%`,
    ];
    console.log(`Starting recording, maximum ${duration} seconds...`);
    currentRecordingReject = reject;
    const recordingProcess = spawn("sox", args);

    recordingProcess.on("error", (err) => {
      killAllRecordingProcesses();
      reject(err);
    });

    recordingProcess.stdout?.on("data", (data) => {
      console.log(data.toString());
    });
    recordingProcess.stderr?.on("data", (data) => {
      console.error(data.toString());
    });

    recordingProcess.on("exit", (code) => {
      removeRecordingProcess(recordingProcess);
      if (code && code !== 0) {
        reject(code);
        return;
      }
      resolve(outputPath);
    });
    recordingProcessList.push(recordingProcess);

    // Set a timeout to kill the recording process after the specified duration
    setTimeout(() => {
      if (recordingProcessList.includes(recordingProcess)) {
        killRecordingProcess(recordingProcess);
        resolve(outputPath);
      }
    }, duration * 1000);
  });
};

// Enough bytes on disk to mean sox got past its silence gate and is actually
// capturing. An aborted recording lands at a couple of hundred bytes.
const SPEECH_STARTED_BYTES = 1200;

/**
 * Record, but give up if the person never starts talking.
 *
 * sox's silence filter waits indefinitely for audio above the threshold, so a
 * wake that nobody follows up on sits on "Listening..." until the hard cap.
 * The output file only grows once capture begins, which is the cheapest signal
 * that speech has started. `maxSec` still bounds the whole utterance, so a long
 * sentence is never cut short.
 */
const recordAwaitingSpeech = async (
  outputPath: string,
  maxSec: number,
  voiceDetectLevel: number,
  startWithinSec: number,
): Promise<boolean> => {
  let started = false;
  const poll = setInterval(() => {
    try {
      if (statSync(outputPath).size > SPEECH_STARTED_BYTES) started = true;
    } catch {
      // File does not exist yet: nothing captured.
    }
  }, 150);
  const giveUp = setTimeout(() => {
    if (!started) {
      console.log(
        `[Record] No speech within ${startWithinSec}s, stopping.`,
      );
      stopRecording();
    }
  }, startWithinSec * 1000);

  try {
    await recordAudio(outputPath, maxSec, voiceDetectLevel);
  } catch {
    // stopRecording rejects the in-flight promise; treat as "nothing heard".
  } finally {
    clearInterval(poll);
    clearTimeout(giveUp);
  }

  try {
    started = started || statSync(outputPath).size > SPEECH_STARTED_BYTES;
  } catch {
    // leave as-is
  }
  return started;
};

const recordAudioManually = (
  outputPath: string
): { result: Promise<string>; stop: () => void } => {
  // Delegate to browser microphone when web audio is enabled and a client is connected.
  if (webAudioBridge.isAvailable()) {
    console.log(`[WebAudio] Starting manual browser recording...`);
    return webAudioBridge.startManualRecording(outputPath);
  }

  let stopFunc: () => void = noop;
  const result = new Promise<string>((resolve, reject) => {
    currentRecordingReject = reject;
    const recordingProcess = spawn("sox", [
      "-t",
      "alsa",
      alsaInputDevice,
      "-t",
      recordFileFormat,
      "-c",
      "1",
      "-r",
      "16000",
      outputPath,
    ]);

    recordingProcess.on("error", (err) => {
      removeRecordingProcess(recordingProcess);
      reject(err);
    });

    recordingProcess.stderr?.on("data", (data) => {
      console.error(data.toString());
    });
    recordingProcessList.push(recordingProcess);
    stopFunc = () => {
      killRecordingProcess(recordingProcess);
    };
    recordingProcess.on("exit", () => {
      removeRecordingProcess(recordingProcess);
      resolve(outputPath);
    });
  });
  return {
    result,
    stop: stopFunc,
  };
};

const stopRecording = (): void => {
  // Also stop any in-progress web recording.
  webAudioBridge.stopRecording();

  if (!isEmpty(recordingProcessList)) {
    killAllRecordingProcesses();
    try {
      currentRecordingReject();
    } catch (e) { }
    console.log("Recording stopped");
  } else {
    console.log("No recording process running");
  }
};

interface Player {
  isPlaying: boolean;
  process: ChildProcess | null;
}

const player: Player = {
  isPlaying: false,
  process: null,
};

setTimeout(() => {
  player.process = startPlayerProcess();
}, 5000);

const playAudioData = (params: TTSResult): Promise<void> => {
  // Delegate to browser speaker when web audio is enabled and a client is connected.
  if (webAudioBridge.isAvailable()) {
    console.log("[WebAudio] Sending audio to browser for playback.");
    return webAudioBridge.playAudioData(params, ttsAudioFormat);
  }

  const { duration: audioDuration, filePath, base64, buffer } = params;
  if (audioDuration <= 0 || (!filePath && !base64 && !buffer)) {
    console.log("No audio data to play, skipping playback.");
    return Promise.resolve();
  }
  // play wav file using aplay
  if (filePath) {
    return Promise.race([
      new Promise<void>((resolve) => {
        setTimeout(() => {
          resolve();
        }, audioDuration + 1000);
      }),
      new Promise<void>((resolve, reject) => {
        console.log("Playback duration:", audioDuration);
        player.isPlaying = true;
        const process = spawn("sox", ["-q", filePath, "-t", "alsa", alsaOutputDevice]);
        process.on("close", (code: number) => {
          player.isPlaying = false;
          if (code !== 0) {
            console.error(`Audio playback error: ${code}`);
            reject(code);
          } else {
            console.log("Audio playback completed");
            resolve();
          }
        });
      }),
    ]).catch((error) => {
      console.error("Audio playback error:", error);
    });
  }

  // play wav/mp3 buffer based on configured TTS format
  return new Promise((resolve, reject) => {
    const audioBuffer = base64 ? Buffer.from(base64, "base64") : buffer;
    console.log("Playback duration:", audioDuration);
    player.isPlaying = true;

    if (ttsAudioFormat === "wav") {
      const process = spawn("sox", [
        "-q",
        "-t",
        "wav",
        "-",
        "-t",
        "alsa",
        alsaOutputDevice,
      ]);
      player.process = process;
      process.stdin?.on("error", (err) => {
        console.error("Sox stdin error:", err.message);
      });
      let stderr = "";
      process.stderr?.on("data", (data) => {
        stderr += data.toString();
      });
      let settled = false;
      const watchdog = setTimeout(() => {
        if (settled) return;
        settled = true;
        player.isPlaying = false;
        if (player.process === process) {
          player.process = null;
        }
        process.kill();
        console.error("Audio playback timed out.");
        resolve();
      }, audioDuration + 2000);
      process.on("exit", (code) => {
        if (settled) return;
        settled = true;
        clearTimeout(watchdog);
        player.isPlaying = false;
        if (player.process === process) {
          player.process = null;
        }
        if (code !== 0) {
          console.error(`Audio playback error: ${code}`);
          if (stderr.trim()) {
            console.error(stderr.trim());
          }
          reject(code);
        } else {
          console.log("Audio playback completed");
          resolve();
        }
      });
      process.stdin?.end(audioBuffer);
      return;
    }

    const process = spawn("sox", [
      "-q",
      "-t",
      "mp3",
      "-",
      "-t",
      "alsa",
      alsaOutputDevice,
      "gain",
      MP3_SOX_GAIN_DB,
    ]);
    player.process = process;
    process.stdin?.on("error", (err) => {
      console.error("Sox stdin error:", err.message);
    });
    let stderr = "";
    process.stderr?.on("data", (data) => {
      stderr += data.toString();
    });
    let settled = false;
    const watchdog = setTimeout(() => {
      if (settled) return;
      settled = true;
      player.isPlaying = false;
      if (player.process === process) {
        player.process = null;
      }
      process.kill();
      console.error("Audio playback timed out.");
      resolve();
    }, audioDuration + 2000);
    process.on("exit", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(watchdog);
      player.isPlaying = false;
      if (player.process === process) {
        player.process = null;
      }
      if (code !== 0) {
        console.error(`Audio playback error: ${code}`);
        if (stderr.trim()) {
          console.error(stderr.trim());
        }
        reject(code);
      } else {
        console.log("Audio playback completed");
        resolve();
      }
    });
    process.stdin?.end(audioBuffer);
  });
};

const stopPlaying = (): void => {
  // Also stop any in-progress web playback.
  webAudioBridge.stopPlayback();

  if (player.isPlaying) {
    try {
      console.log("Stopping audio playback");
      const process = player.process;
      if (process) {
        process.stdin?.end();
        process.kill();
      }
    } catch { }
    player.isPlaying = false;
    // Recreate process
    setTimeout(() => {
      player.process = startPlayerProcess();
    }, 500);
  } else {
    console.log("No audio currently playing");
  }
};

// Close audio player when exiting program
process.on("SIGINT", () => {
  try {
    if (player.process) {
      player.process.stdin?.end();
      player.process.kill();
    }
  } catch { }
  process.exit();
});

/**
 * Kill the persistent TTS player process to free the ALSA device.
 * Resolves once the process has fully exited AND a post-exit settling
 * delay has elapsed so that ALSA fully releases the hardware.
 * Must be paired with restoreAudioPlayer() when done.
 */
const releaseAudioPlayer = (): Promise<void> => {
  const proc = player.process;
  player.process = null;
  player.isPlaying = false;

  if (!proc) {
    return Promise.resolve();
  }

  const waitForExit = new Promise<void>((resolve) => {
    if (proc.exitCode !== null || proc.signalCode !== null) {
      resolve();
      return;
    }

    const timeout = setTimeout(resolve, 3000);

    proc.once("exit", () => {
      clearTimeout(timeout);
      resolve();
    });

    try {
      proc.stdin?.end();
      proc.kill();
    } catch {}
  });

  // After process exit, wait for ALSA device to fully release
  return waitForExit.then(() => new Promise((r) => setTimeout(r, 500)));
};

/**
 * Recreate the persistent TTS player process after releaseAudioPlayer().
 */
const restoreAudioPlayer = (): void => {
  if (!player.process) {
    player.process = startPlayerProcess();
  }
};

export {
  recordAudio,
  recordAwaitingSpeech,
  recordAudioManually,
  stopRecording,
  playAudioData,
  stopPlaying,
  releaseAudioPlayer,
  restoreAudioPlayer,
};
