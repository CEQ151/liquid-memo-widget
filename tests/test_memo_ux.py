"""Regression coverage for configurable highlighting and manual todo ordering."""
from dataclasses import asdict
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from state_store import AppState, CalendarEvent, TodoItem


@pytest.mark.parametrize(("saved", "expected"), [(0, 1), (7, 7), (99, 30)])
def test_near_highlight_days_roundtrips_and_clamps(saved, expected):
    payload = asdict(AppState())
    payload["settings"]["nearHighlightDays"] = saved

    restored = AppState.from_dict(payload)

    assert restored.settings.nearHighlightDays == expected


def test_todo_sort_key_pins_urgent_then_uses_manual_order(qapp):
    from app import MemoWindow

    todos = [
        TodoItem(id="late-ddl", ddl="2099-01-01", order=1),
        TodoItem(id="early-ddl", ddl="2020-01-01", order=3),
        TodoItem(id="urgent", urgent=True, order=9),
        TodoItem(id="first", order=0),
    ]

    assert [todo.id for todo in sorted(todos, key=MemoWindow._todo_sort_key)] == [
        "urgent", "first", "late-ddl", "early-ddl",
    ]


def test_configured_near_window_applies_to_todos_and_calendar(qapp):
    from app import CalendarRow, TodoRow

    state = AppState()
    state.settings.nearHighlightDays = 2
    host = QWidget()
    parent = SimpleNamespace(
        content=host,
        app=SimpleNamespace(state=state),
        text_color_for=lambda _todo: QColor("#111820"),
        text_needs_halo=lambda: False,
        _normal_text_color=lambda: QColor("#111820"),
        edit_todo=lambda _todo_id: None,
        toggle_urgent=lambda _todo_id: None,
        complete_todo=lambda *_args: None,
        toggle_calendar_event=lambda *_args: None,
    )
    start = (datetime.now() + timedelta(days=2, hours=12)).strftime("%Y-%m-%d %H:%M")
    todo_row = TodoRow(TodoItem(text="test", ddl=start), state.settings, parent)
    event_row = CalendarRow(CalendarEvent(summary="test", start=start), False, parent)

    assert todo_row._ddl_status() == "normal"
    assert event_row._event_status() == "normal"

    state.settings.nearHighlightDays = 3
    assert todo_row._ddl_status() == "near"
    assert event_row._event_status() == "near"

    todo_row.deleteLater()
    event_row.deleteLater()
    host.deleteLater()
