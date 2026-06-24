"""Floating-launcher state migration, placement and status regression tests."""
from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

import floating_launcher as launcher_module
from floating_launcher import (
    FloatingModeController,
    LAUNCHER_SIZE,
    clamp_launcher_position,
    default_launcher_position,
    launcher_alert_status,
    panel_position,
)
from state_store import AppState, CalendarEvent, CalendarFeed, TodoItem


class _FakeMemoWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.resize(420, 500)
        self.drag_handle = QWidget(self)
        self.add_popup = QWidget()
        self._is_window_moving = False
        self._reorder_row = None
        self.undock_calls = 0
        self.dock_calls = 0
        self.refresh_calls = 0
        self.geometry_calls = 0

    def _undock(self) -> None:
        self.undock_calls += 1

    def _maybe_dock(self) -> None:
        self.dock_calls += 1

    def refresh(self) -> None:
        self.refresh_calls += 1

    def apply_initial_geometry(self) -> None:
        self.geometry_calls += 1

    def protect_content_layer(self) -> None:
        pass


def _controller_app():
    app = SimpleNamespace(
        state=AppState(),
        window=_FakeMemoWindow(),
        settings_window=QWidget(),
        history_window=QWidget(),
        saved=0,
        menu_calls=0,
    )

    def save_later():
        app.saved += 1

    app.save_later = save_later

    def show_tray_menu():
        app.menu_calls += 1

    app.show_tray_menu = show_tray_menu
    return app


@pytest.fixture
def harmless_window_layer(monkeypatch):
    monkeypatch.setattr(launcher_module, "apply_tool_window", lambda *_args: None)
    monkeypatch.setattr(launcher_module, "detach_from_parent", lambda *_args: None)
    monkeypatch.setattr(launcher_module, "set_topmost", lambda *_args: None)
    monkeypatch.setattr(launcher_module, "protect_window_from_capture", lambda *_args, **_kwargs: True)


@pytest.mark.parametrize(
    ("legacy_edge_hide", "expected"),
    [(True, "edgeHide"), (False, "normal")],
)
def test_v4_edge_auto_hide_migrates_to_window_mode(legacy_edge_hide, expected):
    payload = asdict(AppState())
    payload["version"] = 4
    payload["settings"].pop("windowMode")
    payload["settings"]["edgeAutoHide"] = legacy_edge_hide

    restored = AppState.from_dict(payload)

    assert restored.version == 6
    assert restored.settings.windowMode == expected


def test_invalid_window_mode_falls_back_to_edge_hide():
    payload = asdict(AppState())
    payload["settings"]["windowMode"] = "unknown"

    assert AppState.from_dict(payload).settings.windowMode == "edgeHide"


def test_launcher_coordinates_roundtrip():
    payload = asdict(AppState())
    payload["window"]["launcherX"] = 777
    payload["window"]["launcherY"] = 333

    restored = AppState.from_dict(payload)

    assert (restored.window.launcherX, restored.window.launcherY) == (777, 333)


