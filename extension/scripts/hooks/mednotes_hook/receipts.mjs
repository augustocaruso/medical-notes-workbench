import crypto from "node:crypto";
import { promises as fs } from "node:fs";

import { dryRunStateFile, hookStateDir } from "./runtime.mjs";

export async function sha256File(filePath) {
  const data = await fs.readFile(filePath);
  return crypto.createHash("sha256").update(data).digest("hex");
}

export async function loadDryRunState() {
  try {
    const raw = await fs.readFile(dryRunStateFile, "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : { receipts: {} };
  } catch {
    return { receipts: {} };
  }
}

export async function saveDryRunState(state) {
  await fs.mkdir(hookStateDir, { recursive: true });
  await fs.writeFile(dryRunStateFile, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}
