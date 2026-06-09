/*
 * 文件名: gpu_device_manager.cpp
 * 功能: GPU设备管理实现
 */

#include "gpu_device_manager.h"
#include <sstream>
#include <algorithm>

// ============================================================
//  辅助函数 - 字符串转换
// ============================================================

static std::string WStringToString(const std::wstring& wstr) {
    if (wstr.empty()) return std::string();
    
    int size_needed = WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), NULL, 0, NULL, NULL);
    std::string strTo(size_needed, 0);
    WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), &strTo[0], size_needed, NULL, NULL);
    return strTo;
}

// ============================================================
//  单例实现
// ============================================================

GPUDeviceManager::~GPUDeviceManager() {
    Shutdown();
}

// ============================================================
//  初始化 - 智能多GPU检测
// ============================================================

bool GPUDeviceManager::Initialize(GPUPreference preference) {
    if (initialized) {
        return true;
    }
    
    // 1. 枚举所有GPU和显示器
    if (!EnumerateGPUsAndMonitors()) {
        return false;
    }
    
    // 2. 选择主GPU
    int bestScore = -1;
    for (size_t i = 0; i < gpuDevices.size(); ++i) {
        int score = ScoreGPU(gpuDevices[i].info, preference);
        if (score > bestScore) {
            bestScore = score;
            mainGPUIndex = static_cast<int>(i);
        }
    }
    
    if (mainGPUIndex < 0) {
        return false;
    }
    
    // 3. 初始化主GPU
    if (!InitializeGPUDevice(mainGPUIndex)) {
        return false;
    }
    
    // 更新主GPU角色
    if (gpuDevices[mainGPUIndex].info.connectedMonitors.empty()) {
        gpuDevices[mainGPUIndex].info.role = GPURole::Main;
    } else {
        gpuDevices[mainGPUIndex].info.role = GPURole::Both;
    }
    
    // 4. 初始化有显示器连接的其他GPU
    for (size_t i = 0; i < gpuDevices.size(); ++i) {
        if ((int)i == mainGPUIndex) continue;
        if (gpuDevices[i].info.connectedMonitors.empty()) continue;
        
        InitializeGPUDevice(static_cast<int>(i));
    }
    
    initialized = true;
    return true;
}

// ============================================================
//  枚举GPU和显示器
// ============================================================

bool GPUDeviceManager::EnumerateGPUsAndMonitors() {
    IDXGIFactory* factory = nullptr;
    if (FAILED(CreateDXGIFactory(__uuidof(IDXGIFactory), (void**)&factory))) {
        return false;
    }
    
    // 1. 枚举所有GPU
    std::vector<GPUInfo> allGPUs;
    IDXGIAdapter* adapter = nullptr;
    
    for (UINT i = 0; factory->EnumAdapters(i, &adapter) != DXGI_ERROR_NOT_FOUND; ++i) {
        DXGI_ADAPTER_DESC desc;
        adapter->GetDesc(&desc);
        
        GPUInfo info;
        info.name = desc.Description;
        info.dedicatedVideoMemory = desc.DedicatedVideoMemory;
        info.vendorId = desc.VendorId;
        info.deviceId = desc.DeviceId;
        info.adapterIndex = i;
        info.isIntegrated = IsIntegratedGPU(desc.VendorId, desc.DedicatedVideoMemory);
        info.role = GPURole::Display;
        
        // 计算性能评分
        if (info.isIntegrated) {
            info.performanceScore = 30;
        } else {
            size_t memGB = desc.DedicatedVideoMemory / (1024 * 1024 * 1024);
            info.performanceScore = 50 + (std::min)(static_cast<int>(memGB) * 5, 50);
        }
        
        allGPUs.push_back(info);
        adapter->Release();
    }
    
    // 2. 枚举所有显示器
    monitors.clear();
    EnumDisplayMonitors(nullptr, nullptr, MonitorEnumProc, reinterpret_cast<LPARAM>(this));
    
    // 3. 为每个显示器找到对应的GPU
    for (auto& monitor : monitors) {
        int gpuIndex = -1;
        
        for (UINT adapterIdx = 0; factory->EnumAdapters(adapterIdx, &adapter) != DXGI_ERROR_NOT_FOUND; ++adapterIdx) {
            for (UINT outputIdx = 0; ; ++outputIdx) {
                IDXGIOutput* output = nullptr;
                if (FAILED(adapter->EnumOutputs(outputIdx, &output))) break;
                
                DXGI_OUTPUT_DESC outputDesc;
                output->GetDesc(&outputDesc);
                
                if (outputDesc.Monitor == monitor.handle) {
                    gpuIndex = adapterIdx;
                    monitor.gpuIndex = gpuIndex;
                    
                    if (gpuIndex < (int)allGPUs.size()) {
                        allGPUs[gpuIndex].connectedMonitors.push_back(monitor.index);
                    }
                    
                    output->Release();
                    adapter->Release();
                    goto found_gpu;
                }
                output->Release();
            }
            adapter->Release();
        }
        found_gpu:;
    }
    
    factory->Release();
    
    // 4. 保存GPU信息
    for (const auto& gpu : allGPUs) {
        GPUDevice device;
        device.info = gpu;
        gpuDevices.push_back(device);
    }
    
    return !gpuDevices.empty();
}

