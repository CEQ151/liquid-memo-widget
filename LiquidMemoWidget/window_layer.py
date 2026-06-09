from __future__ import annotations

import ctypes
from ctypes import wintypes


user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

WM_NCHITTEST = 0x0084
WM_NCLBUTTONDOWN = 0x00A1
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232
HTCLIENT = 1
HTCAPTION = 2
HTTRANSPARENT = -1

ReleaseCapture = user32.ReleaseCapture
ReleaseCapture.argtypes = []
ReleaseCapture.restype = wintypes.BOOL

SendMessageW = user32.SendMessageW
SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
SendMessageW.restype = wintypes.LPARAM


def apply_tool_window(hwnd: int) -> None:
    styles = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    styles |= WS_EX_TOOLWINDOW
    styles &= ~WS_EX_APPWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, styles)


def set_topmost(hwnd: int, enabled: bool = True) -> None:
    insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
    user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)


def detach_from_parent(hwnd: int) -> None:
    user32.SetParent(hwnd, 0)


def begin_system_move(hwnd: int) -> None:
    ReleaseCapture()
    SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)


def set_desktop_layer(hwnd: int) -> bool:
    """Best-effort WorkerW parenting. Returns False when the shell layout is unavailable."""
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return False

    result = wintypes.DWORD()
    user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, ctypes.byref(result))

    workerw = 0

    def enum_windows_proc(top_hwnd, _lparam):
        nonlocal workerw
        shell_view = user32.FindWindowExW(top_hwnd, 0, "SHELLDLL_DefView", None)
        if shell_view:
            workerw = user32.FindWindowExW(0, top_hwnd, "WorkerW", None)
        return True

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_windows_proc)
    user32.EnumWindows(enum_proc, 0)

    target = workerw or progman
    if not target:
        return False

    user32.SetParent(hwnd, target)
    return True
