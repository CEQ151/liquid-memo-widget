# Apple Rounded Rect SDF Generator

苹果风格圆角矩形的GPU加速SDF（有向距离场）生成器，支持自动缓存。

## 核心功能

- **完全GPU加速** - Compute Shader计算，支持大尺寸实时生成
- **自动缓存** - 相同参数复用缓存，提速10倍以上
- **精确算法** - 采用Apple设计规范的超椭圆插值

## 快速开始

### 方式1：独立使用（无需 GPUDeviceManager）

```python
from AppleRoundedRect import AppleRoundedRectGPU

gen = AppleRoundedRectGPU()  # 内部自建 D3D 设备，不接资源池

sdf = gen.generate_sdf(width=200, height=200, radius_ratio=0.5)
```

### 方式2：集成 GPUDeviceManager（推荐用于生产）

```python
from GPUDeviceManager import GPUDeviceManager
from AppleRoundedRect import AppleRoundedRectGPU

gpu_mgr = GPUDeviceManager()
gpu_mgr.initialize()

gen = AppleRoundedRectGPU(gpu_manager=gpu_mgr, enable_cache=True)

# 生成 SDF（CPU 回读为 numpy 数组）
sdf = gen.generate_sdf(200, 200, radius_ratio=0.5)           # float32, shape=(h, w)

# 生成掩码（内部=255，外部=0）
mask = gen.generate_mask(200, 200, radius_ratio=0.5)          # uint8,   shape=(h, w)

# 同时返回 SDF 和掩码
sdf, mask = gen.generate_sdf_and_mask(200, 200, radius_ratio=0.5)

# 仅返回资源池 ID（不拷贝到 CPU），直接供 GPUEffectRenderer 使用
sdf_id = gen.generate_sdf_id(200, 200, radius_ratio=0.5,
                              screen_x=100, screen_y=200)
print(gen.resource_id)           # 固定 ID（1000~1999），整个生命周期不变
print(gen.is_resource_id_valid)  # True/False

gen.cleanup()   # 显式释放，或依赖 __del__ 自动释放
```

## API

| 方法/属性 | 说明 |
|-----------|------|
| `generate_sdf(w, h, radius_ratio, scale=1.0)` | 生成 SDF，回读为 `float32` numpy 数组 |
| `generate_mask(w, h, radius_ratio, scale=1.0)` | 生成二值掩码，`uint8` numpy 数组 |
| `generate_sdf_and_mask(w, h, radius_ratio, scale=1.0)` | 同时返回 `(sdf, mask)` |
| `generate_sdf_id(w, h, radius_ratio, scale=1.0, screen_x=0, screen_y=0)` | 生成 SDF 并返回资源池 ID，不拷贝到 CPU |
| `resource_id` | 当前实例在资源池中的固定 ID（1000~1999），首次生成后非 0 |
| `is_resource_id_valid` | `resource_id` 是否在 SDF 段范围内 |
| `cleanup()` | 显式释放 GPU 资源，ID 归还空闲池 |

## 性能

| 分辨率 | 生成时间 | 缓存命中 |
|--------|---------|---------|
| 200×200 | 1.6ms | 0.2ms |
| 1920×1080 | 4.9ms | 0.2ms |
| 3840×2160 | 26ms | 0.2ms |

*测试环境：RTX 4090*

## 缓存机制

每个实例持有一个**固定的** `resource_id`，通过 tag（由参数拼接）判断是否命中缓存：

| 情况 | 行为 |
|------|------|
| 参数相同（tag 相同） | 直接返回，GPU 不重新计算 |
| 参数不同，尺寸相同 | 重新 Dispatch，就地更新纹理，ID 不变 |
| 尺寸改变 | 重建 D3D 纹理，替换资源池指针，ID 不变 |
| 实例销毁 | ID 归还 SDF 段空闲池（1000~1999） |

## 输出说明

- **负值** = 形状内部（距边缘像素数）
- **正值** = 形状外部（距边缘像素数）
- **0** = 边缘
