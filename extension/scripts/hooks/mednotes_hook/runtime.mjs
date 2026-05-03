export const ankiConnectUrl = (process.env.ANKI_CONNECT_URL || "http://127.0.0.1:8765").replace(/\/+$/, "");
export const stdinTimeoutMs = clampInt(process.env.MEDNOTES_HOOK_STDIN_TIMEOUT_MS, 500, 100, 2000);
export const ankiStartTimeoutMs = clampInt(process.env.MEDNOTES_ANKI_START_TIMEOUT_MS, 8000, 1000, 15000);
export const ankiAutoStart = /^(1|true|yes)$/i.test(process.env.MEDNOTES_ANKI_AUTO_START || "");

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
