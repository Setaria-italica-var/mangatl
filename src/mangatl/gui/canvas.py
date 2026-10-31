"""Canvas: image, block overlays and the lasso/rectangle selection tools."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)

from mangatl.gui.geometry import bbox_intersects, move_bbox, resize_bbox

ROLE_COLORS = {
    "dialogue": QColor(64, 158, 255, 70),
    "sfx": QColor(255, 170, 60, 80),
    "symbol": QColor(180, 180, 180, 70),
    "texture": QColor(120, 120, 120, 40),
}


class PageCanvas(QGraphicsView):
    """Zoomable page view with selectable blocks and lasso input."""

    blockClicked = Signal(int)
    lassoFinished = Signal(list)
    rectFinished = Signal(tuple)
    cursorMoved = Signal(int, int)
    blockGeometryChanged = Signal(int, tuple)
    selectionChanged = Signal(bool)
    selectionIdsChanged = Signal(list)
    contextMenuRequested = Signal(object)
    blockRotated = Signal(int, float)
    brushFinished = Signal(list, int, bool)
    brushRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(self.renderHints())
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(32, 34, 38))

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._overlay_items: dict[int, QGraphicsRectItem] = {}
        self._preview: QGraphicsPolygonItem | None = None
        self._brush_points: list[QPointF] = []
        self._brush_item: QGraphicsPathItem | None = None
        self._brush_cursor: QGraphicsEllipseItem | None = None
        self._brush_radius = 32
        self._brush_erase = True
        self._selection: QGraphicsPolygonItem | None = None
        self._selection_points: list[tuple[float, float]] = []
        self._mode = "select"
        self._overlay_opacity = 1.0
        self._selected_id: int | None = None
        self._handle_items: dict[str, QGraphicsRectItem] = {}
        self._drag: dict | None = None
        self._selected: list[int] = []
        self._rubber: dict | None = None
        self._rubber_item: QGraphicsRectItem | None = None
        self._rubber_moved = False
        self._overlay_mode = "blocks"
        self._region_enabled = True
        self._rotations: dict[int, float] = {}
        self._diff_item: QGraphicsPixmapItem | None = None
        self._points: list[QPointF] = []
        self._panning = False
        self._pan_start = QPointF()

    # -- modes ------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """``select``, ``lasso``, ``rect`` or ``brush``."""
        self._mode = mode
        self._brush_points = []
        self._clear_brush_preview()
        if mode != "brush":
            self._hide_brush_cursor()
        self.viewport().setCursor(
            Qt.CursorShape.CrossCursor
            if mode == "brush"
            else Qt.CursorShape.ArrowCursor
        )
        if mode == "select":
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

    @property
    def mode(self) -> str:
        return self._mode

    def set_brush_radius(self, radius: int) -> None:
        self._brush_radius = max(2, int(radius))
        self._update_brush_cursor(None)

    def _brush_path(self, points: list[QPointF]) -> QPainterPath:
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        return path

    def _update_brush_preview(self) -> None:
        self._clear_brush_preview()
        if not self._brush_points:
            return
        item = QGraphicsPathItem(self._brush_path(self._brush_points))
        colour = (
            QColor(255, 90, 90, 110)
            if self._brush_erase
            else QColor(80, 200, 255, 110)
        )
        pen = QPen(colour, self._brush_radius * 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        item.setPen(pen)
        item.setZValue(8)
        self.scene().addItem(item)
        self._brush_item = item

    def _clear_brush_preview(self) -> None:
        if self._brush_item is not None:
            self._remove_item(self._brush_item)
            self._brush_item = None

    def _update_brush_cursor(self, position: QPointF | None) -> None:
        if self._mode != "brush":
            self._hide_brush_cursor()
            return
        if position is None or not self.sceneRect().contains(position):
            self._hide_brush_cursor()
            return
        if self._brush_cursor is None:
            # Magenta reads clearly on white paper, black ink and greyscale screentone.
            item = QGraphicsEllipseItem()
            item.setPen(QPen(QColor(255, 0, 255, 235), 0))
            item.setBrush(QBrush(QColor(255, 0, 255, 28)))
            item.setZValue(20)
            self.scene().addItem(item)
            self._brush_cursor = item
        radius = self._brush_radius
        self._brush_cursor.setRect(
            position.x() - radius, position.y() - radius, radius * 2, radius * 2
        )

    def _hide_brush_cursor(self) -> None:
        if self._brush_cursor is not None:
            self._remove_item(self._brush_cursor)
            self._brush_cursor = None

    # -- content ----------------------------------------------------------
    def show_image(
        self, path, keep_selection: bool = False, preserve_view: bool = False
    ) -> None:
        """Load the page image and reset the view.

        ``keep_selection`` keeps the lasso/rectangle alive when only the preview
        layer changes (original → erased → result), so the user does not lose the
        region while comparing.
        """
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            # Never clear the view for an unreadable file: keep the previous page.
            return
        kept_points = list(self._selection_points) if keep_selection else []
        self.scene().clear()
        # scene().clear() deletes the C++ items; drop the Python wrappers too, or
        # later removals raise "Internal C++ object already deleted".
        self._overlay_items.clear()
        self._handle_items.clear()
        self._preview = None
        self._selection = None
        self._selection_points = []
        self._diff_item = None
        self._brush_item = None
        self._brush_cursor = None
        self._brush_points = []
        if kept_points:
            self._show_selection(kept_points)
        self._pixmap_item = self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        if not preserve_view:
            self.fit()

    def _display_rect(self, block) -> tuple[int, int, int, int]:
        """Result view edits the type-setting frame; source view edits the box."""
        if self._overlay_mode == "text" and block.text_bbox is not None:
            return tuple(int(v) for v in block.text_bbox)
        return tuple(int(v) for v in block.bbox)

    def set_overlay_mode(self, mode: str) -> None:
        """``blocks`` (source), ``diff`` (erased) or ``text`` (result).

        Each view owns one kind of selection: source and result select blocks,
        erased selects a region to erase. Keeping them exclusive avoids the region
        polygon and the block highlight interfering with each other.
        """
        self._overlay_mode = mode
        self._region_enabled = mode in {"blocks", "diff"}
        if not self._region_enabled:
            self.clear_selection()

    def show_erased_diff(self, source_path, erased_path) -> None:
        """Tint the pixels that differ between the page and its erased copy."""
        self.clear_erased_diff()
        try:
            import numpy as np
            from PIL import Image
        except ImportError:
            return
        try:
            with Image.open(source_path) as handle:
                source = handle.convert("RGB")
            with Image.open(erased_path) as handle:
                erased = handle.convert("RGB")
        except OSError:
            return
        if source.size != erased.size:
            return
        before = np.asarray(source, dtype=np.int16)
        after = np.asarray(erased, dtype=np.int16)
        # Erasing lightens ink strokes; JPEG noise and diffusion haze change both
        # directions equally, so only "got brighter" pixels are real removals.
        before_lum = before.mean(axis=2)
        after_lum = after.mean(axis=2)
        mask = (after_lum - before_lum) > 22
        if not mask.any():
            return
        rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
        rgba[mask] = (255, 90, 90, 150)
        height, width = mask.shape
        image = QImage(
            rgba.data, width, height, 4 * width, QImage.Format.Format_RGBA8888
        ).copy()
        item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        item.setZValue(2)
        self.scene().addItem(item)
        self._diff_item = item

    def clear_erased_diff(self) -> None:
        if self._diff_item is not None:
            self._remove_item(self._diff_item)
            self._diff_item = None

    def set_blocks(self, blocks, selected_ids: Sequence[int] = ()) -> None:
        """Redraw block overlays."""
        self._last_blocks = list(blocks)
        self._last_selected = tuple(selected_ids)
        for item in self._overlay_items.values():
            self._remove_item(item)
        self._overlay_items.clear()
        self._clear_handles()
        self._selected = list(selected_ids)
        self._selected_id = self._selected[0] if self._selected else None
        self._rotations = {
            block.id: float(getattr(block, "rotation", 0.0) or 0.0) for block in blocks
        }
        if self._overlay_mode == "diff":
            return
        for block in blocks:
            x1, y1, x2, y2 = self._display_rect(block)
            colour = QColor(ROLE_COLORS.get(block.role, QColor(200, 200, 200, 60)))
            colour.setAlpha(int(colour.alpha() * self._overlay_opacity))
            pen = QPen(QColor(255, 255, 255, 220), 1.2)
            if self._overlay_mode == "text":
                # Untranslated blocks stay visible but dimmed, so the frame tools
                # never look "missing" on a page that has not been translated yet.
                if block.translation.strip():
                    pen = QPen(QColor(255, 255, 255, 235), 1.6, Qt.PenStyle.DashLine)
                else:
                    pen = QPen(QColor(160, 160, 160, 170), 1.2, Qt.PenStyle.DotLine)
            if block.id in selected_ids:
                pen = QPen(QColor(255, 214, 64), 2.2)
            item = QGraphicsRectItem(QRectF(x1, y1, x2 - x1, y2 - y1))
            item.setPen(pen)
            item.setBrush(QBrush(colour))
            item.setToolTip(f"#{block.id} {block.role}\n{block.text[:60]}")
            item.setData(0, block.id)
            self.scene().addItem(item)
            self._overlay_items[block.id] = item
            if len(self._selected) == 1 and block.id == self._selected_id:
                item.setTransformOriginPoint((x1 + x2) / 2, (y1 + y2) / 2)
                item.setRotation(self._rotations.get(block.id, 0.0))
                self._build_handles(
                    (x1, y1, x2, y2), self._rotations.get(block.id, 0.0)
                )

    def set_overlay_opacity(self, value: int) -> None:
        """Set block overlay opacity, 0-100 (100 = fully visible)."""
        self._overlay_opacity = max(0.0, min(1.0, value / 100.0))
        if self._pixmap_item is None:
            return
        self.set_blocks(getattr(self, "_last_blocks", []), getattr(self, "_last_selected", ()))

    def rotate_view(self) -> None:
        """Rotate the view 90 degrees clockwise (the file is untouched)."""
        self.rotate(90)

    def fit(self) -> None:
        """Fit the page into the viewport."""
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    # -- interaction ------------------------------------------------------
    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt name
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier or True:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt name
        position = self.mapToScene(event.position().toPoint())
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            event.accept()
            return
        if self._mode == "brush" and event.button() in {
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        }:
            if not self.sceneRect().contains(position):
                event.accept()
                return
            self._brush_erase = event.button() == Qt.MouseButton.LeftButton
            self._brush_points = [position]
            self._update_brush_preview()
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._mode in {"lasso", "rect"}
            and self._region_enabled
        ):
            self._points = [position]
            self._update_preview()
            event.accept()
            return
        if self._mode == "select" and event.button() == Qt.MouseButton.RightButton:
            self._start_rubber(position, "subtract")
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if isinstance(item, QGraphicsRectItem) and item.data(1) == "rot":
                box = self._rect_of(int(item.data(2)))
                self._drag = {
                    "mode": "rotate",
                    "handle": "rot",
                    "block": int(item.data(2)),
                    "start": position,
                    "bbox": box,
                    "center": ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
                    "base": self._rotations.get(int(item.data(2)), 0.0),
                }
                event.accept()
                return
            if isinstance(item, QGraphicsRectItem) and item.data(1) is not None:
                self._drag = {
                    "mode": "resize",
                    "handle": str(item.data(1)),
                    "block": int(item.data(2)),
                    "start": position,
                    "bbox": self._rect_of(int(item.data(2))),
                }
                event.accept()
                return
            if (
                self._overlay_mode != "diff"
                and isinstance(item, QGraphicsRectItem)
                and item.data(0) is not None
            ):
                block_id = int(item.data(0))
                self.blockClicked.emit(block_id)
                self._drag = {
                    "mode": "move",
                    "handle": "",
                    "block": block_id,
                    "start": position,
                    "bbox": self._rect_of(block_id),
                }
                event.accept()
                return
            if self._mode == "select" and self._overlay_mode in {"blocks", "text"}:
                self._start_rubber(position, "add")
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt name
        position = self.mapToScene(event.position().toPoint())
        self.cursorMoved.emit(int(position.x()), int(position.y()))
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            return
        if self._mode == "brush":
            self._update_brush_cursor(position)
            if self._brush_points and self.sceneRect().contains(position):
                self._brush_points.append(position)
                self._update_brush_preview()
            event.accept()
            return
        if self._rubber is not None:
            self._update_rubber(position)
            return
        if self._drag is not None:
            start = self._drag["start"]
            dx, dy = int(position.x() - start.x()), int(position.y() - start.y())
            bbox = self._drag["bbox"]
            if self._drag["mode"] == "rotate":
                cx, cy = self._drag["center"]
                import math

                start = self._drag["start"]
                start_angle = math.degrees(math.atan2(start.y() - cy, start.x() - cx))
                now_angle = math.degrees(math.atan2(position.y() - cy, position.x() - cx))
                degrees = self._drag["base"] + (now_angle - start_angle)
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    degrees = round(degrees / 15) * 15
                self._rotations[int(self._drag["block"])] = degrees
                item = self._overlay_items.get(int(self._drag["block"]))
                if item is not None:
                    item.setTransformOriginPoint(cx, cy)
                    item.setRotation(degrees)
                return
            if self._drag["mode"] == "move":
                new_bbox = move_bbox(bbox, dx, dy, *self._page_size())
            else:
                new_bbox = resize_bbox(bbox, self._drag["handle"], dx, dy)
                width, height = self._page_size()
                new_bbox = (
                    max(0, new_bbox[0]),
                    max(0, new_bbox[1]),
                    min(width, new_bbox[2]),
                    min(height, new_bbox[3]),
                )
            self._show_bbox(self._drag["block"], new_bbox)
            return
        if self._mode in {"lasso", "rect"} and self._points:
            if self._mode == "rect":
                self._points = [self._points[0], position]
            else:
                self._points.append(position)
            self._update_preview()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self._mode == "brush":
            if self._brush_points:
                points = [(point.x(), point.y()) for point in self._brush_points]
                erase = self._brush_erase
                self._brush_points = []
                self._clear_brush_preview()
                self.brushFinished.emit(points, self._brush_radius, erase)
            event.accept()
            return
        if self._rubber is not None:
            self._finish_rubber(event)
            return
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            return
        if self._drag is not None:
            if self._drag.get("mode") == "rotate":
                degrees = self._rotations.get(int(self._drag["block"]), 0.0)
                self.blockRotated.emit(int(self._drag["block"]), degrees)
                self._drag = None
                return
            item = self._overlay_items.get(int(self._drag["block"]))
            if item is not None:
                rect = item.rect()
                self.blockGeometryChanged.emit(
                    int(self._drag["block"]),
                    (int(rect.x()), int(rect.y()), int(rect.right()), int(rect.bottom())),
                )
            self._drag = None
            return
        if self._mode in {"lasso", "rect"} and self._points:
            points = [(point.x(), point.y()) for point in self._points]
            self._clear_preview()
            if self._mode == "rect":
                x1, y1, x2, y2 = (
                    min(p[0] for p in points),
                    min(p[1] for p in points),
                    max(p[0] for p in points),
                    max(p[1] for p in points),
                )
                if x2 - x1 > 4 and y2 - y1 > 4:
                    self._show_selection([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
                    self.rectFinished.emit((int(x1), int(y1), int(x2), int(y2)))
            elif len(points) >= 3:
                self._show_selection(points)
                self.lassoFinished.emit(points)
            self._points = []
            return
        super().mouseReleaseEvent(event)

    # -- rubber-band multi select ----------------------------------------
    def _start_rubber(self, position: QPointF, mode: str) -> None:
        self._rubber = {"start": position, "mode": mode}
        self._rubber_moved = False
        self._overlay_mode = "blocks"
        self._region_enabled = True
        self._rotations: dict[int, float] = {}
        self._diff_item: QGraphicsPixmapItem | None = None
        self._clear_rubber_item()

    def _update_rubber(self, position: QPointF) -> None:
        if self._rubber is None:
            return
        start = self._rubber["start"]
        rect = QRectF(start, position).normalized()
        self._rubber_moved = rect.width() > 3 or rect.height() > 3
        self._clear_rubber_item()
        item = QGraphicsRectItem(rect)
        pen = QPen(QColor(120, 220, 255), 1.6, Qt.PenStyle.DashLine)
        if self._rubber["mode"] == "subtract":
            pen = QPen(QColor(255, 160, 120), 1.6, Qt.PenStyle.DashLine)
        item.setPen(pen)
        item.setBrush(QBrush(QColor(120, 220, 255, 18)))
        item.setZValue(11)
        self.scene().addItem(item)
        self._rubber_item = item

    def _finish_rubber(self, event) -> None:
        rubber = self._rubber or {}
        start = rubber.get("start", QPointF())
        moved = self._rubber_moved
        mode = rubber.get("mode", "add")
        rectangle = QRectF(start, self.mapToScene(event.position().toPoint())).normalized()
        self._rubber = None
        self._clear_rubber_item()
        if not moved:
            if event.button() == Qt.MouseButton.RightButton:
                self.contextMenuRequested.emit(event.globalPosition().toPoint())
            return
        box = (
            int(rectangle.x()),
            int(rectangle.y()),
            int(rectangle.right()),
            int(rectangle.bottom()),
        )
        hits = [
            block_id
            for block_id, item in self._overlay_items.items()
            if bbox_intersects(self._rect_of(block_id), box)
        ]
        if mode == "subtract":
            selected = [block_id for block_id in self._selected if block_id not in hits]
        else:
            selected = list(dict.fromkeys([*self._selected, *hits]))
        self.select_ids(selected)

    def _clear_rubber_item(self) -> None:
        if self._rubber_item is not None:
            self._remove_item(self._rubber_item)
            self._rubber_item = None

    def select_ids(self, ids: list[int]) -> None:
        """Highlight the given blocks and notify the window."""
        self._selected = list(dict.fromkeys(ids))
        self.selectionIdsChanged.emit(list(self._selected))

    # -- preview ----------------------------------------------------------
    def _update_preview(self) -> None:
        self._clear_preview()
        if len(self._points) < 2:
            return
        polygon = QPolygonF(self._points)
        item = QGraphicsPolygonItem(polygon)
        item.setPen(QPen(QColor(120, 220, 255), 2, Qt.PenStyle.DashLine))
        item.setBrush(QBrush(QColor(120, 220, 255, 40)))
        self.scene().addItem(item)
        self._preview = item

    def _page_size(self) -> tuple[int, int]:
        rect = self.scene().sceneRect()
        return int(rect.width()), int(rect.height())

    def _rect_of(self, block_id: int) -> tuple[int, int, int, int]:
        item = self._overlay_items.get(block_id)
        if item is None:
            return (0, 0, 8, 8)
        rect = item.rect()
        return (int(rect.x()), int(rect.y()), int(rect.right()), int(rect.bottom()))

    def _show_bbox(self, block_id: int, bbox: tuple[int, int, int, int]) -> None:
        item = self._overlay_items.get(block_id)
        if item is None:
            return
        x1, y1, x2, y2 = bbox
        item.setRect(QRectF(x1, y1, x2 - x1, y2 - y1))
        self._build_handles(bbox)

    def _show_selection(self, points: list[tuple[float, float]]) -> None:
        """Keep the lasso/rectangle visible until the action finishes."""
        self._clear_selection()
        self._selection_points = list(points)
        polygon = QPolygonF([QPointF(x, y) for x, y in points])
        item = QGraphicsPolygonItem(polygon)
        item.setPen(QPen(QColor(120, 220, 255), 2, Qt.PenStyle.DashLine))
        item.setBrush(QBrush(QColor(120, 220, 255, 30)))
        item.setZValue(9)
        self.scene().addItem(item)
        self._selection = item
        self.selectionChanged.emit(True)

    def clear_selection(self) -> None:
        """Drop the current region selection."""
        self._clear_selection()
        self.selectionChanged.emit(False)

    def _clear_selection(self) -> None:
        self._selection_points = []
        if self._selection is not None:
            self._remove_item(self._selection)
            self._selection = None

    @property
    def selection_points(self) -> list[tuple[float, float]]:
        return list(self._selection_points)

    def selection_bbox(self) -> tuple[int, int, int, int] | None:
        if not self._selection_points:
            return None
        xs = [point[0] for point in self._selection_points]
        ys = [point[1] for point in self._selection_points]
        return (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if event.key() == Qt.Key.Key_B:
            self.brushRequested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._selection is not None:
            self.clear_selection()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt name
        self.fit()
        event.accept()

    def _remove_item(self, item) -> None:
        """Remove a scene item, tolerating wrappers whose C++ object is gone."""
        try:
            scene = item.scene()
        except RuntimeError:
            return
        if scene is not None:
            scene.removeItem(item)

    def _clear_handles(self) -> None:
        for item in self._handle_items.values():
            self._remove_item(item)
        self._handle_items.clear()

    def _build_handles(
        self, bbox: tuple[int, int, int, int], rotation: float = 0.0
    ) -> None:
        self._clear_handles()
        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        positions = {
            "nw": (x1, y1),
            "n": (cx, y1),
            "ne": (x2, y1),
            "e": (x2, cy),
            "se": (x2, y2),
            "s": (cx, y2),
            "sw": (x1, y2),
            "w": (x1, cy),
        }
        size = 9
        handle = QGraphicsRectItem(cx - size / 2, y1 - 30 - size / 2, size, size)
        handle.setBrush(QBrush(QColor(120, 220, 255)))
        handle.setPen(QPen(QColor(40, 40, 40), 1))
        handle.setData(1, "rot")
        handle.setData(2, self._selected_id)
        handle.setZValue(10)
        self.scene().addItem(handle)
        self._handle_items["rot"] = handle
        for name, (px, py) in positions.items():
            handle = QGraphicsRectItem(px - size / 2, py - size / 2, size, size)
            handle.setBrush(QBrush(QColor(255, 255, 255)))
            handle.setPen(QPen(QColor(40, 40, 40), 1))
            handle.setData(1, name)
            handle.setData(2, self._selected_id)
            handle.setZValue(10)
            self.scene().addItem(handle)
            self._handle_items[name] = handle

    def _clear_preview(self) -> None:
        if self._preview is not None:
            self._remove_item(self._preview)
            self._preview = None
