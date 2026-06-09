#include "gpu_effect_renderer.h"
#include "gpu_effect_registry.h"
#include <algorithm>
#include <vector>
#include <cstring>
#include <stdio.h>

// 引入 GPUResourcePool
#include "../../GPUDeviceManager/src/gpu_resource_pool.h"

bool GPUEffectRenderer::Initialize(ID3D11Device* device, ID3D11DeviceContext* context) {
    if (!device || !context) {
        return false;
    }

    if (!resourcePool) {
        snprintf(lastError, sizeof(lastError), "ResourcePool not set, call SetResourcePool() first");
        return false;
    }
    
    if (initialized) {
        Shutdown();
    }
    
    this->device = device;
    this->context = context;
    
    // 通过注册表自动实例化所有已注册特效，无需 #include 各特效头文件
    auto& entries = GPUEffectRegistry::Entries();
    for (auto& kv : entries) {
        GPUEffectType type = kv.first;
        GPUEffectBase* effect = kv.second.factory();
        if (!effect->Initialize(device)) {
            delete effect;
            snprintf(lastError, sizeof(lastError), "Failed to initialize effect type %d", (int)type);
            return false;
        }
        effects[type] = effect;
    }
    
    enabledEffects.clear();
    
    initialized = true;
    return true;
}

uint64_t GPUEffectRenderer::RenderEffectsByID(uint64_t screenResourceID, uint64_t sdfResourceID) {
    if (!initialized) {
        return 0;
    }
    
    // 获取资源指针
    ID3D11Texture2D* screenTex = nullptr;
    ID3D11ShaderResourceView* screenSRV = nullptr;
    ID3D11ShaderResourceView* sdfSRV = nullptr;
    int width = 0, height = 0, ownerGPU = 0;
    
    if (!GetResourcePointers(screenResourceID, sdfResourceID,
                            &screenTex, &screenSRV, &sdfSRV,
                            &width, &height, &ownerGPU)) {
        return 0;
    }
    
    // 从注册的 SDF 位置获取屏幕坐标
    float posX = 0.0f, posY = 0.0f;
    {
        auto posIt = sdfPositions.find(sdfResourceID);
        if (posIt != sdfPositions.end()) {
            posX = posIt->second.first;
            posY = posIt->second.second;
        }
    }

    // 获取排序后的启用特效列表（按注册表 renderPriority 升序）
    std::vector<GPUEffectType> sortedEffects = GetSortedEnabledEffects();
    
    // 如果没有启用的特效，直接返回输入纹理 ID
    if (sortedEffects.empty()) {
        return screenResourceID;
    }
    
    // 设置视口
    D3D11_VIEWPORT viewport = {};
    viewport.Width = (float)width;
    viewport.Height = (float)height;
    viewport.MinDepth = 0.0f;
    viewport.MaxDepth = 1.0f;
    context->RSSetViewports(1, &viewport);
    
    // 使用 ping-pong 缓冲渲染所有特效
    ID3D11ShaderResourceView* currentInputSRV = screenSRV;
    uint64_t currentInputID = screenResourceID;
    
    auto& pool = *resourcePool;
    
    for (size_t i = 0; i < sortedEffects.size(); ++i) {
        GPUEffectType effectType = sortedEffects[i];
        auto it = effects.find(effectType);
        if (it == effects.end()) continue;
        
        GPUEffectBase* effect = it->second;
        
        // 通过泛型接口构建当前特效所需的 params 缓冲区
        size_t paramsSize = effect->ParamsSize();
        std::vector<uint8_t> paramsBuf(paramsSize, 0);
        effect->BuildParams(m_params[static_cast<int>(effectType)],
                            (float)width, (float)height,
                            posX, posY,
                            paramsBuf.data(), paramsSize);
        
        // 确定输出纹理
        uint64_t outputID = 0;
        if (i == sortedEffects.size() - 1) {
            outputID = GetOrCreateOutputTexture(width, height, ownerGPU);
        } else {
            outputID = GetOrCreateTempTexture((int)i % 2, width, height, ownerGPU);
        }
        
        if (!outputID) {
            return 0;
        }
        
        // 获取输出纹理和 RTV
        auto* outputRes = pool.GetResource(outputID);
        if (!outputRes || !outputRes->resource) {
            return 0;
        }
        
        ID3D11Texture2D* outputTex = static_cast<ID3D11Texture2D*>(outputRes->resource);
        ID3D11RenderTargetView* outputRTV = nullptr;
        HRESULT hr = device->CreateRenderTargetView(outputTex, nullptr, &outputRTV);
        if (FAILED(hr)) {
            return 0;
        }
        
        // 应用当前特效
        bool success = effect->Apply(context, currentInputSRV, sdfSRV, outputRTV, paramsBuf.data());
        SafeRelease(outputRTV);
        
        if (!success) {
            return 0;
        }
        
        // 更新下一次迭代的输入
        if (i < sortedEffects.size() - 1) {
            auto* nextInputRes = pool.GetResource(outputID);
            if (!nextInputRes || !nextInputRes->srv) {
                // 创建 SRV
                ID3D11ShaderResourceView* newSRV = nullptr;
                D3D11_SHADER_RESOURCE_VIEW_DESC srvDesc = {};
                srvDesc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
                srvDesc.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
                srvDesc.Texture2D.MipLevels = 1;
                
                hr = device->CreateShaderResourceView(outputTex, &srvDesc, &newSRV);
                if (FAILED(hr)) {
                    return 0;
                }
                currentInputSRV = newSRV;
            } else {
                currentInputSRV = static_cast<ID3D11ShaderResourceView*>(nextInputRes->srv);
            }
            currentInputID = outputID;
        } else {
            currentInputID = outputID;
        }
    }
    
    return currentInputID;
}

