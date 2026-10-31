@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "MANGATL_HOME=%CD%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "runtime\python.exe" (
  echo 缺少 runtime\python.exe。
  echo 请先运行 setup.bat，或重新解压便携包。
  pause
  exit /b 2
)

"runtime\python.exe" "tools\check_env.py"
if errorlevel 1 (
  echo.
  echo 环境检查未通过：运行 setup.bat 更新依赖后重试。
  pause
  exit /b 1
)

"runtime\python.exe" -m mangatl gui %*
set "code=%errorlevel%"
if not "%code%"=="0" (
  echo.
  echo 启动失败，退出码 %code%。可运行「诊断.bat」查看环境。
  pause
)
exit /b %code%