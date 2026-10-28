"""Speech-bubble detection with a YOLOv8 ONNX model.

Model weights come from the community (see ``docs/bubble-and-inpaint-plan.md``);
this module owns only preprocessing, decoding and NMS, so it can be unit-tested
with synthetic tensors and no weights at all.

Only the *bubble* class is used: text inside a bubble is erased and translated,
text printed on the artwork is left alone. When the weights are missing the caller
keeps the heuristic fallback, never a silent "assume bubble".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_IMGSZ = 640
DEFAULT_CONFIDENCE = 0.3
DEFAULT_IOU = 0.45
BUBBLE_CLASS_NAMES = ("bubble", "speech_bubble", "speech bubble")


@dataclass(frozen=True)
class Bubble:
    """A detected bubble in page coordinates (half-open box)."""

    bbox: tuple[int, int, int, int]
    score: float


def letterbox(
    image: np.ndarray, size: int = DEFAULT_IMGSZ
) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Resize with aspect ratio kept and pad to ``size``.

    Returns the HWC uint8 tensor, the scale applied to the image and the
    ``(pad_x, pad_y)`` offsets, so boxes can be mapped back to page space.
    """
    height, width = image.shape[:2]
    scale = min(size / width, size / height)
    new_width, new_height = int(round(width * scale)), int(round(height * scale))
    if new_width != width or new_height != height:
        from PIL import Image

        image = np.asarray(Image.fromarray(image).resize((new_width, new_height)))
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x = (size - new_width) // 2
    pad_y = (size - new_height) // 2
    canvas[pad_y : pad_y + new_height, pad_x : pad_x + new_width] = image[:, :, :3]
    return canvas, scale, (pad_x, pad_y)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Class-agnostic non-maximum suppression; returns kept indices."""
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        index = int(order[0])
        keep.append(index)
        if order.size == 1:
            break
        rest = order[1:]
        overlaps = _iou(boxes[index], boxes[rest])
        order = rest[overlaps <= iou_threshold]
    return keep


def _iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_box = (box[2] - box[0]) * (box[3] - box[1])
    area_boxes = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union = area_box + area_boxes - inter
    return inter / np.maximum(union, 1e-6)


def decode(
    output: np.ndarray,
    confidence: float,
    iou_threshold: float,
    scale: float,
    padding: tuple[int, int],
    page_size: tuple[int, int],
    class_index: int | None = None,
) -> list[Bubble]:
    """Turn a YOLOv8 head into page-space boxes.

    Accepts both layouts models ship with: ``(1, 4+nc, N)`` (Ultralytics export)
    and ``(1, N, 4+nc)``. ``class_index`` pins the bubble class for multi-class
    models; ``None`` keeps the best-scoring class per anchor.
    """
    tensor = np.asarray(output)
    if tensor.ndim == 3:
        tensor = tensor[0]
    if tensor.ndim != 2:
        return []
    # Decide which axis is the channel axis: it is small (4+nc, at most a few
    # hundred) while the anchor count is large (thousands).
    rows, cols = tensor.shape
    if rows <= 200 and cols > 200 or cols < 5:
        tensor = tensor.T
    if tensor.shape[1] < 5:
        return []

    boxes = tensor[:, :4]
    scores_all = tensor[:, 4:]
    if class_index is not None and class_index < scores_all.shape[1]:
        scores = scores_all[:, class_index]
    else:
        scores = scores_all.max(axis=1)

    mask = scores >= confidence
    if not mask.any():
        return []
    centers = boxes[mask]
    scores = scores[mask]

    x1 = centers[:, 0] - centers[:, 2] / 2
    y1 = centers[:, 1] - centers[:, 3] / 2
    x2 = centers[:, 0] + centers[:, 2] / 2
    y2 = centers[:, 1] + centers[:, 3] / 2
    corners = np.stack([x1, y1, x2, y2], axis=1)

    pad_x, pad_y = padding
    page_width, page_height = page_size
    corners[:, [0, 2]] = (corners[:, [0, 2]] - pad_x) / scale
    corners[:, [1, 3]] = (corners[:, [1, 3]] - pad_y) / scale
    corners[:, [0, 2]] = np.clip(corners[:, [0, 2]], 0, page_width)
    corners[:, [1, 3]] = np.clip(corners[:, [1, 3]], 0, page_height)

    kept = nms(corners, scores, iou_threshold)
    bubbles: list[Bubble] = []
    for index in kept:
        left, top, right, bottom = (int(round(value)) for value in corners[index])
        if right - left < 4 or bottom - top < 4:
            continue
        bubbles.append(Bubble((left, top, right, bottom), float(scores[index])))
    return bubbles


def class_count(output: np.ndarray) -> int:
    """Number of classes encoded in a YOLO head (channels minus the box)."""
    tensor = np.asarray(output)
    if tensor.ndim == 3:
        tensor = tensor[0]
    if tensor.ndim != 2:
        return 0
    rows, cols = tensor.shape
    channels = rows if rows <= 200 and cols > 200 else cols
    return max(0, channels - 4)


def inside(block_bbox: tuple[int, int, int, int], bubbles: list[Bubble], pad: int = 2) -> bool:
    """Whether the block's centre lies inside any bubble (with a small pad)."""
    x1, y1, x2, y2 = block_bbox
    centre_x, centre_y = (x1 + x2) / 2, (y1 + y2) / 2
    for bubble in bubbles:
        bx1, by1, bx2, by2 = bubble.bbox
        if bx1 - pad <= centre_x <= bx2 + pad and by1 - pad <= centre_y <= by2 + pad:
            return True
    return False


