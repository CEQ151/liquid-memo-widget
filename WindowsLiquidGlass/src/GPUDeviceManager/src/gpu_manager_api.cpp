/*
 * 文件名: gpu_manager_api.cpp
 * 功能: GPU管理器统一C API导出实现（多实例版本）
 *
 * 每个 GPUMgr_Create() 创建独立的 GPUContext，
 * 内含独立的 DeviceManager / ResourcePool / GLInterop /
 * DisplayCapture / SwapChainPresenter，互不干扰。
 */

#include "gpu_manager_api.h"
#include "gpu_device_manager.h"
#include "gpu_resource_pool.h"
#include "gpu_display_capture.h"
#include "gpu_gl_interop.h"
#include "gpu_swapchain_presenter.h"
#include <cstring>
#include <string>

// ============================================================
//  GPUContext — 每条"线路"独立持有的全套 GPU 子系统
// ============================================================

struct GPUContext {
    GPUDeviceManager*               deviceManager     = nullptr;
    GPUResourcePool*                resourcePool      = nullptr;
    GPUGLInterop*                   glInterop         = nullptr;
    GPUDisplayCapture*              displayCapture    = nullptr;  // 指向共享单例
    GPUSwapChainPresenterManager*   presenterManager  = nullptr;

    // 本实例持有的追踪帧资源（key=tag, value=resourceId in this context's pool）
    std::unordered_map<std::string, UINT64> persistentCaptureResources;

    // 用于返回调试字符串的缓冲区
    std::string debugInfoBuf;

    GPUContext() {
        deviceManager    = new GPUDeviceManager();
        resourcePool     = new GPUResourcePool();
        glInterop        = new GPUGLInterop();
        presenterManager = new GPUSwapChainPresenterManager();

        // 注入依赖
        resourcePool->SetDeviceManager(deviceManager);
        glInterop->SetResourcePool(resourcePool);
        presenterManager->SetDeviceManager(deviceManager);
        presenterManager->SetResourcePool(resourcePool);

        // 获取共享的进程级 DXGI 单例（首个 context 创建，后续的只增引用计数）
        displayCapture = GPUDisplayCapture::AcquireShared(deviceManager);
    }

    ~GPUContext() {
        // 按依赖顺序逆序销毁
        delete presenterManager;  presenterManager = nullptr;

        // 清理本实例在共享捕获中注册的资源
        for (auto& pair : persistentCaptureResources) {
            if (resourcePool) resourcePool->RemoveResource(pair.second);
        }
        persistentCaptureResources.clear();

        // 释放对共享单例的引用（若已被 ShutdownDisplayCapture 释放则跳过）
        if (displayCapture) {
            GPUDisplayCapture::ReleaseShared();
            displayCapture = nullptr;
        }

        delete glInterop;         glInterop        = nullptr;
        // ResourcePool 在 DeviceManager 之前清理（内部可能访问 device）
        if (resourcePool) { resourcePool->ClearPool(); delete resourcePool; resourcePool = nullptr; }
        if (deviceManager) { deviceManager->Shutdown(); delete deviceManager; deviceManager = nullptr; }
    }

    // 辅助：安全解引用
    GPUContext(const GPUContext&) = delete;
    GPUContext& operator=(const GPUContext&) = delete;
};

static inline GPUContext* CTX(void* h) { return static_cast<GPUContext*>(h); }

// 字符串转换辅助函数
static std::string WStringToString(const std::wstring& wstr) {
    if (wstr.empty()) return std::string();
    int size_needed = WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), NULL, 0, NULL, NULL);
    std::string strTo(size_needed, 0);
    WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), &strTo[0], size_needed, NULL, NULL);
    return strTo;
}

// ============================================================
//  上下文生命周期
// ============================================================

extern "C" {

GPUMGR_API void* __stdcall GPUMgr_Create() {
    return new GPUContext();
}

GPUMGR_API void __stdcall GPUMgr_Destroy(void* handle) {
    delete CTX(handle);
}

GPUMGR_API void* __stdcall GPUMgr_GetResourcePoolPtr(void* handle) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->resourcePool : nullptr;
}

