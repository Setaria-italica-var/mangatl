"""Command line entry point: ``python -m mangatl run <dir>``.

The CLI is deliberately thin: it parses arguments, builds the adapters, and
delegates to :class:`~mangatl.core.pipeline.PipelineService`.

>>> main(["--help"])  # doctest: +SKIP
0
"""

from __future__ import annotations

import argparse
import json
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
    run.add_argument("--translator", default="echo")
    run.add_argument("--source-lang", default="ja")
    run.add_argument("--target-lang", default="zh-CN")
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

    probe = sub.add_parser("probe", help="print an ONNX model's inputs and outputs")
    probe.add_argument("model", type=Path, help="path to a .onnx file")
    return parser


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
    )

    detectors, ocrs, inpainters, translators = default_registries()
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
        translator: Translator = (
            translators.get(config.translator)() if "translate" in enabled else EchoTranslator()
        )
    except (KeyError, ImportError, FileNotFoundError) as exc:
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
        project, detector, ocr, inpainter, translator=translator, on_event=_print_event
    )
    summary = service.run(config)
    print(json.dumps(asdict(summary), ensure_ascii=False))
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