BOOL CALLBACK GPUDeviceManager::MonitorEnumProc(HMONITOR hMonitor, HDC hdcMonitor, 
                                                 LPRECT lprcMonitor, LPARAM dwData) {
    auto* manager = reinterpret_cast<GPUDeviceManager*>(dwData);
    
    MonitorInfo info;
    info.index = static_cast<int>(manager->monitors.size());
    info.handle = hMonitor;
    info.bounds = *lprcMonitor;
    info.width = lprcMonitor->right - lprcMonitor->left;
    info.height = lprcMonitor->bottom - lprcMonitor->top;
    info.gpuIndex = -1;
    info.isPrimary = (lprcMonitor->left == 0 && lprcMonitor->top == 0);
    
    MONITORINFOEXW monitorInfo;
    monitorInfo.cbSize = sizeof(MONITORINFOEXW);
    if (GetMonitorInfoW(hMonitor, &monitorInfo)) {
        info.name = monitorInfo.szDevice;
    }
    
    manager->monitors.push_back(info);
    return TRUE;
}

// ============================================================
//  初始化GPU设备
// ============================================================

bool GPUDeviceManager::InitializeGPUDevice(int gpuIndex) {
    if (gpuIndex < 0 || gpuIndex >= (int)gpuDevices.size()) {
        return false;
    }
    
    auto& gpu = gpuDevices[gpuIndex];
    if (gpu.device) {
        return true;  // 已初始化
    }
    
    IDXGIFactory* factory = nullptr;
    if (FAILED(CreateDXGIFactory(__uuidof(IDXGIFactory), (void**)&factory))) {
        return false;
    }
    
    IDXGIAdapter* adapter = nullptr;
    if (FAILED(factory->EnumAdapters(gpu.info.adapterIndex, &adapter))) {
        factory->Release();
        return false;
    }
    
    factory->Release();
    
    D3D_FEATURE_LEVEL featureLevels[] = {
        D3D_FEATURE_LEVEL_11_1,
        D3D_FEATURE_LEVEL_11_0
    };
    
    D3D_FEATURE_LEVEL featureLevel;
    HRESULT hr = D3D11CreateDevice(
        adapter,
        D3D_DRIVER_TYPE_UNKNOWN,
        nullptr,
        0,
        featureLevels,
        2,
        D3D11_SDK_VERSION,
        &gpu.device,
        &featureLevel,
        &gpu.context
    );
    
    if (FAILED(hr)) {
        adapter->Release();
        return false;
    }
    
    gpu.adapter = adapter;
    return true;
}

// ============================================================
//  查询方法
// ============================================================

std::vector<GPUInfo> GPUDeviceManager::GetAllGPUs() const {
    std::vector<GPUInfo> result;
    for (const auto& dev : gpuDevices) {
        result.push_back(dev.info);
    }
    return result;
}

std::vector<MonitorInfo> GPUDeviceManager::GetAllMonitors() const {
    return monitors;
}

GPUInfo GPUDeviceManager::GetMainGPU() const {
    if (mainGPUIndex >= 0 && mainGPUIndex < (int)gpuDevices.size()) {
        return gpuDevices[mainGPUIndex].info;
    }
    return GPUInfo();
}

GPUInfo GPUDeviceManager::GetGPUByIndex(int index) const {
    if (index >= 0 && index < (int)gpuDevices.size()) {
        return gpuDevices[index].info;
    }
    return GPUInfo();
}

MonitorInfo GPUDeviceManager::GetMonitorByIndex(int index) const {
    if (index >= 0 && index < (int)monitors.size()) {
        return monitors[index];
    }
    return MonitorInfo();
}

// ============================================================
//  设备访问
// ============================================================

ID3D11Device* GPUDeviceManager::GetMainDevice() const {
    if (mainGPUIndex >= 0 && mainGPUIndex < (int)gpuDevices.size()) {
        return gpuDevices[mainGPUIndex].device;
    }
    return nullptr;
}

ID3D11DeviceContext* GPUDeviceManager::GetMainContext() const {
    if (mainGPUIndex >= 0 && mainGPUIndex < (int)gpuDevices.size()) {
        return gpuDevices[mainGPUIndex].context;
    }
    return nullptr;
}

