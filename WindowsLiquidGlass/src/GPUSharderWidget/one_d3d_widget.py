"""
OneGPUWidget —— 屏幕截图 + D3D11 特效显示组件
使用组合模式：内部持有 GPUD3DWidget 作为子控件
不含 GPU 管理器、截图、GPUEffectRenderer 特效等业务逻辑，由 OneGPUWidget 实现
"""

import sys
import os
import ctypes
from ctypes import wintypes
from typing import List

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

try:
    from .gpu_d3d_widget import GPUD3DWidget
    from ..GPUDeviceManager import GPUDeviceManager, GPUPreference
    from ..AppleRoundedRect import AppleRoundedRectGPU
    from ..GPUEffectRenderer import GPUEffectRenderer, EffectType, EFFECTS_PARAMS, EFFECT_TYPE_MAPPING
except ImportError:
    sys.path.append("d:/git")
    from WindowsLiquidGlass.src.GPUSharderWidget.gpu_d3d_widget import GPUD3DWidget
    from WindowsLiquidGlass.src.GPUDeviceManager import GPUDeviceManager, GPUPreference
    from WindowsLiquidGlass.src.AppleRoundedRect import AppleRoundedRectGPU
    from WindowsLiquidGlass.src.GPUEffectRenderer import GPUEffectRenderer, EffectType, EFFECTS_PARAMS, EFFECT_TYPE_MAPPING

WDA_NONE               = 0x00000000
WDA_MONITOR            = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011
WM_MOVING              = 0x0216
WM_MOVE                = 0x0003
WM_NCHITTEST           = 0x0084
HTCAPTION              = 2
HTTRANSPARENT          = -1

user32 = ctypes.windll.user32
SetWindowDisplayAffinity = user32.SetWindowDisplayAffinity
SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
SetWindowDisplayAffinity.restype  = wintypes.BOOL


def set_window_exclude_from_capture(widget, exclude=True):
    """设置窗口是否被屏幕截图捕获（内部自动取顶层窗口）。"""
    if not widget:
        return False
    top = widget.window()
    if not top or not top.winId():
        return False
    hwnd     = int(top.winId())
    affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
    return bool(SetWindowDisplayAffinity(hwnd, affinity))



