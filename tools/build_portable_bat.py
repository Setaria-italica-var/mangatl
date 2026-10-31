"""Build ``dist/mangatl-portable`` from the runtime that lives inside the repo.

No Python install, no pip download: the portable folder is a straight copy of
``runtime\\`` plus models and a couple of bat files.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "mangatl-portable"
RUNTIME = ROOT / "runtime"

README = """mangatl 便携版（bat 启动）

1. 双击「启动.bat」打开编辑器。
2. 模型和 Python 运行时都已随包携带（runtime\\、data\\models、data\\hf），
   目标电脑不需要安装 Python，也不需要联网下载模型。
3. 翻译 Key 在「设置」里填写；勾选「记住 Key」会用 Windows DPAPI
   加密保存到 data/secrets.bin（只对当前 Windows 用户有效）。
4. 整个文件夹可以拷到其它 Windows 电脑；不要单独移动 runtime 目录。
5. 命令行用法：
   runtime\\python.exe -m mangatl run <项目目录> --stages detect,ocr
6. 出问题时双击「诊断.bat」，把生成的「诊断结果.txt」发回来。
7. 依赖版本写在 requirements.txt；更新依赖需在装有 Python 3.12 的机器上运行
   setup.bat（会安装到 runtime\Lib\site-packages），不需要改启动脚本。
"""

DIAG_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在收集环境信息，请稍候…
runtime\\python.exe "诊断.py" > "诊断结果.txt" 2>&1
type "诊断结果.txt"
echo.
echo 已保存到：%~dp0诊断结果.txt
pause
"""


def sync_package() -> int:
    script = ROOT / "tools" / "sync_runtime.py"
    return subprocess.call([str(RUNTIME / "python.exe"), str(script)], cwd=ROOT)


def copy_runtime() -> None:
    target = DIST / "runtime"
    if target.exists():
        shutil.rmtree(target)
    print("copying runtime …")
    shutil.copytree(RUNTIME, target)


def copy_data() -> None:
    data = DIST / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name in ("models", "hf"):
        source = ROOT / "data" / name
        if not source.is_dir():
            print(f"skip missing {source}")
            continue
        target = data / name
        if target.exists():
            shutil.rmtree(target)
        print(f"copying {name} …")
        shutil.copytree(source, target)


def write_files() -> None:
    shutil.copy2(ROOT / "启动.bat", DIST / "启动.bat")
    shutil.copy2(ROOT / "requirements.txt", DIST / "requirements.txt")
    (DIST / "tools").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "tools" / "check_env.py", DIST / "tools" / "check_env.py")
    shutil.copy2(ROOT / "tools" / "diagnose.py", DIST / "诊断.py")
    (DIST / "诊断.bat").write_text(DIAG_BAT, encoding="utf-8")
    (DIST / "使用说明.txt").write_text(README, encoding="utf-8")


def main() -> int:
    if not (RUNTIME / "python.exe").is_file():
        print("runtime/python.exe missing; the project runtime was not found")
        return 2
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    if sync_package() != 0:
        return 2
    copy_runtime()
    copy_data()
    write_files()
    size = sum(path.stat().st_size for path in DIST.rglob("*") if path.is_file())
    print(f"done: {DIST} ({size / 1024 / 1024:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
