/*
 * 文件名: gpu_gl_interop.cpp
 * 功能: D3D11/OpenGL 互操作实现
 */

#include "gpu_gl_interop.h"
#include "gpu_resource_pool.h"
#include <string>
// WGL 扩展名
#define WGL_ACCESS_READ_ONLY_NV           0x0000
#define WGL_ACCESS_READ_WRITE_NV          0x0001
#define WGL_ACCESS_WRITE_DISCARD_NV       0x0002

GPUGLInterop::~GPUGLInterop() {
    Shutdown();
}

bool GPUGLInterop::LoadWGLExtensions() {
    HMODULE opengl32 = GetModuleHandleA("opengl32.dll");
    if (!opengl32) {
        return false;
    }
    
    // 获取 wglGetProcAddress
    typedef void* (WINAPI *PFNWGLGETPROCADDRESSPROC)(const char*);
    auto wglGetProcAddress = (PFNWGLGETPROCADDRESSPROC)GetProcAddress(opengl32, "wglGetProcAddress");
    if (!wglGetProcAddress) {
        return false;
    }
    
    // 加载 WGL_NV_DX_interop 扩展函数
    wglDXOpenDeviceNV = (PFNWGLDXOPENDEVICENVPROC)wglGetProcAddress("wglDXOpenDeviceNV");
    wglDXCloseDeviceNV = (PFNWGLDXCLOSEDEVICENVPROC)wglGetProcAddress("wglDXCloseDeviceNV");
    wglDXRegisterObjectNV = (PFNWGLDXREGISTEROBJECTNVPROC)wglGetProcAddress("wglDXRegisterObjectNV");
    wglDXUnregisterObjectNV = (PFNWGLDXUNREGISTEROBJECTNVPROC)wglGetProcAddress("wglDXUnregisterObjectNV");
    wglDXLockObjectsNV = (PFNWGLDXLOCKOBJECTSNVPROC)wglGetProcAddress("wglDXLockObjectsNV");
    wglDXUnlockObjectsNV = (PFNWGLDXUNLOCKOBJECTSNVPROC)wglGetProcAddress("wglDXUnlockObjectsNV");
    wglDXSetResourceShareHandleNV = (PFNWGLDXSETRESOURCESHAREHANDLENVPROC)wglGetProcAddress("wglDXSetResourceShareHandleNV");
    
    // 检查是否所有函数都加载成功
    if (!wglDXOpenDeviceNV || !wglDXCloseDeviceNV || 
        !wglDXRegisterObjectNV || !wglDXUnregisterObjectNV ||
        !wglDXLockObjectsNV || !wglDXUnlockObjectsNV) {
        return false;
    }
    
    return true;
}

bool GPUGLInterop::Initialize() {
    if (isInitialized) {
        return true;
    }
    
    // 加载 WGL 扩展
    if (!LoadWGLExtensions()) {
        isSupported = false;
        return false;
    }
    
    isSupported = true;
    isInitialized = true;
    
    return true;
}

void GPUGLInterop::Shutdown() {
    if (!isInitialized) {
        return;
    }
    
    // 释放所有互操作句柄
    for (auto& pair : interopHandles) {
        ReleaseGLTexture(pair.second);
    }
    interopHandles.clear();
    glTextureMap.clear();
    
    // 关闭所有注册的设备
    for (auto& pair : registeredDevices) {
        if (pair.second && wglDXCloseDeviceNV) {
            wglDXCloseDeviceNV(pair.second);
        }
    }
    registeredDevices.clear();
    
    isInitialized = false;
}

HANDLE GPUGLInterop::RegisterD3DDevice(void* d3dDevice) {
    if (!isSupported || !d3dDevice) {
        return nullptr;
    }
    
    // 检查是否已经注册
    auto it = registeredDevices.find(d3dDevice);
    if (it != registeredDevices.end()) {
        return it->second;
    }
    
    // 注册设备
    HANDLE deviceHandle = wglDXOpenDeviceNV(d3dDevice);
    if (!deviceHandle) {
        return nullptr;
    }
    
    registeredDevices[d3dDevice] = deviceHandle;
    return deviceHandle;
}