// ============================================================
//  设备管理 API
// ============================================================

GPUMGR_API int __stdcall GPUMgr_Initialize(void* handle, int preference) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    return ctx->deviceManager->Initialize(static_cast<GPUPreference>(preference)) ? 1 : 0;
}

GPUMGR_API void __stdcall GPUMgr_Shutdown(void* handle) {
    auto* ctx = CTX(handle);
    if (!ctx) return;
    ctx->resourcePool->ClearPool();
    ctx->deviceManager->Shutdown();
}

GPUMGR_API int __stdcall GPUMgr_IsInitialized(void* handle) {
    auto* ctx = CTX(handle);
    return ctx ? (ctx->deviceManager->IsInitialized() ? 1 : 0) : 0;
}

GPUMGR_API int __stdcall GPUMgr_GetGPUCount(void* handle) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->deviceManager->GetGPUCount() : 0;
}

GPUMGR_API int __stdcall GPUMgr_GetGPUInfo(void* handle, int index, char* nameBuffer, int bufferSize,
                                            size_t* memory, int* vendorId, int* role,
                                            int* monitorCount) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    auto info = ctx->deviceManager->GetGPUByIndex(index);
    if (info.name.empty()) return 0;
    
    std::string name = WStringToString(info.name);
    if (nameBuffer && bufferSize > 0) {
        strncpy_s(nameBuffer, bufferSize, name.c_str(), _TRUNCATE);
    }
    if (memory)       *memory       = info.dedicatedVideoMemory;
    if (vendorId)     *vendorId     = info.vendorId;
    if (role)         *role         = static_cast<int>(info.role);
    if (monitorCount) *monitorCount = static_cast<int>(info.connectedMonitors.size());
    return 1;
}

GPUMGR_API int __stdcall GPUMgr_GetMonitorCount(void* handle) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->deviceManager->GetMonitorCount() : 0;
}

GPUMGR_API int __stdcall GPUMgr_GetMonitorInfo(void* handle, int index, int* left, int* top,
                                                int* right, int* bottom, int* gpuIndex) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    auto info = ctx->deviceManager->GetMonitorByIndex(index);
    if (info.index < 0) return 0;
    if (left)     *left     = info.bounds.left;
    if (top)      *top      = info.bounds.top;
    if (right)    *right    = info.bounds.right;
    if (bottom)   *bottom   = info.bounds.bottom;
    if (gpuIndex) *gpuIndex = info.gpuIndex;
    return 1;
}

GPUMGR_API void* __stdcall GPUMgr_GetMainDevice(void* handle) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->deviceManager->GetMainDevice() : nullptr;
}

GPUMGR_API void* __stdcall GPUMgr_GetMainContext(void* handle) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->deviceManager->GetMainContext() : nullptr;
}

GPUMGR_API void* __stdcall GPUMgr_GetDeviceByGPUIndex(void* handle, int gpuIndex) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->deviceManager->GetDeviceByGPUIndex(gpuIndex) : nullptr;
}

GPUMGR_API void* __stdcall GPUMgr_GetContextByGPUIndex(void* handle, int gpuIndex) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->deviceManager->GetContextByGPUIndex(gpuIndex) : nullptr;
}

GPUMGR_API void* __stdcall GPUMgr_GetDeviceByMonitor(void* handle, int monitorIndex) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->deviceManager->GetDeviceByMonitor(monitorIndex) : nullptr;
}

GPUMGR_API const char* __stdcall GPUMgr_GetDebugInfo(void* handle) {
    auto* ctx = CTX(handle);
    if (!ctx) return "";
    ctx->debugInfoBuf = ctx->deviceManager->GetDebugInfo();
    
    auto stats = ctx->resourcePool->GetStats();
    ctx->debugInfoBuf += "\n=== Resource Pool ===\n";
    ctx->debugInfoBuf += "Total Resources: " + std::to_string(stats.totalResources) + "\n";
    ctx->debugInfoBuf += "Total Memory: " + std::to_string(stats.totalMemoryBytes / (1024*1024)) + " MB\n";
    return ctx->debugInfoBuf.c_str();
}

