import {
  ankiAutoStart,
  ankiConnectUrl,
  ankiStartTimeoutMs,
  stdinTimeoutMs,
} from "./runtime.mjs";

export async function diagnose() {
  return {
    anki_connect_url: ankiConnectUrl,
    anki_auto_start: ankiAutoStart,
    stdin_timeout_ms: stdinTimeoutMs,
    anki_start_timeout_ms: ankiStartTimeoutMs,
  };
}
