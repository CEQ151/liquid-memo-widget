/*
 * 文件名: gpu_gl_interop.h
 * 功能: D3D11/OpenGL 互操作 - 零拷贝纹理共享
 */

#pragma once

#include "gpu_types.h"
#include <windows.h>
#include <GL/gl.h>

// 前置声明
class GPUResourcePool;

// WGL_NV_DX_interop 扩展函数指针
typedef BOOL (WINAPI * PFNWGLDXSETRESOURCESHAREHANDLENVPROC) (void *dxObject, HANDLE shareHandle);
typedef HANDLE (WINAPI * PFNWGLDXOPENDEVICENVPROC) (void *dxDevice);
typedef BOOL (WINAPI * PFNWGLDXCLOSEDEVICENVPROC) (HANDLE hDevice);
typedef HANDLE (WINAPI * PFNWGLDXREGISTEROBJECTNVPROC) (HANDLE hDevice, void *dxObject, GLuint name, GLenum type, GLenum access);
typedef BOOL (WINAPI * PFNWGLDXUNREGISTEROBJECTNVPROC) (HANDLE hDevice, HANDLE hObject);
typedef BOOL (WINAPI * PFNWGLDXOBJECTACCESSNVPROC) (HANDLE hObject, GLenum access);
typedef BOOL (WINAPI * PFNWGLDXLOCKOBJECTSNVPROC) (HANDLE hDevice, GLint count, HANDLE *hObjects);
typedef BOOL (WINAPI * PFNWGLDXUNLOCKOBJECTSNVPROC) (HANDLE hDevice, GLint count, HANDLE *hObjects);

// 互操作句柄结构
struct GLInteropHandle {
    HANDLE d3dDevice;        // wglDXOpenDeviceNV 返回的设备句柄
    HANDLE interopObject;    // wglDXRegisterObjectNV 返回的对象句柄
    GLuint glTexture;        // OpenGL 纹理 ID
    UINT64 resourceId;       // 对应的资源池 ID
    
    GLInteropHandle() : d3dDevice(nullptr), interopObject(nullptr), 
                       glTexture(0), resourceId(0) {}
};

// ============================================================
//  GPU OpenGL 互操作管理器
// ============================================================

class GPUGLInterop {
public:
    GPUGLInterop() = default;
    ~GPUGLInterop();

    // 禁止拷贝
    GPUGLInterop(const GPUGLInterop&) = delete;
    GPUGLInterop& operator=(const GPUGLInterop&) = delete;

    // 设置依赖
    void SetResourcePool(GPUResourcePool* pool) { resourcePool = pool; }

    // 初始化互操作系统（需要在 OpenGL Context 中调用）
    bool Initialize();
    
    // 检查是否支持互操作
    bool IsSupported() const { return isSupported; }
    
    // 关闭互操作系统
    void Shutdown();
    
    // ========== D3D11 设备注册 ==========
    
    // 注册 D3D11 设备到 OpenGL
    HANDLE RegisterD3DDevice(void* d3dDevice);
    
    // 注销 D3D11 设备
    bool UnregisterD3DDevice(HANDLE deviceHandle);
    
    // ========== 纹理互操作 ==========
    
    // 从资源池中的 D3D11 纹理创建 OpenGL 纹理（零拷贝）
    GLInteropHandle* CreateGLTextureFromD3D(UINT64 resourceId);
    
    // 锁定纹理（在 OpenGL 使用前调用）
    bool LockTexture(GLInteropHandle* handle);
    
    // 解锁纹理（在 OpenGL 使用后调用）
    bool UnlockTexture(GLInteropHandle* handle);
    
    // 释放互操作纹理
    bool ReleaseGLTexture(GLInteropHandle* handle);
    
    // 通过 GL 纹理 ID 查找句柄
    GLInteropHandle* FindHandleByGLTexture(GLuint glTexture);
    
private:
    bool LoadWGLExtensions();
    
    // 依赖注入
    GPUResourcePool* resourcePool = nullptr;
    
    bool isSupported = false;
    bool isInitialized = false;
    
    // WGL 扩展函数指针
    PFNWGLDXOPENDEVICENVPROC wglDXOpenDeviceNV = nullptr;
    PFNWGLDXCLOSEDEVICENVPROC wglDXCloseDeviceNV = nullptr;
    PFNWGLDXREGISTEROBJECTNVPROC wglDXRegisterObjectNV = nullptr;
    PFNWGLDXUNREGISTEROBJECTNVPROC wglDXUnregisterObjectNV = nullptr;
    PFNWGLDXLOCKOBJECTSNVPROC wglDXLockObjectsNV = nullptr;
    PFNWGLDXUNLOCKOBJECTSNVPROC wglDXUnlockObjectsNV = nullptr;
    PFNWGLDXSETRESOURCESHAREHANDLENVPROC wglDXSetResourceShareHandleNV = nullptr;
    
    // 已注册的设备和纹理
    std::map<void*, HANDLE> registeredDevices;  // D3D11Device* -> WGL Device Handle
    std::map<UINT64, GLInteropHandle*> interopHandles;  // resourceId -> GLInteropHandle
    std::map<GLuint, GLInteropHandle*> glTextureMap;    // GLuint -> GLInteropHandle
};