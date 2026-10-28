"""ComicTextDetector (CTD) adapter, ONNX runtime, no torch and no OpenCV.

The ONNX export exposes three tensors (verified with ``mangatl probe``):

===========  ====================  ==================================
name         shape                 meaning
===========  ====================  ==================================
``blk``      ``[1, 64512, 7]``     YOLO boxes (unused here)
``seg``      ``[1, 1, 1024, 1024]``  per-pixel text probability
``det``      ``[1, 2, 1024, 1024]``  DB shrink/threshold maps (unused here)
===========  ====================  ==================================

The mask is what the rest of the pipeline needs, so this adapter groups the mask
into blocks with a small union-find instead of porting the original YOLO + DB
decoders. Line polygons (needed for typesetting) come later; block boxes are
enough for erasing and for the solid-colour fast path.

>>> import numpy as np
>>> mask = np.zeros((10, 10), dtype=bool); mask[2:5, 2:6] = True
>>> boxes = mask_to_boxes(mask, min_area=3)
>>> boxes
[(2, 2, 6, 5)]
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from mangatl.domain.block import TextBlock

DEFAULT_MODEL = Path("data/models/comictextdetector.pt.onnx")
MODEL_ENV = "MANGATL_CTD_MODEL"


@dataclass(frozen=True)
class CtdConfig:
    """Paths and thresholds for the detector."""

    model_path: Path = DEFAULT_MODEL
    detect_size: int = 1024
    threshold: float = 0.5
    min_area: int = 24
    merge_gap: int = 14
    label_max_side: int = 256


def resolve_model_path(config: CtdConfig) -> Path:
    """Return the model path, honouring the ``MANGATL_CTD_MODEL`` override."""
    override = os.environ.get(MODEL_ENV)
    return Path(override) if override else Path(config.model_path)


def letterbox(image: Image.Image, size: int) -> tuple[np.ndarray, float, int, int]:
    """Resize with the aspect ratio kept, pad bottom/right with black.

    Returns the normalised ``(1, 3, size, size)`` blob plus the scale and the
    content size, so boxes can be mapped back exactly.
    """
    width, height = image.size
    scale = size / max(width, height)
    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))

    resized = image.resize((new_width, new_height), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), (0, 0, 0))
    canvas.paste(resized, (0, 0))

    array = np.asarray(canvas, dtype=np.float32) / 255.0
    blob = array.transpose(2, 0, 1)[None]
    return np.ascontiguousarray(blob), scale, new_width, new_height


def _union_find_labels(mask: np.ndarray) -> list[list[int]]:
    """Group ``True`` pixels into components; returns ``[x1, y1, x2, y2]`` boxes."""
    coords = np.argwhere(mask)
    if len(coords) == 0:
        return []

    lookup = {(int(y), int(x)): index for index, (y, x) in enumerate(coords)}
    parent = list(range(len(coords)))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for index, (y, x) in enumerate(coords):
        for neighbour in ((y, x - 1), (y - 1, x)):
            other = lookup.get((int(neighbour[0]), int(neighbour[1])))
            if other is not None:
                union(index, other)

    bounds: dict[int, list[int]] = {}
    for index, (y, x) in enumerate(coords):
        root = find(index)
        box = bounds.get(root)
        if box is None:
            bounds[root] = [int(x), int(y), int(x) + 1, int(y) + 1]
        else:
            box[0] = min(box[0], int(x))
            box[1] = min(box[1], int(y))
            box[2] = max(box[2], int(x) + 1)
            box[3] = max(box[3], int(y) + 1)
    return list(bounds.values())


def mask_to_boxes(mask: np.ndarray, min_area: int = 24) -> list[tuple[int, int, int, int]]:
    """Return one ``(x1, y1, x2, y2)`` box per connected component."""
    boxes: list[tuple[int, int, int, int]] = []
    for x1, y1, x2, y2 in _union_find_labels(mask):
        if (x2 - x1) * (y2 - y1) >= min_area:
            boxes.append((x1, y1, x2, y2))
    return boxes


def dilate_mask(mask: np.ndarray, radius: int = 2) -> np.ndarray:
    """Grow a boolean mask by a square structuring element.

    Glyphs inside one line rarely touch, so a small dilation is what turns
    "hundreds of blobs" into "a few lines" before labelling.
    """
    if radius <= 0:
        return mask
    out = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy == 0 and dx == 0:
                continue
            shifted = np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
            out |= shifted
    return out


def merge_boxes(
    boxes: Sequence[tuple[int, int, int, int]], gap: int = 14
) -> list[tuple[int, int, int, int]]:
    """Merge boxes that overlap, or that touch within ``gap`` on both axes."""
    merged = [tuple(box) for box in boxes]
    changed = True
    while changed:
        changed = False
        result: list[tuple[int, int, int, int]] = []
        for box in merged:
            for index, other in enumerate(result):
                if (
                    box[0] - gap <= other[2]
                    and other[0] - gap <= box[2]
                    and box[1] - gap <= other[3]
                    and other[1] - gap <= box[3]
                ):
                    result[index] = (
                        min(box[0], other[0]),
                        min(box[1], other[1]),
                        max(box[2], other[2]),
                        max(box[3], other[3]),
                    )
                    changed = True
                    break
            else:
                result.append(box)
        merged = result
    return merged


def merge_lines(boxes: Sequence[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Merge stacked or side-by-side lines into one block.

    Two boxes belong together when they overlap on one axis and the gap on the
    other is a fraction of the typical line height; that tolerates normal line
    spacing without gluing separate bubbles together.
    """
    items = [tuple(box) for box in boxes]
    if not items:
        return []
    heights = sorted(box[3] - box[1] for box in items)
    typical = max(8, heights[len(heights) // 2])

    changed = True
    while changed:
        changed = False
        result: list[tuple[int, int, int, int]] = []
        for box in items:
            for index, other in enumerate(result):
                overlap_x = min(box[2], other[2]) - max(box[0], other[0])
                overlap_y = min(box[3], other[3]) - max(box[1], other[1])
                gap_x = max(box[0], other[0]) - min(box[2], other[2])
                gap_y = max(box[1], other[1]) - min(box[3], other[3])
                stacked = overlap_x > 0.3 * min(box[2] - box[0], other[2] - other[0])
                stacked = stacked and gap_y <= 0.9 * typical
                side_by_side = overlap_y > 0.3 * min(box[3] - box[1], other[3] - other[1])
                side_by_side = side_by_side and gap_x <= 0.5 * typical
                if stacked or side_by_side:
                    result[index] = (
                        min(box[0], other[0]),
                        min(box[1], other[1]),
                        max(box[2], other[2]),
                        max(box[3], other[3]),
                    )
                    changed = True
                    break
            else:
                result.append(box)
        items = result
    return items


class CtdDetector:
    """Detect text blocks with ComicTextDetector running through onnxruntime."""

    name = "ctd"

    def __init__(self, config: CtdConfig | None = None) -> None:
        self.config = config or CtdConfig()
        path = resolve_model_path(self.config)
        if not path.is_file():
            raise FileNotFoundError(
                f"CTD model not found: {path}\n"
                f"download it or set {MODEL_ENV} (see docs/m0-plan.md)"
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise ImportError("CTD needs onnxruntime: uv pip install onnxruntime") from exc
        self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name

    def text_mask(self, image_path: Path) -> np.ndarray:
        """Return the per-pixel text probability at the original resolution."""
        with Image.open(image_path) as handle:
            image = handle.convert("RGB")
        blob, scale, content_w, content_h = letterbox(image, self.config.detect_size)
        outputs = dict(
            zip(
                [item.name for item in self._session.get_outputs()],
                self._session.run(None, {self._input_name: blob}),
                strict=True,
            )
        )
        probability = outputs["seg"][0, 0]
        cropped = probability[:content_h, :content_w]
        return np.asarray(
            Image.fromarray(cropped).resize(image.size, Image.BILINEAR), dtype=np.float32
        )

    def detect(self, image_path: Path) -> list[TextBlock]:
        """Return blocks in reading order (right to left when mostly vertical)."""
        blocks, _ = self.detect_with_mask(image_path)
        return blocks

    def detect_with_mask(self, image_path: Path) -> tuple[list[TextBlock], np.ndarray]:
        """Return blocks plus the per-pixel text probability for the inpainter."""
        with Image.open(image_path) as handle:
            width, height = handle.size
        probability = self.text_mask(image_path)
        mask = probability > self.config.threshold

        factor = max(1.0, max(width, height) / self.config.label_max_side)
        if factor > 1.0:
            small = Image.fromarray((mask * 255).astype(np.uint8)).resize(
                (max(1, int(width / factor)), max(1, int(height / factor))), Image.NEAREST
            )
            small_mask = np.asarray(small) > 127
        else:
            small_mask = mask

        grown = dilate_mask(small_mask, radius=2)
        small_boxes = mask_to_boxes(grown, min_area=self.config.min_area)
        scale_back = factor
        boxes = [
            (
                int(x1 * scale_back),
                int(y1 * scale_back),
                int(x2 * scale_back),
                int(y2 * scale_back),
            )
            for x1, y1, x2, y2 in small_boxes
        ]
        boxes = merge_lines(boxes)
        return self._to_blocks(boxes, width, height), probability

    @staticmethod
    def _to_blocks(
        boxes: Sequence[tuple[int, int, int, int]], width: int, height: int
    ) -> list[TextBlock]:
        blocks = [
            TextBlock(
                id=index,
                bbox=(max(0, x1), max(0, y1), min(width, x2), min(height, y2)),
                vertical=(y2 - y1) > (x2 - x1) * 1.6,
            )
            for index, (x1, y1, x2, y2) in enumerate(boxes)
        ]
        vertical_share = sum(1 for block in blocks if block.vertical) / max(1, len(blocks))
        if vertical_share > 0.5:
            blocks.sort(key=lambda block: (-block.bbox[2], block.bbox[1]))
        else:
            blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
        for index, block in enumerate(blocks):
            block.id = index
        return blocks
