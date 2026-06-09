"""
OneOpenGLWidget —— 屏幕截图 + OpenGL 显示组件（独立实现）
使用 WGL_NV_DX_interop 零拷贝（D3D11 纹理直接共享给 OpenGL）。
"""

import sys
import os
import ctypes
from ctypes import wintypes
from typing import Optional, List

import numpy as np

try:
    from PySide6.QtWidgets import *
    from PySide6.QtCore import *
    from PySide6.QtGui import *
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtWidgets import *
    from PySide2.QtCore import *
    from PySide2.QtGui import *
    try:
        from PySide2.QtOpenGLWidgets import QOpenGLWidget
    except ImportError:
        from PySide2.QtWidgets import QOpenGLWidget
    PYSIDE_VERSION = 2

from OpenGL.GL import *
from OpenGL.GL import shaders

try:
    from ..GPUDeviceManager import GPUDeviceManager, GPUPreference, GPUResourceType
    from ..AppleRoundedRect import AppleRoundedRectGPU
    from ..GPUEffectRenderer import GPUEffectRenderer, EffectType
except ImportError:
    sys.path.append("d:/git")
    from WindowsLiquidGlass.src.GPUDeviceManager import GPUDeviceManager, GPUPreference, GPUResourceType
    from WindowsLiquidGlass.src.AppleRoundedRect import AppleRoundedRectGPU
    from WindowsLiquidGlass.src.GPUEffectRenderer import GPUEffectRenderer, EffectType

# DXGI_FORMAT_B8G8R8A8_UNORM = 87
# D3D11_BIND_SHADER_RESOURCE = 0x8, D3D11_BIND_RENDER_TARGET = 0x20
DXGI_FORMAT_B8G8R8A8_UNORM        = 87
D3D11_BIND_SHADER_RESOURCE_AND_RT = 0x8 | 0x20   # 40


# ── Win32 API ─────────────────────────────────────────────────────────────────

WDA_NONE               = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
WM_MOVING              = 0x0216
WM_NCHITTEST           = 0x0084
HTCAPTION              = 2

user32 = ctypes.windll.user32

SetWindowDisplayAffinity = user32.SetWindowDisplayAffinity
SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
SetWindowDisplayAffinity.restype  = wintypes.BOOL


def set_window_exclude_from_capture(widget, exclude=True):
    if not widget:
        return False
    top = widget.window()
    if not top or not top.winId():
        return False
    hwnd     = int(top.winId())
    affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
    return bool(SetWindowDisplayAffinity(hwnd, affinity))


# ── 内嵌 OpenGL 渲染画布 ──────────────────────────────────────────────────────

