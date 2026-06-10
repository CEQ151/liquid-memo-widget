from __future__ import annotations

import ctypes
from ctypes import wintypes


user32 = ctypes.windll.user32

GetWindowLongW = user32.GetWindowLongW
GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLongW.restype = wintypes.LONG

SetWindowLongW = user32.SetWindowLongW
SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
SetWindowLongW.restype = wintypes.LONG

GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000

HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
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

GetWindowRect = user32.GetWindowRect
GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
GetWindowRect.restype = wintypes.BOOL

GetParent = user32.GetParent
GetParent.argtypes = [wintypes.HWND]
GetParent.restype = wintypes.HWND


def apply_tool_window(hwnd: int) -> None:
    styles = GetWindowLongW(hwnd, GWL_EXSTYLE)
    styles |= WS_EX_TOOLWINDOW
    styles &= ~WS_EX_APPWINDOW
    SetWindowLongW(hwnd, GWL_EXSTYLE, ctypes.c_long(styles & 0xFFFFFFFF).value)


def set_topmost(hwnd: int, enabled: bool = True) -> None:
    insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
    user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)


def detach_from_parent(hwnd: int) -> None:
    # No-op fast path: once the window is a detached top-level popup, re-running the
    # restyle + SetWindowPos(SWP_FRAMECHANGED) below forces a non-client recalculation and
    # makes the window flicker. apply_settings() runs on every slider tick, so guard it.
    styles = GetWindowLongW(hwnd, GWL_STYLE)
    if (styles & WS_CHILD) == 0 and (styles & WS_POPUP) != 0 and not GetParent(hwnd):
        return
    rect = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    styles &= ~WS_CHILD
    styles |= WS_POPUP | WS_VISIBLE
    SetWindowLongW(hwnd, GWL_STYLE, ctypes.c_long(styles & 0xFFFFFFFF).value)
    user32.SetParent(hwnd, 0)
    user32.SetWindowPos(hwnd, HWND_TOP, rect.left, rect.top, width, height, SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED)


def begin_system_move(hwnd: int) -> None:
    ReleaseCapture()
    SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
