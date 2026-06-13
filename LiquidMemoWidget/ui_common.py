"""Shared UI foundation: fonts, colors, geometry-free helpers and the small
widgets/mixins reused across the settings, update and memo surfaces. Leaf module
— it must not import the app, the windows or the D3D engine."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    ToolTipFilter,
    ToolTipPosition,
    TransparentToolButton,
    setCustomStyleSheet,
)

ROOT = Path(__file__).resolve().parents[1]


CJK_FONT = "Microsoft YaHei"
LATIN_FONT = "Times New Roman"
FONT_STACK_QSS = 'font-family: "Times New Roman", "Microsoft YaHei", "Segoe UI Emoji";'
def qcolor(hex_value: str, fallback: str = "#111820") -> QColor:
    color = QColor(hex_value)
    return color if color.isValid() else QColor(fallback)


def mixed_font(point_size: int = 10, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont(LATIN_FONT, point_size, weight)
    if hasattr(font, "setFamilies"):
        font.setFamilies([LATIN_FONT, CJK_FONT, "Segoe UI Emoji"])
    return font


def mixed_font_px(pixel_size: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont(LATIN_FONT, -1, weight)
    font.setPixelSize(pixel_size)
    if hasattr(font, "setFamilies"):
        font.setFamilies([LATIN_FONT, CJK_FONT, "Segoe UI Emoji"])
    return font


def qcolor_to_rgb(color: QColor) -> tuple[int, int, int]:
    return color.red(), color.green(), color.blue()


def css_rgba(color: QColor, alpha: float = 1.0) -> str:
    alpha = max(0.0, min(1.0, alpha))
    return f"rgba({color.red()},{color.green()},{color.blue()},{int(alpha * 255)})"


def relative_luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        return normalized / 12.92 if normalized <= 0.03928 else ((normalized + 0.055) / 1.055) ** 2.4

    red, green, blue = qcolor_to_rgb(color)
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast_ratio(foreground: QColor, background: QColor) -> float:
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter = max(first, second)
    darker = min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def best_contrast_color(background: QColor, candidates: list[str]) -> QColor:
    colors = [qcolor(candidate) for candidate in candidates]
    return max(colors, key=lambda color: contrast_ratio(color, background))


def blend_colors(base: QColor, overlay: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    inverse = 1.0 - amount
    return QColor(
        round(base.red() * inverse + overlay.red() * amount),
        round(base.green() * inverse + overlay.green() * amount),
        round(base.blue() * inverse + overlay.blue() * amount),
    )


def add_soft_shadow(widget: QWidget, blur: int = 28, y: int = 10, alpha: int = 72) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y)
    shadow.setColor(QColor(20, 28, 36, alpha))
    widget.setGraphicsEffect(shadow)


def tray_icon() -> QIcon:
    ico_path = ROOT / "assets" / "logo.ico"
    if ico_path.exists():
        icon = QIcon(str(ico_path))
        if not icon.isNull():
            return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(10, 8, 44, 48, 16, 16)
    painter.fillPath(path, QColor(248, 252, 255, 230))
    painter.setPen(QColor(255, 255, 255, 210))
    painter.drawPath(path)
    painter.setPen(QColor(28, 37, 45))
    painter.setFont(mixed_font(24, QFont.Bold))
    painter.drawText(QRect(10, 8, 44, 48), Qt.AlignCenter, "✓")
    painter.end()
    return QIcon(pixmap)
# Settings / dialog typography. Chinese renders in Microsoft YaHei, Latin in Times New Roman
# (a serif face — sizes are kept generous so it stays readable), and nothing is bold per the
# requested style; visual hierarchy comes from size alone.
SETTING_TITLE_FONT_PX = 22        # 主标题：设置 / 历史记录
SETTING_NAV_FONT_PX = 20          # 左侧分类：外观 / 行为 / 日历订阅 / 关于
SETTING_ROW_TITLE_FONT_PX = 19    # 设置项标题：皮肤 / 透明光泽 / 窗口颜色 …
SETTING_TIP_FONT_PX = 18          # 感叹号悬浮说明气泡
SETTING_CONTROL_FONT_PX = 17      # 下拉框 / 开关 / 按钮 / 颜色等控件
SETTING_STATUS_FONT_PX = 16       # 副标题 / 状态 / 说明性文字
POPUP_INPUT_FONT_PX = 19          # 添加备忘 / 编辑截止时间 弹窗输入框
def enlarge_control_font(widget: QWidget, px: int = SETTING_CONTROL_FONT_PX) -> None:
    # qfluentwidgets controls hardcode `font: 14px` in their own QSS, which beats setFont;
    # appending custom QSS via setCustomStyleSheet is the supported override path. The
    # selector must be the widget's class name — a universal `*` rule loses to the default
    # type selectors on specificity.
    name = type(widget).__name__
    font = f"font: {px}px 'Times New Roman','Microsoft YaHei','Segoe UI Emoji';"
    qss = f"{name} {{ {font} }} {name} * {{ {font} }} {name} QLabel {{ {font} }}"
    setCustomStyleSheet(widget, qss, qss)


def set_label_font(label: QWidget, px: int, weight: QFont.Weight = QFont.Normal) -> None:
    # Force a fluent label (TitleLabel/BodyLabel) to a specific pixel size and weight. These
    # labels carry their own bold QSS, so — like enlarge_control_font — the class-name custom
    # stylesheet is what actually wins; setFont keeps QFontMetrics (wrapping) in sync.
    label.setFont(mixed_font_px(px, weight))
    name = type(label).__name__
    bold = "bold " if weight >= QFont.DemiBold else ""
    qss = f"{name} {{ font: {bold}{px}px 'Times New Roman','Microsoft YaHei','Segoe UI Emoji'; }}"
    setCustomStyleSheet(label, qss, qss)
class InfoToolTipFilter(ToolTipFilter):
    """ToolTipFilter whose bubble text is larger than the 12px qfluentwidgets default."""

    def _createToolTip(self):
        tip = super()._createToolTip()
        tip.label.setStyleSheet(
            f"{FONT_STACK_QSS} font-size: {SETTING_TIP_FONT_PX}px; color: rgb(24, 32, 40);"
            " background: transparent; border: none;"
        )
        tip.label.adjustSize()
        tip.adjustSize()
        return tip


class FluentSettingRow(CardWidget):
    def __init__(self, title: str, content: str, control: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(74)
        self.setObjectName("fluentSettingRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(18)

        text_layout = QHBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        title_label = BodyLabel(title)
        set_label_font(title_label, SETTING_ROW_TITLE_FONT_PX)
        text_layout.addWidget(title_label)
        if content:
            info = TransparentToolButton(FluentIcon.INFO, self)
            info.setFixedSize(26, 26)
            info.setIconSize(QSize(16, 16))
            info.setCursor(Qt.WhatsThisCursor)
            info.setToolTip(content)
            info.installEventFilter(InfoToolTipFilter(info, showDelay=200, position=ToolTipPosition.TOP))
            text_layout.addWidget(info, 0, Qt.AlignVCenter)
        text_layout.addStretch()
        layout.addLayout(text_layout, 1)
        layout.addWidget(control, 0, Qt.AlignVCenter)
class FramelessDragMixin:
    """Click-drag a frameless dialog by any spot no child widget consumes (header, gaps).

    Non-interactive children (labels, frames) ignore mouse presses, so the press
    propagates up to the dialog; interactive controls keep working untouched.
    """

    _drag_offset: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
