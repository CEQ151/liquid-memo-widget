from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

sys.dont_write_bytecode = True
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import QEasingCurve, QPoint, QRect, QTimer, Qt, QPropertyAnimation
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    ColorDialog,
    ComboBox,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    Slider,
    SmoothScrollArea,
    SubtitleLabel,
    SwitchButton,
    TitleLabel,
    setTheme,
    Theme,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from WindowsLiquidGlass.src.GPUSharderWidget.one_d3d_widget import (  # noqa: E402
    EFFECTS_PARAMS,
    EffectType,
    OneGPUWidget,
    set_window_exclude_from_capture,
)

from liquid_effects import build_effect_params
from startup import is_startup_enabled, set_startup
from state_store import AppState, Settings, StateStore, TodoItem, utc_now
from window_layer import (
    HTCAPTION,
    HTCLIENT,
    HTTRANSPARENT,
    WM_ENTERSIZEMOVE,
    WM_EXITSIZEMOVE,
    WM_NCHITTEST,
    apply_tool_window,
    begin_system_move,
    set_desktop_layer,
    set_topmost,
)


CJK_FONT = "Microsoft YaHei"
LATIN_FONT = "Times New Roman"
FONT_STACK_QSS = 'font-family: "Times New Roman", "Microsoft YaHei", "Segoe UI Emoji";'

MIN_WIDTH = 320
MAX_WIDTH = 720
MAX_WIDTH_RATIO = 0.52
MIN_HEIGHT = 320
MAX_HEIGHT_RATIO = 0.7
ROW_HEIGHT = 44
OUTER_X = 26


def qcolor(hex_value: str, fallback: str = "#111820") -> QColor:
    color = QColor(hex_value)
    return color if color.isValid() else QColor(fallback)


def mixed_font(point_size: int = 10, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont(LATIN_FONT, point_size, weight)
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


def add_soft_shadow(widget: QWidget, blur: int = 28, y: int = 10, alpha: int = 72) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y)
    shadow.setColor(QColor(20, 28, 36, alpha))
    widget.setGraphicsEffect(shadow)


def tray_icon() -> QIcon:
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


