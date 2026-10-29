"""Text block domain object shared by every pipeline stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TextBlock:
    """One detected text region on a page.

    Coordinates are absolute pixels in the page image, ``(x1, y1, x2, y2)``.

    >>> block = TextBlock(id=0, bbox=(10, 20, 30, 40))
    >>> block.to_dict()["bbox"]
    (10, 20, 30, 40)
    """

    id: int
    bbox: tuple[int, int, int, int]
    text: str = ""
    translation: str = ""
    confidence: float = 0.0
    vertical: bool = False
    lines: list[list[tuple[int, int]]] = field(default_factory=list)
    needs_review: bool = False
    role: str = "dialogue"
    role_reasons: tuple[str, ...] = ()
    mask_coverage: float = 1.0
    area_fraction: float = 0.0
    bbox_erase: bool = True
    in_bubble: bool = True
    bubble_bbox: tuple[int, int, int, int] | None = None
    ocr_score: float = 0.0
    ocr_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping."""
        return {
            "id": self.id,
            "bbox": self.bbox,
            "text": self.text,
            "translation": self.translation,
            "confidence": round(self.confidence, 4),
            "vertical": self.vertical,
            "lines": self.lines,
            "needs_review": self.needs_review,
            "role": self.role,
            "role_reasons": list(self.role_reasons),
            "mask_coverage": round(self.mask_coverage, 4),
            "area_fraction": round(self.area_fraction, 4),
            "bbox_erase": self.bbox_erase,
            "in_bubble": self.in_bubble,
            "ocr_score": round(self.ocr_score, 4),
            "ocr_source": self.ocr_source,
            "bubble_bbox": list(self.bubble_bbox) if self.bubble_bbox else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TextBlock:
        """Rebuild a block from :meth:`to_dict` output.

        >>> TextBlock.from_dict({"id": 1, "bbox": [0, 0, 2, 2]}).bbox
        (0, 0, 2, 2)
        """
        x1, y1, x2, y2 = data["bbox"]
        return cls(
            id=int(data["id"]),
            bbox=(int(x1), int(y1), int(x2), int(y2)),
            text=str(data.get("text", "")),
            translation=str(data.get("translation", "")),
            confidence=float(data.get("confidence", 0.0)),
            vertical=bool(data.get("vertical", False)),
            lines=[[tuple(pt) for pt in line] for line in data.get("lines", [])],
            needs_review=bool(data.get("needs_review", False)),
            role=str(data.get("role", "dialogue")),
            role_reasons=tuple(data.get("role_reasons", ())),
            mask_coverage=float(data.get("mask_coverage", 1.0)),
            area_fraction=float(data.get("area_fraction", 0.0)),
            bbox_erase=bool(data.get("bbox_erase", True)),
            in_bubble=bool(data.get("in_bubble", True)),
            ocr_score=float(data.get("ocr_score", 0.0)),
            ocr_source=str(data.get("ocr_source", "")),
            bubble_bbox=tuple(data["bubble_bbox"]) if data.get("bubble_bbox") else None,
        )
