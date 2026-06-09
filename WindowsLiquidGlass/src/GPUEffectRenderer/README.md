
# GPU Effect Renderer

基于 SDF 距离场的 GPU 实时特效渲染系统，全 GPU 流水线，零 CPU-GPU 数据传输。

## 核心功能

- **泛型架构** - 三个 C API（Enable / IsEnabled / SetParam）驱动所有特效，添加新特效无需修改 Python 层
- **SDF 驱动** - 所有特效基于圆角矩形 SDF 距离场，边缘精确且可抗锯齿
- **资源池集成** - 通过 resource_id 直接在 GPU 上传递纹理，零拷贝

## 快速开始

```python
from GPUDeviceManager import GPUDeviceManager
from GPUEffectRenderer import GPUEffectRenderer, EffectType, EFFECTS_PARAMS
from AppleRoundedRect import AppleRoundedRectGPU

gpu_mgr = GPUDeviceManager()
gpu_mgr.initialize()
gpu_mgr.initialize_display_capture()

sdf = AppleRoundedRectGPU(gpu_manager=gpu_mgr)
fx  = GPUEffectRenderer(gpu_mgr)
fx.initialize(gpu_mgr.get_main_device(), gpu_mgr.get_main_context())

# 生成 SDF（同时注册屏幕坐标，渲染时自动对齐）
sdf_id = sdf.generate_sdf_id(500, 500, radius_ratio=1.0, scale=0.9,
                              screen_x=100, screen_y=200)

# 启用特效
fx.enable_effects([
    EffectType.FLOW,
    EffectType.CHROMATIC_ABERRATION,
    EffectType.HIGHLIGHT,
    EffectType.ANTI_ALIASING,
    EffectType.COLOR_GRADING,
    EffectType.COLOR_OVERLAY,
])

# 修改参数
params = EFFECTS_PARAMS.copy()
params["flow"]["params"]["flow_width"]["value"] = 80
params["highlight"]["params"]["angle"]["value"] = 120
params["color_overlay"]["params"]["color"]["value"] = (1.0, 0.0, 1.0)
fx.update_effects(params)

# 单参数实时调节
fx.set_param(EffectType.HIGHLIGHT, "strength", 0.8)

# 每帧渲染
screen_id  = gpu_mgr.capture_display_region(0, 100, 200, 500, 500)
output_id  = fx.render_effects_by_id(screen_id, sdf_id)
# output_id 可直接传给 GPUDeviceManager.present_resource() 显示

fx.shutdown()
gpu_mgr.shutdown()
```

## API

| 方法 | 说明 |
|------|------|
| `__init__(gpu_mgr)` | 传入已初始化的 `GPUDeviceManager`，共享其资源池 |
| `initialize(device_ptr, context_ptr)` | 初始化渲染器，返回 `bool` |
| `enable_effects(effect_types, effects_params=None)` | 启用指定特效列表，未列出的自动关闭 |
| `update_effects(effects_params)` | 刷新当前已启用特效的参数（不改变启停状态） |
| `set_param(effect_type, key, value)` | 设置单个参数（供 UI 实时调节） |
| `render_effects_by_id(screen_resource_id, sdf_resource_id)` | 渲染特效，返回输出纹理 `resource_id` |
| `is_effect_enabled(effect_type)` | 查询单个特效是否启用 |
| `get_enabled_effects()` | 返回当前启用的 `List[EffectType]` |
| `get_last_error()` | 返回最近一次错误信息 |
| `shutdown()` | 释放所有资源 |

## 特效列表与参数

### `FLOW` — 光流

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `flow_strength` | float [1, 5] | 2.0 | 边缘膨胀幅度 |
| `flow_width` | int [0, 200] | 60 | 流动带宽度（像素） |
| `flow_falloff` | float [0.5, 10] | 5.0 | 过渡平滑指数，越大越锐利 |

### `CHROMATIC_ABERRATION` — 色散

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `chromatic_strength` | float [0, 20] | 5.0 | RGB 通道最大偏移（像素） |
| `chromatic_width` | int [0, 200] | 60 | 色散带宽度（像素） |
| `chromatic_falloff` | float [0.5, 5] | 3.0 | 过渡平滑指数 |
| `offset_r/g/b` | float [-1, 1] | 1/0/-1 | 各通道沿梯度方向偏移比例 |

