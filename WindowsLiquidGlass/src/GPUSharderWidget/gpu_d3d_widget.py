"""
GPUD3DWidget —— 纯 D3D11 显示基类
职责：Win32 子窗口 + SwapChain + Qt PreciseTimer 驱动帧循环
不含 GPU 管理器、截图、特效等业务逻辑，由子类实现 _on_frame()
"""

import sys
import os
import ctypes
from typing import Optional

try:
    from PySide6.QtWidgets import *
    from PySide6.QtCore import *
    from PySide6.QtGui import *
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtWidgets import *
    from PySide2.QtCore import *
    from PySide2.QtGui import *
    PYSIDE_VERSION = 2
# ── Win32 ─────────────────────────────────────────────────────────────────────
user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.DefWindowProcW.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.DefWindowProcW.restype = ctypes.c_ssize_t

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
    ctypes.c_size_t, ctypes.c_ssize_t)

WS_CHILD       = 0x40000000
WS_VISIBLE     = 0x10000000
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER   = 0x0004

WM_NCHITTEST    = 0x0084
HTTRANSPARENT   = -1
HTCAPTION       = 2
WM_MOUSEMOVE    = 0x0200
WM_LBUTTONDOWN  = 0x0201
WM_LBUTTONUP    = 0x0202
WM_RBUTTONDOWN  = 0x0204
WM_RBUTTONUP    = 0x0205
WM_MBUTTONDOWN  = 0x0207
WM_MBUTTONUP    = 0x0208
WM_MOUSEWHEEL   = 0x020A
WM_MOVING       = 0x0216

# 鼠标消息集合，需转发给父 Qt 窗口
_MOUSE_MSGS = {
    WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP,
    WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP,
    WM_MOUSEWHEEL,
}

_wnd_proc_ref: Optional[WNDPROC] = None
_class_registered = False


