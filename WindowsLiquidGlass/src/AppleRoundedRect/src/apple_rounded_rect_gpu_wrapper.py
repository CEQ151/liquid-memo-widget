#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apple 圆角矩形 SDF GPU 生成器 - Python 包装器

缓存策略（单 ID + tag）：
  每个实例在资源池中持有一个固定的 resource_id（SDF 段 1000 ~ 1999）。
  - tag 相同 → 直接返回，不重新生成，不占用新显存
  - tag 不同但尺寸相同 → 重新 Dispatch，就地更新纹理内容，ID 不变
  - 尺寸改变 → 重建 D3D11 纹理，UpdateResourceInPool 替换指针，ID 不变
  - 实例销毁 → RemoveResource，ID 归还到 SDF 段空闲池
"""

import ctypes
import numpy as np
import os
import sys
from typing import Optional, Tuple

try:
    from ...GPUDeviceManager import GPUDeviceManager, GPU_MGR_DLL
except ImportError:
    if "d:/git" not in sys.path:
        sys.path.append("d:/git")
    from OneEffects.GPUDeviceManager import GPUDeviceManager, GPU_MGR_DLL

# 全局 SDF 屏幕坐标缓存：sdf_id -> (screen_x, screen_y)
# 由 generate_sdf_id() 写入，由 GPUEffectRenderer.render_effects_by_id() 在渲染时自动读取
_sdf_positions: dict = {}


def _notify_sdf_position(sdf_id: int, x: float, y: float) -> None:
    """Store SDF screen position and notify GPUEffectRenderer DLL if already loaded."""
    _sdf_positions[sdf_id] = (x, y)
    try:
        import sys
        for mod in list(sys.modules.values()):
            if hasattr(mod, '_register_sdf_position'):
                mod._register_sdf_position(sdf_id, x, y)
                break
    except Exception:
        pass


# ── DLL 路径 ────────────────────────────────────────────────────
APPLE_DLL = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..","bin", "apple_rounded_rect_gpu.dll")
)

# ── SDF 资源 ID 范围（与 gpu_types.h 保持一致）────────────────────────────────
RESOURCE_SLOT_SDF_BEGIN = 1000
RESOURCE_SLOT_SDF_END   = 1999


class AppleRoundedRectGPU:
    """
    苹果圆角矩形 SDF GPU 生成器。

    缓存策略：单一固定 resource_id + tag 比较
      - 每个实例在资源池中只占用 **一个** SDF 段 ID（1000 ~ 1999）
      - 参数相同（tag 相同）→ 直接返回，零额外显存
      - 参数不同（tag 不同）→ 就地更新纹理内容，ID 始终不变
      - 与旧版"每次新参数就分配新 ID"不同，不会造成显存积累

    用法：
        gen = AppleRoundedRectGPU(gpu_manager=gpu_mgr)
        sdf = gen.generate_sdf(width=200, height=200, radius_ratio=0.5)
        rid = gen.resource_id   # 固定 ID，整个生命周期不变（1000~1999）
    """

    def __init__(
        self,
        device=None,
        context=None,
        gpu_manager: "GPUDeviceManager | None" = None,
        enable_cache: bool = True,
    ):
        """
        初始化 SDF 生成器。

        Args:
            gpu_manager : 推荐方式，传入已初始化的 GPUDeviceManager。
            device      : 直接传入 ID3D11Device 指针（gpu_manager 优先）。
            context     : 直接传入 ID3D11DeviceContext 指针。
            enable_cache: 是否接入资源池（默认 True）。
                          False 时仍可生成 SDF，但 resource_id 始终为 0。
        """
        if not os.path.exists(APPLE_DLL):
            raise FileNotFoundError(f"DLL 不存在: {APPLE_DLL}")

        self._dll     = ctypes.CDLL(APPLE_DLL)
        self._gpu_mgr = gpu_manager
        self._handle  = None

        self._setup_signatures()
        self._handle = self._dll.ARRGPU_Create()
        if not self._handle:
            raise RuntimeError("创建 GPU 生成器句柄失败")

        self._initialize(device, context, gpu_manager, enable_cache)

    # ── 公开属性 ──────────────────────────────────────────────────────────────

    @property
    def resource_id(self) -> int:
        """
        该实例在资源池中的固定 ID（1000 ~ 1999）。

        首次调用 generate_sdf 之后才非 0。
        整个生命周期内数值不变（即使尺寸/radius 改变）。
        """
        return int(self._dll.ARRGPU_GetCurrentResourceID(self._handle))

    @property
    def is_resource_id_valid(self) -> bool:
        """resource_id 是否已分配（在 SDF 段范围内）。"""
        return RESOURCE_SLOT_SDF_BEGIN <= self.resource_id <= RESOURCE_SLOT_SDF_END

    # ── 公开 API ──────────────────────────────────────────────────────────────

    def generate_sdf_id(self, width: int, height: int, radius_ratio: float, scale: float = 1.0,
                        screen_x: float = 0.0, screen_y: float = 0.0) -> int:
        """
        生成 SDF 并返回对应的 GPU 资源 ID。

        该 ID 在整个实例生命周期内保持不变（1000 ~ 1999），即使参数改变。
        参数相同时命中缓存，GPU 不重新计算；参数不同时就地更新纹理内容。

        Args:
            width        : 输出宽度（像素）
            height       : 输出高度（像素）
            radius_ratio : 圆角半径比例 [0.0, 1.0]
            scale        : 缩放比例（默认 1.0）
            screen_x     : SDF 左上角在屏幕上的 X 坐标（像素，默认 0）
            screen_y     : SDF 左上角在屏幕上的 Y 坐标（像素，默认 0）
        Returns:
            GPU 资源 ID（1000 ~ 1999），或 0 表示未生成。
        """
        ok = self._dll.ARRGPU_GenerateSDF(
            self._handle,
            ctypes.c_float(width),
            ctypes.c_float(height),
            ctypes.c_float(radius_ratio),
            ctypes.c_float(scale),
        )
        if not ok:
            raise RuntimeError(f"GPU 生成 SDF 失败: {self._last_error()}")
        # 将屏幕坐标存入全局缓存，供 GPUEffectRenderer 自动读取
        _notify_sdf_position(self.resource_id, float(screen_x), float(screen_y))
        return self.resource_id

    def generate_sdf(
        self,
        width: int,
        height: int,
        radius_ratio: float,
        scale: float = 1.0,
    ) -> np.ndarray:
        """
        生成（或复用）圆角矩形 SDF 距离场。

        SDF 约定：负值 = 形状内部，正值 = 形状外部，0 = 边界。

        参数相同时命中缓存（tag 相同），GPU 不重新计算，CPU 直接回读旧数据。
        参数不同时就地更新纹理，resource_id 保持不变。

        Args:
            width        : 输出宽度（像素）
            height       : 输出高度（像素）
            radius_ratio : 圆角半径比例 [0.0, 1.0]
            scale        : 缩放比例（默认 1.0）

        Returns:
            shape=(height, width)，dtype=float32 的 SDF 数组。

        Raises:
            RuntimeError: GPU 生成或 CPU 回读失败。
        """
        ok = self._dll.ARRGPU_GenerateSDF(
            self._handle,
            ctypes.c_float(width),
            ctypes.c_float(height),
            ctypes.c_float(radius_ratio),
            ctypes.c_float(scale),
        )
        if not ok:
            raise RuntimeError(f"GPU 生成 SDF 失败: {self._last_error()}")

        sdf = np.empty((height, width), dtype=np.float32)
        ok = self._dll.ARRGPU_ReadbackSDF(
            self._handle,
            sdf.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            ctypes.c_int(width),
            ctypes.c_int(height),
        )
        if not ok:
            raise RuntimeError(f"SDF 回读失败: {self._last_error()}")

        return sdf

    def generate_mask(
        self,
        width: int,
        height: int,
        radius_ratio: float,
        scale: float = 1.0,
    ) -> np.ndarray:
        """
        生成圆角矩形二值掩码（内部 = 255，外部 = 0）。

        Returns:
            shape=(height, width)，dtype=uint8。
        """
        sdf = self.generate_sdf(width, height, radius_ratio, scale)
        return np.where(sdf < 0, np.uint8(255), np.uint8(0))

    def generate_sdf_and_mask(
        self,
        width: int,
        height: int,
        radius_ratio: float,
        scale: float = 1.0,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        同时返回 SDF 和掩码，兼容旧版 API。

        Returns:
            (sdf, mask): sdf=float32, mask=uint8
        """
        sdf  = self.generate_sdf(width, height, radius_ratio, scale)
        mask = np.where(sdf < 0, np.uint8(255), np.uint8(0))
        return sdf, mask

    def cleanup(self) -> None:
        """
        显式释放 GPU 资源。

        调用后 resource_id 归还到 SDF 段空闲池，可被其他实例复用。
        也可依赖 __del__ 自动调用。
        """
        if self._handle:
            self._dll.ARRGPU_Destroy(self._handle)
            self._handle = None

    # ── 内部实现 ──────────────────────────────────────────────────────────────

    def _setup_signatures(self) -> None:
        dll = self._dll

        dll.ARRGPU_Create.restype              = ctypes.c_void_p
        dll.ARRGPU_CreateAndInit.restype       = ctypes.c_void_p

        dll.ARRGPU_Destroy.argtypes            = [ctypes.c_void_p]
        dll.ARRGPU_Destroy.restype             = None

        dll.ARRGPU_Initialize.argtypes         = [ctypes.c_void_p,
                                                   ctypes.c_void_p, ctypes.c_void_p]
        dll.ARRGPU_Initialize.restype          = ctypes.c_int

        dll.ARRGPU_EnableResourcePool.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p]
        dll.ARRGPU_EnableResourcePool.restype  = None

        dll.ARRGPU_GenerateSDF.argtypes        = [ctypes.c_void_p,
                                                   ctypes.c_float, ctypes.c_float,
                                                   ctypes.c_float, ctypes.c_float]
        dll.ARRGPU_GenerateSDF.restype         = ctypes.c_int

        dll.ARRGPU_ReadbackSDF.argtypes        = [ctypes.c_void_p,
                                                   ctypes.POINTER(ctypes.c_float),
                                                   ctypes.c_int, ctypes.c_int]
        dll.ARRGPU_ReadbackSDF.restype         = ctypes.c_int

        dll.ARRGPU_GetCurrentResourceID.argtypes = [ctypes.c_void_p]
        dll.ARRGPU_GetCurrentResourceID.restype  = ctypes.c_uint64

        dll.ARRGPU_GetLastError.argtypes       = []
        dll.ARRGPU_GetLastError.restype        = ctypes.c_char_p

    def _initialize(self, device, context, gpu_manager, enable_cache=True) -> None:
        if gpu_manager:
            if not gpu_manager.is_initialized():
                raise RuntimeError("GPUDeviceManager 未初始化，请先调用 initialize()")
            device  = gpu_manager.get_main_device()
            context = gpu_manager.get_main_context()
            if not device or not context:
                raise RuntimeError("无法从 GPUDeviceManager 获取 Device/Context")
            if not self._dll.ARRGPU_Initialize(self._handle, device, context):
                raise RuntimeError(f"初始化失败: {self._last_error()}")
            if enable_cache and os.path.exists(GPU_MGR_DLL):
                self._dll.ARRGPU_EnableResourcePool(self._handle, str(GPU_MGR_DLL), gpu_manager._handle)

        elif device and context:
            if not self._dll.ARRGPU_Initialize(self._handle, device, context):
                raise RuntimeError(f"初始化失败: {self._last_error()}")

        else:
            # 独立模式：内部自建 D3D 设备，不接资源池
            self._dll.ARRGPU_Destroy(self._handle)
            self._handle = self._dll.ARRGPU_CreateAndInit()
            if not self._handle:
                raise RuntimeError(f"独立模式初始化失败: {self._last_error()}")

    def _last_error(self) -> str:
        err = self._dll.ARRGPU_GetLastError()
        return err.decode("utf-8") if err else ""

    def __del__(self):
        self.cleanup()


