"""One-click launcher: check the environment, install what is missing, start the GUI.

Built into ``mangatl.exe`` with PyInstaller (see ``tools/build_launcher.py``), but it
also runs directly with any Python 3.10+:

    python tools/launcher.py            # start the editor
    python tools/launcher.py --check    # only report what is missing

Design notes
------------
* The exe stays tiny: Python, Qt and the models are *not* frozen into it.
* The launcher prefers ``runtime\\python`` (embeddable) then ``.venv`` then the
  system interpreter, and creates ``.venv`` when it has to.
* Installs come from ``wheels\\`` first (offline), then from the configured index.
* Long steps print what they are doing; failures pause so a double-click window
  does not vanish before the message is read.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

MODULES = (
    ("PySide6", "PySide6"),
    ("qfluentwidgets", "PySide6-Fluent-Widgets"),
    ("numpy", "numpy"),
    ("PIL", "Pillow"),
    ("onnxruntime", "onnxruntime"),
    ("torch", "torch"),
    ("mangatl", None),
)

REQUIRED_MODELS = (
    ("data/models/comictextdetector.pt.onnx", "文本检测 (CTD)"),
    ("data/models/bubble_detector.onnx", "气泡检测"),
    ("data/models/mit/ocr-ctc.ckpt", "MIT48px OCR"),
    ("data/models/mit/alphabet-all-v5.txt", "MIT48px 字典"),
)

PYTHON_URL = "https://www.python.org/downloads/windows/"


def app_root() -> Path:
    """Folder that contains ``pyproject.toml``, ``src/`` and ``data/``."""
    start = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    return start


LOG_PATH: Path | None = None


def log(message: str) -> None:
    print(message, flush=True)
    if LOG_PATH is not None:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        except OSError:
            pass


def configure_stdio() -> None:
    """Chinese Windows consoles default to GBK; never crash on a log line."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            continue


def run(command: list[str], cwd: Path, quiet: bool = False) -> int:
    log("  $ " + " ".join(str(part) for part in command))
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            check=False,
            text=True,
            stdout=subprocess.PIPE if quiet else None,
            stderr=subprocess.STDOUT if quiet else None,
        )
    except OSError as exc:
        log(f"  ! 无法执行：{exc}")
        return 127
    return completed.returncode


def python_version(path: Path) -> tuple[int, int] | None:
    try:
        output = subprocess.run(
            [str(path), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if output.returncode != 0:
        return None
    parts = output.stdout.strip().split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1])


def find_python(root: Path) -> tuple[Path | None, str]:
    """Return (interpreter, description) using the project-first order."""
    candidates = [
        (root / "runtime" / "python" / "python.exe", "内置运行时"),
        (root / ".venv" / "Scripts" / "python.exe", "项目 .venv"),
    ]
    for path, label in candidates:
        if path.is_file() and python_version(path) is not None:
            return path, label

    for name in ("python", "py"):
        found = shutil.which(name)
        if not found:
            continue
        version = python_version(Path(found))
        if version is not None and version >= (3, 10):
            return Path(found), f"系统 Python {version[0]}.{version[1]}"
    return None, ""


def ensure_venv(root: Path, base: Path) -> Path | None:
    """Create ``.venv`` from ``base`` when the project has none."""
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    if venv_python.is_file():
        return venv_python
    log("创建虚拟环境 .venv …")
    if run([str(base), "-m", "venv", str(root / ".venv")], root) != 0:
        return None
    return venv_python if venv_python.is_file() else None


