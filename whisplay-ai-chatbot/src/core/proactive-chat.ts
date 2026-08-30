import fs from "fs";
import path from "path";
import { chatWithLLMStream } from "../cloud-api/server";
import { dataDir } from "../utils/dir";
import { buildProactiveCue } from "../config/llm-config";
import { getCurrentTimeTag } from "../utils";

/**
 * The slice of ChatFlow this needs. Kept structural so the two files do not
 * import each other.
 */
export interface ProactiveHost {
  currentFlowName: string;
  pendingExternalReply: string;
  pendingExternalEmoji: string;
  transitionTo: (flowName: any) => void;
}

// Where the toggle is remembered. The env var is only the initial default:
// once auto-talk has been turned off by hand it stays off across restarts,
// which is the whole point of a toggle.
const STATE_FILE = path.join(dataDir, "proactive-chat.json");

const readPersisted = (): boolean | null => {
  try {
    const raw = JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
    return typeof raw?.enabled === "boolean" ? raw.enabled : null;
  } catch {
    return null;
  }
};

const writePersisted = (enabled: boolean): void => {
  try {
    fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
    fs.writeFileSync(STATE_FILE, JSON.stringify({ enabled }), "utf8");
  } catch (error: any) {
    console.log(`[Proactive] could not save the toggle: ${error?.message || error}`);
  }
};

const isEnabled = (): boolean => {
  const saved = readPersisted();
  if (saved !== null) return saved;
  return (process.env.PROACTIVE_CHAT_ENABLED || "true").toLowerCase() === "true";
};

const readSeconds = (name: string, fallback: number): number => {
  const parsed = parseInt(process.env[name] || "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

/**
 * Lets her start a conversation on her own.
 *
 * A timer waits a random stretch of quiet, then asks the LLM for one
 * spontaneous line and pushes it through the same path the IM bridge uses to
 * speak, so no new audio or display plumbing is needed. She only ever speaks
 * up from the `sleep` state, so this can never talk over a live exchange.
 */
export class ProactiveChat {
  private host: ProactiveHost;
  private timer?: ReturnType<typeof setTimeout>;
  private generating = false;
  private lastSpokeAt = Date.now();
  private enabled = isEnabled();
  private minIdleSec = readSeconds("PROACTIVE_CHAT_MIN_IDLE_SEC", 120);
  private maxIdleSec = readSeconds("PROACTIVE_CHAT_MAX_IDLE_SEC", 300);

  constructor(host: ProactiveHost) {
    this.host = host;
    if (this.maxIdleSec < this.minIdleSec) {
      this.maxIdleSec = this.minIdleSec;
    }
  }

  isOn(): boolean {
    return this.enabled;
  }

  /** Flip auto-talk at runtime (triple-click). Returns the new state. */
  toggle(): boolean {
    this.enabled = !this.enabled;
    writePersisted(this.enabled);
    console.log(
      `[${getCurrentTimeTag()}] Proactive chat toggled ${this.enabled ? "ON" : "OFF"}.`,
    );
    if (this.enabled) {
      this.lastSpokeAt = Date.now();
      this.scheduleNext();
    } else {
      this.stop();
    }
    return this.enabled;
  }

  start(): void {
    if (!this.enabled) {
      console.log(`[${getCurrentTimeTag()}] Proactive chat disabled.`);
      return;
    }
    console.log(
      `[${getCurrentTimeTag()}] Proactive chat enabled ` +
        `(every ${this.minIdleSec}-${this.maxIdleSec}s of quiet).`,
    );
    this.scheduleNext();
  }

  stop(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
  }

  /** Call whenever the person speaks, so her own clock restarts. */
  noteActivity(): void {
    this.lastSpokeAt = Date.now();
  }

  private scheduleNext(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    // Never re-arm while off. tick()'s finally called this unconditionally, so
    // toggling off mid-generation put the timer straight back and auto-talk
    // resurrected itself.
    if (!this.enabled) return;
    const spread = this.maxIdleSec - this.minIdleSec;
    const waitSec = this.minIdleSec + Math.floor(Math.random() * (spread + 1));
    this.timer = setTimeout(() => {
      void this.tick();
    }, waitSec * 1000);
  }

  private async tick(): Promise<void> {
    // Only ever speak up from an idle device — never over a live exchange.
    if (!this.enabled) return;
    if (this.generating || this.host.currentFlowName !== "sleep") {
      this.scheduleNext();
      return;
    }
    const quietForSeconds = Math.round((Date.now() - this.lastSpokeAt) / 1000);
    if (quietForSeconds < this.minIdleSec) {
      this.scheduleNext();
      return;
    }

    this.generating = true;
    try {
      const line = await this.generateLine(quietForSeconds);
      // Re-check: the person may have started talking while the model ran.
      // Re-check enabled too: generation can take up to a minute, and a line
      // asked for before the toggle was still spoken after it.
      if (line && this.enabled && this.host.currentFlowName === "sleep") {
        console.log(`[${getCurrentTimeTag()}] Proactive: ${line}`);
        this.host.pendingExternalReply = line;
        this.host.pendingExternalEmoji = "";
        this.lastSpokeAt = Date.now();
        this.host.transitionTo("external_answer");
      }
    } catch (error: any) {
      console.log(`[Proactive] generation failed: ${error?.message || error}`);
    } finally {
      this.generating = false;
      this.scheduleNext();
    }
  }

  private generateLine(quietForSeconds: number): Promise<string> {
    return new Promise((resolve) => {
      let text = "";
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve(text.trim());
      };
      // Don't let a wedged request block the next scheduling round.
      const guard = setTimeout(finish, 60_000);
      chatWithLLMStream(
        [{ role: "user", content: buildProactiveCue(quietForSeconds) }],
        (partial: string) => {
          text += partial;
        },
        () => {
          clearTimeout(guard);
          finish();
        },
      );
    });
  }
}

export default ProactiveChat;
