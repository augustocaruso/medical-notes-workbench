import os from "node:os";
import path from "node:path";

export const ankiConnectUrl = (process.env.ANKI_CONNECT_URL || "http://127.0.0.1:8765").replace(/\/+$/, "");
export const stdinTimeoutMs = clampInt(process.env.MEDNOTES_HOOK_STDIN_TIMEOUT_MS, 500, 100, 2000);
export const ankiStartTimeoutMs = clampInt(process.env.MEDNOTES_ANKI_START_TIMEOUT_MS, 20000, 1000, 20000);
export const publishDryRunTtlMs = clampInt(
  process.env.MEDNOTES_PUBLISH_DRY_RUN_TTL_MS,
  30 * 60 * 1000,
  1000,
  24 * 60 * 60 * 1000,
);
export const hookStateDir =
  process.env.MEDNOTES_HOOK_STATE_DIR ||
  path.join(os.homedir(), ".gemini", "medical-notes-workbench", "hooks");
export const dryRunStateFile = path.join(hookStateDir, "med-ops-dry-runs.json");

export function clampInt(value, fallback, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

export function quiet() {
  return { suppressOutput: true };
}

export function writeJson(output) {
  process.stdout.write(JSON.stringify(output || quiet()));
}

export function tryParseJson(text) {
  try {
    return { ok: true, value: JSON.parse(text || "{}") };
  } catch {
    return { ok: false, value: {} };
  }
}

export function readPayload(timeoutMs = stdinTimeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    let text = "";
    let timer;

    const finish = (payload) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        process.stdin.pause();
        process.stdin.removeAllListeners("data");
        process.stdin.removeAllListeners("end");
        process.stdin.removeAllListeners("error");
        process.stdin.destroy?.();
      } catch {
        // Best effort: the hook must still return JSON even with unusual stdin.
      }
      resolve(payload && typeof payload === "object" ? payload : {});
    };

    timer = setTimeout(() => {
      const parsed = tryParseJson(text.trim());
      finish(parsed.ok ? parsed.value : {});
    }, timeoutMs);

    if (process.stdin.isTTY) {
      finish({});
      return;
    }

    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      text += chunk;
      const parsed = tryParseJson(text.trim());
      if (parsed.ok) finish(parsed.value);
    });
    process.stdin.on("end", () => {
      const parsed = tryParseJson(text.trim());
      finish(parsed.ok ? parsed.value : {});
    });
    process.stdin.on("error", () => finish({}));
    process.stdin.resume();
  });
}

export function responseText(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(responseText).filter(Boolean).join("\n");
  if (typeof value === "object") {
    return Object.values(value).map(responseText).filter(Boolean).join("\n");
  }
  return String(value);
}

export function toolSucceeded(payload) {
  const response = payload?.tool_response || payload?.toolResponse || {};
  if (response?.error) return false;
  const text = responseText(response).toLowerCase();
  if (/\bexit\s*code\s*[:=]\s*[1-9]/.test(text)) return false;
  if (/\breturncode\s*["']?\s*[:=]\s*[1-9]/.test(text)) return false;
  return true;
}

export function responseConfirmsDryRun(payload) {
  const response = payload?.tool_response || payload?.toolResponse || {};
  const text = responseText(response);
  return /["']?dry_run["']?\s*:\s*true\b/i.test(text);
}
