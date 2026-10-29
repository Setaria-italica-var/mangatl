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
from mangatl.domain.merge import merge_blocks
from mangatl.domain.plausibility import plausibility
from mangatl.domain.project import Page, Project
from mangatl.domain.quality import looks_garbled
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
        bubble_detector=None,
        ocr_judge=None,
        vision_ocr=None,
        on_event: EventFn | None = None,
    ) -> None:
        self.project = project
        self.detector = detector
        self.ocr = ocr
        self.inpainter = inpainter
        self.translator = translator or EchoTranslator()
        self.renderer = renderer or PageRenderer()
        self.bubble_detector = bubble_detector
        self.ocr_judge = ocr_judge
        self.vision_ocr = vision_ocr
        self.verify_budget = 12
        self.vision_budget = 6
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
                ensure_mask(page, image_path, self.detector)
                annotate_bubbles(
                    page, image_path, config.erase_scope, self.bubble_detector
                )
                if config.merge_fragments:
                    page.blocks = merge_blocks(page.blocks)
            elif stage == "ocr":
                if not page.blocks:
                    raise ValueError(f"{page.name}: OCR needs blocks from the detect stage")
                for block in page.blocks:
                    block.ocr_source = ""
                    block.ocr_candidates = []
                    block.ocr_score = 0.0
                page.blocks = self.ocr.recognize(image_path, page.blocks)
                engine_name = getattr(self.ocr, "name", "")
                for block in page.blocks:
                    if not block.ocr_source:
                        block.ocr_source = engine_name
                    if block.text.strip() and not block.ocr_candidates:
                        block.ocr_candidates = [(block.ocr_source, block.text.strip())]
                    block.ocr_score = plausibility(block.text) if block.text.strip() else 0.0
                if config.verify_ocr:
                    self._verify_ocr(page, image_path)
                assign_roles(page, config)
            elif stage == "translate":
                ensure_mask(page, image_path, self.detector)
                scope = _scope_overrides(config).get(page.name, config.erase_scope)
                annotate_bubbles(page, image_path, scope, self.bubble_detector)
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
                ensure_mask(page, image_path, self.detector)
                scope = _scope_overrides(config).get(page.name, config.erase_scope)
                annotate_bubbles(page, image_path, scope, self.bubble_detector)
                assign_roles(page, config)
                source = self.project.directory / config.output_dirname / page.name
                if not source.is_file():
                    source = image_path  # no erase output yet: letter the original
                destination = self.project.directory / config.result_dirname / page.name
                lettered = [block for block in page.blocks if should_erase(block, config)]
                self.renderer.render(source, lettered, destination, style_source=image_path)
            elif stage == "erase":
                # Roles are derived from the OCR text, so recompute them even
                # when the OCR stage was skipped on a resumed run.
                if page.size is None:
                    page.size = _image_size(image_path)
                ensure_mask(page, image_path, self.detector)
                scope = _scope_overrides(config).get(page.name, config.erase_scope)
                annotate_bubbles(page, image_path, scope, self.bubble_detector)
                assign_roles(page, config)
                destination = self.project.directory / config.output_dirname / page.name
                keep = {item.strip() for item in config.keep_blocks}
                forced = {item.strip() for item in config.force_blocks}
                erasable = [
                    block
                    for block in page.blocks
                    if (f"{page.name}:{block.id}" in forced)
                    or (should_erase(block, config)
                        and f"{page.name}:{block.id}" not in keep)
                ]
                self.inpainter.erase(
                    image_path, destination, erasable, mask=page.text_mask
                )
            page.mark(stage)
            ran_any = True
            self._emit(EVENT_STAGE_DONE, page.name, stage)
        return ran_any

    def _verify_ocr(self, page: Page, image_path: Path) -> None:
        """Ask the judge to pick between disagreeing engines.

        A low score never removes a block: bubble text must still be translated.
        The judge only replaces the chosen text, and keeps ``needs_review`` set
        when it is not confident.
        """
        if self.ocr_judge is None or not getattr(self.ocr_judge, "available", False):
            return
        suspects = [
            block
            for block in page.blocks
            if block.ocr_candidates and block.ocr_score < 0.7
        ]
        if not suspects:
            return
        suspects.sort(key=lambda block: block.ocr_score)
        suspects = suspects[: max(1, int(self.verify_budget))]
        others = [block.text for block in page.blocks if block.text.strip()][:6]
        items = [(block.id, block.ocr_candidates) for block in suspects]
        picks = self.ocr_judge.choose_many(items, context=others)
        for block in suspects:
            choice, confidence = picks.get(block.id, (-1, 0.0))
            if 0 <= choice < len(block.ocr_candidates):
                source, text = block.ocr_candidates[choice]
                block.text = text
                block.ocr_source = source if source else "llm_judge"
                block.ocr_score = plausibility(text)
            if choice < 0 or confidence < 0.5 or block.ocr_score < 0.45:
                block.needs_review = True

        self._repair_text(page)
        self._vision_read(page, image_path)

    def _repair_text(self, page: Page) -> None:
        """Reconstruct heavy OCR noise with the model, then re-validate it.

        A repaired string is accepted only when it is clearly more plausible than
        the OCR noise and still looks like Japanese; it is always flagged for
        review because a model wrote it.
        """
        if self.ocr_judge is None or not getattr(self.ocr_judge, "available", False):
            return
        suspects = [
            block
            for block in page.blocks
            if block.in_bubble and block.text.strip() and block.ocr_score < 0.45
        ]
        if not suspects:
            return
        suspects.sort(key=lambda block: block.ocr_score)
        suspects = suspects[: max(1, int(self.verify_budget))]
        context = [block.text for block in page.blocks if block.text.strip()][:6]
        repaired = self.ocr_judge.repair_many(
            [(block.id, block.text) for block in suspects], context=context
        )
        for block in suspects:
            text = repaired.get(block.id, "").strip()
            if not text:
                continue
            score = plausibility(text)
            if score >= 0.6 and score > block.ocr_score:
                block.text = text
                block.ocr_score = score
                block.ocr_source = "llm_repair"
            block.needs_review = True

    def _vision_read(self, page: Page, image_path: Path) -> None:
        """Read the worst blocks with a vision model, if one is configured.

        Only blocks that are still suspicious and inside a bubble are sent: they
        are the ones that must be translated but whose source text is unreliable.
        """
        if self.vision_ocr is None or not getattr(self.vision_ocr, "available", False):
            return
        candidates = [
            block
            for block in page.blocks
            if block.in_bubble and block.ocr_score < 0.5 and block.bbox[2] > block.bbox[0]
        ]
        candidates.sort(key=lambda block: block.ocr_score)
        for block in candidates[: max(1, int(self.vision_budget))]:
            text = self.vision_ocr.read(image_path, block.bbox)
            if not text:
                continue
            score = plausibility(text)
            if score > block.ocr_score:
                block.text = text
                block.ocr_score = score
                block.ocr_source = getattr(self.vision_ocr, "name", "vision")
                block.needs_review = score < 0.45

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