def missing_modules(python: Path, root: Path) -> list[str]:
    code = (
        "import importlib.util, json, sys\n"
        f"names = {[module for module, _ in MODULES]!r}\n"
        "print(json.dumps([n for n in names if importlib.util.find_spec(n) is None]))\n"
    )
    completed = subprocess.run(
        [str(python), "-c", code],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        return [module for module, _ in MODULES]
    try:
        import json

        return list(json.loads(completed.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        return [module for module, _ in MODULES]


def install_dependencies(python: Path, root: Path) -> bool:
    wheels = root / "wheels"
    base = [str(python), "-m", "pip", "install", "--upgrade"]
    if wheels.is_dir() and any(wheels.iterdir()):
        log("从 wheels/ 离线安装依赖 …")
        code = run([*base, "--no-index", "--find-links", str(wheels), "-e", ".[gui]"], root)
        if code == 0:
            return True
        log("  离线安装失败，尝试在线安装")
    index = os.environ.get("MANGATL_PIP_INDEX", "")
    extra = ["--index-url", index] if index else []
    log("在线安装依赖（首次约 1–2 GB，请耐心等待）…")
    return run([*base, *extra, "-e", ".[gui]"], root) == 0


def missing_models(root: Path) -> list[tuple[str, str]]:
    return [(path, label) for path, label in REQUIRED_MODELS if not (root / path).is_file()]


def fetch_models(python: Path, root: Path) -> None:
    log("下载缺失的模型 …")
    run([str(python), "-m", "mangatl", "fetch-models"], root)
    log("提示：可选下载 LaMa 局部重绘权重（约 208 MB）")
    log("      python -m mangatl fetch-models --lama")


def check(python: Path | None, root: Path) -> int:
    log(f"程序目录：{root}")
    if python is None:
        log("✗ 没有找到 Python 3.10+")
        log(f"  请安装：{PYTHON_URL}")
        return 1
    log(f"✓ Python：{python}（{python_version(python)}）")

    missing = missing_modules(python, root)
    log("✓ 依赖齐全" if not missing else f"✗ 缺少依赖：{', '.join(missing)}")

    models = missing_models(root)
    log("✓ 模型齐全" if not models else "✗ 缺少模型：" + "、".join(label for _, label in models))

    lama = root / "data/models/lama.onnx"
    log(
        "✓ LaMa 权重已就绪"
        if lama.is_file() and lama.stat().st_size > 150_000_000
        else "· LaMa 未安装（局部重绘用 OpenCV 兜底，可用 fetch-models --lama 下载）"
    )
    return 0 if not missing and not models else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mangatl launcher")
    parser.add_argument("--check", action="store_true", help="只检测环境，不安装也不启动")
    parser.add_argument("--no-launch", action="store_true", help="安装完成后不启动 GUI")
    parser.add_argument("--no-pause", action="store_true", help="失败时不等待回车")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="透传给 mangatl gui 的参数")
    options = parser.parse_args(argv)

    configure_stdio()
    global LOG_PATH
    root = app_root()
    LOG_PATH = (
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else root
    ) / "mangatl-launcher.log"
    try:
        LOG_PATH.write_text("", encoding="utf-8")
    except OSError:
        LOG_PATH = None
    log("=" * 60)
    log("  mangatl 启动器")
    log("=" * 60)

    python, label = find_python(root)
    if options.check:
        return check(python, root)

    if python is None:
        log("✗ 没有找到 Python 3.10+")
        log(f"  请先安装 Python 3.10 及以上版本：{PYTHON_URL}")
        log("  安装时勾选 “Add python.exe to PATH”。")
        return _pause(1, options)

    if "系统" in label:
        created = ensure_venv(root, python)
        if created is None:
            log("✗ 创建虚拟环境失败")
            return _pause(1, options)
        python = created
        label = "项目 .venv（新建）"
    log(f"✓ 使用 {label}：{python}")

    missing = missing_modules(python, root)
    if missing:
        log(f"缺少依赖：{', '.join(missing)}")
        if not install_dependencies(python, root):
            log("✗ 依赖安装失败，请检查网络或 MANGATL_PIP_INDEX")
            return _pause(1, options)
    else:
        log("✓ 依赖齐全")

    models = missing_models(root)
    if models:
        log("缺少模型：" + "、".join(label for _, label in models))
        fetch_models(python, root)
        models = missing_models(root)
        if models:
            log("✗ 仍有模型缺失，编辑器仍可启动但相关功能不可用")
        else:
            log("✓ 模型齐全")
    else:
        log("✓ 模型齐全")

    if options.no_launch:
        return 0

    log("启动编辑器 …")
    command = [str(python), "-m", "mangatl", "gui", *options.args]
    try:
        completed = subprocess.run(command, cwd=str(root))
    except KeyboardInterrupt:
        return 0
    if completed.returncode != 0:
        log(f"编辑器退出码 {completed.returncode}")
        return _pause(completed.returncode, options)
    return 0


def _pause(code: int, options) -> int:
    if not options.no_pause and sys.stdin is not None and sys.stdin.isatty():
        with contextlib.suppress(EOFError):
            input("按回车退出 …")
    return code


def _entry() -> int:
    """Keep a double-click window open and leave a log when something explodes."""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - last-resort diagnostic
        import traceback

        print(traceback.format_exc())
        try:
            target = Path(sys.executable).resolve().parent / "mangatl-launcher-crash.log"
            target.write_text(traceback.format_exc(), encoding="utf-8")
            print(f"错误已写入：{target}")
        except OSError:
            pass
        with contextlib.suppress(EOFError, RuntimeError):
            input("启动失败，按回车退出 …")
        return 1


if __name__ == "__main__":
    raise SystemExit(_entry())
