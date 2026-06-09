/*
 * 文件名: gpu_display_capture.cpp
 * 功能: Desktop Duplication 显示器纹理获取实现
 */

#include "gpu_display_capture.h"
#include "gpu_device_manager.h"
#include "gpu_resource_pool.h"
#include <sstream>

// 已移除全局单例函数 GetGPUDisplayCapture()
// 请使用 GPUContext 创建独立实例

// ============================================================
//  进程级共享单例（引用计数）
// ============================================================

static GPUDisplayCapture* g_sharedCapture  = nullptr;
static int                g_sharedRefCount = 0;

// static
GPUDisplayCapture* GPUDisplayCapture::AcquireShared(GPUDeviceManager* mgr) {
    if (!g_sharedCapture) {
        g_sharedCapture           = new GPUDisplayCapture();
        g_sharedCapture->deviceMgr = mgr;   // 仅首次创建时设置
    }
    ++g_sharedRefCount;
    return g_sharedCapture;
}

// static
void GPUDisplayCapture::ReleaseShared() {
    if (g_sharedRefCount > 0 && --g_sharedRefCount == 0) {
        delete g_sharedCapture;
        g_sharedCapture = nullptr;
    }
}

// ============================================================
//  实现
// ============================================================

GPUDisplayCapture::GPUDisplayCapture() : m_initialized(false) {
}

GPUDisplayCapture::~GPUDisplayCapture() {
    Shutdown();
}

bool GPUDisplayCapture::Initialize() {
    if (m_initialized) {
        return true;
    }
    
    // 必须先初始化 GPUDeviceManager
    if (!deviceMgr) {
        m_lastError = "GPUDeviceManager not set, call SetDeviceManager() first";
        return false;
    }
    if (!deviceMgr->IsInitialized()) {
        m_lastError = "GPUDeviceManager must be initialized first";
        return false;
    }
    
    // 获取显示器数量
    int monitorCount = deviceMgr->GetMonitorCount();
    if (monitorCount == 0) {
        m_lastError = "No monitors found";
        return false;
    }
    
    m_displays.resize(monitorCount);
    
    for (int i = 0; i < monitorCount; i++) {
        auto& display = m_displays[i];
        display.monitorIndex = i;
        
        // 获取显示器信息
        MonitorInfo monInfo = deviceMgr->GetMonitorByIndex(i);
        display.bounds = monInfo.bounds;
        display.hMonitor = monInfo.handle;
        
        // 初始化 Desktop Duplication
        if (!InitializeDisplayCapture(display)) {
            m_lastError = "Failed to initialize Desktop Duplication for monitor " + std::to_string(i);
            continue;
        }
    }
    
    m_initialized = true;
    return true;
}

