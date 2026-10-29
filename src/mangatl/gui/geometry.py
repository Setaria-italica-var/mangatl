"""Geometry helpers for the editor: polygons, boxes and masks.

Kept free of Qt so the selection maths can be unit-tested without a display.
"""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageDraw


def polygon_bbox(points: Sequence[tuple[float, float]]) -> tuple[int, int, int, int]:
    """Integer half-open bounding box of a polygon.

    >>> polygon_bbox([(10, 10), (50, 10), (50, 40), (10, 40)])
    (10, 10, 50, 40)
    """
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def clamp_bbox(
    bbox: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    """Clip a box to the page."""
    x1, y1, x2, y2 = bbox
    return (
        max(0, min(x1, width)),
        max(0, min(y1, height)),
        max(0, min(x2, width)),
        max(0, min(y2, height)),
    )


def polygon_mask(
    points: Sequence[tuple[float, float]], width: int, height: int
) -> Image.Image:
    """Rasterise a polygon into an 8-bit mask (255 inside)."""
    mask = Image.new("L", (width, height), 0)
    if len(points) >= 3:
        ImageDraw.Draw(mask).polygon([(float(x), float(y)) for x, y in points], fill=255)
    return mask


def bbox_intersects(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> bool:
    """Whether two half-open boxes overlap."""
    return (
        min(first[2], second[2]) > max(first[0], second[0])
        and min(first[3], second[3]) > max(first[1], second[1])
    )


def bbox_contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    """Whether ``inner`` sits completely inside ``outer``."""
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def scale_bbox(
    bbox: tuple[int, int, int, int], factor: float, offset: tuple[int, int] = (0, 0)
) -> tuple[int, int, int, int]:
    """Scale then translate a box (used when detecting on a crop)."""
    x1, y1, x2, y2 = bbox
    return (
        int(round(x1 * factor)) + offset[0],
        int(round(y1 * factor)) + offset[1],
        int(round(x2 * factor)) + offset[0],
        int(round(y2 * factor)) + offset[1],
    )


HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")


def move_bbox(
    bbox: tuple[int, int, int, int], dx: int, dy: int, width: int, height: int
) -> tuple[int, int, int, int]:
    """Translate a box, keeping it fully inside the page.

    >>> move_bbox((10, 10, 50, 40), -100, 0, 200, 200)
    (0, 10, 40, 40)
    """
    x1, y1, x2, y2 = bbox
    box_width, box_height = x2 - x1, y2 - y1
    left = max(0, min(x1 + dx, width - box_width))
    top = max(0, min(y1 + dy, height - box_height))
    return (left, top, left + box_width, top + box_height)


def resize_bbox(
    bbox: tuple[int, int, int, int],
    handle: str,
    dx: int,
    dy: int,
    min_size: int = 8,
) -> tuple[int, int, int, int]:
    """Resize a box by dragging one of its eight handles.

    ``handle`` is one of ``nw n ne e se s sw w``; ``dx``/``dy`` are the drag delta.

    >>> resize_bbox((10, 10, 60, 50), "se", 10, 5)
    (10, 10, 70, 55)
    >>> resize_bbox((10, 10, 60, 50), "nw", 100, 100)
    (52, 42, 60, 50)
    """
    x1, y1, x2, y2 = bbox
    if "w" in handle:
        x1 += dx
    if "e" in handle:
        x2 += dx
    if "n" in handle:
        y1 += dy
    if "s" in handle:
        y2 += dy
    if x2 - x1 < min_size:
        if "w" in handle:
            x1 = x2 - min_size
        else:
            x2 = x1 + min_size
    if y2 - y1 < min_size:
        if "n" in handle:
            y1 = y2 - min_size
        else:
            y2 = y1 + min_size
    return (x1, y1, x2, y2)
