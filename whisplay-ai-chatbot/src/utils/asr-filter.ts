/**
 * Whisper-family ASR models emit stock phrases when handed silence or noise —
 * usually YouTube outros and subtitle credits from their training data. On an
 * always-on device those phantom turns reach the LLM as if the person had
 * spoken, and once they are in the chat history she will refer back to things
 * that were never said.
 *
 * Only a whole utterance is matched, never a substring: "thanks for watching
 * that with me" is real speech and is kept, while a bare "Thanks for watching!"
 * is dropped.
 */

const DEFAULT_PHANTOM_PHRASES = [
  "thank you for watching",
  "thank you for watching this video",
  "thanks for watching",
  "thanks for watching this video",
  "thank you for watching and see you next time",
  "please subscribe to my channel",
  "subscribe to my channel",
  "like and subscribe",
  "don't forget to subscribe",
  "subtitles by the amara.org community",
  "subtitles by amara.org",
  "amara.org",
  "www.amara.org",
  "transcription by castingwords",
  "transcribed by https://otter.ai",
  "for more information visit www.fema.gov",
  "you",
  // The device's own wake chime, picked up by the mic and transcribed.
  "beep",
  "beep beep",
];

/** Lowercase, strip punctuation and collapse whitespace for comparison. */
const normalize = (text: string): string =>
  text
    .toLowerCase()
    .replace(/[.,!?;:'"“”‘’\-–—…]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

const extraPhrases = (): string[] =>
  (process.env.ASR_PHANTOM_PHRASES || "")
    .split(",")
    .map((phrase) => normalize(phrase))
    .filter((phrase) => phrase.length > 0);

const isFilterEnabled = (): boolean =>
  (process.env.ASR_PHANTOM_FILTER_ENABLED || "true").toLowerCase() === "true";

/**
 * True when the transcript is a known ASR hallucination rather than speech.
 */
export const isPhantomTranscript = (text: string): boolean => {
  if (!isFilterEnabled()) return false;
  const normalized = normalize(text || "");
  if (!normalized) return false;
  const phrases = [
    ...DEFAULT_PHANTOM_PHRASES.map(normalize),
    ...extraPhrases(),
  ];
  return phrases.includes(normalized);
};

export default isPhantomTranscript;
