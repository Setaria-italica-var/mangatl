"""Image analysis shared by adapters: ink mask, connected components, structure.

No torch, no OpenCV: everything is numpy, with a run-length union-find so a
1600x2400 page still labels in a fraction of a second.

>>> import numpy as np
>>> mask = np.zeros((6, 6), dtype=bool); mask[1:3, 1:3] = True
>>> labels, stats = label_components(mask)
>>> len(stats)
1
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def otsu_threshold(gray: np.ndarray) -> int:
    """Return Otsu's threshold for an 8-bit grayscale image."""
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = histogram.sum()
    if total == 0:
        return 127
    levels = np.arange(256, dtype=np.float64)
    weight = np.cumsum(histogram)
    mean = np.cumsum(histogram * levels)
    mean_total = mean[-1]
    denominator = weight * (total - weight)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mean_total * weight - mean * total) ** 2 / denominator
    between[~np.isfinite(between)] = 0.0
    return int(np.argmax(between))


def ink_mask(gray: np.ndarray) -> np.ndarray:
    """Return pixels darker than Otsu's threshold (assumes dark ink on light paper)."""
    return gray <= otsu_threshold(gray)


@dataclass(frozen=True)
class ComponentStats:
    """Shape summary of one connected component."""

    label: int
    area: int
    bbox: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]

    @property
    def fill(self) -> float:
        """Area divided by bounding-box area; loops and strokes are low."""
        box = max(1, self.width * self.height)
        return self.area / box

    @property
    def thickness(self) -> float:
        """Average stroke width estimated from area and the longer side."""
        return self.area / max(1, max(self.width, self.height))


def label_components(mask: np.ndarray) -> tuple[np.ndarray, list[ComponentStats]]:
    """Label 4-connected components with a run-length union-find.

    Returns the label image and per-component statistics. Runs (not pixels) are
    the unit of work, which keeps a full page fast enough for the CPU path.
    """
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    parent: list[int] = [0]
    runs: list[tuple[int, int, int, int]] = []  # y, x1, x2, label

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    next_label = 1
    previous: list[tuple[int, int, int]] = []
    for y in range(height):
        row = mask[y]
        if not row.any():
            previous = []
            continue
        padded = np.concatenate(([False], row, [False]))
        changed = np.diff(padded.astype(np.int8))
        starts = np.flatnonzero(changed == 1)
        ends = np.flatnonzero(changed == -1)

        current: list[tuple[int, int, int]] = []
        for start, end in zip(starts, ends, strict=True):
            label = 0
            for prev_start, prev_end, prev_label in previous:
                if prev_start < end and start < prev_end:
                    if label == 0:
                        label = prev_label
                    else:
                        union(label, prev_label)
            if label == 0:
                label = next_label
                parent.append(label)
                next_label += 1
            labels[y, start:end] = label
            current.append((int(start), int(end), label))
            runs.append((y, int(start), int(end), label))
        previous = current

    roots = np.array([find(index) for index in range(next_label)], dtype=np.int32)
    labels = roots[labels]

    accumulated: dict[int, list[int]] = {}
    for y, start, end, label in runs:
        root = int(roots[label])
        entry = accumulated.get(root)
        if entry is None:
            accumulated[root] = [end - start, start, y, end, y + 1]
        else:
            entry[0] += end - start
            entry[1] = min(entry[1], start)
            entry[2] = min(entry[2], y)
            entry[3] = max(entry[3], end)
            entry[4] = max(entry[4], y + 1)

    stats = [
        ComponentStats(
            label=label,
            area=values[0],
            bbox=(values[1], values[2], values[3], values[4]),
        )
        for label, values in sorted(accumulated.items())
    ]
    return labels, stats