bool GPUDisplayCapture::InitializeDisplayCapture(DisplayCaptureData& data) {
    // 创建 DXGI Factory
    IDXGIFactory1* factory = nullptr;
    HRESULT hr = CreateDXGIFactory1(__uuidof(IDXGIFactory1), (void**)(&factory));
    if (FAILED(hr)) {
        return false;
    }
    
    // 枚举所有 Adapter
    UINT adapterIndex = 0;
    IDXGIAdapter1* adapter = nullptr;
    
    while (factory->EnumAdapters1(adapterIndex, &adapter) != DXGI_ERROR_NOT_FOUND) {
        // 枚举该 Adapter 的所有 Output
        UINT outputIndex = 0;
        IDXGIOutput* output = nullptr;
        
        while (adapter->EnumOutputs(outputIndex, &output) != DXGI_ERROR_NOT_FOUND) {
            DXGI_OUTPUT_DESC desc;
            output->GetDesc(&desc);
            
            // 检查是否匹配当前显示器
            if (desc.DesktopCoordinates.left == data.bounds.left &&
                desc.DesktopCoordinates.top == data.bounds.top) {
                
                data.hMonitor = desc.Monitor;
                
                // 从这个 Adapter 创建 Device（保证 Device 和 Output 匹配）
                D3D_FEATURE_LEVEL featureLevel;
                hr = D3D11CreateDevice(
                    adapter,
                    D3D_DRIVER_TYPE_UNKNOWN,
                    NULL,
                    0,
                    NULL,
                    0,
                    D3D11_SDK_VERSION,
                    &data.device,
                    &featureLevel,
                    &data.context
                );
                
                if (FAILED(hr)) {
                    output->Release();
                    adapter->Release();
                    factory->Release();
                    return false;
                }
                
                // 创建 Desktop Duplication
                IDXGIOutput1* output1 = nullptr;
                hr = output->QueryInterface(__uuidof(IDXGIOutput1), (void**)&output1);
                output->Release();
                
                if (FAILED(hr)) {
                    data.device->Release();
                    data.device = nullptr;
                    data.context->Release();
                    data.context = nullptr;
                    adapter->Release();
                    factory->Release();
                    return false;
                }
                
                hr = output1->DuplicateOutput(data.device, &data.duplication);
                output1->Release();
                
                if (FAILED(hr)) {
                    data.device->Release();
                    data.device = nullptr;
                    data.context->Release();
                    data.context = nullptr;
                    adapter->Release();
                    factory->Release();
                    return false;
                }
                
                adapter->Release();
                factory->Release();
                return true;
            }
            
            output->Release();
            outputIndex++;
        }
        
        adapter->Release();
        adapterIndex++;
    }
    
    factory->Release();
    return false;
}

void GPUDisplayCapture::ShutdownDisplayCapture(DisplayCaptureData& data) {
    // 释放当前帧
    if (data.hasAcquiredFrame && data.duplication) {
        data.duplication->ReleaseFrame();
        if (data.currentTexture) {
            data.currentTexture->Release();
            data.currentTexture = nullptr;
        }
        data.hasAcquiredFrame = false;
    }
    
    if (data.duplication) {
        data.duplication->Release();
        data.duplication = nullptr;
    }
    
    if (data.context) {
        data.context->Release();
        data.context = nullptr;
    }
    
    if (data.device) {
        data.device->Release();
        data.device = nullptr;
    }
}

void GPUDisplayCapture::Shutdown() {
    if (!m_initialized) {
        return;
    }

    for (auto& display : m_displays) {
        ShutdownDisplayCapture(display);
    }

    m_displays.clear();
    m_initialized = false;
}

int GPUDisplayCapture::GetDisplayCount() const {
    return (int)m_displays.size();
}

bool GPUDisplayCapture::GetDisplayBounds(int displayIndex, int* left, int* top, int* right, int* bottom) const {
    if (displayIndex < 0 || displayIndex >= (int)m_displays.size()) {
        return false;
    }
    
    const auto& bounds = m_displays[displayIndex].bounds;
    if (left) *left = bounds.left;
    if (top) *top = bounds.top;
    if (right) *right = bounds.right;
    if (bottom) *bottom = bounds.bottom;
    return true;
}

int GPUDisplayCapture::GetDisplayGPUIndex(int displayIndex) const {
    if (displayIndex < 0 || displayIndex >= (int)m_displays.size()) {
        return -1;
    }
    
    // 通过 device 查找对应的 GPU 索引
    if (!deviceMgr) return -1;
    auto* device = m_displays[displayIndex].device;
    
    for (int i = 0; i < deviceMgr->GetGPUCount(); i++) {
        if (deviceMgr->GetDeviceByGPUIndex(i) == device) {
            return i;
        }
    }
    
    return -1;
}