def covered(block_bbox: tuple[int, int, int, int], bubbles: list[Bubble]) -> bool:
    """Bubble membership: enough overlap, or the centre is inside a bubble.

    OCR boxes are often a few pixels larger than the bubble, so a strict
    ``coverage >= 0.8`` test drops real dialogue; the centre test catches those
    without letting a block that merely touches a bubble pass.
    """
    return coverage(block_bbox, bubbles) >= 0.6 or inside(block_bbox, bubbles)


def coverage(block_bbox: tuple[int, int, int, int], bubbles: list[Bubble]) -> float:
    """Fraction of a block's area covered by the union of bubbles (0..1)."""
    x1, y1, x2, y2 = block_bbox
    area = max(1, (x2 - x1) * (y2 - y1))
    covered = 0
    for bubble in bubbles:
        bx1, by1, bx2, by2 = bubble.bbox
        overlap_x = max(0, min(x2, bx2) - max(x1, bx1))
        overlap_y = max(0, min(y2, by2) - max(y1, by1))
        covered += overlap_x * overlap_y
    return min(1.0, covered / area)


class BubbleDetector:
    """ONNX YOLOv8 bubble detector (detection head only)."""

    name = "bubble_yolo"

    def __init__(
        self,
        model_path: Path | str,
        imgsz: int = DEFAULT_IMGSZ,
        confidence: float = DEFAULT_CONFIDENCE,
        iou: float = DEFAULT_IOU,
        class_index: int | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.imgsz = imgsz
        self.confidence = confidence
        self.iou = iou
        self.class_index = class_index
        self._session = None

    @property
    def available(self) -> bool:
        """Whether the weights exist (the session itself is created lazily)."""
        return self.model_path.is_file()

    def detect_multi(
        self, image_path: Path, blocks=()
    ) -> tuple[list[Bubble], int | None, dict[int, float]]:
        """Detect bubbles, choosing the bubble class automatically when needed.

        Multi-class checkpoints (text + bubble) are common; instead of guessing the
        class id, each candidate class is scored by how well its boxes enclose the
        OCR blocks. The best class wins for the whole page.

        Returns ``(bubbles, class_index, per_class_score)``.
        """
        if not self.available:
            return [], None, {}
        from PIL import Image

        session = self._get_session()
        with Image.open(image_path) as handle:
            page = handle.convert("RGB")
            page_size = page.size
            image = np.asarray(page)

        canvas, scale, padding = letterbox(image, self.imgsz)
        tensor = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        outputs = session.run(None, {session.get_inputs()[0].name: tensor})
        output = outputs[0]

        total = class_count(output)
        if total <= 1 or self.class_index is not None:
            index = self.class_index if self.class_index is not None else 0
            chosen = index if total > 1 else None
            bubbles = decode(
                output, self.confidence, self.iou, scale, padding, page_size, chosen
            )
            return bubbles, index, {}

        scores: dict[int, float] = {}
        best_index, best_bubbles, best_score = 0, [], -1.0
        for index in range(total):
            bubbles = decode(output, self.confidence, self.iou, scale, padding, page_size, index)
            score = (
                float(np.mean([coverage(block.bbox, bubbles) for block in blocks]))
                if blocks and bubbles
                else 0.0
            )
            scores[index] = score
            if score > best_score:
                best_index, best_bubbles, best_score = index, bubbles, score
        return best_bubbles, best_index, scores

    def detect(self, image_path: Path) -> list[Bubble]:
        """Detect bubbles on one page, in page coordinates."""
        if not self.available:
            return []
        from PIL import Image

        session = self._get_session()
        with Image.open(image_path) as handle:
            page = handle.convert("RGB")
            page_size = page.size
            image = np.asarray(page)

        canvas, scale, padding = letterbox(image, self.imgsz)
        tensor = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        outputs = session.run(None, {session.get_inputs()[0].name: tensor})
        return decode(
            outputs[0],
            self.confidence,
            self.iou,
            scale,
            padding,
            page_size,
            self.class_index,
        )

    def _get_session(self):
        if self._session is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(
                str(self.model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        return self._session