class RoundButton(QPushButton):
    def __init__(self, text: str, size: int = 34, parent: QWidget | None = None, tone: str = "neutral") -> None:
        super().__init__(text, parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        palette = {
            "neutral": ("rgba(255,255,255,88)", "rgba(255,255,255,132)", "rgba(255,255,255,175)", "#111820", "rgba(255,255,255,150)"),
            "add": ("rgba(33,150,243,196)", "rgba(33,150,243,225)", "rgba(18,121,218,235)", "white", "rgba(255,255,255,170)"),
            "hide": ("rgba(255,255,255,105)", "rgba(255,255,255,150)", "rgba(255,255,255,190)", "#30404C", "rgba(255,255,255,150)"),
            "confirm": ("rgba(45,184,130,205)", "rgba(45,184,130,235)", "rgba(24,146,101,242)", "white", "rgba(255,255,255,170)"),
        }
        bg, hover, pressed, color, border = palette.get(tone, palette["neutral"])
        radius = size // 2
        self.setStyleSheet(
            f"""
            QPushButton {{
                {FONT_STACK_QSS}
                border: 1px solid {border};
                border-radius: {radius}px;
                background: {bg};
                color: {color};
                font-size: 17px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:pressed {{ background: {pressed}; }}
            """
        )


class TodoTextLabel(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setToolTip(text)
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_full_text(self, text: str) -> None:
        self.setToolTip(text)
        self.setText(text)


class DragHandle(QLabel):
    def __init__(self, parent_window: "MemoWindow") -> None:
        super().__init__("⋮⋮", parent_window.content)
        self.parent_window = parent_window
        self.setFixedSize(38, 32)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.SizeAllCursor)
        self.setStyleSheet(
            f"""
            QLabel {{
                {FONT_STACK_QSS}
                color: rgba(17,24,32,185);
                font-size: 20px;
                border-radius: 16px;
                background: rgba(255,255,255,96);
            }}
            QLabel:hover {{ background: rgba(255,255,255,145); }}
            """
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.parent_window.begin_system_move()
            event.accept()
            return
        super().mousePressEvent(event)


class TodoRow(QFrame):
    def __init__(self, todo: TodoItem, settings: Settings, parent_window: "MemoWindow") -> None:
        super().__init__(parent_window.content)
        self.todo = todo
        self.parent_window = parent_window
        self.setMinimumHeight(ROW_HEIGHT)
        self.setObjectName("todoRow")
        self.setStyleSheet(
            f"""
            QFrame#todoRow {{
                {FONT_STACK_QSS}
                background: transparent;
                border-bottom: 1px solid rgba(255,255,255,72);
            }}
            QFrame#todoRow:hover {{ background: rgba(255,255,255,35); }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(10)

        self.checkbox = QCheckBox()
        self.checkbox.setCursor(Qt.PointingHandCursor)
        self.checkbox.setChecked(todo.done)
        self.checkbox.setStyleSheet(
            """
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 5px;
                border: 1px solid rgba(25,35,45,120);
                background: rgba(255,255,255,80);
            }
            QCheckBox::indicator:hover { background: rgba(255,255,255,140); }
            QCheckBox::indicator:checked {
                background: #111820;
                image: none;
            }
            """
        )
        self.checkbox.stateChanged.connect(self._complete_changed)
        layout.addWidget(self.checkbox)

        self.text = TodoTextLabel(todo.text)
        self.text.setFont(mixed_font(12))
        self.text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.apply_text_style(parent_window.text_color_for(todo), parent_window.text_needs_halo())
        layout.addWidget(self.text, 1)

        self.urgent = QPushButton("❗")
        self.urgent.setFixedSize(30, 30)
        self.urgent.setCursor(Qt.PointingHandCursor)
        self.urgent.setToolTip("加急并置顶")
        self.urgent.setStyleSheet(
            """
            QPushButton {
                border: none;
                border-radius: 15px;
                background: rgba(255,255,255,45);
                font-size: 15px;
            }
            QPushButton:hover { background: rgba(255,255,255,115); }
            QPushButton:pressed { background: rgba(255,255,255,160); }
            """
        )
        self.urgent.clicked.connect(lambda: parent_window.toggle_urgent(todo.id))
        layout.addWidget(self.urgent)

    def apply_text_style(self, color: QColor, protect: bool) -> None:
        alpha = 0.45 if self.todo.done else 1.0
        decoration = "text-decoration: line-through;" if self.todo.done else ""
        self.text.setStyleSheet(f"{FONT_STACK_QSS} font-size: 12pt; color: {css_rgba(color, alpha)}; {decoration}")
        if protect:
            halo = QGraphicsDropShadowEffect(self.text)
            halo.setBlurRadius(3.2)
            halo.setOffset(0, 0)
            if relative_luminance(color) > 0.55:
                halo.setColor(QColor(0, 0, 0, 118))
            else:
                halo.setColor(QColor(255, 255, 255, 138))
            self.text.setGraphicsEffect(halo)
        else:
            self.text.setGraphicsEffect(None)

    def apply_text_width(self, text_width: int) -> int:
        text_width = max(90, text_width)
        self.text.setFixedWidth(text_width)
        metrics = QFontMetrics(self.text.font())
        flags = Qt.TextWordWrap | Qt.TextWrapAnywhere
        rect = metrics.boundingRect(QRect(0, 0, text_width, 2000), flags, self.todo.text)
        height = max(ROW_HEIGHT, rect.height() + 18)
        self.setFixedHeight(height)
        return height

    def _complete_changed(self) -> None:
        self.parent_window.complete_todo(self.todo.id, self.checkbox.isChecked(), self)


class AddTodoPopup(QDialog):
    def __init__(self, parent_window: "MemoWindow") -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.parent_window = parent_window
        self.setWindowTitle("添加事项")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(420, 74)

        self.panel = QFrame(self)
        self.panel.setObjectName("addPanel")
        self.panel.setGeometry(0, 0, self.width(), self.height())
        self.panel.setStyleSheet(
            f"""
            QFrame#addPanel {{
                {FONT_STACK_QSS}
                border-radius: 22px;
                border: 1px solid rgba(255,255,255,170);
                background: rgba(248,252,255,238);
            }}
            QLineEdit {{
                {FONT_STACK_QSS}
                border: 1px solid rgba(255,255,255,145);
                border-radius: 17px;
                background: rgba(255,255,255,150);
                color: #111820;
                font-size: 15px;
                padding: 7px 12px;
                selection-background-color: rgba(33,150,243,120);
            }}
            """
        )
        add_soft_shadow(self.panel, blur=22, y=8, alpha=60)

        layout = QHBoxLayout(self.panel)
        layout.setContentsMargins(18, 12, 12, 12)
        layout.setSpacing(10)
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入事项")
        self.input.returnPressed.connect(self.accept)
        layout.addWidget(self.input, 1)
        self.ok = RoundButton("✓", 42, tone="confirm")
        self.ok.clicked.connect(self.accept)
        layout.addWidget(self.ok)

    def open_near(self, point: QPoint, width: int) -> None:
        width = max(380, min(560, width))
        self.setFixedSize(width, 74)
        self.panel.setGeometry(0, 0, self.width(), self.height())
        self.move(point)
        self.input.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, lambda: self.input.setFocus(Qt.PopupFocusReason))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def accept(self) -> None:
        text = self.input.text().strip()
        if text:
            self.parent_window.add_todo(text)
        self.hide()


class FluentSettingRow(CardWidget):
    def __init__(self, title: str, content: str, control: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(78)
        self.setObjectName("fluentSettingRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(18)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        title_label = BodyLabel(title)
        title_label.setFont(mixed_font(11, QFont.Bold))
        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,145); font-size: 12px;")

        text_layout.addWidget(title_label)
        text_layout.addWidget(content_label)
        layout.addLayout(text_layout, 1)
        layout.addWidget(control, 0, Qt.AlignVCenter)


class HistoryWindow(QDialog):
    def __init__(self, app: "LiquidMemoApp") -> None:
        super().__init__(None, Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.app = app
        self.setWindowTitle("历史记录")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(620, 620)
        self._build()

    def _build(self) -> None:
        self.frame = QFrame(self)
        self.frame.setObjectName("fluentPanel")
        self.frame.setGeometry(0, 0, self.width(), self.height())
        self.frame.setStyleSheet(
            f"""
            QFrame#fluentPanel {{
                {FONT_STACK_QSS}
                background: rgb(246, 248, 252);
                border: 1px solid rgba(255,255,255,185);
                border-radius: 22px;
            }}
            """
        )
        add_soft_shadow(self.frame, blur=34, y=12, alpha=80)

        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(18)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = TitleLabel("历史记录")
        subtitle = BodyLabel("已归档的待办事项可以随时恢复。")
        subtitle.setStyleSheet("color: rgba(17,24,32,150);")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)

        clear = PushButton("清空", self.frame, FluentIcon.DELETE)
        clear.clicked.connect(self._clear)
        header.addWidget(clear)
        close = PrimaryPushButton("完成", self.frame, FluentIcon.ACCEPT)
        close.clicked.connect(self.hide)
        header.addWidget(close)
        layout.addLayout(header)

        self.scroll = SmoothScrollArea(self.frame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.content = QWidget()
        self.content.setStyleSheet("background: transparent;")
        self.list = QVBoxLayout(self.content)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(10)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)
        self.refresh()

    def refresh(self) -> None:
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.app.state.history:
            empty = CardWidget()
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(22, 22, 22, 22)
            title = BodyLabel("暂无历史事项")
            title.setAlignment(Qt.AlignCenter)
            detail = QLabel("勾选完成并归档后的待办会显示在这里。")
            detail.setAlignment(Qt.AlignCenter)
            detail.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,135);")
            empty_layout.addWidget(title)
            empty_layout.addWidget(detail)
            self.list.addWidget(empty)
            self.list.addStretch()
            return

        for todo in reversed(self.app.state.history[-30:]):
            card = CardWidget()
            row_layout = QHBoxLayout(card)
            row_layout.setContentsMargins(18, 12, 14, 12)
            row_layout.setSpacing(14)

            text_layout = QVBoxLayout()
            text_layout.setSpacing(4)
            label = BodyLabel(todo.text)
            label.setWordWrap(True)
            meta = QLabel("已完成" if not todo.completedAt else f"完成于 {todo.completedAt[:10]}")
            meta.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,130); font-size: 12px;")
            text_layout.addWidget(label)
            text_layout.addWidget(meta)
            row_layout.addLayout(text_layout, 1)

            restore = PushButton("恢复", card, FluentIcon.RETURN)
            restore.clicked.connect(lambda _=False, todo_id=todo.id: self._restore(todo_id))
            row_layout.addWidget(restore)
            self.list.addWidget(card)
        self.list.addStretch()

    def _restore(self, todo_id: str) -> None:
        self.app.restore_from_history(todo_id)
        self.refresh()

    def _clear(self) -> None:
        self.app.state.history.clear()
        self.app.save()
        self.refresh()


class SettingsWindow(QDialog):
    def __init__(self, app: "LiquidMemoApp") -> None:
        super().__init__(None, Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.app = app
        self.setWindowTitle("设置")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(660, 720)
        self._build()

    def _build(self) -> None:
        self.frame = QFrame(self)
        self.frame.setObjectName("fluentPanel")
        self.frame.setGeometry(0, 0, self.width(), self.height())
        self.frame.setStyleSheet(
            f"""
            QFrame#fluentPanel {{
                {FONT_STACK_QSS}
                background: rgb(246, 248, 252);
                border: 1px solid rgba(255,255,255,185);
                border-radius: 22px;
            }}
            QFrame#colorSwatch {{
                border: 1px solid rgba(17,24,32,38);
                border-radius: 8px;
            }}
            """
        )
        add_soft_shadow(self.frame, blur=36, y=12, alpha=82)

        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(30, 26, 30, 28)
        layout.setSpacing(18)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = TitleLabel("设置")
        subtitle = BodyLabel("调整桌面备忘的玻璃、颜色、启动和窗口行为。")
        subtitle.setStyleSheet("color: rgba(17,24,32,150);")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        close = PrimaryPushButton("完成", self.frame, FluentIcon.ACCEPT)
        close.clicked.connect(self.hide)
        header.addWidget(close)
        layout.addLayout(header)

        self.scroll = SmoothScrollArea(self.frame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.content = QWidget()
        self.content.setStyleSheet("background: transparent;")
        self.form = QVBoxLayout(self.content)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(12)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

        self._section("外观")
        self.opacity, self.opacity_value = self._slider_row("透明光泽", "控制玻璃底色染色强度，越低越通透。", int(self.app.state.settings.glassOpacity * 100), 0, 38, "%")
        self.opacity.valueChanged.connect(lambda value: self._slider_changed(self.opacity_value, value, "%"))
        self.strength, self.strength_value = self._slider_row("液态强度", "调节边缘折射、色散和高光的存在感。", int(self.app.state.settings.liquidStrength * 100), 20, 140, "%")
        self.strength.valueChanged.connect(lambda value: self._slider_changed(self.strength_value, value, "%"))
        self.window_color = self._color_row("窗口颜色", "控制液态玻璃的低饱和背景染色。", self.app.state.settings.windowTint)
        self.text_color = self._color_row("待办字体颜色", "选择后自动切到手动颜色，并立即应用到普通待办。", self.app.state.settings.todoTextColor, True)
        self.urgent_color = self._color_row("加急字体颜色", "选择后自动切到手动颜色，并立即应用到加急待办。", self.app.state.settings.urgentTextColor, True)
        self.font_mode = self._combo_row(
            "字体颜色模式",
            "自动模式会根据桌面背景选择深色或浅色文字；增强模式会加极轻柔光保护阅读性。",
            {"自动颜色 + 高对比增强": "autoEnhanced", "自动颜色": "auto", "手动颜色": "manual"},
            self.app.state.settings.fontColorMode,
        )
        self.font_mode.currentIndexChanged.connect(self._apply)

        self._section("行为")
        self.complete = self._combo_row("勾选完成之后", "选择完成事项是直接归档，还是留在列表中淡化显示。", {"自动归档消失": "archive", "加分割线并淡化": "dim"}, self.app.state.settings.completeBehavior)
        self.complete.currentIndexChanged.connect(self._apply)
        self.layer = self._combo_row("窗口层级", "选择小组件贴近桌面，或始终悬浮但不阻挡鼠标。", {"始终可见且不挡鼠标": "alwaysVisibleClickThrough", "桌面同层": "desktopLayer"}, self.app.state.settings.layerMode)
        self.layer.currentIndexChanged.connect(self._apply)
        self.position = self._combo_row("默认启动位置", "应用启动时窗口出现的位置。", {"右上角": "topRight", "右下角": "bottomRight", "左上角": "topLeft", "左下角": "bottomLeft", "上次位置": "last", "使用当前位置": "current"}, self.app.state.window.startPosition)
        self.position.currentIndexChanged.connect(self._apply)
        self.startup = self._switch_row("开机自启动", "登录 Windows 后自动启动桌面备忘。", is_startup_enabled())
        self.startup.checkedChanged.connect(lambda _checked: self._apply())

        self.form.addStretch()

    def _section(self, title: str) -> None:
        label = SubtitleLabel(title)
        label.setContentsMargins(2, 8, 0, 0)
        self.form.addWidget(label)

    def _slider_row(self, title: str, content: str, value: int, minimum: int, maximum: int, suffix: str) -> tuple[Slider, BodyLabel]:
        control = QWidget()
        control.setFixedWidth(250)
        layout = QHBoxLayout(control)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        slider = Slider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setThemeColor("#0067C0", "#4CC2FF")
        value_label = BodyLabel(f"{value}{suffix}")
        value_label.setFixedWidth(48)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(slider, 1)
        layout.addWidget(value_label)
        self.form.addWidget(FluentSettingRow(title, content, control))
        return slider, value_label

    def _slider_changed(self, label: BodyLabel, value: int, suffix: str) -> None:
        label.setText(f"{value}{suffix}")
        self._apply()

    def _color_row(self, title: str, content: str, color: str, activates_manual_text_color: bool = False) -> QWidget:
        control = QWidget()
        control.setProperty("selectedColor", color)
        control.setProperty("activatesManualTextColor", activates_manual_text_color)
        control.setFixedWidth(220)
        layout = QHBoxLayout(control)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        swatch = QFrame()
        swatch.setObjectName("colorSwatch")
        swatch.setFixedSize(28, 28)
        button = PushButton(color, control, FluentIcon.PALETTE)
        button.setFixedWidth(170)
        button.clicked.connect(lambda: self._pick_color(control, swatch, button, title))
        layout.addWidget(swatch)
        layout.addWidget(button, 1)
        self._style_color_control(control, swatch, button, color)
        self.form.addWidget(FluentSettingRow(title, content, control))
        return control

    def _style_color_control(self, control: QWidget, swatch: QFrame, button: PushButton, color: str) -> None:
        control.setProperty("selectedColor", color)
        swatch.setStyleSheet(f"QFrame#colorSwatch {{ background: {color}; }}")
        button.setText(color)

    def _combo_row(self, title: str, content: str, options: dict[str, str], current: str) -> ComboBox:
        combo = ComboBox()
        combo.setFixedWidth(240)
        for text, data in options.items():
            combo.addItem(text, userData=data)
        index = combo.findData(current)
        combo.setCurrentIndex(max(0, index))
        self.form.addWidget(FluentSettingRow(title, content, combo))
        return combo

    def _switch_row(self, title: str, content: str, checked: bool) -> SwitchButton:
        switch = SwitchButton()
        switch.setChecked(checked)
        self.form.addWidget(FluentSettingRow(title, content, switch))
        return switch

    def _pick_color(self, control: QWidget, swatch: QFrame, button: PushButton, title: str) -> None:
        current = str(control.property("selectedColor") or "#F8FBFF")
        dialog = ColorDialog(QColor(current), title, self)
        dialog.colorChanged.connect(lambda color: self._color_selected(control, swatch, button, color.name()))
        dialog.exec()

    def _color_selected(self, control: QWidget, swatch: QFrame, button: PushButton, color: str) -> None:
        self._style_color_control(control, swatch, button, color)
        if bool(control.property("activatesManualTextColor")):
            self._set_font_color_mode("manual")
        self._apply()

    def _set_font_color_mode(self, mode: str) -> None:
        index = self.font_mode.findData(mode)
        if index < 0 or self.font_mode.currentIndex() == index:
            return
        previous = self.font_mode.blockSignals(True)
        self.font_mode.setCurrentIndex(index)
        self.font_mode.blockSignals(previous)

    def _control_color(self, control: QWidget, fallback: str) -> str:
        return str(control.property("selectedColor") or fallback)

    def _apply(self) -> None:
        settings = self.app.state.settings
        settings.glassOpacity = self.opacity.value() / 100
        settings.liquidStrength = self.strength.value() / 100
        settings.windowTint = self._control_color(self.window_color, settings.windowTint)
        settings.todoTextColor = self._control_color(self.text_color, settings.todoTextColor)
        settings.urgentTextColor = self._control_color(self.urgent_color, settings.urgentTextColor)
        settings.fontColorMode = str(self.font_mode.currentData())
        settings.completeBehavior = str(self.complete.currentData())
        settings.layerMode = str(self.layer.currentData())
        self.app.state.window.startPosition = str(self.position.currentData())
        settings.startWithWindows = self.startup.isChecked()
        set_startup(settings.startWithWindows)
        self.app.save()
        self.app.window.apply_settings()


class MemoWindow(OneGPUWidget):
    def __init__(self, app: "LiquidMemoApp") -> None:
        super().__init__(qt_move=False)
        self.app = app
        self.setWindowTitle("桌面备忘")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._rows: dict[str, TodoRow] = {}
        self._shown_once = False
        self._sampled_background = QColor(246, 248, 252)
        self._background_complexity = 0.0
        self._auto_text_color = qcolor(app.state.settings.todoTextColor)
        self._auto_urgent_color = qcolor(app.state.settings.urgentTextColor)
        self._is_window_moving = False
        self._contrast_was_active = False
        self._contrast_timer = QTimer(self)
        self._contrast_timer.setInterval(650)
        self._contrast_timer.timeout.connect(self.update_auto_contrast)
        self._build_content()

    @property
    def content(self) -> QWidget:
        return self.container or self

    def _build_content(self) -> None:
        root = self.content
        root.setStyleSheet("background: transparent;")
        self.layout = QVBoxLayout(root)
        self.layout.setContentsMargins(26, 18, 26, 18)
        self.layout.setSpacing(10)

        top = QHBoxLayout()
        self.drag_handle = DragHandle(self)
        top.addWidget(self.drag_handle)
        top.addStretch()
        self.add_button = RoundButton("+", tone="add")
        self.add_button.setToolTip("添加注意事项")
        self.add_button.clicked.connect(self.show_add_popup)
        top.addWidget(self.add_button)
        self.hide_button = RoundButton("–", tone="hide")
        self.hide_button.setToolTip("最小化")
        self.hide_button.clicked.connect(self.hide)
        top.addWidget(self.hide_button)
        self.layout.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollBar:vertical { width: 6px; background: transparent; } QScrollBar::handle:vertical { background: rgba(17,24,32,70); border-radius: 3px; }")
        self.list_widget = QWidget()
        self.list_widget.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 2, 0, 2)
        self.list_layout.setSpacing(0)
        self.scroll.setWidget(self.list_widget)
        self.layout.addWidget(self.scroll, 1)

        self.empty = QLabel("暂无待办")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: rgba(17,24,32,120); font-size: 15px;")
        self.layout.addWidget(self.empty, 1)

        self.add_popup = AddTodoPopup(self)

    def protect_content_layer(self) -> None:
        if self.container:
            self.container.raise_()
        set_window_exclude_from_capture(self, exclude=True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Keep our own text/control layer out of the GPU screen capture. Otherwise
        # the next liquid-glass frame captures and refracts the text itself.
        self.protect_content_layer()
        for delay in (0, 80, 180, 420):
            QTimer.singleShot(delay, self.protect_content_layer)
        if not self._shown_once:
            self._shown_once = True
            QTimer.singleShot(0, self.apply_initial_geometry)
        QTimer.singleShot(0, self.apply_settings)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self._shown_once:
            self.app.state.window.x = self.x()
            self.app.state.window.y = self.y()
            if self._is_window_moving:
                return
            QTimer.singleShot(0, self.protect_content_layer)
            self.app.save_later()
            QTimer.singleShot(120, self.update_auto_contrast)

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            import ctypes
            from ctypes import wintypes

            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_NCHITTEST:
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                local = self.mapFromGlobal(QPoint(x, y))
                if self._rect_for(self.drag_handle).contains(local):
                    return True, HTCAPTION
                if self._is_interactive_point(local):
                    return True, HTCLIENT
                if self.app.state.settings.layerMode in ("alwaysVisibleClickThrough", "desktopLayer"):
                    return True, HTTRANSPARENT
            if msg.message == WM_ENTERSIZEMOVE:
                self._begin_window_move()
            elif msg.message == WM_EXITSIZEMOVE:
                QTimer.singleShot(0, self._end_window_move)
        return super().nativeEvent(event_type, message)

    def _rect_for(self, widget: QWidget) -> QRect:
        top_left = widget.mapTo(self, QPoint(0, 0))
        return QRect(top_left, widget.size())

    def _is_interactive_point(self, point: QPoint) -> bool:
        widgets: list[QWidget] = [self.add_button, self.hide_button]
        for row in self._rows.values():
            widgets.extend([row.checkbox, row.urgent])
        return any(widget.isVisible() and self._rect_for(widget).adjusted(-4, -4, 4, 4).contains(point) for widget in widgets)

    def begin_system_move(self) -> None:
        self._begin_window_move()
        begin_system_move(int(self.winId()))
        QTimer.singleShot(0, self._end_window_move)

    def _begin_window_move(self) -> None:
        if self._is_window_moving:
            return
        self._is_window_moving = True
        self._contrast_was_active = self._contrast_timer.isActive()
        self._contrast_timer.stop()
        self.start(fps=30)

    def _end_window_move(self) -> None:
        if not self._is_window_moving:
            return
        self._is_window_moving = False
        self.app.state.window.x = self.x()
        self.app.state.window.y = self.y()
        self.app.save_later()
        self.protect_content_layer()
        self.start(fps=60)
        if self.app.state.settings.fontColorMode != "manual":
            self._contrast_timer.start()
            QTimer.singleShot(220, self.update_auto_contrast)

    def apply_initial_geometry(self) -> None:
        self.refresh()
        screen = QApplication.primaryScreen().availableGeometry()
        state = self.app.state.window
        if state.startPosition == "last" and state.x is not None and state.y is not None:
            self.move(state.x, state.y)
            return
        if state.startPosition == "current" and state.x is not None and state.y is not None:
            self.move(state.x, state.y)
            return
        x = screen.right() - self.width() - 32 if "Right" in state.startPosition else screen.left() + 32
        y = screen.bottom() - self.height() - 32 if "bottom" in state.startPosition else screen.top() + 32
        self.move(x, y)

    def apply_settings(self) -> None:
        settings = self.app.state.settings
        self.set_capture_source(display_index=0, tag="LiquidMemoWidget")
        self.enable_effects([
            EffectType.FLOW,
            EffectType.CHROMATIC_ABERRATION,
            EffectType.HIGHLIGHT,
            EffectType.ANTI_ALIASING,
            EffectType.COLOR_OVERLAY,
        ])
        self.update_effects(build_effect_params(EFFECTS_PARAMS, settings.windowTint, settings.glassOpacity, settings.liquidStrength))
        self.start(fps=60)
        self.refresh()
        self.protect_content_layer()
        hwnd = int(self.winId())
        apply_tool_window(hwnd)
        if settings.layerMode == "desktopLayer":
            if not set_desktop_layer(hwnd):
                set_topmost(hwnd, True)
        else:
            set_topmost(hwnd, True)
        QTimer.singleShot(120, self.protect_content_layer)
        if settings.fontColorMode == "manual":
            self._contrast_timer.stop()
            self.apply_text_colors()
        else:
            if not self._contrast_timer.isActive():
                self._contrast_timer.start()
            QTimer.singleShot(220, self.update_auto_contrast)

    def refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()

        active = sorted(self.app.state.todos, key=lambda item: (not item.urgent, item.order, item.createdAt))
        self.scroll.setVisible(bool(active))
        self.empty.setVisible(not active)

        for todo in active:
            row = TodoRow(todo, self.app.state.settings, self)
            self._rows[todo.id] = row
            self.list_layout.addWidget(row)
        self.list_layout.addStretch()
        self._resize_for_content(active)
        self.apply_text_colors()

    def text_color_for(self, todo: TodoItem) -> QColor:
        settings = self.app.state.settings
        if settings.fontColorMode == "manual":
            return qcolor(settings.urgentTextColor if todo.urgent else settings.todoTextColor)
        return QColor(self._auto_urgent_color if todo.urgent else self._auto_text_color)

    def text_needs_halo(self) -> bool:
        return self.app.state.settings.fontColorMode == "autoEnhanced"

    def apply_text_colors(self) -> None:
        for row in self._rows.values():
            row.apply_text_style(self.text_color_for(row.todo), self.text_needs_halo())
        if self.app.state.settings.fontColorMode == "manual":
            empty_color = qcolor(self.app.state.settings.todoTextColor)
        else:
            empty_color = QColor(self._auto_text_color)
        self.empty.setStyleSheet(f"{FONT_STACK_QSS} color: {css_rgba(empty_color, 0.58)}; font-size: 15px;")

    def update_auto_contrast(self) -> None:
        if not self.isVisible() or self.app.state.settings.fontColorMode == "manual":
            return
        sample = self._sample_background()
        if sample is None:
            return

        background, complexity = sample
        next_text = best_contrast_color(background, ["#05080C", "#111820", "#F7FAFF", "#FFFFFF"])
        next_urgent = best_contrast_color(background, ["#B3261E", "#D13438", "#F04438", "#FFB4AB", "#FFDAD6"])

        current_text_gain = contrast_ratio(self._auto_text_color, background)
        next_text_gain = contrast_ratio(next_text, background)
        current_urgent_gain = contrast_ratio(self._auto_urgent_color, background)
        next_urgent_gain = contrast_ratio(next_urgent, background)

        changed = False
        if next_text.name() != self._auto_text_color.name() and next_text_gain > current_text_gain + 0.45:
            self._auto_text_color = next_text
            changed = True
        if next_urgent.name() != self._auto_urgent_color.name() and next_urgent_gain > current_urgent_gain + 0.35:
            self._auto_urgent_color = next_urgent
            changed = True
        if abs(complexity - self._background_complexity) > 0.05:
            self._background_complexity = complexity
            changed = True
        self._sampled_background = background

        if changed:
            self.apply_text_colors()

    def _sample_background(self) -> tuple[QColor, float] | None:
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if not screen:
            return None
        try:
            pixmap = screen.grabWindow(0, self.x(), self.y(), max(24, self.width()), max(24, self.height()))
        except Exception:
            return None
        if pixmap.isNull():
            return None
        image = pixmap.scaled(28, 28, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).toImage()
        if image.isNull():
            return None

        total_r = total_g = total_b = 0
        luminances: list[float] = []
        count = image.width() * image.height()
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                total_r += color.red()
                total_g += color.green()
                total_b += color.blue()
                luminances.append(relative_luminance(color))
        if count <= 0:
            return None

        average = QColor(total_r // count, total_g // count, total_b // count)
        mean = sum(luminances) / len(luminances)
        variance = sum((value - mean) ** 2 for value in luminances) / len(luminances)
        complexity = min(1.0, variance ** 0.5 * 3.2)
        return average, complexity

    def _resize_for_content(self, active: list[TodoItem]) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        width = self._adaptive_width(active, screen)
        text_width = self._text_width_for_window(width)
        row_heights = [self._row_height_for(todo, text_width) for todo in active]
        content_height = sum(row_heights) if row_heights else ROW_HEIGHT
        wanted = max(MIN_HEIGHT, 104 + content_height)
        height = min(wanted, int(screen.height() * MAX_HEIGHT_RATIO), screen.height() - 64)

        if self.width() != width or self.height() != height:
            self.update_sdf(width, height, radius_ratio=0.24, scale=0.94)
            if self.container:
                self.container.setFixedSize(width, height)

        for row in self._rows.values():
            row.apply_text_width(text_width)

        self._keep_inside_screen(screen)
        self.app.state.window.width = width
        self.app.state.window.height = height

    def _adaptive_width(self, active: list[TodoItem], screen: QRect) -> int:
        if not active:
            return MIN_WIDTH
        metrics = QFontMetrics(mixed_font(12))
        longest = max(metrics.horizontalAdvance(todo.text) for todo in active)
        chrome = OUTER_X * 2 + 12 + 18 + 30 + 28 + 24
        max_width = min(MAX_WIDTH, int(screen.width() * MAX_WIDTH_RATIO), screen.width() - 64)
        return max(MIN_WIDTH, min(max_width, longest + chrome))

    def _text_width_for_window(self, width: int) -> int:
        return max(90, width - (OUTER_X * 2 + 12 + 18 + 30 + 28 + 12))

    def _row_height_for(self, todo: TodoItem, text_width: int) -> int:
        metrics = QFontMetrics(mixed_font(12))
        flags = Qt.TextWordWrap | Qt.TextWrapAnywhere
        rect = metrics.boundingRect(QRect(0, 0, max(90, text_width), 2000), flags, todo.text)
        return max(ROW_HEIGHT, rect.height() + 18)

    def _keep_inside_screen(self, screen: QRect) -> None:
        if not self.isVisible():
            return
        margin = 12
        x = min(max(self.x(), screen.left() + margin), screen.right() - self.width() - margin)
        y = min(max(self.y(), screen.top() + margin), screen.bottom() - self.height() - margin)
        if x != self.x() or y != self.y():
            self.move(x, y)

    def show_add_popup(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        popup_width = max(400, min(560, self.width() + 56))
        popup_height = 74
        x = self.x() + (self.width() - popup_width) // 2
        y = self.y() + self.height() + 10
        if y + popup_height > screen.bottom() - 12:
            y = self.y() - popup_height - 10
        x = min(max(x, screen.left() + 12), screen.right() - popup_width - 12)
        y = min(max(y, screen.top() + 12), screen.bottom() - popup_height - 12)
        self.add_popup.open_near(QPoint(x, y), popup_width)

    def add_todo(self, text: str) -> None:
        next_order = max([todo.order for todo in self.app.state.todos] + [0]) + 1
        self.app.state.todos.append(TodoItem(id=str(uuid4()), text=text, order=next_order))
        self.app.save()
        self.refresh()

    def toggle_urgent(self, todo_id: str) -> None:
        for todo in self.app.state.todos:
            if todo.id == todo_id:
                todo.urgent = not todo.urgent
                break
        self.app.save()
        self.refresh()

    def complete_todo(self, todo_id: str, checked: bool, row: TodoRow) -> None:
        todo = next((item for item in self.app.state.todos if item.id == todo_id), None)
        if not todo:
            return
        if not checked:
            todo.done = False
            todo.completedAt = None
            self.app.save()
            self.refresh()
            return
        if self.app.state.settings.completeBehavior == "dim":
            todo.done = True
            todo.completedAt = utc_now()
            self.app.save()
            self.refresh()
            return

        effect = QGraphicsOpacityEffect(row)
        row.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", row)
        anim.setDuration(180)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.finished.connect(lambda: self.app.archive_todo(todo_id))
        anim.start(QPropertyAnimation.DeleteWhenStopped)


class LiquidMemoApp:
    def __init__(self) -> None:
        self.qt = QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        setTheme(Theme.LIGHT)
        self.qt.setFont(mixed_font(10))
        self.qt.setStyleSheet(f"* {{ {FONT_STACK_QSS} }}")
        self.store = StateStore()
        self.state = self.store.load()
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save)
        self.window = MemoWindow(self)
        self.settings_window = SettingsWindow(self)
        self.history_window = HistoryWindow(self)
        self.tray_menu: RoundMenu | None = None
        self.tray = QSystemTrayIcon(tray_icon())
        self.tray.setToolTip("桌面备忘")
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.qt.aboutToQuit.connect(self.shutdown)

    def run(self) -> int:
        self.window.show()
        return self.qt.exec()

    def save_later(self) -> None:
        self.save_timer.start(350)

    def save(self) -> None:
        self.store.save(self.state)

    def archive_todo(self, todo_id: str) -> None:
        for index, todo in enumerate(self.state.todos):
            if todo.id == todo_id:
                todo.done = True
                todo.completedAt = utc_now()
                self.state.history.append(todo)
                self.state.todos.pop(index)
                break
        self.save()
        self.window.refresh()
        self.history_window.refresh()

    def restore_from_history(self, todo_id: str) -> None:
        for index, todo in enumerate(self.state.history):
            if todo.id == todo_id:
                todo.done = False
                todo.completedAt = None
                todo.order = max([item.order for item in self.state.todos] + [0]) + 1
                self.state.todos.append(todo)
                self.state.history.pop(index)
                break
        self.save()
        self.window.refresh()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.toggle_window()
        elif reason == QSystemTrayIcon.Context:
            self.show_tray_menu()

    def show_tray_menu(self) -> None:
        pos = QCursor.pos()
        menu = RoundMenu("桌面备忘", self.window)
        self._add_tray_action(menu, FluentIcon.SETTING, "设置", self.show_settings)
        self._add_tray_action(menu, FluentIcon.HISTORY, "历史记录", self.show_history)
        menu.addSeparator()
        label = "隐藏窗口" if self.window.isVisible() else "显示窗口"
        icon = FluentIcon.HIDE if self.window.isVisible() else FluentIcon.VIEW
        self._add_tray_action(menu, icon, label, self.toggle_window)
        self._add_tray_action(menu, FluentIcon.POWER_BUTTON, "退出", self.quit)
        self.tray_menu = menu
        menu.exec(QPoint(pos.x() - 210, pos.y() - 8))

    def _add_tray_action(self, menu: RoundMenu, icon: FluentIcon, text: str, callback) -> None:
        action = Action(icon, text, menu)
        action.triggered.connect(callback)
        menu.addAction(action)

    def toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.show()
            self.window.raise_()

    def show_settings(self) -> None:
        self._center_widget(self.settings_window)
        self.settings_window.show()
        self.settings_window.activateWindow()
        self.settings_window.raise_()

    def show_history(self) -> None:
        self.history_window.refresh()
        self._center_widget(self.history_window)
        self.history_window.show()
        self.history_window.activateWindow()
        self.history_window.raise_()

    def _center_widget(self, widget: QWidget) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.left() + (screen.width() - widget.width()) // 2
        y = screen.top() + (screen.height() - widget.height()) // 2
        widget.move(x, y)

    def quit(self) -> None:
        self.save()
        self.qt.quit()

    def shutdown(self) -> None:
        self.save()
        try:
            self.window.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    app = LiquidMemoApp()
    raise SystemExit(app.run())
