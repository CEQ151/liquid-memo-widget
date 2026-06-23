"""Animated floating launcher and the controller for the app's three window modes.

The launcher is deliberately a separate tiny top-level window. MemoWindow keeps owning all memo
content, skins, hit-testing and persistence; this module only paints the launcher and coordinates
when/where the memo is shown.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

from state_store import AppState, deadline_alert
from window_layer import (
    apply_tool_window,
    detach_from_parent,
    set_topmost,
    set_window_exclude_from_capture,
)

if TYPE_CHECKING:
    from app import LiquidMemoApp


LAUNCHER_SIZE = 72
LAUNCHER_DEFAULT_MARGIN = 24
LAUNCHER_CLAMP_MARGIN = 4
PANEL_GAP = 12
PANEL_MARGIN = 12
PANEL_ANIMATION_MS = 160
PANEL_SHIFT = 8
CURSOR_POLL_MS = 100
COLLAPSE_DELAY_MS = 500
STATUS_REFRESH_MS = 60_000


def _nearest_area(point: QPoint, areas: list[QRect]) -> QRect:
    """Return the area containing point, or the geometrically nearest area."""
    for area in areas:
        if area.contains(point):
            return area

    def distance_sq(area: QRect) -> int:
        x = min(max(point.x(), area.left()), area.right())
        y = min(max(point.y(), area.top()), area.bottom())
        return (point.x() - x) ** 2 + (point.y() - y) ** 2

    return min(areas, key=distance_sq)


def clamp_launcher_position(
    position: QPoint,
    size: QSize,
    screen_areas: Iterable[QRect],
    fallback_area: QRect,
) -> QPoint:
    """Clamp a launcher top-left to a visible screen, recovering stale monitor coordinates."""
    areas = [QRect(area) for area in screen_areas] or [QRect(fallback_area)]
    center = position + QPoint(size.width() // 2, size.height() // 2)
    area = _nearest_area(center, areas)
    min_x = area.left() + LAUNCHER_CLAMP_MARGIN
    min_y = area.top() + LAUNCHER_CLAMP_MARGIN
    max_x = area.left() + area.width() - size.width() - LAUNCHER_CLAMP_MARGIN
    max_y = area.top() + area.height() - size.height() - LAUNCHER_CLAMP_MARGIN
    return QPoint(
        min(max(position.x(), min_x), max(min_x, max_x)),
        min(max(position.y(), min_y), max(min_y, max_y)),
    )


def default_launcher_position(area: QRect, size: QSize = QSize(LAUNCHER_SIZE, LAUNCHER_SIZE)) -> QPoint:
    """Right-side, vertically centered default used when no position has been saved."""
    return QPoint(
        area.left() + area.width() - size.width() - LAUNCHER_DEFAULT_MARGIN,
        area.top() + (area.height() - size.height()) // 2,
    )


def panel_position(launcher: QRect, panel_size: QSize, area: QRect) -> QPoint:
    """Place the panel beside the launcher, preferring the direction toward screen center."""
    left_x = launcher.left() - PANEL_GAP - panel_size.width()
    right_x = launcher.left() + launcher.width() + PANEL_GAP
    min_x = area.left() + PANEL_MARGIN
    max_x = area.left() + area.width() - panel_size.width() - PANEL_MARGIN
    left_fits = left_x >= min_x
    right_fits = right_x <= max_x
    prefer_left = launcher.center().x() >= area.center().x()

    if prefer_left and (left_fits or not right_fits):
        x = left_x
    elif not prefer_left and (right_fits or not left_fits):
        x = right_x
    else:
        x = right_x if right_fits else left_x
    x = min(max(x, min_x), max(min_x, max_x))

    y = launcher.center().y() - panel_size.height() // 2
    min_y = area.top() + PANEL_MARGIN
    max_y = area.top() + area.height() - panel_size.height() - PANEL_MARGIN
    y = min(max(y, min_y), max(min_y, max_y))
    return QPoint(x, y)


def launcher_alert_status(state: AppState, now: datetime | None = None) -> str:
    """Return ``overdue``, ``near`` or ``none`` for the launcher's status dot."""
    now = now or datetime.now()
    saw_near = False

    def classify(raw: str) -> str:
        # The launcher dot has no "normal" state: a far-off or unparseable deadline is "none".
        status = deadline_alert(raw, state.settings.nearHighlightDays, now)
        return "none" if status == "normal" else status

    for todo in state.todos:
        if todo.done:
            continue
        status = classify(todo.ddl)
        if status == "overdue":
            return status
        saw_near = saw_near or status == "near"

    if state.settings.calendarEnabled:
        visible_feeds = {feed.id for feed in state.settings.active_calendar_feeds()}
        done_keys = set(state.calendarDoneKeys)
        for event in state.calendarEvents:
            if event.feedId not in visible_feeds or event.key in done_keys:
                continue
            status = classify(event.start)
            if status == "overdue":
                return status
            saw_near = saw_near or status == "near"

    return "near" if saw_near else "none"