// 核心功能：获取显示器纹理（零拷贝）
ID3D11Texture2D* GPUDisplayCapture::GetDisplayTexture(int displayIndex) {
    if (displayIndex < 0 || displayIndex >= (int)m_displays.size()) {
        return nullptr;
    }
    
    auto& display = m_displays[displayIndex];
    if (!display.duplication) {
        return nullptr;
    }
    
    // 释放上一帧
    if (display.hasAcquiredFrame) {
        display.duplication->ReleaseFrame();
        if (display.currentTexture) {
            display.currentTexture->Release();
            display.currentTexture = nullptr;
        }
        display.hasAcquiredFrame = false;
    }
    
    // 获取新帧（0ms 超时）
    DXGI_OUTDUPL_FRAME_INFO frameInfo;
    IDXGIResource* desktopResource = nullptr;
    HRESULT hr = display.duplication->AcquireNextFrame(0, &frameInfo, &desktopResource);
    
    // 没有新帧
    if (hr == DXGI_ERROR_WAIT_TIMEOUT) {
        return nullptr;
    }
    
    if (FAILED(hr)) {
        return nullptr;
    }
    
    // 获取纹理接口（零拷贝）
    hr = desktopResource->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&display.currentTexture);
    desktopResource->Release();
    
    if (FAILED(hr)) {
        display.duplication->ReleaseFrame();
        return nullptr;
    }
    
    display.hasAcquiredFrame = true;
    return display.currentTexture;
}