bool GPUEffectRenderer::GetResourcePointers(
    uint64_t screenResourceID,
    uint64_t sdfResourceID,
    ID3D11Texture2D** outScreenTex,
    ID3D11ShaderResourceView** outScreenSRV,
    ID3D11ShaderResourceView** outSdfSRV,
    int* outWidth,
    int* outHeight,
    int* outOwnerGPU
) {
    auto& pool = *resourcePool;
    
    auto* screenRes = pool.GetResource(screenResourceID);
    if (!screenRes || !screenRes->resource) {
        return false;
    }
    
    auto* sdfRes = pool.GetResource(sdfResourceID);
    if (!sdfRes || !sdfRes->srv) {
        return false;
    }
    
    *outScreenTex = static_cast<ID3D11Texture2D*>(screenRes->resource);
    *outSdfSRV = static_cast<ID3D11ShaderResourceView*>(sdfRes->srv);
    *outWidth = screenRes->width;
    *outHeight = screenRes->height;
    *outOwnerGPU = screenRes->ownerGPUIndex;
    
    // 为截图创建 SRV（如果没有）
    if (!screenRes->srv) {
        D3D11_SHADER_RESOURCE_VIEW_DESC srvDesc = {};
        srvDesc.Format = (DXGI_FORMAT)screenRes->format;
        srvDesc.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
        srvDesc.Texture2D.MipLevels = 1;
        
        HRESULT hr = device->CreateShaderResourceView(*outScreenTex, &srvDesc, outScreenSRV);
        if (FAILED(hr)) {
            return false;
        }
    } else {
        *outScreenSRV = static_cast<ID3D11ShaderResourceView*>(screenRes->srv);
    }
    
    return true;
}

uint64_t GPUEffectRenderer::GetOrCreateOutputTexture(int width, int height, int ownerGPU) {
    auto key = std::make_pair(width, height);
    
    auto it = outputCache.find(key);
    if (it != outputCache.end()) {
        return it->second;
    }
    
    auto& pool = *resourcePool;
    for (auto& pair : outputCache) {
        pool.RemoveResource(pair.second);
    }
    outputCache.clear();
    
    GPUResourceDesc desc;
    desc.type = GPUResourceType::Texture2D;
    desc.width = width;
    desc.height = height;
    desc.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.bindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
    desc.usage = D3D11_USAGE_DEFAULT;
    desc.tag = "GPUEffectRenderer_Output";
    
    uint64_t outputID = pool.CreateResource(desc, ownerGPU, nullptr,
                                           RESOURCE_SLOT_EFFECT_BEGIN,
                                           RESOURCE_SLOT_EFFECT_END);
    
    if (outputID) {
        outputCache[key] = outputID;
    }
    
    return outputID;
}

