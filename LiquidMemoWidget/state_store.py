from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


APP_DIR = Path.home() / "AppData" / "Roaming" / "DesktopMemo_Pro"
STATE_PATH = APP_DIR / "liquid-state.json"
# User-uploaded background images for custom image skins. Kept beside the state file (a
# per-user, writable, backed-up location) rather than under the read-only bundled assets dir.
SKINS_DIR = APP_DIR / "skins"


def skins_dir() -> Path:
    """Return the custom-skin image directory, creating it on first use."""
    SKINS_DIR.mkdir(parents=True, exist_ok=True)
    return SKINS_DIR


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


def near_highlight_window(near_days: int) -> timedelta:
    """The "near deadline" amber window, with nearHighlightDays clamped to the 1..30 range the
    settings spinbox and state loader enforce (defensive: also clamps a hand-edited state file)."""
    return timedelta(days=max(1, min(30, int(near_days or 1))))


def deadline_alert(raw: str, near_days: int, now: datetime | None = None) -> str:
    """Classify a single deadline string as ``overdue`` / ``near`` / ``normal``.

    ``normal`` covers both an unparseable string and one comfortably in the future. This is the
    single source of truth shared by TodoRow, CalendarRow and the floating launcher's status dot
    so the overdue/near boundary cannot drift between them."""
    now = now or datetime.now()
    deadline = parse_ddl(raw, now)
    if deadline is None:
        return "normal"
    if deadline < now:
        return "overdue"
    return "near" if deadline - now <= near_highlight_window(near_days) else "normal"


@dataclass
class TodoItem:
    id: str = field(default_factory=lambda: str(uuid4()))
    text: str = ""
    ddl: str = ""
    location: str = ""
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
            location=str(data.get("location") or ""),
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
    # Independent position of the floating-launcher bubble. None uses the default position on
    # the primary screen; stale/off-screen values are clamped when the launcher is shown.
    launcherX: int | None = None
    launcherY: int | None = None
    startPosition: str = "topRight"
    visible: bool = True


