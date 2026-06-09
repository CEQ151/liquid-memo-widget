/*
 * 文件名: gpu_device_manager.h
 * 功能: GPU设备管理 - 检测、初始化、设备访问
 */

#pragma once

#include "gpu_types.h"

// ============================================================
//  GPU 设备管理器
// ============================================================

class GPUDeviceManager {
public:
    GPUDeviceManager() = default;
    ~GPUDeviceManager();

    // 禁止拷贝
    GPUDeviceManager(const GPUDeviceManager&) = delete;
    GPUDeviceManager& operator=(const GPUDeviceManager&) = delete;

    // ========== 初始化 ==========
    
    bool Initialize(GPUPreference preference = GPUPreference::Auto);
    void Shutdown();
    
    // ========== GPU 查询 ==========
    
    std::vector<GPUInfo> GetAllGPUs() const;
    std::vector<MonitorInfo> GetAllMonitors() const;
    
    int GetGPUCount() const { return static_cast<int>(gpuDevices.size()); }
    int GetMonitorCount() const { return static_cast<int>(monitors.size()); }
    
    GPUInfo GetMainGPU() const;
    int GetMainGPUIndex() const { return mainGPUIndex; }
    
    GPUInfo GetGPUByIndex(int index) const;
    MonitorInfo GetMonitorByIndex(int index) const;
    
    // ========== 设备访问 ==========
    
    ID3D11Device* GetMainDevice() const;
    ID3D11DeviceContext* GetMainContext() const;
    
    ID3D11Device* GetDeviceByGPUIndex(int gpuIndex) const;
    ID3D11DeviceContext* GetContextByGPUIndex(int gpuIndex) const;
    
    int FindGPUByMonitor(int monitorIndex) const;
    ID3D11Device* GetDeviceByMonitor(int monitorIndex) const;
    
    // ========== 状态 ==========
    
    bool IsInitialized() const { return initialized; }
    std::string GetDebugInfo() const;
    
    // ========== 内部访问(供资源池模块使用) ==========
    
    const std::vector<GPUDevice>& GetGPUDevices() const { return gpuDevices; }
    
private:
    bool EnumerateGPUsAndMonitors();
    bool InitializeGPUDevice(int gpuIndex);
    int ScoreGPU(const GPUInfo& info, GPUPreference preference);
    bool IsIntegratedGPU(UINT vendorId, size_t dedicatedMemory);
    std::wstring GetVendorName(UINT vendorId) const;
    
    static BOOL CALLBACK MonitorEnumProc(HMONITOR hMonitor, HDC hdcMonitor, 
                                         LPRECT lprcMonitor, LPARAM dwData);
    
    bool initialized = false;
    
    std::vector<GPUDevice> gpuDevices;
    int mainGPUIndex = -1;
    
    std::vector<MonitorInfo> monitors;
};