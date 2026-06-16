"""Custom image-skin editor: the crop dialog the user drives to turn an uploaded image into a
memo background, plus the small pure helpers (export the crop, load a skin pixmap, measure its
brightness for text contrast). Leaf-ish UI module — reaches the app only through `self.app` and
imports nothing from app.py/the D3D engine."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon, LineEdit, PrimaryPushButton, PushButton, TitleLabel

from ui_common import (
    FONT_STACK_QSS,
    SETTING_ROW_TITLE_FONT_PX,
    SETTING_STATUS_FONT_PX,
    add_soft_shadow,
    enlarge_control_font,
    relative_luminance,
    set_label_font,
)

# Longest edge of a saved background PNG. The crop is downscaled to this so a 24MP phone photo
# does not become a multi-megabyte skin file; the memo window is small enough that this is plenty.
MAX_SKIN_EDGE = 1920

_IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.bmp *.webp)"


def image_open_filter() -> str:
    return _IMAGE_FILTER


def load_skin_pixmap(path: Path | str) -> QPixmap | None:
    """Load a saved skin image; return None if missing/unreadable so callers can fall back."""
    pixmap = QPixmap(str(path))
    return None if pixmap.isNull() else pixmap


def mean_luminance(pixmap: QPixmap) -> float:
    """Average relative luminance (0..1) of the image, sampled on a tiny downscale. Drives the
    deterministic dark/light text choice in image-skin mode (capture-based auto-contrast is off)."""
    if pixmap.isNull():
        return 1.0
    image = pixmap.toImage().scaled(16, 16, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    if image.isNull():
        return 1.0
    total = 0.0
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            total += relative_luminance(image.pixelColor(x, y))
            count += 1
    return total / count if count else 1.0


class CropCanvas(QWidget):
    """Pan/zoom an image behind a fixed crop rectangle. The crop rect is centered and never
    moves; the user drags the image (pan) and scrolls (zoom) to choose what falls inside it.
    The image is constrained to always cover the crop rect, so the exported region is never
    blank. All math is in canvas (widget) coordinates; export_region maps back to source pixels."""

    def __init__(self, source: QPixmap, aspect: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._src = source
        self.setFixedSize(720, 430)
        self.setCursor(Qt.OpenHandCursor)
        # Centered crop rect with the requested aspect (the memo window's), fit inside the canvas
        # with a margin so the dimmed border is visible.
        avail_w = self.width() * 0.84
        avail_h = self.height() * 0.84
        if avail_w / avail_h > aspect:
            crop_h = avail_h
            crop_w = crop_h * aspect
        else:
            crop_w = avail_w
            crop_h = crop_w / aspect
        cx = (self.width() - crop_w) / 2
        cy = (self.height() - crop_h) / 2
        self._crop = QRect(round(cx), round(cy), round(crop_w), round(crop_h))

        self._min_scale = max(self._crop.width() / max(1, self._src.width()),
                              self._crop.height() / max(1, self._src.height()))
        self._scale = self._min_scale
        # Center the image over the crop rect initially.
        self._offset = QPointF(
            self._crop.center().x() - self._src.width() * self._scale / 2,
            self._crop.center().y() - self._src.height() * self._scale / 2,
        )
        self._clamp_offset()
        self._drag_anchor: QPoint | None = None

    # --- geometry helpers ---------------------------------------------------
    def _img_size(self) -> tuple[float, float]:
        return self._src.width() * self._scale, self._src.height() * self._scale

    def _clamp_offset(self) -> None:
        img_w, img_h = self._img_size()
        # offset.x in [crop.right - img_w, crop.left]; image must span the crop rect.
        min_x = self._crop.right() - img_w
        min_y = self._crop.bottom() - img_h
        x = min(self._crop.left(), max(min_x, self._offset.x()))
        y = min(self._crop.top(), max(min_y, self._offset.y()))
        self._offset = QPointF(x, y)

    # --- interaction --------------------------------------------------------
    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        factor = 1.12 ** steps
        new_scale = max(self._min_scale, min(self._min_scale * 12.0, self._scale * factor))
        if new_scale == self._scale:
            event.accept()
            return
        # Zoom about the cursor: keep the source point under the cursor fixed.
        cursor = event.position()
        src_x = (cursor.x() - self._offset.x()) / self._scale
        src_y = (cursor.y() - self._offset.y()) / self._scale
        self._scale = new_scale
        self._offset = QPointF(cursor.x() - src_x * new_scale, cursor.y() - src_y * new_scale)
        self._clamp_offset()
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_anchor = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()  # keep the press from bubbling to FramelessDragMixin (would move dialog)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_anchor is not None and (event.buttons() & Qt.LeftButton):
            pos = event.position().toPoint()
            delta = pos - self._drag_anchor
            self._drag_anchor = pos
            self._offset = QPointF(self._offset.x() + delta.x(), self._offset.y() + delta.y())
            self._clamp_offset()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_anchor is not None:
            self._drag_anchor = None
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # --- painting -----------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        canvas = self.rect()
        # Checkerboard-free dark backdrop behind the image.
        path = QPainterPath()
        path.addRoundedRect(QRectF(canvas), 14, 14)
        painter.setClipPath(path)
        painter.fillRect(canvas, QColor(28, 32, 38))

        img_w, img_h = self._img_size()
        target = QRectF(self._offset.x(), self._offset.y(), img_w, img_h)
        painter.drawPixmap(target, self._src, QRectF(self._src.rect()))

        # Dim everything outside the crop rect so the framed region pops.
        painter.save()
        painter.setClipRegion(QRegion(canvas).subtracted(QRegion(self._crop)), Qt.IntersectClip)
        painter.fillRect(canvas, QColor(0, 0, 0, 120))
        painter.restore()

        # Unfilled crop border + rule-of-thirds guides.
        painter.setClipping(False)
        pen = QPen(QColor(255, 255, 255, 235), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self._crop)
        guide = QPen(QColor(255, 255, 255, 70), 1)
        painter.setPen(guide)
        for i in (1, 2):
            gx = self._crop.left() + self._crop.width() * i / 3
            gy = self._crop.top() + self._crop.height() * i / 3
            painter.drawLine(int(gx), self._crop.top(), int(gx), self._crop.bottom())
            painter.drawLine(self._crop.left(), int(gy), self._crop.right(), int(gy))
        painter.end()

    # --- export -------------------------------------------------------------
    def export_region(self) -> QPixmap:
        """Render the cropped region to a (downscaled) pixmap at source resolution."""
        sx = (self._crop.left() - self._offset.x()) / self._scale
        sy = (self._crop.top() - self._offset.y()) / self._scale
        sw = self._crop.width() / self._scale
        sh = self._crop.height() / self._scale
        src_rect = QRect(round(sx), round(sy), max(1, round(sw)), max(1, round(sh)))
        src_rect = src_rect.intersected(self._src.rect())
        cropped = self._src.copy(src_rect)
        longest = max(cropped.width(), cropped.height())
        if longest > MAX_SKIN_EDGE:
            if cropped.width() >= cropped.height():
                cropped = cropped.scaledToWidth(MAX_SKIN_EDGE, Qt.SmoothTransformation)
            else:
                cropped = cropped.scaledToHeight(MAX_SKIN_EDGE, Qt.SmoothTransformation)
        return cropped


def export_crop(canvas: CropCanvas, dst_path: Path) -> bool:
    """Save the canvas's cropped region as a PNG. Returns True on success."""
    pixmap = canvas.export_region()
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    return bool(pixmap.save(str(dst_path), "PNG"))


