@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "RESET_SCRIPT=%SCRIPT_DIR%reset_windows_python_uv.ps1"

if not exist "%RESET_SCRIPT%" (
  echo Reset script not found: %RESET_SCRIPT% 1>&2
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%RESET_SCRIPT%" -FullReset %*
exit /b %ERRORLEVEL%