// ============================================================
//  内部辅助：为单个显示器截取区域（全局坐标系）
//  outTexture 是在 dstDevice 上创建的纹理，宽度=width，高度=height
//  在 dstDevice 上，只有该显示器覆盖的部分被写入，其余区域是垃圾数据
//  返回 false 表示该显示器与请求区域完全不相交
// ============================================================
static bool CaptureOneDisplay(
    DisplayCaptureData& display,
    ID3D11Device* dstDevice,
    ID3D11DeviceContext* dstContext,
    int globalX, int globalY,
    int width, int height,
    ID3D11Texture2D* dstTexture)
{
    int dispL = display.bounds.left;
    int dispT = display.bounds.top;
    int dispR = display.bounds.right;
    int dispB = display.bounds.bottom;

    int reqL = globalX, reqT = globalY;
    int reqR = globalX + width, reqB = globalY + height;

    int isectL = max(reqL, dispL), isectT = max(reqT, dispT);
    int isectR = min(reqR, dispR), isectB = min(reqB, dispB);

    if (isectL >= isectR || isectT >= isectB) return false;

    int srcX = isectL - dispL, srcY = isectT - dispT;
    int srcW = isectR - isectL, srcH = isectB - isectT;
    int dstX = isectL - reqL,   dstY = isectT - reqT;

    // 尝试获取新帧
    DXGI_OUTDUPL_FRAME_INFO frameInfo;
    IDXGIResource* desktopResource = nullptr;
    bool acquiredNewFrame = false;

    HRESULT hr = display.duplication->AcquireNextFrame(0, &frameInfo, &desktopResource);

    if (SUCCEEDED(hr)) {
        // 拿到新帧，替换 currentTexture
        ID3D11Texture2D* srcTex = nullptr;
        hr = desktopResource->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&srcTex);
        desktopResource->Release();
        if (FAILED(hr)) {
            display.duplication->ReleaseFrame();
            return false;
        }
        // 释放旧的持有纹理（若有）
        if (display.currentTexture) {
            display.currentTexture->Release();
            display.currentTexture = nullptr;
        }
        display.currentTexture   = srcTex;
        display.hasAcquiredFrame = true;
        acquiredNewFrame = true;
    } else if (hr == DXGI_ERROR_WAIT_TIMEOUT) {
        // 屏幕无变化，复用上一帧 currentTexture
        if (!display.currentTexture) return false;
        // acquiredNewFrame = false，后面不 ReleaseFrame
    } else {
        // 真正的错误
        return false;
    }

    // 用 currentTexture 拷贝到 dstTexture
    ID3D11Texture2D* srcTex = display.currentTexture;
    bool sameDevice = (display.device == dstDevice);

    if (sameDevice) {
        D3D11_BOX box = { (UINT)srcX, (UINT)srcY, 0, (UINT)(srcX+srcW), (UINT)(srcY+srcH), 1 };
        dstContext->CopySubresourceRegion(dstTexture, 0, dstX, dstY, 0, srcTex, 0, &box);
    } else {
        // ── 跨设备：CPU Staging 中转 ──────────────────────────────
        D3D11_TEXTURE2D_DESC srcDesc;
        srcTex->GetDesc(&srcDesc);

        D3D11_TEXTURE2D_DESC stagingDesc = {};
        stagingDesc.Width            = (UINT)srcW;
        stagingDesc.Height           = (UINT)srcH;
        stagingDesc.MipLevels        = 1;
        stagingDesc.ArraySize        = 1;
        stagingDesc.Format           = srcDesc.Format;
        stagingDesc.SampleDesc.Count = 1;
        stagingDesc.Usage            = D3D11_USAGE_STAGING;
        stagingDesc.CPUAccessFlags   = D3D11_CPU_ACCESS_READ;

        ID3D11Texture2D* stagingTex = nullptr;
        hr = display.device->CreateTexture2D(&stagingDesc, nullptr, &stagingTex);
        if (FAILED(hr)) {
            if (acquiredNewFrame) {
                display.duplication->ReleaseFrame();
                display.currentTexture->Release();
                display.currentTexture   = nullptr;
                display.hasAcquiredFrame = false;
            }
            return false;
        }

        {
            D3D11_BOX box = { (UINT)srcX, (UINT)srcY, 0, (UINT)(srcX+srcW), (UINT)(srcY+srcH), 1 };
            display.context->CopySubresourceRegion(stagingTex, 0, 0, 0, 0, srcTex, 0, &box);
            display.context->Flush();

            D3D11_MAPPED_SUBRESOURCE mapped = {};
            hr = display.context->Map(stagingTex, 0, D3D11_MAP_READ, 0, &mapped);
            if (FAILED(hr)) {
                stagingTex->Release();
                if (acquiredNewFrame) {
                    display.duplication->ReleaseFrame();
                    display.currentTexture->Release();
                    display.currentTexture   = nullptr;
                    display.hasAcquiredFrame = false;
                }
                return false;
            }

            D3D11_TEXTURE2D_DESC uploadDesc = {};
            uploadDesc.Width            = (UINT)srcW;
            uploadDesc.Height           = (UINT)srcH;
            uploadDesc.MipLevels        = 1;
            uploadDesc.ArraySize        = 1;
            uploadDesc.Format           = DXGI_FORMAT_B8G8R8A8_UNORM;
            uploadDesc.SampleDesc.Count = 1;
            uploadDesc.Usage            = D3D11_USAGE_DEFAULT;
            uploadDesc.BindFlags        = D3D11_BIND_SHADER_RESOURCE;

            D3D11_SUBRESOURCE_DATA uploadData = {};
            uploadData.pSysMem     = mapped.pData;
            uploadData.SysMemPitch = mapped.RowPitch;

            ID3D11Texture2D* uploadTex = nullptr;
            hr = dstDevice->CreateTexture2D(&uploadDesc, &uploadData, &uploadTex);
            display.context->Unmap(stagingTex, 0);
            stagingTex->Release();

            if (FAILED(hr)) {
                if (acquiredNewFrame) {
                    display.duplication->ReleaseFrame();
                    display.currentTexture->Release();
                    display.currentTexture   = nullptr;
                    display.hasAcquiredFrame = false;
                }
                return false;
            }

            dstContext->CopySubresourceRegion(dstTexture, 0, dstX, dstY, 0, uploadTex, 0, nullptr);
            uploadTex->Release();
        }
    }

    // 新帧：必须 ReleaseFrame 归还给 DXGI，但保留 currentTexture 指针供下次 TIMEOUT 复用
    if (acquiredNewFrame) {
        display.duplication->ReleaseFrame();
        // 注意：不 Release currentTexture，保留指针供下次 TIMEOUT 时复用
        display.hasAcquiredFrame = false;
    }
    return true;
}


