# GPUSharderWidget

Qt 封装的 GPU 纹理显示组件，将屏幕截图 + GPU 特效 + Qt 窗口管理整合为开箱即用的 Widget。  
支持两条渲染路径：**D3D11 直接呈现**（`OneGPUWidget`）和 **OpenGL 路径**（`OneOpenGLWidget`）。

---

## 文件结构

| 文件 | 说明 |
|------|------|
| `one_d3d_widget.py` | `OneGPUWidget` D3D11 路径，组合 `GPUD3DWidget` 与截图/特效逻辑 |
| `one_gl_widget.py`  | `OneOpenGLWidget` 使用 QOpenGLWidget 基类 |
| `gpu_d3d_widget.py` | `GPUD3DWidget` D3D11 显示基类，Win32 子窗口 + SwapChain + QTimer |

---


## 快速开始

### OneGPUWidget（D3D11 路径）

```python
from src.GPUSharderWidget.one_d3d_widget import OneGPUWidget
from src.GPUEffectRenderer import EffectType
from src.GPUEffectRenderer.src.effects_params import BlurParams

widget = OneGPUWidget()                  # 可传入已有 GPUDeviceManager
widget.set_capture_source(display_index=0, tag="MyApp")
widget.update_sdf(400, 300, radius_ratio=0.5, scale=0.85)
widget.enable_effects([EffectType.BLUR])
widget.update_effects({EffectType.BLUR: BlurParams(radius=8)})
widget.start(fps=60) # 静态背景不设置
widget.show()
```

子组件（仅 PySide6）：

```python
# PySide6 下 widget.container 是透明 QWidget，随主窗口移动/缩放
if widget.container:
    label = QLabel("Hello", widget.container)
```

---

### OneOpenGLWidget（OpenGL 路径）

```python
from src.GPUSharderWidget.one_gl_widget import OneOpenGLWidget
from src.GPUEffectRenderer import EffectType

widget = OneOpenGLWidget()
widget.set_capture_source(display_index=0, tag="MyApp")
widget.update_sdf(400, 300, radius_ratio=0.5, scale=0.85)
widget.enable_effects([EffectType.BLUR])
widget.start(fps=60)  # 静态背景不设置
widget.show()

# 诊断帧内容
widget.save_debug_frame("debug.png")
```

---

## OneGPUWidget API

### 构造函数

```python
OneGPUWidget(parent=None, mgr: GPUDeviceManager = None, qt_move: bool = True)
```

| 参数 | 说明 |
|------|------|
| `parent` | Qt 父级 widget |
| `mgr` | 已有 `GPUDeviceManager` 实例，为 `None` 时内部自动创建 |
| `qt_move` | `False`  通过系统 HTCAPTION 拖动（低延迟）；`True` Qt 鼠标事件拖动 |

### 方法

| 方法 | 说明 |
|------|------|
| `set_capture_source(display_index=0, tag="OneGPUWidget")` | 设置截图来源（显示器索引和窗口标签） |
| `start(fps=60)` | 启动帧循环 |
| `stop()` | 暂停帧循环，不销毁资源 |
| `update_sdf(width, height, radius_ratio=0.5, scale=0.8) -> bool` | 生成圆角矩形 SDF 并将窗口固定为对应尺寸，**须在 `show()` 后调用** |
| `enable_effects(effects: List[EffectType])` | 启用指定特效列表，空列表关闭所有特效 |
| `update_effects(effects_params: dict)` | 更新特效参数，格式见 `GPUEffectRenderer` 文档 |
| `cleanup()` | 销毁所有 GPU 资源，窗口关闭前调用 |

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `effect` | `GPUEffectRenderer` | 访问底层特效渲染器，可调用 `GPUEffectRenderer` 的全部 API |
| `container` | `QWidget \| None` | 透明子容器（**仅 PySide6**），用于在 D3D 背景上叠加 Qt 组件 |

---

## OneOpenGLWidget API

### 构造函数

```python
OneOpenGLWidget(parent=None)
```

内部自动创建 `GPUDeviceManager`。

### 方法

| 方法 | 说明 |
|------|------|
| `set_capture_source(display_index=0, tag="OneOpenGLWidget")` | 设置截图来源 |
| `start(fps=60)` | 启动帧循环（静态背景可以不启动） |
| `stop()` | 暂停帧循环 |
| `update_sdf(width, height, radius_ratio=0.5, scale=0.8) -> bool` | 生成圆角矩形 SDF 并固定窗口尺寸，**须在 `show()` 后调用** |
| `enable_effects(effects: List[EffectType])` | 启用指定特效列表 |
| `cleanup()` | 销毁所有 GPU 资源 |

---

## GPUD3DWidget（基类）

> 一般不需要直接使用，`OneGPUWidget` 已将其完整封装。

`GPUD3DWidget` 是纯 D3D11 显示基类，负责：
- Win32 子窗口生命周期
- DXGI SwapChain 创建 / resize / 销毁
- Qt PreciseTimer 驱动帧循环

鼠标消息路由：内部 Win32 子窗口的 `WM_NCHITTEST` 返回 `HTTRANSPARENT`，所有鼠标消息透传给父 Qt 窗口处理。

**子类实现接口：**

| 方法 | 说明 |
|------|------|
| `_init_presenter(gpu_mgr, width, height) -> bool` | 初始化 SwapChain，在 gpu_mgr 就绪后调用 |
| `_present(resource_id)` | 将纹理呈现到屏幕，在 `_on_frame()` 中调用 |
| `_on_frame()` | 每帧回调（override），实现截图 / 特效 / present 逻辑 |

**公开控制 API：**

| 方法 | 说明 |
|------|------|
| `start(fps=60)` | 启动帧循环（需先完成 `_init_presenter`） |
| `stop()` | 暂停帧循环 |
| `cleanup()` | 销毁 SwapChain 和 Win32 子窗口 |

---

## 已知问题

1. 性能不足和快速拖动是偶然会有闪烁和延迟拖动问题
2. PySide2 在使用D3D实例时无法透明，导致无法在D3D窗口添加组件，虽然能添加但是都会有黑底（问题可能在表面实例，或者是PySide2的限制）