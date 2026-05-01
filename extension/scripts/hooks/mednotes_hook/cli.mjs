import { pathToFileURL } from "node:url";

import { ensureAnkiBefore } from "./anki_preflight.mjs";
import { diagnose } from "./diagnostics.mjs";
import { medOpsAfter, medOpsBefore } from "./med_ops_guard.mjs";
import { quiet, readPayload, writeJson } from "./runtime.mjs";

export async function dispatch(mode, payload) {
  if (mode === "ensure-anki-before") return ensureAnkiBefore(payload);
  if (mode === "med-ops-before") return medOpsBefore(payload);
  if (mode === "med-ops-after") return medOpsAfter(payload);
  return quiet();
}

export async function run(argv = process.argv.slice(2)) {
  const mode = argv[0] || "";
  if (mode === "diagnose") {
    writeJson(await diagnose());
    return;
  }

  const payload = await readPayload();
  writeJson(await dispatch(mode, payload));
}

export async function main(argv = process.argv.slice(2)) {
  try {
    await run(argv);
  } catch (error) {
    console.error(`mednotes hook failed open: ${error instanceof Error ? error.message : String(error)}`);
    writeJson(quiet());
    process.exitCode = 0;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
