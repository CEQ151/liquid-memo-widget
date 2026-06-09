/*
 * 文件名: gpu_resource_pool.cpp
 * 功能: GPU资源缓存池实现
 */

#include "gpu_resource_pool.h"
#include "gpu_device_manager.h"

// ============================================================
//  单例实现
// ============================================================

GPUResourcePool::~GPUResourcePool() {
    ClearPool();
}

// ============================================================
//  ID 分配 / 回收
// ============================================================

UINT64 GPUResourcePool::AllocId(UINT64 slotBegin, UINT64 slotEnd) {
    // 注册段信息（首次调用时）
    if (slotStates.find(slotBegin) == slotStates.end()) {
        slotStates[slotBegin].next = 0;
        slotEndMap[slotBegin] = slotEnd;
    }

    auto& state = slotStates[slotBegin];
    UINT64 capacity = slotEnd - slotBegin + 1;

    // 优先从空闲池取
    if (!state.free.empty()) {
        UINT64 id = *state.free.begin();
        state.free.erase(state.free.begin());
        idToSlotBegin[id] = slotBegin;
        return id;
    }

    // 段未满，取下一个新槽
    if (state.next < capacity) {
        UINT64 id = slotBegin + state.next;
        state.next++;
        idToSlotBegin[id] = slotBegin;
        return id;
    }

    // 段已满（所有槽都在使用中），返回 0 表示失败
    // 实际使用中单段 1000 个槽同时在用几乎不可能触发
    return 0;
}

void GPUResourcePool::FreeId(UINT64 id) {
    auto it = idToSlotBegin.find(id);
    if (it == idToSlotBegin.end()) return;

    UINT64 slotBegin = it->second;
    idToSlotBegin.erase(it);

    auto stateIt = slotStates.find(slotBegin);
    if (stateIt != slotStates.end()) {
        stateIt->second.free.insert(id);
    }
}

// ============================================================
//  添加资源
// ============================================================

UINT64 GPUResourcePool::AddResource(void* resource, GPUResourceType type, void* srv,
                                    int ownerGPU, const char* tag,
                                    UINT64 slotBegin, UINT64 slotEnd) {
    if (!resource) return 0;

    if (!m_devMgr) return 0;
    auto& deviceMgr = *m_devMgr;
    if (ownerGPU < 0 || ownerGPU >= deviceMgr.GetGPUCount()) return 0;

    UINT64 resourceId = AllocId(slotBegin, slotEnd);
    if (!resourceId && resourceId != 0) return 0; // 段满
    // 注意：slotBegin 可以为 0，ID=0 保留为"无效"，AllocId 从 slotBegin 开始
    // 若 slotBegin=0 且分配到 0，需特殊处理 —— 实际 Capture 段从 0 开始时
    // ID=0 是无效标记，因此 Capture_Begin 建议从 1 开始（见下方说明）

    CachedGPUResource cached;
    cached.id           = resourceId;
    cached.type         = type;
    cached.ownerGPUIndex= ownerGPU;
    cached.resource     = resource;
    cached.srv          = srv;
    if (tag) cached.tag = tag;

    if (type == GPUResourceType::Texture2D) {
        ID3D11Texture2D* tex = static_cast<ID3D11Texture2D*>(resource);
        D3D11_TEXTURE2D_DESC desc; tex->GetDesc(&desc);
        cached.width       = desc.Width;
        cached.height      = desc.Height;
        cached.format      = desc.Format;
        cached.sizeInBytes = desc.Width * desc.Height * 4;

        if (!srv && (desc.BindFlags & D3D11_BIND_SHADER_RESOURCE)) {
            ID3D11Device* device = deviceMgr.GetDeviceByGPUIndex(ownerGPU);
            if (device) {
                D3D11_SHADER_RESOURCE_VIEW_DESC srvDesc = {};
                srvDesc.Format                    = desc.Format;
                srvDesc.ViewDimension             = D3D11_SRV_DIMENSION_TEXTURE2D;
                srvDesc.Texture2D.MipLevels       = desc.MipLevels;
                srvDesc.Texture2D.MostDetailedMip = 0;
                ID3D11ShaderResourceView* newSRV  = nullptr;
                if (SUCCEEDED(device->CreateShaderResourceView(tex, &srvDesc, &newSRV)))
                    cached.srv = newSRV;
            }
        }
        tex->AddRef();
    } else if (type == GPUResourceType::Buffer) {
        ID3D11Buffer* buf = static_cast<ID3D11Buffer*>(resource);
        D3D11_BUFFER_DESC desc; buf->GetDesc(&desc);
        cached.sizeInBytes = desc.ByteWidth;
        buf->AddRef();
    }

    if (srv) static_cast<ID3D11ShaderResourceView*>(srv)->AddRef();

    resourcePool[resourceId] = cached;
    if (!cached.tag.empty()) tagIndex.insert({cached.tag, resourceId});

    return resourceId;
}