class _GLCanvas(QOpenGLWidget):

    def __init__(self, mgr: GPUDeviceManager, parent=None):
        super().__init__(parent)
        self._mgr = mgr

        # fmt = QSurfaceFormat()
        # fmt.setVersion(3, 3)
        # fmt.setProfile(QSurfaceFormat.CoreProfile)
        # fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
        # fmt.setSwapInterval(1)
        # fmt.setAlphaBufferSize(8)  # 必须申请 alpha 缓冲，透明像素才能正确输出
        # self.setFormat(fmt)

        self._vao           = 0
        self._vbo           = 0
        self._ebo           = 0
        self._shader        = 0
        self._ready         = False
        self._gl_handle     = None
        self._active_gl_tex = 0

    # ── OpenGL 生命周期 ───────────────────────────────────────────────────────

    def initializeGL(self):
        glClearColor(0.0, 0.0, 0.0, 0.0)  # 透明背景，alpha=0
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self._init_shader()
        self._init_quad()

        if not self._mgr.initialize_gl_interop():
            print("[GLCanvas] ❌ WGL_NV_DX_interop 初始化失败")
            return

        print("[GLCanvas] ✅ 零拷贝模式（WGL_NV_DX_interop）")
        self._ready = True

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)

    def paintGL(self):
        """Qt 驱动的渲染：lock → draw → unlock 在同一 paintGL 调用内完成。"""
        glClear(GL_COLOR_BUFFER_BIT)

        if not self._ready or not self._gl_handle or self._active_gl_tex == 0:
            return

        if not self._mgr.lock_gl_texture(self._gl_handle):
            print("[GLCanvas] ❌ lock_gl_texture 失败")
            return

        glUseProgram(self._shader)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._active_gl_tex)
        glUniform1i(glGetUniformLocation(self._shader, "uTex"), 0)
        glBindVertexArray(self._vao)
        glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

        self._mgr.unlock_gl_texture(self._gl_handle)

    # ── 帧更新 ────────────────────────────────────────────────────────────────

    def set_frame(self, resource_id: int, sync: bool = False):
        """更新要显示的 D3D 资源，sync=True 时同步渲染（repaint），否则异步（update）。"""
        if not self._ready:
            return

        self.makeCurrent()

        if resource_id != getattr(self, '_current_resource_id', 0):
            if self._gl_handle is not None:
                self._mgr.release_gl_texture(self._gl_handle)
                self._gl_handle     = None
                self._active_gl_tex = 0

            handle = self._mgr.create_gl_texture_from_d3d(resource_id)
            if not handle:
                print(f"[GLCanvas] ❌ create_gl_texture_from_d3d({resource_id}) 失败")
                self.doneCurrent()
                return

            self._gl_handle           = handle
            self._active_gl_tex       = self._mgr.get_gl_texture_id(handle)
            self._current_resource_id = resource_id

        self.doneCurrent()

        if sync:
            self.repaint()
        else:
            self.update()

    # ── 清理 ─────────────────────────────────────────────────────────────────

    def save_debug_frame(self, path: str = "debug_gl_frame.png") -> bool:
        """读取当前 OpenGL 帧缓冲像素并保存为 PNG，用于诊断透明是否正确。"""
        if not self._ready or self._active_gl_tex == 0:
            print("[GLCanvas] save_debug_frame: 尚未就绪")
            return False

        self.makeCurrent()

        # 强制渲染一帧到帧缓冲
        self.paintGL()

        w, h = self.width(), self.height()
        # glReadPixels 读 RGBA
        data = glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)
        self.doneCurrent()

        import numpy as np
        from PIL import Image
        arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
        # OpenGL 原点在左下，翻转到左上
        arr = np.flipud(arr)
        img = Image.fromarray(arr, 'RGBA')
        img.save(path)
        print(f"[GLCanvas] ✅ 已保存帧缓冲截图: {path}  (size={w}x{h})")
        return True

    def cleanup_gl(self):
        if not self._ready:
            return
        self.makeCurrent()
        if self._gl_handle is not None:
            self._mgr.release_gl_texture(self._gl_handle)
            self._gl_handle = None
        self._mgr.shutdown_gl_interop()
        if self._vao:
            glDeleteVertexArrays(1, [self._vao])
        if self._vbo:
            glDeleteBuffers(1, [self._vbo])
        if self._ebo:
            glDeleteBuffers(1, [self._ebo])
        if self._shader:
            glDeleteProgram(self._shader)
        self.doneCurrent()
        self._ready = False

    # ── 内部初始化 ────────────────────────────────────────────────────────────

    def _init_shader(self):
        vert = """
        #version 330 core
        layout(location=0) in vec2 aPos;
        layout(location=1) in vec2 aUV;
        out vec2 vUV;
        void main() { gl_Position = vec4(aPos, 0.0, 1.0); vUV = aUV; }
        """
        frag = """
        #version 330 core
        in vec2 vUV;
        out vec4 FragColor;
        uniform sampler2D uTex;
        void main() { FragColor = texture(uTex, vUV); }
        """
        vs = shaders.compileShader(vert, GL_VERTEX_SHADER)
        fs = shaders.compileShader(frag, GL_FRAGMENT_SHADER)
        self._shader = shaders.compileProgram(vs, fs)

    def _init_quad(self):
        verts = np.array([
            -1.0, -1.0,  0.0, 1.0,
             1.0, -1.0,  1.0, 1.0,
             1.0,  1.0,  1.0, 0.0,
            -1.0,  1.0,  0.0, 0.0,
        ], dtype=np.float32)
        idx = np.array([0, 1, 2, 2, 3, 0], dtype=np.uint32)

        self._vao = glGenVertexArrays(1)
        glBindVertexArray(self._vao)
        self._vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_STATIC_DRAW)
        self._ebo = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(8))
        glEnableVertexAttribArray(1)
        glBindVertexArray(0)


