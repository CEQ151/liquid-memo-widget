"""System reminder manager: a periodic scan pops native Windows toasts (the tray
balloon) for calendar events and todos whose deadline is approaching. Qt glue around
the Qt-free state; the app is reached through `self.app`.

Kept free of any `app` import (only `state_store`) so importing it cannot create a cycle
with app.py, which imports this module.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from state_store import parse_ddl

if TYPE_CHECKING:
    from app import LiquidMemoApp

NOTIFY_CHECK_INTERVAL_MS = 60 * 1000  # how often the reminder scan runs
NOTIFY_TOAST_TIMEOUT_MS = 8000  # how long a toast stays on screen
ALLDAY_NOTIFY_HOUR = 9  # all-day events have no clock time: remind at this hour on the day
_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


def _short_time(when: datetime, all_day: bool) -> str:
    weekday = _WEEKDAY_CN[when.weekday()]
    if all_day:
        return f"{when.strftime('%m-%d')} 周{weekday} 全天"
    return f"{when.strftime('%m-%d')} 周{weekday} {when.strftime('%H:%M')}"


class NotificationManager:
    """Owns the reminder scan: a timer that toasts upcoming calendar events and todo
    deadlines via the tray icon, de-duplicated across scans and relaunches."""

    def __init__(self, app: "LiquidMemoApp") -> None:
        self.app = app
        self._timer = QTimer()
        self._timer.setInterval(NOTIFY_CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self.check_now)

    def start(self) -> None:
        # The scan runs regardless of calendarEnabled (todo deadlines always apply); check_now
        # itself no-ops when the feature toggle is off.
        self._timer.start()
        # Clicking a toast brings the memo window forward.
        try:
            self.app.tray.messageClicked.connect(self._on_message_clicked)
        except Exception:
            pass
        self.check_now()

    def stop(self) -> None:
        self._timer.stop()

    def _on_message_clicked(self) -> None:
        try:
            self.app.window.show()
            self.app.window.raise_()
        except Exception:
            pass

    def _candidates(self, now: datetime) -> list[tuple[str, str, str, datetime, datetime]]:
        """(key, title, body, window_start, window_end) for every item that could remind.

        A reminder fires while `window_start <= now <= window_end`. The `now <= start` upper
        bound for timed items means an item whose time already passed while the app was closed
        is not announced late.
        """
        settings = self.app.state.settings
        lead = timedelta(minutes=settings.notifyMinutesBefore)
        out: list[tuple[str, str, str, datetime, datetime]] = []

        # Calendar events from checked feeds only (the filter returns [] when calendar is off).
        done = set(self.app.state.calendarDoneKeys)
        for event in self.app.window._visible_calendar_events():
            if event.key in done:
                continue
            when = parse_ddl(event.start, now)
            if when is None:
                continue
            if event.allDay:
                win_start = when.replace(hour=ALLDAY_NOTIFY_HOUR, minute=0, second=0, microsecond=0)
                win_end = when.replace(hour=23, minute=59, second=59, microsecond=0)
            else:
                win_start = when - lead
                win_end = when
            summary = event.summary or "（无标题）"
            body = f"{_short_time(when, event.allDay)}\n{summary}"
            out.append((f"cal|{event.key}", "日程提醒", body, win_start, win_end))

        # Todos with a deadline. The key includes the ddl text so editing a deadline re-arms it.
        for todo in self.app.state.todos:
            if todo.done or not (todo.ddl or "").strip():
                continue
            when = parse_ddl(todo.ddl, now)
            if when is None:
                continue
            text = todo.text or "（无内容）"
            body = f"{_short_time(when, False)} 截止\n{text}"
            out.append((f"todo|{todo.id}|{todo.ddl}", "待办提醒", body, when - lead, when))

        return out

    def check_now(self) -> None:
        state = self.app.state
        if not state.settings.notificationsEnabled:
            return
        now = datetime.now()
        candidates = self._candidates(now)
        valid = {item[0] for item in candidates}
        # Prune notified keys to the current candidates so the set cannot grow without bound.
        kept = [key for key in state.notifiedKeys if key in valid]
        already = set(kept)

        fired: list[tuple[str, str]] = []  # (title, body) of newly-firing items
        for key, title, body, win_start, win_end in candidates:
            if key in already:
                continue
            if win_start <= now <= win_end:
                fired.append((title, body))
                kept.append(key)
                already.add(key)

        if fired:
            self._toast(fired)
        if kept != state.notifiedKeys:
            state.notifiedKeys = kept
            self.app.save_later()

    def _toast(self, fired: list[tuple[str, str]]) -> None:
        # Several items at once collapse into one toast — successive showMessage calls would
        # otherwise overwrite each other and only the last would be seen.
        if len(fired) == 1:
            title, body = fired[0]
        else:
            title = "即将到来的事项"
            lines = [body.replace("\n", " ") for _t, body in fired[:5]]
            if len(fired) > 5:
                lines.append(f"……另有 {len(fired) - 5} 项")
            body = "\n".join(lines)
        try:
            self.app.tray.showMessage(title, body, QSystemTrayIcon.Information, NOTIFY_TOAST_TIMEOUT_MS)
        except Exception:
            pass
