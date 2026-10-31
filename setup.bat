@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

py -3.12 "tools\setup_env.py" %*
if errorlevel 9009 (
  python "tools\setup_env.py" %*
)
if errorlevel 1 pause