class OneGPUWidget(QWidget):
    """
    屏幕截图 + D3D11 特效显示组件。
    截图区域由窗口当前位置和尺寸决定，随窗口移动/缩放自动更新。
    内部使用 GPUD3DWidget 作为组合子控件（而非继承）。

    用法：
        widget = OneGPUWidget()
        widget.update_sdf(width=512, height=512, radius_ratio=1.0, scale=0.9) # 生成圆角矩形 SDF，并固定窗口尺寸
        widget.set_capture_source(display_index=0)
        widget.start(fps=60) # 启动帧循环，对于静态背景可以不设置
        widget.cleanup()
    """

    def __init__(self, parent=None, mgr: GPUDeviceManager = None, qt_move=True) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        # 设置背景透明
        #self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        # D3D 子控件：填满整个 OneGPUWidget
        self._d3d = GPUD3DWidget(self)
        self._d3d.setGeometry(0, 0, self.width(), self.height())

        # OneGPUWidget 自持 QTimer，仿照 OneOpenGLWidget 的工作模式。
        # 不使用 GPUD3DWidget._timer，避免 PySide2 下 GPUD3DWidget.start() 因
        # _capture_w/_capture_h==0（零尺寸子控件 isVisible() 为 False 导致
        # _init_presenter 未执行）而直接返回，timer 从未启动的问题。
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_frame)
        
        self._mgr      = mgr if mgr else GPUDeviceManager()
        self._sdf      = None
        self._fx       = GPUEffectRenderer(self._mgr)
        self._fx_ready = False
        self._sdf_id:      int  = 0
        self._has_effects: bool = False

        self._display_index: int = 0
        self._display_left:  int = 0
        self._display_top:   int = 0
        self._capture_tag:   str = "OneGPUWidget"
        self._resource_id:   int = 0

        self._pending_x: int = 0
        self._pending_y: int = 0
        self._fps:        int = 0   # 记录最近一次 start() 请求的 fps，用于 presenter 延迟创建后自动启动定时器
        self._frame_count: int = 0  # debug 用：帧计数
        self._last_display_id: int = 0  # 上一帧成功 present 的纹理 ID（截图/特效任一失败时直接复用）

        if not self._mgr.initialize(GPUPreference.AUTO):
            print("[OneGPUWidget] ❌ GPU 初始化失败")
            return
        if not self._mgr.initialize_display_capture():
            print("[OneGPUWidget] ❌ 显示捕获初始化失败")
            return

        self._sdf = AppleRoundedRectGPU(gpu_manager=self._mgr)

        device_ptr  = self._mgr.get_main_device()
        context_ptr = self._mgr.get_main_context()
        if self._fx.initialize(device_ptr, context_ptr):
            self._fx_ready = True
        else:
            print(f"[OneGPUWidget] ⚠️ 特效渲染器初始化失败: {self._fx.get_last_error()}")

        # 🎯 拖动相关变量
        self.qt_move = qt_move
        self._dragging = False
        self._drag_start_position = QPoint()
        self._drag_start_widget_position = QPoint()

        self.container = None
        """用于给其他组件提供父级容器，自动跟随 OneGPUWidget 移动/缩放。
        仅 PySide6 可用，PySide2 受限于 WA_TranslucentBackground 在D3D背景上无法透明。"""
        if PYSIDE_VERSION == 6:
            self.container = QWidget(self)
            self.container.setStyleSheet("background: transparent;")
            self.container.setAttribute(Qt.WA_TranslucentBackground)
            self.container.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
            self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
    # ── 公开 API ──────────────────────────────────────────────────────────────

    def set_capture_source(
        self,
        display_index: int = 0,
        tag: str = "OneGPUWidget",
    ) -> None:
        """
        设置截图来源（显示器索引和标签）。
        截图区域完全由窗口当前位置和尺寸决定，随窗口移动/缩放自动更新。
        """
        self._display_index = display_index
        self._capture_tag   = tag

        bounds = self._mgr.get_display_bounds(display_index)
        if bounds:
            self._display_left = bounds['left']
            self._display_top  = bounds['top']
        else:
            self._display_left = 0
            self._display_top  = 0

        if self._resource_id:
            self._mgr.remove_resource(self._resource_id)
            self._resource_id = 0

        w, h = self.width(), self.height()
        if w > 0 and h > 0:
            self._d3d._init_presenter(self._mgr, w, h)
            self._update_pending_pos()

    def start(self, fps: int = 60) -> None:
        """启动帧循环。对于静态背景可以不设置"""
        self._fps = fps
        self._timer.start(min(max(1, round(1000 / fps)), 115))

    def stop(self) -> None:
        """暂停帧循环。"""
        self._timer.stop()

    def update_sdf(self, width: int, height: int,
                   radius_ratio: float = 0.5, scale: float = 0.8) -> bool:
        """
        生成圆角矩形 SDF，并将窗口固定为对应尺寸。
        必须在 show() 之后调用一次，特效才能正确对齐。
        """
        if not self._sdf:
            return False
        self._sdf_id = self._sdf.generate_sdf_id(
            width, height, radius_ratio=radius_ratio, scale=scale
        )
        if not self._sdf_id:
            return False
        self.setFixedSize(width, height)
        # padding = int(min(width, height) * (1 - scale) / 2)
        if self.container is not None:
            self.container.setFixedSize(width, height)
        return True

    def enable_effects(self, effects: List[EffectType]) -> None:
        """
        启用指定特效列表，未指定的自动关闭。空列表关闭所有特效。
        用法与 OneOpenGLWidget.enable_effects 完全一致。
        """
        if not self._fx_ready:
            return
        if not effects:
            self._has_effects = False
            self._fx.enable_effects([])
            return
        self._fx.enable_effects(effects)
        self._has_effects = True

    def update_effects(self, effects_params: dict) -> None:
        """
        更新特效参数。参数格式详见 GPUEffectRenderer/src/effects_params.py。
        用法与 OneOpenGLWidget.update_effects 完全一致。
        """
        if not self._fx_ready:
            return
        self._fx.update_effects(effects_params)

    @property
    def effect(self) -> GPUEffectRenderer:
        return self._fx

    def cleanup(self) -> None:
        self._timer.stop()
        self._d3d.cleanup()
        if self._resource_id:
            self._mgr.remove_resource(self._resource_id)
            self._resource_id = 0
        if self._fx_ready:
            self._fx.shutdown()
            self._fx_ready = False
        # 必须在 _mgr.shutdown() 之前销毁 SDF（否则 DLL 内部上下文已释放时 __del__ 报访问违规）
        if self._sdf:
            self._sdf.cleanup()
            self._sdf = None
        self._mgr.shutdown_display_capture()
        self._mgr.shutdown()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # show() 之前调用 set_capture_source() 时，widget 尚无尺寸，
        # _init_presenter 可能未被执行（_d3d._gpu_mgr = None）。
        # 在这里补充调用，确保 presenter / 子窗口一定被创建。
        w, h = self.width(), self.height()
        if not self._d3d._presenter_id:
            if w > 0 and h > 0:
                self._d3d._init_presenter(self._mgr, w, h)
        self._update_pending_pos()
        QTimer.singleShot(0, lambda: set_window_exclude_from_capture(self.window(), exclude=True))

    def closeEvent(self, event) -> None:
        self.stop()
        self.cleanup()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        # 同步 D3D 子控件尺寸
        self._d3d.setGeometry(0, 0, w, h)
        self._update_pending_pos()
        if w > 0 and h > 0:
            if not self._d3d._presenter_id:
                # 首次获得有效尺寸（例如 setFixedSize 在 show 之后调用）
                if self.isVisible():
                    self._d3d._init_presenter(self._mgr, w, h)
                    # start() 可能在 presenter 创建之前调用过，定时器未启动，补回
                    if self._fps and not self._timer.isActive():
                        self._timer.start(min(max(1, round(1000 / self._fps)), 115))
            elif w != self._d3d._capture_w or h != self._d3d._capture_h:
                if self._resource_id:
                    self._mgr.remove_resource(self._resource_id)
                    self._resource_id = 0
                self._d3d._init_presenter(self._mgr, w, h)
        self._on_frame()

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if not self.qt_move:
            return super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start_position = self._get_global_pos(event)
            self._drag_start_widget_position = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if not self.qt_move:
            return super().mouseMoveEvent(event)
        if self._dragging and event.buttons() & Qt.LeftButton:
            mouse_delta = self._get_global_pos(event) - self._drag_start_position
            new_position = self._drag_start_widget_position + mouse_delta

            if self.parent():
                parent_rect = self.parent().rect()
                widget_rect = QRect(new_position, self.size())

                if new_position.x() < 0:
                    new_position.setX(0)
                if new_position.y() < 0:
                    new_position.setY(0)
                if widget_rect.right() > parent_rect.right():
                    new_position.setX(parent_rect.right() - self.width())
                if widget_rect.bottom() > parent_rect.bottom():
                    new_position.setY(parent_rect.bottom() - self.height())

            self._pending_x = new_position.x() - self._display_left
            self._pending_y = new_position.y() - self._display_top
            self._on_frame()
            self.move(new_position)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if not self.qt_move:
            return super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
        super().mouseReleaseEvent(event)

    @staticmethod
    def _get_global_pos(event) -> QPoint:
        """兼容 PySide2 / PySide6 获取鼠标全局坐标"""
        if PYSIDE_VERSION == 6:
            return event.globalPosition().toPoint()
        else:
            return event.globalPos()


    def nativeEvent(self, event_type, message):
        """
        拦截 WM_NCHITTEST 和 WM_MOVING。

        未绑定伴随控件时：返回 HTCAPTION 使整个客户区都是可拖动区域，
        Windows 进入内置 modal 移动循环，触发 WM_MOVING。
        WM_MOVING：在窗口实际移动前预先截图并 present，彻底消除拖动拖影。
        """
        if self.qt_move:
            return super().nativeEvent(event_type, message)
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_NCHITTEST:
                return True, HTCAPTION
        
            if msg.message == WM_MOVING:
                rect = ctypes.cast(msg.lParam, ctypes.POINTER(wintypes.RECT)).contents
                border_x = self.geometry().left()  - self.frameGeometry().left()
                border_y = self.geometry().top()   - self.frameGeometry().top()
                self._pending_x = rect.left + border_x - self._display_left
                self._pending_y = rect.top  + border_y - self._display_top
                self._on_frame()
            if msg.message == WM_MOVE:
                # 系统强制拉回后窗口实际位置已变，重新同步坐标
                QTimer.singleShot(0, self._update_pending_pos)
        return super().nativeEvent(event_type, message)

    # def paintEvent(self, event) -> None:
    #     painter = QPainter(self)
    #     painter.fillRect(self.rect(), QColor(0, 0, 0, 30))
    #     painter.end()

    # ── 内部 ─────────────────────────────────────────────────────────────────

    def _update_pending_pos(self) -> None:
        """将窗口当前屏幕位置换算为显示器局部坐标，存入 _pending_x/_pending_y。
        自动跟踪窗口所在的显示器，更新 _display_index/_display_left/_display_top。"""
        global_pos = self.mapToGlobal(QPoint(0, 0))
        center_x = global_pos.x() + self.width() // 2
        center_y = global_pos.y() + self.height() // 2

        # 自动检测窗口中心所在的显示器
        display_count = self._mgr.get_display_count()
        for i in range(display_count):
            bounds = self._mgr.get_display_bounds(i)
            if bounds:
                if (bounds['left'] <= center_x < bounds['right'] and
                        bounds['top'] <= center_y < bounds['bottom']):
                    self._display_index = i
                    self._display_left  = bounds['left']
                    self._display_top   = bounds['top']
                    break

        _pending_x = global_pos.x() - self._display_left
        _pending_y = global_pos.y() - self._display_top
        if _pending_x != self._pending_x or _pending_y != self._pending_y:
            self._pending_x = _pending_x
            self._pending_y = _pending_y
            QTimer.singleShot(0, self._on_frame)

    # ── 帧循环 ────────────────────────────────────────────────────────────────

    def _on_frame(self) -> None:
        if not self._d3d._presenter_id:
            return
        if self._d3d._capture_w <= 0 or self._d3d._capture_h <= 0:
            return
        
        new_id = self._mgr.capture_display_region(
            display_index = self._display_index,
            x             = self._pending_x,
            y             = self._pending_y,
            width         = self._d3d._capture_w,
            height        = self._d3d._capture_h,
            tag           = self._capture_tag,
        )
        self._frame_count += 1

        # ── 截图失败：直接复用上一帧已合成好的纹理，跳过特效重渲染 ──────
        if not new_id:
            if self._last_display_id:
                ctypes.windll.dwmapi.DwmFlush()
                self._d3d._present(self._last_display_id)
            return

        if self._resource_id and self._resource_id != new_id:
            self._mgr.remove_resource(self._resource_id)
        self._resource_id = new_id

        # ── 特效处理 ──────────────────────────────────────────────────────
        display_id = self._resource_id
        if self._fx_ready and self._has_effects and self._sdf_id:
            output_id = self._fx.render_effects_by_id(
                screen_resource_id=self._resource_id,
                sdf_resource_id=self._sdf_id,
            )
            if output_id:
                display_id = output_id
            else:
                # 特效渲染失败：直接复用上一帧，避免闪烁
                err = self._fx.get_last_error()
                if err:
                    print(f"[OneGPUWidget] ⚠️ 特效渲染失败: {err}")
                if self._last_display_id:
                    ctypes.windll.dwmapi.DwmFlush()
                    self._d3d._present(self._last_display_id)
                return

        ctypes.windll.dwmapi.DwmFlush()
        self._d3d._present(display_id)
        self._last_display_id = display_id  # 记录本帧成功结果

