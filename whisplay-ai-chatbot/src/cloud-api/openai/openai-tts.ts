import mp3Duration from "mp3-duration";
import { openai } from "./openai"; // Assuming openai is exported from openai.ts
import dotenv from "dotenv";
import { TTSResult } from "../../type";

dotenv.config();

const openAiVoiceModel = process.env.OPENAI_VOICE_MODEL || "tts-1"; // Default to tts-1
const openAiVoiceType = process.env.OPENAI_VOICE_TYPE || "nova"; // Optional: alloy, echo, fable, onyx, nova, shimmer

// Delivery direction ("sound warm and unhurried") is only understood by the
// gpt-4o TTS models; tts-1 and tts-1-hd reject the field.
const supportsInstructions = (): boolean =>
  /gpt-4o|mini-tts/i.test(openAiVoiceModel);

const ttsInstructions = (process.env.OPENAI_TTS_INSTRUCTIONS || "").trim();

// 0.25–4.0. Slightly under 1.0 reads as more relaxed and less clipped.
const ttsSpeed = (() => {
  const raw = parseFloat(process.env.OPENAI_TTS_SPEED || "");
  if (!Number.isFinite(raw)) return undefined;
  return Math.min(4, Math.max(0.25, raw));
})();

const openaiTTS = async (
  text: string
): Promise<TTSResult> => {
  if (!openai) {
    console.error("OpenAI API key is not set.");
    return { duration: 0 };
  }
  const mp3 = await openai.audio.speech.create({
    model: openAiVoiceModel,
    voice: openAiVoiceType,
    input: text,
    ...(ttsInstructions && supportsInstructions()
      ? { instructions: ttsInstructions }
      : {}),
    ...(ttsSpeed !== undefined ? { speed: ttsSpeed } : {}),
  }).catch((error) => {
    console.log("OpenAI TTS failed:", error);
    return null;
  });
  if (!mp3) {
    return { duration: 0 };
  }
  const buffer = Buffer.from(await mp3.arrayBuffer());
  const duration = await mp3Duration(buffer);
  return { buffer, duration: duration * 1000 };
};

export default openaiTTS;