# ── 测试入口 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import time

    gpu_mgr = GPUDeviceManager()
    if not gpu_mgr.initialize():
        sys.exit("GPU 初始化失败")

    gen = AppleRoundedRectGPU(gpu_manager=gpu_mgr, enable_cache=True)

    def _show(label: str, t0: float) -> None:
        sys.stdout.write(
            f"{label:<30}  rid={gen.resource_id}  valid={gen.is_resource_id_valid}"
            f"  {(time.perf_counter() - t0) * 1000:.2f}ms\n"
        )

    # 首次生成
    t0 = time.perf_counter()
    sdf = gen.generate_sdf(200, 200, radius_ratio=0.5)
    sys.stdout.write(
        f"{'首次生成':<30}  range=[{sdf.min():.2f}, {sdf.max():.2f}]"
        f"  rid={gen.resource_id}  valid={gen.is_resource_id_valid}"
        f"  {(time.perf_counter() - t0) * 1000:.2f}ms\n"
    )

    # tag 相同 → 命中缓存，ID 不变
    t0 = time.perf_counter()
    gen.generate_sdf(200, 200, radius_ratio=0.5)
    _show("tag 相同 → cache hit，ID 不变", t0)

    # tag 不同（radius 变）→ 就地更新，ID 不变
    t0 = time.perf_counter()
    gen.generate_sdf(200, 200, radius_ratio=0.3)
    _show("tag 不同 → 就地更新，ID 不变", t0)

    # 尺寸变化 → 重建纹理，UpdateResourceInPool，ID 不变
    t0 = time.perf_counter()
    gen.generate_sdf(300, 300, radius_ratio=0.5)
    _show("尺寸变化 → 重建纹理，ID 不变", t0)

    # mask
    t0 = time.perf_counter()
    mask = gen.generate_mask(200, 200, radius_ratio=0.5)
    sys.stdout.write(
        f"{'mask':<30}  shape={mask.shape}  coverage={mask.mean():.1f}/255"
        f"  {(time.perf_counter() - t0) * 1000:.2f}ms\n"
    )

    gen.cleanup()
    gpu_mgr.shutdown()