# ── 主组件 ────────────────────────────────────────────────────────────────────

class OneOpenGLWidget(QWidget):
    """
    屏幕截图 + OpenGL 显示组件。

    用法：
        widget = OneOpenGLWidget()
        widget.resize(1280, 720)
        widget.set_capture_source(display_index=0)
        widget.start(fps=60)
        widget.cleanup()
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self._drag_pos: Optional[QPoint] = None
        self._pending_capture_x: Optional[int] = None  # WM_MOVING 预截图坐标
        self._pending_capture_y: Optional[int] = None

        self._mgr      = GPUDeviceManager()
        if not self._mgr.initialize(GPUPreference.AUTO):
            print("[OneOpenGLWidget] ❌ GPU 初始化失败")
            return

        self._sdf      = AppleRoundedRectGPU(gpu_manager=self._mgr)
        self._fx       = GPUEffectRenderer(gpu_mgr=self._mgr)
        

        self._display_index: int = 0
        self._display_left:  int = 0
        self._display_top:   int = 0
        self._capture_tag:   str = "OneOpenGLWidget"
        self._sdf_id:        int = 0
        self._resource_id:   int = 0
        self._output_id:     int = 0   # 特效输出纹理，与窗口同尺寸，提前建好
        self._timer:         Optional[QTimer] = None


        if not self._mgr.initialize_display_capture():
            print("[OneOpenGLWidget] ❌ 显示捕获初始化失败")
            return

        device_ptr  = self._mgr.get_main_device()
        context_ptr = self._mgr.get_main_context()
        self._fx.initialize(device_ptr, context_ptr)
        self._fx_ready = True
        self._has_enffects = False

        self._canvas = _GLCanvas(self._mgr, self)
        self._canvas.setGeometry(0, 0, self.width(), self.height())
        self._canvas.lower()
        self._canvas.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def update_sdf(self, width: int, height: int, radius_ratio: float = 0.5, scale: float = 0.8) -> bool:
        if not self._sdf:
            return False
        self._sdf_id = self._sdf.generate_sdf_id(width, height, radius_ratio=radius_ratio, scale=scale)
        if self._sdf_id == 0:
            return False
        
        self.setFixedSize(width, height)
        return True

    def enable_effects(self, effects: List[EffectType]):
        """启用/禁用描边特效"""
        if not self._fx_ready:
            return
        if not effects:
            self._has_enffects = False
            self._fx.enable_effects([])
            return
        self._fx.enable_effects(effects)
        self._has_enffects = True


    # ── 公开 API ──────────────────────────────────────────────────────────────

    def set_capture_source(self, display_index: int = 0, tag: str = "OneOpenGLWidget") -> None:
        self._display_index = display_index
        self._capture_tag   = tag

        bounds = self._mgr.get_display_bounds(display_index)
        if bounds:
            self._display_left = bounds['left']
            self._display_top  = bounds['top']
        else:
            self._display_left = 0
            self._display_top  = 0

    def start(self, fps: int = 60) -> None:
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(max(1, round(1000 / fps)))

    def stop(self) -> None:
        if self._timer:
            self._timer.stop()

    @property
    def effect(self) -> GPUEffectRenderer:
        return self._fx

    def save_debug_frame(self, path: str = "debug_gl_frame.png") -> bool:
        """保存当前 GL 帧缓冲截图，方便诊断透明 / 纹理内容问题。"""
        return self._canvas.save_debug_frame(path)

    def cleanup(self) -> None:
        self.stop()
        self._canvas.cleanup_gl()
        if self._resource_id:
            self._mgr.remove_resource(self._resource_id)
            self._resource_id = 0
        if self._fx_ready:
            self._fx.shutdown()  # 内部调用 cleanup_output_cache
            self._fx_ready = False
        self._mgr.shutdown_display_capture()
        self._mgr.shutdown()

    # ── Qt 事件 ───────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        pass  # 拖动由 WM_NCHITTEST/HTCAPTION 系统接管，无需 Qt 鼠标事件

    def mouseMoveEvent(self, event):
        pass

    def mouseReleaseEvent(self, event):
        pass

    def nativeEvent(self, event_type, message):
        """
        WM_NCHITTEST → HTCAPTION：整个窗口都是标题栏，系统接管 modal 拖动循环，
        延迟比 Qt mouseMoveEvent 低一个数量级。
        WM_MOVING：在窗口实际移动前预先截图，彻底消除拖动拖影。
        """
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_NCHITTEST:
                return True, HTCAPTION
            if msg.message == WM_MOVING:
                rect = ctypes.cast(msg.lParam, ctypes.POINTER(wintypes.RECT)).contents
                # FramelessWindowHint 下无边框，client 原点 == frame 原点
                self._pending_capture_x = rect.left - self._display_left
                self._pending_capture_y = rect.top  - self._display_top
                self._on_tick()
        return super().nativeEvent(event_type, message)

    # def paintEvent(self, event):
    #     # 父窗口透明，不画任何东西，内容完全由 _GLCanvas 负责
    #     pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, lambda: set_window_exclude_from_capture(self.window(), exclude=True))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._canvas.setGeometry(0, 0, self.width(), self.height())

    # ── 定时器 tick ───────────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return

        # WM_MOVING 预截图坐标优先；否则用当前窗口位置
        if self._pending_capture_x is not None:
            x = self._pending_capture_x
            y = self._pending_capture_y
            self._pending_capture_x = None
            self._pending_capture_y = None
        else:
            global_pos = self.mapToGlobal(QPoint(0, 0))
            x = global_pos.x() - self._display_left
            y = global_pos.y() - self._display_top

        # 截图
        new_id = self._mgr.capture_display_region(
            display_index = self._display_index,
            x             = x,
            y             = y,
            width         = w,
            height        = h,
            tag           = self._capture_tag,
        )
        if new_id:
            self._resource_id = new_id

        if not self._resource_id:
            return

        # 特效处理
        display_id = self._resource_id  # 降级：直接显示截图

        if self._fx_ready and self._has_enffects and self._sdf_id:
            output_id = self._fx.render_effects_by_id(
                screen_resource_id=self._resource_id,
                sdf_resource_id=self._sdf_id,
            )
            if output_id:
                display_id = output_id
            else:
                err = self._fx.get_last_error()
                if err:
                    print(f"[OneOpenGLWidget] ⚠️ 特效渲染失败: {err}")

        # 提交显示
        self._canvas.set_frame(display_id, sync=False)

# ── 测试入口 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    app = QApplication(sys.argv)

    widget = OneOpenGLWidget()

    #widget.resize(1920, 1080)

    # label = QLabel("OneOpenGLWidget\n拖动移动窗口", widget)
    # label.setStyleSheet("color: white; font-size: 16px; background: rgba(0,30,120,20);")
    # label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    widget.set_capture_source(display_index=0)
    widget.update_sdf(width=256, height=256, radius_ratio=1, scale=0.9)
    widget.show()
    
    widget.start(fps=30)

    widget.enable_effects([
        EffectType.FLOW, 
        EffectType.CHROMATIC_ABERRATION, 
        EffectType.HIGHLIGHT, 
        #EffectType.BLUR, 
        EffectType.ANTI_ALIASING,
        EffectType.COLOR_GRADING,
        ])

    app.aboutToQuit.connect(widget.cleanup)
    if PYSIDE_VERSION == 2:
        sys.exit(app.exec_())
    else:
        sys.exit(app.exec())