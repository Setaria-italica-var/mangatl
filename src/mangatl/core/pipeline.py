"""Stage orchestration: detect -> ocr -> erase, one page at a time.

The service knows nothing about Qt, models or the CLI. It takes the three
adapters plus a project, runs the configured stages, marks progress on each page
and writes the project file after every page so a crash keeps finished work.

>>> from mangatl.domain.project import Project
>>> import tempfile, pathlib
>>> tmp = pathlib.Path(tempfile.mkdtemp())
>>> project = Project.open(tmp)
>>> project.scan()
[]
>>> PipelineService(  # doctest: +SKIP
...     project=project, detector=None, ocr=None, inpainter=None)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mangatl.adapters.base import Detector, Inpainter, Ocr
from mangatl.core.config import RunConfig
from mangatl.domain.project import Page, Project

EVENT_STAGE_START = "stage-start"
EVENT_STAGE_DONE = "stage-done"
EVENT_PAGE_DONE = "page-done"
EVENT_PAGE_FAILED = "page-failed"

EventFn = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    """A single progress notification."""

    kind: str
    page: str
    detail: str = ""


@dataclass
class RunSummary:
    """Aggregate result of one pipeline run."""

    total: int = 0
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    blocks: int = 0


class PipelineService:
    """Run the configured stages over every page of a project."""

    def __init__(
        self,
        project: Project,
        detector: Detector,
        ocr: Ocr,
        inpainter: Inpainter,
        on_event: EventFn | None = None,
    ) -> None:
        self.project = project
        self.detector = detector
        self.ocr = ocr
        self.inpainter = inpainter
        self.on_event = on_event

    def run(self, config: RunConfig) -> RunSummary:
        """Process every page and return the summary."""
        summary = RunSummary(total=len(self.project))
        for page in self.project:
            try:
                self._run_page(page, config)
            except Exception as exc:  # one bad page must not abort the batch
                summary.failed += 1
                self._emit(EVENT_PAGE_FAILED, page.name, str(exc))
                continue
            summary.ok += 1
            summary.blocks += len(page.blocks)
            self.project.save()
            self._emit(EVENT_PAGE_DONE, page.name, f"{len(page.blocks)} blocks")
        return summary

    def _run_page(self, page: Page, config: RunConfig) -> None:
        image_path = self.project.directory / page.name
        for stage in config.stages:
            if page.is_done(stage) and not config.force:
                continue
            self._emit(EVENT_STAGE_START, page.name, stage)
            if stage == "detect":
                page.blocks = self.detector.detect(image_path)
            elif stage == "ocr":
                if not page.blocks:
                    raise ValueError(f"{page.name}: OCR needs blocks from the detect stage")
                page.blocks = self.ocr.recognize(image_path, page.blocks)
            elif stage == "erase":
                destination = self.project.directory / config.output_dirname / page.name
                self.inpainter.erase(image_path, destination, page.blocks)
            page.mark(stage)
            self._emit(EVENT_STAGE_DONE, page.name, stage)

    def _emit(self, kind: str, page: str, detail: str = "") -> None:
        if self.on_event is not None:
            self.on_event(Event(kind=kind, page=page, detail=detail))


def output_path(project: Project, config: RunConfig, page_name: str) -> Path:
    """Where the erased page for ``page_name`` is written."""
    return project.directory / config.output_dirname / page_name
