#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import { readFileSync } from "node:fs";

const ankiConnectUrl = (process.env.ANKI_CONNECT_URL || "http://127.0.0.1:8765").replace(/\/+$/, "");
const startTimeoutMs = Number(process.env.MEDNOTES_ANKI_START_TIMEOUT_MS || "25000");

function readPayload() {
  try {
    return JSON.parse(readFileSync(0, "utf8") || "{}");
  } catch {
    return {};
  }
}

function writeOutput(output) {
  process.stdout.write(JSON.stringify(output));
}

function isAnkiRelevant(payload) {
  const toolName = String(payload.tool_name || payload.toolName || payload.name || "");
  if (/^mcp_anki_/.test(toolName)) return true;

  const likelyToolFields = [
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

  if (/\banki\b/.test(likelyToolFields)) return true;
  if (
    /\b(sync|get_due_cards|get_cards|present_card|rate_card|listdecks|deckstats|createdeck|changedeck|addnote|addnotes|findnotes|notesinfo|updatenotefields|deletenotes|gettags|addtags|removetags|replacetags|clearunusedtags|modelnames|modelfieldnames|modelstyling|createmodel|updatemodelstyling|storemediafile|retrievemediafile|guibrowse|guiaddcards)\b/.test(
      likelyToolFields,
    )
  ) {
    return true;
  }

  const toolInput = payload.tool_input || payload.toolInput || {};
  const command = String(toolInput.command || toolInput.cmd || "").toLowerCase();
  if (
    command.includes("/twenty_rules") ||
    command.includes("/mednotes:twenty_rules") ||
    command.includes("/mednotes:flashcards") ||
    (command.includes("anki") && command.includes("flash"))
  ) {
    return true;
  }

  const prompt = String(payload.prompt || payload.user_prompt || "").toLowerCase();
  if (
    prompt.includes("/twenty_rules") ||
    prompt.includes("/mednotes:twenty_rules") ||
    prompt.includes("/mednotes:flashcards")
  ) {
    return true;
  }

  return false;
}

function ankiConnectReady(timeoutMs = 1500) {
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

function powershellExecutable() {
  return process.platform === "win32" ? "powershell.exe" : "pwsh";
}

function runPowerShell(script) {
  return spawnSync(
    powershellExecutable(),
    ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
    { encoding: "utf8", windowsHide: true },
  );
}

function launchAnkiWindows() {
  const script = String.raw`
$ErrorActionPreference = "SilentlyContinue"
$programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
$paths = @(
  "$env:LOCALAPPDATA\Programs\Anki\anki.exe",
  "$env:ProgramFiles\Anki\anki.exe",
  $(if ($programFilesX86) { Join-Path $programFilesX86 "Anki\anki.exe" }),
  "C:\Users\leona\AppData\Local\Programs\Anki\anki.exe"
)
$running = Get-Process -Name "anki" -ErrorAction SilentlyContinue | Select-Object -First 1
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
public class MedNotesAnkiWindow {
  [DllImport("user32.dll")]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
try { Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue } catch {}
Get-Process | Where-Object {
  $_.MainWindowTitle -match "Anki" -and $_.MainWindowHandle -ne [IntPtr]::Zero
} | ForEach-Object {
  try { [MedNotesAnkiWindow]::ShowWindow($_.MainWindowHandle, 6) | Out-Null } catch {}
}
exit 0
`;
  const result = runPowerShell(script);
  if (result.status !== 0) {
    console.error((result.stderr || result.stdout || "Could not start Anki").trim());
  }
  return result.status === 0;
}

function minimizeAnkiWindows() {
  if (process.platform !== "win32") return;
  runPowerShell(String.raw`
$ErrorActionPreference = "SilentlyContinue"
$code = @"
using System;
using System.Runtime.InteropServices;
public class MedNotesAnkiWindow {
  [DllImport("user32.dll")]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
try { Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue } catch {}
Get-Process | Where-Object {
  $_.MainWindowTitle -match "Anki" -and $_.MainWindowHandle -ne [IntPtr]::Zero
} | ForEach-Object {
  try { [MedNotesAnkiWindow]::ShowWindow($_.MainWindowHandle, 6) | Out-Null } catch {}
}
`);
}

function launchAnki() {
  if (process.platform === "win32") return launchAnkiWindows();

  if (process.platform === "darwin") {
    const result = spawnSync("open", ["-g", "-j", "-a", "Anki"], { stdio: "ignore" });
    return result.status === 0;
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
    if (await ankiConnectReady(1200)) return true;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return false;
}

async function main() {
  const payload = readPayload();
  if (!isAnkiRelevant(payload)) {
    writeOutput({ decision: "allow", suppressOutput: true });
    return;
  }

  if (await ankiConnectReady()) {
    minimizeAnkiWindows();
    writeOutput({
      decision: "allow",
      hookSpecificOutput: {
        additionalContext: `AnkiConnect is already ready at ${ankiConnectUrl}.`,
      },
      suppressOutput: true,
    });
    return;
  }

  console.error("AnkiConnect is not ready. Trying to start Anki before Anki MCP tool use...");
  const launched = launchAnki();
  const ready = launched ? await waitForAnkiConnect(startTimeoutMs) : false;
  minimizeAnkiWindows();

  if (ready) {
    writeOutput({
      decision: "allow",
      hookSpecificOutput: {
        additionalContext: `Anki is running and AnkiConnect is ready at ${ankiConnectUrl}.`,
      },
      suppressOutput: true,
    });
    return;
  }

  writeOutput({
    decision: "allow",
    hookSpecificOutput: {
      additionalContext:
        `Anki MCP may fail: AnkiConnect did not answer at ${ankiConnectUrl}. ` +
        "Open Anki Desktop and confirm the AnkiConnect add-on is installed.",
    },
    suppressOutput: true,
  });
}

main().catch((error) => {
  console.error(`ensure_anki hook failed open: ${error instanceof Error ? error.message : String(error)}`);
  writeOutput({ decision: "allow", suppressOutput: true });
});
