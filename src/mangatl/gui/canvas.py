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
        self._mode = "select"
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
    def show_image(self, path) -> None:
        """Load the page image and reset the view."""
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return
        self.scene().clear()
        self._overlay_items.clear()
        self._pixmap_item = self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        self.fit()

    def set_blocks(self, blocks, selected_ids: Sequence[int] = ()) -> None:
        """Redraw block overlays."""
        for item in self._overlay_items.values():
            self.scene().removeItem(item)
        self._overlay_items.clear()
        for block in blocks:
            x1, y1, x2, y2 = block.bbox
            colour = ROLE_COLORS.get(block.role, QColor(200, 200, 200, 60))
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
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if isinstance(item, QGraphicsRectItem) and item.data(0) is not None:
                self.blockClicked.emit(int(item.data(0)))
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
        if self._mode in {"lasso", "rect"} and self._points:
            if self._mode == "rect":
                self._points = [self._points[0], position]
            else:
                self._points.append(position)
            self._update_preview()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt name
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
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
                    self.rectFinished.emit((int(x1), int(y1), int(x2), int(y2)))
            elif len(points) >= 3:
                self.lassoFinished.emit(points)
            self._points = []
            return
        super().mouseReleaseEvent(event)

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

    def _clear_preview(self) -> None:
        if self._preview is not None:
            self.scene().removeItem(self._preview)
            self._preview = None
