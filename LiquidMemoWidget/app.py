from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

sys.dont_write_bytecode = True
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QThreadPool,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QPainter, QPixmap
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
    ToolTipPosition,
    setTheme,
    Theme,
)

from skin_editor import load_skin_pixmap, mean_luminance as image_mean_luminance
from state_store import CalendarEvent, Settings, StateStore, TodoItem, parse_ddl, utc_now
from wheel_hook import GlobalWheelHook
from window_layer import (
    HTBOTTOM,
    HTCAPTION,
    HTCLIENT,
    HTTRANSPARENT,
    WM_ENTERSIZEMOVE,
    WM_EXITSIZEMOVE,
    WM_NCLBUTTONDBLCLK,
    WM_NCHITTEST,
    apply_tool_window,
    begin_system_move,
    detach_from_parent,
    set_rounded_corners,
    set_topmost,
    set_window_exclude_from_capture,
)
from qframelesswindow.windows.window_effect import WindowsWindowEffect
from ui_common import (
    FONT_STACK_QSS,
    InfoToolTipFilter,
    POPUP_INPUT_FONT_PX,
    SETTING_CONTROL_FONT_PX,
    SETTING_ROW_TITLE_FONT_PX,
    SETTING_STATUS_FONT_PX,
    SETTING_TITLE_FONT_PX,
    add_soft_shadow,
    best_contrast_color,
    css_rgba,
    enlarge_control_font,
    mixed_font,
    qcolor,
    relative_luminance,
    scaled_dialog_size,
    set_label_font,
    tray_icon,
)
from settings_ui import SettingsWindow
from update_ui import UpdateManager
from calendar_manager import CalendarManager
from notify_manager import NotificationManager
from startup import reconcile_startup
from floating_launcher import FloatingModeController
from surprise_mode import SurpriseService, SURPRISE_TEXT


MIN_WIDTH = 320
MAX_WIDTH = 720
MAX_WIDTH_RATIO = 0.52
MIN_HEIGHT = 320
MAX_HEIGHT_RATIO = 0.7
RESIZE_MARGIN = 6
SURPRISE_MIN_WIDTH = 400
# A vertical scrollbar lives inside the list viewport. Reserve its full painted width in the
# collapsed layout even before Qt decides whether it is needed; otherwise adding the special
# pinned row can make the bar appear and steal pixels from already-fixed DDL/calendar columns.
SCROLLBAR_LAYOUT_RESERVE = 12
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
# Deadline highlighting: a parsed DDL already past "now" turns red; one due within the
# user-configured nearHighlightDays turns amber. Unparseable or done items stay normal.
DDL_OVERDUE_COLOR = "#FF3B30"
DDL_NEAR_COLOR = "#FF9500"
# Placeholder shown in an empty (but visible) DDL cell, signalling it is click-to-set.
DDL_EMPTY_HINT = "＋"
# Calendar subscription ("日程" group).
CALENDAR_HEADER_HEIGHT = 30
_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
# Top/bottom breathing room inside the scrollable list, so the first and last rows are never
# flush against the scroll viewport edge (near the window's rounded top/bottom) and get visually
# clipped. Counted in the window-height budget so it never squeezes.
LIST_EDGE_PAD = 7


def format_event_time(event: "CalendarEvent") -> str:
    """Compact local time shown in the calendar event's time column."""
    deadline = parse_ddl(event.start)
    if deadline is None:
        return event.start
    weekday = _WEEKDAY_CN[deadline.weekday()]
    if event.allDay:
        return f"{deadline.strftime('%m-%d')} 周{weekday} 全天"
    return f"{deadline.strftime('%m-%d')} 周{weekday} {deadline.strftime('%H:%M')}"

# Edge auto-hide ("dock"): when the window is dragged within DOCK_THRESHOLD px of a work-area
# edge (left/right/top) it snaps flush and, once the cursor leaves, slides off-screen leaving a
# DOCK_PEEK-px strip. Moving the cursor back onto that strip slides it out again.
WM_MOUSEMOVE = 0x0200
DOCK_THRESHOLD = 18
DOCK_PEEK = 5
DOCK_HIDE_DELAY_MS = 600
DOCK_SLIDE_MS = 200
DOCK_POLL_MS = 120


def install_tooltip(widget: QWidget) -> None:
    """Show the widget's tooltip as a readable qfluentwidgets bubble instead of a native
    QToolTip. A native tooltip here inherits the owning row/button's text color (white on a
    dark desktop) and an app-level `QToolTip` QSS rule cannot reliably override it, so the
    bubble renders unreadable (black-on-black / white-on-white). The bubble sets its own
    dark text + light background and reads the widget's existing setToolTip() text."""
    widget.installEventFilter(InfoToolTipFilter(widget, showDelay=400, position=ToolTipPosition.TOP))


def location_line_height() -> int:
    """Extra height a row gains from its dim second '📍 location' line (the 10pt label plus the
    2px text-column spacing). Shared by row layout and the window height pre-calc so they agree."""
    return QFontMetrics(mixed_font(10)).height() + 2


_text_measure_label: QLabel | None = None


def wrapped_text_height(text: str, width: int) -> int:
    """Height a 12pt word-wrapped title label needs to show `text` in full at `width`.

    Measured through an off-screen QLabel configured exactly like the real title labels
    (TodoTextLabel: PlainText, wordWrap), so the value matches what the label actually
    renders. QFontMetrics.boundingRect with TextWrapAnywhere disagreed with QLabel's
    word-boundary wrapping and underestimated tall rows, clipping the first/last line."""
    global _text_measure_label
    label = _text_measure_label
    if label is None:
        label = QLabel()
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setFont(mixed_font(12))
        _text_measure_label = label
    label.setText(text)
    height = label.heightForWidth(max(90, width))
    if height <= 0:  # QLabel returns -1 if it somehow has no height-for-width
        height = QFontMetrics(mixed_font(12)).boundingRect(
            QRect(0, 0, max(90, width), 2000), Qt.TextWordWrap, text
        ).height()
    return height