// ============================================================
//  创建资源
// ============================================================

UINT64 GPUResourcePool::CreateResource(const GPUResourceDesc& desc, int gpuIndex,
                                       const void* initialData,
                                       UINT64 slotBegin, UINT64 slotEnd) {
    if (!m_devMgr) return 0;
    auto& deviceMgr = *m_devMgr;
    if (gpuIndex < 0 || gpuIndex >= deviceMgr.GetGPUCount()) return 0;
    if (!deviceMgr.GetDeviceByGPUIndex(gpuIndex)) return 0;

    CachedGPUResource resource;
    if (desc.type == GPUResourceType::Texture2D) {
        if (!CreateTexture2D(desc, gpuIndex, initialData, resource)) return 0;
    } else if (desc.type == GPUResourceType::Buffer) {
        if (!CreateBuffer(desc, gpuIndex, initialData, resource)) return 0;
    } else {
        return 0;
    }

    UINT64 resourceId = AllocId(slotBegin, slotEnd);
    if (!resourceId && slotBegin != 0) return 0;

    resource.id            = resourceId;
    resource.ownerGPUIndex = gpuIndex;
    resource.tag           = desc.tag;

    resourcePool[resourceId] = resource;
    if (!resource.tag.empty()) tagIndex.insert({resource.tag, resourceId});

    return resourceId;
}

