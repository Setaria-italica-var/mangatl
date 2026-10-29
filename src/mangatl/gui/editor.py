"""Editing operations behind the GUI, free of Qt.

The window calls these methods; they mutate the page/project and write files. That
keeps the Qt layer thin and lets the operations be tested (and reused by the CLI).
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from mangatl.adapters.detectors.ctd import CtdDetector
from mangatl.adapters.inpaint.masked import MaskedInpainter
from mangatl.core.pipeline import _image_size, assign_roles, block_area_fraction
from mangatl.domain.block import TextBlock
from mangatl.domain.project import Page, Project
from mangatl.domain.roles import BlockRole, RoleConfig, classify
from mangatl.gui.geometry import bbox_intersects, clamp_bbox, polygon_bbox, polygon_mask
from mangatl.render.renderer import PageRenderer


@dataclass
class PageEditor:
    """Edits one page of a project."""

    project: Project
    page: Page
    detector: CtdDetector | None = None
    inpainter: MaskedInpainter | None = None
    renderer: PageRenderer | None = None

    # -- paths ------------------------------------------------------------
    @property
    def image_path(self) -> Path:
        return self.project.directory / self.page.name

    @property
    def erased_path(self) -> Path:
        return self.project.directory / "inpainted" / self.page.name

    @property
    def result_path(self) -> Path:
        return self.project.directory / "result" / self.page.name

    def view_path(self, mode: str) -> Path | None:
        """File to display for a view mode: ``source``, ``erased`` or ``result``.

        Falls back to earlier stages so the view never goes blank.

        >>> PageEditor(Project.open("x"), Page(name="p")).view_path("source").name
        'p'
        """
        if mode == "result" and self.result_path.is_file():
            return self.result_path
        if mode == "erased" and self.erased_path.is_file():
            return self.erased_path
        return self.image_path

    # -- block editing ----------------------------------------------------
    def blocks_in(self, region: tuple[int, int, int, int]) -> list[TextBlock]:
        """Blocks intersecting a region box."""
        return [block for block in self.page.blocks if bbox_intersects(block.bbox, region)]

    def add_block(
        self,
        bbox: tuple[int, int, int, int],
        text: str = "",
        translation: str = "",
        vertical: bool | None = None,
    ) -> TextBlock:
        """Create a block from a lasso/rectangle and select it."""
        width, height = self._size()
        box = clamp_bbox(bbox, width, height)
        if vertical is None:
            vertical = (box[3] - box[1]) > (box[2] - box[0]) * 1.2
        block = TextBlock(
            id=max((item.id for item in self.page.blocks), default=-1) + 1,
            bbox=box,
            text=text,
            translation=translation,
            vertical=vertical,
            role=BlockRole.DIALOGUE.value,
            in_bubble=True,
            bubble_bbox=box,
            ocr_source="manual",
        )
        self.page.blocks.append(block)
        self._after_edit()
        return block

    def remove_blocks(self, blocks: Sequence[TextBlock]) -> None:
        """Delete blocks and renumber ids."""
        doomed = {id(block) for block in blocks}
        self.page.blocks = [b for b in self.page.blocks if id(b) not in doomed]
        for index, block in enumerate(self.page.blocks):
            block.id = index
        self._after_edit()

    def set_text(self, block: TextBlock, text: str) -> None:
        """Set the source text (manual correction)."""
        block.text = text.strip()
        block.ocr_source = "manual"
        block.needs_review = False
        self._refresh_role(block)
        self._after_edit()

    def set_bbox(self, block: TextBlock, bbox: tuple[int, int, int, int]) -> None:
        """Move or resize a block from the canvas."""
        width, height = self._size()
        box = clamp_bbox(tuple(int(v) for v in bbox), width, height)
        block.bbox = box
        # A manually placed frame defines its own lettering area. Keeping the old
        # bubble clip would stop the text from following the frame.
        block.bubble_bbox = box
        self.project.save()

    def lock_style(self, block: TextBlock) -> int:
        """Freeze size and colours before a frame transform changes the box.

        Without this the renderer re-estimates typography from the pixels under
        the box: dragging a frame over artwork would change glyph size *and*
        colour, which reads as the text "deforming".
        """
        style = dict(block.style or {})
        if style.get("font_size") and style.get("fg") and style.get("bg"):
            return int(style["font_size"])
        measured = self._measure_font_size(block)
        if self.renderer is None:
            self.renderer = PageRenderer()
        try:
            estimated = self.renderer.estimate(block, self.image_path)
        except Exception:  # noqa: BLE001 - never block editing on an estimate failure
            estimated = {}
        for key in ("font_size", "fg", "bg", "stroke"):
            if key not in style and key in estimated:
                style[key] = estimated[key]
        if not style.get("font_size") and measured:
            style["font_size"] = measured
        block.style = style
        return int(style.get("font_size") or 0)

    def _measure_font_size(self, block: TextBlock) -> int:
        if self.renderer is None:
            self.renderer = PageRenderer()
        try:
            return int(self.renderer.measure(block, self.image_path))
        except Exception:  # noqa: BLE001 - never block editing on a measure failure
            return 0

    def set_text_bbox(self, block: TextBlock, bbox: tuple[int, int, int, int]) -> None:
        """Move the type-setting frame without touching the detection box."""
        width, height = self._size()
        block.text_bbox = clamp_bbox(tuple(int(v) for v in bbox), width, height)
        self.project.save()

    def set_style(self, block: TextBlock, style: dict) -> None:
        """Persist manual typography overrides for one block."""
        block.style = {key: value for key, value in style.items() if value not in ("", 0, 0.0)}
        self.project.save()

    def set_translation(self, block: TextBlock, translation: str) -> None:
        """Set the translation."""
        block.translation = translation.strip()
        block.needs_review = False
        self._after_edit()

    # -- region operations ------------------------------------------------
    def redetect(self, points: Sequence[tuple[float, float]]) -> list[TextBlock]:
        """Run detection on the selected region and add the found blocks.

        Detection runs on a crop, so the boxes are translated back into page
        coordinates.
        """
        if self.detector is None:
            self.detector = CtdDetector()
        width, height = self._size()
        x1, y1, x2, y2 = clamp_bbox(polygon_bbox(points), width, height)
        if x2 - x1 < 8 or y2 - y1 < 8:
            return []
        with Image.open(self.image_path) as handle:
            crop = handle.convert("RGB").crop((x1, y1, x2, y2))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp:
            crop.save(temp.name)
            found = self.detector.detect(Path(temp.name))
        Path(temp.name).unlink(missing_ok=True)

        added: list[TextBlock] = []
        for block in found:
            bx1, by1, bx2, by2 = block.bbox
            added.append(
                self.add_block(
                    (bx1 + x1, by1 + y1, bx2 + x1, by2 + y1),
                    text=block.text,
                    vertical=block.vertical,
                )
            )
        return added

    def erase_region(self, points: Sequence[tuple[float, float]]) -> Path:
        """Inpaint the glyphs inside the selected region.

        The detector's text mask restricts the erase to actual lettering, so the
        lasso cannot smear artwork.
        """
        if self.inpainter is None:
            self.inpainter = self._best_inpainter()
        width, height = self._size()
        mask = np.array(polygon_mask(points, width, height)) > 0
        destination = self.erased_path
        # Start from the current erased page, not the original: otherwise every
        # new region fill would undo the previous ones.
        source = destination if destination.is_file() else self.image_path
        self.inpainter.fill_region(source, destination, mask)
        self.page.mark("erase")
        self.project.save()
        return destination

    def restore_region(self, points: Sequence[tuple[float, float]]) -> Path:
        """Put the original pixels back inside a region.

        Useful after an over-eager erase: the artwork under the region comes from
        the untouched page image, while the rest of ``inpainted/`` is kept.
        """
        width, height = self._size()
        mask = polygon_mask(points, width, height)
        with Image.open(self.image_path) as handle:
            source = handle.convert("RGB")
        destination = self.erased_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            with Image.open(destination) as handle:
                target = handle.convert("RGB")
        else:
            target = source.copy()
        target.paste(source, mask=mask)
        temp = destination.with_name(destination.stem + ".tmp" + destination.suffix)
        target.save(temp)
        temp.replace(destination)
        self.page.mark("erase")
        self.project.save()
        return destination

    def _best_inpainter(self):
        """LaMa when the weights are present, otherwise the mask filler."""
        from mangatl.adapters.inpaint.lama import DEFAULT_MODEL, LamaInpainter

        if Path(DEFAULT_MODEL).is_file():
            return LamaInpainter()
        return MaskedInpainter()

    def rerender(self) -> Path:
        """Letter the page with the current blocks."""
        if self.renderer is None:
            self.renderer = PageRenderer()
        source = self.erased_path if self.erased_path.is_file() else self.image_path
        destination = self.result_path
        self.renderer.render(source, self.page.blocks, destination, style_source=self.image_path)
        self.page.mark("render")
        self.project.save()
        return destination

    # -- internals --------------------------------------------------------
    def _size(self) -> tuple[int, int]:
        if self.page.size is None:
            size = _image_size(self.image_path)
            self.page.size = size or (1, 1)
        return self.page.size

    def _refresh_role(self, block: TextBlock) -> None:
        decision = classify(
            block.text,
            confidence=block.confidence or 0.6,
            mask_coverage=block.mask_coverage,
            config=RoleConfig(),
        )
        block.role = decision.role.value
        block.role_reasons = decision.reasons

    def _after_edit(self) -> None:
        assign_roles(self.page, _Config())
        self.project.save()

    def _page_area_fraction(self, block: TextBlock) -> float:
        return block_area_fraction(self.page, block)


class _Config:
    """Minimal stand-in for ``RunConfig`` in role assignment."""

    erase_background = False
    sfx_policy = "erase"


def empty_page(project: Project, name: str) -> Page:
    """Create a page entry for an image on disk that the project does not know yet."""
    page = Page(name=name)
    project.pages[name] = page
    return page
