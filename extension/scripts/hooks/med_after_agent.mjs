#!/usr/bin/env node

import { readFileSync } from "node:fs";

function readPayload() {
  try {
    return JSON.parse(readFileSync(0, "utf8") || "{}");
  } catch {
    return {};
  }
}

const payload = readPayload();
const prompt = String(payload.prompt || "").toLowerCase();
const response = String(payload.prompt_response || "").toLowerCase();

let output = { decision: "allow", suppressOutput: true };

if (prompt.includes("process") && prompt.includes("chat") && prompt.includes("mednotes")) {
  const required = ["dry-run", "publish", "linker"];
  const missing = required.some((term) => !response.includes(term));
  if (!payload.stop_hook_active && missing) {
    output = {
      decision: "deny",
      reason:
        "Atualize a resposta final incluindo status de dry-run, publish-batch e linker do pipeline medico.",
      suppressOutput: true,
    };
  }
}

process.stdout.write(JSON.stringify(output));