bool GPUResourcePool::CreateTexture2D(const GPUResourceDesc& desc, int gpuIndex, 
                                     const void* initialData, CachedGPUResource& outResource) {
    if (!m_devMgr) return false;
    auto& deviceMgr = *m_devMgr;
    auto* device = deviceMgr.GetDeviceByGPUIndex(gpuIndex);
    
    if (!device) return false;
    
    D3D11_TEXTURE2D_DESC texDesc = {};
    texDesc.Width = desc.width;
    texDesc.Height = desc.height;
    texDesc.MipLevels = 1;
    texDesc.ArraySize = 1;
    texDesc.Format = desc.format;
    texDesc.SampleDesc.Count = 1;
    texDesc.Usage = desc.usage;
    texDesc.BindFlags = desc.bindFlags;
    
    if (desc.usage == D3D11_USAGE_STAGING) {
        texDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ | D3D11_CPU_ACCESS_WRITE;
    }
    
    D3D11_SUBRESOURCE_DATA initData = {};
    if (initialData) {
        initData.pSysMem = initialData;
        initData.SysMemPitch = desc.width * 4;  // 假设RGBA
    }
    
    ID3D11Texture2D* texture = nullptr;
    HRESULT hr = device->CreateTexture2D(&texDesc, initialData ? &initData : nullptr, &texture);
    if (FAILED(hr)) {
        return false;
    }
    
    outResource.type = GPUResourceType::Texture2D;
    outResource.resource = texture;
    outResource.width = desc.width;
    outResource.height = desc.height;
    outResource.format = desc.format;
    outResource.sizeInBytes = desc.width * desc.height * 4;
    
    const auto& gpuDevices = deviceMgr.GetGPUDevices();
    if (gpuIndex >= 0 && gpuIndex < (int)gpuDevices.size()) {
        outResource.device = gpuDevices[gpuIndex].device;
        outResource.context = gpuDevices[gpuIndex].context;
    }

    // 创建SRV
    if (desc.bindFlags & D3D11_BIND_SHADER_RESOURCE) {
        ID3D11ShaderResourceView* srv = nullptr;
        D3D11_SHADER_RESOURCE_VIEW_DESC srvDesc = {};
        srvDesc.Format = desc.format;
        srvDesc.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
        srvDesc.Texture2D.MipLevels = 1;
        
        hr = device->CreateShaderResourceView(texture, &srvDesc, &srv);
        if (SUCCEEDED(hr)) {
            outResource.srv = srv;
        }
    }
    
    // 创建UAV
    if (desc.bindFlags & D3D11_BIND_UNORDERED_ACCESS) {
        ID3D11UnorderedAccessView* uav = nullptr;
        D3D11_UNORDERED_ACCESS_VIEW_DESC uavDesc = {};
        uavDesc.Format = desc.format;
        uavDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
        
        hr = device->CreateUnorderedAccessView(texture, &uavDesc, &uav);
        if (SUCCEEDED(hr)) {
            outResource.uav = uav;
        }
    }
    
    // 创建RTV
    if (desc.bindFlags & D3D11_BIND_RENDER_TARGET) {
        ID3D11RenderTargetView* rtv = nullptr;
        D3D11_RENDER_TARGET_VIEW_DESC rtvDesc = {};
        rtvDesc.Format = desc.format;
        rtvDesc.ViewDimension = D3D11_RTV_DIMENSION_TEXTURE2D;
        
        hr = device->CreateRenderTargetView(texture, &rtvDesc, &rtv);
        if (SUCCEEDED(hr)) {
            outResource.rtv = rtv;
        }
    }
    
    return true;
}

bool GPUResourcePool::CreateBuffer(const GPUResourceDesc& desc, int gpuIndex,
                                   const void* initialData, CachedGPUResource& outResource) {
    if (!m_devMgr) return false;
    auto& deviceMgr = *m_devMgr;
    auto* device = deviceMgr.GetDeviceByGPUIndex(gpuIndex);
    
    if (!device) return false;
    
    D3D11_BUFFER_DESC bufDesc = {};
    bufDesc.ByteWidth = desc.width;  // 使用width作为字节大小
    bufDesc.Usage = desc.usage;
    bufDesc.BindFlags = desc.bindFlags;
    
    if (desc.usage == D3D11_USAGE_STAGING) {
        bufDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ | D3D11_CPU_ACCESS_WRITE;
    }
    
    D3D11_SUBRESOURCE_DATA initData = {};
    if (initialData) {
        initData.pSysMem = initialData;
    }
    
    ID3D11Buffer* buffer = nullptr;
    HRESULT hr = device->CreateBuffer(&bufDesc, initialData ? &initData : nullptr, &buffer);
    if (FAILED(hr)) {
        return false;
    }
    
    outResource.type = GPUResourceType::Buffer;
    outResource.resource = buffer;
    outResource.sizeInBytes = desc.width;
    
    return true;
}

// ============================================================
//  查询资源
// ============================================================

CachedGPUResource* GPUResourcePool::GetResource(UINT64 resourceId) {
    auto it = resourcePool.find(resourceId);
    if (it != resourcePool.end()) {
        return &it->second;
    }
    return nullptr;
}

std::vector<UINT64> GPUResourcePool::FindResourcesByTag(const char* tag) {
    std::vector<UINT64> result;
    if (!tag) return result;
    
    auto range = tagIndex.equal_range(tag);
    for (auto it = range.first; it != range.second; ++it) {
        result.push_back(it->second);
    }
    
    return result;
}

