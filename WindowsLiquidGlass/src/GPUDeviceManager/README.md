# GPU Device Manager

多GPU设备管理与资源池系统，提供跨模块的GPU资源共享和缓存。

## 核心功能

- **多实例隔离** - 每个实例持有独立的 GPUContext，设备/资源池/互操作完全隔离
- **自动检测多GPU** - 识别独显/集显及其连接的显示器
- **统一资源池** - 跨模块共享GPU资源，自动缓存
- **Desktop Duplication** - 零延迟屏幕区域捕获
- **D3D11/OpenGL 零拷贝互操作** - 基于 `WGL_NV_DX_interop`
- **DXGI SwapChain Presenter** - GPU 纹理直接 Present 到 Win32 窗口

## 快速开始

```python
from GPUDeviceManager import GPUDeviceManager, GPUPreference

mgr = GPUDeviceManager()
mgr.initialize(GPUPreference.AUTO)

# 多实例：每个实例完全独立
mgr2 = GPUDeviceManager()
mgr2.initialize(GPUPreference.HIGH_PERFORMANCE)

device  = mgr.get_main_device()
context = mgr.get_main_context()

mgr.shutdown()
mgr2.shutdown()
```

## API

### 设备管理

| 方法 | 说明 |
|------|------|
| `initialize(preference=AUTO)` | 初始化GPU设备，返回 `bool` |
| `is_initialized()` | 是否已初始化 |
| `get_main_device()` | 获取主 ID3D11Device 指针 |
| `get_main_context()` | 获取主 ID3D11DeviceContext 指针 |
| `get_device_by_gpu(gpu_index)` | 按GPU索引获取 Device |
| `get_context_by_gpu(gpu_index)` | 按GPU索引获取 Context |
| `get_device_by_monitor(monitor_index)` | 按显示器索引获取 Device |
| `enumerate_gpus()` | 枚举所有GPU，返回 `List[GPUInfo]` |
| `enumerate_monitors()` | 枚举所有显示器，返回 `List[MonitorInfo]` |
| `get_debug_info()` | 返回调试信息字符串 |
| `shutdown()` | 销毁本实例 GPUContext |

`GPUPreference`: `AUTO` / `DEDICATED` / `INTEGRATED` / `LOW_POWER` / `HIGH_PERFORMANCE` / `SPECIFIC`

### 资源池

| 方法 | 说明 |
|------|------|
| `add_resource(ptr, type, srv_ptr, owner_gpu, tag="")` | 将已有资源加入资源池，返回 `resource_id` |
| `create_resource(type, w, h, format, bind_flags, usage, gpu_index, tag="")` | 创建并加入资源池 |
| `get_resource(resource_id)` | 查询资源信息，返回 `ResourceInfo` |
| `remove_resource(resource_id)` | 从资源池移除资源 |
| `clear_resource_pool()` | 清空资源池 |
| `get_pool_stats()` | 返回 `(资源数, 显存字节)` |
| `get_resource_texture(id)` | 获取纹理指针 |
| `get_resource_srv(id)` | 获取 SRV 指针 |
| `get_resource_rtv(id)` | 获取 RTV 指针 |
| `get_resource_uav(id)` | 获取 UAV 指针 |
| `copy_resource_to_cpu(id, buffer)` | 拷贝到 CPU buffer |
| `copy_resource_to_numpy(id)` | 拷贝到 `numpy` 数组，返回 `(H, W, 4) uint8 BGRA` |
| `copy_resource_to_gpu(src_id, dst_gpu_index)` | 跨GPU拷贝 |

`GPUResourceType`: `TEXTURE2D` / `TEXTURE3D` / `BUFFER` / `STRUCTURED_BUFFER` / `RENDER_TARGET` / `CUSTOM`

### 屏幕捕获（Desktop Duplication）

| 方法 | 说明 |
|------|------|
| `initialize_display_capture()` | 初始化屏幕捕获 |
| `shutdown_display_capture()` | 关闭屏幕捕获 |
| `get_display_count()` | 获取显示器数量 |
| `get_display_bounds(display_index)` | 返回 `{left, top, right, bottom, width, height}` |
| `capture_display_region(display_index, x, y, w, h, tag="")` | 捕获指定区域，返回 `resource_id` |
| `get_display_texture(display_index)` | 获取最新帧纹理指针（需配合 `release_display_frame`） |
| `release_display_frame(display_index)` | 释放帧引用 |

### D3D11/OpenGL 互操作

| 方法 | 说明 |
|------|------|
| `initialize_gl_interop()` | 初始化 `WGL_NV_DX_interop`（需在 GL Context 中调用） |
| `is_gl_interop_supported()` | 是否支持互操作 |
| `shutdown_gl_interop()` | 关闭互操作 |
| `create_gl_texture_from_d3d(resource_id)` | 创建共享 GL 纹理句柄 |
| `lock_gl_texture(gl_handle)` | 加锁（GL 使用前调用） |
| `unlock_gl_texture(gl_handle)` | 解锁（GL 使用后调用） |
| `release_gl_texture(gl_handle)` | 释放句柄 |
| `get_gl_texture_id(gl_handle)` | 返回 OpenGL 纹理 ID |

### DXGI SwapChain Presenter

| 方法 | 说明 |
|------|------|
| `create_presenter(hwnd, w, h, gpu_index=-1)` | 为 Win32 窗口创建 SwapChain，返回 `presenter_id` |
| `destroy_presenter(presenter_id)` | 销毁 SwapChain |
| `present_resource(presenter_id, resource_id, sync_interval=1)` | 将资源 Present 到窗口 |
| `resize_presenter(presenter_id, w, h)` | 调整 SwapChain 尺寸 |

## 数据类

```python
GPUInfo(index, name, memory_mb, vendor_id, vendor_name, role, monitor_count, is_integrated)
MonitorInfo(index, left, top, right, bottom, width, height, gpu_index)
ResourceInfo(resource_id, resource_ptr, srv_ptr, resource_type, width, height, owner_gpu)
```

## 架构

```
GPUDeviceManager/
├── src/
│   ├── gpu_types.h                  # 通用类型定义
│   ├── gpu_device_manager.h/cpp     # 设备检测与管理
│   ├── gpu_resource_pool.h/cpp      # 资源池缓存
│   ├── gpu_display_capture.h/cpp    # Desktop Duplication 屏幕捕获
│   ├── gpu_gl_interop.h/cpp         # D3D11/OpenGL 零拷贝互操作
│   ├── gpu_swapchain_presenter.h/cpp# DXGI SwapChain Presenter
│   └── gpu_manager_api.h/cpp        # C API 导出
└── bin/
    └── gpu_device_manager.dll
```


