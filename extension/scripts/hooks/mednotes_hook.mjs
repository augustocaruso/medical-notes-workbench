#!/usr/bin/env node

import { spawn } from "node:child_process";
import crypto from "node:crypto";
import http from "node:http";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

const mode = process.argv[2] || "";
const ankiConnectUrl = (process.env.ANKI_CONNECT_URL || "http://127.0.0.1:8765").replace(/\/+$/, "");
const stdinTimeoutMs = clampInt(process.env.MEDNOTES_HOOK_STDIN_TIMEOUT_MS, 500, 100, 2000);
const ankiStartTimeoutMs = clampInt(process.env.MEDNOTES_ANKI_START_TIMEOUT_MS, 20000, 1000, 20000);
const publishDryRunTtlMs = clampInt(process.env.MEDNOTES_PUBLISH_DRY_RUN_TTL_MS, 30 * 60 * 1000, 1000, 24 * 60 * 60 * 1000);
const hookStateDir =
  process.env.MEDNOTES_HOOK_STATE_DIR ||
  path.join(os.homedir(), ".gemini", "medical-notes-workbench", "hooks");
const dryRunStateFile = path.join(hookStateDir, "med-ops-dry-runs.json");

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

function clampInt(value, fallback, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

function quiet() {
  return { suppressOutput: true };
}

function writeJson(output) {
  process.stdout.write(JSON.stringify(output || quiet()));
}

function tryParseJson(text) {
  try {
    return { ok: true, value: JSON.parse(text || "{}") };
  } catch {
    return { ok: false, value: {} };
  }
}

function readPayload(timeoutMs = stdinTimeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    let text = "";
    let timer;

    const finish = (payload) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        process.stdin.pause();
        process.stdin.removeAllListeners("data");
        process.stdin.removeAllListeners("end");
        process.stdin.removeAllListeners("error");
        process.stdin.destroy?.();
      } catch {
        // Best effort: the hook must still return JSON even with unusual stdin.
      }
      resolve(payload && typeof payload === "object" ? payload : {});
    };

    timer = setTimeout(() => {
      const parsed = tryParseJson(text.trim());
      finish(parsed.ok ? parsed.value : {});
    }, timeoutMs);

    if (process.stdin.isTTY) {
      finish({});
      return;
    }

    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      text += chunk;
      const parsed = tryParseJson(text.trim());
      if (parsed.ok) finish(parsed.value);
    });
    process.stdin.on("end", () => {
      const parsed = tryParseJson(text.trim());
      finish(parsed.ok ? parsed.value : {});
    });
    process.stdin.on("error", () => finish({}));
    process.stdin.resume();
  });
}

function commandFromPayload(payload) {
  const toolInput = payload?.tool_input || payload?.toolInput || {};
  for (const key of ["command", "cmd"]) {
    const value = toolInput[key];
    if (typeof value === "string") return value;
  }
  return "";
}

function tokenizeCommand(command) {
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

function baseName(token) {
  return token.replace(/\\/g, "/").split("/").pop() || token;
}

function parseMedOpsCommand(command) {
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

function optionValue(tokens, flag) {
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token === flag) return tokens[index + 1] || "";
    if (token.startsWith(`${flag}=`)) return token.slice(flag.length + 1);
  }
  return "";
}

function resolveManifest(manifest, cwd) {
  if (!manifest) return "";
  return path.resolve(cwd || process.cwd(), manifest);
}

async function sha256File(filePath) {
  const data = await fs.readFile(filePath);
  return crypto.createHash("sha256").update(data).digest("hex");
}

