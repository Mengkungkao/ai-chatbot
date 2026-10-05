/**
 * Configuration problems found at start-up (a mistyped ASR_SERVER, a TTS
 * service that is not installed, ...). Each one is also logged, but the log
 * is not where a device user looks: the idle screen shows them instead of
 * the usual hint, so a chatbot that cannot listen or speak says why.
 */
export const setupProblems: string[] = [];

export const addSetupProblem = (problem: string): void => {
  console.warn(`[Setup] ${problem}`);
  if (!setupProblems.includes(problem)) setupProblems.push(problem);
};

/** The idle-screen text for the problems, or "" when there are none. */
export const setupProblemText = (): string =>
  setupProblems.length === 0
    ? ""
    : `Setup problem in .env:\n${setupProblems.join("\n")}\n` +
      "Fix the .env in the app's data folder, then open AI Chatbot again.";

/**
 * Record a service error that a setting causes (a model name that does not
 * exist, a rejected key), not a passing one such as a network failure: only
 * the request errors in `statuses` become setup problems. Speech recognition
 * leaves 400 out: OpenAI answers a too-short recording with it.
 */
export const reportServiceError = (
  service: string,
  setting: string,
  error: any,
  statuses: number[] = [400, 401, 403, 404],
): void => {
  const status = Number(error?.status);
  if (!statuses.includes(status)) return;
  const detail =
    status === 401
      ? "the API key was rejected"
      : String(error?.error?.message || error?.message || `HTTP ${status}`).slice(0, 120);
  addSetupProblem(`${service} (${setting}): ${detail}`);
};