def interior_regions(pixels):
    """Label the interiors of *individual* closed ink loops.

    Filling all ink at once merges a bubble with the panel it touches, which
    produced useless regions. Each loop is filled on its own instead, so a bubble
    inside a panel keeps its own interior.

    Returns ``(labels, stats)`` or ``None`` when the image stack is unavailable.
    """
    try:
        import numpy as np
        from PIL import Image

        from mangatl.adapters.imaging import ComponentStats, fill_holes, label_components
    except ImportError:  # pragma: no cover - numpy/Pillow optional for stubs
        return None

    gray = np.asarray(Image.fromarray(pixels[..., :3]).convert("L"))
    ink = gray < 200
    labels, components = label_components(ink)
    height, width = gray.shape
    page_extent = float(max(height, width))

    interiors = np.zeros(gray.shape, dtype=np.int32)
    collected: list[ComponentStats] = []
    next_label = 1

    for component in components:
        long_side = float(max(component.width, component.height))
        if component.area < 120 or component.fill >= 0.25 or long_side < 0.05 * page_extent:
            continue
        x1, y1, x2, y2 = component.bbox
        pad = 2
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(width, x2 + pad), min(height, y2 + pad)
        sub = labels[y1:y2, x1:x2] == component.label
        if not sub.any():
            continue
        hole = fill_holes(sub) & ~sub
        if not hole.any():
            continue
        ys, xs = np.nonzero(hole)
        top, bottom = int(ys.min()), int(ys.max()) + 1
        left, right = int(xs.min()), int(xs.max()) + 1
        window = interiors[y1 + top : y1 + bottom, x1 + left : x1 + right]
        window[hole[top:bottom, left:right]] = next_label
        collected.append(
            ComponentStats(
                label=next_label,
                area=int(hole.sum()),
                bbox=(x1 + left, y1 + top, x1 + right, y1 + bottom),
            )
        )
        next_label += 1
    return interiors, collected


