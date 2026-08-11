import fs from "fs";
import dotenv from "dotenv";
import { openai } from "./openai"; // Assuming openai is exported from openai.ts

dotenv.config();

const OpenAiAsrModel = process.env.OPENAI_ASR_MODEL || "whisper-1"; //default to whisper-1 - changeable if openai compatible provider like NanoGPT is used

// ISO-639-1 code. Without it Whisper guesses the language from the audio, and
// on a short or noisy clip it guesses badly — a few seconds of English can come
// back as Bengali or Welsh script. Leave empty to auto-detect.
const OpenAiAsrLanguage = (process.env.OPENAI_ASR_LANGUAGE || "").trim();

// Nudges Whisper toward the vocabulary and spelling this device expects. It is
// a decoding hint, not an instruction, so keep it short.
const OpenAiAsrPrompt = (process.env.OPENAI_ASR_PROMPT || "").trim();

export const recognizeAudio = async (
  audioFilePath: string
): Promise<string> => {
  if (!openai) {
    console.error("OpenAI API key is not set.");
    return "";
  }
  if (!fs.existsSync(audioFilePath)) {
    console.error("Audio file does not exist:", audioFilePath);
    return "";
  }

  try {
    const transcription = await openai.audio.transcriptions.create({
      file: fs.createReadStream(audioFilePath),
      model: OpenAiAsrModel,
      ...(OpenAiAsrLanguage ? { language: OpenAiAsrLanguage } : {}),
      ...(OpenAiAsrPrompt ? { prompt: OpenAiAsrPrompt } : {}),
    });
    console.log("Transcription result:", transcription.text);
    return transcription.text;
  } catch (error) {
    console.error("Audio recognition failed:", error);
    return "";
  }
};
