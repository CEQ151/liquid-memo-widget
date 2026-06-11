from __future__ import annotations

import json
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


@dataclass
class TodoItem:
    id: str = field(default_factory=lambda: str(uuid4()))
    text: str = ""
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


@dataclass
class AppState:
    version: int = 2
    settings: Settings = field(default_factory=Settings)
    window: WindowState = field(default_factory=WindowState)
    todos: list[TodoItem] = field(default_factory=list)
    history: list[TodoItem] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AppState":
        settings_defaults = asdict(Settings())
        window_defaults = asdict(WindowState())
        settings_data = dict(data.get("settings") or {})
        window_data = dict(data.get("window") or {})
        settings = Settings(**{key: settings_data.get(key, value) for key, value in settings_defaults.items()})
        if settings.layerMode != "alwaysVisibleClickThrough":
            settings.layerMode = "alwaysVisibleClickThrough"
        window = WindowState(**{key: window_data.get(key, value) for key, value in window_defaults.items()})
        todos = [TodoItem.from_dict(item) for item in data.get("todos") or []]
        history = [TodoItem.from_dict(item) for item in data.get("history") or []]
        return AppState(version=2, settings=settings, window=window, todos=todos, history=history)


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
