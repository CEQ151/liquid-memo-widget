from __future__ import annotations

import sys
import winreg
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "LiquidMemoWidget"


def _command() -> str:
    exe = Path(sys.executable)
    script = Path(sys.argv[0]).resolve()
    if exe.name.lower().endswith(".exe") and script.suffix.lower() != ".py":
        return f'"{exe}"'
    return f'"{exe}" "{script}"'


def _read_startup_command() -> str | None:
    """The current Run value's command string, or None when auto-start is not enabled."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except FileNotFoundError:
        return None


def set_startup(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def is_startup_enabled() -> bool:
    return _read_startup_command() is not None


def reconcile_startup() -> None:
    """Re-point the auto-start entry at the running exe when it has drifted.

    The Run value stores an absolute exe path but its name is fixed, so different builds of the
    app (portable vs. installed) share one entry. If a portable build enabled auto-start and the
    user later installs and runs the setup build — or moves/deletes whatever build the entry
    points at — the stored path goes stale or dead (boot then launches the wrong copy, or
    silently nothing, while the settings toggle still reads "on"). On launch the running build
    re-claims the entry so auto-start always points at a valid, currently-used exe.

    No-op when auto-start is off, when the path already matches, or for an unfrozen source/dev
    run — the latter must never repoint a real install's entry at `python + script`."""
    if not getattr(sys, "frozen", False):
        return
    try:
        current = _read_startup_command()
        if current is not None and current != _command():
            set_startup(True)
    except OSError:
        pass
