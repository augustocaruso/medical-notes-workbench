#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { join } from "node:path";

const extensionPath = process.argv[2] || process.cwd();
const script = join(extensionPath, "scripts", "mednotes", "med_ops.py");
const context =
  "Medical Notes Workbench: use /mednotes:process-chats for Chats_Raw -> " +
  "Wiki_Medicina. med_ops.py is the only supported way to mutate raw chat " +
  `status or commit generated notes. Script: ${script}`;

try {
  readFileSync(0, "utf8");
} catch {
  // Hook input is advisory only for this context hook.
}

process.stdout.write(
  JSON.stringify({
    hookSpecificOutput: { additionalContext: context },
    suppressOutput: true,
  }),
);