async function loadDryRunState() {
  try {
    const raw = await fs.readFile(dryRunStateFile, "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : { receipts: {} };
  } catch {
    return { receipts: {} };
  }
}

async function saveDryRunState(state) {
  await fs.mkdir(hookStateDir, { recursive: true });
  await fs.writeFile(dryRunStateFile, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}

function responseText(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(responseText).filter(Boolean).join("\n");
  if (typeof value === "object") {
    return Object.values(value).map(responseText).filter(Boolean).join("\n");
  }
  return String(value);
}

function toolSucceeded(payload) {
  const response = payload?.tool_response || payload?.toolResponse || {};
  if (response?.error) return false;
  const text = responseText(response).toLowerCase();
  if (/\bexit\s*code\s*[:=]\s*[1-9]/.test(text)) return false;
  if (/\breturncode\s*["']?\s*[:=]\s*[1-9]/.test(text)) return false;
  return true;
}

function responseConfirmsDryRun(payload) {
  const response = payload?.tool_response || payload?.toolResponse || {};
  const text = responseText(response);
  return /["']?dry_run["']?\s*:\s*true\b/i.test(text);
}

async function medOpsBefore(payload) {
  const command = commandFromPayload(payload);
  const parsed = parseMedOpsCommand(command);
  if (!parsed) return quiet();

  if (parsed.subcommand === "commit") {
    return {
      decision: "deny",
      reason:
        "Bloqueado: o comando legado med_ops.py commit foi removido. Use stage-note, depois publish-batch --dry-run e só então publish-batch.",
      suppressOutput: true,
    };
  }

  if (parsed.subcommand === "commit-batch" && !parsed.dryRun) {
    return {
      decision: "deny",
      reason:
        "Bloqueado: commit-batch é apenas alias de compatibilidade. Use publish-batch --dry-run, revise, depois publish-batch.",
      suppressOutput: true,
    };
  }

  if (parsed.subcommand !== "publish-batch" || parsed.dryRun) return quiet();

  const manifestPath = resolveManifest(parsed.manifest, payload.cwd);
  if (!manifestPath) {
    return {
      decision: "deny",
      reason: "Bloqueado: publish-batch real precisa de --manifest para validar o dry-run anterior.",
      suppressOutput: true,
    };
  }

  let manifestSha;
  try {
    manifestSha = await sha256File(manifestPath);
  } catch {
    return {
      decision: "deny",
      reason:
        "Bloqueado: nao consegui ler o manifest informado. Confirme o caminho e rode publish-batch --dry-run novamente.",
      suppressOutput: true,
    };
  }

  const state = await loadDryRunState();
  const receipt = state.receipts?.[manifestPath];
  if (!receipt) {
    return {
      decision: "deny",
      reason: "Bloqueado: rode publish-batch --dry-run para este manifest antes do publish real.",
      suppressOutput: true,
    };
  }
  if (Date.now() > Number(receipt.expires_at || 0)) {
    return {
      decision: "deny",
      reason: "Bloqueado: o dry-run desse manifest expirou. Rode publish-batch --dry-run novamente.",
      suppressOutput: true,
    };
  }
  if (receipt.manifest_sha256 !== manifestSha) {
    return {
      decision: "deny",
      reason: "Bloqueado: o manifest mudou desde o dry-run. Rode publish-batch --dry-run novamente.",
      suppressOutput: true,
    };
  }

  return quiet();
}

async function medOpsAfter(payload) {
  const command = commandFromPayload(payload);
  const parsed = parseMedOpsCommand(command);
  if (!parsed || parsed.subcommand !== "publish-batch") return quiet();

  const manifestPath = resolveManifest(parsed.manifest, payload.cwd);
  if (!manifestPath || !toolSucceeded(payload)) return quiet();

  const state = await loadDryRunState();
  state.receipts ||= {};

  if (parsed.dryRun) {
    if (!responseConfirmsDryRun(payload)) {
      return {
        systemMessage:
          "Dry-run terminou, mas o hook nao encontrou confirmacao JSON de dry_run=true. O publish-batch real continuara bloqueado.",
        suppressOutput: true,
      };
    }

    const manifestSha = await sha256File(manifestPath);
    const now = Date.now();
    state.receipts[manifestPath] = {
      manifest: manifestPath,
      manifest_sha256: manifestSha,
      cwd: payload.cwd || process.cwd(),
      dry_run_at: new Date(now).toISOString(),
      expires_at: now + publishDryRunTtlMs,
    };
    await saveDryRunState(state);
    return {
      systemMessage: "Dry-run validado para este manifest; publish-batch real liberado por tempo limitado.",
      suppressOutput: true,
    };
  }

  if (state.receipts[manifestPath]) {
    delete state.receipts[manifestPath];
    await saveDryRunState(state);
    return {
      systemMessage: "Publish-batch concluido; o recibo de dry-run deste manifest foi invalidado.",
      suppressOutput: true,
    };
  }

  return quiet();
}

function isAnkiTool(payload) {
  const toolName = String(payload.tool_name || payload.toolName || payload.name || "");
  if (/^mcp_anki(?:-mcp)?_/.test(toolName)) return true;
  const fields = [
    payload.tool_name,
    payload.toolName,
    payload.name,
    payload.server_name,
    payload.serverName,
    payload.mcp_server_name,
    payload.mcpServerName,
    payload.tool?.name,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return /\banki\b/.test(fields);
}

function ankiConnectReady(timeoutMs = 800) {
  return new Promise((resolve) => {
    const body = JSON.stringify({ action: "version", version: 6 });
    const request = http.request(
      ankiConnectUrl,
      {
        method: "POST",
        timeout: timeoutMs,
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (response) => {
        let text = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          text += chunk;
        });
        response.on("end", () => {
          try {
            const parsed = JSON.parse(text || "{}");
            resolve(response.statusCode === 200 && parsed.error == null && parsed.result != null);
          } catch {
            resolve(false);
          }
        });
      },
    );
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
    request.write(body);
    request.end();
  });
}

function runProcess(command, args, timeoutMs) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(command, args, { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
    } catch (error) {
      resolve({ ok: false, message: error instanceof Error ? error.message : String(error) });
      return;
    }

    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve({ ok: false, timedOut: true, message: stderr.trim() });
    }, timeoutMs);

    child.stderr?.setEncoding("utf8");
    child.stderr?.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ ok: false, message: error instanceof Error ? error.message : String(error) });
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, message: stderr.trim() });
    });
  });
}

