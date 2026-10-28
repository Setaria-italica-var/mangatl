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
from mangatl.render.style import TextStyle, estimate_style

ROTATE_IN_VERTICAL = set("ー〜~…‥—―「」『』（）()［］[]")
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
    ) -> Path:
        """Write the lettered page to ``destination`` and return it."""
        with Image.open(image_path) as handle:
            page = handle.convert("RGBA")
        pixels = page.copy()
        draw = ImageDraw.Draw(page)

        for block in blocks:
            text = block.translation.strip()
            if not text or block.role == "texture":
                continue
            style = estimate_style(
                _rgb_array(pixels), None, block.bbox, vertical=block.vertical
            )
            self._draw_block(draw, page, block, text, style)

        destination.parent.mkdir(parents=True, exist_ok=True)
        page.convert("RGB").save(destination)
        return destination

    # -- internals --------------------------------------------------------
    def _draw_block(
        self,
        draw: ImageDraw.ImageDraw,
        page: Image.Image,
        block: TextBlock,
        text: str,
        style: TextStyle,
    ) -> None:
        x1, y1, x2, y2 = block.bbox
        width, height = max(1, x2 - x1), max(1, y2 - y1)
        font_ref = fonts.resolve(style.category, style.weight) or fonts.resolve("sans")
        if font_ref is None:
            return  # no CJK font on this machine: skip rather than draw boxes

        start = max(self.config.min_font_size + 2, int(style.font_size * 1.1))
        if block.vertical:
            layout = fit_vertical(
                text,
                width,
                height,
                font_ref,
                start,
                min_size=self.config.min_font_size,
                column_spacing=self.config.column_spacing,
            )
            self._draw_vertical(draw, page, block, layout, style, font_ref)
        else:
            layout = fit_horizontal(
                text,
                width,
                height,
                font_ref,
                start,
                min_size=self.config.min_font_size,
                line_spacing=self.config.line_spacing,
            )
            self._draw_horizontal(draw, block, layout, style, font_ref)

        # Recompute rather than accumulate: an earlier run may have flagged this
        # block with a different font size, and stale flags are not actionable.
        block.needs_review = layout.overflow

    def _draw_horizontal(
        self,
        draw: ImageDraw.ImageDraw,
        block: TextBlock,
        layout: FitResult,
        style: TextStyle,
        font_ref: fonts.FontRef,
    ) -> None:
        font = fonts.load(font_ref, layout.font_size)
        x1, y1, x2, y2 = block.bbox
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
    ) -> None:
        font = fonts.load(font_ref, layout.font_size)
        x1, y1, x2, y2 = block.bbox
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
