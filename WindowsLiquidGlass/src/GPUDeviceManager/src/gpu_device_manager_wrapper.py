"""
GPU设备管理器 Python 包装
支持: 多GPU管理 + 通用资源缓存池 + D3D11/OpenGL 零拷贝互操作
多实例版本：每个 GPUDeviceManager 实例拥有独立的 GPUContext（设备/资源池/互操作全部隔离）
"""

import ctypes
import os
from enum import IntEnum
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

_DLL_PATH = os.path.join(os.path.dirname(__file__), "..", "bin")
_DLL_PATH = os.path.abspath(_DLL_PATH).replace("\\", "/")
os.environ["PATH"] = f"{_DLL_PATH};{os.environ['PATH']}"

_DLL_FILE = f"{_DLL_PATH}/gpu_device_manager.dll".replace("\\", "/")

# ============================================================
#  枚举类型
# ============================================================

class GPUPreference(IntEnum):
    """GPU偏好设置"""
    AUTO = 0
    DEDICATED = 1
    INTEGRATED = 2
    LOW_POWER = 3
    HIGH_PERFORMANCE = 4
    SPECIFIC = 5

class GPURole(IntEnum):
    """GPU角色"""
    MAIN = 0          # 主GPU (用于计算)
    DISPLAY = 1       # 有显示器连接的GPU
    BOTH = 2          # 既是主GPU也有显示器

class GPUResourceType(IntEnum):
    """GPU资源类型"""
    TEXTURE2D = 0
    TEXTURE3D = 1
    BUFFER = 2
    STRUCTURED_BUFFER = 3
    RENDER_TARGET = 4
    CUSTOM = 5

# ============================================================
#  数据类
# ============================================================

@dataclass
class GPUInfo:
    """GPU信息"""
    index: int
    name: str
    memory_mb: int
    vendor_id: int
    vendor_name: str
    role: GPURole
    monitor_count: int
    is_integrated: bool
    
    def __repr__(self):
        gpu_type = "集显" if self.is_integrated else "独显"
        role_name = {GPURole.MAIN: "主GPU", GPURole.DISPLAY: "显示", GPURole.BOTH: "主+显示"}
        return (f"GPU[{self.index}]: {self.name} ({self.vendor_name} {gpu_type}, "
                f"{self.memory_mb}MB, {role_name.get(self.role, '未知')}, "
                f"{self.monitor_count}个显示器)")

@dataclass
class MonitorInfo:
    """显示器信息"""
    index: int
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int
    gpu_index: int
    
    def __repr__(self):
        return (f"Monitor[{self.index}]: {self.width}x{self.height} "
                f"at ({self.left},{self.top}) -> GPU[{self.gpu_index}]")

@dataclass
class ResourceInfo:
    """GPU资源信息"""
    resource_id: int
    resource_ptr: int
    srv_ptr: int
    resource_type: GPUResourceType
    width: int
    height: int
    owner_gpu: int
    
    def __repr__(self):
        type_name = {
            GPUResourceType.TEXTURE2D: "Texture2D",
            GPUResourceType.TEXTURE3D: "Texture3D",
            GPUResourceType.BUFFER: "Buffer",
            GPUResourceType.STRUCTURED_BUFFER: "StructuredBuffer",
            GPUResourceType.RENDER_TARGET: "RenderTarget",
            GPUResourceType.CUSTOM: "Custom"
        }
        return (f"Resource[{self.resource_id}]: {type_name.get(self.resource_type, 'Unknown')} "
                f"{self.width}x{self.height} on GPU[{self.owner_gpu}]")

# ============================================================
#  GPU设备管理器
# ============================================================

