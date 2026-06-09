/*
 * 文件名: gpu_effect_api.cpp
 * 功能: GPU 特效渲染器 C API 实现（多实例版本）
 *
 * 用法:
 *   void* mgr = GPUMgr_Create();
 *   GPUMgr_Initialize(mgr, 0);
 *   void* eff = GPUEffect_Create(mgr);   // 共享 ResourcePool
 *   GPUEffect_Initialize(eff, device, context);
 *   ...
 *   GPUEffect_Destroy(eff);
 *   GPUMgr_Destroy(mgr);
 */

#include "gpu_effect_api.h"
#include "gpu_effect_renderer.h"
#include "../../GPUDeviceManager/src/gpu_resource_pool.h"
#include "../../GPUDeviceManager/src/gpu_manager_api.h"
#include <d3d11.h>

// ============================================================
//  GPUEffectContext — 包装 GPUEffectRenderer 实例
// ============================================================

struct GPUEffectContext {
    GPUEffectRenderer* renderer = nullptr;

    explicit GPUEffectContext(GPUResourcePool* pool) {
        renderer = new GPUEffectRenderer();
        renderer->SetResourcePool(pool);
    }
    ~GPUEffectContext() {
        delete renderer;
        renderer = nullptr;
    }
    GPUEffectContext(const GPUEffectContext&) = delete;
    GPUEffectContext& operator=(const GPUEffectContext&) = delete;
};

// GPUMgr_GetResourcePoolPtr 在 gpu_manager_api.cpp 中导出，
// 返回 GPUContext 内部的 GPUResourcePool* 指针。
extern "C" GPUMGR_API void* __stdcall GPUMgr_GetResourcePoolPtr(void* handle);

static inline GPUEffectContext* EFX(void* h) { return static_cast<GPUEffectContext*>(h); }
static inline GPUEffectRenderer* RND(void* h) {
    auto* c = EFX(h);
    return c ? c->renderer : nullptr;
}

// ============================================================
//  生命周期
// ============================================================

GPUEFFECT_API void* __stdcall GPUEffect_Create(void* gpuMgrHandle) {
    if (!gpuMgrHandle) return nullptr;
    GPUResourcePool* pool = static_cast<GPUResourcePool*>(GPUMgr_GetResourcePoolPtr(gpuMgrHandle));
    if (!pool) return nullptr;
    return new GPUEffectContext(pool);
}

GPUEFFECT_API void __stdcall GPUEffect_Destroy(void* handle) {
    delete EFX(handle);
}

// ============================================================
//  初始化
// ============================================================

GPUEFFECT_API int __stdcall GPUEffect_Initialize(void* handle, void* devicePtr, void* contextPtr) {
    auto* r = RND(handle);
    if (!r || !devicePtr || !contextPtr) return 0;
    return r->Initialize(
        static_cast<ID3D11Device*>(devicePtr),
        static_cast<ID3D11DeviceContext*>(contextPtr)
    ) ? 1 : 0;
}

GPUEFFECT_API void __stdcall GPUEffect_Shutdown(void* handle) {
    auto* r = RND(handle);
    if (r) r->Shutdown();
}

GPUEFFECT_API uint64_t __stdcall GPUEffect_RenderEffectsByID(
    void* handle,
    uint64_t screenResourceID,
    uint64_t sdfResourceID
) {
    auto* r = RND(handle);
    return r ? r->RenderEffectsByID(screenResourceID, sdfResourceID) : 0;
}

GPUEFFECT_API void __stdcall GPUEffect_RegisterSDFPosition(
    void* handle, uint64_t sdfId, float x, float y
) {
    auto* r = RND(handle);
    if (r) r->RegisterSDFPosition(sdfId, x, y);
}

GPUEFFECT_API const char* __stdcall GPUEffect_GetLastError(void* handle) {
    auto* r = RND(handle);
    return r ? r->GetLastError() : "";
}

// ========== 泛型特效控制 ==========

GPUEFFECT_API void __stdcall GPUEffect_Enable(void* handle, int effectType, int enabled) {
    auto* r = RND(handle);
    if (!r) return;
    auto type = static_cast<GPUEffectType>(effectType);
    enabled ? r->EnableEffect(type) : r->DisableEffect(type);
}

GPUEFFECT_API int __stdcall GPUEffect_IsEnabled(void* handle, int effectType) {
    auto* r = RND(handle);
    return r ? (r->IsEffectEnabled(static_cast<GPUEffectType>(effectType)) ? 1 : 0) : 0;
}

GPUEFFECT_API void __stdcall GPUEffect_SetParam(
    void* handle, int effectType, const char* key, float value
) {
    auto* r = RND(handle);
    if (!r || !key) return;
    r->SetParam(static_cast<GPUEffectType>(effectType), key, value);
}

