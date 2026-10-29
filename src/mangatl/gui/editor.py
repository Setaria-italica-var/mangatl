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
from mangatl.gui.geometry import bbox_intersects, clamp_bbox, polygon_bbox
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
        old = block.bbox
        box = clamp_bbox(tuple(int(v) for v in bbox), width, height)
        block.bbox = box
        if block.bubble_bbox == old:
            block.bubble_bbox = box
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
        if self.detector is None:
            self.detector = CtdDetector()
        if self.inpainter is None:
            self.inpainter = MaskedInpainter()
        width, height = self._size()
        x1, y1, x2, y2 = clamp_bbox(polygon_bbox(points), width, height)
        mask = self.detector.text_mask(self.image_path)
        trimmed = np.zeros_like(mask)
        trimmed[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
        scratch = TextBlock(id=0, bbox=(x1, y1, x2, y2))
        destination = self.erased_path
        self.inpainter.erase(self.image_path, destination, [scratch], mask=trimmed)
        self.page.mark("erase")
        self.project.save()
        return destination

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
