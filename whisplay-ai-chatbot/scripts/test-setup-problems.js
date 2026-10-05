// A chatbot that cannot listen or speak must say why on its idle screen.
// On the boards, ASR_SERVER=opeai (a typo) and TTS_SERVER=piper without Piper
// installed only showed up in the log: the user saw a chatbot that ignored
// them, or answered in text without a voice.
//
// Run against the built output:  node scripts/test-setup-problems.js
const assert = require("assert");
const path = require("path");
Object.assign(process.env, {
  ASR_SERVER: "opeai",
  LLM_SERVER: "test",
  TTS_SERVER: "piper",
  PIPER_BINARY_PATH: "/path/to/piper-binary",
});
const dist = path.resolve(__dirname, "..", "dist");
require(path.join(dist, "cloud-api", "server.js"));
const { setupProblemText, setupProblems } = require(path.join(dist, "utils", "setup-problems.js"));
const text = setupProblemText();
console.log(text);
assert.strictEqual(setupProblems.length, 2, "two problems: the ASR typo and the missing Piper");
assert.match(text, /ASR_SERVER=opeai is not a speech-recognition service/);
assert.match(text, /TTS_SERVER=piper, but Piper is not installed \(PIPER_BINARY_PATH=\/path\/to\/piper-binary\)/);

// Errors the service gives back because of a setting become problems too,
// but not a passing failure, nor a too-short recording (400) for ASR.
const { reportServiceError } = require(path.join(dist, "utils", "setup-problems.js"));
reportServiceError("OpenAI voice", "OPENAI_VOICE_MODEL=tt-1-hd",
  { status: 404, error: { message: "The model `tt-1-hd` does not exist or you do not have access to it." } });
reportServiceError("OpenAI voice", "OPENAI_VOICE_MODEL=tts-1", { status: 500, message: "server error" });
reportServiceError("OpenAI voice", "OPENAI_VOICE_MODEL=tts-1", { code: "ECONNRESET" });
reportServiceError("OpenAI speech recognition", "OPENAI_ASR_MODEL=whisper-1",
  { status: 400, message: "Audio file is too short." }, [401, 403, 404]);
reportServiceError("OpenAI speech recognition", "OPENAI_ASR_MODEL=whisper-1",
  { status: 401, message: "Incorrect API key provided: sk-...abcd" }, [401, 403, 404]);
console.log(setupProblemText());
assert.strictEqual(setupProblems.length, 4);
assert.match(setupProblems[2], /^OpenAI voice \(OPENAI_VOICE_MODEL=tt-1-hd\): The model `tt-1-hd` does not exist/);
assert.strictEqual(setupProblems[3], "OpenAI speech recognition (OPENAI_ASR_MODEL=whisper-1): the API key was rejected");
console.log("PASS");
