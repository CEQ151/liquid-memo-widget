from __future__ import annotations

import ctypes
import math
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np

sys.dont_write_bytecode = True
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFontMetrics
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
    QMenu,
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
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    SmoothScrollArea,
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

from liquid_effects import build_effect_params, color_overlay_strength
from state_store import CalendarEvent, Settings, StateStore, TodoItem, parse_ddl, utc_now
from wheel_hook import GlobalWheelHook
from window_layer import (
    HTCAPTION,
    HTCLIENT,
    HTTRANSPARENT,
    WM_ENTERSIZEMOVE,
    WM_EXITSIZEMOVE,
    WM_NCHITTEST,
    apply_tool_window,
    begin_system_move,
    detach_from_parent,
    set_rounded_corners,
    set_topmost,
)
from qframelesswindow.windows.window_effect import WindowsWindowEffect
from ui_common import (
    FONT_STACK_QSS,
    POPUP_INPUT_FONT_PX,
    SETTING_STATUS_FONT_PX,
    SETTING_TITLE_FONT_PX,
    add_soft_shadow,
    best_contrast_color,
    blend_colors,
    contrast_ratio,
    css_rgba,
    mixed_font,
    qcolor,
    relative_luminance,
    set_label_font,
    tray_icon,
)
from settings_ui import SettingsWindow
from update_ui import UpdateManager
from calendar_manager import CalendarManager


MIN_WIDTH = 320
MAX_WIDTH = 720
MAX_WIDTH_RATIO = 0.52
MIN_HEIGHT = 320
MAX_HEIGHT_RATIO = 0.7
ROW_HEIGHT = 44
OUTER_X = 26
# DDL column: a fixed-width deadline column shown to the right of each todo's text,
# separated from it by a solid vertical line. Width is only reserved from the text
# column when at least one active todo actually carries a ddl.
# DDL column width is adaptive: sized to fit the widest deadline text in the current view so
# dates always show in full, clamped to [MIN, MAX] so a single long string can't blow up the
# window (anything past MAX still elides).
DDL_COL_MIN = 64
DDL_COL_MAX = 240
DDL_COL_EXPANDED_MAX = 600  # in expanded mode the time column may grow to avoid any elision
DDL_COL_PAD = 6
DDL_SEP_WIDTH = 1
# Two extra HBox gaps (text↔separator and separator↔ddl) at the layout's 10px spacing.
DDL_COL_GAPS = 20
# Deadline highlighting: a parsed DDL already past "now" turns red; one due within
# DDL_NEAR_WINDOW turns amber. Unparseable or done items follow the normal text color.
DDL_OVERDUE_COLOR = "#FF3B30"
DDL_NEAR_COLOR = "#FF9500"
DDL_NEAR_WINDOW = timedelta(hours=24)
# Placeholder shown in an empty (but visible) DDL cell, signalling it is click-to-set.
DDL_EMPTY_HINT = "＋"
# Calendar subscription ("日程" group).
CALENDAR_HEADER_HEIGHT = 30
_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


def format_event_time(event: "CalendarEvent") -> str:
    """Compact local time shown in the calendar event's time column."""
    deadline = parse_ddl(event.start)
    if deadline is None:
        return event.start
    weekday = _WEEKDAY_CN[deadline.weekday()]
    if event.allDay:
        return f"{deadline.strftime('%m-%d')} 周{weekday} 全天"
    return f"{deadline.strftime('%m-%d')} 周{weekday} {deadline.strftime('%H:%M')}"
BUSY_BACKGROUND_ENTER = 0.36
BUSY_BACKGROUND_EXIT = 0.26
HIGH_VISIBILITY_COLORS = ["#39FF14", "#C800FF", "#00F5FF", "#FFF200"]
_SAMPLE_DIM = 44
# The glass output is a static transform of the captured background, so the frame loop only
# exists to follow background changes — it does not need 60fps. Lower rates also leave room
# for the per-frame blank-frame validation readback.
REST_FPS = 20
MOVE_FPS = 30

# Edge auto-hide ("dock"): when the window is dragged within DOCK_THRESHOLD px of a work-area
# edge (left/right/top) it snaps flush and, once the cursor leaves, slides off-screen leaving a
# DOCK_PEEK-px strip. Moving the cursor back onto that strip slides it out again.
WM_MOUSEMOVE = 0x0200
DOCK_THRESHOLD = 18
DOCK_PEEK = 5
DOCK_HIDE_DELAY_MS = 600
DOCK_SLIDE_MS = 200
DOCK_POLL_MS = 120


def _dwm_flush() -> None:
    try:
        ctypes.windll.dwmapi.DwmFlush()
    except Exception:
        pass


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


