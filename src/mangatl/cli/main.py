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
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from mangatl.adapters.base import Inpainter, Ocr, Registry, Translator
from mangatl.adapters.stubs import CopyInpainter, EchoOcr, GridDetector
from mangatl.adapters.translators.echo import EchoTranslator
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
    translators.add("echo", EchoTranslator)
    from mangatl.adapters.translators.openai_compat import OpenAiTranslator

    translators.add("openai", OpenAiTranslator)
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
    run.add_argument("--detector", default="grid")
    run.add_argument("--ocr", default="echo")
    run.add_argument("--inpainter", default="copy")
    default_translator = "openai" if os.environ.get("MANGATL_API_KEY") else "echo"
    run.add_argument("--translator", default=default_translator)
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
        "--bubble-model",
        default="data/models/bubble_detector.onnx",
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

    check = sub.add_parser("translate-test", help="send one sentence to the configured LLM")
    check.add_argument("--text", default="おはよう")
    check.add_argument("--target-lang", default="Simplified Chinese")

    fetch = sub.add_parser("fetch-models", help="download model weights from the HF hub")
    fetch.add_argument("--repo", default="ogkalu/comic-speech-bubble-detector-yolov8m")
    fetch.add_argument("--dest", type=Path, default=Path("data/models/bubble-src"))
    fetch.add_argument("--endpoint", default="")
    fetch.add_argument("--no-export", action="store_true")
    fetch.add_argument("--imgsz", type=int, default=640)
    fetch.add_argument("--list", action="store_true", help="only list the repository files")

    inspect = sub.add_parser("inspect", help="print the stored block decisions for a project")
    inspect.add_argument("directory", type=Path)

    bubbles_test = sub.add_parser("bubbles-test", help="run the bubble model on one page")
    bubbles_test.add_argument("page", type=Path)
    bubbles_test.add_argument("--model", default="data/models/bubble_detector.onnx")
    bubbles_test.add_argument("--classes", type=int, default=None)

    probe = sub.add_parser("probe", help="print an ONNX model's inputs and outputs")
    probe.add_argument("model", type=Path, help="path to a .onnx file")
    return parser


def _build_bubble_detector(config: RunConfig):
    """Instantiate the bubble detector, honouring the requested mode."""
    if config.bubbles in ("off", "heuristic"):
        return None
    from mangatl.adapters.detectors.bubbles import BubbleDetector

    detector = BubbleDetector(config.bubble_model)
    if config.bubbles == "model" and not detector.available:
        raise FileNotFoundError(
            f"bubble model not found: {config.bubble_model}\n"
            "hint: download it as described in docs/bubble-and-inpaint-plan.md"
        )
    return detector


def _run_translate_test(text: str, target: str) -> int:
    """One-shot provider check: fail with the provider's own message."""
    from mangatl.adapters.translators.openai_compat import (
        LlmConfig,
        OpenAiTranslator,
        TranslationError,
    )

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
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("HF_HOME", str(Path("data/hf").resolve()))


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
    print(f"{'page':10} {'id':>3} {'role':8} {'bubble':6} {'cov':>6} {'area':>6} {'size':>11} text")
    for page in project:
        for block in page.blocks:
            width = block.bbox[2] - block.bbox[0]
            height = block.bbox[3] - block.bbox[1]
            print(
                f"{page.name:10} {block.id:3} {block.role:8} "
                f"{str(block.in_bubble):6} {block.mask_coverage:6.3f} "
                f"{block.area_fraction:6.2f} {width:5}x{height:<5} "
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = _build_parser().parse_args(argv)
    if args.command == "demo":
        return _run_demo(args.directory, args.pages, args.seed)
    if args.command == "probe":
        return _run_probe(args.model)
    if args.command == "translate-test":
        return _run_translate_test(args.text, args.target_lang)
    if args.command == "inspect":
        return _run_inspect(args.directory)
    if args.command == "fetch-models":
        return _run_fetch_models(args)
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
        bubble_model=args.bubble_model,
        keep_blocks=tuple(filter(None, (s.strip() for s in args.keep_blocks.split(",")))),
        force_blocks=tuple(filter(None, (s.strip() for s in args.erase_blocks.split(",")))),
    )

    detectors, ocrs, inpainters, translators = default_registries()
    if config.bubbles in ("auto", "model"):
        model_path = Path(config.bubble_model)
        backend = "model" if model_path.is_file() else "heuristic (model missing)"
        print(f"bubbles: {backend}: {model_path}")
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
        translator: Translator = (
            translators.get(config.translator)() if "translate" in enabled else EchoTranslator()
        )
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
    service = PipelineService(
        project,
        detector,
        ocr,
        inpainter,
        translator=translator,
        bubble_detector=bubble_detector,
        on_event=_print_event,
    )
    summary = service.run(config)
    print(json.dumps(asdict(summary), ensure_ascii=False))
    if "render" in enabled and config.translator == "echo":
        print(
            "warning: translator=echo copies the source text, so the rendered pages "
            "still show the original language. Set MANGATL_API_KEY and pass "
            "--translator openai.",
            file=sys.stderr,
        )
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
