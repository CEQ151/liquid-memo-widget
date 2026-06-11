from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


APP_DIR = Path.home() / "AppData" / "Roaming" / "DesktopMemo_Pro"
STATE_PATH = APP_DIR / "liquid-state.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# DDL is stored as free text (e.g. "6-15 23:59", "2026/6/15", "6月15日"). For sorting and
# overdue/near highlighting we make a best-effort parse of common machine-readable forms into
# a naive local datetime; anything we cannot parse (e.g. "下周一") returns None and is excluded
# from date-based sorting/highlighting while still displaying its text verbatim.
_DDL_PATTERNS = [
    # YYYY-MM-DD or YYYY/MM/DD, optional HH:MM
    re.compile(r"^(?P<y>\d{4})[-/.](?P<mo>\d{1,2})[-/.](?P<d>\d{1,2})(?:\s+(?P<h>\d{1,2}):(?P<mi>\d{2}))?$"),
    # MM-DD or M/D (no year), optional HH:MM
    re.compile(r"^(?P<mo>\d{1,2})[-/.](?P<d>\d{1,2})(?:\s+(?P<h>\d{1,2}):(?P<mi>\d{2}))?$"),
    # Chinese: YYYY年M月D日 / M月D日, optional H[点时]M?分
    re.compile(
        r"^(?:(?P<y>\d{4})年)?(?P<mo>\d{1,2})月(?P<d>\d{1,2})日?"
        r"(?:\s*(?P<h>\d{1,2})[点时](?:(?P<mi>\d{1,2})分?)?)?$"
    ),
]


def parse_ddl(text: str, now: datetime | None = None) -> datetime | None:
    """Best-effort parse of a DDL string into a naive local datetime, or None.

    Year-less inputs assume the current year; if that places the deadline more than ~180 days
    in the past it rolls to next year (so "1-5" entered in December means next January).
    A missing time defaults to 23:59 (end of day), matching common deadline semantics.
    """
    text = (text or "").strip()
    if not text:
        return None
    now = now or datetime.now()
    for pattern in _DDL_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        parts = match.groupdict()
        try:
            month = int(parts["mo"])
            day = int(parts["d"])
            year = int(parts["y"]) if parts.get("y") else now.year
            hour = int(parts["h"]) if parts.get("h") else 23
            minute = int(parts["mi"]) if parts.get("mi") else (0 if parts.get("h") else 59)
            candidate = datetime(year, month, day, hour, minute)
        except (ValueError, TypeError):
            return None
        if not parts.get("y") and (now - candidate).days > 180:
            try:
                candidate = candidate.replace(year=year + 1)
            except ValueError:
                pass
        return candidate
    return None


@dataclass
class TodoItem:
    id: str = field(default_factory=lambda: str(uuid4()))
    text: str = ""
    ddl: str = ""
    urgent: bool = False
    done: bool = False
    createdAt: str = field(default_factory=utc_now)
    completedAt: str | None = None
    order: int = 0

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TodoItem":
        return TodoItem(
            id=str(data.get("id") or uuid4()),
            text=str(data.get("text") or ""),
            ddl=str(data.get("ddl") or ""),
            urgent=bool(data.get("urgent", False)),
            done=bool(data.get("done", False)),
            createdAt=str(data.get("createdAt") or utc_now()),
            completedAt=data.get("completedAt"),
            order=int(data.get("order", 0)),
        )


@dataclass
class WindowState:
    x: int | None = None
    y: int | None = None
    width: int = 320
    height: int = 320
    startPosition: str = "topRight"
    visible: bool = True


@dataclass
class Settings:
    glassOpacity: float = 0.0
    liquidStrength: float = 1.0
    windowTint: str = "#FFFFFF"
    todoTextColor: str = "#111820"
    urgentTextColor: str = "#FF0000"
    fontColorMode: str = "autoEnhanced"
    completeBehavior: str = "archive"
    layerMode: str = "alwaysVisibleClickThrough"
    startWithWindows: bool = False
    # Calendar subscription: when enabled, the widget syncs the next `calendarSyncDays` days of
    # events from an ICS/webcal URL and shows them in a separate "日程" group.
    calendarEnabled: bool = False
    calendarUrl: str = ""
    calendarSyncDays: int = 7


@dataclass
class CalendarEvent:
    uid: str = ""
    summary: str = ""
    start: str = ""  # ISO local datetime (or date for all-day)
    allDay: bool = False
    # Stable identity for one occurrence (a recurring series yields one key per instance), used
    # to remember which events the user checked off across re-syncs.
    key: str = ""

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CalendarEvent":
        uid = str(data.get("uid") or "")
        start = str(data.get("start") or "")
        return CalendarEvent(
            uid=uid,
            summary=str(data.get("summary") or ""),
            start=start,
            allDay=bool(data.get("allDay", False)),
            key=str(data.get("key") or f"{uid}|{start}"),
        )


@dataclass
class AppState:
    version: int = 3
    settings: Settings = field(default_factory=Settings)
    window: WindowState = field(default_factory=WindowState)
    todos: list[TodoItem] = field(default_factory=list)
    history: list[TodoItem] = field(default_factory=list)
    # Calendar cache + state, all persisted so a relaunch shows last-synced events offline.
    calendarEvents: list[CalendarEvent] = field(default_factory=list)
    calendarDoneKeys: list[str] = field(default_factory=list)
    calendarLastSync: str | None = None
    calendarLastError: str | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AppState":
        settings_defaults = asdict(Settings())
        window_defaults = asdict(WindowState())
        settings_data = dict(data.get("settings") or {})
        window_data = dict(data.get("window") or {})
        settings = Settings(**{key: settings_data.get(key, value) for key, value in settings_defaults.items()})
        if settings.layerMode != "alwaysVisibleClickThrough":
            settings.layerMode = "alwaysVisibleClickThrough"
        settings.calendarSyncDays = max(1, min(30, int(settings.calendarSyncDays or 7)))
        window = WindowState(**{key: window_data.get(key, value) for key, value in window_defaults.items()})
        todos = [TodoItem.from_dict(item) for item in data.get("todos") or []]
        history = [TodoItem.from_dict(item) for item in data.get("history") or []]
        events = [CalendarEvent.from_dict(item) for item in data.get("calendarEvents") or []]
        done_keys = [str(key) for key in data.get("calendarDoneKeys") or []]
        return AppState(
            version=3,
            settings=settings,
            window=window,
            todos=todos,
            history=history,
            calendarEvents=events,
            calendarDoneKeys=done_keys,
            calendarLastSync=data.get("calendarLastSync"),
            calendarLastError=data.get("calendarLastError"),
        )


class StateStore:
    def __init__(self, path: Path = STATE_PATH) -> None:
        self.path = path

    def load(self) -> AppState:
        if not self.path.exists():
            return AppState()

        try:
            with self.path.open("r", encoding="utf-8") as stream:
                return AppState.from_dict(json.load(stream))
        except Exception:
            self._backup_bad_state()
            return AppState()

    def save(self, state: AppState) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as stream:
            json.dump(asdict(state), stream, ensure_ascii=False, indent=2)
        tmp_path.replace(self.path)

    def _backup_bad_state(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.path, APP_DIR / f"liquid-state.bad-{stamp}.json")
        except Exception:
            pass
