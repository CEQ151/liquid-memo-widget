"""Stage 1 fluid demo window.

A standalone QMainWindow wrapping FluidGLWidget. Handles keyboard shortcuts
(R = reset, Space = pause, Esc = close) and prints FPS / GL info to stderr.

Run with:
    python -m LiquidMemoWidget.experimental_fluid.fluid_demo_window
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QSurfaceFormat
from PySide6.QtWidgets import QMainWindow, QLabel, QVBoxLayout, QWidget

from .fluid_config import FluidConfig
from .fluid_gl_widget import FluidGLWidget


class FluidDemoWindow(QMainWindow):
    def __init__(self, config: FluidConfig | None = None, config_path: Path | None = None):
        super().__init__()
        self._config_path = config_path
        self.setWindowTitle("Stage 1 — 灰蓝流体原型 (GPU)")
        self.resize(1000, 700)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self.cfg = config or FluidConfig()

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.gl_widget = FluidGLWidget(self.cfg, self)
        layout.addWidget(self.gl_widget, 1)

        self.status = QLabel(self)
        self.status.setStyleSheet(
            "color:#D0D8E0; background:rgba(20,28,38,200); "
            "padding:4px 10px; font-family:Consolas,monospace; font-size:12px;"
        )
        self.status.setText("启动中…")
        layout.addWidget(self.status)

        self.setCentralWidget(central)

        self.gl_widget.fps_changed.connect(self._on_fps)

    def _on_fps(self, fps: float) -> None:
        fmt = QSurfaceFormat.defaultFormat()
        glstr = f"GL {fmt.version()[0]}.{fmt.version()[1]}"
        state = "暂停" if self.gl_widget.is_paused() else "运行"
        self.status.setText(
            f"FPS {fps:5.1f}  |  {glstr}  |  sim {self.cfg.sim_resolution}  "
            f"dye {self.cfg.dye_resolution}  iter {self.cfg.pressure_iterations}  |  {state}  "
            f"|  R=清空  Space=暂停  Esc=关闭"
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        k = event.key()
        if k == Qt.Key_Escape:
            self.close()
        elif k == Qt.Key_R:
            self.gl_widget.reset_fluid()
        elif k == Qt.Key_Space:
            self.gl_widget.toggle_pause()
        elif k == Qt.Key_L:
            self._reload_config()
        else:
            super().keyPressEvent(event)

    def _reload_config(self) -> None:
        """Re-read the tuner JSON and apply it live (L key).

        Palette / tone / motion take effect immediately; sim/dye resolution is
        fixed at init, so changing those needs a restart.
        """
        if not self._config_path or not self._config_path.exists():
            self.status.setText("没有可重载的配置（把 inkwash.json 放到本模块同目录）")
            return
        try:
            self.cfg = FluidConfig.from_tuner_json(self._config_path)
        except Exception as exc:  # noqa: BLE001 — surface any parse error to the status bar
            self.status.setText(f"重载失败: {exc}")
            return
        self.gl_widget.set_config(self.cfg)
        self.status.setText(f"已重载 {self._config_path.name}")


def configure_gl_format() -> None:
    """Request an OpenGL 3.3 Core Profile context.

    Must be called BEFORE QApplication is constructed — Qt reads the default
    surface format when creating the application and the first GL context.
    """
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setAlphaBufferSize(8)
    fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    QSurfaceFormat.setDefaultFormat(fmt)


def _resolve_config_path() -> Path | None:
    """An explicit CLI path wins; otherwise auto-load inkwash.json beside this module."""
    if len(sys.argv) > 1:
        cli = Path(sys.argv[1])
        return cli if cli.exists() else None
    default = Path(__file__).parent / "inkwash.json"
    return default if default.exists() else None


def main() -> int:
    from PySide6.QtWidgets import QApplication
    configure_gl_format()
    app = QApplication(sys.argv)
    cfg_path = _resolve_config_path()
    cfg = FluidConfig.from_tuner_json(cfg_path) if cfg_path else FluidConfig()
    win = FluidDemoWindow(cfg, config_path=cfg_path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
