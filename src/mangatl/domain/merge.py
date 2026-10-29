"""Merge OCR fragments that belong to the same speech bubble.

The text detector often splits one bubble into several boxes: a wide box for the
main line plus tiny boxes for a stray ``と`` or ``ん``, or two halves of a wrapped
line. Translating those separately produces half sentences and empty bubbles.

Merging is deliberately conservative: blocks must share an orientation, sit close
together with overlapping spans, and (when bubbles are known) fall in the same
bubble. Anything ambiguous is left alone.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from mangatl.domain.block import TextBlock

MAX_GAP = 12
MIN_SPAN_OVERLAP = 0.3


def _gap(a: tuple[int, int, int, int], b: tuple[int, int, int, int], vertical: bool) -> int:
    """Distance between two boxes along the axis that separates them."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    if vertical:
        horizontal = max(0, max(ax1, bx1) - min(ax2, bx2))
        vertical_gap = max(0, max(ay1, by1) - min(ay2, by2))
        return max(horizontal, vertical_gap)
    horizontal = max(0, max(ax1, bx1) - min(ax2, bx2))
    vertical_gap = max(0, max(ay1, by1) - min(ay2, by2))
    return max(horizontal, vertical_gap)


def _span_overlap(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int], vertical: bool
) -> float:
    """Overlap of the two boxes along their reading axis, as a fraction."""
    if vertical:
        a1, a2, b1, b2 = a[1], a[3], b[1], b[3]
    else:
        a1, a2, b1, b2 = a[0], a[2], b[0], b[2]
    overlap = max(0, min(a2, b2) - max(a1, b1))
    smallest = max(1, min(a2 - a1, b2 - b1))
    return overlap / smallest


def _union(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _reading_order(blocks: Sequence[TextBlock]) -> list[TextBlock]:
    """Order merged fragments the way they are read."""
    if not blocks:
        return []
    if blocks[0].vertical:
        return sorted(blocks, key=lambda block: (-block.bbox[2], block.bbox[1]))
    return sorted(blocks, key=lambda block: (block.bbox[1], block.bbox[0]))


def _same_bubble(a: TextBlock, b: TextBlock) -> bool | None:
    """``True``/``False`` when both know their bubble, ``None`` when unknown."""
    if a.bubble_bbox is None or b.bubble_bbox is None:
        return None
    ax1, ay1, ax2, ay2 = a.bubble_bbox
    bx1, by1, bx2, by2 = b.bubble_bbox
    intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    smallest = max(1, min((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1)))
    return intersection / smallest > 0.5


def merge_blocks(blocks: Sequence[TextBlock], max_gap: int = MAX_GAP) -> list[TextBlock]:
    """Union blocks that are fragments of the same bubble text.

    Returns new blocks (ids are reassigned) so callers can store them directly.
    """
    items = list(blocks)
    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            first, second = items[i], items[j]
            if first.vertical != second.vertical:
                continue
            same = _same_bubble(first, second)
            if same is False:
                continue
            from mangatl.adapters.detectors.ctd import can_merge

            if not can_merge(first.bbox, second.bbox):
                continue
            union(i, j)

    groups: dict[int, list[TextBlock]] = {}
    for index, item in enumerate(items):
        groups.setdefault(find(index), []).append(item)

    merged: list[TextBlock] = []
    for members in groups.values():
        ordered = _reading_order(members)
        box = ordered[0].bbox
        for member in ordered[1:]:
            box = _union(box, member.bbox)
        directions = Counter(member.vertical for member in ordered)
        vertical = directions.most_common(1)[0][0]
        text = "".join(member.text for member in ordered).strip()
        merged.append(
            TextBlock(
                id=len(merged),
                bbox=box,
                text=text,
                translation="".join(member.translation for member in ordered).strip(),
                confidence=min(member.confidence for member in ordered),
                vertical=vertical,
                needs_review=any(member.needs_review for member in ordered),
                role=ordered[0].role,
                role_reasons=ordered[0].role_reasons,
                in_bubble=any(member.in_bubble for member in ordered),
                bubble_bbox=ordered[0].bubble_bbox,
            )
        )
    return merged