bool GPUResourcePool::GetResourceInfo(UINT64 resourceId, void** outResource, void** outSRV,
                                      GPUResourceType* outType, int* outWidth, int* outHeight) {
    auto* res = GetResource(resourceId);
    if (!res) return false;
    
    if (outResource) *outResource = res->resource;
    if (outSRV) *outSRV = res->srv;
    if (outType) *outType = res->type;
    if (outWidth) *outWidth = res->width;
    if (outHeight) *outHeight = res->height;
    
    return true;
}


// ============================================================
//  管理资源
// ============================================================

bool GPUResourcePool::UpdateResource(UINT64 resourceId, void* newResource, void* newSRV,
                                     const char* newTag) {
    auto it = resourcePool.find(resourceId);
    if (it == resourcePool.end()) return false;

    auto& res = it->second;

    // Release 旧资源
    if (res.srv)      static_cast<ID3D11ShaderResourceView*>(res.srv)->Release();
    if (res.resource) static_cast<ID3D11Resource*>(res.resource)->Release();

    // AddRef 新资源
    if (newResource) static_cast<ID3D11Resource*>(newResource)->AddRef();
    if (newSRV)      static_cast<ID3D11ShaderResourceView*>(newSRV)->AddRef();

    res.resource = newResource;
    res.srv      = newSRV;

    // 更新尺寸信息
    if (newResource && res.type == GPUResourceType::Texture2D) {
        ID3D11Texture2D* tex = static_cast<ID3D11Texture2D*>(newResource);
        D3D11_TEXTURE2D_DESC desc; tex->GetDesc(&desc);
        res.width       = desc.Width;
        res.height      = desc.Height;
        res.format      = desc.Format;
        res.sizeInBytes = desc.Width * desc.Height * 4;
    }

    // 更新 tag 索引
    if (newTag && res.tag != newTag) {
        if (!res.tag.empty()) {
            auto range = tagIndex.equal_range(res.tag);
            for (auto tagIt = range.first; tagIt != range.second; ++tagIt) {
                if (tagIt->second == resourceId) { tagIndex.erase(tagIt); break; }
            }
        }
        res.tag = newTag;
        if (!res.tag.empty()) tagIndex.insert({res.tag, resourceId});
    }

    return true;
}

void GPUResourcePool::RemoveResource(UINT64 resourceId) {
    auto it = resourcePool.find(resourceId);
    if (it == resourcePool.end()) return;

    auto& res = it->second;
    if (res.rtv)      static_cast<ID3D11RenderTargetView*>(res.rtv)->Release();
    if (res.uav)      static_cast<ID3D11UnorderedAccessView*>(res.uav)->Release();
    if (res.srv)      static_cast<ID3D11ShaderResourceView*>(res.srv)->Release();
    if (res.resource) static_cast<ID3D11Resource*>(res.resource)->Release();

    if (!res.tag.empty()) {
        auto range = tagIndex.equal_range(res.tag);
        for (auto tagIt = range.first; tagIt != range.second; ++tagIt) {
            if (tagIt->second == resourceId) { tagIndex.erase(tagIt); break; }
        }
    }

    resourcePool.erase(it);
    FreeId(resourceId);   // ← 归还 ID 到空闲池
}

void GPUResourcePool::ClearPool() {
    for (auto& pair : resourcePool) {
        auto& res = pair.second;
        if (res.rtv)      static_cast<ID3D11RenderTargetView*>(res.rtv)->Release();
        if (res.uav)      static_cast<ID3D11UnorderedAccessView*>(res.uav)->Release();
        if (res.srv)      static_cast<ID3D11ShaderResourceView*>(res.srv)->Release();
        if (res.resource) static_cast<ID3D11Resource*>(res.resource)->Release();
    }
    resourcePool.clear();
    tagIndex.clear();
    slotStates.clear();
    idToSlotBegin.clear();
    slotEndMap.clear();
}

