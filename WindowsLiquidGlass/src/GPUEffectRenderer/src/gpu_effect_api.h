#pragma once

#include <stdint.h>

#ifdef GPU_EFFECT_RENDERER_EXPORTS
#define GPUEFFECT_API __declspec(dllexport)
#else
#define GPUEFFECT_API __declspec(dllimport)
#endif

extern "C" {
    // ========== 生命周期 ==========
    GPUEFFECT_API void* __stdcall GPUEffect_Create(void* gpuMgrHandle);
    GPUEFFECT_API void  __stdcall GPUEffect_Destroy(void* handle);

    // ========== 初始化 ==========
    GPUEFFECT_API int  __stdcall GPUEffect_Initialize(void* handle, void* devicePtr, void* contextPtr);
    GPUEFFECT_API void __stdcall GPUEffect_Shutdown(void* handle);

    // ========== 核心渲染 ==========
    // 通过资源 ID 渲染，返回输出纹理 ID（0 表示失败）
    GPUEFFECT_API uint64_t __stdcall GPUEffect_RenderEffectsByID(
        void* handle,
        uint64_t screenResourceID,
        uint64_t sdfResourceID
    );

    // 注册 SDF 屏幕坐标（每次 generate_sdf_id 后调用）
    GPUEFFECT_API void __stdcall GPUEffect_RegisterSDFPosition(
        void* handle, uint64_t sdfId, float x, float y
    );

    // ========== 泛型特效控制 ==========
    // effectType 与 GPUEffectType 枚举值对应
    GPUEFFECT_API void __stdcall GPUEffect_Enable(void* handle, int effectType, int enabled);
    GPUEFFECT_API int  __stdcall GPUEffect_IsEnabled(void* handle, int effectType);

    // key 与 effects_params.py 中参数名一致；整数参数以 float 传入，内部转换
    GPUEFFECT_API void __stdcall GPUEffect_SetParam(
        void* handle, int effectType, const char* key, float value
    );

    // ========== 调试 ==========
    GPUEFFECT_API const char* __stdcall GPUEffect_GetLastError(void* handle);
}


