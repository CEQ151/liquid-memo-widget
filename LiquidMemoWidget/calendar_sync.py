"""ICS calendar subscription: fetch a feed and expand it into local-time events.

Kept Qt-free so it can run on a background worker thread and be unit-tested offline.
"""
from __future__ import annotations

import urllib.request
from datetime import date, datetime, timedelta

import icalendar
import recurring_ical_events

from state_store import CalendarEvent

_USER_AGENT = "DesktopMemo-Pro/1.0 (+calendar-subscription)"
_TIMEOUT = 10
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap to avoid pathological feeds


def normalize_url(url: str) -> str:
    """webcal(s):// is just http(s):// for fetching."""
    url = (url or "").strip()
    if url.lower().startswith("webcals://"):
        return "https://" + url[len("webcals://"):]
    if url.lower().startswith("webcal://"):
        return "https://" + url[len("webcal://"):]
    return url


def fetch_ics(url: str, timeout: int = _TIMEOUT) -> str:
    """GET the ICS text. Raises on empty URL, http, or network error."""
    target = normalize_url(url)
    if not target:
        raise ValueError("订阅链接为空")
    if not target.lower().startswith(("http://", "https://")):
        raise ValueError("订阅链接必须以 http(s):// 或 webcal:// 开头")
    request = urllib.request.Request(target, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise ValueError("日历文件过大（超过 5MB）")
    return raw.decode("utf-8", errors="replace")


def _to_local(value: datetime | date) -> tuple[str, bool]:
    """Return (ISO string, all_day). Aware datetimes convert to local; dates are all-day."""
    if isinstance(value, datetime):
        local = value.astimezone() if value.tzinfo is not None else value
        return local.strftime("%Y-%m-%d %H:%M"), False
    # date (all-day event)
    return value.strftime("%Y-%m-%d"), True


def parse_events(ics_text: str, days: int, now: datetime | None = None) -> list[CalendarEvent]:
    """Expand VEVENTs (incl. RRULE) falling within [now, now + days) into local-time events."""
    now = now or datetime.now()
    days = max(1, min(30, int(days)))
    window_end = now + timedelta(days=days)

    calendar = icalendar.Calendar.from_ical(ics_text)
    occurrences = recurring_ical_events.of(calendar).between(now, window_end)

    events: list[CalendarEvent] = []
    seen: set[str] = set()
    for component in occurrences:
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        start_iso, all_day = _to_local(dtstart.dt)
        summary = str(component.get("SUMMARY") or "（无标题）").strip()
        uid = str(component.get("UID") or summary)
        key = f"{uid}|{start_iso}"
        if key in seen:
            continue
        seen.add(key)
        events.append(CalendarEvent(uid=uid, summary=summary, start=start_iso, allDay=all_day, key=key))

    events.sort(key=lambda event: event.start)
    return events
