/*
 * 文件名: gpu_resource_pool.h
 * 功能: GPU通用资源缓存池 - 资源管理、跨GPU拷贝
 */

#pragma once

#include "gpu_types.h"
#include <set>

// 前向声明，避免循环包含
class GPUDeviceManager;

// ============================================================
//  资源 ID 分段定义
//  每段容量 1000，超出时循环复用空闲槽
// ============================================================

enum class ResourceSlot : UINT64 {
    Capture_Begin = 1,
    Capture_End   = 999,
    SDF_Begin     = 1000,
    SDF_End       = 1999,
    Effect_Begin  = 2000,
    Effect_End    = 2999,
};

// ============================================================
//  GPU 资源池管理器
// ============================================================

class GPUMGR_API GPUResourcePool {
public:
    GPUResourcePool() = default;
    ~GPUResourcePool();

    // 禁止拷贝
    GPUResourcePool(const GPUResourcePool&) = delete;
    GPUResourcePool& operator=(const GPUResourcePool&) = delete;

    // 设置依赖（必须在 AddResource/CreateResource 之前调用）
    void SetDeviceManager(GPUDeviceManager* mgr) { m_devMgr = mgr; }

    // ========== 添加资源 ==========

    // slotBegin/slotEnd 指定 ID 范围，默认放入 Capture 段
    UINT64 AddResource(void* resource, GPUResourceType type, void* srv,
                       int ownerGPU, const char* tag = nullptr,
                       UINT64 slotBegin = (UINT64)ResourceSlot::Capture_Begin,
                       UINT64 slotEnd   = (UINT64)ResourceSlot::Capture_End);

    UINT64 CreateResource(const GPUResourceDesc& desc, int gpuIndex,
                          const void* initialData = nullptr,
                          UINT64 slotBegin = (UINT64)ResourceSlot::Capture_Begin,
                          UINT64 slotEnd   = (UINT64)ResourceSlot::Capture_End);

    // ========== 查询资源 ==========

    CachedGPUResource* GetResource(UINT64 resourceId);

    std::vector<UINT64> FindResourcesByTag(const char* tag);

    bool GetResourceInfo(UINT64 resourceId, void** outResource, void** outSRV,
                         GPUResourceType* outType, int* outWidth, int* outHeight);

    // ========== 管理资源 ==========

    // ID 保持不变，旧纹理/SRV 的引用计数会被 Release。
    bool UpdateResource(UINT64 resourceId, void* newResource, void* newSRV,
                        const char* newTag = nullptr);

    void RemoveResource(UINT64 resourceId);

    void ClearPool();

    PoolStats GetStats() const;

    // ========== 跨GPU操作 ==========

    UINT64 CopyToGPU(UINT64 srcResourceId, int dstGPUIndex);

    bool CopyCPU(UINT64 resourceId, unsigned char* buffer);
    bool CopyToCPU(UINT64 resourceId, unsigned char* buffer); // 兼容旧名

private:
    bool CreateTexture2D(const GPUResourceDesc& desc, int gpuIndex,
                         const void* initialData, CachedGPUResource& outResource);

    bool CreateBuffer(const GPUResourceDesc& desc, int gpuIndex,
                      const void* initialData, CachedGPUResource& outResource);

    bool CopyCrossGPU(void* src, int srcGPUIndex,
                      void* dst, int dstGPUIndex, GPUResourceType type);

    // 从指定段分配一个空闲 ID（优先复用已释放的槽）
    UINT64 AllocId(UINT64 slotBegin, UINT64 slotEnd);

    // 释放 ID 回空闲池
    void FreeId(UINT64 id);

    std::map<UINT64, CachedGPUResource> resourcePool;
    std::multimap<std::string, UINT64>  tagIndex;

    // 每个段：下一个未用过的 ID，以及已回收的空闲槽
    struct SlotState {
        UINT64       next  = 0;   // 相对于段起始的偏移，下一个未分配过的值
        std::set<UINT64> free;    // 已回收的绝对 ID
    };
    // key = slotBegin，value = 该段状态
    std::map<UINT64, SlotState> slotStates;
    // 用于 FreeId 时反查所属段
    // key = 绝对 ID，value = 该段的 slotBegin
    std::map<UINT64, UINT64> idToSlotBegin;
    // 记录每个段的 slotEnd
    std::map<UINT64, UINT64> slotEndMap;

    // 依赖注入
    GPUDeviceManager* m_devMgr = nullptr;
};