#Requires -Version 5.1
<#
.SYNOPSIS
Reset the Medical Notes Workbench Python environment on Windows and rebuild it with uv.

.DESCRIPTION
By default this script resets only the Medical Notes Workbench environment.
Pass -RemoveGlobalPython -YesReallyRemoveGlobalPython to uninstall global
Python Software Foundation installs and the Python Launcher, clean Python PATH
entries, then rebuild everything with uv-managed Python.
Pass -FullReset for the one-command workflow: ensure standalone uv, remove
global Python/launcher, clean WindowsApps aliases from PATH, sync, and check.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string] $ExtensionRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string] $StateDir = (Join-Path $HOME ".gemini\medical-notes-workbench"),
    [string] $PythonVersion = "3.12",
    [switch] $FullReset,
    [switch] $RemoveGlobalPython,
    [switch] $YesReallyRemoveGlobalPython,
    [switch] $RemoveWindowsAppsFromPath,
    [switch] $Dev,
    [switch] $Pdf,
    [switch] $SkipChecks
)

$ErrorActionPreference = "Stop"

if ($FullReset) {
    $RemoveGlobalPython = $true
    $YesReallyRemoveGlobalPython = $true
    $RemoveWindowsAppsFromPath = $true
}

function Write-Step {
    param([string] $Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [string] $FilePath,
        [string[]] $Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Get-PythonUninstallEntries {
    $roots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )

    foreach ($root in $roots) {
        Get-ItemProperty -Path $root -ErrorAction SilentlyContinue |
            Where-Object {
                $name = [string] $_.DisplayName
                $publisher = [string] $_.Publisher
                $name -and (
                    $publisher -match "Python Software Foundation" -or
                    $name -match "^Python( \d| Launcher|$)"
                )
            } |
            ForEach-Object {
                [pscustomobject] @{
                    DisplayName = [string] $_.DisplayName
                    Publisher = [string] $_.Publisher
                    QuietUninstallString = [string] $_.QuietUninstallString
                    UninstallString = [string] $_.UninstallString
                    RegistryPath = [string] $_.PSPath
                }
            }
    }
}

function Get-PythonInstallRoots {
    $roots = @(
        "HKCU:\Software\Python\PythonCore\*\InstallPath",
        "HKLM:\Software\Python\PythonCore\*\InstallPath",
        "HKLM:\Software\WOW6432Node\Python\PythonCore\*\InstallPath"
    )

    foreach ($root in $roots) {
        Get-ItemProperty -Path $root -ErrorAction SilentlyContinue |
            ForEach-Object {
                if ($_.ExecutablePath) {
                    Split-Path -Parent ([string] $_.ExecutablePath)
                }
                elseif ($_.PSChildName) {
                    [string] $_.PSChildName
                }
                elseif ($_.InstallPath) {
                    [string] $_.InstallPath
                }
            }
    }
}

function Get-CommandPaths {
    param([string[]] $Names)

    foreach ($name in $Names) {
        $output = & where.exe $name 2>$null
        if ($LASTEXITCODE -eq 0) {
            $output | Where-Object { $_ }
        }
    }
}

function ConvertTo-QuietUninstallCommand {
    param([object] $Entry)

    $cmdLine = if ($Entry.QuietUninstallString) {
        $Entry.QuietUninstallString
    }
    else {
        $Entry.UninstallString
    }

    if (-not $cmdLine) {
        return $null
    }

    if ($cmdLine -match "\{[0-9A-Fa-f-]{36}\}") {
        return "msiexec.exe /x $($Matches[0]) /qn /norestart"
    }

    if (-not $Entry.QuietUninstallString -and $cmdLine -notmatch "(?i)(/quiet|/qn|/passive)") {
        $cmdLine = "$cmdLine /quiet"
    }

    return $cmdLine
}

function Invoke-GlobalPythonRemoval {
    param([string[]] $KnownRoots)

    $entries = @(Get-PythonUninstallEntries | Sort-Object RegistryPath -Unique)
    Write-Step "Inventario de Python global"

    $commandPaths = @(Get-CommandPaths @("python", "python3", "py") | Sort-Object -Unique)
    if ($commandPaths.Count -gt 0) {
        Write-Host "Comandos encontrados no PATH:"
        $commandPaths | ForEach-Object { Write-Host "  $_" }
    }
    else {
        Write-Host "Nenhum python/python3/py encontrado no PATH."
    }

    if ($entries.Count -gt 0) {
        Write-Host "Instalacoes registradas para remocao:"
        $entries | ForEach-Object { Write-Host "  $($_.DisplayName) [$($_.Publisher)]" }
    }
    else {
        Write-Host "Nenhuma instalacao PSF/Python Launcher registrada para remocao."
    }

    if (-not $YesReallyRemoveGlobalPython) {
        throw "Remocao global bloqueada. Rode novamente com -RemoveGlobalPython -YesReallyRemoveGlobalPython para confirmar."
    }

    foreach ($entry in $entries) {
        $cmdLine = ConvertTo-QuietUninstallCommand $entry
        if (-not $cmdLine) {
            Write-Warning "Sem comando de uninstall para $($entry.DisplayName). Pulei."
            continue
        }
        if ($PSCmdlet.ShouldProcess($entry.DisplayName, "Uninstall global Python")) {
            Write-Step "Removendo $($entry.DisplayName)"
            $process = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/s", "/c", $cmdLine) -Wait -PassThru
            if ($process.ExitCode -ne 0) {
                Write-Warning "Uninstall retornou codigo $($process.ExitCode): $($entry.DisplayName)"
            }
        }
    }

    Remove-PythonEnvironmentVariables
    Remove-PythonPathEntries -KnownRoots $KnownRoots
    Remove-ResidualPythonDirectories -KnownRoots $KnownRoots
}

function Remove-PythonEnvironmentVariables {
    foreach ($target in @("User", "Machine")) {
        foreach ($name in @("PYTHONHOME", "PYTHONPATH", "PYLAUNCHER_ALLOW_INSTALL", "PYLAUNCHER_NO_SEARCH_PATH")) {
            try {
                if ([Environment]::GetEnvironmentVariable($name, $target)) {
                    if ($PSCmdlet.ShouldProcess("$target $name", "Remove Python environment variable")) {
                        [Environment]::SetEnvironmentVariable($name, $null, $target)
                    }
                }
            }
            catch {
                Write-Warning "Nao consegui limpar $target ${name}: $($_.Exception.Message)"
            }
        }
    }
}

function Test-PythonPathEntry {
    param(
        [string] $Entry,
        [string[]] $KnownRoots
    )

    if (-not $Entry) {
        return $false
    }

    $expanded = [Environment]::ExpandEnvironmentVariables($Entry).Trim('"').TrimEnd("\")
    if (-not $expanded) {
        return $false
    }

    if ($RemoveWindowsAppsFromPath -and $expanded -like "*\Microsoft\WindowsApps") {
        return $true
    }

    foreach ($root in $KnownRoots) {
        if ($root) {
            $normalizedRoot = [Environment]::ExpandEnvironmentVariables($root).Trim('"').TrimEnd("\")
            if ($normalizedRoot -and $expanded.StartsWith($normalizedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
        }
    }

    return ($expanded -match "(?i)\\Programs\\Python\\Python\d+" -or
            $expanded -match "(?i)\\Python\d+(\\Scripts)?$" -or
            $expanded -match "(?i)\\PythonCore\\" -or
            $expanded -match "(?i)\\Python\\Launcher$")
}

function Remove-PythonPathEntries {
    param([string[]] $KnownRoots)

    foreach ($target in @("User", "Machine")) {
        try {
            $pathValue = [Environment]::GetEnvironmentVariable("Path", $target)
            if (-not $pathValue) {
                continue
            }
            $entries = @($pathValue -split ";" | Where-Object { $_ -ne "" })
            $kept = @()
            $removed = @()
            foreach ($entry in $entries) {
                if (Test-PythonPathEntry -Entry $entry -KnownRoots $KnownRoots) {
                    $removed += $entry
                }
                else {
                    $kept += $entry
                }
            }
            if ($removed.Count -gt 0) {
                if ($PSCmdlet.ShouldProcess("$target PATH", "Remove Python PATH entries")) {
                    [Environment]::SetEnvironmentVariable("Path", ($kept -join ";"), $target)
                }
                Write-Host "PATH $target: removido"
                $removed | ForEach-Object { Write-Host "  $_" }
            }
        }
        catch {
            Write-Warning "Nao consegui editar PATH $target: $($_.Exception.Message)"
        }
    }
}

function Remove-ResidualPythonDirectories {
    param([string[]] $KnownRoots)

    $candidates = @()
    $candidates += $KnownRoots
    if ($env:LOCALAPPDATA) {
        $candidates += Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Programs\Python") -Directory -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
    }
    if ($env:ProgramFiles) {
        $candidates += Get-ChildItem -Path $env:ProgramFiles -Directory -Filter "Python*" -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
    }
    if (${env:ProgramFiles(x86)}) {
        $candidates += Get-ChildItem -Path ${env:ProgramFiles(x86)} -Directory -Filter "Python*" -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
    }

    $safeCandidates = $candidates |
        Where-Object { $_ -and (Test-Path $_) } |
        Sort-Object -Unique |
        Where-Object {
            $_ -match "(?i)\\Programs\\Python\\Python\d+" -or
            $_ -match "(?i)\\Python\d+$" -or
            $_ -match "(?i)\\Python\\Launcher$"
        }

    foreach ($dir in $safeCandidates) {
        if ($PSCmdlet.ShouldProcess($dir, "Remove residual Python directory")) {
            Write-Step "Removendo diretorio residual: $dir"
            Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Install-UvStandalone {
    Write-Step "Instalando/atualizando uv standalone com o instalador oficial"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao instalar uv."
    }
}

function Resolve-Uv {
    param([switch] $ForceInstall)

    if (-not $ForceInstall) {
        $command = Get-Command uv -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    else {
        Write-Step "Garantindo uv standalone antes do reset global"
    }

    Install-UvStandalone

    $candidatePaths = @(
        (Join-Path $HOME ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\uv\uv.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($candidate in $candidatePaths) {
        $candidateDir = Split-Path -Parent $candidate
        if (($env:Path -split ";") -notcontains $candidateDir) {
            $env:Path = "$candidateDir;$env:Path"
        }
        return $candidate
    }

    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw "uv foi instalado, mas nao entrou no PATH desta sessao. Abra um novo PowerShell e rode novamente."
}

$ExtensionRoot = (Resolve-Path $ExtensionRoot).Path
if (-not (Test-Path (Join-Path $ExtensionRoot "pyproject.toml"))) {
    throw "ExtensionRoot invalido: nao encontrei pyproject.toml em $ExtensionRoot"
}

$knownPythonRoots = @(Get-PythonInstallRoots | Where-Object { $_ } | Sort-Object -Unique)

Write-Step "Preparando diretorio persistente"
New-Item -ItemType Directory -Force $StateDir | Out-Null

$configPath = Join-Path $StateDir "config.toml"
if (-not (Test-Path $configPath)) {
    $configExample = Join-Path $ExtensionRoot "config.example.toml"
    if (Test-Path $configExample) {
        Copy-Item $configExample $configPath
        Write-Host "config.toml criado em $configPath"
    }
}

$envPath = Join-Path $StateDir ".env"
if (-not (Test-Path $envPath)) {
    $envExample = Join-Path $ExtensionRoot ".env.example"
    if (Test-Path $envExample) {
        Copy-Item $envExample $envPath
        Write-Host ".env criado em $envPath"
    }
}

$uv = Resolve-Uv -ForceInstall:$FullReset
Write-Step "Usando uv: $uv"
Invoke-Checked $uv @("--version")

if ($RemoveGlobalPython) {
    Invoke-GlobalPythonRemoval -KnownRoots $knownPythonRoots
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Step "Instalando Python gerenciado pelo uv ($PythonVersion)"
Invoke-Checked $uv @("python", "install", $PythonVersion)

$persistentVenv = Join-Path $StateDir ".venv"
$bundleVenv = Join-Path $ExtensionRoot ".venv"
foreach ($venv in @($persistentVenv, $bundleVenv)) {
    if (Test-Path $venv) {
        if ($PSCmdlet.ShouldProcess($venv, "Remove project virtual environment")) {
            Write-Step "Removendo ambiente antigo: $venv"
            Remove-Item -LiteralPath $venv -Recurse -Force
        }
    }
}

$env:UV_PROJECT_ENVIRONMENT = $persistentVenv
$syncArgs = @("sync", "--python", $PythonVersion)
if ($Dev) {
    $syncArgs += @("--extra", "dev")
}
if ($Pdf) {
    $syncArgs += @("--extra", "pdf")
}

Write-Step "Sincronizando dependencias com uv"
Push-Location $ExtensionRoot
try {
    Invoke-Checked $uv $syncArgs

    if (-not $SkipChecks) {
        Write-Step "Rodando checks basicos"
        Invoke-Checked $uv @("run", "python", "-m", "enricher", "--help")
        Invoke-Checked $uv @("run", "python", "scripts\mednotes\med_ops.py", "validate", "--config", $configPath)
        Invoke-Checked $uv @("run", "python", "scripts\mednotes\med_linker.py", "--help")
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Pronto. Ambiente Python do workbench reconstruido com uv." -ForegroundColor Green
Write-Host "ExtensionRoot: $ExtensionRoot"
Write-Host "StateDir:      $StateDir"
Write-Host "Venv uv:       $persistentVenv"
Write-Host ""
Write-Host "Para comandos manuais nesta sessao:"
Write-Host ('$env:UV_PROJECT_ENVIRONMENT = "{0}"' -f $persistentVenv)
Write-Host 'uv run python scripts\mednotes\med_ops.py fix-wiki --dry-run --json'
if ($RemoveGlobalPython) {
    Write-Host ""
    Write-Host "Se 'where python' ainda apontar para Microsoft\\WindowsApps, desative o alias"
    Write-Host "python.exe/python3.exe em Settings > Apps > Advanced app settings > App execution aliases,"
    Write-Host "ou rode novamente com -RemoveWindowsAppsFromPath para remover WindowsApps do PATH."
}
