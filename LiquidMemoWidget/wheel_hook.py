"""Global low-level mouse-wheel hook (Windows WH_MOUSE_LL).

The memo window is click-through (WM_NCHITTEST returns HTTRANSPARENT over non-interactive
areas), and Windows routes wheel messages over an HTTRANSPARENT region to the window *below* —
so the list can only be wheel-scrolled while the cursor happens to sit on an HTCLIENT control.
A low-level mouse hook sees the wheel before any window does, regardless of hit-testing, so we
can scroll the list whenever the cursor is over it while leaving clicks to pass through.

Kept dependency-free (ctypes only) so it can be unit-imported and bundled without extras.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

# Use private WinDLL instances (not the shared ctypes.windll.* singletons): setting argtypes /
# restype below must not leak onto the prototypes the vendored D3D code uses for the same
# functions, or e.g. GetModuleHandleW's restype change corrupts its CreateWindowExW hinstance.
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_MOUSE_LL = 14
WM_MOUSEWHEEL = 0x020A
HC_ACTION = 0

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class GlobalWheelHook:
    """Installs a process-wide low-level mouse hook and forwards wheel notches to `on_wheel`.

    `on_wheel(screen_x, screen_y, delta)` returns True to *consume* the wheel (so the window
    underneath does not also scroll); any other / no return lets the event pass through.
    """

    def __init__(self, on_wheel: Callable[[int, int, int], bool]) -> None:
        self._on_wheel = on_wheel
        self._hook = None
        # Keep a strong reference to the C callback: if it is garbage-collected while the hook
        # is installed, Windows calls into freed memory and crashes the process.
        self._proc = HOOKPROC(self._dispatch)

    def _dispatch(self, n_code, w_param, l_param):
        try:
            if n_code == HC_ACTION and w_param == WM_MOUSEWHEEL:
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                if self._on_wheel(info.pt.x, info.pt.y, delta):
                    return 1  # consume: do not deliver this wheel to the window below
        except Exception:
            # A hook callback must never raise across the ctypes boundary; fall through.
            pass
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def install(self) -> bool:
        if self._hook:
            return True
        module = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, module, 0)
        return bool(self._hook)

    def uninstall(self) -> None:
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