bool GPUGLInterop::UnregisterD3DDevice(HANDLE deviceHandle) {
    if (!deviceHandle || !wglDXCloseDeviceNV) {
        return false;
    }
    
    // 从映射中移除
    for (auto it = registeredDevices.begin(); it != registeredDevices.end(); ++it) {
        if (it->second == deviceHandle) {
            registeredDevices.erase(it);
            break;
        }
    }
    
    return wglDXCloseDeviceNV(deviceHandle) == TRUE;
}

GLInteropHandle* GPUGLInterop::CreateGLTextureFromD3D(UINT64 resourceId) {
    if (!isSupported) {
        return nullptr;
    }
    
    // 检查是否已经创建
    auto it = interopHandles.find(resourceId);
    if (it != interopHandles.end()) {
        return it->second;
    }
    
    // 获取 D3D11 资源
    if (!resourcePool) return nullptr;
    auto* res = resourcePool->GetResource(resourceId);
    if (!res || !res->resource || !res->device) {
        return nullptr;
    }
    
    // 注册 D3D11 设备
    HANDLE wglDevice = RegisterD3DDevice(res->device);
    if (!wglDevice) {
        return nullptr;
    }
    
    // 创建 OpenGL 纹理
    GLuint glTexture = 0;
    glGenTextures(1, &glTexture);
    if (glTexture == 0) {
        return nullptr;
    }
    
    // 注册 D3D11 纹理到 OpenGL
    HANDLE interopObject = wglDXRegisterObjectNV(
        wglDevice,
        res->resource,
        glTexture,
        GL_TEXTURE_2D,
        WGL_ACCESS_READ_ONLY_NV
    );
    
    if (!interopObject) {
        glDeleteTextures(1, &glTexture);
        return nullptr;
    }
    
    // 创建互操作句柄
    GLInteropHandle* handle = new GLInteropHandle();
    handle->d3dDevice = wglDevice;
    handle->interopObject = interopObject;
    handle->glTexture = glTexture;
    handle->resourceId = resourceId;
    
    // 存储映射
    interopHandles[resourceId] = handle;
    glTextureMap[glTexture] = handle;
    
    return handle;
}

bool GPUGLInterop::LockTexture(GLInteropHandle* handle) {
    if (!handle || !handle->interopObject || !wglDXLockObjectsNV) {
        return false;
    }
    
    return wglDXLockObjectsNV(handle->d3dDevice, 1, &handle->interopObject) == TRUE;
}

bool GPUGLInterop::UnlockTexture(GLInteropHandle* handle) {
    if (!handle || !handle->interopObject || !wglDXUnlockObjectsNV) {
        return false;
    }
    
    return wglDXUnlockObjectsNV(handle->d3dDevice, 1, &handle->interopObject) == TRUE;
}

bool GPUGLInterop::ReleaseGLTexture(GLInteropHandle* handle) {
    if (!handle) {
        return false;
    }
    
    bool success = true;
    
    // 注销互操作对象
    if (handle->interopObject && wglDXUnregisterObjectNV) {
        success = wglDXUnregisterObjectNV(handle->d3dDevice, handle->interopObject) == TRUE;
    }
    
    // 删除 OpenGL 纹理
    if (handle->glTexture != 0) {
        glDeleteTextures(1, &handle->glTexture);
    }
    
    // 从映射中移除
    interopHandles.erase(handle->resourceId);
    glTextureMap.erase(handle->glTexture);
    
    delete handle;
    
    return success;
}

GLInteropHandle* GPUGLInterop::FindHandleByGLTexture(GLuint glTexture) {
    auto it = glTextureMap.find(glTexture);
    return (it != glTextureMap.end()) ? it->second : nullptr;
}