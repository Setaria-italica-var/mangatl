"""Build a bat-launched portable folder with an embeddable Python runtime.

Layout under ``dist/mangatl-portable``::

    启动.bat
    runtime/            embeddable CPython + every wheel the venv uses
    data/models, data/hf
    data/settings.json  (created on first run)

No installer, no registry; the folder can be copied to another Windows machine.
"""

from __future__ import annotations

import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "mangatl-portable"
CACHE = ROOT / ".tmp" / "python-3.12.10-embed-amd64.zip"
URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
SITE = DIST / "runtime" / "Lib" / "site-packages"
PTH = (
    "python312.zip\n"
    ".\n"
    "Lib\\site-packages\n"
    "Lib\\site-packages\\win32\n"
    "Lib\\site-packages\\win32\\lib\n"
    "Lib\\site-packages\\Pythonwin\n"
    "Lib\\site-packages\\pywin32_system32\n"
    "import site\n"
)

BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%CD%\\runtime\\Lib\\site-packages"
set "PATH=%CD%\\runtime;%PATH%"
set "PATH=%CD%\\runtime\\Lib\\site-packages\\torch\\lib;%PATH%"
set "PATH=%CD%\\runtime\\Lib\\site-packages\\pywin32_system32;%PATH%"
runtime\\python.exe -m mangatl gui %*
if errorlevel 1 pause
"""

README = """mangatl 便携版（bat 启动）

1. 双击「启动.bat」打开编辑器。
2. 模型已随包携带（data/models、data/hf），不需要联网下载。
3. 翻译 Key 在「设置」里填写；勾选「记住 Key」会用 Windows DPAPI
   加密保存到 data/secrets.bin（只对当前 Windows 用户有效）。
4. 整个文件夹可以拷到其它 Windows 电脑；不要单独移动 runtime 目录。
5. 命令行用法：
   runtime\\python.exe -m mangatl run <项目目录> --stages detect,ocr
"""


def download() -> Path:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE.is_file() and CACHE.stat().st_size > 10_000_000:
        return CACHE
    print(f"downloading {URL}")
    request = urllib.request.Request(URL, headers={"User-Agent": "mangatl-build"})
    with urllib.request.urlopen(request, timeout=120) as response:
        CACHE.write_bytes(response.read())
    return CACHE


def unpack() -> None:
    runtime = DIST / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(download()) as archive:
        archive.extractall(runtime)
    pth = runtime / "python312._pth"
    pth.write_text(PTH, encoding="utf-8")
    print("runtime ready:", runtime)


def copy_packages() -> None:
    source = ROOT / ".venv" / "Lib" / "site-packages"
    SITE.mkdir(parents=True, exist_ok=True)
    skip = {"pip", "setuptools", "pkg_resources", "wheel"}
    for entry in source.iterdir():
        if entry.name in skip:
            continue
        target = SITE / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)
    shutil.copytree(ROOT / "src" / "mangatl", SITE / "mangatl", dirs_exist_ok=True)
    print("site-packages ready")


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


def main() -> int:
    unpack()
    copy_packages()
    copy_data()
    (DIST / "启动.bat").write_text(BAT, encoding="utf-8")
    (DIST / "使用说明.txt").write_text(README, encoding="utf-8")
    size = sum(path.stat().st_size for path in DIST.rglob("*") if path.is_file())
    print(f"done: {DIST} ({size / 1024 / 1024:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