PoolStats GPUResourcePool::GetStats() const {
    PoolStats stats;
    stats.totalResources = static_cast<int>(resourcePool.size());
    stats.totalMemoryBytes = 0;
    
    for (const auto& pair : resourcePool) {
        const auto& res = pair.second;
        
        stats.totalMemoryBytes += res.sizeInBytes;
        stats.resourcesByType[res.type]++;
        stats.resourcesByGPU[res.ownerGPUIndex]++;
    }
    
    return stats;
}

// ============================================================
//  跨GPU拷贝
// ============================================================

UINT64 GPUResourcePool::CopyToGPU(UINT64 srcResourceId, int dstGPUIndex) {
    auto* srcRes = GetResource(srcResourceId);
    if (!srcRes) return 0;
    
    if (srcRes->ownerGPUIndex == dstGPUIndex) {
        return srcResourceId;  // 已经在目标GPU上
    }
    
    if (!m_devMgr) return 0;
    auto& deviceMgr = *m_devMgr;
    if (dstGPUIndex < 0 || dstGPUIndex >= deviceMgr.GetGPUCount()) {
        return 0;
    }
    
    auto* dstDevice = deviceMgr.GetDeviceByGPUIndex(dstGPUIndex);
    if (!dstDevice) return 0;
    
    // 创建目标资源
    if (srcRes->type == GPUResourceType::Texture2D) {
        GPUResourceDesc desc;
        desc.type = GPUResourceType::Texture2D;
        desc.width = srcRes->width;
        desc.height = srcRes->height;
        desc.format = srcRes->format;
        desc.bindFlags = D3D11_BIND_SHADER_RESOURCE;
        desc.usage = D3D11_USAGE_DEFAULT;
        desc.tag = srcRes->tag;
        
        CachedGPUResource dstRes;
        if (!CreateTexture2D(desc, dstGPUIndex, nullptr, dstRes)) {
            return 0;
        }
        
        // 跨GPU拷贝
        if (!CopyCrossGPU(srcRes->resource, srcRes->ownerGPUIndex,
                         dstRes.resource, dstGPUIndex, srcRes->type)) {
            if (dstRes.srv) static_cast<ID3D11ShaderResourceView*>(dstRes.srv)->Release();
            if (dstRes.resource) static_cast<ID3D11Texture2D*>(dstRes.resource)->Release();
            return 0;
        }
        
        // 添加到缓存池
        UINT64 newId = AllocId(RESOURCE_SLOT_CAPTURE_BEGIN, RESOURCE_SLOT_CAPTURE_END);
        if (!newId) {
            if (dstRes.srv)      static_cast<ID3D11ShaderResourceView*>(dstRes.srv)->Release();
            if (dstRes.resource) static_cast<ID3D11Texture2D*>(dstRes.resource)->Release();
            return 0;
        }
        dstRes.id            = newId;
        dstRes.ownerGPUIndex = dstGPUIndex;

        resourcePool[newId] = dstRes;
        idToSlotBegin[newId] = RESOURCE_SLOT_CAPTURE_BEGIN;

        if (!dstRes.tag.empty()) {
            tagIndex.insert({dstRes.tag, newId});
        }

        return newId;
    }
    
    return 0;
}