class FloatingLauncherWindow(QWidget):
    """Small transparent, draggable launcher painted entirely with Qt."""

    activated = Signal()
    contextMenuRequested = Signal(QPoint)
    dragStarted = Signal()
    dragMoved = Signal(QPoint)
    dragFinished = Signal(QPoint)

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setFixedSize(LAUNCHER_SIZE, LAUNCHER_SIZE)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("点击展开桌面备忘；拖动可调整位置；右键打开菜单")

        self._alert_status = "none"
        self._surprise_mode = False
        self._surprise_burst = 0.0
        self._idle = 0.0
        self._shine = 0.0
        self._hover = 0.0
        self._pressed = 0.0
        self._press_global: QPoint | None = None
        self._press_window_pos = QPoint()
        self._dragging = False
        self._window_layer_applied = False

        self._idle_animation = QVariantAnimation(self)
        self._idle_animation.setDuration(2400)
        self._idle_animation.setStartValue(0.0)
        self._idle_animation.setKeyValueAt(0.5, 1.0)
        self._idle_animation.setEndValue(0.0)
        self._idle_animation.setEasingCurve(QEasingCurve.InOutSine)
        self._idle_animation.setLoopCount(-1)
        self._idle_animation.valueChanged.connect(self._set_idle)

        self._shine_animation = QVariantAnimation(self)
        self._shine_animation.setDuration(4000)
        self._shine_animation.setStartValue(0.0)
        self._shine_animation.setKeyValueAt(0.68, 0.0)
        self._shine_animation.setEndValue(1.0)
        self._shine_animation.setLoopCount(-1)
        self._shine_animation.valueChanged.connect(self._set_shine)

        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(140)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover)

        self._press_animation = QVariantAnimation(self)
        self._press_animation.setDuration(80)
        self._press_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._press_animation.valueChanged.connect(self._set_pressed)
        self._burst_animation = QVariantAnimation(self)
        self._burst_animation.setDuration(1200)
        self._burst_animation.setStartValue(0.0)
        self._burst_animation.setKeyValueAt(0.35, 1.0)
        self._burst_animation.setEndValue(0.0)
        self._burst_animation.valueChanged.connect(self._set_burst)

    def set_surprise_mode(self, enabled: bool) -> None:
        self._surprise_mode = bool(enabled)
        self.update()

    def play_surprise_burst(self) -> None:
        if not self._surprise_mode:
            return
        self._burst_animation.stop()
        self._burst_animation.start()

    def set_alert_status(self, status: str) -> None:
        status = status if status in {"none", "near", "overdue"} else "none"
        if status != self._alert_status:
            self._alert_status = status
            self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._window_layer_applied:
            hwnd = int(self.winId())
            apply_tool_window(hwnd)
            detach_from_parent(hwnd)
            set_topmost(hwnd, True)
            self._window_layer_applied = True
        set_window_exclude_from_capture(int(self.winId()), exclude=True)
        self._idle_animation.start()
        self._shine_animation.start()

    def hideEvent(self, event) -> None:
        self._idle_animation.stop()
        self._shine_animation.stop()
        super().hideEvent(event)

    def enterEvent(self, event) -> None:
        self._animate_scalar(self._hover_animation, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_scalar(self._hover_animation, self._hover, 0.0)
        super().leaveEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.contextMenuRequested.emit(event.globalPos())
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_window_pos = self.pos()
            self._dragging = False
            self.setCursor(Qt.ClosedHandCursor)
            self._animate_scalar(self._press_animation, self._pressed, 1.0)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_global is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        current = event.globalPosition().toPoint()
        delta = current - self._press_global
        if not self._dragging and delta.manhattanLength() >= QApplication.startDragDistance():
            self._dragging = True
            self.dragStarted.emit()
        if self._dragging:
            self.dragMoved.emit(self._press_window_pos + delta)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._press_global is not None:
            was_dragging = self._dragging
            self._press_global = None
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)
            self._animate_scalar(self._press_animation, self._pressed, 0.0)
            if was_dragging:
                self.dragFinished.emit(self.pos())
            else:
                self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        idle_y = -1.0 + self._idle * 2.0
        resting_scale = 1.0 + 0.035 * self._idle
        hover_scale = resting_scale * (1.0 - self._hover) + 1.08 * self._hover
        scale = hover_scale * (1.0 - self._pressed) + 0.94 * self._pressed
        painter.translate(self.width() / 2.0, self.height() / 2.0 + idle_y)
        painter.scale(scale, scale)

        shadow_alpha = round(54 + 42 * self._hover)
        shadow = QRadialGradient(QPointF(0, 8), 34)
        shadow.setColorAt(0.0, QColor(25, 45, 90, shadow_alpha))
        shadow.setColorAt(1.0, QColor(25, 45, 90, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(QRectF(-34, -24, 68, 68))

        body_rect = QRectF(-30, -28, 60, 56)
        body_path = QPainterPath()
        body_path.addRoundedRect(body_rect, 19, 19)
        body_gradient = QLinearGradient(body_rect.topLeft(), body_rect.bottomRight())
        if self._surprise_mode:
            body_gradient.setColorAt(0.0, QColor("#FFB7D5"))
            body_gradient.setColorAt(0.48, QColor("#FF78B2"))
            body_gradient.setColorAt(1.0, QColor("#C68CFF"))
        else:
            body_gradient.setColorAt(0.0, QColor("#79E4FF"))
            body_gradient.setColorAt(0.48, QColor("#64B8FF"))
            body_gradient.setColorAt(1.0, QColor("#756BFF"))
        painter.setBrush(body_gradient)
        painter.setPen(QPen(QColor(255, 255, 255, 205), 1.1))
        painter.drawPath(body_path)

        painter.setPen(QPen(QColor(255, 255, 255, 150), 2.3, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(QRectF(-24, -23, 38, 24), 52 * 16, 75 * 16)

        # A compact folded note: simple enough to stay legible at 72px, but recognizably derived
        # from the full application logo.
        note = QPainterPath()
        note.moveTo(-15, -16)
        note.quadTo(-18, -16, -18, -12)
        note.lineTo(-18, 15)
        note.quadTo(-18, 18, -14, 18)
        note.lineTo(16, 18)
        note.quadTo(19, 18, 19, 14)
        note.lineTo(19, -7)
        note.lineTo(9, -16)
        note.closeSubpath()
        note_gradient = QLinearGradient(-12, -16, 14, 18)
        note_gradient.setColorAt(0.0, QColor(255, 255, 255, 248))
        note_gradient.setColorAt(1.0, QColor(225, 238, 255, 235))
        painter.setPen(QPen(QColor(255, 255, 255, 225), 0.9))
        painter.setBrush(note_gradient)
        painter.drawPath(note)

        fold = QPainterPath()
        fold.moveTo(9, -16)
        fold.lineTo(9, -9)
        fold.quadTo(9, -6, 13, -6)
        fold.lineTo(19, -6)
        fold.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(190, 215, 247, 205))
        painter.drawPath(fold)

        painter.setPen(QPen(QColor(49, 69, 110, 225), 2.2, Qt.SolidLine, Qt.RoundCap))
        for y, width in ((-4, 21), (3, 21), (10, 14)):
            painter.drawLine(QPointF(-11, y), QPointF(-11 + width, y))

        if self._shine > 0.001:
            painter.save()
            painter.setClipPath(body_path)
            shine_x = -55 + self._shine * 110
            shine_gradient = QLinearGradient(shine_x - 10, 0, shine_x + 10, 0)
            shine_gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
            shine_gradient.setColorAt(0.5, QColor(255, 255, 255, 82))
            shine_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(shine_gradient)
            painter.setPen(Qt.NoPen)
            painter.rotate(-18)
            painter.drawRect(QRectF(shine_x - 14, -55, 28, 110))
            painter.restore()

        painter.resetTransform()
        if self._surprise_mode:
            painter.setPen(Qt.NoPen)
            for index in range(9):
                angle = (index / 9.0 + self._idle * 0.14) * math.tau
                radius = 30 + self._surprise_burst * 8
                x = 36 + math.cos(angle) * radius
                y = 36 + math.sin(angle) * radius
                alpha = 105 + round(self._surprise_burst * 100)
                painter.setBrush(QColor(255, 88 + index * 8, 158 + index * 5, min(240, alpha)))
                if index % 3:
                    heart = QPainterPath(QPointF(x, y + 2.4))
                    heart.cubicTo(x - 6, y - 1.5, x - 3.8, y - 5.5, x, y - 2.4)
                    heart.cubicTo(x + 3.8, y - 5.5, x + 6, y - 1.5, x, y + 2.4)
                    painter.drawPath(heart)
                else:
                    star = QPainterPath()
                    for point_index in range(8):
                        star_angle = -math.pi / 2 + point_index * math.pi / 4
                        star_radius = 3.7 if point_index % 2 == 0 else 1.3
                        point = QPointF(
                            x + math.cos(star_angle) * star_radius,
                            y + math.sin(star_angle) * star_radius,
                        )
                        star.moveTo(point) if point_index == 0 else star.lineTo(point)
                    star.closeSubpath()
                    painter.drawPath(star)
        if self._alert_status != "none":
            color = QColor("#FF3B30" if self._alert_status == "overdue" else "#FF9500")
            painter.setPen(QPen(QColor(255, 255, 255, 235), 2.2))
            painter.setBrush(color)
            painter.drawEllipse(QRectF(54, 7, 11, 11))

        painter.end()

    def _animate_scalar(self, animation: QVariantAnimation, start: float, end: float) -> None:
        animation.stop()
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()

    def _set_idle(self, value) -> None:
        self._idle = float(value)
        self.update()

    def _set_shine(self, value) -> None:
        self._shine = float(value)
        self.update()

    def _set_hover(self, value) -> None:
        self._hover = float(value)
        self.update()

    def _set_pressed(self, value) -> None:
        self._pressed = float(value)
        self.update()

    def _set_burst(self, value) -> None:
        self._surprise_burst = float(value)
        self.update()


class FloatingModeController(QObject):
    """Own the launcher and coordinate visibility/position of the existing MemoWindow."""

    def __init__(self, app: "LiquidMemoApp") -> None:
        super().__init__()
        self.app = app
        self.window = app.window
        self.launcher = FloatingLauncherWindow()
        self.launcher.activated.connect(self.toggle_panel)
        self.launcher.contextMenuRequested.connect(lambda _pos: self.app.show_tray_menu())
        self.launcher.dragStarted.connect(self._begin_launcher_drag)
        self.launcher.dragMoved.connect(self._move_launcher)
        self.launcher.dragFinished.connect(self._finish_launcher_drag)

        self._panel_visible = False
        self._panel_animation: QParallelAnimationGroup | None = None

        self._cursor_poll = QTimer(self)
        self._cursor_poll.setInterval(CURSOR_POLL_MS)
        self._cursor_poll.timeout.connect(self._poll_cursor)
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(COLLAPSE_DELAY_MS)
        self._collapse_timer.timeout.connect(self.collapse_panel)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(STATUS_REFRESH_MS)
        self._status_timer.timeout.connect(self.update_status)

    @property
    def mode(self) -> str:
        return self.app.state.settings.windowMode

    def start(self) -> None:
        self._status_timer.start()
        self.apply_mode(initial=True)

    def apply_mode(self, initial: bool = False) -> None:
        self._stop_panel_animation()
        self._collapse_timer.stop()
        floating = self.mode == "floatingLauncher"
        self.window.drag_handle.setVisible(not floating)

        if floating:
            self.window._undock()
            self.window.hide()
            self._panel_visible = False
            self._show_launcher()
            return

        self._cursor_poll.stop()
        self.launcher.hide()
        self._panel_visible = False
        self.window.setWindowOpacity(1.0)
        if not self.window.isVisible() or not initial:
            self.window.show()
            self.window.raise_()
        if not initial:
            # Returning from the launcher popover (whose position is never persisted): re-apply the
            # saved normal/edge-mode geometry, otherwise the memo reappears stuck at the popover
            # anchor instead of where the user left it.
            self.window.apply_initial_geometry()
        if self.mode == "normal":
            self.window._undock()
        else:
            QTimer.singleShot(0, self.window._maybe_dock)

    def surfaces_visible(self) -> bool:
        return self.launcher.isVisible() if self.mode == "floatingLauncher" else self.window.isVisible()

    def toggle_surfaces(self) -> None:
        if self.mode != "floatingLauncher":
            if self.window.isVisible():
                self.window.hide()
            else:
                self.window.show()
                self.window.raise_()
            return
        if self.launcher.isVisible():
            self.collapse_panel(immediate=True)
            self.launcher.hide()
            self._cursor_poll.stop()
        else:
            self._show_launcher()

    def toggle_panel(self) -> None:
        if self._panel_visible or self.window.isVisible():
            self.collapse_panel()
        else:
            self.expand_panel()

    def expand_panel(self) -> None:
        if self.mode != "floatingLauncher":
            return
        if not self.launcher.isVisible():
            self._show_launcher()
        self._collapse_timer.stop()
        self._stop_panel_animation()

        self.window.setWindowOpacity(0.0)
        self.window.show()
        self.window.refresh()
        target = self._panel_target()
        shift = PANEL_SHIFT if target.x() < self.launcher.x() else -PANEL_SHIFT
        start = target + QPoint(shift, 0)
        self.window.move(start)
        self.window.raise_()
        self.launcher.raise_()
        self._panel_visible = True

        group = QParallelAnimationGroup(self)
        position_animation = QPropertyAnimation(self.window, b"pos", group)
        position_animation.setDuration(PANEL_ANIMATION_MS)
        position_animation.setStartValue(start)
        position_animation.setEndValue(target)
        position_animation.setEasingCurve(QEasingCurve.OutCubic)
        opacity_animation = QPropertyAnimation(self.window, b"windowOpacity", group)
        opacity_animation.setDuration(PANEL_ANIMATION_MS)
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.OutCubic)
        group.finished.connect(lambda: self._finish_expand(target, group))
        self._panel_animation = group
        group.start()
        self._cursor_poll.start()

    def collapse_panel(self, immediate: bool = False) -> None:
        self._collapse_timer.stop()
        if not self.window.isVisible():
            self._panel_visible = False
            return
        self._stop_panel_animation()
        self._panel_visible = False
        try:
            self.window.add_popup.hide()
        except RuntimeError:
            pass
        if immediate:
            self.window.hide()
            self.window.setWindowOpacity(1.0)
            return

        start = self.window.pos()
        shift = -PANEL_SHIFT if start.x() < self.launcher.x() else PANEL_SHIFT
        end = start + QPoint(shift, 0)
        group = QParallelAnimationGroup(self)
        position_animation = QPropertyAnimation(self.window, b"pos", group)
        position_animation.setDuration(PANEL_ANIMATION_MS)
        position_animation.setStartValue(start)
        position_animation.setEndValue(end)
        position_animation.setEasingCurve(QEasingCurve.InCubic)
        opacity_animation = QPropertyAnimation(self.window, b"windowOpacity", group)
        opacity_animation.setDuration(PANEL_ANIMATION_MS)
        opacity_animation.setStartValue(self.window.windowOpacity())
        opacity_animation.setEndValue(0.0)
        opacity_animation.setEasingCurve(QEasingCurve.InCubic)
        group.finished.connect(lambda: self._finish_collapse(group))
        self._panel_animation = group
        group.start()

    def reposition_panel(self) -> None:
        if self.mode != "floatingLauncher" or not self.window.isVisible() or not self._panel_visible:
            return
        if self._panel_animation is not None:
            return
        self.window.move(self._panel_target())
        self.launcher.raise_()

    def update_status(self) -> None:
        self.launcher.set_alert_status(launcher_alert_status(self.app.state))

    def stop(self) -> None:
        self._cursor_poll.stop()
        self._collapse_timer.stop()
        self._status_timer.stop()
        self._stop_panel_animation()
        self.window.setWindowOpacity(1.0)
        self.launcher.hide()

    def _show_launcher(self) -> None:
        position = self._resolved_launcher_position()
        self.launcher.move(position)
        self.launcher.show()
        self.launcher.raise_()
        self.update_status()
        self._cursor_poll.start()

    def _resolved_launcher_position(self) -> QPoint:
        primary = QApplication.primaryScreen()
        if primary is None:
            return QPoint(24, 24)
        fallback = primary.availableGeometry()
        state = self.app.state.window
        if state.launcherX is None or state.launcherY is None:
            position = default_launcher_position(fallback, self.launcher.size())
        else:
            position = QPoint(int(state.launcherX), int(state.launcherY))
        areas = [screen.availableGeometry() for screen in QApplication.screens()]
        clamped = clamp_launcher_position(position, self.launcher.size(), areas, fallback)
        if (state.launcherX, state.launcherY) != (clamped.x(), clamped.y()):
            state.launcherX, state.launcherY = clamped.x(), clamped.y()
            self.app.save_later()
        return clamped

    def _panel_target(self) -> QPoint:
        center = self.launcher.frameGeometry().center()
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        return panel_position(self.launcher.frameGeometry(), self.window.size(), area)

    def _begin_launcher_drag(self) -> None:
        self.collapse_panel(immediate=True)

    def _move_launcher(self, position: QPoint) -> None:
        primary = QApplication.primaryScreen()
        if primary is None:
            self.launcher.move(position)
            return
        areas = [screen.availableGeometry() for screen in QApplication.screens()]
        clamped = clamp_launcher_position(position, self.launcher.size(), areas, primary.availableGeometry())
        self.launcher.move(clamped)

    def _finish_launcher_drag(self, _position: QPoint) -> None:
        state = self.app.state.window
        state.launcherX = self.launcher.x()
        state.launcherY = self.launcher.y()
        self.app.save_later()

    def _poll_cursor(self) -> None:
        if not self._panel_visible or not self.window.isVisible():
            self._collapse_timer.stop()
            return
        if self._interaction_active():
            self._collapse_timer.stop()
            return
        cursor = QCursor.pos()
        inside_launcher = self.launcher.frameGeometry().adjusted(-4, -4, 4, 4).contains(cursor)
        inside_panel = self.window.frameGeometry().adjusted(-4, -4, 4, 4).contains(cursor)
        if inside_launcher or inside_panel:
            self._collapse_timer.stop()
        elif not self._collapse_timer.isActive():
            self._collapse_timer.start(COLLAPSE_DELAY_MS)

    def _interaction_active(self) -> bool:
        return bool(
            self.window._is_window_moving
            or self.window._reorder_row is not None
            or self.window.add_popup.isVisible()
            or bool(getattr(self.app, "surprise", None) and self.app.surprise.note_dialog.isVisible())
            or self.app.settings_window.isVisible()
            or self.app.history_window.isVisible()
        )

    def _finish_expand(self, target: QPoint, group: QParallelAnimationGroup) -> None:
        if self._panel_animation is not group:
            group.deleteLater()
            return
        self._panel_animation = None
        self.window.move(target)
        self.window.setWindowOpacity(1.0)
        self.window.protect_content_layer()
        self.launcher.raise_()
        group.deleteLater()

    def _finish_collapse(self, group: QParallelAnimationGroup) -> None:
        if self._panel_animation is not group:
            group.deleteLater()
            return
        self._panel_animation = None
        self.window.hide()
        self.window.setWindowOpacity(1.0)
        group.deleteLater()

    def _stop_panel_animation(self) -> None:
        if self._panel_animation is None:
            return
        group = self._panel_animation
        self._panel_animation = None
        group.stop()
        group.deleteLater()
