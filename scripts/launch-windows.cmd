@echo off
setlocal
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-start.ps1" %*
if errorlevel 1 (
  echo.
  echo AdaptivMCP did not start. See the error above.
  pause
  exit /b 1
)