class DDLCell(TodoTextLabel):
    """Deadline column label. Emits `clicked` so its row can open the DDL editor; the row also
    registers it with the native hit-test so the click lands here instead of passing through."""

    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setWordWrap(False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


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
        self._style_signature: tuple[str, bool, bool, str] | None = None
        self._halo: QGraphicsDropShadowEffect | None = None
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
        layout.addWidget(self.text, 1)

        # DDL column: solid vertical separator + deadline label. Both stay hidden until the
        # layout pass (apply_text_width) decides the column should be shown for this view.
        self.ddl_sep = QFrame()
        self.ddl_sep.setObjectName("ddlSeparator")
        self.ddl_sep.setFixedWidth(DDL_SEP_WIDTH)
        self.ddl_sep.setStyleSheet("QFrame#ddlSeparator { background: rgba(25,35,45,110); border: none; }")
        self.ddl_sep.setVisible(False)
        layout.addWidget(self.ddl_sep)

        self.ddl_label = DDLCell(todo.ddl)
        self.ddl_label.setFont(mixed_font(11))
        self.ddl_label.setFixedWidth(DDL_COL_MIN)  # adaptive width set in apply_text_width
        self.ddl_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.ddl_label.setToolTip(todo.ddl or "点击设置截止时间")
        self.ddl_label.setVisible(False)
        self.ddl_label.clicked.connect(lambda: parent_window.edit_ddl(todo.id))
        layout.addWidget(self.ddl_label)

        # Style text + ddl together, now that both labels exist.
        self.apply_text_style(parent_window.text_color_for(todo), parent_window.text_needs_halo())

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

    def _ddl_status(self) -> str:
        # "overdue"/"near"/"normal"/"none" — drives the deadline color. Done items and
        # cells whose text we cannot parse into a date never get the alert colors.
        if self.todo.done or not self.todo.ddl.strip():
            return "none"
        deadline = parse_ddl(self.todo.ddl)
        if deadline is None:
            return "normal"
        now = datetime.now()
        if deadline < now:
            return "overdue"
        if deadline - now <= DDL_NEAR_WINDOW:
            return "near"
        return "normal"

    def apply_text_style(self, color: QColor, protect: bool) -> None:
        # Re-applying an identical style (and especially swapping in a brand-new
        # QGraphicsDropShadowEffect) forces a repaint of the row; with the contrast timer
        # firing every few hundred ms that reads as text flicker. Skip no-op updates and
        # reuse the existing halo effect.
        ddl_status = self._ddl_status()
        signature = (color.name(), self.todo.done, protect, ddl_status)
        if signature == self._style_signature:
            return
        self._style_signature = signature
        alpha = 0.45 if self.todo.done else 1.0
        decoration = "text-decoration: line-through;" if self.todo.done else ""
        self.text.setStyleSheet(f"{FONT_STACK_QSS} font-size: 12pt; color: {css_rgba(color, alpha)}; {decoration}")
        if ddl_status == "overdue":
            ddl_css = f"color: {DDL_OVERDUE_COLOR}; font-weight: 600;"
        elif ddl_status == "near":
            ddl_css = f"color: {DDL_NEAR_COLOR}; font-weight: 600;"
        elif self.todo.ddl.strip():
            ddl_css = f"color: {css_rgba(color, alpha * 0.85)};"
        else:
            ddl_css = f"color: {css_rgba(color, alpha * 0.4)};"  # faint click-to-set hint
        self.ddl_label.setStyleSheet(f"{FONT_STACK_QSS} font-size: 11pt; {ddl_css} {decoration}")
        if protect:
            halo = self._halo
            if halo is None:
                halo = QGraphicsDropShadowEffect(self.text)
                halo.setBlurRadius(3.2)
                halo.setOffset(0, 0)
                self._halo = halo
                self.text.setGraphicsEffect(halo)
            if relative_luminance(color) > 0.55:
                halo.setColor(QColor(0, 0, 0, 118))
            else:
                halo.setColor(QColor(255, 255, 255, 138))
        elif self._halo is not None:
            self._halo = None
            self.text.setGraphicsEffect(None)

    def apply_text_width(self, text_width: int, show_ddl: bool = False, ddl_width: int = DDL_COL_MIN) -> int:
        text_width = max(90, text_width)
        self.text.setFixedWidth(text_width)
        self.ddl_sep.setVisible(show_ddl)
        self.ddl_label.setVisible(show_ddl)
        if show_ddl:
            self.ddl_label.setFixedWidth(ddl_width)
            raw = self.todo.ddl.strip()
            if raw:
                ddl_metrics = QFontMetrics(self.ddl_label.font())
                self.ddl_label.setText(ddl_metrics.elidedText(raw, Qt.ElideRight, ddl_width))
            else:
                self.ddl_label.setText(DDL_EMPTY_HINT)
        metrics = QFontMetrics(self.text.font())
        flags = Qt.TextWordWrap | Qt.TextWrapAnywhere
        rect = metrics.boundingRect(QRect(0, 0, text_width, 2000), flags, self.todo.text)
        height = max(ROW_HEIGHT, rect.height() + 18)
        self.setFixedHeight(height)
        return height

    def _complete_changed(self) -> None:
        self.parent_window.complete_todo(self.todo.id, self.checkbox.isChecked(), self)


class CalendarRow(QFrame):
    """A read-only synced calendar event. Mirrors TodoRow's apply_text_style / apply_text_width
    interface (and exposes .checkbox / .ddl_label) so the window's shared layout and contrast
    loops can treat it like a todo row. No urgent button; the time cell is display-only."""

    def __init__(self, event: CalendarEvent, done: bool, parent_window: "MemoWindow") -> None:
        super().__init__(parent_window.content)
        self.cal_event = event
        self.done = done
        self.parent_window = parent_window
        self._style_signature: tuple[str, bool, bool, str] | None = None
        self._halo: QGraphicsDropShadowEffect | None = None
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
        self.checkbox.setChecked(done)
        self.checkbox.setStyleSheet(
            """
            QCheckBox::indicator {
                width: 18px; height: 18px; border-radius: 5px;
                border: 1px solid rgba(25,35,45,120); background: rgba(255,255,255,80);
            }
            QCheckBox::indicator:hover { background: rgba(255,255,255,140); }
            QCheckBox::indicator:checked { background: #111820; image: none; }
            """
        )
        self.checkbox.stateChanged.connect(self._done_changed)
        layout.addWidget(self.checkbox)

        # A small glyph marks these rows as calendar events rather than user todos.
        self.text = TodoTextLabel(f"📅 {event.summary}")
        self.text.setFont(mixed_font(12))
        self.text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.text, 1)

        self.ddl_sep = QFrame()
        self.ddl_sep.setObjectName("ddlSeparator")
        self.ddl_sep.setFixedWidth(DDL_SEP_WIDTH)
        self.ddl_sep.setStyleSheet("QFrame#ddlSeparator { background: rgba(25,35,45,110); border: none; }")
        layout.addWidget(self.ddl_sep)

        self.ddl_label = TodoTextLabel(format_event_time(event))
        self.ddl_label.setFont(mixed_font(11))
        self.ddl_label.setWordWrap(False)
        self.ddl_label.setFixedWidth(DDL_COL_MIN)
        self.ddl_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.ddl_label)

        self.apply_text_style(parent_window._normal_text_color(), parent_window.text_needs_halo())

    def _event_status(self) -> str:
        if self.done:
            return "none"
        start = parse_ddl(self.cal_event.start)
        if start is None:
            return "normal"
        now = datetime.now()
        if start < now:
            return "overdue"
        if start - now <= DDL_NEAR_WINDOW:
            return "near"
        return "normal"

    def apply_text_style(self, color: QColor, protect: bool) -> None:
        status = self._event_status()
        signature = (color.name(), self.done, protect, status)
        if signature == self._style_signature:
            return
        self._style_signature = signature
        alpha = 0.4 if self.done else 1.0
        decoration = "text-decoration: line-through;" if self.done else ""
        self.text.setStyleSheet(f"{FONT_STACK_QSS} font-size: 12pt; color: {css_rgba(color, alpha)}; {decoration}")
        if status == "overdue":
            time_css = f"color: {DDL_OVERDUE_COLOR}; font-weight: 600;"
        elif status == "near":
            time_css = f"color: {DDL_NEAR_COLOR}; font-weight: 600;"
        else:
            time_css = f"color: {css_rgba(color, alpha * 0.85)};"
        self.ddl_label.setStyleSheet(f"{FONT_STACK_QSS} font-size: 11pt; {time_css} {decoration}")
        if protect:
            halo = self._halo
            if halo is None:
                halo = QGraphicsDropShadowEffect(self.text)
                halo.setBlurRadius(3.2)
                halo.setOffset(0, 0)
                self._halo = halo
                self.text.setGraphicsEffect(halo)
            halo.setColor(QColor(0, 0, 0, 118) if relative_luminance(color) > 0.55 else QColor(255, 255, 255, 138))
        elif self._halo is not None:
            self._halo = None
            self.text.setGraphicsEffect(None)

    def apply_text_width(self, text_width: int, show_ddl: bool = True, ddl_width: int = DDL_COL_MIN) -> int:
        text_width = max(90, text_width)
        self.text.setFixedWidth(text_width)
        self.ddl_label.setFixedWidth(ddl_width)
        metrics = QFontMetrics(self.ddl_label.font())
        self.ddl_label.setText(metrics.elidedText(format_event_time(self.cal_event), Qt.ElideRight, ddl_width))
        text_metrics = QFontMetrics(self.text.font())
        flags = Qt.TextWordWrap | Qt.TextWrapAnywhere
        rect = text_metrics.boundingRect(QRect(0, 0, text_width, 2000), flags, self.text.text())
        height = max(ROW_HEIGHT, rect.height() + 18)
        self.setFixedHeight(height)
        return height

    def _done_changed(self) -> None:
        self.parent_window.toggle_calendar_event(self.cal_event.key, self.checkbox.isChecked())


class AddTodoPopup(QDialog):
    def __init__(self, parent_window: "MemoWindow") -> None:
        # Qt.Tool (not Qt.Popup): a Popup window grabs input and does not reliably hand
        # keyboard focus to the QLineEdit on Windows, so the user could not type. The
        # WindowDeactivate handler below gives the same click-outside-to-dismiss behavior.
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.parent_window = parent_window
        self.setWindowTitle("添加事项")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(460, 88)

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
                font-size: {POPUP_INPUT_FONT_PX}px;
                padding: 9px 14px;
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
        self.ddl_input = QLineEdit()
        self.ddl_input.setPlaceholderText("DDL（可选）")
        self.ddl_input.setFixedWidth(140)
        self.ddl_input.returnPressed.connect(self.accept)
        layout.addWidget(self.ddl_input)
        self.ok = RoundButton("✓", 46, tone="confirm")
        self.ok.clicked.connect(self.accept)
        layout.addWidget(self.ok)

    def open_near(self, point: QPoint, width: int) -> None:
        width = max(420, min(600, width))
        self.setFixedSize(width, 88)
        self.panel.setGeometry(0, 0, self.width(), self.height())
        self.move(point)
        self.input.clear()
        self.ddl_input.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, lambda: self.input.setFocus(Qt.PopupFocusReason))

    def event(self, event) -> bool:
        if event.type() == QEvent.WindowDeactivate:
            self.hide()
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def accept(self) -> None:
        text = self.input.text().strip()
        if text:
            self.parent_window.add_todo(text, self.ddl_input.text().strip())
        self.hide()