class GPUDeviceManager:
    """GPU设备管理器 - 每个实例持有独立的 GPUContext（完全隔离的设备/资源池）"""

    # 类级别：只加载 DLL 一次，签名也只设置一次
    _dll = None
    _signatures_configured = False

    def __init__(self):
        # 加载 DLL（只加载一次）
        if GPUDeviceManager._dll is None:
            if not os.path.exists(_DLL_FILE):
                raise FileNotFoundError(f"DLL not found: {_DLL_FILE}")
            GPUDeviceManager._dll = ctypes.CDLL(_DLL_FILE)

        self.dll = GPUDeviceManager._dll

        if not GPUDeviceManager._signatures_configured:
            self._setup_signatures()
            GPUDeviceManager._signatures_configured = True

        # 每个实例创建独立的 GPUContext
        self._handle: ctypes.c_void_p = self.dll.GPUMgr_Create()
        if not self._handle:
            raise RuntimeError("GPUMgr_Create() 返回空句柄")

    # ------------------------------------------------------------------
    #  函数签名设置（所有函数首参数均为 c_void_p handle）
    # ------------------------------------------------------------------
    def _setup_signatures(self):
        """设置DLL函数签名"""
        h = ctypes.c_void_p

        # 生命周期
        self.dll.GPUMgr_Create.argtypes = []
        self.dll.GPUMgr_Create.restype = h

        self.dll.GPUMgr_Destroy.argtypes = [h]
        self.dll.GPUMgr_Destroy.restype = None

        # ========== 设备管理 ==========
        self.dll.GPUMgr_Initialize.argtypes = [h, ctypes.c_int]
        self.dll.GPUMgr_Initialize.restype = ctypes.c_int

        self.dll.GPUMgr_Shutdown.argtypes = [h]
        self.dll.GPUMgr_Shutdown.restype = None

        self.dll.GPUMgr_IsInitialized.argtypes = [h]
        self.dll.GPUMgr_IsInitialized.restype = ctypes.c_int

        self.dll.GPUMgr_GetGPUCount.argtypes = [h]
        self.dll.GPUMgr_GetGPUCount.restype = ctypes.c_int

        self.dll.GPUMgr_GetGPUInfo.argtypes = [
            h,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        self.dll.GPUMgr_GetGPUInfo.restype = ctypes.c_int

        self.dll.GPUMgr_GetMonitorCount.argtypes = [h]
        self.dll.GPUMgr_GetMonitorCount.restype = ctypes.c_int

        self.dll.GPUMgr_GetMonitorInfo.argtypes = [
            h,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        self.dll.GPUMgr_GetMonitorInfo.restype = ctypes.c_int

        self.dll.GPUMgr_GetMainDevice.argtypes = [h]
        self.dll.GPUMgr_GetMainDevice.restype = h

        self.dll.GPUMgr_GetMainContext.argtypes = [h]
        self.dll.GPUMgr_GetMainContext.restype = h

        self.dll.GPUMgr_GetDeviceByGPUIndex.argtypes = [h, ctypes.c_int]
        self.dll.GPUMgr_GetDeviceByGPUIndex.restype = h

        self.dll.GPUMgr_GetContextByGPUIndex.argtypes = [h, ctypes.c_int]
        self.dll.GPUMgr_GetContextByGPUIndex.restype = h

        self.dll.GPUMgr_GetDeviceByMonitor.argtypes = [h, ctypes.c_int]
        self.dll.GPUMgr_GetDeviceByMonitor.restype = h

        self.dll.GPUMgr_GetDebugInfo.argtypes = [h]
        self.dll.GPUMgr_GetDebugInfo.restype = ctypes.c_char_p

        # ========== 资源池管理 ==========
        self.dll.GPUMgr_AddResourceToPool.argtypes = [
            h, h, ctypes.c_int, h, ctypes.c_int, ctypes.c_char_p
        ]
        self.dll.GPUMgr_AddResourceToPool.restype = ctypes.c_uint64

        self.dll.GPUMgr_CreateResourceInPool.argtypes = [
            h,
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_char_p,
        ]
        self.dll.GPUMgr_CreateResourceInPool.restype = ctypes.c_uint64

        self.dll.GPUMgr_GetResourceFromPool.argtypes = [
            h,
            ctypes.c_uint64,
            ctypes.POINTER(h),
            ctypes.POINTER(h),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        self.dll.GPUMgr_GetResourceFromPool.restype = ctypes.c_int

        self.dll.GPUMgr_RemoveResourceFromPool.argtypes = [h, ctypes.c_uint64]
        self.dll.GPUMgr_RemoveResourceFromPool.restype = None

        self.dll.GPUMgr_ClearResourcePool.argtypes = [h]
        self.dll.GPUMgr_ClearResourcePool.restype = None

        self.dll.GPUMgr_CopyResourceToGPU.argtypes = [h, ctypes.c_uint64, ctypes.c_int]
        self.dll.GPUMgr_CopyResourceToGPU.restype = ctypes.c_uint64

        self.dll.GPUMgr_CopyResourceToCPU.argtypes = [h, ctypes.c_uint64, h]
        self.dll.GPUMgr_CopyResourceToCPU.restype = ctypes.c_int

        self.dll.GPUMgr_GetResourceDataSize.argtypes = [
            h,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        self.dll.GPUMgr_GetResourceDataSize.restype = ctypes.c_int

        self.dll.GPUMgr_GetPoolStats.argtypes = [
            h,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.dll.GPUMgr_GetPoolStats.restype = ctypes.c_int

        # ========== Desktop Duplication 显示器捕获 ==========
        self.dll.GPUMgr_InitializeDisplayCapture.argtypes = [h]
        self.dll.GPUMgr_InitializeDisplayCapture.restype = ctypes.c_int

        self.dll.GPUMgr_ShutdownDisplayCapture.argtypes = [h]
        self.dll.GPUMgr_ShutdownDisplayCapture.restype = None

        self.dll.GPUMgr_GetDisplayCount.argtypes = [h]
        self.dll.GPUMgr_GetDisplayCount.restype = ctypes.c_int

        self.dll.GPUMgr_GetDisplayBounds.argtypes = [
            h,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        self.dll.GPUMgr_GetDisplayBounds.restype = ctypes.c_int

        self.dll.GPUMgr_GetDisplayGPUIndex.argtypes = [h, ctypes.c_int]
        self.dll.GPUMgr_GetDisplayGPUIndex.restype = ctypes.c_int

        self.dll.GPUMgr_GetDisplayTexture.argtypes = [h, ctypes.c_int]
        self.dll.GPUMgr_GetDisplayTexture.restype = h

        self.dll.GPUMgr_CaptureDisplayRegion.argtypes = [
            h,
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_char_p,
        ]
        self.dll.GPUMgr_CaptureDisplayRegion.restype = ctypes.c_uint64

        self.dll.GPUMgr_ReleaseDisplayFrame.argtypes = [h, ctypes.c_int]
        self.dll.GPUMgr_ReleaseDisplayFrame.restype = None

        self.dll.GPUMgr_GetDisplayDevice.argtypes = [h, ctypes.c_int]
        self.dll.GPUMgr_GetDisplayDevice.restype = h

        # 资源池快捷访问
        self.dll.GPUMgr_GetResourceTexture.argtypes = [h, ctypes.c_uint64]
        self.dll.GPUMgr_GetResourceTexture.restype = h

        self.dll.GPUMgr_GetResourceSRV.argtypes = [h, ctypes.c_uint64]
        self.dll.GPUMgr_GetResourceSRV.restype = h

        self.dll.GPUMgr_GetResourceRTV.argtypes = [h, ctypes.c_uint64]
        self.dll.GPUMgr_GetResourceRTV.restype = h

        self.dll.GPUMgr_GetResourceUAV.argtypes = [h, ctypes.c_uint64]
        self.dll.GPUMgr_GetResourceUAV.restype = h

        # ========== D3D11/OpenGL 互操作 ==========
        self.dll.GPUMgr_InitializeGLInterop.argtypes = [h]
        self.dll.GPUMgr_InitializeGLInterop.restype = ctypes.c_int

        self.dll.GPUMgr_IsGLInteropSupported.argtypes = [h]
        self.dll.GPUMgr_IsGLInteropSupported.restype = ctypes.c_int

        self.dll.GPUMgr_ShutdownGLInterop.argtypes = [h]
        self.dll.GPUMgr_ShutdownGLInterop.restype = None

        self.dll.GPUMgr_CreateGLTextureFromD3D.argtypes = [h, ctypes.c_uint64]
        self.dll.GPUMgr_CreateGLTextureFromD3D.restype = h

        self.dll.GPUMgr_LockGLTexture.argtypes = [h, h]
        self.dll.GPUMgr_LockGLTexture.restype = ctypes.c_int

        self.dll.GPUMgr_UnlockGLTexture.argtypes = [h, h]
        self.dll.GPUMgr_UnlockGLTexture.restype = ctypes.c_int

        self.dll.GPUMgr_ReleaseGLTexture.argtypes = [h, h]
        self.dll.GPUMgr_ReleaseGLTexture.restype = ctypes.c_int

        self.dll.GPUMgr_GetGLTextureID.argtypes = [h, h]
        self.dll.GPUMgr_GetGLTextureID.restype = ctypes.c_uint

        # ========== DXGI SwapChain Presenter ==========
        self.dll.GPUMgr_CreatePresenter.argtypes = [h, h, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.dll.GPUMgr_CreatePresenter.restype = ctypes.c_uint64

        self.dll.GPUMgr_DestroyPresenter.argtypes = [h, ctypes.c_uint64]
        self.dll.GPUMgr_DestroyPresenter.restype = None

        self.dll.GPUMgr_PresentResource.argtypes = [h, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int]
        self.dll.GPUMgr_PresentResource.restype = ctypes.c_int

        self.dll.GPUMgr_ResizePresenter.argtypes = [h, ctypes.c_uint64, ctypes.c_int, ctypes.c_int]
        self.dll.GPUMgr_ResizePresenter.restype = ctypes.c_int

        # ========== 内部子系统访问 ==========
        self.dll.GPUMgr_GetResourcePoolPtr.argtypes = [h]
        self.dll.GPUMgr_GetResourcePoolPtr.restype = h

    # ------------------------------------------------------------------
    #  设备管理方法
    # ------------------------------------------------------------------

    def initialize(self, preference: GPUPreference = GPUPreference.AUTO) -> bool:
        """初始化GPU设备"""
        return bool(self.dll.GPUMgr_Initialize(self._handle, int(preference)))

    def is_initialized(self) -> bool:
        return bool(self.dll.GPUMgr_IsInitialized(self._handle))

    def get_gpu_count(self) -> int:
        return self.dll.GPUMgr_GetGPUCount(self._handle)

    def get_gpu_info(self, index: int) -> Optional[GPUInfo]:
        name_buffer = ctypes.create_string_buffer(256)
        memory = ctypes.c_size_t()
        vendor_id = ctypes.c_int()
        role = ctypes.c_int()
        monitor_count = ctypes.c_int()

        result = self.dll.GPUMgr_GetGPUInfo(
            self._handle, index, name_buffer, 256,
            ctypes.byref(memory), ctypes.byref(vendor_id),
            ctypes.byref(role), ctypes.byref(monitor_count)
        )
        if not result:
            return None
        memory_mb = memory.value // (1024 * 1024)
        vendor_name = self._get_vendor_name(vendor_id.value)
        is_integrated = self._is_integrated(vendor_id.value, memory_mb)
        return GPUInfo(
            index=index,
            name=name_buffer.value.decode('utf-8'),
            memory_mb=memory_mb,
            vendor_id=vendor_id.value,
            vendor_name=vendor_name,
            role=GPURole(role.value),
            monitor_count=monitor_count.value,
            is_integrated=is_integrated
        )

    def enumerate_gpus(self) -> List[GPUInfo]:
        count = self.get_gpu_count()
        # return [g for i in range(count) if (g := self.get_gpu_info(i))]
        gpus = []
        for i in range(count):
            g = self.get_gpu_info(i)
            if g:
                gpus.append(g)
        return gpus

    def get_monitor_count(self) -> int:
        return self.dll.GPUMgr_GetMonitorCount(self._handle)

    def get_monitor_info(self, index: int) -> Optional[MonitorInfo]:
        left, top, right, bottom, gpu_index = (ctypes.c_int() for _ in range(5))
        result = self.dll.GPUMgr_GetMonitorInfo(
            self._handle, index,
            ctypes.byref(left), ctypes.byref(top),
            ctypes.byref(right), ctypes.byref(bottom),
            ctypes.byref(gpu_index)
        )
        if not result:
            return None
        return MonitorInfo(
            index=index,
            left=left.value, top=top.value,
            right=right.value, bottom=bottom.value,
            width=right.value - left.value,
            height=bottom.value - top.value,
            gpu_index=gpu_index.value
        )

    def enumerate_monitors(self) -> List[MonitorInfo]:
        count = self.get_monitor_count()
        monitors = []
        for i in range(count):
            m = self.get_monitor_info(i)
            if m:
                monitors.append(m)
        return monitors

    def get_main_device(self) -> int:
        return self.dll.GPUMgr_GetMainDevice(self._handle)

    def get_main_context(self) -> int:
        return self.dll.GPUMgr_GetMainContext(self._handle)

    def get_device_by_gpu(self, gpu_index: int) -> int:
        return self.dll.GPUMgr_GetDeviceByGPUIndex(self._handle, gpu_index)

    def get_context_by_gpu(self, gpu_index: int) -> int:
        return self.dll.GPUMgr_GetContextByGPUIndex(self._handle, gpu_index)

    def get_device_by_monitor(self, monitor_index: int) -> int:
        return self.dll.GPUMgr_GetDeviceByMonitor(self._handle, monitor_index)

    def get_debug_info(self) -> str:
        info = self.dll.GPUMgr_GetDebugInfo(self._handle)
        return info.decode('utf-8') if info else ""

    def shutdown(self):
        """销毁本实例的 GPUContext（设备/资源池/互操作全部释放）"""
        if self._handle:
            self.dll.GPUMgr_Destroy(self._handle)
            self._handle = None

    def __del__(self):
        if getattr(self, '_handle', None):
            self.shutdown()

    # ------------------------------------------------------------------
    #  资源池管理方法
    # ------------------------------------------------------------------

    def add_resource(self, resource_ptr: int, resource_type: GPUResourceType,
                     srv_ptr: int, owner_gpu: int, tag: str = "") -> int:
        return self.dll.GPUMgr_AddResourceToPool(
            self._handle, resource_ptr, int(resource_type), srv_ptr, owner_gpu,
            tag.encode('utf-8') if tag else None
        )

    def create_resource(self, resource_type: GPUResourceType, width: int, height: int,
                        format: int, bind_flags: int, usage: int,
                        gpu_index: int, tag: str = "") -> int:
        return self.dll.GPUMgr_CreateResourceInPool(
            self._handle, int(resource_type), width, height,
            format, bind_flags, usage, gpu_index,
            tag.encode('utf-8') if tag else None
        )

    def get_resource(self, resource_id: int) -> Optional[ResourceInfo]:
        resource_ptr = ctypes.c_void_p()
        srv_ptr = ctypes.c_void_p()
        res_type = ctypes.c_int()
        width = ctypes.c_int()
        height = ctypes.c_int()
        owner_gpu = ctypes.c_int()

        result = self.dll.GPUMgr_GetResourceFromPool(
            self._handle, resource_id,
            ctypes.byref(resource_ptr), ctypes.byref(srv_ptr),
            ctypes.byref(res_type), ctypes.byref(width),
            ctypes.byref(height), ctypes.byref(owner_gpu)
        )
        if not result:
            return None
        return ResourceInfo(
            resource_id=resource_id,
            resource_ptr=resource_ptr.value or 0,
            srv_ptr=srv_ptr.value or 0,
            resource_type=GPUResourceType(res_type.value),
            width=width.value,
            height=height.value,
            owner_gpu=owner_gpu.value
        )

    def remove_resource(self, resource_id: int):
        self.dll.GPUMgr_RemoveResourceFromPool(self._handle, resource_id)

    def clear_resource_pool(self):
        self.dll.GPUMgr_ClearResourcePool(self._handle)

    def copy_resource_to_gpu(self, src_resource_id: int, dst_gpu_index: int) -> int:
        return self.dll.GPUMgr_CopyResourceToGPU(self._handle, src_resource_id, dst_gpu_index)

    def copy_resource_to_cpu(self, resource_id: int, buffer: ctypes.Array) -> bool:
        return bool(self.dll.GPUMgr_CopyResourceToCPU(self._handle, resource_id, ctypes.byref(buffer)))

    def copy_resource_to_numpy(self, resource_id: int):
        """拷贝GPU纹理资源到numpy数组，返回 (H, W, 4) uint8 BGRA 数组"""
        try:
            import numpy as np
        except ImportError:
            print("需要安装numpy: pip install numpy")
            return None

        width = ctypes.c_int()
        height = ctypes.c_int()
        stride = ctypes.c_int()

        if not self.dll.GPUMgr_GetResourceDataSize(
            self._handle, resource_id,
            ctypes.byref(width), ctypes.byref(height), ctypes.byref(stride)
        ):
            return None

        w, h, s = width.value, height.value, stride.value
        buffer = (ctypes.c_ubyte * (h * s))()
        if not self.dll.GPUMgr_CopyResourceToCPU(self._handle, resource_id, buffer):
            return None

        arr = np.frombuffer(buffer, dtype=np.uint8).reshape((h, w, 4))
        return arr.copy()

    def get_pool_stats(self) -> Tuple[int, int]:
        total_resources = ctypes.c_int()
        total_memory = ctypes.c_size_t()
        self.dll.GPUMgr_GetPoolStats(self._handle, ctypes.byref(total_resources), ctypes.byref(total_memory))
        return (total_resources.value, total_memory.value)

    def get_resource_texture(self, resource_id: int) -> int:
        return self.dll.GPUMgr_GetResourceTexture(self._handle, resource_id)

    def get_resource_srv(self, resource_id: int) -> int:
        return self.dll.GPUMgr_GetResourceSRV(self._handle, resource_id)

    def get_resource_rtv(self, resource_id: int) -> int:
        return self.dll.GPUMgr_GetResourceRTV(self._handle, resource_id)

    def get_resource_uav(self, resource_id: int) -> int:
        return self.dll.GPUMgr_GetResourceUAV(self._handle, resource_id)

    # ------------------------------------------------------------------
    #  Desktop Duplication 显示器捕获
    # ------------------------------------------------------------------

    def initialize_display_capture(self) -> bool:
        return bool(self.dll.GPUMgr_InitializeDisplayCapture(self._handle))

    def shutdown_display_capture(self):
        self.dll.GPUMgr_ShutdownDisplayCapture(self._handle)

    def get_display_count(self) -> int:
        return self.dll.GPUMgr_GetDisplayCount(self._handle)

    def get_display_bounds(self, display_index: int) -> Optional[dict]:
        left, top, right, bottom = (ctypes.c_int() for _ in range(4))
        if self.dll.GPUMgr_GetDisplayBounds(
            self._handle, display_index,
            ctypes.byref(left), ctypes.byref(top),
            ctypes.byref(right), ctypes.byref(bottom)
        ):
            return {
                'left': left.value, 'top': top.value,
                'right': right.value, 'bottom': bottom.value,
                'width': right.value - left.value,
                'height': bottom.value - top.value,
            }
        return None

    def get_display_texture(self, display_index: int) -> int:
        return self.dll.GPUMgr_GetDisplayTexture(self._handle, display_index)

    def release_display_frame(self, display_index: int):
        self.dll.GPUMgr_ReleaseDisplayFrame(self._handle, display_index)

    def capture_display_region(self, display_index: int, x: int, y: int,
                               width: int, height: int, tag: str = "") -> int:
        return self.dll.GPUMgr_CaptureDisplayRegion(
            self._handle, display_index, x, y, width, height,
            tag.encode('utf-8') if tag else None
        )

    # ------------------------------------------------------------------
    #  D3D11/OpenGL 互操作方法
    # ------------------------------------------------------------------

    def initialize_gl_interop(self) -> bool:
        """初始化 OpenGL 互操作（必须在 OpenGL Context 中调用）"""
        return self.dll.GPUMgr_InitializeGLInterop(self._handle) == 1

    def is_gl_interop_supported(self) -> bool:
        return self.dll.GPUMgr_IsGLInteropSupported(self._handle) == 1

    def shutdown_gl_interop(self):
        self.dll.GPUMgr_ShutdownGLInterop(self._handle)

    def create_gl_texture_from_d3d(self, resource_id: int) -> Optional[int]:
        handle = self.dll.GPUMgr_CreateGLTextureFromD3D(self._handle, resource_id)
        return handle if handle else None

    def lock_gl_texture(self, gl_handle: int) -> bool:
        return bool(gl_handle) and self.dll.GPUMgr_LockGLTexture(self._handle, gl_handle) == 1

    def unlock_gl_texture(self, gl_handle: int) -> bool:
        return bool(gl_handle) and self.dll.GPUMgr_UnlockGLTexture(self._handle, gl_handle) == 1

    def release_gl_texture(self, gl_handle: int) -> bool:
        return bool(gl_handle) and self.dll.GPUMgr_ReleaseGLTexture(self._handle, gl_handle) == 1

    def get_gl_texture_id(self, gl_handle: int) -> int:
        if not gl_handle:
            return 0
        return self.dll.GPUMgr_GetGLTextureID(self._handle, gl_handle)

    # ------------------------------------------------------------------
    #  DXGI SwapChain Presenter
    # ------------------------------------------------------------------

    def create_presenter(self, hwnd: int, width: int, height: int, gpu_index: int = -1) -> int:
        return self.dll.GPUMgr_CreatePresenter(self._handle, hwnd, width, height, gpu_index)

    def destroy_presenter(self, presenter_id: int):
        self.dll.GPUMgr_DestroyPresenter(self._handle, presenter_id)

    def present_resource(self, presenter_id: int, resource_id: int, sync_interval: int = 1) -> bool:
        return self.dll.GPUMgr_PresentResource(self._handle, presenter_id, resource_id, sync_interval) == 1

    def resize_presenter(self, presenter_id: int, width: int, height: int) -> bool:
        return self.dll.GPUMgr_ResizePresenter(self._handle, presenter_id, width, height) == 1

    # ------------------------------------------------------------------
    #  辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _get_vendor_name(vendor_id: int) -> str:
        return {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel"}.get(vendor_id, "Unknown")

    @staticmethod
    def _is_integrated(vendor_id: int, memory_mb: int) -> bool:
        return vendor_id == 0x8086 or memory_mb < 512


if __name__ == "__main__":
    mgr = GPUDeviceManager()
    if mgr.initialize(GPUPreference.AUTO):
        print("GPU设备管理器初始化成功")
        gpus = mgr.enumerate_gpus()
        for gpu in gpus:
            print(gpu)
        if mgr.initialize_display_capture():
            region_id = mgr.capture_display_region(0, 0, 0, 800, 600, tag="test")
            if region_id:
                print(f"截图成功，资源ID: {region_id}")
            mgr.shutdown_display_capture()
        mgr.shutdown()
    else:
        print("GPU设备管理器初始化失败")