def _ensure_wndclass(hinstance) -> None:
    global _class_registered, _wnd_proc_ref
    if _class_registered:
        return

    def _wnd_proc(hwnd, msg, wparam, lparam):
        # WM_NCHITTEST: 返回 HTTRANSPARENT 让父窗口处理（触发系统拖动等）
        if msg == WM_NCHITTEST:
            return HTTRANSPARENT
        # 鼠标消息：转发给父 Qt HWND（PostMessage 不阻塞 wndproc）
        if msg in _MOUSE_MSGS:
            parent = user32.GetParent(hwnd)
            if parent:
                user32.PostMessageW(parent, msg, wparam, lparam)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    _wnd_proc_ref = WNDPROC(_wnd_proc)

    class WNDCLASSEX(ctypes.Structure):
        _fields_ = [
            ("cbSize",        ctypes.c_uint),
            ("style",         ctypes.c_uint),
            ("lpfnWndProc",   WNDPROC),
            ("cbClsExtra",    ctypes.c_int),
            ("cbWndExtra",    ctypes.c_int),
            ("hInstance",     ctypes.c_void_p),
            ("hIcon",         ctypes.c_void_p),
            ("hCursor",       ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName",  ctypes.c_wchar_p),
            ("lpszClassName", ctypes.c_wchar_p),
            ("hIconSm",       ctypes.c_void_p),
        ]

    wc = WNDCLASSEX()
    wc.cbSize        = ctypes.sizeof(WNDCLASSEX)
    wc.lpfnWndProc   = _wnd_proc_ref
    wc.hInstance     = hinstance
    wc.hbrBackground = ctypes.cast(ctypes.c_void_p(0), ctypes.c_void_p)
    wc.lpszClassName = "GPUD3DChildWnd"
    user32.RegisterClassExW(ctypes.byref(wc))
    _class_registered = True


class GPUD3DWidget(QWidget):
    """
    纯 D3D11 显示基类。

    负责：
      - Win32 子窗口生命周期
      - DXGI SwapChain 创建 / resize / 销毁
      - Qt PreciseTimer 帧循环（调用 _on_frame）

    鼠标事件路由：
      - 内部 Win32 子窗口 WM_NCHITTEST 返回 HTTRANSPARENT
        → 父 Qt HWND 可处理 WM_NCHITTEST（返回 HTCAPTION 则全窗口可拖动）
      - 鼠标点击/移动/滚轮通过 PostMessage 转发给父 Qt HWND
        → Qt 正常触发 mousePressEvent / mouseMoveEvent / wheelEvent 等

    子类只需：
      1. 调用 _init_presenter(gpu_mgr, w, h) 传入设备管理器和尺寸
      2. 覆写 _on_frame() 实现 capture / effect / present 逻辑
      3. 需要时调用 _present(resource_id) 完成显示
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # 由 _init_presenter 赋值
        self._gpu_mgr       = None          # GPUDeviceManager（由子类传入）
        self._child_hwnd:   Optional[int] = None
        self._presenter_id: int = 0
        self._capture_w:    int = 0
        self._capture_h:    int = 0

        # Qt PreciseTimer
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_frame)

    # ── 子类接口 ──────────────────────────────────────────────────────────────

    def _init_presenter(self, gpu_mgr, width: int, height: int) -> bool:
        """
        初始化 SwapChain。子类在准备好 gpu_mgr 后调用。
        """
        self._gpu_mgr    = gpu_mgr
        self._capture_w  = width
        self._capture_h  = height

        if self._child_hwnd:
            # 已存在则只 resize
            user32.SetWindowPos(
                self._child_hwnd, None, 0, 0, width, height,
                SWP_NOACTIVATE | SWP_NOZORDER)
            if self._presenter_id:
                gpu_mgr.resize_presenter(self._presenter_id, width, height)
        elif self.isVisible():
            self._create_child_window()

        return self._presenter_id != 0

    def _present(self, resource_id: int) -> None:
        """将 resource_id 对应的纹理 Present 到屏幕。子类在 _on_frame 中调用。"""
        if self._presenter_id and resource_id:
            self._gpu_mgr.present_resource(self._presenter_id, resource_id)

    def _on_frame(self) -> None:
        """
        每帧回调，由 Qt PreciseTimer 在主线程触发。
        子类覆写此方法实现 capture / effect / present 逻辑。
        """

    # ── 公开控制 API ──────────────────────────────────────────────────────────

    def start(self, fps: int = 60) -> None:
        """启动帧循环。"""
        if not self._capture_w or not self._capture_h:
            print("[D3DWidget] ❌ 请先调用 _init_presenter()")
            return
        # 限制 FPS 在 1~115 范围，过高可能导致系统不稳定
        self._timer.start(min(max(1, round(1000 / fps)), 115))

    def stop(self) -> None:
        """暂停帧循环（不销毁资源）。"""
        self._timer.stop()

    def cleanup(self) -> None:
        """销毁 SwapChain 和 Win32 子窗口，窗口关闭前调用。"""
        self.stop()
        if self._presenter_id and self._gpu_mgr:
            self._gpu_mgr.destroy_presenter(self._presenter_id)
            self._presenter_id = 0
        if self._child_hwnd:
            user32.DestroyWindow(self._child_hwnd)
            self._child_hwnd = None

    # ── Qt 事件 ───────────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._child_hwnd is None and self._gpu_mgr and self._capture_w:
            self._create_child_window()

    def nativeEvent(self, event_type, message):
        # _child_hwnd 的 wndproc 对 WM_NCHITTEST 返回 HTTRANSPARENT，
        # Win32 将消息上传到本 Qt HWND（GPUD3DWidget）；
        # 这里继续返回 HTTRANSPARENT，让消息再上传到父级 OneGPUWidget，
        # OneGPUWidget.nativeEvent 才能返回 HTCAPTION 触发系统拖动。
        if event_type == b"windows_generic_MSG":
            import ctypes, ctypes.wintypes as wt
            msg = ctypes.cast(int(message), ctypes.POINTER(wt.MSG)).contents
            if msg.message == WM_NCHITTEST:
                return True, HTTRANSPARENT
        return super().nativeEvent(event_type, message)

    # ── 内部 ─────────────────────────────────────────────────────────────────

    def _create_child_window(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        _ensure_wndclass(hinstance)

        self._child_hwnd = user32.CreateWindowExW(
            0, "GPUD3DChildWnd", "",
            WS_CHILD | WS_VISIBLE,
            0, 0, self._capture_w, self._capture_h,
            int(self.winId()), None, hinstance, None,
        )
        if not self._child_hwnd:
            print("[D3DWidget] ❌ 子窗口创建失败")
            return

        self._presenter_id = self._gpu_mgr.create_presenter(
            self._child_hwnd, self._capture_w, self._capture_h)
        if not self._presenter_id:
            print("[D3DWidget] ❌ SwapChain 创建失败")