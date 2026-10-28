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

from mangatl.adapters.base import Detector, Inpainter, Ocr, Translator
from mangatl.adapters.translators.echo import EchoTranslator
from mangatl.core.config import RunConfig
from mangatl.domain.block import TextBlock
from mangatl.domain.project import Page, Project
from mangatl.domain.roles import BlockRole, RoleConfig, classify, is_translatable
from mangatl.render.renderer import PageRenderer

EVENT_STAGE_START = "stage-start"
EVENT_STAGE_DONE = "stage-done"
EVENT_PAGE_DONE = "page-done"
EVENT_PAGE_FAILED = "page-failed"
EVENT_PAGE_SKIPPED = "page-skipped"

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
        translator: Translator | None = None,
        renderer: PageRenderer | None = None,
        on_event: EventFn | None = None,
    ) -> None:
        self.project = project
        self.detector = detector
        self.ocr = ocr
        self.inpainter = inpainter
        self.translator = translator or EchoTranslator()
        self.renderer = renderer or PageRenderer()
        self.on_event = on_event

    def run(self, config: RunConfig) -> RunSummary:
        """Process every page and return the summary."""
        summary = RunSummary(total=len(self.project))
        for page in self.project:
            try:
                ran_any = self._run_page(page, config)
            except Exception as exc:  # one bad page must not abort the batch
                summary.failed += 1
                self._emit(EVENT_PAGE_FAILED, page.name, str(exc))
                continue
            if not ran_any:
                summary.skipped += 1
                self._emit(EVENT_PAGE_SKIPPED, page.name)
                continue
            summary.ok += 1
            summary.blocks += len(page.blocks)
            self.project.save()
            self._emit(EVENT_PAGE_DONE, page.name, f"{len(page.blocks)} blocks")
        return summary

    def _run_page(self, page: Page, config: RunConfig) -> bool:
        """Run the pending stages for one page; return whether anything ran."""
        image_path = self.project.directory / page.name
        ran_any = False
        for stage in config.stages:
            if page.is_done(stage) and not config.force:
                continue
            self._emit(EVENT_STAGE_START, page.name, stage)
            if stage == "detect":
                if hasattr(self.detector, "detect_with_mask"):
                    page.blocks, page.text_mask = self.detector.detect_with_mask(image_path)
                else:
                    page.blocks = self.detector.detect(image_path)
            elif stage == "ocr":
                if not page.blocks:
                    raise ValueError(f"{page.name}: OCR needs blocks from the detect stage")
                page.blocks = self.ocr.recognize(image_path, page.blocks)
                assign_roles(page, config)
            elif stage == "translate":
                assign_roles(page, config)
                for block in page.blocks:
                    if block.role == BlockRole.SYMBOL.value:
                        # Symbols are language-neutral: keep them as they are.
                        block.translation = block.text
                translatable = [
                    block for block in page.blocks if should_translate(block, config)
                ]
                if translatable:
                    self.translator.translate(
                        translatable,
                        {
                            "source_lang": config.src_lang,
                            "target_lang": config.tgt_lang,
                        },
                    )
            elif stage == "render":
                assign_roles(page, config)
                source = self.project.directory / config.output_dirname / page.name
                if not source.is_file():
                    source = image_path  # no erase output yet: letter the original
                destination = self.project.directory / config.result_dirname / page.name
                self.renderer.render(source, page.blocks, destination)
            elif stage == "erase":
                # Roles are derived from the OCR text, so recompute them even
                # when the OCR stage was skipped on a resumed run.
                if page.size is None:
                    page.size = _image_size(image_path)
                if page.text_mask is None and hasattr(self.detector, "text_mask"):
                    page.text_mask = self.detector.text_mask(image_path)
                assign_roles(page, config)
                destination = self.project.directory / config.output_dirname / page.name
                erasable = [block for block in page.blocks if should_erase(block, config)]
                self.inpainter.erase(
                    image_path, destination, erasable, mask=page.text_mask
                )
            page.mark(stage)
            ran_any = True
            self._emit(EVENT_STAGE_DONE, page.name, stage)
        return ran_any

    def _emit(self, kind: str, page: str, detail: str = "") -> None:
        if self.on_event is not None:
            self.on_event(Event(kind=kind, page=page, detail=detail))


def output_path(project: Project, config: RunConfig, page_name: str) -> Path:
    """Where the erased page for ``page_name`` is written."""
    return project.directory / config.output_dirname / page_name


def _image_size(path: Path) -> tuple[int, int] | None:
    """Read a page's pixel size without importing an image stack in core."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a render dependency
        return None
    with Image.open(path) as handle:
        return handle.size


def block_area_fraction(page: Page, block: TextBlock) -> float:
    """Block box area as a fraction of the page (0.0 when the size is unknown)."""
    if page.size is None:
        return 0.0
    width, height = page.size
    x1, y1, x2, y2 = block.bbox
    return max(0, x2 - x1) * max(0, y2 - y1) / max(1, width * height)


def mask_coverage(page: Page, block: TextBlock, threshold: float = 0.5) -> float:
    """Fraction of the block box that the detector marked as text."""
    if page.text_mask is None:
        return 1.0
    probability = page.text_mask
    height, width = probability.shape[:2]
    x1, y1, x2, y2 = block.bbox
    x1, y1 = max(0, min(x1, width)), max(0, min(y1, height))
    x2, y2 = max(0, min(x2, width)), max(0, min(y2, height))
    region = probability[y1:y2, x1:x2]
    if region.size == 0:
        return 0.0
    return float((region > threshold).mean())


def assign_roles(page: Page, config: RunConfig) -> None:
    """Classify every block as dialogue / SFX / texture, using the OCR result."""
    settings = RoleConfig()
    for block in page.blocks:
        confidence = block.confidence if block.confidence > 0 else 0.5
        coverage = mask_coverage(page, block)
        decision = classify(
            block.text,
            confidence=confidence,
            mask_coverage=coverage,
            config=settings,
        )
        block.mask_coverage = coverage
        block.area_fraction = block_area_fraction(page, block)
        # A box that covers a large part of the page but contains little text is
        # a detector artefact: erase its glyph pixels, never the whole box.
        block.bbox_erase = not (block.area_fraction > 0.35 and coverage < 0.1)
        block.role = decision.role.value
        block.role_reasons = decision.reasons
        if decision.role is BlockRole.DIALOGUE and confidence < 0.5:
            block.needs_review = True


def should_translate(block: TextBlock, config: RunConfig) -> bool:
    """Whether this block should be sent to the translator.

    Symbols are copied verbatim by the renderer, and SFX that are kept as
    artwork must not be translated (there would be nothing to draw the result on).
    """
    if not block.text.strip():
        return False
    if not is_translatable(block.role):
        return False
    return not (block.role == BlockRole.SFX.value and config.sfx_policy != "erase")


def should_erase(block: TextBlock, config: RunConfig) -> bool:
    """Whether the inpainter may touch this block.

    ``texture`` never qualifies, and a block whose box is almost empty of text
    pixels is treated as a false positive even when OCR returned something —
    that is what protects a whole-page misdetection from being wiped.
    """
    if block.role == BlockRole.TEXTURE.value:
        return False
    if block.mask_coverage < 0.02:
        return False
    return not (block.role == BlockRole.SFX.value and config.sfx_policy != "erase")
