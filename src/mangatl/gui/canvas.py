"""Canvas: image, block overlays and the lasso/rectangle selection tools."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
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
        self._points: list[QPointF] = []
        self._panning = False
        self._pan_start = QPointF()

    # -- modes ------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """``select``, ``lasso`` or ``rect``."""
        self._mode = mode
        if mode == "select":
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

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
        if kept_points:
            self._show_selection(kept_points)
        self._pixmap_item = self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        if not preserve_view:
            self.fit()

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
        for block in blocks:
            x1, y1, x2, y2 = block.bbox
            colour = QColor(ROLE_COLORS.get(block.role, QColor(200, 200, 200, 60)))
            colour.setAlpha(int(colour.alpha() * self._overlay_opacity))
            pen = QPen(QColor(255, 255, 255, 220), 1.2)
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
                self._build_handles(block.bbox)

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
        if event.button() == Qt.MouseButton.LeftButton and self._mode in {"lasso", "rect"}:
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
            if isinstance(item, QGraphicsRectItem) and item.data(0) is not None:
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
            if self._mode == "select":
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
        if self._rubber is not None:
            self._update_rubber(position)
            return
        if self._drag is not None:
            start = self._drag["start"]
            dx, dy = int(position.x() - start.x()), int(position.y() - start.y())
            bbox = self._drag["bbox"]
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
        if self._rubber is not None:
            self._finish_rubber(event)
            return
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            return
        if self._drag is not None:
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

    def _build_handles(self, bbox: tuple[int, int, int, int]) -> None:
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