def test_launcher_default_and_stale_position_are_kept_on_screen():
    primary = QRect(0, 0, 1920, 1080)
    second = QRect(1920, 0, 1280, 1024)
    size = QSize(LAUNCHER_SIZE, LAUNCHER_SIZE)

    default = default_launcher_position(primary, size)
    assert default == QPoint(1920 - LAUNCHER_SIZE - 24, (1080 - LAUNCHER_SIZE) // 2)

    clamped = clamp_launcher_position(QPoint(5000, -400), size, [primary, second], primary)
    assert second.contains(QRect(clamped, size))


def test_panel_opens_toward_screen_center_and_stays_inside():
    area = QRect(0, 0, 1920, 1080)
    panel = QSize(420, 500)

    from_right = panel_position(QRect(1800, 450, 72, 72), panel, area)
    from_left = panel_position(QRect(40, 450, 72, 72), panel, area)
    from_corner = panel_position(QRect(1840, 980, 72, 72), QSize(700, 700), area)

    assert from_right.x() < 1800
    assert from_left.x() > 40
    assert area.adjusted(11, 11, -11, -11).contains(QRect(from_corner, QSize(700, 700)))


def test_launcher_status_prioritizes_overdue_and_ignores_done_items():
    now = datetime(2026, 6, 23, 12, 0)
    state = AppState()
    state.settings.nearHighlightDays = 3
    state.todos = [
        TodoItem(id="done", ddl="2026-06-20 12:00", done=True),
        TodoItem(id="near", ddl="2026-06-25 12:00"),
    ]
    assert launcher_alert_status(state, now) == "near"

    state.todos.append(TodoItem(id="late", ddl="2026-06-22 12:00"))
    assert launcher_alert_status(state, now) == "overdue"


def test_launcher_status_filters_calendar_feeds_and_checked_events():
    now = datetime(2026, 6, 23, 12, 0)
    state = AppState()
    state.settings.calendarEnabled = True
    state.settings.nearHighlightDays = 3
    state.settings.calendarFeeds = [
        CalendarFeed(id="visible", url="https://example.com/a.ics", enabled=True),
        CalendarFeed(id="hidden", url="https://example.com/b.ics", enabled=False),
    ]
    state.calendarEvents = [
        CalendarEvent(key="checked", feedId="visible", start="2026-06-22 12:00"),
        CalendarEvent(key="hidden", feedId="hidden", start="2026-06-22 12:00"),
        CalendarEvent(key="near", feedId="visible", start="2026-06-24 12:00"),
    ]
    state.calendarDoneKeys = ["checked"]

    assert launcher_alert_status(state, now) == "near"


def test_controller_switches_between_all_three_modes(qapp, harmless_window_layer):
    app = _controller_app()
    app.state.settings.windowMode = "floatingLauncher"
    controller = FloatingModeController(app)

    controller.start()
    assert controller.launcher.isVisible()
    assert not app.window.isVisible()
    assert not app.window.drag_handle.isVisible()

    controller.expand_panel()
    assert app.window.isVisible()
    assert controller._panel_visible
    controller.collapse_panel(immediate=True)
    QTest.qWait(1)  # flush the stopped animation group's deferred deletion while targets live
    assert not app.window.isVisible()

    app.state.settings.windowMode = "normal"
    controller.apply_mode()
    assert app.window.isVisible()
    assert not controller.launcher.isVisible()
    assert app.window.drag_handle.isVisible()
    # Leaving launcher mode must re-apply the saved geometry (the popover never persists position).
    assert app.window.geometry_calls >= 1

    app.state.settings.windowMode = "edgeHide"
    controller.apply_mode()
    qapp.processEvents()
    assert app.window.dock_calls >= 1

    controller.stop()
    QTest.qWait(1)
    app.window.close()
    app.settings_window.close()
    app.history_window.close()


def test_controller_delays_collapse_and_pauses_for_popup(qapp, harmless_window_layer, monkeypatch):
    app = _controller_app()
    app.state.settings.windowMode = "floatingLauncher"
    controller = FloatingModeController(app)
    controller.start()
    controller.expand_panel()
    monkeypatch.setattr(launcher_module, "QCursor", SimpleNamespace(pos=lambda: QPoint(5000, 5000)))

    app.window.add_popup.show()
    controller._poll_cursor()
    assert not controller._collapse_timer.isActive()

    app.window.add_popup.hide()
    controller._poll_cursor()
    assert controller._collapse_timer.isActive()
    QTest.qWait(750)
    assert not app.window.isVisible()

    controller.stop()
    QTest.qWait(1)
    app.window.close()
    app.settings_window.close()
    app.history_window.close()


def test_launcher_click_and_drag_position_persistence(qapp, harmless_window_layer):
    app = _controller_app()
    app.state.settings.windowMode = "floatingLauncher"
    controller = FloatingModeController(app)
    activations = []
    controller.launcher.activated.connect(lambda: activations.append(True))
    controller.start()

    context_event = QContextMenuEvent(
        QContextMenuEvent.Mouse, QPoint(36, 36), controller.launcher.mapToGlobal(QPoint(36, 36))
    )
    qapp.sendEvent(controller.launcher, context_event)
    assert app.menu_calls == 1

    QTest.mouseClick(controller.launcher, Qt.LeftButton, pos=QPoint(36, 36))
    assert activations == [True]

    controller._begin_launcher_drag()
    controller._move_launcher(QPoint(200, 240))
    controller._finish_launcher_drag(controller.launcher.pos())
    assert (app.state.window.launcherX, app.state.window.launcherY) == (
        controller.launcher.x(), controller.launcher.y()
    )
    assert app.saved >= 1

    controller.stop()
    QTest.qWait(1)
    app.window.close()
    app.settings_window.close()
    app.history_window.close()