// ============================================================
//  资源池管理 API
// ============================================================

GPUMGR_API UINT64 __stdcall GPUMgr_AddResourceToPool(void* handle, void* resource, int type, 
                                                      void* srv, int ownerGPU, const char* tag) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->resourcePool->AddResource(resource, static_cast<GPUResourceType>(type), srv, ownerGPU, tag) : 0;
}

GPUMGR_API UINT64 __stdcall GPUMgr_CreateResourceInPool(void* handle, int type, int width, int height,
                                                         int format, int bindFlags, 
                                                         int usage, int gpuIndex, 
                                                         const char* tag) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    GPUResourceDesc desc;
    desc.type      = static_cast<GPUResourceType>(type);
    desc.width     = width;
    desc.height    = height;
    desc.format    = static_cast<DXGI_FORMAT>(format);
    desc.bindFlags = bindFlags;
    desc.usage     = static_cast<D3D11_USAGE>(usage);
    if (tag) desc.tag = tag;
    return ctx->resourcePool->CreateResource(desc, gpuIndex, nullptr);
}

GPUMGR_API int __stdcall GPUMgr_GetResourceFromPool(void* handle, UINT64 resourceId, void** outResource,
                                                    void** outSRV, int* type, 
                                                    int* width, int* height, int* ownerGPU) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    GPUResourceType resType;
    bool result = ctx->resourcePool->GetResourceInfo(resourceId, outResource, outSRV, &resType, width, height);
    if (result && type)     *type = static_cast<int>(resType);
    if (result && ownerGPU) {
        auto* res = ctx->resourcePool->GetResource(resourceId);
        if (res) *ownerGPU = res->ownerGPUIndex;
    }
    return result ? 1 : 0;
}
                                                                
GPUMGR_API void __stdcall GPUMgr_RemoveResourceFromPool(void* handle, UINT64 resourceId) {
    auto* ctx = CTX(handle);
    if (ctx) ctx->resourcePool->RemoveResource(resourceId);
}

GPUMGR_API int __stdcall GPUMgr_UpdateResourceInPool(void* handle, UINT64 resourceId,
                                                      void* newResource, void* newSRV,
                                                      const char* newTag) {
    auto* ctx = CTX(handle);
    return ctx ? (ctx->resourcePool->UpdateResource(resourceId, newResource, newSRV, newTag) ? 1 : 0) : 0;
}

GPUMGR_API UINT64 __stdcall GPUMgr_AddResourceToPoolInSlot(void* handle, void* resource, int type,
                                                             void* srv, int ownerGPU,
                                                             const char* tag,
                                                             UINT64 slotBegin,
                                                             UINT64 slotEnd) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->resourcePool->AddResource(resource, static_cast<GPUResourceType>(type), srv, ownerGPU, tag, slotBegin, slotEnd) : 0;
}

GPUMGR_API void __stdcall GPUMgr_ClearResourcePool(void* handle) {
    auto* ctx = CTX(handle);
    if (ctx) ctx->resourcePool->ClearPool();
}

GPUMGR_API UINT64 __stdcall GPUMgr_CopyResourceToGPU(void* handle, UINT64 srcResourceId, int dstGPUIndex) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->resourcePool->CopyToGPU(srcResourceId, dstGPUIndex) : 0;
}

GPUMGR_API int __stdcall GPUMgr_CopyResourceToCPU(void* handle, UINT64 resourceId, unsigned char* buffer) {
    auto* ctx = CTX(handle);
    return ctx ? (ctx->resourcePool->CopyToCPU(resourceId, buffer) ? 1 : 0) : 0;
}

GPUMGR_API int __stdcall GPUMgr_GetResourceDataSize(void* handle, UINT64 resourceId, int* width, int* height, int* stride) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    auto* res = ctx->resourcePool->GetResource(resourceId);
    if (!res || res->type != GPUResourceType::Texture2D) return 0;
    if (width)  *width  = res->width;
    if (height) *height = res->height;
    if (stride) *stride = res->width * 4;
    return 1;
}

