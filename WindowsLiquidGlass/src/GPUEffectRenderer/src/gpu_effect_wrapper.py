"""
GPU特效渲染器 Python 包装（重构泛型版本）

新架构：只暴露三个泛型 C API（GPUEffect_Enable / IsEnabled / SetParam），
无需为每种特效写专属方法。添加新特效只需在 effects_params.py 中新增参数定义，
在 C++ 侧写 REGISTER_EFFECT 宏即可，不需要修改本文件。
"""

import ctypes
import os
from typing import List, Set, Dict, Optional, Tuple

_DLL_PATH = os.path.join(os.path.dirname(__file__), "..", "bin")
_DLL_FILE = os.path.abspath(f"{_DLL_PATH}/gpu_effect_renderer.dll")

# 模块级 SDF 位置缓存：sdf_id -> (screen_x, screen_y)
_sdf_position_cache: Dict[int, Tuple[float, float]] = {}

from .effects_params import EffectType, EFFECT_TYPE_MAPPING, EFFECTS_PARAMS


def _register_sdf_position(sdf_id: int, x: float, y: float) -> None:
    """供 apple_rounded_rect_gpu_wrapper._notify_sdf_position 回调，无需手动调用。"""
    _sdf_position_cache[sdf_id] = (x, y)


class GPUEffectRenderer:
    """GPU特效渲染器 — 每个实例绑定一个 GPUDeviceManager 实例，共享其资源池"""

    # 类级别：只加载 DLL / 设置签名一次
    _dll = None
    _signatures_configured = False

    def __init__(self, gpu_mgr, dll_path: str = _DLL_FILE):
        """
        Args:
            gpu_mgr: GPUDeviceManager 实例（已初始化），共享其 ResourcePool
            dll_path: 特效渲染器 DLL 路径（可选）
        """
        if GPUEffectRenderer._dll is None:
            if not os.path.exists(dll_path):
                raise FileNotFoundError(f"DLL not found: {dll_path}")
            GPUEffectRenderer._dll = ctypes.CDLL(dll_path)

        self.dll = GPUEffectRenderer._dll

        if not GPUEffectRenderer._signatures_configured:
            self._setup_signatures()
            GPUEffectRenderer._signatures_configured = True

        self._handle: ctypes.c_void_p = self.dll.GPUEffect_Create(gpu_mgr._handle)
        if not self._handle:
            raise RuntimeError("GPUEffect_Create() 返回空句柄")

        self._enabled_effects: Set[EffectType] = set()

    # ------------------------------------------------------------------
    #  函数签名设置（只需三个泛型特效控制函数）
    # ------------------------------------------------------------------
    def _setup_signatures(self):
        h = ctypes.c_void_p

        self.dll.GPUEffect_Create.argtypes = [h]
        self.dll.GPUEffect_Create.restype = h

        self.dll.GPUEffect_Destroy.argtypes = [h]
        self.dll.GPUEffect_Destroy.restype = None

        self.dll.GPUEffect_Initialize.argtypes = [h, h, h]
        self.dll.GPUEffect_Initialize.restype = ctypes.c_int

        self.dll.GPUEffect_Shutdown.argtypes = [h]
        self.dll.GPUEffect_Shutdown.restype = None

        self.dll.GPUEffect_RenderEffectsByID.argtypes = [h, ctypes.c_uint64, ctypes.c_uint64]
        self.dll.GPUEffect_RenderEffectsByID.restype = ctypes.c_uint64

        self.dll.GPUEffect_RegisterSDFPosition.argtypes = [h, ctypes.c_uint64, ctypes.c_float, ctypes.c_float]
        self.dll.GPUEffect_RegisterSDFPosition.restype = None

        self.dll.GPUEffect_GetLastError.argtypes = [h]
        self.dll.GPUEffect_GetLastError.restype = ctypes.c_char_p

        # 泛型特效控制 — 三个函数替代原来所有 Enable/IsEnabled/SetXxxParams
        self.dll.GPUEffect_Enable.argtypes = [h, ctypes.c_int, ctypes.c_int]
        self.dll.GPUEffect_Enable.restype = None

        self.dll.GPUEffect_IsEnabled.argtypes = [h, ctypes.c_int]
        self.dll.GPUEffect_IsEnabled.restype = ctypes.c_int

        self.dll.GPUEffect_SetParam.argtypes = [h, ctypes.c_int, ctypes.c_char_p, ctypes.c_float]
        self.dll.GPUEffect_SetParam.restype = None

    # ------------------------------------------------------------------
    #  生命周期
    # ------------------------------------------------------------------

    def initialize(self, device_ptr: int, context_ptr: int) -> bool:
        return self.dll.GPUEffect_Initialize(self._handle, device_ptr, context_ptr) != 0

    def shutdown(self):
        if self._handle:
            self.dll.GPUEffect_Shutdown(self._handle)
            self.dll.GPUEffect_Destroy(self._handle)
            self._handle = None
            self._enabled_effects.clear()

    def __del__(self):
        if getattr(self, '_handle', None):
            self.shutdown()

    # ------------------------------------------------------------------
    #  渲染
    # ------------------------------------------------------------------

    def render_effects_by_id(self, screen_resource_id: int, sdf_resource_id: int) -> int:
        """渲染特效，返回输出纹理 ID"""
        if sdf_resource_id in _sdf_position_cache:
            x, y = _sdf_position_cache[sdf_resource_id]
            self.dll.GPUEffect_RegisterSDFPosition(self._handle, sdf_resource_id, x, y)
        return self.dll.GPUEffect_RenderEffectsByID(self._handle, screen_resource_id, sdf_resource_id)

    # ------------------------------------------------------------------
    #  内部工具：展开颜色/向量参数
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_params(param_dict: dict) -> Dict[str, float]:
        """
        将 effects_params.py 中的参数展开为 {key: float} 字典。
        - type="color" (3-tuple) → key_r, key_g, key_b
        - type="color" (4-tuple) → key_r, key_g, key_b, key_a
        - type="vec3"            → key_r, key_g, key_b
        - 其余类型               → key: float(value)
        """
        result: Dict[str, float] = {}
        for key, info in param_dict.items():
            if key == "enable":
                continue
            ptype = info.get("type", "float")
            value = info.get("value", info.get("default", 0.0))
            if ptype in ("color", "vec3"):
                result[f"{key}_r"] = float(value[0])
                result[f"{key}_g"] = float(value[1])
                result[f"{key}_b"] = float(value[2])
                if ptype == "color" and len(value) == 4:
                    result[f"{key}_a"] = float(value[3])
            else:
                result[key] = float(value)
        return result

    def _set_effect_params(self, effect_type: EffectType, flat_params: Dict[str, float]):
        """将展开后的参数逐个发送给 C++ 层"""
        etype_int = ctypes.c_int(int(effect_type))
        for key, val in flat_params.items():
            self.dll.GPUEffect_SetParam(
                self._handle, etype_int,
                key.encode("utf-8"),
                ctypes.c_float(val)
            )

    # ------------------------------------------------------------------
    #  特效批量控制
    # ------------------------------------------------------------------

    def enable_effects(self, effect_types: List[EffectType], effects_params=None):
        """
        启用 effect_types 中的特效并向渲染器推送参数；未在列表中的特效自动关闭。
        effects_params 可传入自定义参数字典（格式同 EFFECTS_PARAMS），不传则使用默认值。
        """
        if effects_params is None:
            effects_params = EFFECTS_PARAMS

        new_effects = set(effect_types)

        for effect in EffectType:
            effect_name = EFFECT_TYPE_MAPPING.get(effect, "")
            should_enable = effect in new_effects

            # 推送参数（无论是否启用，保持参数最新）
            effect_cfg = effects_params.get(effect_name, {})
            param_dict  = effect_cfg.get("params", {})
            if param_dict:
                flat = self._expand_params(param_dict)
                self._set_effect_params(effect, flat)

            # 启用/禁用
            self.dll.GPUEffect_Enable(self._handle, int(effect), 1 if should_enable else 0)

        self._enabled_effects = new_effects

    def update_effects(self, effects_params=None):
        """用新参数刷新当前已启用特效的参数（不改变启/停状态）"""
        self.enable_effects(list(self._enabled_effects), effects_params)

    def get_enabled_effects(self) -> List[EffectType]:
        return list(self._enabled_effects)

    def is_effect_enabled(self, effect_type: EffectType) -> bool:
        return self.dll.GPUEffect_IsEnabled(self._handle, int(effect_type)) != 0

    # ------------------------------------------------------------------
    #  单个参数设置（供 UI 实时调节使用）
    # ------------------------------------------------------------------

    def set_param(self, effect_type: EffectType, key: str, value: float):
        """直接设置单个参数（float），整数参数以 float 传入"""
        self.dll.GPUEffect_SetParam(
            self._handle, int(effect_type),
            key.encode("utf-8"),
            ctypes.c_float(float(value))
        )

    # ------------------------------------------------------------------
    #  调试
    # ------------------------------------------------------------------

    def get_last_error(self) -> str:
        err = self.dll.GPUEffect_GetLastError(self._handle)
        return err.decode("utf-8") if err else ""
