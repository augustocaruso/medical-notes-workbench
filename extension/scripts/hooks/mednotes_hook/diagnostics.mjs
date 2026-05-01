import {
  ankiConnectUrl,
  ankiStartTimeoutMs,
  dryRunStateFile,
  hookStateDir,
  publishDryRunTtlMs,
  stdinTimeoutMs,
} from "./runtime.mjs";
import { loadDryRunState } from "./receipts.mjs";

export async function diagnose() {
  const state = await loadDryRunState();
  return {
    anki_connect_url: ankiConnectUrl,
    hook_state_dir: hookStateDir,
    dry_run_state_file: dryRunStateFile,
    stdin_timeout_ms: stdinTimeoutMs,
    anki_start_timeout_ms: ankiStartTimeoutMs,
    publish_dry_run_ttl_ms: publishDryRunTtlMs,
    dry_run_receipt_count: Object.keys(state.receipts || {}).length,
  };
}