ID3D11Device* GPUDeviceManager::GetDeviceByGPUIndex(int gpuIndex) const {
    if (gpuIndex >= 0 && gpuIndex < (int)gpuDevices.size()) {
        return gpuDevices[gpuIndex].device;
    }
    return nullptr;
}

ID3D11DeviceContext* GPUDeviceManager::GetContextByGPUIndex(int gpuIndex) const {
    if (gpuIndex >= 0 && gpuIndex < (int)gpuDevices.size()) {
        return gpuDevices[gpuIndex].context;
    }
    return nullptr;
}

int GPUDeviceManager::FindGPUByMonitor(int monitorIndex) const {
    if (monitorIndex >= 0 && monitorIndex < (int)monitors.size()) {
        return monitors[monitorIndex].gpuIndex;
    }
    return -1;
}

ID3D11Device* GPUDeviceManager::GetDeviceByMonitor(int monitorIndex) const {
    int gpuIndex = FindGPUByMonitor(monitorIndex);
    return GetDeviceByGPUIndex(gpuIndex);
}

// ============================================================
//  辅助函数
// ============================================================

int GPUDeviceManager::ScoreGPU(const GPUInfo& info, GPUPreference preference) {
    int score = info.performanceScore;
    
    switch (preference) {
        case GPUPreference::Dedicated:
        case GPUPreference::HighPerformance:
            if (!info.isIntegrated) score += 50;
            break;
            
        case GPUPreference::Integrated:
        case GPUPreference::LowPower:
            if (info.isIntegrated) score += 50;
            break;
            
        case GPUPreference::Auto:
        default:
            break;
    }
    
    return score;
}

bool GPUDeviceManager::IsIntegratedGPU(UINT vendorId, size_t dedicatedMemory) {
    if (vendorId == 0x8086) {  // Intel
        return true;
    }
    
    if (vendorId == 0x1002 && dedicatedMemory < 512 * 1024 * 1024) {  // AMD APU
        return true;
    }
    
    if (dedicatedMemory < 256 * 1024 * 1024) {
        return true;
    }
    
    return false;
}

std::wstring GPUDeviceManager::GetVendorName(UINT vendorId) const {
    switch (vendorId) {
        case 0x10DE: return L"NVIDIA";
        case 0x1002: return L"AMD";
        case 0x8086: return L"Intel";
        default: return L"Unknown";
    }
}

// ============================================================
//  调试信息
// ============================================================

std::string GPUDeviceManager::GetDebugInfo() const {
    if (!initialized) {
        return "GPU Device Manager: Not initialized";
    }
    
    std::stringstream ss;
    ss << "=== GPU Device Manager ===\n";
    ss << "Initialized: Yes\n";
    ss << "GPU Count: " << gpuDevices.size() << "\n";
    ss << "Monitor Count: " << monitors.size() << "\n\n";
    
    // 主GPU信息
    if (mainGPUIndex >= 0 && mainGPUIndex < (int)gpuDevices.size()) {
        const auto& mainGPU = gpuDevices[mainGPUIndex].info;
        ss << "Main GPU [" << mainGPUIndex << "]:\n";
        ss << "  Name: " << WStringToString(mainGPU.name) << "\n";
        ss << "  Vendor: " << WStringToString(GetVendorName(mainGPU.vendorId)) << "\n";
        ss << "  Memory: " << (mainGPU.dedicatedVideoMemory / (1024*1024)) << " MB\n";
        ss << "  Type: " << (mainGPU.isIntegrated ? "Integrated" : "Dedicated") << "\n";
        ss << "  Role: " << (mainGPU.role == GPURole::Main ? "Main" : 
                            mainGPU.role == GPURole::Display ? "Display" : "Both") << "\n";
        ss << "  Connected Monitors: " << mainGPU.connectedMonitors.size() << "\n\n";
    }
    
    // 所有GPU列表
    ss << "All GPUs:\n";
    for (size_t i = 0; i < gpuDevices.size(); ++i) {
        const auto& gpu = gpuDevices[i].info;
        ss << "  [" << i << "] " << WStringToString(gpu.name);
        ss << " (" << (gpu.dedicatedVideoMemory / (1024*1024)) << "MB, ";
        ss << "Score: " << gpu.performanceScore << ", ";
        ss << "Monitors: " << gpu.connectedMonitors.size() << ")\n";
    }
    
    return ss.str();
}

// ============================================================
//  清理
// ============================================================

void GPUDeviceManager::Shutdown() {
    if (!initialized) return;
    
    // 释放GPU设备
    for (auto& gpu : gpuDevices) {
        SafeRelease(gpu.context);
        SafeRelease(gpu.device);
        SafeRelease(gpu.adapter);
    }
    
    gpuDevices.clear();
    monitors.clear();
    mainGPUIndex = -1;
    initialized = false;
}