class CropDialog(QDialog):
    """Modal fluent card that frames the crop canvas, a name field and save/cancel buttons.
    Follows the _ReleaseCardDialog / HistoryWindow visual idiom. Show via exec(); on Accepted
    the caller reads `.canvas` (to export_crop) and `.skin_name`."""

    def __init__(self, source: QPixmap, aspect: float, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        width, height = 800, 678
        self.setFixedSize(width, height)

        self.frame = QFrame(self)
        self.frame.setObjectName("fluentPanel")
        self.frame.setGeometry(0, 0, width, height)
        self.frame.setStyleSheet(
            f"""
            QFrame#fluentPanel {{
                {FONT_STACK_QSS}
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgb(252, 253, 255), stop:1 rgb(240, 244, 250));
                border: 1px solid rgba(255,255,255,210);
                border-radius: 22px;
            }}
            """
        )
        add_soft_shadow(self.frame, blur=34, y=12, alpha=80)

        body = QVBoxLayout(self.frame)
        body.setContentsMargins(30, 26, 30, 26)
        body.setSpacing(12)

        title = TitleLabel("裁切背景图")
        set_label_font(title, SETTING_ROW_TITLE_FONT_PX + 3)
        subtitle = BodyLabel("拖动图片调整位置，滚动鼠标滚轮缩放；白色矩形内为最终背景区域。")
        subtitle.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,150); font-size: {SETTING_STATUS_FONT_PX}px;")
        body.addWidget(title)
        body.addWidget(subtitle)

        self.canvas = CropCanvas(source, aspect, self.frame)
        canvas_row = QHBoxLayout()
        canvas_row.setContentsMargins(0, 8, 0, 8)
        canvas_row.addStretch()
        canvas_row.addWidget(self.canvas)
        canvas_row.addStretch()
        body.addLayout(canvas_row)
        # Collect any leftover height here so the name field / buttons always sit clear below the
        # fixed-size canvas instead of overlapping it.
        body.addStretch(1)

        name_row = QHBoxLayout()
        name_row.setSpacing(12)
        name_label = BodyLabel("皮肤名称")
        set_label_font(name_label, SETTING_ROW_TITLE_FONT_PX)
        self.name_input = LineEdit()
        self.name_input.setPlaceholderText("例如：海边日落")
        self.name_input.setClearButtonEnabled(True)
        self.name_input.setMaxLength(40)
        self.name_input.setFixedHeight(38)
        enlarge_control_font(self.name_input)
        self.name_input.returnPressed.connect(self._on_save)
        name_row.addWidget(name_label)
        name_row.addWidget(self.name_input, 1)
        body.addLayout(name_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.setContentsMargins(0, 6, 0, 0)
        buttons.addStretch()
        cancel = PushButton("取消")
        cancel.setMinimumWidth(108)
        cancel.setFixedHeight(40)
        enlarge_control_font(cancel)
        cancel.clicked.connect(self.reject)
        save = PrimaryPushButton("保存", self, FluentIcon.ACCEPT)
        save.setMinimumWidth(120)
        save.setFixedHeight(40)
        enlarge_control_font(save)
        save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        body.addLayout(buttons)

        self.skin_name = ""

    def _on_save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self.name_input.setFocus()
            return
        self.skin_name = name
        self.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            self.move(screen.center() - self.rect().center())
