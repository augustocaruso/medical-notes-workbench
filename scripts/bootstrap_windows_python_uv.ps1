#Requires -Version 5.1
<#
.SYNOPSIS
One-command bootstrap for resetting Windows Python to uv for Medical Notes Workbench.

.DESCRIPTION
This script is safe to run from an installed extension or through irm/iex. It
downloads the latest reset script when possible, falls back to the bundled copy,
and runs a full reset.
#>

[CmdletBinding()]
param(
    [string] $ExtensionRoot,
    [string] $Branch = "gemini-cli-extension",
    [switch] $SkipScriptUpdate,
    [switch] $SkipChecks,
    [switch] $NoElevate
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string] $Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-SelfElevatedIfNeeded {
    if ($NoElevate -or (Test-IsAdmin)) {
        return
    }

    if (-not $PSCommandPath) {
        Write-Warning "Nao estou como Administrador e nao consigo auto-elevar script sem arquivo. Continuando mesmo assim."
        return
    }

    Write-Step "Reabrindo como Administrador"
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "`"$PSCommandPath`"",
        "-NoElevate"
    )
    if ($ExtensionRoot) {
        $arguments += @("-ExtensionRoot", "`"$ExtensionRoot`"")
    }
    if ($Branch) {
        $arguments += @("-Branch", "`"$Branch`"")
    }
    if ($SkipScriptUpdate) {
        $arguments += "-SkipScriptUpdate"
    }
    if ($SkipChecks) {
        $arguments += "-SkipChecks"
    }

    Start-Process -FilePath "powershell.exe" -ArgumentList ($arguments -join " ") -Verb RunAs | Out-Null
    exit 0
}

function Resolve-ExtensionRoot {
    if ($ExtensionRoot) {
        return (Resolve-Path $ExtensionRoot).Path
    }

    if ($PSScriptRoot) {
        $candidate = (Resolve-Path (Join-Path $PSScriptRoot "..") -ErrorAction SilentlyContinue)
        if ($candidate -and (Test-Path (Join-Path $candidate.Path "pyproject.toml"))) {
            return $candidate.Path
        }
    }

    $default = Join-Path $HOME ".gemini\extensions\medical-notes-workbench"
    if (Test-Path (Join-Path $default "pyproject.toml")) {
        return $default
    }

    throw "Nao encontrei a extensao em $default. Instale/atualize medical-notes-workbench primeiro."
}

function Update-ResetScript {
    param(
        [string] $Root,
        [string] $ResetScript
    )

    if ($SkipScriptUpdate) {
        return
    }

    $url = "https://raw.githubusercontent.com/augustocaruso/medical-notes-workbench/$Branch/scripts/reset_windows_python_uv.ps1"
    Write-Step "Atualizando reset script"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $content = Invoke-WebRequest -Uri $url -UseBasicParsing
        if (-not $content.Content -or $content.Content -notmatch "param\(") {
            throw "conteudo remoto inesperado"
        }
        New-Item -ItemType Directory -Force (Split-Path -Parent $ResetScript) | Out-Null
        if (Test-Path $ResetScript) {
            Copy-Item -LiteralPath $ResetScript -Destination "$ResetScript.bak" -Force
        }
        Set-Content -LiteralPath $ResetScript -Value $content.Content -Encoding UTF8
        Write-Host "Reset script atualizado: $ResetScript"
    }
    catch {
        Write-Warning "Nao consegui atualizar reset script pelo GitHub: $($_.Exception.Message)"
        if (-not (Test-Path $ResetScript)) {
            throw "Reset script local tambem nao existe: $ResetScript"
        }
        Write-Host "Usando reset script local: $ResetScript"
    }
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Este bootstrap e exclusivo para Windows."
}

Invoke-SelfElevatedIfNeeded

$root = Resolve-ExtensionRoot
$resetScript = Join-Path $root "scripts\reset_windows_python_uv.ps1"

Update-ResetScript -Root $root -ResetScript $resetScript

$argsForReset = @("-FullReset")
if ($SkipChecks) {
    $argsForReset += "-SkipChecks"
}

Write-Step "Executando reset completo"
& $resetScript @argsForReset
exit $LASTEXITCODE