uint64_t GPUEffectRenderer::GetOrCreateTempTexture(int index, int width, int height, int ownerGPU) {
    auto key = std::make_tuple(index, width, height);
    
    auto it = tempTextureCache.find(key);
    if (it != tempTextureCache.end()) {
        return it->second;
    }
    
    bool sizeChanged = false;
    for (auto& pair : tempTextureCache) {
        if (std::get<1>(pair.first) != width || std::get<2>(pair.first) != height) {
            sizeChanged = true;
            break;
        }
    }
    
    if (sizeChanged) {
        auto& pool = *resourcePool;
        for (auto& pair : tempTextureCache) {
            pool.RemoveResource(pair.second);
        }
        tempTextureCache.clear();
    }
    
    auto& pool = *resourcePool;
    GPUResourceDesc desc;
    desc.type = GPUResourceType::Texture2D;
    desc.width = width;
    desc.height = height;
    desc.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.bindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
    desc.usage = D3D11_USAGE_DEFAULT;
    desc.tag = index == 0 ? "GPUEffectRenderer_Temp0" : "GPUEffectRenderer_Temp1";
    
    uint64_t tempID = pool.CreateResource(desc, ownerGPU, nullptr,
                                         RESOURCE_SLOT_EFFECT_BEGIN,
                                         RESOURCE_SLOT_EFFECT_END);
    
    if (tempID) {
        tempTextureCache[key] = tempID;
    }
    
    return tempID;
}

std::vector<GPUEffectType> GPUEffectRenderer::GetSortedEnabledEffects() const {
    // 按注册表 renderPriority 升序排列已启用特效
    auto& entries = GPUEffectRegistry::Entries();
    
    std::vector<std::pair<int, GPUEffectType>> prioritized;
    for (auto& type : enabledEffects) {
        auto eit = entries.find(type);
        int priority = (eit != entries.end()) ? eit->second.renderPriority : 999;
        prioritized.push_back({priority, type});
    }
    
    std::sort(prioritized.begin(), prioritized.end(),
              [](const auto& a, const auto& b) { return a.first < b.first; });
    
    std::vector<GPUEffectType> sorted;
    for (auto& p : prioritized) {
        sorted.push_back(p.second);
    }
    return sorted;
}

void GPUEffectRenderer::EnableEffect(GPUEffectType type) {
    if (std::find(enabledEffects.begin(), enabledEffects.end(), type) != enabledEffects.end()) {
        return;
    }
    if (effects.find(type) != effects.end()) {
        enabledEffects.push_back(type);
    }
}

void GPUEffectRenderer::DisableEffect(GPUEffectType type) {
    auto it = std::find(enabledEffects.begin(), enabledEffects.end(), type);
    if (it != enabledEffects.end()) {
        enabledEffects.erase(it);
    }
}

bool GPUEffectRenderer::IsEffectEnabled(GPUEffectType type) const {
    return std::find(enabledEffects.begin(), enabledEffects.end(), type) != enabledEffects.end();
}

void GPUEffectRenderer::SetParam(GPUEffectType type, const char* key, float value) {
    m_params[static_cast<int>(type)][key] = value;
}

void GPUEffectRenderer::RegisterSDFPosition(uint64_t sdfId, float x, float y) {
    sdfPositions[sdfId] = {x, y};
}

void GPUEffectRenderer::Shutdown() {
    for (auto& pair : effects) {
        if (pair.second) {
            pair.second->Shutdown();
            delete pair.second;
        }
    }
    effects.clear();
    enabledEffects.clear();
    
    if (resourcePool) {
        auto& pool = *resourcePool;
        for (auto& pair : outputCache) {
            pool.RemoveResource(pair.second);
        }
        for (auto& pair : tempTextureCache) {
            pool.RemoveResource(pair.second);
        }
    }
    outputCache.clear();
    tempTextureCache.clear();
    
    device = nullptr;
    context = nullptr;
    initialized = false;
}

