#pragma once

#include "gpu_types.h"
#include <dxgi1_2.h>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

// 前置声明
class GPUDeviceManager;
class GPUResourcePool;

// ============================================================
//  显示器捕获数据
// ============================================================

struct DisplayCaptureData {
    int monitorIndex;
    HMONITOR hMonitor;
    RECT bounds;

    ID3D11Device* device;
    ID3D11DeviceContext* context;
    IDXGIOutputDuplication* duplication;

    ID3D11Texture2D* currentTexture;
    bool hasAcquiredFrame;

    DisplayCaptureData()
        : monitorIndex(-1), hMonitor(nullptr), device(nullptr),
          context(nullptr), duplication(nullptr),
          currentTexture(nullptr), hasAcquiredFrame(false) {
        bounds = {0, 0, 0, 0};
    }
};

// ============================================================
//  显示器捕获管理器
// ============================================================

class GPUDisplayCapture {
public:
    GPUDisplayCapture();
    ~GPUDisplayCapture();

    // ---- 进程级单例：所有 GPUContext 共享一个 DXGI duplication 实例 ----
    // 引用计数第一次创建，最后一次释放销毁
    static GPUDisplayCapture* AcquireShared(GPUDeviceManager* mgr);
    static void                ReleaseShared();

    // 设置依赖（仅首次概欲创建时有效）
    void SetDeviceManager(GPUDeviceManager* mgr) { deviceMgr = mgr; }

    bool Initialize();
    void Shutdown();
    bool IsInitialized() const { return m_initialized; }

    int GetDisplayCount() const;
    bool GetDisplayBounds(int displayIndex, int* left, int* top, int* right, int* bottom) const;
    int GetDisplayGPUIndex(int displayIndex) const;

    ID3D11Texture2D* GetDisplayTexture(int displayIndex);

    // 每个 GPUContext 传入自己的 device/pool/persistentResources，确保纹理资源完全隔离
    UINT64 CaptureDisplayRegion(
        int displayIndex, int x, int y, int width, int height,
        ID3D11Device*        dstDevice,
        ID3D11DeviceContext* dstContext,
        GPUResourcePool*     pool,
        std::unordered_map<std::string, UINT64>& persistentResources,
        int mainGPUIndex,
        const char* tag = nullptr);

    void ReleaseCurrentFrame(int displayIndex);

    ID3D11Device* GetDisplayDevice(int displayIndex) const;
    ID3D11DeviceContext* GetDisplayContext(int displayIndex) const;

    std::string GetDebugInfo() const;

private:
    bool InitializeDisplayCapture(DisplayCaptureData& data);
    void ShutdownDisplayCapture(DisplayCaptureData& data);

private:
    bool m_initialized;
    std::vector<DisplayCaptureData> m_displays;
    std::string m_lastError;

    // 依赖注入（仅首次获取的 context 设置）
    GPUDeviceManager* deviceMgr = nullptr;
};