class RoundButton(QPushButton):
    def __init__(self, text: str, size: int = 34, parent: QWidget | None = None, tone: str = "neutral") -> None:
        super().__init__(text, parent)
        self.tone = tone
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.apply_surprise_theme(False)
        install_tooltip(self)

    def apply_surprise_theme(self, active: bool) -> None:
        palette = {
            "neutral": ("rgba(255,255,255,88)", "rgba(255,255,255,132)", "rgba(255,255,255,175)", "#111820", "rgba(255,255,255,150)"),
            "add": ("rgba(33,150,243,196)", "rgba(33,150,243,225)", "rgba(18,121,218,235)", "white", "rgba(255,255,255,170)"),
            "hide": ("rgba(255,255,255,105)", "rgba(255,255,255,150)", "rgba(255,255,255,190)", "#30404C", "rgba(255,255,255,150)"),
            "confirm": ("rgba(45,184,130,205)", "rgba(45,184,130,235)", "rgba(24,146,101,242)", "white", "rgba(255,255,255,170)"),
        }
        if active:
            palette["add"] = ("rgba(232,93,147,210)", "rgba(241,119,165,235)", "rgba(201,65,119,242)", "white", "rgba(255,255,255,190)")
            palette["confirm"] = palette["add"]
        bg, hover, pressed, color, border = palette.get(self.tone, palette["neutral"])
        radius = self.width() // 2
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
        install_tooltip(self)
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
        self.settings = settings
        self.parent_window = parent_window
        self._drag_start: QPoint | None = None
        self._dragging = False
        self._style_signature: tuple[str, bool, bool, str] | None = None
        self._halo: QGraphicsDropShadowEffect | None = None
        self.setMinimumHeight(ROW_HEIGHT)
        self.setObjectName("todoRow")
        self.setCursor(Qt.OpenHandCursor)
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
        # Let a press on the title reach the row so the whole non-control surface can drag.
        self.text.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # Location shows on a dim second line under the title, only when set (📍 …); the column
        # stays single-line otherwise so rows without a location are not taller.
        self.location_label = TodoTextLabel("")
        self.location_label.setFont(mixed_font(10))
        self.location_label.setWordWrap(False)
        self.location_label.setVisible(False)
        self.location_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.addWidget(self.text)
        text_col.addWidget(self.location_label)
        layout.addLayout(text_col, 1)

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
        self.ddl_label.setToolTip(todo.ddl or "点击编辑事项")
        self.ddl_label.setVisible(False)
        self.ddl_label.clicked.connect(lambda: parent_window.edit_todo(todo.id))
        layout.addWidget(self.ddl_label)

        # Style text + ddl together, now that both labels exist.
        self.apply_text_style(parent_window.text_color_for(todo), parent_window.text_needs_halo())

        self.edit_btn = QPushButton("✎")
        self.edit_btn.setFixedSize(30, 30)
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setToolTip("编辑事项（内容 / 地点 / DDL）")
        install_tooltip(self.edit_btn)
        self.edit_btn.setStyleSheet(
            """
            QPushButton {
                border: none;
                border-radius: 15px;
                background: rgba(255,255,255,45);
                font-size: 14px;
            }
            QPushButton:hover { background: rgba(255,255,255,115); }
            QPushButton:pressed { background: rgba(255,255,255,160); }
            """
        )
        self.edit_btn.clicked.connect(lambda: parent_window.edit_todo(todo.id))
        layout.addWidget(self.edit_btn)

        self.urgent = QPushButton("❗")
        self.urgent.setFixedSize(30, 30)
        self.urgent.setCursor(Qt.PointingHandCursor)
        self.urgent.setToolTip("加急并置顶")
        install_tooltip(self.urgent)
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
        if deadline - now <= timedelta(days=self.settings.nearHighlightDays):
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
        self.location_label.setStyleSheet(f"{FONT_STACK_QSS} font-size: 10pt; color: {css_rgba(color, alpha * 0.6)}; {decoration}")
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
        loc = self.todo.location.strip()
        if loc:
            self.location_label.setFixedWidth(text_width)
            loc_metrics = QFontMetrics(self.location_label.font())
            self.location_label.set_full_text(f"📍 {loc}")
            self.location_label.setText(loc_metrics.elidedText(f"📍 {loc}", Qt.ElideRight, text_width))
        self.location_label.setVisible(bool(loc))
        height = wrapped_text_height(self.text.text(), text_width) + (location_line_height() if loc else 0)
        height = max(ROW_HEIGHT, height + 18)
        self.setFixedHeight(height)
        return height

    def _complete_changed(self) -> None:
        self.parent_window.complete_todo(self.todo.id, self.checkbox.isChecked(), self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self._dragging = False
            # Accept the press so this row keeps Qt's implicit mouse grab while the pointer moves
            # across sibling rows; its move/release handlers can then drive the full drag session.
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self._drag_start).manhattanLength()
        if not self._dragging and distance >= QApplication.startDragDistance():
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self.parent_window.begin_todo_reorder(self)
        if self._dragging:
            self.parent_window.move_todo_reorder(self, event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_dragging = self._dragging
        self._drag_start = None
        self._dragging = False
        self.setCursor(Qt.OpenHandCursor)
        if event.button() == Qt.LeftButton and was_dragging:
            self.parent_window.finish_todo_reorder(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)


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
        # Location (from the ICS LOCATION field) on a dim second line, only when present.
        self.location_label = TodoTextLabel("")
        self.location_label.setFont(mixed_font(10))
        self.location_label.setWordWrap(False)
        self.location_label.setVisible(False)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.addWidget(self.text)
        text_col.addWidget(self.location_label)
        layout.addLayout(text_col, 1)

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
        near = timedelta(days=self.parent_window.app.state.settings.nearHighlightDays)
        if start - now <= near:
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
        self.location_label.setStyleSheet(f"{FONT_STACK_QSS} font-size: 10pt; color: {css_rgba(color, alpha * 0.6)}; {decoration}")
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
        loc = self.cal_event.location.strip()
        if loc:
            self.location_label.setFixedWidth(text_width)
            loc_metrics = QFontMetrics(self.location_label.font())
            self.location_label.set_full_text(f"📍 {loc}")
            self.location_label.setText(loc_metrics.elidedText(f"📍 {loc}", Qt.ElideRight, text_width))
        self.location_label.setVisible(bool(loc))
        height = wrapped_text_height(self.text.text(), text_width) + (location_line_height() if loc else 0)
        height = max(ROW_HEIGHT, height + 18)
        self.setFixedHeight(height)
        return height

    def _done_changed(self) -> None:
        self.parent_window.toggle_calendar_event(self.cal_event.key, self.checkbox.isChecked())


class TodoEditorPopup(QDialog):
    """Add or edit a todo: 内容 / 地点(可选) / DDL(可选). Shared by the "+" add flow and the
    per-row pencil edit. Qt.Tool (not Qt.Popup) so the QLineEdits reliably get keyboard focus
    on Windows; the WindowDeactivate handler gives click-outside-to-dismiss."""

    def __init__(self, parent_window: "MemoWindow") -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.parent_window = parent_window
        self._edit_id: str | None = None  # None = add mode, else the todo being edited
        self.setWindowTitle("添加事项")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(460, 132)

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

        outer = QVBoxLayout(self.panel)
        outer.setContentsMargins(18, 14, 14, 14)
        outer.setSpacing(10)
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入事项")
        self.input.returnPressed.connect(self.accept)
        outer.addWidget(self.input)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("地点（可选）")
        self.location_input.returnPressed.connect(self.accept)
        row.addWidget(self.location_input, 1)
        self.ddl_input = QLineEdit()
        self.ddl_input.setPlaceholderText("DDL（可选）")
        self.ddl_input.setFixedWidth(150)
        self.ddl_input.returnPressed.connect(self.accept)
        row.addWidget(self.ddl_input)
        self.ok = RoundButton("✓", 46, tone="confirm")
        self.ok.clicked.connect(self.accept)
        row.addWidget(self.ok)
        outer.addLayout(row)
        surprise = getattr(getattr(parent_window, "app", None), "surprise", None)
        self.apply_surprise_theme(bool(surprise and surprise.active))

    def apply_surprise_theme(self, active: bool) -> None:
        background = "rgba(255,240,246,242)" if active else "rgba(248,252,255,238)"
        field = "rgba(255,255,255,185)" if active else "rgba(255,255,255,150)"
        color = SURPRISE_TEXT if active else "#111820"
        self.panel.setStyleSheet(
            f"QFrame#addPanel {{ {FONT_STACK_QSS} border-radius: 22px; border: 1px solid rgba(255,255,255,170); background: {background}; }}"
            f" QLineEdit {{ {FONT_STACK_QSS} border: 1px solid rgba(255,255,255,145); border-radius: 17px; background: {field}; color: {color}; font-size: {POPUP_INPUT_FONT_PX}px; padding: 9px 14px; selection-background-color: rgba(232,93,147,120); }}"
        )

    def _position(self, point: QPoint, width: int) -> None:
        width = max(420, min(600, width))
        self.setFixedSize(width, 132)
        self.panel.setGeometry(0, 0, self.width(), self.height())
        self.move(point)

    def _show_focused(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, lambda: (self.input.setFocus(Qt.PopupFocusReason), self.input.selectAll()))

    def open_add(self, point: QPoint, width: int) -> None:
        self._edit_id = None
        self.setWindowTitle("添加事项")
        self.input.clear()
        self.location_input.clear()
        self.ddl_input.clear()
        self._position(point, width)
        self._show_focused()

    def open_edit(self, todo_id: str, text: str, location: str, ddl: str, point: QPoint, width: int) -> None:
        self._edit_id = todo_id
        self.setWindowTitle("编辑事项")
        self.input.setText(text)
        self.location_input.setText(location)
        self.ddl_input.setText(ddl)
        self._position(point, width)
        self._show_focused()

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
        location = self.location_input.text().strip()
        ddl = self.ddl_input.text().strip()
        if text:
            if self._edit_id is not None:
                self.parent_window.update_todo(self._edit_id, text, location, ddl)
            else:
                self.parent_window.add_todo(text, location, ddl)
        self._edit_id = None
        self.hide()


class HistoryWindow(QDialog):
    def __init__(self, app: "LiquidMemoApp") -> None:
        super().__init__(None, Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.app = app
        self.setWindowTitle("历史记录")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(scaled_dialog_size(620, 620))
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
        layout.setContentsMargins(38, 34, 38, 38)
        layout.setSpacing(24)

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
        enlarge_control_font(clear)
        header.addWidget(clear)
        close = PrimaryPushButton("完成", self.frame, FluentIcon.ACCEPT)
        close.clicked.connect(self.hide)
        enlarge_control_font(close)
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
        self.apply_surprise_theme(getattr(getattr(self.app, "surprise", None), "active", False))

    def apply_surprise_theme(self, active: bool) -> None:
        background = "qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #FFF8FB,stop:1 #FFE3EC)" if active else "rgb(246,248,252)"
        self.frame.setStyleSheet(
            f"QFrame#fluentPanel {{ {FONT_STACK_QSS} background: {background}; border: 1px solid rgba(255,255,255,185); border-radius: 22px; }}"
        )

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
            set_label_font(title, SETTING_ROW_TITLE_FONT_PX)
            detail = QLabel("勾选完成并归档后的待办会显示在这里。")
            detail.setAlignment(Qt.AlignCenter)
            detail.setStyleSheet(
                f"{FONT_STACK_QSS} color: rgba(17,24,32,135); font-size: {SETTING_STATUS_FONT_PX}px;"
            )
            empty_layout.addWidget(title)
            empty_layout.addWidget(detail)
            self.list.addWidget(empty)
            self.list.addStretch()
            return

        for todo in reversed(self.app.state.history[-30:]):
            card = CardWidget()
            row_layout = QHBoxLayout(card)
            row_layout.setContentsMargins(24, 18, 20, 18)
            row_layout.setSpacing(18)

            text_layout = QVBoxLayout()
            text_layout.setSpacing(4)
            label = BodyLabel(todo.text)
            label.setWordWrap(True)
            set_label_font(label, SETTING_CONTROL_FONT_PX)
            meta = QLabel("已完成" if not todo.completedAt else f"完成于 {todo.completedAt[:10]}")
            meta.setStyleSheet(
                f"{FONT_STACK_QSS} color: rgba(17,24,32,130); font-size: {SETTING_STATUS_FONT_PX}px;"
            )
            text_layout.addWidget(label)
            text_layout.addWidget(meta)
            row_layout.addLayout(text_layout, 1)

            restore = PushButton("恢复", card, FluentIcon.RETURN)
            restore.clicked.connect(lambda _=False, todo_id=todo.id: self._restore(todo_id))
            enlarge_control_font(restore)
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


class AcrylicSkin:
    """Frosted-glass skin: the window is a translucent DWM acrylic surface (rounded by DWM) with
    no GPU screen capture and no effect chain — so the whole window IS the surface
    (geometry_scale = 1.0) and content fills it with only a small corner margin."""

    kind = "acrylic"
    geometry_scale = 1.0
    corner_margin = 14

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


class ImageSkin:
    """User image-background skin: a static, cover-scaled image painted below the content layer.
    Like AcrylicSkin there is no GPU screen capture and no effect chain — the window IS the
    surface (geometry_scale = 1.0, content fills it), rounded by DWM. `image_path` is the
    resolved PNG under state_store.skins_dir(); a missing image makes _make_skin fall back to
    AcrylicSkin so this always points at a readable file when live."""

    kind = "image"
    geometry_scale = 1.0
    corner_margin = 14

    def __init__(self, image_path: "Path | None" = None) -> None:
        self.image_path = image_path

    def vertical_padding(self, height: int) -> int:
        return 0

    def horizontal_padding(self, width: int) -> int:
        return 0


class _ImageBackground(QWidget):
    """Cover-scaled static image painted below the (capture-excluded) content layer for the image
    skin. Transparent to mouse so the window's native hit-testing still governs clicks; the DWM
    rounded corners clip it to shape, exactly as the acrylic frost is clipped."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._pixmap = QPixmap()

    def set_image(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap if (pixmap is not None and not pixmap.isNull()) else QPixmap()
        self.update()

    def paintEvent(self, event) -> None:
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self.rect()
        # Cover: scale to fill, center-crop the overflow (no distortion, no blank bars).
        scaled = self._pixmap.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (scaled.width() - rect.width()) // 2
        y = (scaled.height() - rect.height()) // 2
        painter.drawPixmap(rect, scaled, QRect(x, y, rect.width(), rect.height()))


class MemoWindow(QWidget):
    def __init__(self, app: "LiquidMemoApp") -> None:
        super().__init__()
        self.app = app
        self.skin = self._make_skin(app.state.settings.skin)
        # Tracks which rendering mode is currently live so apply_settings only performs the
        # acrylic<->image transition when the skin actually changes.
        self._active_skin_kind: str | None = None
        self._window_effect = WindowsWindowEffect(self)
        self._acrylic_applied = False
        self._acrylic_signature: str | None = None
        # Image-skin (static background) state. _image_bg paints the cover-scaled image below the
        # content layer; _image_luminance drives the deterministic dark/light text choice.
        self._image_bg: _ImageBackground | None = None
        self._image_pixmap: QPixmap | None = None
        self._image_luminance: float = 1.0
        self.setWindowTitle("桌面备忘")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)
        # All interactive content lives in this transparent child layer, kept out of any screen
        # capture by protect_content_layer(); the window itself only carries the frost / image
        # surface. (Previously provided by the D3D base class; recreated here directly.)
        self.container = QWidget(self)
        self.container.setStyleSheet("background: transparent;")
        self.container.setAttribute(Qt.WA_TranslucentBackground)
        self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._rows: dict[str, TodoRow] = {}
        self._event_rows: dict[str, CalendarRow] = {}
        self._calendar_header: QLabel | None = None
        self._surprise_row: QWidget | None = None
        # Expanded mode grows the window to fit all content (no height clamp, no scrollbar, no
        # elided text); collapsed mode keeps the default clamp + scroll behavior.
        self._expanded = False
        self._shown_once = False
        self._window_layer_applied = False
        self._is_window_moving = False
        self._reorder_row: TodoRow | None = None
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
        self.hide_button.clicked.connect(self.app.hide_memo_window)
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
        self.list_layout.setContentsMargins(0, LIST_EDGE_PAD, 0, LIST_EDGE_PAD)
        self.list_layout.setSpacing(0)
        self.scroll.setWidget(self.list_widget)
        self.layout.addWidget(self.scroll, 1)

        self.empty = QLabel("暂无待办")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: rgba(17,24,32,120); font-size: 15px;")
        self.layout.addWidget(self.empty, 1)

        self.add_popup = TodoEditorPopup(self)

    def protect_content_layer(self) -> None:
        # Keep the content layer above the surface and excluded from any screen capture (so
        # screenshots / recordings of the desktop don't grab the widget's own text).
        if self.container:
            self.container.raise_()
        set_window_exclude_from_capture(int(self.winId()), exclude=True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
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

    def cleanup(self) -> None:
        # Called on app shutdown. No GPU/capture resources to release anymore (the D3D engine is
        # gone); just stop the dock timers and any in-flight slide.
        self._dock_poll.stop()
        self._hide_timer.stop()
        self._cancel_slide()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self._shown_once:
            # During a dock slide the window is mid-animation toward an off-screen position; skip
            # the per-move save work (and don't persist off-screen coordinates).
            if self._dock_animating:
                return
            # In floating-launcher mode the panel is an ephemeral popover anchored to the
            # launcher. Do not overwrite the user's normal/edge-mode window position.
            if self.app.state.settings.windowMode == "floatingLauncher":
                return
            self.app.state.window.x = self.x()
            self.app.state.window.y = self.y()
            if self._is_window_moving:
                return
            QTimer.singleShot(0, self.protect_content_layer)
            self.app.save_later()

    def resizeEvent(self, event) -> None:
        # The container fills the window; the image layer (a sibling child) tracks it too so the
        # static background always covers the window.
        super().resizeEvent(event)
        if self.container is not None:
            self.container.setGeometry(0, 0, self.width(), self.height())
        if self._image_bg is not None:
            self._image_bg.setGeometry(0, 0, self.width(), self.height())
        if (
            self._is_window_moving
            and not self._expanded
            and event.oldSize().height() != event.size().height()
        ):
            # Programmatic content-fit resizes happen outside the native size/move loop, so only
            # a real bottom-edge drag reaches this branch and becomes the user's saved height.
            self.app.state.window.manualHeight = self.height()
            self.app.state.window.height = self.height()
            self.app.save_later()

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
                if (
                    not self._expanded
                    and 0 <= local.x() < self.width()
                    and self.height() - RESIZE_MARGIN <= local.y() <= self.height()
                ):
                    return True, HTBOTTOM
                if self.drag_handle.isVisible() and self._rect_for(self.drag_handle).contains(local):
                    return True, HTCAPTION
                if self._point_over_todo_row(local):
                    return True, HTCLIENT
                if self._is_interactive_point(local):
                    return True, HTCLIENT
                if self.app.state.settings.layerMode == "alwaysVisibleClickThrough":
                    return True, HTTRANSPARENT
            if msg.message == WM_NCLBUTTONDBLCLK and int(msg.wParam) == HTBOTTOM:
                self.app.state.window.manualHeight = None
                self.app.save_later()
                self.refresh()
                return True, 0
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
            # edit_btn (✎) opens the editor and ddl_label (the DDLCell) also opens it on click;
            # the time cell on calendar rows is display-only, so only their checkbox is interactive.
            widgets.extend([row.checkbox, row.urgent, row.ddl_label, row.edit_btn])
        for row in self._event_rows.values():
            widgets.append(row.checkbox)
        if self._surprise_row is not None:
            widgets.extend([self._surprise_row.checkbox, self._surprise_row.draw])
        # Wheel scrolling over the list is handled by the global wheel hook (see
        # _on_global_wheel). Todo rows are handled separately by _point_over_todo_row; outside
        # those rows, only these discrete controls receive clicks.
        return any(widget.isVisible() and self._rect_for(widget).adjusted(-4, -4, 4, 4).contains(point) for widget in widgets)

    def _point_over_todo_row(self, point: QPoint) -> bool:
        """Todo rows receive Qt mouse events for reordering; calendar rows stay click-through."""
        return any(row.isVisible() and self._rect_for(row).contains(point) for row in self._rows.values())

    def begin_system_move(self) -> None:
        self._begin_window_move()
        begin_system_move(int(self.winId()))
        QTimer.singleShot(0, self._end_window_move)

    def _begin_window_move(self) -> None:
        if self._is_window_moving:
            return
        self._is_window_moving = True
        # The frost / image surface follows the window natively — nothing to spin up on move.

    def _end_window_move(self) -> None:
        if not self._is_window_moving:
            return
        self._is_window_moving = False
        self.app.state.window.x = self.x()
        self.app.state.window.y = self.y()
        self.app.save_later()
        self.protect_content_layer()
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
        if self.app.state.settings.windowMode != "edgeHide" or not self.isVisible():
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
            or self._reorder_row is not None
            or self.add_popup.isVisible()
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
        if getattr(self.app, "surprise", None) is not None and self.app.surprise.active:
            return AcrylicSkin()
        if skin_name.startswith("image:"):
            skin_id = skin_name[len("image:"):]
            custom = next((s for s in self.app.state.settings.customSkins if s.id == skin_id), None)
            if custom is not None and custom.image_path().exists():
                return ImageSkin(custom.image_path())
            return AcrylicSkin()  # missing/deleted image -> safe fallback to the frost skin
        return AcrylicSkin()

    def apply_settings(self, refresh_rows: bool = False) -> None:
        settings = self.app.state.settings
        # _make_skin resolves a missing image skin down to AcrylicSkin, so branch on the resolved
        # skin's kind (not the raw "image:<id>" string) for both dispatch and change detection —
        # otherwise "image" never equals "image:<id>" and skin_changed misfires.
        self.skin = self._make_skin(settings.skin)
        new_kind = self.skin.kind
        skin_changed = self._active_skin_kind not in (None, new_kind)
        if new_kind == "image":
            self._apply_image_mode()
        else:
            self._apply_acrylic_mode()
        # Frost and image use the same full-fill geometry, but switching between them swaps the
        # background layer, so a skin change still needs a relayout even if not explicitly asked.
        if refresh_rows or skin_changed:
            self.refresh()
        self.protect_content_layer()
        self.apply_window_layer()
        if settings.windowMode != "edgeHide":
            self._undock()

    def _apply_acrylic_mode(self) -> None:
        # Frosted mode: the window is a translucent DWM acrylic surface; the image layer (if any)
        # is hidden so the frost shows through.
        self._active_skin_kind = "acrylic"
        self._hide_image_bg()
        self._apply_acrylic_effect()
        self.apply_text_colors()

    def _ensure_image_bg(self) -> "_ImageBackground":
        if self._image_bg is None:
            self._image_bg = _ImageBackground(self)
            self._image_bg.setGeometry(0, 0, self.width(), self.height())
        return self._image_bg

    def _hide_image_bg(self) -> None:
        if self._image_bg is not None:
            self._image_bg.hide()

    def _apply_image_mode(self) -> None:
        # Static image surface: _image_bg paints the cover-scaled image below the
        # (capture-excluded) content layer, and DWM rounds the window corners.
        self._active_skin_kind = "image"
        self._remove_acrylic()
        path = getattr(self.skin, "image_path", None)
        pixmap = load_skin_pixmap(path) if path is not None else None
        self._image_pixmap = pixmap
        self._image_luminance = image_mean_luminance(pixmap) if pixmap is not None else 1.0
        image_bg = self._ensure_image_bg()
        image_bg.set_image(pixmap)
        image_bg.setGeometry(0, 0, self.width(), self.height())
        image_bg.show()
        image_bg.lower()  # beneath the content layer; container is raised back on top below
        if self.container:
            self.container.raise_()
        set_rounded_corners(int(self.winId()), True)
        self.apply_text_colors()

    def _apply_acrylic_effect(self) -> None:
        settings = self.app.state.settings
        tint = qcolor("#FFDDE8" if self.app.surprise.active else settings.windowTint, "#F2F4F7")
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
        # Urgent items stay pinned; within each group the user's drag order is authoritative.
        return (not item.urgent, item.order, item.createdAt)

    def _todo_rows_in_layout(self) -> list[TodoRow]:
        rows: list[TodoRow] = []
        for index in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(index).widget()
            if isinstance(widget, TodoRow):
                rows.append(widget)
        return rows

    def begin_todo_reorder(self, row: TodoRow) -> None:
        if row not in self._todo_rows_in_layout():
            return
        self._reorder_row = row
        row.raise_()

    def move_todo_reorder(self, row: TodoRow, global_pos: QPoint) -> None:
        if self._reorder_row is not row:
            return
        rows = self._todo_rows_in_layout()
        if row not in rows:
            return
        cursor_y = self.list_widget.mapFromGlobal(global_pos).y()
        others = [candidate for candidate in rows if candidate is not row]
        target_index = sum(cursor_y >= candidate.geometry().center().y() for candidate in others)
        if target_index == rows.index(row):
            return
        self.list_layout.removeWidget(row)
        self.list_layout.insertWidget(target_index, row)
        self.list_layout.activate()
        row.raise_()

    def finish_todo_reorder(self, row: TodoRow) -> None:
        if self._reorder_row is not row:
            return
        self._reorder_row = None
        # Assign one monotonic sequence to the visual list. refresh() immediately re-pins urgent
        # rows while preserving the resulting manual order inside each urgent/non-urgent group.
        for order, ordered_row in enumerate(self._todo_rows_in_layout()):
            ordered_row.todo.order = order
        self.app.save()
        self.refresh()

    def refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()
        self._event_rows.clear()
        self._calendar_header = None
        self._surprise_row = self.app.surprise.make_row(self.content)

        active = sorted(self.app.state.todos, key=self._todo_sort_key)
        events = self._visible_calendar_events()
        has_surprise = self._surprise_row is not None
        self.scroll.setVisible(bool(active) or bool(events) or has_surprise)
        self.empty.setVisible(not active and not events and not has_surprise)

        if self._surprise_row is not None:
            self.list_layout.addWidget(self._surprise_row)

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
        controller = getattr(self.app, "floating", None)
        if controller is not None:
            controller.update_status()

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

    def _image_text_color(self) -> QColor:
        # Image mode has no live capture to sample, so contrast is deterministic: soft dark text
        # on a bright image, soft light text on a dark one (reusing the acrylic text palette).
        dark, light = qcolor(ACRYLIC_TEXT_DARK), qcolor(ACRYLIC_TEXT_LIGHT)
        return dark if self._image_luminance > 0.55 else light

    def _normal_text_color(self) -> QColor:
        settings = self.app.state.settings
        if self.app.surprise.active:
            return qcolor(SURPRISE_TEXT)
        if settings.skin.startswith("image:"):
            # Image surfaces honor a manual color choice; otherwise pick by image luminance.
            if settings.fontColorMode == "manual":
                return qcolor(settings.todoTextColor)
            return self._image_text_color()
        return self._acrylic_text_color()  # frost: deterministic by tint luminance

    def text_color_for(self, todo: TodoItem) -> QColor:
        if todo.urgent:
            return qcolor(self.app.state.settings.urgentTextColor, "#FF0000")
        return self._normal_text_color()

    def text_needs_halo(self) -> bool:
        # Both remaining skins are even, static surfaces with deterministic text — never any halo.
        # (Kept as a method because TodoRow/CalendarRow constructors call it.)
        return False

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
        # `normal` already resolves to the manual/acrylic/image color, so it is the right base
        # for the empty-state label in every skin and font mode.
        self.empty.setStyleSheet(f"{FONT_STACK_QSS} color: {css_rgba(normal, 0.58)}; font-size: 15px;")

    def _resize_for_content(self, active: list[TodoItem], events: list[CalendarEvent] | None = None) -> None:
        events = events or []
        screen = QApplication.primaryScreen().availableGeometry()
        show_todo_ddl = any(todo.ddl for todo in active)
        # The time column is shared by todo DDLs and event times; show it (and reserve width)
        # whenever either group needs it, sizing to the widest string across both for alignment.
        column_active = show_todo_ddl or bool(events)
        ddl_width = self._time_column_width(active, events, self._expanded) if column_active else 0
        ddl_reserve = (ddl_width + DDL_SEP_WIDTH + DDL_COL_GAPS) if column_active else 0
        scrollbar_reserve = 0 if self._expanded else SCROLLBAR_LAYOUT_RESERVE
        trailing_reserve = ddl_reserve + scrollbar_reserve
        width = self._adaptive_width(active, events, screen, trailing_reserve)
        text_width = self._text_width_for_window(width, trailing_reserve)
        content_height = sum(self._measure_row_height(todo.text, text_width, todo.location) for todo in active)
        if self._surprise_row is not None:
            content_height += self._surprise_row.height()
        if events:
            # Calendar rows render "📅 {summary}", which wraps (and grows taller than ROW_HEIGHT)
            # for long titles — measure them like todos so the window height isn't underestimated
            # (which previously left expanded mode hiding the scrollbar yet still clipping rows).
            content_height += CALENDAR_HEADER_HEIGHT
            content_height += sum(self._measure_row_height(f"📅 {event.summary}", text_width, event.location) for event in events)
        content_height = max(content_height, ROW_HEIGHT)
        # The scrollable list adds top/bottom breathing room around the rows; budget it here so
        # the window grows to keep the first/last rows fully visible instead of squeezing them.
        content_height += 2 * LIST_EDGE_PAD
        # Window height = top block + rows + corner margin (scale is 1.0 for both static skins,
        # kept here so the formula still reads generally).
        scale = self.skin.geometry_scale
        corner = self.skin.corner_margin
        needed = MEMO_TOP_BLOCK + content_height + 2 * corner
        wanted = max(MIN_HEIGHT, math.ceil(needed / scale))
        screen_cap = max(MIN_HEIGHT, screen.height() - 64)
        self.setFixedWidth(width)
        if self._expanded:
            # Grow to fit everything; only the physical screen limits us. Hide the scrollbar
            # when it all fits, but fall back to AsNeeded if content still exceeds the screen.
            height = min(wanted, screen_cap)
            fits = wanted <= screen_cap
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if fits else Qt.ScrollBarAsNeeded)
            self.setFixedHeight(height)
        else:
            auto_height = min(wanted, int(screen.height() * MAX_HEIGHT_RATIO), screen_cap)
            manual_height = self.app.state.window.manualHeight
            try:
                manual_height = int(manual_height) if manual_height is not None else None
            except (TypeError, ValueError):
                manual_height = None
            height = max(MIN_HEIGHT, min(manual_height, screen_cap)) if manual_height is not None else auto_height
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            # Width remains content-driven and fixed, but the native HTBOTTOM edge may resize
            # height anywhere inside the usable screen. resizeEvent persists only user drags.
            self.setMinimumHeight(MIN_HEIGHT)
            self.setMaximumHeight(screen_cap)
            if self.height() != height:
                self.resize(width, height)

        # Inset the content. Both skins fill the window (geometry_scale = 1.0 → vertical/horizontal
        # padding are 0), so this collapses to OUTER_X horizontally and the corner margin vertically.
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
        controller = getattr(self.app, "floating", None)
        if controller is not None:
            controller.reposition_panel()
        if self._dock_edge is not None:
            # Content resized while docked: re-pin to the (recomputed) dock position so the peek
            # strip and slide geometry stay correct for the new size.
            self._reposition_dock()

    def _adaptive_width(self, active: list[TodoItem], events: list[CalendarEvent], screen: QRect, ddl_reserve: int = 0) -> int:
        minimum = SURPRISE_MIN_WIDTH if getattr(self.app.surprise, "active", False) else MIN_WIDTH
        if not active and not events:
            return minimum
        metrics = QFontMetrics(mixed_font(12))
        text_widths = [metrics.horizontalAdvance(todo.text) for todo in active]
        text_widths += [metrics.horizontalAdvance(f"📅 {event.summary}") for event in events]
        longest = max(text_widths) if text_widths else 0
        chrome = OUTER_X * 2 + 12 + 18 + 30 + 28 + 24 + 40 + ddl_reserve  # +40: 编辑✎按钮 + 间距
        max_width = min(MAX_WIDTH, int(screen.width() * MAX_WIDTH_RATIO), screen.width() - 64)
        return max(minimum, min(max_width, longest + chrome))

    def _text_width_for_window(self, width: int, ddl_reserve: int = 0) -> int:
        # Must mirror _adaptive_width's chrome (incl. the +40 编辑✎按钮 reserve); otherwise the
        # title label is pinned wider than the row can hold and pushes the trailing ❗ button off
        # the right edge, where it clips out of view.
        return max(90, width - (OUTER_X * 2 + 12 + 18 + 30 + 28 + 12 + 40) - ddl_reserve)

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

    def _measure_row_height(self, text: str, text_width: int, location: str = "") -> int:
        # Mirror TodoRow/CalendarRow.apply_text_width so the window height pre-calc matches the
        # rows' actual heights (incl. the optional 📍 location second line).
        height = wrapped_text_height(text, text_width) + (location_line_height() if location.strip() else 0)
        return max(ROW_HEIGHT, height + 18)

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

    def _popup_position(self, popup_width: int, anchor: QPoint, popup_height: int = 132) -> QPoint:
        screen = QApplication.primaryScreen().availableGeometry()
        x = min(max(anchor.x(), screen.left() + 12), screen.right() - popup_width - 12)
        y = anchor.y()
        if y + popup_height > screen.bottom() - 12:
            y = anchor.y() - popup_height - 12
        y = min(max(y, screen.top() + 12), screen.bottom() - popup_height - 12)
        return QPoint(x, y)

    def show_add_popup(self) -> None:
        popup_width = max(420, min(600, self.width() + 56))
        anchor = QPoint(self.x() + (self.width() - popup_width) // 2, self.y() + self.height() + 10)
        self.add_popup.open_add(self._popup_position(popup_width, anchor), popup_width)

    def add_todo(self, text: str, location: str = "", ddl: str = "") -> None:
        next_order = max([todo.order for todo in self.app.state.todos] + [0]) + 1
        self.app.state.todos.append(
            TodoItem(id=str(uuid4()), text=text, ddl=ddl, location=location, order=next_order)
        )
        self.app.save()
        self.refresh()

    def edit_todo(self, todo_id: str) -> None:
        todo = next((item for item in self.app.state.todos if item.id == todo_id), None)
        if todo is None:
            return
        popup_width = max(420, min(600, self.width() + 56))
        row = self._rows.get(todo_id)
        if row is not None:
            anchor = row.edit_btn.mapToGlobal(QPoint(0, row.edit_btn.height() + 6))
        else:
            anchor = QPoint(self.x(), self.y() + self.height() + 10)
        self.add_popup.open_edit(
            todo_id, todo.text, todo.location, todo.ddl,
            self._popup_position(popup_width, anchor), popup_width,
        )

    def update_todo(self, todo_id: str, text: str, location: str, ddl: str) -> None:
        todo = next((item for item in self.app.state.todos if item.id == todo_id), None)
        if todo is None:
            return
        if (todo.text, todo.location, todo.ddl) == (text, location, ddl):
            return
        todo.text = text
        todo.location = location
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

    def apply_surprise_theme(self, active: bool) -> None:
        self._acrylic_signature = None
        for button in (self.add_button, self.hide_button, self.expand_button):
            button.apply_surprise_theme(active)
        self.apply_settings(refresh_rows=True)
        self.add_popup.apply_surprise_theme(active)


class LiquidMemoApp:
    def __init__(self) -> None:
        self.qt = QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        setTheme(Theme.LIGHT)
        self.qt.setFont(mixed_font(10))
        self.qt.setWindowIcon(tray_icon())
        # Tooltips are rendered as qfluentwidgets bubbles via install_tooltip(); a native
        # QToolTip here inherits the owning widget's (white) text color and styling it through
        # this app-level `*`/QToolTip rule is unreliable, so we don't try.
        self.qt.setStyleSheet(f"* {{ {FONT_STACK_QSS} }}")
        self.store = StateStore()
        self.state = self.store.load()
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save)
        self.surprise = SurpriseService(self)
        self.window = MemoWindow(self)
        self.settings_window = SettingsWindow(self)
        self.history_window = HistoryWindow(self)
        self.calendar = CalendarManager(self)
        self.notifier = NotificationManager(self)
        self.updater = UpdateManager(self)
        self.floating = FloatingModeController(self)
        self.surprise.bind_ui()
        self.tray_menu: QMenu | None = None
        self.tray = QSystemTrayIcon(tray_icon())
        self.tray.setToolTip("桌面备忘")
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.qt.aboutToQuit.connect(self.shutdown)

    def run(self) -> int:
        # Re-claim the launch-at-login entry for this exe if a different build (e.g. the
        # portable copy, before this one was installed) had left it pointing elsewhere.
        reconcile_startup()
        # The mode controller decides whether startup shows the memo itself or only the launcher.
        self.floating.start()
        # Kick off the first calendar sync once the event loop is about to run.
        QTimer.singleShot(0, self.calendar.start)
        # Start the reminder scan after the window/state have settled.
        QTimer.singleShot(2000, self.notifier.start)
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
        menu_bg = "rgb(255,240,246)" if self.surprise.active else "rgb(251,252,254)"
        menu_selected = "rgba(232,93,147,42)" if self.surprise.active else "rgba(0,103,192,30)"
        menu_selected_text = SURPRISE_TEXT if self.surprise.active else "rgb(0,71,138)"
        menu.setStyleSheet(
            f"""
            QMenu {{
                {FONT_STACK_QSS}
                background-color: {menu_bg};
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
                background-color: {menu_selected};
                color: {menu_selected_text};
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
        surfaces_visible = self.floating.surfaces_visible()
        label = "隐藏悬浮窗" if surfaces_visible else "显示悬浮窗"
        if self.state.settings.windowMode != "floatingLauncher":
            label = "隐藏窗口" if surfaces_visible else "显示窗口"
        icon = FluentIcon.HIDE if surfaces_visible else FluentIcon.VIEW
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
        self.floating.toggle_surfaces()

    def hide_memo_window(self) -> None:
        """The memo's minus button collapses to the launcher in floating mode."""
        if self.state.settings.windowMode == "floatingLauncher":
            self.floating.collapse_panel()
        else:
            self.window.hide()

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

    def quit_for_update(self) -> None:
        """Make the visible app disappear promptly before the detached updater takes over.

        Active QRunnables cannot be cancelled safely, so the helper still has a same-executable
        watchdog for a worker that outlives Qt. Clearing queued work and stopping every manager
        keeps the normal path graceful and avoids waiting on work that has not started yet.
        """
        self.save_timer.stop()
        self.save()
        for manager in (self.calendar, self.notifier, self.surprise, self.floating):
            try:
                manager.stop()
            except Exception:
                pass
        QThreadPool.globalInstance().clear()
        try:
            self.tray.hide()
        except Exception:
            pass
        for widget in self.qt.topLevelWidgets():
            widget.hide()
        self.qt.quit()

    def shutdown(self) -> None:
        self.save()
        try:
            self.calendar.stop()
            self.notifier.stop()
            self.surprise.stop()
        except Exception:
            pass
        try:
            self.floating.stop()
        except Exception:
            pass
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
