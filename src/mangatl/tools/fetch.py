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
OFFICIAL_ENDPOINT = "https://huggingface.co"
USER_AGENT = "mangatl/0.1 (+https://github.com/mangatl/mangatl)"
DIRECT_CANDIDATES = ("best.pt", "model.pt", "weights.pt", "model.onnx", "best.onnx")
DEFAULT_REPO = "ogkalu/comic-speech-bubble-detector-yolov8m"
KNOWN_REPOS = (
    "ogkalu/comic-speech-bubble-detector-yolov8m",
    "ogkalu/comic-text-and-bubble-detector",
    "kitsumed/yolov8m_seg-speech-bubble",
    "mayocream/speech-bubble-segmentation",
)
CHECKPOINT_SUFFIXES = (".pt", ".pth", ".bin")
SKIP_PATTERNS = (".gitattributes", "README.md", "LICENSE", "LICENSE.md", ".md")


def endpoint() -> str:
    """Hub endpoint, honouring ``HF_ENDPOINT`` (the mirror is the default)."""
    return os.environ.get("HF_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")


def _open(url: str, timeout: float):
    """Open a URL with a browser-like User-Agent (mirrors reject the default)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def model_card(repo: str, base: str | None = None) -> dict:
    """Fetch the repository's file list, falling back to the official hub."""
    bases = [base or endpoint()]
    if not base and bases[0] != OFFICIAL_ENDPOINT:
        bases.append(OFFICIAL_ENDPOINT)
    last_error: Exception | None = None
    for candidate in bases:
        url = f"{candidate.rstrip('/')}/api/models/{repo}"
        try:
            with _open(url, 60) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # try the next endpoint
            last_error = exc
    raise RuntimeError(
        f"cannot read model card for {repo}: {last_error}\n"
        "known repositories: " + ", ".join(KNOWN_REPOS) + "\n"
        "pass --repo <name> to try another one"
    ) from last_error


def direct_weight(repo: str, base: str | None = None) -> list[tuple[str, str]]:
    """Guess well-known checkpoint names when the API is unavailable."""
    bases = [base or endpoint()]
    if not base and bases[0] != OFFICIAL_ENDPOINT:
        bases.append(OFFICIAL_ENDPOINT)
    for candidate in bases:
        root = candidate.rstrip("/")
        for name in DIRECT_CANDIDATES:
            url = f"{root}/{repo}/resolve/main/{name}"
            try:
                with _open(url, 30) as response:
                    if response.status == 200:
                        return [(name, url)]
            except Exception:
                continue
    return []


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
    with _open(url, 120) as response, temporary.open("wb") as handle:
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
    try:
        info = model_card(repo, base)
        files = weight_files(info, base, repo)
    except Exception as exc:
        print(f"model card unavailable ({exc}); trying direct file names", file=sys.stderr)
        files = direct_weight(repo, base)
    if not files:
        raise RuntimeError(f"no downloadable files in {repo}")
    for name, url in files:
        target = destination / name
        if target.is_file():
            print(f"skip {name} (already present)")
            continue
        print(f"download {name} -> {target}")
        download(url, target)
        if target.stat().st_size < 1024:
            raise RuntimeError(f"{target} is suspiciously small ({target.stat().st_size} B)")

    checkpoint = next(
        (destination / name for name, _ in files if name.endswith(CHECKPOINT_SUFFIXES)),
        None,
    )
    if not export or checkpoint is None:
        return None
    return export_onnx(checkpoint, destination, imgsz, Path("data/ultralytics"))


def export_onnx(
    checkpoint: Path, destination: Path, imgsz: int = 640, config_dir: Path | None = None
) -> Path | None:
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
    environment = dict(os.environ)
    # Ultralytics writes settings to %APPDATA%; point it at the project instead,
    # which also works on machines where that directory is locked down.
    environment.setdefault("YOLO_CONFIG_DIR", str(config_dir or Path("data/ultralytics")))
    result = subprocess.run(
        [sys.executable, "-c", code, str(checkpoint), str(imgsz)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
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
