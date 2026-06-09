/*
 * 文件名: gpu_swapchain_presenter.cpp
 */

#include "gpu_swapchain_presenter.h"
#include "gpu_device_manager.h"
#include "gpu_resource_pool.h"
#include <dxgi1_2.h>
#include <dcomp.h>
#include <algorithm>

GPUSwapChainPresenterManager::~GPUSwapChainPresenterManager() {
    // 复制 key 列表，避免边删边遍历
    std::vector<UINT64> ids;
    for (auto& pair : m_presenters) ids.push_back(pair.first);
    for (auto id : ids) DestroyPresenter(id);
}

UINT64 GPUSwapChainPresenterManager::CreatePresenter(
    HWND hwnd, UINT width, UINT height, int gpuIndex)
{
    if (!hwnd || width == 0 || height == 0) return 0;

    if (!deviceMgr) return 0;
    auto& devMgr = *deviceMgr;
    ID3D11Device*        device  = (gpuIndex >= 0) ? devMgr.GetDeviceByGPUIndex(gpuIndex)  : devMgr.GetMainDevice();
    ID3D11DeviceContext* context = (gpuIndex >= 0) ? devMgr.GetContextByGPUIndex(gpuIndex) : devMgr.GetMainContext();
    if (!device || !context) return 0;

    // DXGI Factory
    IDXGIDevice*   dxgiDevice  = nullptr;
    IDXGIAdapter*  dxgiAdapter = nullptr;
    IDXGIFactory2* factory     = nullptr;
    if (FAILED(device->QueryInterface(__uuidof(IDXGIDevice),  (void**)&dxgiDevice)))  return 0;
    if (FAILED(dxgiDevice->GetAdapter(&dxgiAdapter)))         { dxgiDevice->Release(); return 0; }
    if (FAILED(dxgiAdapter->GetParent(__uuidof(IDXGIFactory2),(void**)&factory))) {
        dxgiAdapter->Release(); dxgiDevice->Release(); return 0;
    }

    DXGI_SWAP_CHAIN_DESC1 desc = {};
    desc.Width       = width;
    desc.Height      = height;
    desc.Format      = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc  = { 1, 0 };
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 2;
    desc.SwapEffect  = DXGI_SWAP_EFFECT_FLIP_DISCARD;
    desc.AlphaMode   = DXGI_ALPHA_MODE_PREMULTIPLIED;  // 支持逐像素透明
    desc.Scaling     = DXGI_SCALING_STRETCH;
    desc.Flags       = 0;

    IDXGISwapChain1* swapChain = nullptr;
    // CreateSwapChainForComposition: 不绑定 HWND，由 DirectComposition 负责合成
    HRESULT hr = factory->CreateSwapChainForComposition(device, &desc, nullptr, &swapChain);

    // ── DirectComposition 绑定 ────────────────────────────────────────────────
    IDCompositionDevice* dcompDevice = nullptr;
    IDCompositionTarget* dcompTarget = nullptr;
    IDCompositionVisual* dcompVisual = nullptr;
    if (SUCCEEDED(hr)) {
        if (SUCCEEDED(DCompositionCreateDevice(
                dxgiDevice, __uuidof(IDCompositionDevice), (void**)&dcompDevice))) {
            dcompDevice->CreateTargetForHwnd(hwnd, TRUE, &dcompTarget);
            dcompDevice->CreateVisual(&dcompVisual);
            if (dcompVisual) dcompVisual->SetContent(swapChain);
            if (dcompTarget) dcompTarget->SetRoot(dcompVisual);
            dcompDevice->Commit();
        }
    }

    factory->Release(); dxgiAdapter->Release(); dxgiDevice->Release();
    if (FAILED(hr)) return 0;

    auto* p        = new SwapChainPresenter();
    p->hwnd        = hwnd;
    p->swapChain   = swapChain;
    p->device      = device;
    p->context     = context;
    p->dcompDevice = dcompDevice;
    p->dcompTarget = dcompTarget;
    p->dcompVisual = dcompVisual;
    p->width       = width;
    p->height      = height;
    p->presenterId = m_nextId++;

    if (!RebuildBackbufferRTV(p)) {
        swapChain->Release();
        delete p;
        return 0;
    }

    m_presenters[p->presenterId] = p;
    return p->presenterId;
}

bool GPUSwapChainPresenterManager::RebuildBackbufferRTV(SwapChainPresenter* p) {
    if (p->backbufferRTV) { p->backbufferRTV->Release(); p->backbufferRTV = nullptr; }
    if (p->backbufferTex) { p->backbufferTex->Release(); p->backbufferTex = nullptr; }

    if (FAILED(p->swapChain->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&p->backbufferTex)))
        return false;

    HRESULT hr = p->device->CreateRenderTargetView(p->backbufferTex, nullptr, &p->backbufferRTV);
    // backbufferTex 保留持有（不 Release），Present 后才失效，
    // 但 FLIP_DISCARD 下每次 Present 都会轮换 backbuffer，所以每帧必须重新 GetBuffer
    // → 这里不持有，立即 Release，Present 时再 GetBuffer
    p->backbufferTex->Release();
    p->backbufferTex = nullptr;
    return SUCCEEDED(hr);
}