### `HIGHLIGHT` — 边缘高光

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `width` | float [0, 50] | 5.0 | 高光带宽度（像素） |
| `angle` | int [0, 360] | 225 | 光源方向（度），0=右，90=上 |
| `strength` | float [0, 1] | 1.0 | 整体亮度系数 |
| `range` | float [0, 1] | 0.3 | 高光在边缘圆周上的覆盖比例 |
| `mode` | int {0,1} | 1 | 0=叠加白色，1=提亮+微增饱和度 |
| `diagonal` | int {0,1} | 1 | 0=不透明对象，1=透明对象 |

### `BLUR` — 高斯模糊

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `radius` | int [0, 50] | 10 | 模糊半径（像素） |

### `ANTI_ALIASING` — 抗锯齿

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `blur_radius` | float [0, 10] | 2.5 | 边缘高斯模糊强度 |
| `edge_range` | float [0, 5] | 1.0 | SDF=0 向内外扩展处理的像素距离 |
| `strength` | float [0, 1] | 1.0 | 抗锯齿混合权重 |

### `COLOR_GRADING` — 综合调色

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `brightness` | float [-1, 1] | 0.0 | 线性亮度偏移 |
| `contrast` | float [0, 3] | 1.0 | 以 0.5 为中点拉伸 |
| `saturation` | float [0, 3] | 1.0 | HSV 饱和度缩放 |
| `hue_shift` | float [-0.5, 0.5] | 0.0 | 色相旋转，±0.5=±180° |
| `exposure` | float [-3, 3] | 0.0 | EV 档位，+1=加一档曝光 |
| `gamma` | float [0.1, 5] | 1.0 | 幂次校正 |
| `temperature` | float [-1, 1] | 0.0 | 正=暖色调，负=冷色调 |
| `highlights` | float [-1, 1] | 0.0 | 高光区亮度调整 |
| `shadows` | float [-1, 1] | 0.0 | 阴影区亮度调整 |
| `vibrance` | float [-1, 2] | 0.0 | 自然饱和度（保护高饱和色） |
| `fadeout` | float [0, 0.5] | 0.0 | 提升黑位，模拟胶片感 |
| `vignette_strength` | float [0, 1] | 0.0 | 暗角强度 |
| `vignette_radius` | float [0, 1] | 0.5 | 暗角起始位置 |
| `vignette_softness` | float [0, 1] | 0.5 | 暗角过渡柔化 |
| `shadow_color` | vec3 | (0,0,0) | 暗部着色偏向 |
| `midtone_color` | vec3 | (0,0,0) | 中间调着色偏向 |
| `highlight_color` | vec3 | (0,0,0) | 亮部着色偏向 |

### `COLOR_OVERLAY` — 颜色叠加

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `color` | color (R,G,B) | (1,0,1) | 叠加目标颜色 |
| `strength` | float [0, 1] | 0.1 | 混合权重，0=无叠加，1=完全叠加 |

## 扩展新特效

1. `effects_params.py` — `EffectType` 新增枚举值，`EFFECT_TYPE_MAPPING` 新增映射，`EFFECTS_PARAMS` 新增参数定义
2. C++ 侧创建 `effects/your_effect.h/cpp/.hlsl`，写 `REGISTER_EFFECT` 宏
3. **无需修改 `gpu_effect_wrapper.py`**

## 架构

```
GPUEffectRenderer/
├── src/
│   ├── effects_params.py            # 特效参数定义（Python）
│   ├── gpu_effect_wrapper.py        # Python 封装
│   ├── gpu_effect_types.h           # 类型定义
│   ├── gpu_effect_base.h            # 特效基类
│   ├── gpu_effect_registry.h/cpp    # REGISTER_EFFECT 宏注册表
│   ├── gpu_effect_renderer.h/cpp    # 特效管理器
│   ├── gpu_effect_api.h/cpp         # C API 导出
│   └── effects/                     # 各特效实现
└── bin/
    ├── gpu_effect_renderer.dll
    └── *_ps.cso                     # 编译后的 Pixel Shader
```
