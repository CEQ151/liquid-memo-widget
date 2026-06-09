/*
 * 文件名: gpu_manager_api.h
 * 功能: GPU管理器统一C API导出（多实例版本）
 *
 * 用法:
 *   void* ctx = GPUMgr_Create();
 *   GPUMgr_Initialize(ctx, 0);
 *   ...
 *   GPUMgr_Destroy(ctx);
 */

#pragma once

#include "gpu_types.h"

extern "C" {

    // ========== 上下文生命周期 ==========

    // 创建新的 GPUContext 实例，返回不透明句柄
    GPUMGR_API void* __stdcall GPUMgr_Create();
    // 销毁 GPUContext 实例（会自动 Shutdown 所有子系统）
    GPUMGR_API void  __stdcall GPUMgr_Destroy(void* handle);

    // ========== 设备管理 ==========
    
    GPUMGR_API int __stdcall GPUMgr_Initialize(void* handle, int preference);
    GPUMGR_API void __stdcall GPUMgr_Shutdown(void* handle);
    GPUMGR_API int __stdcall GPUMgr_IsInitialized(void* handle);
    
    GPUMGR_API int __stdcall GPUMgr_GetGPUCount(void* handle);
    GPUMGR_API int __stdcall GPUMgr_GetGPUInfo(void* handle, int index, char* nameBuffer, int bufferSize,
                                                size_t* memory, int* vendorId, int* role,
                                                int* monitorCount);
    
    GPUMGR_API int __stdcall GPUMgr_GetMonitorCount(void* handle);
    GPUMGR_API int __stdcall GPUMgr_GetMonitorInfo(void* handle, int index, int* left, int* top,
                                                    int* right, int* bottom, int* gpuIndex);
    
    GPUMGR_API void* __stdcall GPUMgr_GetMainDevice(void* handle);
    GPUMGR_API void* __stdcall GPUMgr_GetMainContext(void* handle);
    GPUMGR_API void* __stdcall GPUMgr_GetDeviceByGPUIndex(void* handle, int gpuIndex);
    GPUMGR_API void* __stdcall GPUMgr_GetContextByGPUIndex(void* handle, int gpuIndex);
    GPUMGR_API void* __stdcall GPUMgr_GetDeviceByMonitor(void* handle, int monitorIndex);
    
    GPUMGR_API const char* __stdcall GPUMgr_GetDebugInfo(void* handle);
    
    // ========== 资源池管理 ==========
    
    GPUMGR_API UINT64 __stdcall GPUMgr_AddResourceToPool(void* handle, void* resource, int type, 
                                                          void* srv, int ownerGPU, const char* tag);
    
    GPUMGR_API UINT64 __stdcall GPUMgr_CreateResourceInPool(void* handle, int type, int width, int height,
                                                             int format, int bindFlags, 
                                                             int usage, int gpuIndex, 
                                                             const char* tag);
    
    GPUMGR_API int __stdcall GPUMgr_GetResourceFromPool(void* handle, UINT64 resourceId, void** outResource,
                                                        void** outSRV, int* type, 
                                                        int* width, int* height, int* ownerGPU);
    
    GPUMGR_API void __stdcall GPUMgr_RemoveResourceFromPool(void* handle, UINT64 resourceId);
    
    GPUMGR_API void __stdcall GPUMgr_ClearResourcePool(void* handle);
    
    GPUMGR_API UINT64 __stdcall GPUMgr_CopyResourceToGPU(void* handle, UINT64 srcResourceId, int dstGPUIndex);
    
    GPUMGR_API int __stdcall GPUMgr_CopyResourceToCPU(void* handle, UINT64 resourceId, unsigned char* buffer);
    
    GPUMGR_API int __stdcall GPUMgr_GetResourceDataSize(void* handle, UINT64 resourceId, int* width, int* height, int* stride);
    
    GPUMGR_API int __stdcall GPUMgr_GetPoolStats(void* handle, int* totalResources, size_t* totalMemory);
    
    GPUMGR_API int __stdcall GPUMgr_UpdateResourceInPool(void* handle, UINT64 resourceId,
                                                         void* newResource, void* newSRV,
                                                         const char* newTag);

    GPUMGR_API UINT64 __stdcall GPUMgr_AddResourceToPoolInSlot(void* handle, void* resource, int type,
                                                                void* srv, int ownerGPU,
                                                                const char* tag,
                                                                UINT64 slotBegin,
                                                                UINT64 slotEnd);
                                                                
    // ========== D3D11/OpenGL 互操作函数 ==========

    GPUMGR_API int __stdcall GPUMgr_InitializeGLInterop(void* handle);
    GPUMGR_API int __stdcall GPUMgr_IsGLInteropSupported(void* handle);
    GPUMGR_API void __stdcall GPUMgr_ShutdownGLInterop(void* handle);
    GPUMGR_API void* __stdcall GPUMgr_CreateGLTextureFromD3D(void* handle, UINT64 resourceId);
    GPUMGR_API int __stdcall GPUMgr_LockGLTexture(void* handle, void* glTextureHandle);
    GPUMGR_API int __stdcall GPUMgr_UnlockGLTexture(void* handle, void* glTextureHandle);
    GPUMGR_API int __stdcall GPUMgr_ReleaseGLTexture(void* handle, void* glTextureHandle);
    GPUMGR_API unsigned int __stdcall GPUMgr_GetGLTextureID(void* handle, void* glTextureHandle);

    // ========== Desktop Duplication 显示器捕获 ==========
    
    GPUMGR_API int __stdcall GPUMgr_InitializeDisplayCapture(void* handle);
    GPUMGR_API void __stdcall GPUMgr_ShutdownDisplayCapture(void* handle);
    GPUMGR_API int __stdcall GPUMgr_GetDisplayCount(void* handle);
    GPUMGR_API int __stdcall GPUMgr_GetDisplayBounds(void* handle, int displayIndex, int* left, int* top,
                                                      int* right, int* bottom);
    GPUMGR_API int __stdcall GPUMgr_GetDisplayGPUIndex(void* handle, int displayIndex);
    GPUMGR_API void* __stdcall GPUMgr_GetDisplayTexture(void* handle, int displayIndex);
    GPUMGR_API UINT64 __stdcall GPUMgr_CaptureDisplayRegion(void* handle, int displayIndex, int x, int y, 
                                                            int width, int height, const char* tag);
    GPUMGR_API void __stdcall GPUMgr_ReleaseDisplayFrame(void* handle, int displayIndex);
    GPUMGR_API void* __stdcall GPUMgr_GetDisplayDevice(void* handle, int displayIndex);
    GPUMGR_API void* __stdcall GPUMgr_GetDisplayContext(void* handle, int displayIndex);

    // ========== 资源池纹理访问 ==========

    GPUMGR_API void* __stdcall GPUMgr_GetResourceTexture(void* handle, UINT64 resourceId);
    GPUMGR_API void* __stdcall GPUMgr_GetResourceSRV(void* handle, UINT64 resourceId);
    GPUMGR_API void* __stdcall GPUMgr_GetResourceRTV(void* handle, UINT64 resourceId);
    GPUMGR_API void* __stdcall GPUMgr_GetResourceUAV(void* handle, UINT64 resourceId);
    
    // ========== DXGI SwapChain Presenter ==========
    GPUMGR_API UINT64 __stdcall GPUMgr_CreatePresenter(void* handle, void* hwnd, int width, int height, int gpuIndex);
    GPUMGR_API void   __stdcall GPUMgr_DestroyPresenter(void* handle, UINT64 presenterId);
    GPUMGR_API int    __stdcall GPUMgr_PresentResource(void* handle, UINT64 presenterId, UINT64 resourceId, int syncInterval);
    GPUMGR_API int    __stdcall GPUMgr_ResizePresenter(void* handle, UINT64 presenterId, int width, int height);

    // ========== 内部子系统访问（供同进程内其他模块使用） ==========
    // 返回 GPUContext 内部的 GPUResourcePool 指针，供特效渲染器等模块获取
    GPUMGR_API void* __stdcall GPUMgr_GetResourcePoolPtr(void* handle);

} // extern "C"