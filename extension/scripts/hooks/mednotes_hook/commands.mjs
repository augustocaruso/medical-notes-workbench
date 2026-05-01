import path from "node:path";

const medOpsSubcommands = new Set([
  "list-pending",
  "list-triados",
  "triage",
  "discard",
  "stage-note",
  "publish-batch",
  "commit",
  "commit-batch",
  "run-linker",
  "validate",
]);

export function commandFromPayload(payload) {
  const toolInput = payload?.tool_input || payload?.toolInput || {};
  for (const key of ["command", "cmd"]) {
    const value = toolInput[key];
    if (typeof value === "string") return value;
  }
  return "";
}

export function tokenizeCommand(command) {
  const tokens = [];
  let current = "";
  let quote = "";

  for (let index = 0; index < command.length; index += 1) {
    const char = command[index];
    if (quote) {
      if (char === quote) {
        quote = "";
      } else {
        current += char;
      }
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      continue;
    }
    if (/\s/.test(char)) {
      if (current) {
        tokens.push(current);
        current = "";
      }
      continue;
    }
    current += char;
  }

  if (current) tokens.push(current);
  return tokens;
}

export function baseName(token) {
  return token.replace(/\\/g, "/").split("/").pop() || token;
}

export function parseMedOpsCommand(command) {
  const tokens = tokenizeCommand(command);
  const scriptIndex = tokens.findIndex((token) => baseName(token) === "med_ops.py");
  if (scriptIndex < 0) return null;

  let commandIndex = -1;
  for (let index = scriptIndex + 1; index < tokens.length; index += 1) {
    if (medOpsSubcommands.has(tokens[index])) {
      commandIndex = index;
      break;
    }
  }
  if (commandIndex < 0) return { tokens, subcommand: "", args: [], dryRun: false, manifest: "" };

  const afterScript = tokens.slice(scriptIndex + 1);
  const args = tokens.slice(commandIndex + 1);
  return {
    tokens,
    subcommand: tokens[commandIndex],
    args,
    dryRun: afterScript.includes("--dry-run"),
    manifest: optionValue(afterScript, "--manifest"),
  };
}

export function optionValue(tokens, flag) {
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token === flag) return tokens[index + 1] || "";
    if (token.startsWith(`${flag}=`)) return token.slice(flag.length + 1);
  }
  return "";
}

export function resolveManifest(manifest, cwd) {
  if (!manifest) return "";
  return path.resolve(cwd || process.cwd(), manifest);
}