UINT64 GPUDisplayCapture::CaptureDisplayRegion(
    int displayIndex, int x, int y, int width, int height,
    ID3D11Device*        mainDevice,
    ID3D11DeviceContext* mainContext,
    GPUResourcePool*     resourcePool,
    std::unordered_map<std::string, UINT64>& persistentResources,
    int mainGPUIndex,
    const char* tag) {

    if (!m_initialized || width <= 0 || height <= 0) return 0;
    if (!mainDevice || !mainContext || !resourcePool) return 0;

    if (displayIndex < 0 || displayIndex >= (int)m_displays.size()) return 0;
    const auto& baseBounds = m_displays[displayIndex].bounds;
    int globalX = baseBounds.left + x;
    int globalY = baseBounds.top  + y;

    std::string tagStr(tag ? tag : "");

    // ── 复用已有纹理（尺寸匹配时直接原地更新，不重新分配）──────────
    auto it = persistentResources.find(tagStr);
    if (it != persistentResources.end()) {
        UINT64 existingId = it->second;
        auto* res = resourcePool->GetResource(existingId);
        if (res && res->resource) {
            ID3D11Texture2D* tex = static_cast<ID3D11Texture2D*>(res->resource);
            D3D11_TEXTURE2D_DESC desc;
            tex->GetDesc(&desc);
            if ((int)desc.Width == width && (int)desc.Height == height) {
                // 尝试捕获新帧；失败时保留上一帧内容，直接复用（不 Clear）
                for (auto& display : m_displays) {
                    if (!display.duplication) continue;
                    CaptureOneDisplay(display, mainDevice, mainContext,
                                      globalX, globalY, width, height, tex);
                }
                return existingId;
            }
        }
        // 尺寸变了，移除旧的
        resourcePool->RemoveResource(existingId);
        persistentResources.erase(it);
    }

    // ── 首次或尺寸变化：新建纹理 ────────────────────────────────────
    D3D11_TEXTURE2D_DESC finalDesc = {};
    finalDesc.Width     = (UINT)width;
    finalDesc.Height    = (UINT)height;
    finalDesc.MipLevels = 1;
    finalDesc.ArraySize = 1;
    finalDesc.Format    = DXGI_FORMAT_B8G8R8A8_UNORM;
    finalDesc.SampleDesc.Count = 1;
    finalDesc.Usage     = D3D11_USAGE_DEFAULT;
    finalDesc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
    finalDesc.MiscFlags = D3D11_RESOURCE_MISC_SHARED;
    
    ID3D11Texture2D* finalTexture = nullptr;
    HRESULT hr = mainDevice->CreateTexture2D(&finalDesc, nullptr, &finalTexture);
    if (FAILED(hr)) return 0;

    // 尝试捕获第一帧；若 DXGI 暂无可用帧（新建 duplicator 尚未收到更新），清黑后仍注册资源
    bool firstFrameSuccess = false;
    for (auto& display : m_displays) {
        if (!display.duplication) continue;
        if (CaptureOneDisplay(display, mainDevice, mainContext,
                              globalX, globalY, width, height, finalTexture)) {
            firstFrameSuccess = true;
        }
    }
    // 首次若 DXGI 暂无可用帧（静态桌面 / 新建 duplicator），
    // 仍注册纹理（清为全黑）并立即返回，下帧走复用路径更新内容
    if (!firstFrameSuccess) {
        // 用渲染目标视图清黑
        D3D11_RENDER_TARGET_VIEW_DESC clearRtvDesc = {};
        clearRtvDesc.Format             = DXGI_FORMAT_B8G8R8A8_UNORM;
        clearRtvDesc.ViewDimension      = D3D11_RTV_DIMENSION_TEXTURE2D;
        clearRtvDesc.Texture2D.MipSlice = 0;
        ID3D11RenderTargetView* clearRtv = nullptr;
        if (SUCCEEDED(mainDevice->CreateRenderTargetView(finalTexture, &clearRtvDesc, &clearRtv))) {
            const float black[4] = {0.f, 0.f, 0.f, 0.f};
            mainContext->ClearRenderTargetView(clearRtv, black);
            clearRtv->Release();
        }
        // 继续注册，不返回 0
    }

    D3D11_SHADER_RESOURCE_VIEW_DESC srvDesc = {};
    srvDesc.Format                    = finalDesc.Format;
    srvDesc.ViewDimension             = D3D11_SRV_DIMENSION_TEXTURE2D;
    srvDesc.Texture2D.MipLevels       = 1;
    srvDesc.Texture2D.MostDetailedMip = 0;

    ID3D11ShaderResourceView* srv = nullptr;
    hr = mainDevice->CreateShaderResourceView(finalTexture, &srvDesc, &srv);
    if (FAILED(hr)) { finalTexture->Release(); return 0; }

    ID3D11RenderTargetView* rtv = nullptr;
    D3D11_RENDER_TARGET_VIEW_DESC rtvDesc = {};
    rtvDesc.Format             = finalDesc.Format;
    rtvDesc.ViewDimension      = D3D11_RTV_DIMENSION_TEXTURE2D;
    rtvDesc.Texture2D.MipSlice = 0;
    mainDevice->CreateRenderTargetView(finalTexture, &rtvDesc, &rtv);

    auto& pool = *resourcePool;

    UINT64 resourceId = pool.AddResource(finalTexture, GPUResourceType::Texture2D,
                                         srv, mainGPUIndex, tag);
    auto* res = pool.GetResource(resourceId);
    if (res) {
        res->device  = mainDevice;
        res->context = mainContext;
        if (rtv) res->rtv = rtv;
    } else {
        if (rtv) rtv->Release();
    }

    finalTexture->Release();
    srv->Release();

    if (!tagStr.empty()) {
        persistentResources[tagStr] = resourceId;
    }

    return resourceId;
}

