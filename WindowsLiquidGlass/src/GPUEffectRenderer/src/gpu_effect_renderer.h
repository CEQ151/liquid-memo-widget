#pragma once

/*
 * gpu_effect_renderer.h — 重构后的泛型渲染器
 *
 * 添加新特效无需修改此文件。
 * 只需在新特效的 .cpp 末尾写 REGISTER_EFFECT(...)，并在 effects_params.py 中
 * 添加参数定义，渲染器会自动发现并管理该特效。
 */

#include "gpu_effect_types.h"
#include "gpu_effect_base.h"
#include "gpu_effect_registry.h"
#include <vector>
#include <map>
#include <unordered_map>
#include <utility>
#include <tuple>
#include <cstdint>

class GPUResourcePool;
#include "../../GPUDeviceManager/src/gpu_resource_pool.h"

class GPUEffectRenderer {
public:
    GPUEffectRenderer() = default;
    ~GPUEffectRenderer() { Shutdown(); }

    GPUEffectRenderer(const GPUEffectRenderer&) = delete;
    GPUEffectRenderer& operator=(const GPUEffectRenderer&) = delete;

    void SetResourcePool(GPUResourcePool* pool) { resourcePool = pool; }

    // 初始化：通过注册表自动实例化所有已注册特效，无需 #include 各特效头文件
    bool Initialize(ID3D11Device* device, ID3D11DeviceContext* context);

    // 核心渲染（接口不变）
    uint64_t RenderEffectsByID(uint64_t screenResourceID, uint64_t sdfResourceID);

    // SDF 屏幕坐标注册（接口不变）
    void RegisterSDFPosition(uint64_t sdfId, float x, float y);

    // 特效启/停
    void EnableEffect(GPUEffectType type);
    void DisableEffect(GPUEffectType type);
    bool IsEffectEnabled(GPUEffectType type) const;

    // ── 泛型参数设置 ──────────────────────────────────────────────────────────
    // key 与 effects_params.py 中的参数名一致（整数参数也以 float 传入，内部转换）
    void SetParam(GPUEffectType type, const char* key, float value);

    void Shutdown();
    const char* GetLastError() const { return lastError; }

private:
    uint64_t GetOrCreateOutputTexture(int width, int height, int ownerGPU);
    uint64_t GetOrCreateTempTexture(int index, int width, int height, int ownerGPU);

    bool GetResourcePointers(
        uint64_t screenResourceID, uint64_t sdfResourceID,
        ID3D11Texture2D** outScreenTex,
        ID3D11ShaderResourceView** outScreenSRV,
        ID3D11ShaderResourceView** outSdfSRV,
        int* outWidth, int* outHeight, int* outOwnerGPU
    );

    // 按注册表 renderPriority 升序返回已启用特效列表
    std::vector<GPUEffectType> GetSortedEnabledEffects() const;

    ID3D11Device*        device      = nullptr;
    ID3D11DeviceContext* context     = nullptr;
    bool                 initialized = false;

    std::map<GPUEffectType, GPUEffectBase*> effects;
    std::vector<GPUEffectType>              enabledEffects;

    // 泛型参数存储：effectType(int) → { paramKey → float }
    std::unordered_map<int, ParamMap> m_params;

    // SDF ID → (screenX, screenY)
    std::unordered_map<uint64_t, std::pair<float, float>> sdfPositions;

    std::map<std::pair<int, int>, uint64_t>       outputCache;
    std::map<std::tuple<int, int, int>, uint64_t> tempTextureCache;

    char             lastError[256] = {0};
    GPUResourcePool* resourcePool   = nullptr;

    template<typename T>
    void SafeRelease(T*& ptr) {
        if (ptr) { ptr->Release(); ptr = nullptr; }
    }
};