# ── 测试入口 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    app = QApplication(sys.argv)
    widget = OneGPUWidget() # 第二个实例，测试多实例共存
    widget.set_capture_source(display_index=0)
    widget.show()
    widget.start(fps=60)

    widget.update_sdf(width=500, height=500, radius_ratio=1, scale=0.9)
    widget.enable_effects([
        EffectType.FLOW,
        EffectType.CHROMATIC_ABERRATION,
        EffectType.HIGHLIGHT,
        # EffectType.BLUR,
        EffectType.ANTI_ALIASING,
        EffectType.COLOR_GRADING,
        EffectType.COLOR_OVERLAY,
    ])

    effects_params = EFFECTS_PARAMS.copy()
    effects_params["flow"]["params"]["flow_width"]["value"] = 60
    effects_params["highlight"]["params"]["range"]["value"] = 0.5
    effects_params["highlight"]["params"]["angle"]["value"] = 120

    effects_params["color_grading"]["params"]["saturation"]["value"] = 1.5
    # effects_params["color_grading"]["params"]["contrast"]["value"] = 1.2
    effects_params["color_overlay"]["params"]["color"]["value"] = (1.0, 0.0, 1.0)
    effects_params["color_overlay"]["params"]["strength"]["value"] = 0.1

    widget.update_effects(effects_params)
    app.aboutToQuit.connect(widget.cleanup)
    if PYSIDE_VERSION == 2:
        sys.exit(app.exec_())
    else:
        sys.exit(app.exec())