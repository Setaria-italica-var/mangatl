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
