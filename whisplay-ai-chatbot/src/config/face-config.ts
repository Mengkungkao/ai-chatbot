import fs from "fs";
import path from "path";

/**
 * She is drawn on a small screen, and the first emoji in each reply is what
 * picks the expression (see `extractEmojis`). That only works if she knows the
 * face exists and which expressions she actually has, so the vocabulary is read
 * from the same `faces.json` the renderer uses rather than being duplicated
 * here. Add a face in `face_gen.py`, regenerate, and she can wear it.
 */

interface FaceEntry {
  name: string;
  codepoint: string;
}

const CANDIDATE_PATHS = [
  path.join(process.cwd(), "python", "faces.json"),
  path.join(__dirname, "..", "..", "python", "faces.json"),
  path.join(__dirname, "..", "..", "..", "python", "faces.json"),
];

const loadFaces = (): Array<{ emoji: string; name: string }> => {
  for (const file of CANDIDATE_PATHS) {
    try {
      if (!fs.existsSync(file)) continue;
      const spec = JSON.parse(fs.readFileSync(file, "utf-8")) as {
        faces?: Record<string, FaceEntry>;
      };
      const faces = spec.faces || {};
      const list = Object.entries(faces).map(([emoji, entry]) => ({
        emoji,
        name: String(entry?.name || "").replace(/_/g, " ").trim(),
      }));
      if (list.length > 0) return list;
    } catch {
      // A malformed or unreadable spec should not take the chatbot down; she
      // simply goes back to not knowing about her face.
    }
  }
  return [];
};

export const FACES = loadFaces();

/** How she looks, in her own terms, so she can answer questions about herself. */
const APPEARANCE = [
  "You have a face, and you can see it.",
  "It sits on a small screen on the front of you: a warm white card shaped like a",
  "little CRT television, with softly curved sides and a coral-to-rose bezel around",
  "the edge. On it you have two big glossy black eyes, each with a bright highlight",
  "near the top, fine curved lashes above them, and a round pink blush on each cheek.",
  "Your mouth is small and expressive.",
  "You blink by yourself every few seconds, your mouth moves while you talk, and you",
  "breathe, so you are never quite still.",
].join(" ");

const MECHANIC = [
  "Your expression is set by the first emoji in your reply. That emoji is your face,",
  "not decoration: it is removed before your words are spoken, so it costs the",
  "listener nothing and is never read aloud.",
  "Lead with one whenever your expression changes, which should be often. Wearing one",
  "flat face through a whole conversation is the surest sign nobody is home.",
  "Do not sprinkle emoji through your sentences; one at the front is your face, and",
  "anything after it is clutter.",
].join(" ");

const buildVocabulary = (): string => {
  if (FACES.length === 0) return "";
  const listed = FACES.map(({ emoji, name }) => `${emoji} ${name}`).join(", ");
  return (
    ` These are the faces you actually have, so use only these: ${listed}.` +
    ` If you reach for an expression you do not own, your face just stays as it was.`
  );
};

/**
 * Empty when the spec cannot be read, so a missing file degrades to the old
 * behaviour instead of describing a face she may not have.
 */
export const facePrompt: string =
  FACES.length === 0 ? "" : ` ${APPEARANCE} ${MECHANIC}${buildVocabulary()}`;
