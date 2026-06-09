/*
 * 文件名: gpu_swapchain_presenter.h
 * 功能: DXGI SwapChain 封装，将 D3D11 纹理直接 Present 到窗口
 *       无需 OpenGL 互操作，GPU 占用极低
 */

#pragma once
#include "gpu_types.h"
#include <dxgi1_2.h>
#include <dcomp.h>

// 前置声明
class GPUDeviceManager;
class GPUResourcePool;

struct SwapChainPresenter {
    HWND                    hwnd           = nullptr;
    IDXGISwapChain1*        swapChain      = nullptr;
    ID3D11Device*           device         = nullptr;
    ID3D11DeviceContext*    context        = nullptr;
    ID3D11RenderTargetView* backbufferRTV  = nullptr;
    ID3D11Texture2D*        backbufferTex  = nullptr;
    ID3D11ShaderResourceView* blitSRV      = nullptr;
    IDCompositionDevice*    dcompDevice    = nullptr;
    IDCompositionTarget*    dcompTarget    = nullptr;
    IDCompositionVisual*    dcompVisual    = nullptr;
    UINT                    width          = 0;
    UINT                    height         = 0;
    UINT64                  presenterId    = 0;
};

class GPUSwapChainPresenterManager {
public:
    GPUSwapChainPresenterManager() = default;
    ~GPUSwapChainPresenterManager();

    // 禁止拷贝
    GPUSwapChainPresenterManager(const GPUSwapChainPresenterManager&) = delete;
    GPUSwapChainPresenterManager& operator=(const GPUSwapChainPresenterManager&) = delete;

    // 设置依赖
    void SetDeviceManager(GPUDeviceManager* mgr) { deviceMgr = mgr; }
    void SetResourcePool(GPUResourcePool* pool)  { resourcePool = pool; }

    // 创建/销毁 Presenter（每个窗口一个）
    UINT64 CreatePresenter(HWND hwnd, UINT width, UINT height, int gpuIndex = -1);
    void   DestroyPresenter(UINT64 presenterId);

    // 将资源池中的纹理 blit 到 SwapChain 并 Present，syncInterval 可选（默认为 1，表示垂直同步）
    bool   PresentResource(UINT64 presenterId, UINT64 resourceId, UINT syncInterval = 1);

    // 窗口大小变化时调用
    bool   ResizePresenter(UINT64 presenterId, UINT width, UINT height);

private:
    bool RebuildBackbufferRTV(SwapChainPresenter* p);

    // 依赖注入
    GPUDeviceManager* deviceMgr   = nullptr;
    GPUResourcePool*  resourcePool = nullptr;

    std::map<UINT64, SwapChainPresenter*> m_presenters;
    UINT64 m_nextId = 1;
};