bool GPUResourcePool::CopyCrossGPU(void* src, int srcGPUIndex,
                                   void* dst, int dstGPUIndex, GPUResourceType type) {
    if (type != GPUResourceType::Texture2D) {
        return false;  // 目前只支持Texture2D
    }
    
    if (!m_devMgr) return false;
    auto& deviceMgr = *m_devMgr;
    const auto& gpuDevices = deviceMgr.GetGPUDevices();
    
    if (srcGPUIndex < 0 || srcGPUIndex >= (int)gpuDevices.size()) return false;
    if (dstGPUIndex < 0 || dstGPUIndex >= (int)gpuDevices.size()) return false;
    
    const auto& srcGPU = gpuDevices[srcGPUIndex];
    const auto& dstGPU = gpuDevices[dstGPUIndex];
    
    ID3D11Texture2D* srcTex = static_cast<ID3D11Texture2D*>(src);
    ID3D11Texture2D* dstTex = static_cast<ID3D11Texture2D*>(dst);
    
    D3D11_TEXTURE2D_DESC desc;
    srcTex->GetDesc(&desc);
    
    // 创建staging纹理（在源GPU上）
    desc.Usage = D3D11_USAGE_STAGING;
    desc.BindFlags = 0;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    
    ID3D11Texture2D* staging = nullptr;
    HRESULT hr = srcGPU.device->CreateTexture2D(&desc, nullptr, &staging);
    if (FAILED(hr)) return false;
    
    // 拷贝到staging
    srcGPU.context->CopyResource(staging, srcTex);
    
    // 映射读取
    D3D11_MAPPED_SUBRESOURCE mapped;
    hr = srcGPU.context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) {
        staging->Release();
        return false;
    }
    
    // 更新目标纹理
    dstGPU.context->UpdateSubresource(dstTex, 0, nullptr, mapped.pData, mapped.RowPitch, 0);
    
    srcGPU.context->Unmap(staging, 0);
    staging->Release();
    
    return true;
}

// ============================================================
//  拷贝到CPU
// ============================================================

bool GPUResourcePool::CopyToCPU(UINT64 resourceId, unsigned char* buffer) {
    if (!buffer) {
        return false;
    }
    
    auto* res = GetResource(resourceId);
    if (!res || res->type != GPUResourceType::Texture2D) {
        return false;
    }
    

    // 🔥 优先使用资源自己的Device和Context（用于Desktop Duplication资源）
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;
    
    if (res->device && res->context) {
        // 使用资源自己的Device和Context
        device = static_cast<ID3D11Device*>(res->device);
        context = static_cast<ID3D11DeviceContext*>(res->context);
    } else {
        // 回退到GPU索引查找
        if (!m_devMgr) return false;
        auto& deviceMgr = *m_devMgr;
        int gpuIndex = res->ownerGPUIndex;
        
        if (gpuIndex < 0 || gpuIndex >= deviceMgr.GetGPUCount()) {
            return false;
        }
        
        const auto& gpuDevices = deviceMgr.GetGPUDevices();
        const auto& gpu = gpuDevices[gpuIndex];
        device = gpu.device;
        context = gpu.context;
    }
    
    if (!device || !context) {
        return false;
    }
    
    ID3D11Texture2D* srcTex = static_cast<ID3D11Texture2D*>(res->resource);
    
    // 创建staging纹理
    D3D11_TEXTURE2D_DESC desc;
    srcTex->GetDesc(&desc);

    // 重置所有标志以创建staging纹理
    desc.Usage = D3D11_USAGE_STAGING;
    desc.BindFlags = 0;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    desc.MiscFlags = 0;  // 清除MiscFlags（重要！）
    
    ID3D11Texture2D* staging = nullptr;
    HRESULT hr = device->CreateTexture2D(&desc, nullptr, &staging);
    if (FAILED(hr)) {
        return false;
    }
    

    // 🔥 使用正确的Context进行拷贝
    context->CopyResource(staging, srcTex);

    // 映射读取
    D3D11_MAPPED_SUBRESOURCE mapped;
    hr = context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) {
        staging->Release();
        return false;
    }
    

    // 拷贝数据
    unsigned char* src = static_cast<unsigned char*>(mapped.pData);
    for (int y = 0; y < res->height; ++y) {
        memcpy(buffer + y * res->width * 4, 
               src + y * mapped.RowPitch, 
               res->width * 4);
    }
    
    context->Unmap(staging, 0);
    staging->Release();

    return true;
}