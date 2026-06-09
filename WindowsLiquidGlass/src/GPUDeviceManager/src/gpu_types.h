/*
 * 文件名: gpu_types.h
 * 功能: GPU管理器公共类型定义
 */

#pragma once

#include <d3d11.h>
#include <dxgi1_6.h>
#include <windows.h>
#include <string>
#include <vector>
#include <map>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")

#ifdef GPU_DEVICE_MANAGER_EXPORTS
#define GPUMGR_API __declspec(dllexport)
#else
#define GPUMGR_API __declspec(dllimport)
#endif

// ============================================================
//  资源 ID 分段常量（与 GPUResourcePool::AllocId 配合）
// ============================================================
constexpr UINT64 RESOURCE_SLOT_CAPTURE_BEGIN = 1;       // 屏幕截图纹理  1 ~ 999
constexpr UINT64 RESOURCE_SLOT_CAPTURE_END   = 999;

constexpr UINT64 RESOURCE_SLOT_SDF_BEGIN     = 1000;    // SDF 纹理      1000 ~ 1999
constexpr UINT64 RESOURCE_SLOT_SDF_END       = 1999;

constexpr UINT64 RESOURCE_SLOT_EFFECT_BEGIN  = 2000;    // 特效输出纹理  2000 ~ 2999
constexpr UINT64 RESOURCE_SLOT_EFFECT_END    = 2999;

// ============================================================
//  枚举类型
// ============================================================

enum class GPUResourceType {
    Texture2D = 0,
    Texture3D = 1,
    Buffer = 2,
    StructuredBuffer = 3,
    RenderTarget = 4,
    Custom = 5
};

enum class GPURole {
    Main = 0,          // 主GPU (用于计算)
    Display = 1,       // 有显示器连接的GPU
    Both = 2           // 既是主GPU也有显示器
};

enum class GPUPreference {
    Auto = 0,
    Dedicated = 1,
    Integrated = 2,
    LowPower = 3,
    HighPerformance = 4,
    Specific = 5
};

// ============================================================
//  GPU 信息
// ============================================================

struct GPUInfo {
    std::wstring name;
    size_t dedicatedVideoMemory;
    UINT vendorId;
    UINT deviceId;
    bool isIntegrated;
    int performanceScore;
    int adapterIndex;
    GPURole role;
    std::vector<int> connectedMonitors;
};

// ============================================================
//  显示器信息
// ============================================================

struct MonitorInfo {
    int index;
    HMONITOR handle;
    RECT bounds;
    int width;
    int height;
    std::wstring name;
    int gpuIndex;
    bool isPrimary;
};

// ============================================================
//  GPU 设备信息(内部)
// ============================================================

struct GPUDevice {
    ID3D11Device* device;
    ID3D11DeviceContext* context;
    IDXGIAdapter* adapter;
    GPUInfo info;
    
    GPUDevice() : device(nullptr), context(nullptr), adapter(nullptr) {}
};

// ============================================================
//  GPU资源缓存
// ============================================================

struct CachedGPUResource {
    UINT64 id;
    GPUResourceType type;
    int ownerGPUIndex;
    
    void* resource;     // ID3D11Resource*
    void* srv;          // ID3D11ShaderResourceView*
    void* uav;          // ID3D11UnorderedAccessView*
    void* rtv;          // ID3D11RenderTargetView*
    
    // 🔥 新增：存储实际的Device和Context指针（不持有引用）
    void* device;       // ID3D11Device* (非所有者)
    void* context;      // ID3D11DeviceContext* (非所有者)
    
    int width;
    int height;
    int depth;
    size_t sizeInBytes;
    
    DXGI_FORMAT format;
    
    std::string tag;
    void* userData;
    
    CachedGPUResource() : id(0), type(GPUResourceType::Custom), ownerGPUIndex(-1),
                         resource(nullptr), srv(nullptr), uav(nullptr), rtv(nullptr),
                         device(nullptr), context(nullptr),  // 🔥 初始化新字段
                         width(0), height(0), depth(0), sizeInBytes(0),
                         format(DXGI_FORMAT_UNKNOWN), userData(nullptr) {}
};

// ============================================================
//  资源描述符
// ============================================================

struct GPUResourceDesc {
    GPUResourceType type;
    int width;
    int height;
    int depth;
    DXGI_FORMAT format;
    UINT bindFlags;
    D3D11_USAGE usage;
    std::string tag;
    
    GPUResourceDesc() : type(GPUResourceType::Texture2D), width(0), height(0), depth(1),
                       format(DXGI_FORMAT_R8G8B8A8_UNORM),
                       bindFlags(D3D11_BIND_SHADER_RESOURCE),
                       usage(D3D11_USAGE_DEFAULT) {}
};

// ============================================================
//  缓存池统计信息
// ============================================================

struct PoolStats {
    int totalResources;
    size_t totalMemoryBytes;
    std::map<GPUResourceType, int> resourcesByType;
    std::map<int, int> resourcesByGPU;
};

// ============================================================
//  辅助函数
// ============================================================

template<typename T>
inline void SafeRelease(T*& ptr) {
    if (ptr) { 
        ptr->Release(); 
        ptr = nullptr; 
    }
}