def bright_fraction(pixels, bbox: tuple[int, int, int, int], probability=None) -> float:
    """Share of light background pixels around the text (glyphs excluded)."""
    import numpy as np

    height, width = pixels.shape[:2]
    x1, y1, x2, y2 = bbox
    x1, y1 = max(0, min(x1, width)), max(0, min(y1, height))
    x2, y2 = max(0, min(x2, width)), max(0, min(y2, height))
    if x2 <= x1 or y2 <= y1:
        return 0.0
    margin_x = max(6, int((x2 - x1) * 0.25))
    margin_y = max(6, int((y2 - y1) * 0.25))
    left, top = max(0, x1 - margin_x), max(0, y1 - margin_y)
    right, bottom = min(width, x2 + margin_x), min(height, y2 + margin_y)
    luminance = pixels[top:bottom, left:right, :3].astype(np.float32).mean(axis=2)
    if probability is not None:
        mask = np.asarray(probability)[top:bottom, left:right]
        background = luminance[mask < 0.2]
        if background.size < 50:
            return 0.0
        return float((background >= 160).mean())
    return float((luminance >= 160).mean())


def is_bubble(bbox: tuple[int, int, int, int], regions, page_size: tuple[int, int]) -> bool:
    """Whether a block sits inside a closed region of the drawing.

    A speech bubble is a closed outline around the text. Checking that the whole
    block is enclosed by one region is what separates dialogue from a sound
    effect printed on the open artwork: the latter is not surrounded by any loop,
    however white the paper behind it happens to be.
    """
    if regions is None:
        return False
    labels, stats = regions
    height, width = page_size
    x1, y1, x2, y2 = bbox
    x1, y1 = max(0, min(x1, width)), max(0, min(y1, height))
    x2, y2 = max(0, min(x2, width)), max(0, min(y2, height))
    if x2 <= x1 or y2 <= y1:
        return False

    centre_y = min(height - 1, (y1 + y2) // 2)
    centre_x = min(width - 1, (x1 + x2) // 2)
    label = int(labels[centre_y, centre_x])
    if label == 0:
        return False
    stats_by_label = {item.label: item for item in stats}
    region = stats_by_label.get(label)
    if region is None:
        return False

    blocked_area = (x2 - x1) * (y2 - y1)
    if region.area > 0.35 * height * width:
        return False  # a whole-page region is a panel or the page itself
    if region.area < 0.8 * blocked_area:
        return False
    rx1, ry1, rx2, ry2 = region.bbox
    return rx1 <= x1 + 2 and ry1 <= y1 + 2 and rx2 >= x2 - 2 and ry2 >= y2 - 2


def _scope_overrides(config: RunConfig) -> dict[str, str]:
    """Parse ``--page-scope 009.jpg=all`` entries into a mapping."""
    result: dict[str, str] = {}
    for item in config.page_scopes:
        if "=" not in item:
            continue
        name, scope = item.split("=", 1)
        if scope in {"strict", "bright", "all"}:
            result[name.strip()] = scope.strip()
    return result


def ensure_mask(page: Page, image_path: Path, detector) -> None:
    """Compute the detector's text probability once per page, if possible."""
    if page.text_mask is not None:
        return
    if hasattr(detector, "text_mask"):
        page.text_mask = detector.text_mask(image_path)


def annotate_with_model(page: Page, image_path: Path, detector) -> bool:
    """Mark blocks inside model-detected bubbles; returns whether it ran."""
    if detector is None or not getattr(detector, "available", False):
        return False
    try:
        from mangatl.adapters.detectors.bubbles import coverage, covered

        if hasattr(detector, "detect_multi"):
            bubbles, index, _scores = detector.detect_multi(image_path, page.blocks)
            detector.last_class = index
        else:
            bubbles = detector.detect(image_path)
    except Exception:  # a broken model must not stop the page
        return False
    if not bubbles:
        return False  # let the heuristic try: a page the model misses entirely
    page_area = max(1, page.size[0] * page.size[1]) if page.size else None
    for block in page.blocks:
        x1, y1, x2, y2 = block.bbox
        block_area = max(1, (x2 - x1) * (y2 - y1))
        # Sanity-filter the detections: a "bubble" smaller than the text it should
        # contain, or one covering most of the page, is a false positive.
        usable = []
        for bubble in bubbles:
            bx1, by1, bx2, by2 = bubble.bbox
            area = max(1, (bx2 - bx1) * (by2 - by1))
            if area < 0.25 * block_area:
                continue  # far too small to be the bubble around this text
            if page_area is not None and area > 0.4 * page_area:
                continue
            usable.append(bubble)
        block.in_bubble = covered(block.bbox, usable)
        if block.in_bubble:
            best = max(
                usable, key=lambda bubble: coverage(block.bbox, [bubble]), default=None
            )
            block.bubble_bbox = best.bbox if best is not None else None
        else:
            block.bubble_bbox = None
    return True


def annotate_bubbles(page: Page, image_path: Path, scope: str = "strict", detector=None) -> None:
    """Mark each block as inside a closed bubble region or embedded in artwork."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:  # pragma: no cover - numpy/Pillow optional for stubs
        return

    if scope == "all":
        # Explicit override: letter every block, model or not.
        for block in page.blocks:
            block.in_bubble = True
        return
    if annotate_with_model(page, image_path, detector):
        return

    with Image.open(image_path) as handle:
        pixels = np.array(handle.convert("RGB"))
    from mangatl.adapters.imaging import bounded_background

    page_size = (pixels.shape[1], pixels.shape[0])
    regions = interior_regions(pixels)
    for block in page.blocks:
        if scope == "all":
            block.in_bubble = True
            continue
        enclosed = is_bubble(block.bbox, regions, page_size) or bounded_background(
            pixels, block.bbox
        )
        if scope == "strict":
            block.in_bubble = enclosed
        else:
            block.in_bubble = enclosed or (
                bright_fraction(pixels, block.bbox, page.text_mask) >= 0.8
            )


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
        if (
            block.role == BlockRole.SYMBOL.value
            and block.bubble_bbox is not None
            and not block.vertical
        ):
            bx1, by1, bx2, by2 = block.bubble_bbox
            if (by2 - by1) > (bx2 - bx1) * 1.2:
                block.vertical = True
        if block.role == BlockRole.SYMBOL.value and not block.translation.strip():
            # Symbols are copied verbatim, so they can be erased even when the
            # translate stage has not run.
            block.translation = block.text
        block.mask_coverage = coverage
        block.area_fraction = block_area_fraction(page, block)
        # A box that covers a large part of the page but contains little text is
        # a detector artefact: erase its glyph pixels, never the whole box.
        block.bbox_erase = not (block.area_fraction > 0.35 and coverage < 0.1)
        block.role = decision.role.value
        block.role_reasons = decision.reasons
        if block.text.strip() and plausibility(block.text) < 0.45:
            # The OCR probably misread decorative lettering. Do NOT skip: bubble
            # text must still be translated. Flag it so the verification chain
            # (second engine / LLM judge / vision model) gets a chance, and let a
            # human know the source text is suspect.
            block.needs_review = True
            block.role_reasons = (*decision.reasons, "implausible-ocr")
        if looks_garbled(block.text) and block.role in (
            BlockRole.DIALOGUE.value,
            BlockRole.SFX.value,
        ):
            # Engine noise on stylised lettering: never erase or translate it.
            block.role = BlockRole.TEXTURE.value
            block.role_reasons = (*decision.reasons, "garbled-ocr")
            block.needs_review = True
            continue
        if block.role in (BlockRole.SFX.value, BlockRole.SYMBOL.value) and not block.in_bubble:
            # Sound effects printed over the artwork are part of the drawing:
            # keep them untouched and out of the translation budget.
            block.role = BlockRole.TEXTURE.value
            block.role_reasons = (*decision.reasons, "background-art")
        if decision.role is BlockRole.DIALOGUE and confidence < 0.5:
            block.needs_review = True


def should_translate(block: TextBlock, config: RunConfig) -> bool:
    """Whether this block should be sent to the translator.

    Symbols are copied verbatim by the renderer, and SFX that are kept as
    artwork must not be translated (there would be nothing to draw the result on).
    """
    if not block.text.strip():
        return False
    if not block.in_bubble and not config.erase_background:
        return False  # background text is neither erased nor lettered
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
    if not block.in_bubble and not config.erase_background:
        # Text embedded in the artwork (sound effects, signage) is left alone
        # unless the caller explicitly asks for background erasing.
        return False
    if config.require_translation and not block.translation.strip():
        # Erasing without a replacement leaves an empty bubble, which is worse
        # than leaving the original text in place.
        return False
    return not (block.role == BlockRole.SFX.value and config.sfx_policy != "erase")