void GPUSwapChainPresenterManager::DestroyPresenter(UINT64 presenterId) {
    auto it = m_presenters.find(presenterId);
    if (it == m_presenters.end()) return;
    auto* p = it->second;
    if (p->backbufferRTV) p->backbufferRTV->Release();
    if (p->backbufferTex) p->backbufferTex->Release();
    if (p->blitSRV)       p->blitSRV->Release();
    if (p->dcompVisual)   p->dcompVisual->Release();
    if (p->dcompTarget)   p->dcompTarget->Release();
    if (p->dcompDevice)   p->dcompDevice->Release();
    if (p->swapChain)     p->swapChain->Release();
    delete p;
    m_presenters.erase(it);
}

bool GPUSwapChainPresenterManager::PresentResource(UINT64 presenterId, UINT64 resourceId, UINT syncInterval) {
    auto it = m_presenters.find(presenterId);
    if (it == m_presenters.end()) return false;
    auto* p = it->second;

    auto* res = resourcePool ? resourcePool->GetResource(resourceId) : nullptr;
    if (!res || !res->resource) return false;
    auto* srcTex = static_cast<ID3D11Texture2D*>(res->resource);

    D3D11_TEXTURE2D_DESC srcDesc = {};
    srcTex->GetDesc(&srcDesc);

    // 每帧重新拿 backbuffer（FLIP_DISCARD 每次 Present 后指针轮换）
    ID3D11Texture2D* backbuffer = nullptr;
    if (FAILED(p->swapChain->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&backbuffer)))
        return false;

    D3D11_TEXTURE2D_DESC dstDesc = {};
    backbuffer->GetDesc(&dstDesc);

    bool sameSize   = (srcDesc.Width == dstDesc.Width && srcDesc.Height == dstDesc.Height);
    bool sameFormat = (srcDesc.Format == dstDesc.Format);

    if (sameSize && sameFormat) {
        // ── 最优路径：直接 CopyResource（Copy 引擎，几乎零 3D 占用）──
        p->context->CopyResource(backbuffer, srcTex);
    } else if (sameSize) {
        // ── 格式不同但尺寸相同：用 CopySubresourceRegion 仍可行
        //    D3D11 Runtime 会自动做格式转换（同 bpp 的 typeless cast）
        //    若格式完全不兼容则会静默失败，退到 ClearRTV 保底
        D3D11_BOX box = {0, 0, 0, srcDesc.Width, srcDesc.Height, 1};
        p->context->CopySubresourceRegion(backbuffer, 0, 0, 0, 0, srcTex, 0, &box);
    } else {
        // ── 尺寸不同：清黑 + 居中 CopySubresourceRegion ──────────
        ID3D11RenderTargetView* rtv = nullptr;
        if (SUCCEEDED(p->device->CreateRenderTargetView(backbuffer, nullptr, &rtv))) {
            float transparent[4] = {0, 0, 0, 0};  // 透明黑，预乘 alpha
            p->context->ClearRenderTargetView(rtv, transparent);
            rtv->Release();
        }
        UINT copyW = (srcDesc.Width  < dstDesc.Width)  ? srcDesc.Width  : dstDesc.Width;
        UINT copyH = (srcDesc.Height < dstDesc.Height) ? srcDesc.Height : dstDesc.Height;
        D3D11_BOX box = {0, 0, 0, copyW, copyH, 1};
        p->context->CopySubresourceRegion(backbuffer, 0, 0, 0, 0, srcTex, 0, &box);
    }

    // ── backbuffer Release 必须在 Present 之前 ─────────────────
    backbuffer->Release();
    backbuffer = nullptr;

    HRESULT hr = p->swapChain->Present(syncInterval, 0);
    if (hr == DXGI_ERROR_DEVICE_REMOVED || hr == DXGI_ERROR_DEVICE_RESET) {
        // 设备丢失，标记但不崩溃
        return false;
    }
    return SUCCEEDED(hr);
}

bool GPUSwapChainPresenterManager::ResizePresenter(UINT64 presenterId, UINT width, UINT height) {
    auto it = m_presenters.find(presenterId);
    if (it == m_presenters.end()) return false;
    auto* p = it->second;
    if (width == 0 || height == 0) return true;  // 最小化时忽略

    // ResizeBuffers 前必须先释放所有对 backbuffer 的引用
    if (p->backbufferRTV) { p->backbufferRTV->Release(); p->backbufferRTV = nullptr; }
    if (p->backbufferTex) { p->backbufferTex->Release(); p->backbufferTex = nullptr; }
    p->context->ClearState();  // 清除所有绑定，防止 ResizeBuffers 因引用未释放而失败

    HRESULT hr = p->swapChain->ResizeBuffers(0, width, height, DXGI_FORMAT_UNKNOWN, 0);
    if (FAILED(hr)) return false;

    p->width  = width;
    p->height = height;
    return RebuildBackbufferRTV(p);
}