@dataclass
class CalendarFeed:
    """One ICS/webcal subscription. `enabled` is the per-calendar checkbox: only checked
    feeds are synced and have their events shown in the memo window."""

    id: str = field(default_factory=lambda: str(uuid4()))
    url: str = ""
    name: str = ""  # auto-filled from the feed's X-WR-CALNAME on sync; falls back to the URL
    enabled: bool = True

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CalendarFeed":
        return CalendarFeed(
            id=str(data.get("id") or uuid4()),
            url=str(data.get("url") or ""),
            name=str(data.get("name") or ""),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class CustomSkin:
    """A user-created image-background skin. The selected-skin string for one of these is
    `f"image:{id}"`. `file` is just the filename (no directory) of the cropped PNG under
    `skins_dir()`; it is resolved to an absolute path at render time so the saved state stays
    portable across machines/installs."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    file: str = ""  # filename only, under SKINS_DIR
    fit: str = "cover"  # reserved; only "cover" is implemented today

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CustomSkin":
        return CustomSkin(
            id=str(data.get("id") or uuid4()),
            name=str(data.get("name") or ""),
            file=str(data.get("file") or ""),
            fit=str(data.get("fit") or "cover"),
        )

    def image_path(self) -> Path:
        return SKINS_DIR / self.file


@dataclass
class Settings:
    # Rendering skin. "acrylic" is a lightweight DWM frosted-glass surface (no GPU screen
    # capture) and is the default; "image:<id>" selects a user-created CustomSkin (a static image
    # background, see customSkins). Any unrecognized value normalizes to "acrylic" in from_dict.
    # (The old real-time D3D "glass" skin was removed.)
    skin: str = "acrylic"
    # User-created image-background skins, each selectable as "image:<id>". The built-in
    # acrylic skin is not in this list and cannot be deleted.
    customSkins: list[CustomSkin] = field(default_factory=list)
    windowTint: str = "#FFFFFF"
    todoTextColor: str = "#111820"
    urgentTextColor: str = "#FF0000"
    fontColorMode: str = "autoEnhanced"
    completeBehavior: str = "archive"
    layerMode: str = "alwaysVisibleClickThrough"
    startWithWindows: bool = False
    # Window presentation: regular memo, edge-docked auto-hide, or a small floating launcher
    # that opens the memo on demand. Older edgeAutoHide states migrate in AppState.from_dict.
    windowMode: str = "edgeHide"
    # When False (default) the memo / launcher / note dialog opt out of screen capture
    # (WDA_EXCLUDEFROMCAPTURE), so screenshots and recordings of the desktop don't grab them.
    # Set True to let them appear in captures (drives window_layer.set_capture_exclusion).
    allowScreenshot: bool = False
    # Calendar subscription: when enabled, the widget syncs the next `calendarSyncDays` days of
    # events from the checked ICS/webcal feeds and shows them in a separate "日程" group.
    # Deleted feeds move to `calendarFeedArchive` so an accidental deletion can be restored.
    calendarEnabled: bool = False
    calendarFeeds: list[CalendarFeed] = field(default_factory=list)
    calendarFeedArchive: list[CalendarFeed] = field(default_factory=list)
    calendarSyncDays: int = 7
    # System reminders: when enabled, a background scan pops a native Windows toast
    # (tray balloon) `notifyMinutesBefore` minutes before a calendar event or a todo's
    # deadline. All-day events instead remind once on the day (see notify_manager).
    notificationsEnabled: bool = False
    notifyMinutesBefore: int = 15
    # Days before a deadline/event start when its time cell turns amber ("near"). Applies to
    # both todo DDLs and subscribed calendar events; overdue stays red regardless. 1 == the
    # original fixed 24h window.
    nearHighlightDays: int = 1
    # Version of the app on its previous run; when it differs from the current
    # APP_VERSION the app shows the new version's changelog once after an update.
    lastRunVersion: str = ""
    # Set to the target version just before an in-app update installs; cleared on the
    # next launch. If the running version did not advance, the install failed and the
    # app surfaces an "update failed" notice (see update_ui.UpdateManager.on_startup).
    pendingUpdateVersion: str = ""
    # Auto-update preferences. When `autoCheckUpdates` is off the app only checks when the
    # user clicks "检查更新". The silent startup check is throttled to once every few hours
    # (see update_ui) using `lastUpdateCheckAt` (ISO-8601 UTC). `lastDismissedUpdateVersion`
    # remembers the version the user clicked "稍后再说" on, so a silent check won't re-prompt
    # for it across runs until a newer version appears (a manual check always prompts).
    autoCheckUpdates: bool = True
    lastUpdateCheckAt: str = ""
    lastDismissedUpdateVersion: str = ""
    surpriseEnabled: bool = False
    surpriseKeyBlob: str = ""
    preSurpriseWindowMode: str = ""
    preSurpriseSkin: str = ""
    surpriseCompletedDate: str = ""
    surpriseNoteDate: str = ""
    surpriseNoteIndex: int = -1
    surpriseNoteTheme: str = "qinghua"

    def active_calendar_feeds(self) -> list[CalendarFeed]:
        """Feeds that are checked and have a URL — the only ones synced and displayed."""
        return [feed for feed in self.calendarFeeds if feed.enabled and feed.url.strip()]

    def active_custom_skin(self) -> "CustomSkin | None":
        """The CustomSkin selected by `skin` ("image:<id>"), or None for a built-in skin."""
        if not self.skin.startswith("image:"):
            return None
        skin_id = self.skin[len("image:"):]
        return next((s for s in self.customSkins if s.id == skin_id), None)


@dataclass
class CalendarEvent:
    uid: str = ""
    summary: str = ""
    start: str = ""  # ISO local datetime (or date for all-day)
    location: str = ""  # from the ICS LOCATION field; "" when absent
    allDay: bool = False
    # Stable identity for one occurrence (a recurring series yields one key per instance), used
    # to remember which events the user checked off across re-syncs. Feed-scoped, so the same
    # event arriving from two subscriptions cannot collide.
    key: str = ""
    feedId: str = ""  # owning CalendarFeed.id; display filters on the feed's checkbox

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CalendarEvent":
        uid = str(data.get("uid") or "")
        start = str(data.get("start") or "")
        return CalendarEvent(
            uid=uid,
            summary=str(data.get("summary") or ""),
            start=start,
            location=str(data.get("location") or ""),
            allDay=bool(data.get("allDay", False)),
            key=str(data.get("key") or f"{uid}|{start}"),
            feedId=str(data.get("feedId") or ""),
        )


@dataclass
class AppState:
    version: int = 6
    settings: Settings = field(default_factory=Settings)
    window: WindowState = field(default_factory=WindowState)
    todos: list[TodoItem] = field(default_factory=list)
    history: list[TodoItem] = field(default_factory=list)
    # Calendar cache + state, all persisted so a relaunch shows last-synced events offline.
    calendarEvents: list[CalendarEvent] = field(default_factory=list)
    calendarDoneKeys: list[str] = field(default_factory=list)
    calendarLastSync: str | None = None
    calendarLastError: str | None = None
    # Keys (calendar event / todo) the reminder scan has already toasted, so a fired
    # reminder is not repeated on the next scan or after a relaunch.
    notifiedKeys: list[str] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AppState":
        settings_defaults = asdict(Settings())
        window_defaults = asdict(WindowState())
        settings_data = dict(data.get("settings") or {})
        window_data = dict(data.get("window") or {})
        settings = Settings(**{key: settings_data.get(key, value) for key, value in settings_defaults.items()})
        # v4 -> v5: replace the edge-auto-hide boolean with one explicit three-way mode. Preserve
        # existing behavior exactly for upgraded users; new installs default to edgeHide above.
        if "windowMode" not in settings_data:
            settings.windowMode = "edgeHide" if bool(settings_data.get("edgeAutoHide", True)) else "normal"
        if settings.windowMode not in {"normal", "edgeHide", "floatingLauncher"}:
            settings.windowMode = "edgeHide"
        if settings.layerMode != "alwaysVisibleClickThrough":
            settings.layerMode = "alwaysVisibleClickThrough"
        # The generic loop above leaves dataclass lists as raw dicts; rebuild them typed
        # (customSkins first so the skin whitelist below can validate an "image:<id>" against it).
        settings.customSkins = [CustomSkin.from_dict(item) for item in settings_data.get("customSkins") or []]
        # The "glass" (real-time D3D liquid-glass) skin was removed; it is intentionally absent
        # from valid_skins so any saved "glass" selection normalizes back to the frost skin below.
        # "surprise_swirl" is a valid stored value so an active surprise session survives a restart,
        # but it only ever *renders* / appears in the picker while surprise mode is active (gated in
        # MemoWindow._make_skin and SettingsWindow._refresh_skin_combo, both keyed on the decrypted
        # payload) — so it cannot leak to a normal user even by hand-editing this file.
        valid_skins = {"acrylic", "surprise_swirl"} | {f"image:{s.id}" for s in settings.customSkins}
        if settings.skin not in valid_skins:
            settings.skin = "acrylic"
        settings.calendarSyncDays = max(1, min(30, int(settings.calendarSyncDays or 7)))
        settings.allowScreenshot = bool(settings.allowScreenshot)
        settings.notificationsEnabled = bool(settings.notificationsEnabled)
        settings.autoCheckUpdates = bool(settings.autoCheckUpdates)
        settings.notifyMinutesBefore = max(1, min(1440, int(settings.notifyMinutesBefore or 15)))
        settings.nearHighlightDays = max(1, min(30, int(settings.nearHighlightDays or 1)))
        settings.surpriseEnabled = bool(settings.surpriseEnabled)
        try:
            settings.surpriseNoteIndex = int(settings.surpriseNoteIndex)
        except (TypeError, ValueError):
            settings.surpriseNoteIndex = -1
        if settings.surpriseNoteTheme not in {"qinghua", "warm", "blush"}:
            settings.surpriseNoteTheme = "qinghua"
        settings.calendarFeeds = [CalendarFeed.from_dict(item) for item in settings_data.get("calendarFeeds") or []]
        settings.calendarFeedArchive = [CalendarFeed.from_dict(item) for item in settings_data.get("calendarFeedArchive") or []]
        window = WindowState(**{key: window_data.get(key, value) for key, value in window_defaults.items()})
        todos = [TodoItem.from_dict(item) for item in data.get("todos") or []]
        history = [TodoItem.from_dict(item) for item in data.get("history") or []]
        events = [CalendarEvent.from_dict(item) for item in data.get("calendarEvents") or []]
        done_keys = [str(key) for key in data.get("calendarDoneKeys") or []]
        notified_keys = [str(key) for key in data.get("notifiedKeys") or []]
        # v3 -> v4 migration: the single `calendarUrl` string becomes the first feed; cached
        # events and done-keys are retagged to the new feed-scoped identity so nothing is lost.
        legacy_url = str(settings_data.get("calendarUrl") or "").strip()
        if legacy_url and not settings.calendarFeeds:
            feed = CalendarFeed(url=legacy_url)
            settings.calendarFeeds = [feed]
            for event in events:
                if not event.feedId:
                    event.feedId = feed.id
                    event.key = f"{feed.id}|{event.key}"
            done_keys = [f"{feed.id}|{key}" for key in done_keys]
        return AppState(
            version=6,
            settings=settings,
            window=window,
            todos=todos,
            history=history,
            calendarEvents=events,
            calendarDoneKeys=done_keys,
            calendarLastSync=data.get("calendarLastSync"),
            calendarLastError=data.get("calendarLastError"),
            notifiedKeys=notified_keys,
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