class EditDDLPopup(QDialog):
    """Single-field popup to set/clear the deadline of an existing todo. Mirrors AddTodoPopup's
    Qt.Tool + click-outside-to-dismiss behavior; the editing target is remembered per open."""

    def __init__(self, parent_window: "MemoWindow") -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.parent_window = parent_window
        self._todo_id: str | None = None
        self.setWindowTitle("设置截止时间")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(380, 88)

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
                font-size: {POPUP_INPUT_FONT_PX}px;
                padding: 9px 14px;
                selection-background-color: rgba(33,150,243,120);
            }}
            """
        )
        add_soft_shadow(self.panel, blur=22, y=8, alpha=60)

        layout = QHBoxLayout(self.panel)
        layout.setContentsMargins(18, 12, 12, 12)
        layout.setSpacing(10)
        self.input = QLineEdit()
        self.input.setPlaceholderText("DDL（留空清除）")
        self.input.returnPressed.connect(self.accept)
        layout.addWidget(self.input, 1)
        self.ok = RoundButton("✓", 46, tone="confirm")
        self.ok.clicked.connect(self.accept)
        layout.addWidget(self.ok)

    def open_for(self, todo_id: str, current: str, point: QPoint) -> None:
        self._todo_id = todo_id
        self.move(point)
        self.input.setText(current)
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, lambda: (self.input.setFocus(Qt.PopupFocusReason), self.input.selectAll()))

    def event(self, event) -> bool:
        if event.type() == QEvent.WindowDeactivate:
            self.hide()
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def accept(self) -> None:
        if self._todo_id is not None:
            self.parent_window.set_ddl(self._todo_id, self.input.text().strip())
        self._todo_id = None
        self.hide()


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
        set_label_font(title, SETTING_TITLE_FONT_PX)
        subtitle = BodyLabel("已归档的待办事项可以随时恢复。")
        subtitle.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,150); font-size: {SETTING_STATUS_FONT_PX}px;")
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


# Fixed vertical chrome inside the window that is NOT glass padding: the top bar (drag handle +
# buttons), its spacing to the list, and the scroll's inner margins. The window height is solved
# so that, after the proportional glass padding, this block + the rows + corner margin all fit
# inside the glass. (Originally folded into a 104px magic constant alongside the static margins.)
MEMO_TOP_BLOCK = 68


class GlassSkin:
    """Liquid-glass skin: defines the background geometry and the content insets that keep rows
    inside the visible glass. The glass rounded-rect is the window scaled by `geometry_scale`, so
    it leaves a margin proportional to the window size on every side; content must inset by that
    same proportional padding or it spills into the transparent gap (most visible at the bottom
    once the window grows tall, e.g. in expanded mode).

    Future skins (e.g. a flat translucent panel for low-end PCs) can set geometry_scale = 1.0
    (no padding, content fills the window) and uses_glass = False; the inset math below degrades
    to the static corner margin with no special-casing."""

    kind = "glass"
    geometry_scale = 0.94
    radius_ratio = 0.24
    corner_margin = 8  # rounded-corner avoidance + a little breathing room
    uses_glass = True

    def vertical_padding(self, height: int) -> int:
        return round(height * (1.0 - self.geometry_scale) / 2.0)

    def horizontal_padding(self, width: int) -> int:
        return round(width * (1.0 - self.geometry_scale) / 2.0)


class AcrylicSkin:
    """Lightweight frosted-glass skin for low-end PCs. The window is a translucent DWM
    acrylic surface (rounded by DWM, not an SDF) with no GPU screen capture, no effect chain,
    and no contrast sampling — so the whole window IS the surface (geometry_scale = 1.0) and
    content fills it with only a small corner margin. uses_glass = False makes the inset math
    in _resize_for_content collapse to the static corner margin."""

    kind = "acrylic"
    geometry_scale = 1.0
    radius_ratio = 0.0
    corner_margin = 14
    uses_glass = False

    def vertical_padding(self, height: int) -> int:
        return 0

    def horizontal_padding(self, width: int) -> int:
        return 0


# Acrylic frost tint opacity (alpha over the blurred desktop). Kept at a readability floor so
# even a busy/terminal desktop behind the window is pressed into a near-uniform surface.
ACRYLIC_TINT_ALPHA = 0xB3  # ~0.70
# Deterministic text colors for the acrylic skin, chosen by the frost tint's luminance: a soft
# near-black on light frost, a soft near-white on dark frost (not pure #000/#FFF — calmer).
ACRYLIC_TEXT_DARK = "#1B2127"
ACRYLIC_TEXT_LIGHT = "#E8ECEF"


class MemoWindow(OneGPUWidget):
    def __init__(self, app: "LiquidMemoApp") -> None:
        super().__init__(qt_move=False)
        self.app = app
        self.skin = self._make_skin(app.state.settings.skin)
        # Tracks which rendering mode is currently live so apply_settings only performs the
        # (heavier) glass<->acrylic transition when the skin actually changes.
        self._active_skin_kind: str | None = None
        self._window_effect = WindowsWindowEffect(self)
        self._acrylic_applied = False
        self._acrylic_signature: str | None = None
        self.setWindowTitle("桌面备忘")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._rows: dict[str, TodoRow] = {}
        self._event_rows: dict[str, CalendarRow] = {}
        self._calendar_header: QLabel | None = None
        # Expanded mode grows the window to fit all content (no height clamp, no scrollbar, no
        # elided text); collapsed mode keeps the default clamp + scroll behavior.
        self._expanded = False
        self._shown_once = False
        self._sampled_background = QColor(246, 248, 252)
        self._background_complexity = 0.0
        self._background_extremely_busy = False
        self._auto_text_color = qcolor(app.state.settings.todoTextColor)
        self._last_text_color_change = 0.0
        self._latest_frame: np.ndarray | None = None
        self._effects_enabled = False
        self._window_layer_applied = False
        self._is_window_moving = False
        self._contrast_was_active = False
        self._capture_source_ready = False
        self._last_capture_reset = time.monotonic()
        self._last_capture_sync = 0.0
        self._effect_signature: tuple[str, int, int] | None = None
        self._contrast_timer = QTimer(self)
        self._contrast_timer.setTimerType(Qt.PreciseTimer)
        self._contrast_timer.setInterval(300)
        self._contrast_timer.timeout.connect(self.update_auto_contrast)
        # Coalesces the "force a contrast refresh after a change settled" requests so a
        # rapid stream of apply_settings() calls (e.g. dragging a slider) collapses into a
        # single forced sample instead of queuing dozens of full captures.
        self._contrast_refresh_timer = QTimer(self)
        self._contrast_refresh_timer.setSingleShot(True)
        self._contrast_refresh_timer.timeout.connect(lambda: self.update_auto_contrast(force=True))
        self._build_content()
        # Global wheel hook: scroll the list whenever the cursor is over it, bypassing the
        # click-through hit-testing that otherwise sends wheel events to the desktop below.
        self._wheel_hook = GlobalWheelHook(self._on_global_wheel)
        self._wheel_hook.install()

        # ── Edge auto-hide (dock) state ──────────────────────────────────────────────────
        self._dock_edge: str | None = None      # "left"/"right"/"top" while docked, else None
        self._dock_hidden = False               # True when slid off-screen (only peek showing)
        self._dock_animating = False            # suppresses moveEvent side effects during slide
        self._dock_shown_pos: QPoint | None = None  # flush-against-edge position (fully visible)
        self._slide_anim: QPropertyAnimation | None = None
        # Cursor poll runs only while docked-and-shown: detects the cursor leaving the window so
        # the hide countdown can start (the click-through body never delivers leave events).
        self._dock_poll = QTimer(self)
        self._dock_poll.setInterval(DOCK_POLL_MS)
        self._dock_poll.timeout.connect(self._dock_tick)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_docked)

    def schedule_contrast_refresh(self, delay: int = 180) -> None:
        if self.app.state.settings.skin == "acrylic" or self.app.state.settings.fontColorMode == "manual":
            return
        self._contrast_refresh_timer.start(delay)

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
        self.expand_button = RoundButton("▾", tone="neutral")
        self.expand_button.setToolTip("展开全部")
        self.expand_button.clicked.connect(self.toggle_expanded)
        top.addWidget(self.expand_button)
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
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            " QScrollBar:vertical { width: 9px; background: transparent; margin: 2px 1px; }"
            " QScrollBar::handle:vertical { background: rgba(17,24,32,80); border-radius: 4px; min-height: 36px; }"
            " QScrollBar::handle:vertical:hover { background: rgba(17,24,32,130); }"
            " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
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
        self.edit_ddl_popup = EditDDLPopup(self)

    def protect_content_layer(self) -> None:
        if self.container:
            self.container.raise_()
        set_window_exclude_from_capture(self, exclude=True)

    def sync_capture_position(self, render: bool = False) -> None:
        try:
            self._update_pending_pos()
            self._last_capture_sync = time.monotonic()
            if render:
                self._on_frame()
        except Exception as exc:
            print(f"[LiquidMemo] capture sync failed: {exc}")

    def reset_capture_pipeline(self, reason: str = "manual") -> None:
        try:
            was_active = self._timer.isActive()
            fps = self._fps or REST_FPS
            self.stop()
            if self._resource_id:
                self._mgr.remove_resource(self._resource_id)
        except Exception:
            was_active = True
            fps = REST_FPS

        self._resource_id = 0
        self._last_display_id = 0
        self._capture_source_ready = False

        try:
            self._mgr.shutdown_display_capture()
            if not self._mgr.initialize_display_capture():
                print(f"[LiquidMemo] display capture reset failed: {reason}")
                return
            self.set_capture_source(display_index=self._display_index, tag="LiquidMemoWidget")
            self._capture_source_ready = True
            self.sync_capture_position(render=True)
            for delay in (40, 120, 260):
                QTimer.singleShot(delay, lambda: self.sync_capture_position(render=True))
        except Exception as exc:
            print(f"[LiquidMemo] display capture reset error: {exc}")
        finally:
            self._last_capture_reset = time.monotonic()
            if was_active or self.isVisible():
                self.start(fps=fps)

    def refresh_capture_after_idle(self) -> None:
        if time.monotonic() - self._last_capture_reset > 45:
            self.reset_capture_pipeline("idle-before-move")
        else:
            self.sync_capture_position(render=True)

    def ensure_frame_loop(self, fps: int = REST_FPS) -> None:
        if not self._timer.isActive() or self._fps != fps:
            self.start(fps=fps)

    def _on_frame(self) -> None:
        # Validated replacement for OneGPUWidget._on_frame. The OS desktop duplication
        # occasionally hands back an all-black frame for this WDA_EXCLUDEFROMCAPTURE
        # window's region; the stock loop presented those directly, which is the visible
        # black<->transparent flicker. Here every captured frame is read back and checked
        # first — a blank frame is dropped and the last good output stays on screen.
        if self._active_skin_kind == "acrylic":
            return  # frosted skin does no screen capture; the DWM acrylic follows the window
        d3d = self._d3d
        if not d3d._presenter_id or d3d._capture_w <= 0 or d3d._capture_h <= 0:
            return

        new_id = self._mgr.capture_display_region(
            display_index=self._display_index,
            x=self._pending_x,
            y=self._pending_y,
            width=d3d._capture_w,
            height=d3d._capture_h,
            tag=self._capture_tag,
        )
        self._frame_count += 1
        if not new_id:
            self._present_last_frame()
            return

        frame: np.ndarray | None
        try:
            frame = self._mgr.copy_resource_to_numpy(new_id)
        except Exception:
            frame = None
        if frame is not None and self._last_display_id and self._frame_looks_blank(frame):
            if new_id != self._resource_id:
                self._mgr.remove_resource(new_id)
            self._present_last_frame()
            return
        if frame is not None:
            self._latest_frame = frame

        if self._resource_id and self._resource_id != new_id:
            self._mgr.remove_resource(self._resource_id)
        self._resource_id = new_id

        display_id = new_id
        if self._fx_ready and self._has_effects and self._sdf_id:
            output_id = self._fx.render_effects_by_id(
                screen_resource_id=new_id,
                sdf_resource_id=self._sdf_id,
            )
            if output_id:
                display_id = output_id
            else:
                self._present_last_frame()
                return

        _dwm_flush()
        d3d._present(display_id)
        self._last_display_id = display_id

    def _present_last_frame(self) -> None:
        if self._last_display_id:
            _dwm_flush()
            self._d3d._present(self._last_display_id)

    @staticmethod
    def _frame_looks_blank(frame: np.ndarray) -> bool:
        # Genuine desktops are never pitch black across the whole region (even dark
        # wallpapers carry a few brighter pixels); a duplication glitch frame is exactly 0.
        return int(frame[::8, ::8, :3].max()) < 6

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # In frosted mode the D3D surface is never presented; hide it before the first paint so
        # its blank swapchain doesn't flash over the acrylic before apply_settings runs.
        if self.app.state.settings.skin == "acrylic" and not self._d3d.isHidden():
            self._d3d.hide()
        # Keep our own text/control layer out of the GPU screen capture. Otherwise
        # the next liquid-glass frame captures and refracts the text itself.
        self.protect_content_layer()
        for delay in (0, 80, 180, 420):
            QTimer.singleShot(delay, self.protect_content_layer)
        # Re-showing (e.g. from the tray) while docked-hidden would otherwise reveal the window
        # at its off-screen position — snap it back out so it is actually visible.
        if self._dock_edge is not None and self._dock_hidden:
            self._reveal_docked()
        if not self._shown_once:
            self._shown_once = True
            self.apply_initial_geometry()
            QTimer.singleShot(80, self.refresh)
            QTimer.singleShot(180, self.apply_text_colors)
            # Restore a dock if the saved position sits against an edge.
            QTimer.singleShot(280, self._maybe_dock)
        QTimer.singleShot(0, self.apply_settings)

    def hideEvent(self, event) -> None:
        # Suspend dock timers/animation while the window is hidden (e.g. from the tray); showEvent
        # restores the dock. _dock_edge/_dock_hidden are kept so the state survives a hide/show.
        self._dock_poll.stop()
        self._hide_timer.stop()
        self._cancel_slide()
        self._dock_animating = False
        super().hideEvent(event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self._shown_once:
            # During a dock slide the window is mid-animation toward an off-screen position; skip
            # the per-move capture/save/contrast work (and don't persist off-screen coordinates).
            if self._dock_animating:
                return
            self.app.state.window.x = self.x()
            self.app.state.window.y = self.y()
            if self._is_window_moving:
                self.sync_capture_position(render=True)
                return
            self.sync_capture_position(render=False)
            QTimer.singleShot(0, self.protect_content_layer)
            self.app.save_later()
            self.schedule_contrast_refresh(80)

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            import ctypes
            from ctypes import wintypes

            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_NCHITTEST:
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                local = self.mapFromGlobal(QPoint(x, y))
                # While hidden, the on-screen peek strip must be HTCLIENT (not click-through) so
                # the window receives WM_MOUSEMOVE over it and can slide back out.
                if self._dock_hidden and not self._dock_animating and self._peek_rect_local().contains(local):
                    return True, HTCLIENT
                if self._rect_for(self.drag_handle).contains(local):
                    return True, HTCAPTION
                if self._is_interactive_point(local):
                    return True, HTCLIENT
                if self.app.state.settings.layerMode == "alwaysVisibleClickThrough":
                    return True, HTTRANSPARENT
            if msg.message == WM_MOUSEMOVE:
                # Only the peek strip is HTCLIENT while hidden, so any mouse-move here means the
                # cursor reached the strip — slide the window back out.
                if self._dock_hidden and not self._dock_animating:
                    self._show_docked()
            if msg.message == WM_ENTERSIZEMOVE:
                self._begin_window_move()
            elif msg.message == WM_EXITSIZEMOVE:
                QTimer.singleShot(0, self._end_window_move)
        return super().nativeEvent(event_type, message)

    def _rect_for(self, widget: QWidget) -> QRect:
        top_left = widget.mapTo(self, QPoint(0, 0))
        return QRect(top_left, widget.size())

    def _is_interactive_point(self, point: QPoint) -> bool:
        widgets: list[QWidget] = [self.add_button, self.hide_button, self.expand_button]
        for row in self._rows.values():
            # ddl_label is the editable DDLCell (click-to-edit); the time cell on calendar rows
            # is display-only, so only their checkbox is interactive.
            widgets.extend([row.checkbox, row.urgent, row.ddl_label])
        for row in self._event_rows.values():
            widgets.append(row.checkbox)
        # Wheel scrolling over the list is handled by the global wheel hook (see
        # _on_global_wheel), so the list area can stay click-through: only the discrete controls
        # below are interactive, everything else passes clicks to the desktop.
        return any(widget.isVisible() and self._rect_for(widget).adjusted(-4, -4, 4, 4).contains(point) for widget in widgets)

    def begin_system_move(self) -> None:
        self._begin_window_move()
        begin_system_move(int(self.winId()))
        QTimer.singleShot(0, self._end_window_move)

    def _begin_window_move(self) -> None:
        if self._is_window_moving:
            return
        self._is_window_moving = True
        if self._active_skin_kind == "acrylic":
            return  # the frost follows the window via DWM — no capture loop to spin up
        self._contrast_was_active = self._contrast_timer.isActive()
        self._contrast_timer.stop()
        self.refresh_capture_after_idle()
        self.start(fps=MOVE_FPS)

    def _end_window_move(self) -> None:
        if not self._is_window_moving:
            return
        self._is_window_moving = False
        self.app.state.window.x = self.x()
        self.app.state.window.y = self.y()
        self.app.save_later()
        if self._active_skin_kind == "acrylic":
            self.protect_content_layer()
            self._maybe_dock()
            return
        self.sync_capture_position(render=True)
        self.protect_content_layer()
        self.start(fps=REST_FPS)
        if self.app.state.settings.fontColorMode != "manual":
            self._contrast_timer.start()
            self.schedule_contrast_refresh()
        self._maybe_dock()

    # ── Edge auto-hide (dock) ────────────────────────────────────────────────────────────
    def _dock_geometry(self) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry()

    def _dock_pos(self, hidden: bool) -> QPoint:
        """The window position for the current dock edge, either flush-visible or slid out to a
        DOCK_PEEK strip. The cross-axis (position along the edge) comes from the snapped shown
        position; the perpendicular axis is recomputed from the live window size."""
        g = self._dock_geometry()
        w, h = self.width(), self.height()
        shown = self._dock_shown_pos or self.pos()
        if self._dock_edge == "left":
            x = (g.left() - w + DOCK_PEEK) if hidden else g.left()
            return QPoint(x, shown.y())
        if self._dock_edge == "right":
            x = (g.left() + g.width() - DOCK_PEEK) if hidden else (g.left() + g.width() - w)
            return QPoint(x, shown.y())
        y = (g.top() - h + DOCK_PEEK) if hidden else g.top()  # "top"
        return QPoint(shown.x(), y)

    def _peek_rect_local(self) -> QRect:
        w, h = self.width(), self.height()
        if self._dock_edge == "left":
            return QRect(w - DOCK_PEEK, 0, DOCK_PEEK, h)
        if self._dock_edge == "right":
            return QRect(0, 0, DOCK_PEEK, h)
        if self._dock_edge == "top":
            return QRect(0, h - DOCK_PEEK, w, DOCK_PEEK)
        return QRect()

    def _maybe_dock(self) -> None:
        # Called after a move ends: dock to the nearest edge within threshold, else undock.
        if not self.app.state.settings.edgeAutoHide or not self.isVisible():
            self._undock()
            return
        g = self._dock_geometry()
        x, y, w, h = self.x(), self.y(), self.width(), self.height()
        gaps = {
            "left": x - g.left(),
            "right": (g.left() + g.width()) - (x + w),
            "top": y - g.top(),
        }
        edge = min(gaps, key=gaps.get)
        if gaps[edge] > DOCK_THRESHOLD:
            self._undock()
            return
        self._dock_edge = edge
        self._dock_hidden = False
        if edge == "left":
            shown = QPoint(g.left(), y)
        elif edge == "right":
            shown = QPoint(g.left() + g.width() - w, y)
        else:
            shown = QPoint(x, g.top())
        self._dock_shown_pos = shown
        if self.pos() != shown:
            self.move(shown)
        self._dock_shown_pos = self.pos()
        self._hide_timer.stop()
        self._dock_poll.start(DOCK_POLL_MS)

    def _undock(self) -> None:
        if self._dock_edge is None:
            self._dock_hidden = False
            return
        if self._dock_hidden:
            self._reveal_docked()  # never leave the window stranded off-screen
        self._dock_edge = None
        self._dock_hidden = False
        self._dock_animating = False
        self._dock_shown_pos = None
        self._dock_poll.stop()
        self._hide_timer.stop()
        self._cancel_slide()
        if self._active_skin_kind == "glass":
            self.ensure_frame_loop(REST_FPS)

    def _reposition_dock(self) -> None:
        target = self._dock_pos(self._dock_hidden)
        if self.pos() == target:
            return
        if self._dock_hidden:
            self._dock_animating = True
            self.move(target)
            self._dock_animating = False
        else:
            self.move(target)
            self._dock_shown_pos = self.pos()

    def _reveal_docked(self) -> None:
        # Instant (no slide) reveal to the flush position — used on tray re-show and undock.
        self._cancel_slide()
        self._dock_animating = True
        self.move(self._dock_pos(hidden=False))
        self._dock_animating = False
        self._dock_hidden = False
        if self._active_skin_kind == "glass":
            self.ensure_frame_loop(REST_FPS)
            self.sync_capture_position(render=True)
        self.protect_content_layer()
        if self._dock_edge is not None:
            self._dock_poll.start(DOCK_POLL_MS)

    def _hide_docked(self) -> None:
        if self._dock_edge is None or self._dock_hidden or self._dock_animating:
            return
        if self._suppress_hide():
            return
        self._dock_hidden = True
        self._hide_timer.stop()
        # The poll keeps running while hidden: it is what detects the cursor reaching the peek
        # strip. (WM_MOUSEMOVE on the strip proved unreliable in practice — the mostly off-screen
        # HTCLIENT sliver does not dependably receive mouse messages.)
        self._animate_to(self._dock_pos(hidden=True))

    def _show_docked(self) -> None:
        if self._dock_edge is None or not self._dock_hidden or self._dock_animating:
            return
        self._dock_hidden = False
        if self._active_skin_kind == "glass":
            self.ensure_frame_loop(REST_FPS)
        self._animate_to(self._dock_pos(hidden=False))
        self._dock_poll.start(DOCK_POLL_MS)

    def _animate_to(self, target: QPoint) -> None:
        self._cancel_slide()
        if self.pos() == target:
            self._on_slide_finished()
            return
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(DOCK_SLIDE_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.finished.connect(self._on_slide_finished)
        self._dock_animating = True
        self._slide_anim = anim
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _cancel_slide(self) -> None:
        if self._slide_anim is not None:
            try:
                self._slide_anim.stop()
            except RuntimeError:
                pass
            self._slide_anim = None

    def _on_slide_finished(self) -> None:
        self._dock_animating = False
        self._slide_anim = None
        if self._active_skin_kind == "glass":
            if self._dock_hidden:
                self.stop()  # fully off-screen: stop the capture loop (saves power)
            else:
                self.refresh_capture_after_idle()
                self.ensure_frame_loop(REST_FPS)
                self.sync_capture_position(render=True)
        self.protect_content_layer()

    def _peek_rect_global(self) -> QRect:
        # The on-screen strip of the hidden window, in global coordinates, with a small inward
        # tolerance so the cursor doesn't have to land on the exact 5px sliver.
        g = self._dock_geometry()
        if self._dock_edge == "left":
            return QRect(g.left(), self.y(), DOCK_PEEK + 2, self.height())
        if self._dock_edge == "right":
            return QRect(g.left() + g.width() - DOCK_PEEK - 2, self.y(), DOCK_PEEK + 2, self.height())
        if self._dock_edge == "top":
            return QRect(self.x(), g.top(), self.width(), DOCK_PEEK + 2)
        return QRect()

    def _dock_tick(self) -> None:
        # Poll while docked. Shown: start the hide countdown when the cursor leaves the window.
        # Hidden: watch for the cursor reaching the peek strip and slide back out.
        if self._dock_edge is None or self._dock_animating:
            return
        cursor = QCursor.pos()
        if self._dock_hidden:
            if self._peek_rect_global().contains(cursor):
                self._show_docked()
            return
        if self._suppress_hide():
            self._hide_timer.stop()
            return
        inside = self.frameGeometry().adjusted(-3, -3, 3, 3).contains(cursor)
        if inside:
            self._hide_timer.stop()
        elif not self._hide_timer.isActive():
            self._hide_timer.start(DOCK_HIDE_DELAY_MS)

    def _suppress_hide(self) -> bool:
        return (
            self._is_window_moving
            or self.add_popup.isVisible()
            or self.edit_ddl_popup.isVisible()
            or self.app.settings_window.isVisible()
            or self.app.history_window.isVisible()
        )

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

    def _make_skin(self, skin_name: str):
        return AcrylicSkin() if skin_name == "acrylic" else GlassSkin()

    def apply_settings(self, refresh_rows: bool = False, reset_capture: bool = False) -> None:
        settings = self.app.state.settings
        skin_changed = self._active_skin_kind not in (None, settings.skin)
        self.skin = self._make_skin(settings.skin)
        if settings.skin == "acrylic":
            self._apply_acrylic_mode()
        else:
            self._apply_glass_mode(reset_capture)
        # The two skins use different content insets/geometry (glass padding vs acrylic
        # full-fill), so a skin switch needs a relayout even if the caller didn't ask for one.
        if refresh_rows or skin_changed:
            self.refresh()
        self.protect_content_layer()
        self.apply_window_layer()
        if not settings.edgeAutoHide:
            self._undock()

    def _apply_glass_mode(self, reset_capture: bool = False) -> None:
        settings = self.app.state.settings
        if self._active_skin_kind not in (None, "glass"):
            # Coming back from acrylic: drop the frost, re-show the D3D surface, and rebuild the
            # capture pipeline (it was stopped / went stale while frosted).
            self._remove_acrylic()
            self._d3d.show()
            reset_capture = True
        self._active_skin_kind = "glass"

        if reset_capture:
            self.reset_capture_pipeline("settings")
        elif not self._capture_source_ready:
            self.set_capture_source(display_index=0, tag="LiquidMemoWidget")
            self._capture_source_ready = True
            self._last_capture_reset = time.monotonic()
            self.sync_capture_position(render=True)
        else:
            self.sync_capture_position(render=False)

        # Re-enabling the effect chain resets renderer state and can drop/blank a frame, so
        # do it once: apply_settings runs on every slider tick while dragging.
        if not self._effects_enabled:
            self.enable_effects([
                EffectType.FLOW,
                EffectType.CHROMATIC_ABERRATION,
                EffectType.HIGHLIGHT,
                EffectType.ANTI_ALIASING,
                EffectType.COLOR_OVERLAY,
            ])
            self._effects_enabled = True
        effect_signature = (settings.windowTint, int(settings.glassOpacity * 1000), int(settings.liquidStrength * 1000))
        if effect_signature != self._effect_signature:
            self.update_effects(build_effect_params(EFFECTS_PARAMS, settings.windowTint, settings.glassOpacity, settings.liquidStrength))
            self._effect_signature = effect_signature
        self.ensure_frame_loop(fps=REST_FPS)
        if settings.fontColorMode == "manual":
            self._contrast_timer.stop()
            self.apply_text_colors()
        else:
            if not self._contrast_timer.isActive():
                self._contrast_timer.start()
            self.schedule_contrast_refresh()

    def _apply_acrylic_mode(self) -> None:
        # Frosted mode: no screen capture, no effect chain, no contrast sampling. The window is
        # a translucent DWM acrylic surface; the D3D child is hidden so the frost shows through.
        self._active_skin_kind = "acrylic"
        self._contrast_timer.stop()
        self.stop()
        if not self._d3d.isHidden():
            self._d3d.hide()
        self._apply_acrylic_effect()
        self.apply_text_colors()

    def _apply_acrylic_effect(self) -> None:
        settings = self.app.state.settings
        tint = qcolor(settings.windowTint, "#F2F4F7")
        gradient = f"{tint.red():02X}{tint.green():02X}{tint.blue():02X}{ACRYLIC_TINT_ALPHA:02X}"
        if self._acrylic_applied and gradient == self._acrylic_signature:
            return  # avoid re-issuing the composition attribute on every slider tick (flicker)
        hwnd = int(self.winId())
        self._window_effect.setAcrylicEffect(hwnd, gradient, enableShadow=True)
        set_rounded_corners(hwnd, True)
        self._acrylic_applied = True
        self._acrylic_signature = gradient

    def _remove_acrylic(self) -> None:
        if not self._acrylic_applied:
            return
        try:
            hwnd = int(self.winId())
            self._window_effect.removeBackgroundEffect(hwnd)
            set_rounded_corners(hwnd, False)
        except Exception:
            pass
        self._acrylic_applied = False
        self._acrylic_signature = None

    def apply_window_layer(self) -> None:
        # SetWindowPos/Z-order churn on every apply_settings call makes the window flash;
        # the tool-window style, parent detach, and topmost flag are sticky, so once is enough.
        if not self.isVisible() or self._window_layer_applied:
            return
        hwnd = int(self.winId())
        apply_tool_window(hwnd)
        detach_from_parent(hwnd)
        set_topmost(hwnd, True)
        self._window_layer_applied = True

    @staticmethod
    def _todo_sort_key(item: TodoItem) -> tuple:
        # Urgent items stay pinned to the top (existing behavior). Within each group, items
        # with a parseable deadline sort by it (earliest first); items without a usable date
        # fall back to their manual order, landing after the dated ones.
        deadline = parse_ddl(item.ddl)
        ddl_rank = deadline.timestamp() if deadline else float("inf")
        return (not item.urgent, ddl_rank, item.order, item.createdAt)

    def refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()
        self._event_rows.clear()
        self._calendar_header = None

        active = sorted(self.app.state.todos, key=self._todo_sort_key)
        events = self._visible_calendar_events()
        self.scroll.setVisible(bool(active) or bool(events))
        self.empty.setVisible(not active and not events)

        for todo in active:
            row = TodoRow(todo, self.app.state.settings, self)
            self._rows[todo.id] = row
            self.list_layout.addWidget(row)

        if events:
            self._calendar_header = self._make_calendar_header()
            self.list_layout.addWidget(self._calendar_header)
            done = set(self.app.state.calendarDoneKeys)
            for event in events:
                row = CalendarRow(event, event.key in done, self)
                self._event_rows[event.key] = row
                self.list_layout.addWidget(row)

        self.list_layout.addStretch()
        self._resize_for_content(active, events)
        self.apply_text_colors()

    def _visible_calendar_events(self) -> list[CalendarEvent]:
        # Synced events are read-only and never archive to history (they would just re-sync),
        # so unlike todos they ignore completeBehavior: checking one only dims + strikes it
        # through in place and it stays visible until it drops out of the sync window.
        # Only events of checked feeds show; unchecked feeds keep their cache hidden.
        settings = self.app.state.settings
        if not settings.calendarEnabled:
            return []
        visible = {feed.id for feed in settings.active_calendar_feeds()}
        return [event for event in self.app.state.calendarEvents if event.feedId in visible]

    def _make_calendar_header(self) -> QLabel:
        header = QLabel("日程")
        header.setFixedHeight(CALENDAR_HEADER_HEIGHT)
        color = self._normal_text_color()
        header.setStyleSheet(
            f"{FONT_STACK_QSS} color: {css_rgba(color, 0.7)}; font-size: 11pt; font-weight: 600; padding-left: 6px;"
        )
        return header

    def toggle_calendar_event(self, key: str, checked: bool) -> None:
        self.app.calendar.toggle_event_done(key, checked)

    def toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.expand_button.setText("▴" if self._expanded else "▾")
        self.expand_button.setToolTip("收起" if self._expanded else "展开全部")
        self.refresh()

    def _scroll_overflowing(self) -> bool:
        bar = self.scroll.verticalScrollBar()
        return bar is not None and bar.maximum() > 0

    def _on_global_wheel(self, gx: int, gy: int, delta: int) -> bool:
        # Invoked from the low-level mouse hook on the GUI thread's message pump. Scroll only
        # when the list is visible, overflowing, and the cursor is over the scroll area; else
        # return False so the wheel passes through to whatever is underneath.
        if not self.isVisible() or not self.scroll.isVisible() or not self._scroll_overflowing():
            return False
        local = self.mapFromGlobal(QPoint(gx, gy))
        if not self._rect_for(self.scroll).contains(local):
            return False
        bar = self.scroll.verticalScrollBar()
        if bar is None:
            return False
        bar.setValue(bar.value() - round(delta / 120.0 * 60))
        return True

    def _acrylic_text_color(self) -> QColor:
        # The frost tint dominates the surface, so contrast is deterministic: pick the soft
        # dark or soft light text by the tint's luminance. No sampling, no neon, no flicker.
        tint = qcolor(self.app.state.settings.windowTint, "#F2F4F7")
        return best_contrast_color(tint, [ACRYLIC_TEXT_DARK, ACRYLIC_TEXT_LIGHT])

    def _normal_text_color(self) -> QColor:
        settings = self.app.state.settings
        if settings.skin == "acrylic":
            return self._acrylic_text_color()
        if settings.fontColorMode == "manual":
            return qcolor(settings.todoTextColor)
        return QColor(self._auto_text_color)

    def text_color_for(self, todo: TodoItem) -> QColor:
        if todo.urgent:
            return qcolor(self.app.state.settings.urgentTextColor, "#FF0000")
        return self._normal_text_color()

    def text_needs_halo(self) -> bool:
        settings = self.app.state.settings
        if settings.skin == "acrylic":
            return False  # the frost is already a calm, even surface — no protective halo
        if settings.fontColorMode == "manual":
            return False
        return settings.fontColorMode == "autoEnhanced" or self._background_extremely_busy

    def apply_text_colors(self) -> None:
        for row in self._rows.values():
            row.apply_text_style(self.text_color_for(row.todo), self.text_needs_halo())
        normal = self._normal_text_color()
        for row in self._event_rows.values():
            row.apply_text_style(normal, self.text_needs_halo())
        if self._calendar_header is not None:
            self._calendar_header.setStyleSheet(
                f"{FONT_STACK_QSS} color: {css_rgba(normal, 0.7)}; font-size: 11pt; font-weight: 600; padding-left: 6px;"
            )
        # `normal` already resolves to the manual/auto/acrylic color, so it is the right base
        # for the empty-state label in every skin and font mode.
        self.empty.setStyleSheet(f"{FONT_STACK_QSS} color: {css_rgba(normal, 0.58)}; font-size: 15px;")

    def update_auto_contrast(self, force: bool = False) -> None:
        if not self.isVisible() or self.app.state.settings.skin == "acrylic":
            return
        if self.app.state.settings.fontColorMode == "manual":
            return
        sample = self._sample_background()
        if sample is None:
            sampled_background = QColor(self._sampled_background)
            complexity = self._background_complexity
        else:
            sampled_background, complexity = sample

        background = self._effective_contrast_background(sampled_background)
        busy = complexity >= (BUSY_BACKGROUND_EXIT if self._background_extremely_busy else BUSY_BACKGROUND_ENTER)
        if busy:
            next_text = best_contrast_color(background, HIGH_VISIBILITY_COLORS)
        else:
            next_text = best_contrast_color(background, ["#05080C", "#111820", "#F7FAFF", "#FFFFFF"])

        current_text_gain = contrast_ratio(self._auto_text_color, background)
        next_text_gain = contrast_ratio(next_text, background)

        now = time.monotonic()
        changed = False
        if busy != self._background_extremely_busy:
            self._background_extremely_busy = busy
            changed = True
        # Switch color only when the current one is genuinely hard to read, or the candidate
        # is clearly better AND the last switch has settled. Rapid back-and-forth color swaps
        # every sample read as text flicker, so prefer keeping a readable color stable.
        settled = (now - self._last_text_color_change) >= 1.0
        should_switch = force or current_text_gain < 3.2 or (settled and next_text_gain > current_text_gain + 0.75)
        if next_text.name() != self._auto_text_color.name() and should_switch:
            self._auto_text_color = next_text
            self._last_text_color_change = now
            changed = True
        self._background_complexity = complexity
        self._sampled_background = sampled_background

        if changed:
            self.apply_text_colors()

    def _effective_contrast_background(self, sampled_background: QColor) -> QColor:
        settings = self.app.state.settings
        tint = qcolor(settings.windowTint, "#FFFFFF")
        return blend_colors(sampled_background, tint, color_overlay_strength(settings.glassOpacity))

    def _sample_background(self) -> tuple[QColor, float] | None:
        # Reuse the frame the validated render loop (_on_frame) already read back and
        # blank-checked: the desktop content directly behind this window with the window
        # itself omitted. The contrast sampler therefore issues no screen capture and no
        # GPU readback of its own.
        frame = self._latest_frame
        if frame is None:
            return None
        return self._analyze_sample_array(frame)

    def _analyze_sample_array(self, bgra: np.ndarray) -> tuple[QColor, float] | None:
        if bgra is None or bgra.ndim != 3 or bgra.shape[0] < 2 or bgra.shape[1] < 2:
            return None
        step_y = max(1, bgra.shape[0] // _SAMPLE_DIM)
        step_x = max(1, bgra.shape[1] // _SAMPLE_DIM)
        sample = bgra[::step_y, ::step_x, :3].astype(np.float32) / 255.0
        blue, green, red = sample[..., 0], sample[..., 1], sample[..., 2]

        def linearize(channel: np.ndarray) -> np.ndarray:
            return np.where(channel <= 0.03928, channel / 12.92, ((channel + 0.055) / 1.055) ** 2.4)

        luminance = 0.2126 * linearize(red) + 0.7152 * linearize(green) + 0.0722 * linearize(blue)
        average = QColor(
            min(255, round(float(red.mean()) * 255)),
            min(255, round(float(green.mean()) * 255)),
            min(255, round(float(blue.mean()) * 255)),
        )
        mean_luminance = float(luminance.mean())
        luminance_range = float(luminance.max() - luminance.min())
        bright_fraction = float((luminance > 0.68).mean())
        dark_fraction = float((luminance < 0.16).mean())
        mid_fraction = float(((luminance >= 0.24) & (luminance <= 0.76)).mean())
        luminance_std = float(luminance.std())
        color_std = float(((red.var() + green.var() + blue.var()) / 3.0) ** 0.5)

        edge_x = np.abs(np.diff(luminance, axis=1))
        edge_y = np.abs(np.diff(luminance, axis=0))
        edge_count = edge_x.size + edge_y.size
        edge_density = float((edge_x.sum() + edge_y.sum()) / edge_count) if edge_count else 0.0

        terminal_like = (
            mean_luminance < 0.32
            and bright_fraction > 0.018
            and dark_fraction > 0.48
            and luminance_range > 0.54
            and edge_density > 0.018
        )
        mixed_text_like = (
            bright_fraction > 0.05
            and dark_fraction > 0.18
            and mid_fraction < 0.78
            and luminance_range > 0.48
            and edge_density > 0.02
        )

        complexity = min(
            1.0,
            max(
                luminance_std * 3.1,
                color_std * 2.35,
                edge_density * 7.5,
                bright_fraction * dark_fraction * luminance_range * 6.0,
                luminance_std * 1.55 + color_std * 1.15 + edge_density * 3.6,
                0.58 if terminal_like else 0.0,
                0.46 if mixed_text_like else 0.0,
            ),
        )
        return average, complexity

    def _resize_for_content(self, active: list[TodoItem], events: list[CalendarEvent] | None = None) -> None:
        events = events or []
        screen = QApplication.primaryScreen().availableGeometry()
        show_todo_ddl = any(todo.ddl for todo in active)
        # The time column is shared by todo DDLs and event times; show it (and reserve width)
        # whenever either group needs it, sizing to the widest string across both for alignment.
        column_active = show_todo_ddl or bool(events)
        ddl_width = self._time_column_width(active, events, self._expanded) if column_active else 0
        ddl_reserve = (ddl_width + DDL_SEP_WIDTH + DDL_COL_GAPS) if column_active else 0
        width = self._adaptive_width(active, events, screen, ddl_reserve)
        text_width = self._text_width_for_window(width, ddl_reserve)
        content_height = sum(self._measure_row_height(todo.text, text_width) for todo in active)
        if events:
            # Calendar rows render "📅 {summary}", which wraps (and grows taller than ROW_HEIGHT)
            # for long titles — measure them like todos so the window height isn't underestimated
            # (which previously left expanded mode hiding the scrollbar yet still clipping rows).
            content_height += CALENDAR_HEADER_HEIGHT
            content_height += sum(self._measure_row_height(f"📅 {event.summary}", text_width) for event in events)
        content_height = max(content_height, ROW_HEIGHT)
        # Solve the window height so that, after the glass's proportional vertical padding, the
        # top block + rows + corner margin still fit inside the glass: H*scale = needed.
        scale = self.skin.geometry_scale
        corner = self.skin.corner_margin
        needed = MEMO_TOP_BLOCK + content_height + 2 * corner
        wanted = max(MIN_HEIGHT, math.ceil(needed / scale))
        screen_cap = screen.height() - 64
        if self._expanded:
            # Grow to fit everything; only the physical screen limits us. Hide the scrollbar
            # when it all fits, but fall back to AsNeeded if content still exceeds the screen.
            height = min(wanted, screen_cap)
            fits = wanted <= screen_cap
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if fits else Qt.ScrollBarAsNeeded)
        else:
            height = min(wanted, int(screen.height() * MAX_HEIGHT_RATIO), screen_cap)
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        if self.width() != width or self.height() != height:
            self.update_sdf(width, height, radius_ratio=self.skin.radius_ratio, scale=scale)
            if self.container:
                self.container.setFixedSize(width, height)

        # Inset the content to the glass. Vertical follows the proportional glass padding so the
        # bottom rows never cross the glass edge; horizontal keeps OUTER_X, which at our width
        # range always already exceeds the glass's horizontal padding (so no change there).
        pad_y = self.skin.vertical_padding(height)
        pad_x = max(OUTER_X, self.skin.horizontal_padding(width))
        self.layout.setContentsMargins(pad_x, pad_y + corner, pad_x, pad_y + corner)

        for row in self._rows.values():
            row.apply_text_width(text_width, show_todo_ddl, ddl_width)
        for row in self._event_rows.values():
            row.apply_text_width(text_width, True, ddl_width)

        self._keep_inside_screen(screen)
        self.app.state.window.width = width
        self.app.state.window.height = height
        if self._dock_edge is not None:
            # Content resized while docked: re-pin to the (recomputed) dock position so the peek
            # strip and slide geometry stay correct for the new size.
            self._reposition_dock()

    def _adaptive_width(self, active: list[TodoItem], events: list[CalendarEvent], screen: QRect, ddl_reserve: int = 0) -> int:
        if not active and not events:
            return MIN_WIDTH
        metrics = QFontMetrics(mixed_font(12))
        text_widths = [metrics.horizontalAdvance(todo.text) for todo in active]
        text_widths += [metrics.horizontalAdvance(f"📅 {event.summary}") for event in events]
        longest = max(text_widths) if text_widths else 0
        chrome = OUTER_X * 2 + 12 + 18 + 30 + 28 + 24 + ddl_reserve
        max_width = min(MAX_WIDTH, int(screen.width() * MAX_WIDTH_RATIO), screen.width() - 64)
        return max(MIN_WIDTH, min(max_width, longest + chrome))

    def _text_width_for_window(self, width: int, ddl_reserve: int = 0) -> int:
        return max(90, width - (OUTER_X * 2 + 12 + 18 + 30 + 28 + 12) - ddl_reserve)

    def _time_column_width(self, active: list[TodoItem], events: list[CalendarEvent], expanded: bool = False) -> int:
        # Width that fits the widest deadline/event-time text in this view (so they show in
        # full), clamped to [DDL_COL_MIN, cap]. Collapsed elides past DDL_COL_MAX; expanded
        # lifts the cap so nothing is truncated.
        metrics = QFontMetrics(mixed_font(11))
        candidates = [todo.ddl.strip() for todo in active if todo.ddl.strip()]
        candidates += [format_event_time(event) for event in events]
        longest = max((metrics.horizontalAdvance(text) for text in candidates), default=0)
        cap = DDL_COL_EXPANDED_MAX if expanded else DDL_COL_MAX
        return max(DDL_COL_MIN, min(cap, longest + DDL_COL_PAD))

    def _measure_row_height(self, text: str, text_width: int) -> int:
        metrics = QFontMetrics(mixed_font(12))
        flags = Qt.TextWordWrap | Qt.TextWrapAnywhere
        rect = metrics.boundingRect(QRect(0, 0, max(90, text_width), 2000), flags, text)
        return max(ROW_HEIGHT, rect.height() + 18)

    def _keep_inside_screen(self, screen: QRect) -> None:
        if not self.isVisible():
            return
        if self._dock_edge is not None:
            return  # docked positions intentionally sit at / past the screen edge
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

    def add_todo(self, text: str, ddl: str = "") -> None:
        next_order = max([todo.order for todo in self.app.state.todos] + [0]) + 1
        self.app.state.todos.append(TodoItem(id=str(uuid4()), text=text, ddl=ddl, order=next_order))
        self.app.save()
        self.refresh()

    def edit_ddl(self, todo_id: str) -> None:
        todo = next((item for item in self.app.state.todos if item.id == todo_id), None)
        if todo is None:
            return
        row = self._rows.get(todo_id)
        screen = QApplication.primaryScreen().availableGeometry()
        popup = self.edit_ddl_popup
        if row is not None:
            anchor = row.ddl_label.mapToGlobal(QPoint(0, row.ddl_label.height() + 6))
        else:
            anchor = QPoint(self.x(), self.y() + self.height() + 10)
        x = min(max(anchor.x(), screen.left() + 12), screen.right() - popup.width() - 12)
        y = min(max(anchor.y(), screen.top() + 12), screen.bottom() - popup.height() - 12)
        popup.open_for(todo_id, todo.ddl, QPoint(x, y))

    def set_ddl(self, todo_id: str, ddl: str) -> None:
        todo = next((item for item in self.app.state.todos if item.id == todo_id), None)
        if todo is None or todo.ddl == ddl:
            return
        todo.ddl = ddl
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
        self.qt.setWindowIcon(tray_icon())
        self.qt.setStyleSheet(f"* {{ {FONT_STACK_QSS} }}")
        self.store = StateStore()
        self.state = self.store.load()
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save)
        self.window = MemoWindow(self)
        self.settings_window = SettingsWindow(self)
        self.history_window = HistoryWindow(self)
        self.calendar = CalendarManager(self)
        self.updater = UpdateManager(self)
        self.tray_menu: QMenu | None = None
        self.tray = QSystemTrayIcon(tray_icon())
        self.tray.setToolTip("桌面备忘")
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.qt.aboutToQuit.connect(self.shutdown)

    def run(self) -> int:
        # showEvent already drives the initial geometry/refresh/recolor sequence; scheduling
        # it again here only rebuilt the list and recolored it a second time.
        self.window.show()
        # Kick off the first calendar sync once the event loop is about to run.
        QTimer.singleShot(0, self.calendar.start)
        # Changelog-after-update + delayed silent update check, after the UI settles.
        QTimer.singleShot(1500, self.updater.on_startup)
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
        menu = QMenu("桌面备忘", self.window)
        # Translucent + frameless so the rounded corners render cleanly instead of being
        # clipped by the menu's square native window.
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        menu.setMinimumWidth(264)
        menu.setStyleSheet(
            f"""
            QMenu {{
                {FONT_STACK_QSS}
                background-color: rgb(251, 252, 254);
                color: rgb(24, 32, 40);
                border: 1px solid rgba(17,24,32,26);
                border-radius: 15px;
                padding: 8px;
                font-size: 17px;
            }}
            QMenu::item {{
                min-width: 224px;
                min-height: 44px;
                padding: 9px 26px 9px 18px;
                margin: 2px 4px;
                border-radius: 10px;
                background-color: transparent;
            }}
            QMenu::item:selected {{
                background-color: rgba(0, 103, 192, 30);
                color: rgb(0, 71, 138);
            }}
            QMenu::icon {{
                padding-left: 12px;
            }}
            QMenu::separator {{
                height: 1px;
                margin: 6px 14px;
                background: rgba(17,24,32,20);
            }}
            """
        )
        self._add_tray_action(menu, FluentIcon.SETTING, "设置", self.show_settings)
        self._add_tray_action(menu, FluentIcon.HISTORY, "历史记录", self.show_history)
        menu.addSeparator()
        label = "隐藏窗口" if self.window.isVisible() else "显示窗口"
        icon = FluentIcon.HIDE if self.window.isVisible() else FluentIcon.VIEW
        self._add_tray_action(menu, icon, label, self.toggle_window)
        self._add_tray_action(menu, FluentIcon.POWER_BUTTON, "退出", self.quit)
        self.tray_menu = menu
        # The tray icon lives at the bottom-right of the screen, so dropping the menu downward
        # from the cursor pushed it off the bottom edge / too low. Instead anchor the menu's
        # bottom-right corner near the cursor so it opens up-and-to-the-left, and clamp it to
        # the screen work area so it is never clipped.
        menu.ensurePolished()
        size = menu.sizeHint()
        screen = self.qt.screenAt(pos) or self.qt.primaryScreen()
        area = screen.availableGeometry()
        x = pos.x() - size.width() - 6
        y = pos.y() - size.height()
        x = max(area.left() + 4, min(x, area.right() - size.width() - 4))
        y = max(area.top() + 4, min(y, area.bottom() - size.height() - 4))
        menu.exec(QPoint(x, y))

    def _add_tray_action(self, menu: QMenu, icon: FluentIcon, text: str, callback) -> None:
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
        self.settings_window.sync_from_state()
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
            self.window._wheel_hook.uninstall()
        except Exception:
            pass
        try:
            self.window.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    app = LiquidMemoApp()
    raise SystemExit(app.run())
