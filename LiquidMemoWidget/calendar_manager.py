"""Calendar subscription manager: periodic refresh, background fetch and applying
results to state. Qt glue around the Qt-free calendar_sync module; the app is
reached through `self.app`."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

import calendar_sync
from state_store import CalendarEvent, CalendarFeed, utc_now

if TYPE_CHECKING:
    from app import LiquidMemoApp

CALENDAR_SYNC_INTERVAL_MS = 30 * 60 * 1000  # periodic background refresh


class _CalendarSyncSignals(QObject):
    # dict: {"events": list[CalendarEvent], "okIds": list[str], "names": dict[str, str],
    #        "errors": list[str]} — partial failures carry both events and errors.
    finished = Signal(dict)


class _CalendarSyncTask(QRunnable):
    """Fetch + parse every checked feed on a pool thread so the render loop never blocks.

    One feed failing must not lose the others: each feed is fetched independently and the
    result reports per-feed success (okIds) so the manager can keep cached events for the
    feeds that failed this round.
    """

    def __init__(self, feeds: list[CalendarFeed], days: int, signals: _CalendarSyncSignals) -> None:
        super().__init__()
        # Snapshot plain values; the live dataclasses belong to the UI thread.
        self.feeds = [(feed.id, feed.url, feed.name) for feed in feeds]
        self.days = days
        self.signals = signals

    def run(self) -> None:
        events: list[CalendarEvent] = []
        ok_ids: list[str] = []
        names: dict[str, str] = {}
        errors: list[str] = []
        for feed_id, url, name in self.feeds:
            try:
                text = calendar_sync.fetch_ics(url)
                feed_name, feed_events = calendar_sync.parse_feed(text, self.days, datetime.now(), feed_id)
                events.extend(feed_events)
                ok_ids.append(feed_id)
                if feed_name:
                    names[feed_id] = feed_name
            except Exception as exc:  # network/parse errors are reported to the UI, not fatal
                errors.append(f"{name or url}：{str(exc) or exc.__class__.__name__}")
        self.signals.finished.emit(
            {"events": events, "okIds": ok_ids, "names": names, "errors": errors}
        )


class CalendarManager:
    """Owns calendar sync: periodic refresh, background fetch, and applying results to state."""

    def __init__(self, app: "LiquidMemoApp") -> None:
        self.app = app
        self._running = False
        self._signals: _CalendarSyncSignals | None = None
        self._timer = QTimer()
        self._timer.setInterval(CALENDAR_SYNC_INTERVAL_MS)
        self._timer.timeout.connect(self.sync_now)
        # Coalesces rapid settings edits (typing a URL, nudging the day spinbox) into one sync.
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self.sync_now)

    def start(self) -> None:
        if self.app.state.settings.calendarEnabled:
            self._timer.start()
            self.sync_now()

    def stop(self) -> None:
        self._timer.stop()
        self._debounce.stop()

    def on_settings_changed(self) -> None:
        settings = self.app.state.settings
        if settings.calendarEnabled and settings.active_calendar_feeds():
            if not self._timer.isActive():
                self._timer.start()
            self._debounce.start()
            # Show cached events of just-(re)enabled feeds immediately; the debounced sync
            # then refreshes them from the network.
            self.app.window.refresh()
        else:
            self._timer.stop()
            self._debounce.stop()
            self.app.window.refresh()  # hide the 日程 group when disabled / no checked feed

    def sync_now(self) -> None:
        settings = self.app.state.settings
        feeds = settings.active_calendar_feeds()
        if not settings.calendarEnabled or not feeds or self._running:
            return
        self._running = True
        self.app.settings_window.refresh_calendar_status(syncing=True)
        signals = _CalendarSyncSignals()
        signals.finished.connect(self._on_finished)
        self._signals = signals  # keep a reference alive until the task completes
        task = _CalendarSyncTask(feeds, settings.calendarSyncDays, signals)
        QThreadPool.globalInstance().start(task)

    def _on_finished(self, result: dict) -> None:
        self._running = False
        state = self.app.state
        settings = state.settings
        synced_ok = set(result["okIds"])
        feed_ids = {feed.id for feed in settings.calendarFeeds}
        # Freshly synced feeds replace their cached events; feeds that failed this round or
        # are unchecked keep their cache (hidden by the display filter, refreshed when they
        # come back). Events of deleted feeds drop out here.
        kept = [
            event for event in state.calendarEvents
            if event.feedId in feed_ids and event.feedId not in synced_ok
        ]
        state.calendarEvents = sorted(kept + result["events"], key=lambda event: event.start)
        # Adopt calendar names advertised by the feeds (X-WR-CALNAME).
        for feed in settings.calendarFeeds:
            name = result["names"].get(feed.id)
            if name and feed.name != name:
                feed.name = name
        if synced_ok:
            state.calendarLastSync = utc_now()
        state.calendarLastError = "；".join(result["errors"]) or None
        self._prune_done_keys()
        self.app.save()
        self.app.window.refresh()
        self.app.settings_window.refresh_calendar_status()
        self.app.settings_window.refresh_feed_list()

    def _prune_done_keys(self) -> None:
        # Keep only keys still present in the freshly synced window; past, dropped occurrences
        # fall out so the done set cannot grow without bound.
        valid = {event.key for event in self.app.state.calendarEvents}
        self.app.state.calendarDoneKeys = [key for key in self.app.state.calendarDoneKeys if key in valid]

    def toggle_event_done(self, key: str, checked: bool) -> None:
        keys = self.app.state.calendarDoneKeys
        if checked and key not in keys:
            keys.append(key)
        elif not checked and key in keys:
            keys.remove(key)
        self.app.save()
        self.app.window.refresh()
