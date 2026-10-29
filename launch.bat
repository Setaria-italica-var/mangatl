@echo off
rem One-click start without building an exe (uses the bundled venv).
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\launcher.py %*
) else (
  python tools\launcher.py %*
)
pause