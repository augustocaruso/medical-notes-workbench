#!/usr/bin/env node
import { spawnSync } from "node:child_process";

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error("usage: node scripts/run_python.mjs <script.py> [args...]");
  process.exit(2);
}

const candidates = [];
if (process.env.PYTHON) {
  candidates.push([process.env.PYTHON]);
}
if (process.platform === "win32") {
  candidates.push(["py", "-3"], ["python"], ["python3"]);
} else {
  candidates.push(["python3"], ["python"], ["py", "-3"]);
}

for (const candidate of candidates) {
  const [binary, ...prefixArgs] = candidate;
  const result = spawnSync(binary, [...prefixArgs, ...args], {
    stdio: "inherit",
    shell: false,
  });
  if (result.error?.code === "ENOENT") {
    continue;
  }
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  process.exit(result.status ?? 1);
}

console.error("Could not find a Python 3 interpreter. Set PYTHON or install Python.");
process.exit(127);
