"""Download model weights from the HuggingFace hub without the HF CLI.

The official command line tool moved from ``huggingface-cli`` to ``hf`` and its
entry point is not always on PATH inside a uv-managed venv, so the project fetches
weights itself: one HTTPS request for the model card, then one per file.

Only stdlib is used for the transfer; exporting a ``.pt`` checkpoint to ONNX uses
``ultralytics`` when it is installed and is skipped otherwise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_ENDPOINT = "https://hf-mirror.com"
DEFAULT_REPO = "ogkalu/comic-speech-bubble-detector"
CHECKPOINT_SUFFIXES = (".pt", ".pth", ".bin")
SKIP_PATTERNS = (".gitattributes", "README.md", "LICENSE", "LICENSE.md", ".md")


def endpoint() -> str:
    """Hub endpoint, honouring ``HF_ENDPOINT`` (the mirror is the default)."""
    return os.environ.get("HF_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")


def model_card(repo: str, base: str | None = None) -> dict:
    """Fetch the repository's file list as JSON."""
    url = f"{(base or endpoint())}/api/models/{repo}"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def weight_files(info: dict, base: str | None = None, repo: str = "") -> list[tuple[str, str]]:
    """``(relative path, download url)`` for the files worth downloading."""
    root = (base or endpoint()).rstrip("/")
    files: list[tuple[str, str]] = []
    for sibling in info.get("siblings", []):
        name = str(sibling.get("rfilename", ""))
        if not name or name.endswith(SKIP_PATTERNS):
            continue
        if not name.endswith((".pt", ".pth", ".bin", ".onnx", ".json", ".yaml", ".yml")):
            continue
        files.append((name, f"{root}/{repo}/resolve/main/{name}"))
    return files


def download(url: str, destination: Path) -> Path:
    """Download one file, creating parent directories as needed."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as handle:
        while chunk := response.read(1 << 20):
            handle.write(chunk)
    temporary.replace(destination)
    return destination


def fetch(
    repo: str = DEFAULT_REPO,
    destination: Path = Path("data/models/bubble-src"),
    base: str | None = None,
    export: bool = True,
    imgsz: int = 640,
) -> Path | None:
    """Download a repo and optionally export its checkpoint to ONNX.

    Returns the exported ONNX path, or ``None`` when no export happened.
    """
    info = model_card(repo, base)
    files = weight_files(info, base, repo)
    if not files:
        raise RuntimeError(f"no downloadable files in {repo}")
    for name, url in files:
        target = destination / name
        if target.is_file():
            print(f"skip {name} (already present)")
            continue
        print(f"download {name} -> {target}")
        download(url, target)

    checkpoint = next(
        (destination / name for name, _ in files if name.endswith(CHECKPOINT_SUFFIXES)),
        None,
    )
    if not export or checkpoint is None:
        return None
    return export_onnx(checkpoint, destination, imgsz)


def export_onnx(checkpoint: Path, destination: Path, imgsz: int = 640) -> Path | None:
    """Export a YOLO checkpoint with ultralytics; returns the ONNX path."""
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        print(
            "ultralytics is not installed, skipping export.\n"
            "  uv pip install ultralytics\n"
            f"  python -c \"from ultralytics import YOLO; "
            f"YOLO(r'{checkpoint}').export(format='onnx', imgsz={imgsz})\"",
            file=sys.stderr,
        )
        return None

    code = (
        "import sys\n"
        "from ultralytics import YOLO\n"
        "model = YOLO(sys.argv[1])\n"
        "print(model.export(format='onnx', imgsz=int(sys.argv[2]), opset=12, simplify=True))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(checkpoint), str(imgsz)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
        return None

    produced = sorted(checkpoint.parent.glob("*.onnx"))
    if not produced:
        print("export finished but no .onnx was produced", file=sys.stderr)
        return None
    target = destination.parent / "bubble_detector.onnx"
    produced[0].replace(target)
    print(f"exported {target}")
    return target
