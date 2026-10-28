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

from mangatl.adapters.base import Inpainter, Ocr, Registry
from mangatl.adapters.stubs import CopyInpainter, EchoOcr, GridDetector
from mangatl.core.config import STAGE_ORDER, RunConfig
from mangatl.core.pipeline import EVENT_PAGE_DONE, Event, PipelineService
from mangatl.domain.project import Project

DetectorRegistry = Registry[type]


def default_registries() -> tuple[DetectorRegistry, DetectorRegistry, DetectorRegistry]:
    """Return registries preloaded with every available adapter.

    Adapters that need optional dependencies are registered only when those
    dependencies import cleanly, so a stub-only install still works.
    """
    detectors: DetectorRegistry = Registry("detector")
    detectors.add("grid", GridDetector)

    ocrs: DetectorRegistry = Registry("ocr")
    ocrs.add("echo", EchoOcr)

    inpainters: DetectorRegistry = Registry("inpainter")
    inpainters.add("copy", CopyInpainter)
    try:
        from mangatl.adapters.inpaint.auto import AutoInpainter
        from mangatl.adapters.inpaint.diffusion import DiffusionInpainter
        from mangatl.adapters.inpaint.solid import SolidFillInpainter
    except ImportError:  # numpy / Pillow missing
        pass
    else:
        inpainters.add("solid", SolidFillInpainter)
        inpainters.add("diffusion", DiffusionInpainter)
        inpainters.add("auto", AutoInpainter)
    return detectors, ocrs, inpainters


def _print_event(event: Event) -> None:
    if event.kind == EVENT_PAGE_DONE:
        print(f"[{event.page}] done: {event.detail}")


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
    run.add_argument("--force", action="store_true", help="re-run stages already marked done")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = _build_parser().parse_args(argv)
    if args.command != "run":  # pragma: no cover - argparse enforces the choices
        return 2

    stages = tuple(part.strip() for part in args.stages.split(",") if part.strip())
    config = RunConfig(
        stages=stages,
        detector=args.detector,
        ocr=args.ocr,
        inpainter=args.inpainter,
        force=args.force,
    )

    detectors, ocrs, inpainters = default_registries()
    try:
        detector = detectors.get(config.detector)()
        ocr: Ocr = ocrs.get(config.ocr)()
        inpainter: Inpainter = inpainters.get(config.inpainter)()
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    project = Project.open(args.directory)
    project.scan()
    service = PipelineService(project, detector, ocr, inpainter, on_event=_print_event)
    summary = service.run(config)
    print(json.dumps(asdict(summary), ensure_ascii=False))
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
