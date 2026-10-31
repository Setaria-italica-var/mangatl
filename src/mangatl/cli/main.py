"""Command line entry point: ``python -m mangatl run <dir>``.

The CLI is deliberately thin: it parses arguments, builds the adapters, and
delegates to :class:`~mangatl.core.pipeline.PipelineService`.

>>> main(["--help"])  # doctest: +SKIP
0
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from mangatl import paths
from mangatl.adapters.base import Inpainter, Ocr, Registry, Translator
from mangatl.adapters.stubs import CopyInpainter, CopyTranslator, EchoOcr, GridDetector
from mangatl.adapters.translators.openai_compat import (
    PROFILES,
    LlmConfig,
    OpenAiTranslator,
    TranslationError,
)
from mangatl.core.config import STAGE_ORDER, RunConfig
from mangatl.core.pipeline import EVENT_PAGE_DONE, EVENT_PAGE_FAILED, Event, PipelineService
from mangatl.domain.project import Project

DetectorRegistry = Registry[type]


def default_registries() -> tuple[
    DetectorRegistry, DetectorRegistry, DetectorRegistry, DetectorRegistry
]:
    """Return registries preloaded with every available adapter.

    Adapters that need optional dependencies are registered only when those
    dependencies import cleanly, so a stub-only install still works.
    """
    detectors: DetectorRegistry = Registry("detector")
    detectors.add("grid", GridDetector)
    try:
        from mangatl.adapters.detectors.ctd import CtdDetector
    except ImportError:  # numpy / Pillow missing
        pass
    else:
        detectors.add("ctd", CtdDetector)

    ocrs: DetectorRegistry = Registry("ocr")
    ocrs.add("echo", EchoOcr)
    try:
        from mangatl.adapters.ocr.manga_ocr import MangaOcrAdapter
    except ImportError:  # manga-ocr (or PIL) missing
        pass
    else:
        ocrs.add("manga_ocr", MangaOcrAdapter)
        from mangatl.adapters.ocr.hybrid import FusionOcr, HybridOcr

        ocrs.add("hybrid", HybridOcr)
        from mangatl.adapters.ocr.mit48px import Mit48pxOcr

        ocrs.add("mit48px_ctc", Mit48pxOcr)
        from mangatl.adapters.ocr.manga_ocr import MangaOcrAdapter

        ocrs.add("mit_manga", lambda: FusionOcr(Mit48pxOcr(), MangaOcrAdapter()))
        try:
            from mangatl.adapters.ocr.surya import SuryaOcr

            ocrs.add("surya", SuryaOcr)
        except ImportError:  # surya is optional; the name simply stays absent
            pass
    try:
        from mangatl.adapters.ocr.rapid import RapidOcrAdapter
    except ImportError:  # numpy missing; the engine itself is imported lazily
        pass
    else:
        ocrs.add("rapidocr", RapidOcrAdapter)

    inpainters: DetectorRegistry = Registry("inpainter")
    inpainters.add("copy", CopyInpainter)
    try:
        from mangatl.adapters.inpaint.auto import AutoInpainter
        from mangatl.adapters.inpaint.diffusion import DiffusionInpainter
        from mangatl.adapters.inpaint.masked import MaskedInpainter
        from mangatl.adapters.inpaint.solid import SolidFillInpainter
    except ImportError:  # numpy / Pillow missing
        pass
    else:
        inpainters.add("solid", SolidFillInpainter)
        inpainters.add("diffusion", DiffusionInpainter)
        inpainters.add("auto", AutoInpainter)
        inpainters.add("masked", MaskedInpainter)
        from mangatl.adapters.inpaint.lama import LamaInpainter

        inpainters.add("lama", LamaInpainter)

    translators: DetectorRegistry = Registry("translator")
    for profile in PROFILES:
        translators.add(
            profile,
            lambda name=profile: OpenAiTranslator(LlmConfig.from_env(name)),
        )
    translators.add("echo", CopyTranslator)
    return detectors, ocrs, inpainters, translators


def _print_event(event: Event) -> None:
    if event.kind == EVENT_PAGE_DONE:
        print(f"[{event.page}] done: {event.detail}")
    elif event.kind == EVENT_PAGE_FAILED:
        print(f"[{event.page}] failed: {event.detail}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mangatl", description="Local manga translation pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the pipeline over one project directory")
    run.add_argument("directory", type=Path, help="folder containing page images")
    run.add_argument(
        "--stages",
        default=",".join(STAGE_ORDER),
        help=f"comma separated subset of: {', '.join(STAGE_ORDER)}",
    )
    run.add_argument(
        "--pages",
        default="",
        help="page range like 1-20 or a list like 1,3,5-8 (default: every page)",
    )
    run.add_argument(
        "--events-json",
        action="store_true",
        help="stream progress events as one JSON object per line on stdout",
    )
    run.add_argument(
        "--heartbeat",
        type=float,
        default=3.0,
        help="seconds between tick events in --events-json mode",
    )
    run.add_argument("--detector", default="grid")
    run.add_argument("--ocr", default="echo")
    run.add_argument(
        "--vision-model",
        default="",
        help="vision model id for hard blocks (OpenAI-compatible endpoint)",
    )
    run.add_argument(
        "--vision-base-url",
        default="",
        help="vision endpoint, e.g. http://127.0.0.1:8080/v1 for llama.cpp",
    )
    run.add_argument(
        "--verify-ocr",
        choices=("auto", "off"),
        default="auto",
        help="ask the configured LLM to pick between disagreeing OCR engines",
    )
    run.add_argument(
        "--ocr-lang",
        default="japan",
        help="recognition language for RapidOCR (japan, ch, en, korean, ...)",
    )
    run.add_argument("--inpainter", default="copy")
    default_translator = "openai" if os.environ.get("MANGATL_API_KEY") else "echo"
    run.add_argument(
        "--translator",
        default=default_translator,
        help="openai | ollama | lmstudio | llamacpp | echo (source text)",
    )
    run.add_argument("--source-lang", default="ja")
    run.add_argument("--target-lang", default="zh-CN")
    run.add_argument(
        "--offline",
        action="store_true",
        help="never touch the network for models (uses the local HF cache)",
    )
    run.add_argument(
        "--bubbles",
        choices=("auto", "model", "heuristic", "off"),
        default="auto",
        help="bubble detection: auto uses the ONNX model when present, "
        "heuristic falls back to the pixel test, off erases every block",
    )
    run.add_argument(
        "--two-pass-bubbles",
        choices=("on", "off"),
        default="on",
        help="re-check pages where plausible dialogue has no bubble (on by default)",
    )
    run.add_argument(
        "--bubble-conf",
        type=float,
        default=0.3,
        help="bubble detector confidence (lower finds more bubbles, more false positives)",
    )
    run.add_argument(
        "--bubble-model",
        default=paths.models_file("bubble_detector.onnx"),
        help="path to the YOLOv8 bubble detector ONNX file",
    )
    run.add_argument(
        "--erase-scope",
        choices=("strict", "bright", "all"),
        default="strict",
        help="strict: only text enclosed by a bubble outline; bright: also very "
        "light backgrounds; all: every detected block",
    )
    run.add_argument(
        "--page-scope",
        action="append",
        default=[],
        metavar="PAGE=SCOPE",
        help="per-page erase scope, e.g. --page-scope 009.jpg=all",
    )
    run.add_argument(
        "--force-bubble",
        action="append",
        default=[],
        metavar="PAGE:ID",
        help="treat a block as bubble content even when the model missed its bubble",
    )
    run.add_argument(
        "--keep-blocks",
        default="",
        help="comma separated page:id pairs to always keep, e.g. 001.jpg:3,001.jpg:5",
    )
    run.add_argument(
        "--erase-blocks",
        default="",
        help="comma separated page:id pairs to always erase",
    )
    run.add_argument(
        "--erase-background",
        action="store_true",
        help="also erase text that is not inside a bubble (off by default)",
    )
    run.add_argument(
        "--sfx",
        choices=("keep", "erase"),
        default="keep",
        help="keep onomatopoeia as artwork (default) or erase it too",
    )
    run.add_argument("--force", action="store_true", help="re-run stages already marked done")

    demo = sub.add_parser("demo", help="write synthetic pages for a smoke test")
    demo.add_argument("directory", type=Path, help="folder to create the pages in")
    demo.add_argument("--pages", type=int, default=6)
    demo.add_argument("--seed", type=int, default=7)

    gui = sub.add_parser("gui", help="open the desktop editor on a project")
    gui.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=None,
        help="manga folder; omit to reopen the last one",
    )

    check = sub.add_parser("translate-test", help="send one sentence to the configured LLM")
    check.add_argument("--text", default="おはよう")
    check.add_argument("--target-lang", default="Simplified Chinese")

    fetch = sub.add_parser("fetch-models", help="download model weights from the HF hub")
    fetch.add_argument("--repo", default="ogkalu/comic-speech-bubble-detector-yolov8m")
    fetch.add_argument("--dest", type=Path, default=paths.models_dir() / "bubble-src")
    fetch.add_argument("--endpoint", default="")
    fetch.add_argument("--no-export", action="store_true")
    fetch.add_argument("--imgsz", type=int, default=640)
    fetch.add_argument("--list", action="store_true", help="only list the repository files")
    fetch.add_argument(
        "--lama",
        action="store_true",
        help="download LaMa inpainting weights (~200 MB) for Photoshop-like fills",
    )

    inspect = sub.add_parser("inspect", help="print the stored block decisions for a project")
    inspect.add_argument("directory", type=Path)

    vision_test = sub.add_parser("vision-test", help="send one crop to the vision model")
    vision_test.add_argument("page", type=Path)
    vision_test.add_argument("--bbox", default="", help="x1,y1,x2,y2; whole page when omitted")
    vision_test.add_argument("--model", default="")
    vision_test.add_argument("--base-url", default="")
    vision_test.add_argument("--timeout", type=float, default=90.0)

    bubbles_test = sub.add_parser("bubbles-test", help="run the bubble model on one page")
    bubbles_test.add_argument("page", type=Path)
    bubbles_test.add_argument("--model", default=paths.models_file("bubble_detector.onnx"))
    bubbles_test.add_argument("--classes", type=int, default=None)

    fill = sub.add_parser("fill-region", help="repaint a polygon region (GUI worker)")
    fill.add_argument("directory", type=Path)
    fill.add_argument("--page", required=True)
    fill.add_argument("--polygon", required=True, help="x,y;x,y;…")
    fill.add_argument("--inpainter", default="masked", choices=["masked", "lama"])

    sub.add_parser("task-worker", help="long-lived background task worker (JSON lines)")
    sub.add_parser("region-worker", help=argparse.SUPPRESS)

    ocr_crop = sub.add_parser("ocr-crop", help="re-OCR one block (used by the GUI)")
    ocr_crop.add_argument("directory", type=Path)
    ocr_crop.add_argument("--page", required=True)
    ocr_crop.add_argument("--block", type=int, required=True)

    probe = sub.add_parser("probe", help="print an ONNX model's inputs and outputs")
    probe.add_argument("model", type=Path, help="path to a .onnx file")
    return parser


def _build_bubble_detector(config: RunConfig):
    """Instantiate the bubble detector, honouring the requested mode."""
    if config.bubbles in ("off", "heuristic"):
        return None
    from mangatl.adapters.detectors.bubbles import BubbleDetector

    detector = BubbleDetector(config.bubble_model, confidence=config.bubble_confidence)
    if config.bubbles == "model" and not detector.available:
        raise FileNotFoundError(
            f"bubble model not found: {config.bubble_model}\n"
            "hint: download it as described in docs/bubble-and-inpaint-plan.md"
        )
    return detector


def _ocr_engine():
    """Fusion when MIT48 weights exist, otherwise manga-ocr alone."""
    from mangatl.adapters.ocr.manga_ocr import MangaOcrAdapter

    manga = MangaOcrAdapter()
    try:
        from mangatl.adapters.ocr.hybrid import FusionOcr
        from mangatl.adapters.ocr.mit48px import DEFAULT_MODEL, Mit48pxOcr

        model = Path(os.environ.get("MANGATL_MIT48_MODEL", DEFAULT_MODEL))
        if model.is_file():
            return FusionOcr(Mit48pxOcr(), manga)
    except Exception:  # noqa: BLE001 - optional engine
        pass
    return manga


def _parse_polygon(spec: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for part in spec.split(";"):
        part = part.strip()
        if not part:
            continue
        x, y = part.split(",")
        points.append((float(x), float(y)))
    return points


class _FillCancelled(Exception):
    """Raised when the GUI asked to discard this region fill."""


def _make_region_filler(name: str, cache: dict):
    if name in cache:
        return cache[name]
    if name == "lama":
        from mangatl.adapters.inpaint.lama import LamaInpainter

        filler = LamaInpainter()
    else:
        from mangatl.adapters.inpaint.masked import MaskedInpainter

        filler = MaskedInpainter()
    cache[name] = filler
    return filler


def _fill_region(
    directory: Path,
    page_name: str,
    points: list[tuple[float, float]],
    inpainter_name: str,
    cache: dict,
    cancel_path: Path | None = None,
    request_id: str = "",
) -> float:
    """Fill one polygon; returns elapsed seconds. Raises on failure."""
    started = time.monotonic()
    from PIL import Image, ImageDraw

    project = Project.open(directory)
    page = next((item for item in project if item.name == page_name), None)
    if page is None:
        raise ValueError(f"page not found: {page_name}")
    if len(points) < 3:
        raise ValueError("polygon needs 3+ points")
    source = project.directory / page.name
    destination = project.directory / "inpainted" / page.name
    base = destination if destination.is_file() else source
    with Image.open(source) as handle:
        width, height = handle.size
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    import numpy as np

    array = np.asarray(mask) > 0
    filler = _make_region_filler(inpainter_name, cache)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + ".tmp" + destination.suffix)
    filler.fill_region(base, temporary, array)
    if cancel_path is not None and cancel_path.is_file():
        try:
            requested = cancel_path.read_text(encoding="utf-8").strip()
        except OSError:
            requested = ""
        if requested == request_id:
            temporary.unlink(missing_ok=True)
            cancel_path.unlink(missing_ok=True)
            raise _FillCancelled()
    os.replace(temporary, destination)
    page.mark("erase")
    project.save()
    return time.monotonic() - started


def _run_fill_region(
    directory: Path, page_name: str, polygon: str, inpainter_name: str
) -> int:
    """One-shot fill; prints one JSON line."""
    cache: dict = {}
    try:
        points = _parse_polygon(polygon)
        seconds = _fill_region(directory, page_name, points, inpainter_name, cache)
    except Exception as exc:  # noqa: BLE001 - report as JSON
        print(
            json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=True,
            )
        )
        return 1
    print(json.dumps({"ok": True, "seconds": round(seconds, 2)}, ensure_ascii=True))
    return 0


class _TaskCancelled(Exception):
    """The GUI asked to discard this background task."""


def _cancel_token(request_id: object) -> Path | None:
    if not request_id:
        return None
    return paths.data_dir() / "tmp" / f"region-cancel-{request_id}"


def _consume_cancel(request_id: object) -> bool:
    token = _cancel_token(request_id)
    if token is None or not token.is_file():
        return False
    try:
        requested = token.read_text(encoding="utf-8").strip()
    except OSError:
        requested = ""
    token.unlink(missing_ok=True)
    return requested == str(request_id)


def _worker_page(directory: str, page_name: str):
    project = Project.open(directory)
    page = next((item for item in project if item.name == page_name), None)
    if page is None:
        raise ValueError(f"page not found: {page_name}")
    return project, page


def _task_ocr(request: dict, cache: dict) -> dict:
    from mangatl.domain.block import TextBlock
    from mangatl.domain.plausibility import plausibility
    from mangatl.domain.quality import looks_like_hallucination

    project, page = _worker_page(str(request["directory"]), str(request["page"]))
    block = next((item for item in page.blocks if item.id == request["block"]), None)
    if block is None:
        raise ValueError(f"block not found: {request['block']}")
    original = block.text
    engine = cache.get("ocr")
    if engine is None:
        engine = _ocr_engine()
        cache["ocr"] = engine
    probe = TextBlock.from_dict(block.to_dict())
    result = engine.recognize(project.directory / page.name, [probe])[0]
    text = result.text.strip()
    if (
        not text
        or plausibility(text) < 0.25
        or looks_like_hallucination(text, original)
    ):
        return {"ok": False, "rejected": True, "text": text}
    if _consume_cancel(request.get("id")):
        raise _TaskCancelled()
    block.text = text
    block.ocr_source = "reocr"
    block.needs_review = False
    project.save()
    return {"ok": True, "text": text}


def _task_translate(request: dict, cache: dict) -> dict:
    project, page = _worker_page(str(request["directory"]), str(request["page"]))
    wanted = {int(item) for item in request.get("blocks", [])}
    blocks = [block for block in page.blocks if block.id in wanted]
    if not blocks:
        raise ValueError("no blocks selected")
    profile = str(request.get("translator", "echo"))
    translator = cache.setdefault("translators", {}).get(profile)
    if translator is None:
        if profile == "echo":
            translator = CopyTranslator()
        else:
            from mangatl.adapters.translators.openai_compat import (
                LlmConfig,
                OpenAiTranslator,
            )

            translator = OpenAiTranslator(LlmConfig.from_env(profile))
        cache["translators"][profile] = translator
    translator.translate(blocks, {"target_lang": "简体中文"})
    if _consume_cancel(request.get("id")):
        raise _TaskCancelled()
    project.save()
    return {"ok": True, "count": len(blocks)}


def _task_detect(request: dict, cache: dict) -> dict:
    import tempfile

    from PIL import Image

    from mangatl.adapters.detectors.ctd import CtdDetector
    from mangatl.domain.block import TextBlock
    from mangatl.domain.roles import BlockRole

    project, page = _worker_page(str(request["directory"]), str(request["page"]))
    points = [(float(x), float(y)) for x, y in request.get("polygon", [])]
    if len(points) < 3:
        raise ValueError("polygon needs 3+ points")
    with Image.open(project.directory / page.name) as handle:
        width, height = handle.size
        x1 = max(0, min(int(min(p[0] for p in points)), width))
        y1 = max(0, min(int(min(p[1] for p in points)), height))
        x2 = max(0, min(int(max(p[0] for p in points)), width))
        y2 = max(0, min(int(max(p[1] for p in points)), height))
        if x2 - x1 < 8 or y2 - y1 < 8:
            return {"ok": True, "added": 0}
        crop = handle.convert("RGB").crop((x1, y1, x2, y2))
    detector = cache.get("detector")
    if detector is None:
        detector = CtdDetector()
        cache["detector"] = detector
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
        crop.save(temporary.name)
        found = detector.detect(Path(temporary.name))
    Path(temporary.name).unlink(missing_ok=True)
    if _consume_cancel(request.get("id")):
        raise _TaskCancelled()
    added = 0
    for block in found:
        bx1, by1, bx2, by2 = block.bbox
        box = (
            max(0, min(bx1 + x1, width)),
            max(0, min(by1 + y1, height)),
            max(0, min(bx2 + x1, width)),
            max(0, min(by2 + y1, height)),
        )
        new = TextBlock(
            id=max((item.id for item in page.blocks), default=-1) + 1,
            bbox=box,
            text=block.text,
            translation="",
            vertical=block.vertical,
            role=BlockRole.DIALOGUE.value,
            in_bubble=True,
            bubble_bbox=box,
            ocr_source="manual",
        )
        page.blocks.append(new)
        added += 1
    if added:
        project.save()
    return {"ok": True, "added": added}


def _task_brush(request: dict, cache: dict) -> dict:
    """Fill a freehand stroke mask (round-capped polyline) in the erased page."""
    import numpy as np
    from PIL import Image, ImageDraw

    project, page = _worker_page(str(request["directory"]), str(request["page"]))
    points = [(float(x), float(y)) for x, y in request.get("points", [])]
    if not points:
        raise ValueError("empty brush stroke")
    radius = max(2, int(request.get("radius", 32)))
    with Image.open(project.directory / page.name) as handle:
        width, height = handle.size
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    if len(points) == 1:
        x, y = points[0]
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    else:
        draw.line(points, fill=255, width=radius * 2, joint="curve")
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    array = np.asarray(mask) > 0
    if not array.any():
        return {"ok": True, "empty": True}
    source = project.directory / page.name
    destination = project.directory / "inpainted" / page.name
    base = destination if destination.is_file() else source
    filler = _make_region_filler(
        str(request.get("engine", "masked")), cache["fillers"]
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + ".tmp" + destination.suffix)
    filler.fill_region(base, temporary, array)
    if _consume_cancel(request.get("id")):
        temporary.unlink(missing_ok=True)
        raise _TaskCancelled()
    os.replace(temporary, destination)
    page.mark("erase")
    project.save()
    return {"ok": True}


def _run_task_worker() -> int:
    """Long-lived worker: fill / ocr / translate / detect, JSON lines both ways."""
    cache: dict = {"fillers": {}, "ocr": None, "translators": {}, "detector": None}
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request_id = None
        op = "fill"
        try:
            request = json.loads(line)
            request_id = request.get("id")
            op = str(request.get("op", "fill"))
            if op == "fill":
                points = [
                    (float(point[0]), float(point[1]))
                    for point in request["polygon"]
                ]
                seconds = _fill_region(
                    Path(request["directory"]),
                    str(request["page"]),
                    points,
                    str(request.get("inpainter", "masked")),
                    cache["fillers"],
                    cancel_path=_cancel_token(request_id),
                    request_id=str(request_id or ""),
                )
                payload = {
                    "id": request_id,
                    "op": op,
                    "ok": True,
                    "seconds": round(seconds, 2),
                }
            elif op == "ocr":
                payload = {"id": request_id, "op": op, **_task_ocr(request, cache)}
            elif op == "translate":
                payload = {
                    "id": request_id,
                    "op": op,
                    **_task_translate(request, cache),
                }
            elif op == "detect":
                payload = {
                    "id": request_id,
                    "op": op,
                    **_task_detect(request, cache),
                }
            elif op == "brush":
                payload = {
                    "id": request_id,
                    "op": op,
                    **_task_brush(request, cache),
                }
            else:
                raise ValueError(f"unknown op: {op}")
        except _TaskCancelled:
            payload = {"id": request_id, "op": op, "ok": False, "cancelled": True}
        except _FillCancelled:
            payload = {"id": request_id, "op": op, "ok": False, "cancelled": True}
        except Exception as exc:  # noqa: BLE001 - keep the worker alive
            payload = {
                "id": request_id,
                "op": op,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        print(json.dumps(payload, ensure_ascii=True), flush=True)
    return 0


def _run_ocr_crop(directory: Path, page_name: str, block_id: int) -> int:
    """Re-OCR a single block in a child process, printing one JSON line."""
    project = Project.open(directory)
    page = next((item for item in project if item.name == page_name), None)
    if page is None:
        print(json.dumps({"error": f"page not found: {page_name}"}, ensure_ascii=True))
        return 2
    block = next((item for item in page.blocks if item.id == block_id), None)
    if block is None:
        print(json.dumps({"error": f"block not found: {block_id}"}, ensure_ascii=True))
        return 2
    probe = _ocr_engine().recognize(project.directory / page.name, [block])[0]
    print(json.dumps({"id": block.id, "text": probe.text}, ensure_ascii=True))
    return 0


def _build_ocr_judge(config: RunConfig):
    """LLM judge for OCR disagreements, only when a provider is configured."""
    if not config.verify_ocr:
        return None
    from mangatl.adapters.ocr.judge import LlmJudge
    from mangatl.adapters.translators.openai_compat import LlmConfig, TranslationError

    try:
        config_llm = LlmConfig.from_env()
    except TranslationError:
        return None
    judge = LlmJudge(config_llm)
    return judge if judge.available else None


def _build_vision_ocr(config: RunConfig):
    """Vision reader for hard blocks; inert unless a model id is configured."""
    if not config.verify_ocr:
        return None
    from mangatl.adapters.ocr.vision import VisionConfig, VisionOcr

    vision = VisionOcr(VisionConfig.from_env())
    return vision if vision.available else None


def _run_translate_test(text: str, target: str) -> int:
    """One-shot provider check: fail with the provider's own message."""
    config = LlmConfig.from_env()
    if not config.api_key:
        print(
            "error: MANGATL_API_KEY is not set\n"
            "hint: set MANGATL_API_KEY=sk-... and optionally MANGATL_BASE_URL / MANGATL_MODEL",
            file=sys.stderr,
        )
        return 2
    print(f"base_url={config.base_url} model={config.model} key_len={len(config.api_key)}")
    try:
        result = OpenAiTranslator(config).check(text, target)
    except TranslationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "hint: 401 -> key wrong; 404 -> base_url or model name; "
            "timeout -> network/proxy; 429 -> rate limit or quota",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - surface anything the provider does
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _force_offline() -> None:
    """Make huggingface/transformers use the cache and skip network probes.

    The variables must be set before those libraries are imported, which is why
    this runs at the very start of ``main``.
    """
    os.environ["MANGATL_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("HF_HOME", str(paths.hf_dir().resolve()))


# The fp32 export is the recommended graph (opset 17); the dynamo export is slow
# and its DFT nodes break in onnxruntime.
LAMA_URL = "https://hf-mirror.com/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx"
LAMA_MIN_BYTES = 150_000_000
LAMA_EXPECTED_BYTES = 207_500_000


def _run_fetch_lama(destination: Path) -> int:
    import os
    import urllib.request

    if destination.is_file() and destination.stat().st_size >= LAMA_MIN_BYTES:
        print(f"already present: {destination}")
        return 0
    if destination.is_file():
        print(f"removing incomplete file ({destination.stat().st_size / 1e6:.0f} MB)")
        destination.unlink()

    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    downloaded = part.stat().st_size if part.is_file() else 0
    headers = {"User-Agent": "mangatl"}
    if downloaded:
        headers["Range"] = f"bytes={downloaded}-"
        print(f"resuming at {downloaded / 1e6:.0f} MB")
    request = urllib.request.Request(LAMA_URL, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        if downloaded and response.status != 206:
            downloaded = 0
            print("server ignored the range request, restarting")
        chunk_total = int(response.headers.get("Content-Length", 0))
        total = downloaded + chunk_total if chunk_total else LAMA_EXPECTED_BYTES
        mode = "ab" if downloaded else "wb"
        done = downloaded
        with open(part, mode) as handle:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
                done += len(chunk)
                print(
                    f"\r{done / 1e6:7.1f} / {total / 1e6:.0f} MB",
                    end="",
                    flush=True,
                )
    if part.stat().st_size < LAMA_MIN_BYTES:
        print("\ndownload looks truncated; rerun to resume")
        return 1
    os.replace(part, destination)
    print(f"\nsaved {destination} ({destination.stat().st_size / 1e6:.0f} MB)")
    return 0


def _run_fetch_models(args) -> int:
    """Download weights and export ONNX; returns a process exit code."""
    from mangatl.tools.fetch import fetch

    base = args.endpoint or None
    if args.list:
        from mangatl.tools.fetch import model_card, weight_files

        try:
            info = model_card(args.repo, base)
        except Exception as exc:  # noqa: BLE001 - network failures are user-facing
            print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        for name, url in weight_files(info, base, args.repo):
            print(f"{name}\t{url}")
        return 0
    try:
        exported = fetch(
            repo=args.repo,
            destination=args.dest,
            base=base,
            export=not args.no_export,
            imgsz=args.imgsz,
        )
    except Exception as exc:  # noqa: BLE001 - network failures are user-facing
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "hint: check HF_ENDPOINT (mirror); try --repo with one of the known ones "
            "listed above",
            file=sys.stderr,
        )
        return 1

    if exported is None:
        print(
            "weights downloaded; export to ONNX then register:\n"
            f"  --bubble-model {args.dest}/bubble_detector.onnx",
            file=sys.stderr,
        )
        return 0
    print(f"done: {exported}")
    return 0


def _run_vision_test(page: Path, bbox: str, model: str, base_url: str, timeout: float) -> int:
    """Read one crop with the configured vision model and report the score."""
    from PIL import Image

    from mangatl.adapters.ocr.vision import VisionConfig, VisionOcr
    from mangatl.domain.plausibility import plausibility

    if model:
        os.environ["MANGATL_VISION_MODEL"] = model
    if base_url:
        os.environ["MANGATL_VISION_BASE_URL"] = base_url
    config = VisionConfig.from_env()
    config = VisionConfig(
        base_url=config.base_url, api_key=config.api_key, model=config.model, timeout=timeout
    )
    reader = VisionOcr(config)
    if not reader.available:
        print(
            "error: vision endpoint not configured (set --model/--base-url or MANGATL_VISION_*)",
            file=sys.stderr,
        )
        return 2

    with Image.open(page) as handle:
        size = handle.size
    if bbox:
        try:
            x1, y1, x2, y2 = (int(value) for value in bbox.split(","))
        except ValueError:
            print("error: --bbox must be x1,y1,x2,y2", file=sys.stderr)
            return 2
    else:
        x1, y1, x2, y2 = 0, 0, size[0], size[1]

    started = time.perf_counter()
    text = reader.read(page, (x1, y1, x2, y2))
    elapsed = time.perf_counter() - started
    print(f"endpoint={config.base_url} model={config.model} crop={(x1, y1, x2, y2)}")
    print(f"elapsed={elapsed:.2f}s plausibility={plausibility(text):.2f}")
    print(repr(text))
    return 0


def _run_bubbles_test(page: Path, model_path: str, classes: int | None) -> int:
    """Show what the bubble model sees, class by class."""
    import numpy as np
    from PIL import Image

    from mangatl.adapters.detectors.bubbles import (
        BubbleDetector,
        class_count,
        decode,
        letterbox,
    )

    detector = BubbleDetector(model_path, class_index=classes)
    if not detector.available:
        print(f"error: bubble model not found: {model_path}", file=sys.stderr)
        return 2

    session = detector._get_session()  # noqa: SLF001 - diagnostic command
    with Image.open(page) as handle:
        image = np.asarray(handle.convert("RGB"))
        page_size = handle.size
    canvas, scale, padding = letterbox(image, detector.imgsz)
    tensor = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    output = session.run(None, {session.get_inputs()[0].name: tensor})[0]
    total = class_count(output)
    print(f"classes: {total}")

    for index in range(max(1, total)):
        chosen = index if total > 1 else None
        bubbles = decode(
            output, detector.confidence, detector.iou, scale, padding, page_size, chosen
        )
        print(f"class {index}: {len(bubbles)} bubbles")
        for bubble in bubbles[:10]:
            print(f"  {bubble.bbox} score={bubble.score:.3f}")

    bubbles, chosen, scores = detector.detect_multi(page)
    print(f"auto choice: class={chosen} scores={scores} bubbles={len(bubbles)}")
    return 0


def _run_inspect(directory: Path) -> int:
    """Print every block's role and geometry so a skipped page can be explained."""
    from mangatl.domain.project import Project

    try:
        project = Project.open(directory)
    except FileNotFoundError:
        print(f"error: {directory} has no project.json", file=sys.stderr)
        return 2
    print(
        f"{'page':10} {'id':>3} {'role':8} {'bubble':6} {'cov':>6} {'area':>6} "
        f"{'score':>5} {'source':10} {'size':>11} text"
    )
    for page in project:
        for block in page.blocks:
            width = block.bbox[2] - block.bbox[0]
            height = block.bbox[3] - block.bbox[1]
            print(
                f"{page.name:10} {block.id:3} {block.role:8} "
                f"{str(block.in_bubble):6} {block.mask_coverage:6.3f} "
                f"{block.area_fraction:6.2f} {block.ocr_score:5.2f} "
                f"{block.ocr_source[:10]:10} {width:5}x{height:<5} "
                f"{block.text[:22]!r}"
            )
    return 0


def _run_probe(model: Path) -> int:
    """Report the tensor contract of an ONNX model before writing a decoder."""
    try:
        import onnxruntime as ort
    except ImportError:
        print("error: probing needs onnxruntime (pip install onnxruntime)", file=sys.stderr)
        return 2
    if not model.is_file():
        print(f"error: {model} does not exist", file=sys.stderr)
        return 2
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    print(f"providers: {session.get_providers()}")
    for item in session.get_inputs():
        print(f"input  {item.name}: shape={item.shape} type={item.type}")
    for item in session.get_outputs():
        print(f"output {item.name}: shape={item.shape} type={item.type}")
    return 0


def _run_demo(directory: Path, pages: int, seed: int) -> int:
    try:
        from mangatl.tools.demo import generate
    except ImportError:
        print("error: generating demo pages needs Pillow (pip install pillow)", file=sys.stderr)
        return 2
    paths = generate(directory, pages=pages, seed=seed)
    print(f"wrote {len(paths)} pages to {directory}")
    return 0


def _configure_stdio() -> None:
    """Make console output survive CJK text on a legacy code page.

    A GBK console cannot encode ``・`` or ``…``; when output is redirected the
    process must write UTF-8 or the whole command dies with UnicodeEncodeError.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):  # not a TextIOWrapper
            continue



def parse_pages(spec: str, names: list[str]) -> set[str] | None:
    """Turn ``1-5,8`` into a set of page names; empty means "all pages"."""
    text = spec.strip()
    if not text:
        return None
    wanted: set[str] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            first, _, last = part.partition("-")
            try:
                start, end = int(first), int(last)
            except ValueError:
                continue
            for index in range(start, end + 1):
                if 1 <= index <= len(names):
                    wanted.add(names[index - 1])
        else:
            try:
                index = int(part)
            except ValueError:
                continue
            if 1 <= index <= len(names):
                wanted.add(names[index - 1])
    return wanted


class _EventStream:
    """Writes NDJSON progress plus a heartbeat tick between long operations."""

    def __init__(self, config, heartbeat: float = 3.0) -> None:
        self.config = config
        self.heartbeat = max(0.5, heartbeat)
        self.started = time.time()
        self.last = self.started
        self.last_kind = "start"
        self.last_page = ""
        self.last_detail = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()

    def handler(self, event) -> None:
        self.last = time.time()
        self.last_kind = event.kind
        self.last_page = getattr(event, "page", "") or self.last_page
        self.last_detail = getattr(event, "detail", "") or self.last_detail
        _emit_json(
            {
                "kind": event.kind,
                "page": getattr(event, "page", ""),
                "detail": getattr(event, "detail", ""),
                "ts": round(self.last, 3),
                "elapsed": round(self.last - self.started, 2),
            }
        )

    def _beat(self) -> None:
        while not self._stop.wait(self.heartbeat):
            now = time.time()
            _emit_json(
                {
                    "kind": "tick",
                    "page": self.last_page,
                    "stage": self.last_detail or self.last_kind,
                    "ts": round(now, 3),
                    "elapsed": round(now - self.started, 2),
                    "idle": round(now - self.last, 2),
                }
            )

    def stop(self) -> None:
        self._stop.set()


def _emit_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    _configure_stdio()
    args = _build_parser().parse_args(argv)
    if args.command == "demo":
        return _run_demo(args.directory, args.pages, args.seed)
    if args.command == "fill-region":
        return _run_fill_region(
            args.directory, args.page, args.polygon, args.inpainter
        )
    if args.command in {"task-worker", "region-worker"}:
        return _run_task_worker()
    if args.command == "ocr-crop":
        return _run_ocr_crop(args.directory, args.page, args.block)
    if args.command == "probe":
        return _run_probe(args.model)
    if args.command == "gui":
        from mangatl.gui.app import run

        return run(args.directory)
    if args.command == "translate-test":
        return _run_translate_test(args.text, args.target_lang)
    if args.command == "inspect":
        return _run_inspect(args.directory)
    if args.command == "fetch-models":
        if getattr(args, "lama", False):
            return _run_fetch_lama(Path(paths.models_file("lama.onnx")))
        return _run_fetch_models(args)
    if args.command == "vision-test":
        return _run_vision_test(
            args.page, args.bbox, args.model, args.base_url, args.timeout
        )
    if args.command == "bubbles-test":
        return _run_bubbles_test(args.page, args.model, args.classes)
    if args.command != "run":  # pragma: no cover - argparse enforces the choices
        return 2

    stages = tuple(part.strip() for part in args.stages.split(",") if part.strip())
    config = RunConfig(
        stages=stages,
        detector=args.detector,
        ocr=args.ocr,
        inpainter=args.inpainter,
        translator=args.translator,
        src_lang=args.source_lang,
        tgt_lang=args.target_lang,
        force=args.force,
        sfx_policy=args.sfx,
        erase_background=args.erase_background,
        erase_scope="all" if args.bubbles == "off" else args.erase_scope,
        bubbles=args.bubbles,
        verify_ocr=args.verify_ocr != "off",
        bubble_model=args.bubble_model,
        bubble_confidence=args.bubble_conf,
        two_pass_bubbles=args.two_pass_bubbles == "on",
        page_scopes=tuple(args.page_scope),
        force_bubble=tuple(args.force_bubble),
        keep_blocks=tuple(filter(None, (s.strip() for s in args.keep_blocks.split(",")))),
        force_blocks=tuple(filter(None, (s.strip() for s in args.erase_blocks.split(",")))),
    )

    detectors, ocrs, inpainters, translators = default_registries()
    if config.bubbles in ("auto", "model"):
        model_path = Path(config.bubble_model)
        backend = "model" if model_path.is_file() else "heuristic (model missing)"
        print(
            f"bubbles: {backend}: {model_path}",
            file=sys.stderr if args.events_json else sys.stdout,
        )
    enabled = config.enabled
    try:
        # Only build the adapters whose stage is selected: constructing an OCR
        # engine can load hundreds of megabytes for nothing on an erase-only run.
        detector_class = detectors.get(config.detector)
        # The erase stage reuses the detector's text mask, so a real detector is
        # still worth building when only erasing.
        needs_mask = "detect" in enabled or (
            "erase" in enabled and hasattr(detector_class, "text_mask")
        )
        detector = detector_class() if needs_mask else GridDetector()
        ocr: Ocr = ocrs.get(config.ocr)() if "ocr" in enabled else EchoOcr()
        inpainter: Inpainter = (
            inpainters.get(config.inpainter)() if "erase" in enabled else CopyInpainter()
        )
        bubble_detector = _build_bubble_detector(config)
        ocr_judge = _build_ocr_judge(config)
        vision_ocr = _build_vision_ocr(config)
        if "translate" in enabled:
            # Fail before loading OCR/detector weights when the provider is unusable.
            if config.translator != "echo":
                LlmConfig.from_env(config.translator)
            translator: Translator = translators.get(config.translator)()
        else:
            from mangatl.adapters.stubs import CopyTranslator

            translator = CopyTranslator()
    except Exception as exc:  # noqa: BLE001 - adapter construction is startup
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        project = Project.open(args.directory)
    except FileNotFoundError:
        print(
            f"error: {args.directory} does not exist\n"
            f"hint: generate synthetic pages first -> python -m mangatl demo {args.directory}",
            file=sys.stderr,
        )
        return 2
    project.scan()
    stream = _EventStream(config, heartbeat=args.heartbeat) if args.events_json else None
    service = PipelineService(
        project,
        detector,
        ocr,
        inpainter,
        translator=translator,
        bubble_detector=bubble_detector,
        ocr_judge=ocr_judge,
        vision_ocr=vision_ocr,
        on_event=stream.handler if stream is not None else _print_event,
    )
    only = parse_pages(args.pages, [page.name for page in project])
    if stream is not None:
        stream.start()
    try:
        summary = service.run(config, only=only)
    finally:
        if stream is not None:
            stream.stop()
    if args.events_json:
        _emit_json({"kind": "summary", **asdict(summary)})
    else:
        print(json.dumps(asdict(summary), ensure_ascii=True))
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
