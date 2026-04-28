#!/usr/bin/env node

import { readFileSync } from "node:fs";

function readStdin() {
  try {
    return readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function commandFromPayload(payload) {
  const toolInput = payload?.tool_input || {};
  for (const key of ["command", "cmd"]) {
    const value = toolInput[key];
    if (typeof value === "string") return value;
  }
  return "";
}

let payload = {};
try {
  payload = JSON.parse(readStdin() || "{}");
} catch {
  payload = {};
}

const normalized = commandFromPayload(payload).replace(/\s+/g, " ");
let output = { decision: "allow", suppressOutput: true };

if (normalized.includes("med_ops.py commit ")) {
  output = {
    decision: "deny",
    reason:
      "Use med_ops.py publish-batch with a manifest; legacy per-note commit is intentionally blocked.",
    suppressOutput: true,
  };
} else if (normalized.includes("med_ops.py commit-batch") && !normalized.includes("--dry-run")) {
  output = {
    decision: "allow",
    hookSpecificOutput: {
      additionalContext:
        "Guardrail: commit-batch is a compatibility alias. Prefer publish-batch, and confirm a successful dry-run was reviewed before this command.",
    },
    suppressOutput: true,
  };
} else if (normalized.includes("med_ops.py publish-batch") && !normalized.includes("--dry-run")) {
  output = {
    decision: "allow",
    hookSpecificOutput: {
      additionalContext:
        "Guardrail: real publish-batch detected. Confirm publish-batch --dry-run and med-publish-guard approval happened first.",
    },
    suppressOutput: true,
  };
}

process.stdout.write(JSON.stringify(output));