GPUMGR_API int __stdcall GPUMgr_GetPoolStats(void* handle, int* totalResources, size_t* totalMemory) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    auto stats = ctx->resourcePool->GetStats();
    if (totalResources) *totalResources = stats.totalResources;
    if (totalMemory)    *totalMemory    = stats.totalMemoryBytes;
    return 1;
}

// ========== Desktop Duplication 显示器捕获 ==========

GPUMGR_API int __stdcall GPUMgr_InitializeDisplayCapture(void* handle) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    // 若已被 ShutdownDisplayCapture 释放，重新获取共享实例
    if (!ctx->displayCapture) {
        ctx->displayCapture = GPUDisplayCapture::AcquireShared(ctx->deviceManager);
    }
    return ctx->displayCapture->Initialize() ? 1 : 0;
}

GPUMGR_API void __stdcall GPUMgr_ShutdownDisplayCapture(void* handle) {
    auto* ctx = CTX(handle);
    if (!ctx || !ctx->displayCapture) return;
    // 清理本 context 在共享捕获中注册的持久资源
    for (auto& pair : ctx->persistentCaptureResources) {
        ctx->resourcePool->RemoveResource(pair.second);
    }
    ctx->persistentCaptureResources.clear();
    // 释放共享单例引用；最后一个释放时会调用 Shutdown + delete
    GPUDisplayCapture::ReleaseShared();
    ctx->displayCapture = nullptr;
}

GPUMGR_API int __stdcall GPUMgr_GetDisplayCount(void* handle) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->displayCapture->GetDisplayCount() : 0;
}

GPUMGR_API int __stdcall GPUMgr_GetDisplayBounds(void* handle, int displayIndex, int* left, int* top,
                                                  int* right, int* bottom) {
    auto* ctx = CTX(handle);
    return ctx ? (ctx->displayCapture->GetDisplayBounds(displayIndex, left, top, right, bottom) ? 1 : 0) : 0;
}

GPUMGR_API int __stdcall GPUMgr_GetDisplayGPUIndex(void* handle, int displayIndex) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->displayCapture->GetDisplayGPUIndex(displayIndex) : -1;
}

GPUMGR_API void* __stdcall GPUMgr_GetDisplayTexture(void* handle, int displayIndex) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->displayCapture->GetDisplayTexture(displayIndex) : nullptr;
}

GPUMGR_API UINT64 __stdcall GPUMgr_CaptureDisplayRegion(void* handle, int displayIndex, int x, int y, 
                                                         int width, int height, const char* tag) {
    auto* ctx = CTX(handle);
    if (!ctx || !ctx->displayCapture) return 0;
    return ctx->displayCapture->CaptureDisplayRegion(
        displayIndex, x, y, width, height,
        ctx->deviceManager->GetMainDevice(),
        ctx->deviceManager->GetMainContext(),
        ctx->resourcePool,
        ctx->persistentCaptureResources,
        ctx->deviceManager->GetMainGPUIndex(),
        tag
    );
}

GPUMGR_API void __stdcall GPUMgr_ReleaseDisplayFrame(void* handle, int displayIndex) {
    auto* ctx = CTX(handle);
    if (ctx) ctx->displayCapture->ReleaseCurrentFrame(displayIndex);
}

GPUMGR_API void* __stdcall GPUMgr_GetDisplayDevice(void* handle, int displayIndex) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->displayCapture->GetDisplayDevice(displayIndex) : nullptr;
}

GPUMGR_API void* __stdcall GPUMgr_GetDisplayContext(void* handle, int displayIndex) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->displayCapture->GetDisplayContext(displayIndex) : nullptr;
}

// ========== 资源池纹理访问 API ==========

GPUMGR_API void* __stdcall GPUMgr_GetResourceTexture(void* handle, UINT64 resourceId) {
    auto* ctx = CTX(handle);
    if (!ctx) return nullptr;
    auto* res = ctx->resourcePool->GetResource(resourceId);
    return res ? res->resource : nullptr;
}

GPUMGR_API void* __stdcall GPUMgr_GetResourceSRV(void* handle, UINT64 resourceId) {
    auto* ctx = CTX(handle);
    if (!ctx) return nullptr;
    auto* res = ctx->resourcePool->GetResource(resourceId);
    return res ? res->srv : nullptr;
}

