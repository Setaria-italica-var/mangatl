"""Draw translated text back into the bubbles.

This is the only place in the project that writes pixels. It consumes the erased
page plus the blocks (with ``translation`` and a measured ``style``) and produces
the final image.

Layout choices follow manga lettering practice:

* text is centred in the block box, which is already inside the bubble;
* glyph size shrinks until the text fits, with a hard floor;
* vertical blocks are set in right-to-left columns, and glyphs that rotate in
  vertical writing (``ー``, ``…``, brackets) are rotated instead of squashed;
* a thin outline in the bubble colour keeps the text legible over screentone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from mangatl.domain.block import TextBlock
from mangatl.render import fonts
from mangatl.render.layout import FitResult, fit_horizontal, fit_vertical
from mangatl.render.style import TextStyle, apply_overrides, estimate_style

ROTATE_IN_VERTICAL = set("ー〜～~―—─–‐‑‒…‥⋯（）()［］")
VERTICAL_OFFSET = 1.06


@dataclass(frozen=True)
class RenderConfig:
    """Knobs for drawing."""

    min_font_size: int = 9
    line_spacing: float = 1.15
    column_spacing: float = 1.08
    max_stroke: int = 4


class PageRenderer:
    """Render every translatable block of a page."""

    name = "default"

    def __init__(self, config: RenderConfig | None = None) -> None:
        self.config = config or RenderConfig()

    def render(
        self,
        image_path: Path,
        blocks: Sequence[TextBlock],
        destination: Path,
        style_source: Path | None = None,
    ) -> Path:
        """Write the lettered page to ``destination`` and return it.

        ``style_source`` is the page *before* erasing: colour and stroke width must
        be measured while the glyphs are still there, otherwise the estimator sees
        only the bubble paper and produces pale grey text.
        """
        with Image.open(image_path) as handle:
            page = handle.convert("RGBA")
        style_pixels = _rgb_array(Image.open(style_source).convert("RGB")) if style_source else None
        if style_pixels is None:
            style_pixels = _rgb_array(page.copy())
        draw = ImageDraw.Draw(page)

        for block in blocks:
            text = block.translation.strip()
            if not text or block.role == "texture":
                continue
            style = estimate_style(
                style_pixels, None, block.bbox, vertical=block.vertical
            )
            style = apply_overrides(style, getattr(block, "style", {}) or {})
            self._draw_block(draw, page, block, text, style)

        destination.parent.mkdir(parents=True, exist_ok=True)
        page.convert("RGB").save(destination)
        return destination

    def measure(self, block: TextBlock, style_source: Path | None = None) -> int:
        """Font size the block would use right now, without drawing it."""
        text = block.translation.strip()
        if not text:
            return 0
        pixels = None
        if style_source is not None and Path(style_source).is_file():
            with Image.open(style_source) as handle:
                pixels = _rgb_array(handle.convert("RGB"))
        style = estimate_style(pixels, None, block.bbox, vertical=block.vertical)
        style = apply_overrides(style, getattr(block, "style", {}) or {})
        box = self._layout_box(block)
        width, height = max(1, box[2] - box[0]), max(1, box[3] - box[1])
        font_ref = fonts.resolve(style.category, style.weight) or fonts.resolve("sans")
        if font_ref is None:
            return 0
        explicit = int((block.style or {}).get("font_size") or 0)
        start = explicit or max(
            self.config.min_font_size + 2, int(style.font_size * 1.1)
        )
        floor = explicit or self.config.min_font_size
        stroke = self._stroke(style, start)
        text_width = max(1, width - 2 * stroke)
        text_height = max(1, height - 2 * stroke)
        if block.vertical:
            layout = fit_vertical(
                text,
                text_width,
                text_height,
                font_ref,
                start,
                min_size=floor,
                column_spacing=self.config.column_spacing,
            )
        else:
            spacing = float(
                (block.style or {}).get("line_spacing") or self.config.line_spacing
            )
            layout = fit_horizontal(
                text,
                text_width,
                text_height,
                font_ref,
                start,
                min_size=floor,
                line_spacing=spacing,
            )
        return int(layout.font_size)

    # -- internals --------------------------------------------------------
    def _draw_block(
        self,
        draw: ImageDraw.ImageDraw,
        page: Image.Image,
        block: TextBlock,
        text: str,
        style: TextStyle,
    ) -> None:
        box = self._layout_box(block)
        x1, y1, x2, y2 = box
        width, height = max(1, x2 - x1), max(1, y2 - y1)
        font_ref = fonts.resolve(style.category, style.weight) or fonts.resolve("sans")
        if font_ref is None:
            return  # no CJK font on this machine: skip rather than draw boxes

        rotation = float(getattr(block, "rotation", 0.0) or 0.0)
        target = page
        target_draw = draw
        if abs(rotation) > 0.01:
            # Letter on a transparent layer, then rotate about the box centre so
            # the glyphs can be placed at any angle without smearing the page.
            target = Image.new("RGBA", page.size, (0, 0, 0, 0))
            target_draw = ImageDraw.Draw(target)

        explicit_size = int((block.style or {}).get("font_size") or 0)
        start = explicit_size or max(self.config.min_font_size + 2, int(style.font_size * 1.1))
        # A locked size means "free transform": the frame may change, the glyphs
        # must not. Without it, dragging a handle would re-fit the text each time.
        floor = explicit_size or self.config.min_font_size
        # Reserve room for the outline: a glyph of size S plus stroke occupies S+2*stroke.
        text_width = max(1, width - 2 * self._stroke(style, start))
        text_height = max(1, height - 2 * self._stroke(style, start))
        if block.vertical:
            layout = fit_vertical(
                text,
                text_width,
                text_height,
                font_ref,
                start,
                min_size=floor,
                column_spacing=self.config.column_spacing,
            )
            self._draw_vertical(target_draw, target, block, layout, style, font_ref, box)
        else:
            spacing = float((block.style or {}).get("line_spacing") or self.config.line_spacing)
            layout = fit_horizontal(
                text,
                text_width,
                text_height,
                font_ref,
                start,
                min_size=floor,
                line_spacing=spacing,
            )
            self._draw_horizontal(target_draw, block, layout, style, font_ref, box)

        if target is not page:
            centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            rotated = target.rotate(
                -rotation,
                resample=Image.BICUBIC,
                center=centre,
                fillcolor=(0, 0, 0, 0),
            )
            page.alpha_composite(rotated)

        block.rendered_size = layout.font_size
        # Recompute rather than accumulate: an earlier run may have flagged this
        # block with a different font size, and stale flags are not actionable.
        block.needs_review = layout.overflow

    def _layout_box(self, block: TextBlock) -> tuple[int, int, int, int]:
        """Lettering area: the text box clipped to its bubble, with an inset."""
        x1, y1, x2, y2 = block.bbox
        if block.bubble_bbox is not None:
            bx1, by1, bx2, by2 = block.bubble_bbox
            x1, y1 = max(x1, bx1), max(y1, by1)
            x2, y2 = min(x2, bx2), min(y2, by2)
        inset = 3
        if x2 - x1 > 2 * inset and y2 - y1 > 2 * inset:
            x1, y1, x2, y2 = x1 + inset, y1 + inset, x2 - inset, y2 - inset
        return x1, y1, x2, y2

    def _draw_horizontal(
        self,
        draw: ImageDraw.ImageDraw,
        block: TextBlock,
        layout: FitResult,
        style: TextStyle,
        font_ref: fonts.FontRef,
        box: tuple[int, int, int, int],
    ) -> None:
        font = fonts.load(font_ref, layout.font_size)
        x1, y1, x2, y2 = box
        width = x2 - x1
        total = len(layout.lines) * layout.line_height
        top = y1 + ((y2 - y1) - total) / 2
        stroke = self._stroke(style, layout.font_size)

        for index, line in enumerate(layout.lines):
            if not line:
                continue
            line_width = font.getlength(line)
            if style.align == "left":
                x = x1
            elif style.align == "right":
                x = x2 - line_width
            else:
                x = x1 + (width - line_width) / 2
            y = top + index * layout.line_height
            draw.text(
                (x, y),
                line,
                font=font,
                fill=(*style.fg, 255),
                anchor="la",
                stroke_width=stroke,
                stroke_fill=(*style.bg, 255),
            )

    def _draw_vertical(
        self,
        draw: ImageDraw.ImageDraw,
        page: Image.Image,
        block: TextBlock,
        layout: FitResult,
        style: TextStyle,
        font_ref: fonts.FontRef,
        box: tuple[int, int, int, int],
    ) -> None:
        font = fonts.load(font_ref, layout.font_size)
        x1, y1, x2, y2 = box
        size = layout.font_size
        stroke = self._stroke(style, size)
        columns = layout.lines
        total_width = len(columns) * layout.line_height
        right = x2 - ((x2 - x1) - total_width) / 2

        for column_index, column in enumerate(columns):
            centre_x = right - column_index * layout.line_height - layout.line_height / 2
            for row, char in enumerate(column):
                if char.isspace():
                    continue
                centre_y = y1 + (row + 0.5) * size * VERTICAL_OFFSET
                if centre_y > y2:
                    break
                if char in ROTATE_IN_VERTICAL:
                    self._draw_rotated(page, char, centre_x, centre_y, font, style, stroke)
                else:
                    draw.text(
                        (centre_x, centre_y),
                        char,
                        font=font,
                        fill=(*style.fg, 255),
                        anchor="mm",
                        stroke_width=stroke,
                        stroke_fill=(*style.bg, 255),
                    )

    def _draw_rotated(
        self,
        page: Image.Image,
        char: str,
        centre_x: float,
        centre_y: float,
        font,
        style: TextStyle,
        stroke: int,
    ) -> None:
        size = int(font.size * 1.6) + 4
        tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tile_draw = ImageDraw.Draw(tile)
        tile_draw.text(
            (size / 2, size / 2),
            char,
            font=font,
            fill=(*style.fg, 255),
            anchor="mm",
            stroke_width=stroke,
            stroke_fill=(*style.bg, 255),
        )
        rotated = tile.rotate(90, resample=Image.BICUBIC, expand=False)
        page.alpha_composite(rotated, (int(centre_x - size / 2), int(centre_y - size / 2)))

    def _stroke(self, style: TextStyle, size: int) -> int:
        if style.font_size <= 0:
            return 0
        scaled = int(round(style.stroke_width * size / style.font_size))
        return max(0, min(self.config.max_stroke, scaled))


def _rgb_array(image: Image.Image):
    import numpy as np

    return np.array(image.convert("RGB"))