def bounded_background(
    pixels: np.ndarray,
    bbox: tuple[int, int, int, int],
    *,
    light: int = 200,
    window_scale: float = 1.6,
) -> bool:
    """Whether the light background around ``bbox`` is enclosed nearby.

    Flood fills the light pixels from the block's centre inside a limited window.
    If the fill reaches the window edge the background continues into the artwork
    (no bubble); if it stays inside, the text sits in a closed bubble. This is
    tolerant of small gaps in the outline, which a strict loop test is not.

    >>> import numpy as np
    >>> page = np.full((60, 60, 3), 250, dtype=np.uint8)
    >>> bounded_background(page, (20, 20, 40, 40))
    False
    """
    from collections import deque

    height, width = pixels.shape[:2]
    x1, y1, x2, y2 = bbox
    x1, y1 = max(0, min(x1, width)), max(0, min(y1, height))
    x2, y2 = max(0, min(x2, width)), max(0, min(y2, height))
    if x2 <= x1 or y2 <= y1:
        return False

    pad_x = int((x2 - x1) * (window_scale - 1) / 2) + 8
    pad_y = int((y2 - y1) * (window_scale - 1) / 2) + 8
    left, top = max(0, x1 - pad_x), max(0, y1 - pad_y)
    right, bottom = min(width, x2 + pad_x), min(height, y2 + pad_y)
    if right - left < 8 or bottom - top < 8:
        return False

    crop = pixels[top:bottom, left:right, :3].astype(np.float32).mean(axis=2)
    background = crop >= light
    rows, cols = background.shape
    start_y, start_x = (y1 + y2) // 2 - top, (x1 + x2) // 2 - left
    start_y = min(max(0, start_y), rows - 1)
    start_x = min(max(0, start_x), cols - 1)
    if not background[start_y, start_x]:
        return False

    seen = np.zeros_like(background, dtype=bool)
    queue = deque([(start_y, start_x)])
    seen[start_y, start_x] = True
    while queue:
        y, x = queue.popleft()
        if y in (0, rows - 1) or x in (0, cols - 1):
            return False
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < rows and 0 <= nx < cols and background[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                queue.append((ny, nx))
    return True


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Return ``mask`` plus every enclosed region (a binary fill-holes).

    Used to turn bubble outlines into their interior: label the complement, keep
    the components that do not touch the page border, and add them back.

    >>> import numpy as np
    >>> ring = np.zeros((9, 9), dtype=bool)
    >>> ring[2, 2:7] = ring[6, 2:7] = ring[2:7, 2] = ring[2:7, 6] = True
    >>> fill_holes(ring)[4, 4]
    True
    """
    complement = ~mask
    labels, stats = label_components(complement)
    if not stats:
        return mask

    border_labels: set[int] = set()
    border_labels.update(int(label) for label in labels[0, :])
    border_labels.update(int(label) for label in labels[-1, :])
    border_labels.update(int(label) for label in labels[:, 0])
    border_labels.update(int(label) for label in labels[:, -1])
    border_labels.discard(0)

    holes = (labels > 0) & ~np.isin(labels, list(border_labels))
    return mask | holes


def structure_mask(
    labels: np.ndarray,
    stats: list[ComponentStats],
    text_mask: np.ndarray,
    block_area: np.ndarray | None = None,
) -> np.ndarray:
    """Return the ink components that look like structure, not glyphs.

    Three cases cover the styles the pipeline must survive:

    * **bubble outline** - a large, mostly empty loop (low ``fill``);
    * **dashed / thin rules** - long and thin, whatever their size;
    * **solid black areas** - panels or inverted bubbles, large and filled.

    Only components that actually intersect ``text_mask`` are considered, so a
    quiet page does not pay for the classification.
    """
    height, width = labels.shape
    page_area = float(height * width)
    page_extent = float(max(height, width))

    selected = np.zeros_like(labels, dtype=bool)
    for item in stats:
        if item.area < 20:
            continue
        component = labels == item.label
        if not bool((component & text_mask).any()):
            continue
        long_side = float(max(item.width, item.height))
        short_side = float(max(1, min(item.width, item.height)))
        loop = item.fill < 0.2 and long_side > 0.12 * page_extent
        blob = item.fill > 0.85 and item.area > 0.02 * page_area
        dash = (
            long_side / short_side >= 1.8
            and item.thickness <= 5
            and item.area >= 10
        )
        if dash and block_area is not None:
            # A dash sits on a bubble edge, i.e. outside the text block. The same
            # shape inside a block is a glyph stroke and must be erased.
            inside = float((component & block_area).sum()) / max(1, item.area)
            dash = inside < 0.3
        if loop or blob or dash:
            selected |= component
    return selected