GPUMGR_API void* __stdcall GPUMgr_GetResourceRTV(void* handle, UINT64 resourceId) {
    auto* ctx = CTX(handle);
    if (!ctx) return nullptr;
    auto* res = ctx->resourcePool->GetResource(resourceId);
    return res ? res->rtv : nullptr;
}

GPUMGR_API void* __stdcall GPUMgr_GetResourceUAV(void* handle, UINT64 resourceId) {
    auto* ctx = CTX(handle);
    if (!ctx) return nullptr;
    auto* res = ctx->resourcePool->GetResource(resourceId);
    return res ? res->uav : nullptr;
}

// ========== D3D11/OpenGL 互操作函数 ==========

GPUMGR_API int __stdcall GPUMgr_InitializeGLInterop(void* handle) {
    auto* ctx = CTX(handle);
    return ctx ? (ctx->glInterop->Initialize() ? 1 : 0) : 0;
}

GPUMGR_API int __stdcall GPUMgr_IsGLInteropSupported(void* handle) {
    auto* ctx = CTX(handle);
    return ctx ? (ctx->glInterop->IsSupported() ? 1 : 0) : 0;
}

GPUMGR_API void __stdcall GPUMgr_ShutdownGLInterop(void* handle) {
    auto* ctx = CTX(handle);
    if (ctx) ctx->glInterop->Shutdown();
}

GPUMGR_API void* __stdcall GPUMgr_CreateGLTextureFromD3D(void* handle, UINT64 resourceId) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->glInterop->CreateGLTextureFromD3D(resourceId) : nullptr;
}

GPUMGR_API int __stdcall GPUMgr_LockGLTexture(void* handle, void* glTextureHandle) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    auto* h = static_cast<GLInteropHandle*>(glTextureHandle);
    return ctx->glInterop->LockTexture(h) ? 1 : 0;
}

GPUMGR_API int __stdcall GPUMgr_UnlockGLTexture(void* handle, void* glTextureHandle) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    auto* h = static_cast<GLInteropHandle*>(glTextureHandle);
    return ctx->glInterop->UnlockTexture(h) ? 1 : 0;
}

GPUMGR_API int __stdcall GPUMgr_ReleaseGLTexture(void* handle, void* glTextureHandle) {
    auto* ctx = CTX(handle);
    if (!ctx) return 0;
    auto* h = static_cast<GLInteropHandle*>(glTextureHandle);
    return ctx->glInterop->ReleaseGLTexture(h) ? 1 : 0;
}

GPUMGR_API unsigned int __stdcall GPUMgr_GetGLTextureID(void* handle, void* glTextureHandle) {
    auto* h = static_cast<GLInteropHandle*>(glTextureHandle);
    return h ? h->glTexture : 0;
}

// ========== SwapChain Presenter API ==========

GPUMGR_API UINT64 __stdcall GPUMgr_CreatePresenter(void* handle, void* hwnd, int width, int height, int gpuIndex) {
    auto* ctx = CTX(handle);
    return ctx ? ctx->presenterManager->CreatePresenter((HWND)hwnd, (UINT)width, (UINT)height, gpuIndex) : 0;
}

GPUMGR_API void __stdcall GPUMgr_DestroyPresenter(void* handle, UINT64 presenterId) {
    auto* ctx = CTX(handle);
    if (ctx) ctx->presenterManager->DestroyPresenter(presenterId);
}

GPUMGR_API int __stdcall GPUMgr_PresentResource(void* handle, UINT64 presenterId, UINT64 resourceId, int syncInterval) {
    auto* ctx = CTX(handle);
    return ctx ? (ctx->presenterManager->PresentResource(presenterId, resourceId, syncInterval) ? 1 : 0) : 0;
}

GPUMGR_API int __stdcall GPUMgr_ResizePresenter(void* handle, UINT64 presenterId, int width, int height) {
    auto* ctx = CTX(handle);
    return ctx ? (ctx->presenterManager->ResizePresenter(presenterId, (UINT)width, (UINT)height) ? 1 : 0) : 0;
}

} // extern "C"
