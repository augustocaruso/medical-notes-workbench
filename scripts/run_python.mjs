#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import os from "node:os";

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error("usage: node scripts/run_python.mjs <script.py> [args...]");
  process.exit(2);
}

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "..");
const uv = process.env.UV || "uv";
const env = { ...process.env };

const appHome =
  env.MEDNOTES_HOME ||
  env.MEDICAL_NOTES_WORKBENCH_HOME ||
  join(os.homedir(), ".gemini", "medical-notes-workbench");

const installedExtension = existsSync(join(projectRoot, "gemini-extension.json"));
const usePersistentEnv =
  env.MEDNOTES_USE_PERSISTENT_UV_ENV === "1" ||
  (env.MEDNOTES_USE_PERSISTENT_UV_ENV !== "0" && installedExtension);

if (!env.UV_PROJECT_ENVIRONMENT && usePersistentEnv) {
  mkdirSync(appHome, { recursive: true });
  env.UV_PROJECT_ENVIRONMENT = join(appHome, ".venv");
}

const result = spawnSync(uv, ["run", "--project", projectRoot, "python", ...args], {
  env,
  stdio: "inherit",
  shell: false,
});

if (result.error?.code === "ENOENT") {
  console.error(
    "Could not find uv. Install uv first, or run scripts/reset_windows_python_uv.ps1 on Windows.",
  );
  process.exit(127);
}

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