async function launchAnki() {
  if (process.platform === "win32") {
    const script = String.raw`
$ErrorActionPreference = "SilentlyContinue"
$programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
$paths = @(
  "$env:LOCALAPPDATA\Programs\Anki\anki.exe",
  "$env:ProgramFiles\Anki\anki.exe",
  $(if ($programFilesX86) { Join-Path $programFilesX86 "Anki\anki.exe" }),
  "C:\Users\leona\AppData\Local\Programs\Anki\anki.exe"
)
$running = (Get-Process -Name "anki" -ErrorAction SilentlyContinue | Select-Object -First 1) -or (Get-Process | Where-Object { $_.MainWindowTitle -match "Anki" } | Select-Object -First 1)
if (-not $running) {
  $ankiPath = $paths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
  if ($ankiPath) {
    Start-Process -FilePath $ankiPath -WindowStyle Minimized
  } else {
    Write-Error "anki.exe not found in standard paths"
    exit 2
  }
}
$code = @"
using System;
using System.Runtime.InteropServices;
public class Win32Anki {
  [DllImport("user32.dll")]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
try { Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue } catch { }

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$ankiReady = $false
$windowMinimized = $false
$ankiWindow = $null
while ($stopwatch.Elapsed.TotalSeconds -lt 20) {
  if (-not $ankiReady) {
    try {
      Invoke-RestMethod -Uri "http://127.0.0.1:8765" -Method Get -TimeoutSec 1 -ErrorAction Stop | Out-Null
      $ankiReady = $true
    } catch { }
  }

  if (-not $windowMinimized) {
    $ankiWindow = Get-Process | Where-Object { $_.MainWindowTitle -match "Anki" -and $_.MainWindowHandle -ne [IntPtr]::Zero } | Select-Object -First 1
    if ($ankiWindow) {
      try {
        [Win32Anki]::ShowWindow($ankiWindow.MainWindowHandle, 6) | Out-Null
        $windowMinimized = $true
      } catch { }
    }
  }

  if ($ankiReady -and $windowMinimized) {
    Start-Sleep -Milliseconds 500
    if ($ankiWindow) {
      try { [Win32Anki]::ShowWindow($ankiWindow.MainWindowHandle, 6) | Out-Null } catch { }
    }
    break
  }
  Start-Sleep -Milliseconds 200
}
exit 0
`;
    const result = await runProcess("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], ankiStartTimeoutMs + 1000);
    if (!result.ok && result.message) console.error(result.message);
    return result.ok;
  }

  if (process.platform === "darwin") {
    const result = await runProcess("open", ["-g", "-j", "-a", "Anki"], 3000);
    if (!result.ok && result.message) console.error(result.message);
    return result.ok;
  }

  try {
    const child = spawn("anki", [], { detached: true, stdio: "ignore" });
    child.unref();
    return true;
  } catch (error) {
    console.error(`Could not start Anki: ${error instanceof Error ? error.message : String(error)}`);
    return false;
  }
}

async function waitForAnkiConnect(timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await ankiConnectReady()) return true;
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  return false;
}

async function ensureAnkiBefore(payload) {
  if (!isAnkiTool(payload)) return quiet();
  if (await ankiConnectReady()) return quiet();

  console.error("AnkiConnect is not ready. Trying a bounded Anki preflight before Anki MCP tool use.");
  const launched = await launchAnki();
  const ready = launched ? await waitForAnkiConnect(ankiStartTimeoutMs) : false;

  if (ready) {
    return {
      systemMessage: "Anki foi aberto; AnkiConnect esta pronto para usar o MCP.",
      suppressOutput: true,
    };
  }

  return {
    systemMessage:
      "AnkiConnect nao respondeu; a ferramenta Anki MCP pode falhar. Abra o Anki Desktop e confira o add-on AnkiConnect.",
    suppressOutput: true,
  };
}

async function diagnose() {
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

async function main() {
  if (mode === "diagnose") {
    writeJson(await diagnose());
    return;
  }

  const payload = await readPayload();
  if (mode === "ensure-anki-before") {
    writeJson(await ensureAnkiBefore(payload));
  } else if (mode === "med-ops-before") {
    writeJson(await medOpsBefore(payload));
  } else if (mode === "med-ops-after") {
    writeJson(await medOpsAfter(payload));
  } else {
    writeJson(quiet());
  }
  process.exit(0);
}

main().catch((error) => {
  console.error(`mednotes hook failed open: ${error instanceof Error ? error.message : String(error)}`);
  writeJson(quiet());
  process.exit(0);
});