void GPUDisplayCapture::ReleaseCurrentFrame(int displayIndex) {
    if (displayIndex < 0 || displayIndex >= (int)m_displays.size()) {
        return;
    }
    
    auto& display = m_displays[displayIndex];
    if (display.hasAcquiredFrame && display.duplication) {
        display.duplication->ReleaseFrame();
        if (display.currentTexture) {
            display.currentTexture->Release();
            display.currentTexture = nullptr;
        }
        display.hasAcquiredFrame = false;
    }
}

ID3D11Device* GPUDisplayCapture::GetDisplayDevice(int displayIndex) const {
    if (displayIndex < 0 || displayIndex >= (int)m_displays.size()) {
        return nullptr;
    }
    return m_displays[displayIndex].device;
}

ID3D11DeviceContext* GPUDisplayCapture::GetDisplayContext(int displayIndex) const {
    if (displayIndex < 0 || displayIndex >= (int)m_displays.size()) {
        return nullptr;
    }
    return m_displays[displayIndex].context;
}

std::string GPUDisplayCapture::GetDebugInfo() const {
    std::ostringstream oss;
    oss << "=== GPU Display Capture Info ===\n";
    oss << "Initialized: " << (m_initialized ? "Yes" : "No") << "\n";
    oss << "Display Count: " << m_displays.size() << "\n\n";
    
    for (size_t i = 0; i < m_displays.size(); i++) {
        const auto& display = m_displays[i];
        oss << "Display[" << i << "]:\n";
        oss << "  Bounds: (" << display.bounds.left << "," << display.bounds.top 
            << ") - (" << display.bounds.right << "," << display.bounds.bottom << ")\n";
        oss << "  Size: " << (display.bounds.right - display.bounds.left) 
            << "x" << (display.bounds.bottom - display.bounds.top) << "\n";
        oss << "  Device: " << display.device << "\n";
        oss << "  Duplication: " << (display.duplication ? "OK" : "Failed") << "\n";
        oss << "  Current Frame: " << (display.hasAcquiredFrame ? "Acquired" : "None") << "\n\n";
    }
    
    return oss.str();
}