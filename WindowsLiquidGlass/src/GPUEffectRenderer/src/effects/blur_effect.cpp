/*
 * 文件名: blur_effect.cpp
 * 功能: 可分离高斯模糊 - 横向+纵向两pass实现
 */

#include "blur_effect.h"
#include <d3dcompiler.h>
#include <Windows.h>
#include <fstream>
#include <vector>

#pragma comment(lib, "d3dcompiler.lib")

static std::wstring GetDLLDirectory() {
    wchar_t path[MAX_PATH];
    HMODULE hm = NULL;
    if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCWSTR)&GetDLLDirectory, &hm)) {
        GetModuleFileNameW(hm, path, sizeof(path) / sizeof(wchar_t));
        std::wstring fullPath(path);
        size_t pos = fullPath.find_last_of(L"\\/");
        return pos != std::wstring::npos ? fullPath.substr(0, pos + 1) : L"";
    }
    return L"";
}

static HRESULT LoadPSFromCSO(ID3D11Device* device, const std::wstring& path, ID3D11PixelShader** outPS) {
    std::ifstream file(path, std::ios::binary);
    if (!file.is_open()) return E_FAIL;
    std::vector<char> data((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    return device->CreatePixelShader(data.data(), data.size(), nullptr, outPS);
}

BlurEffect::BlurEffect()
    : pixelShaderHorz_(nullptr), pixelShaderVert_(nullptr)
    , constantBuffer_(nullptr)
    , intermediateTexture_(nullptr), intermediateSRV_(nullptr), intermediateRTV_(nullptr)
    , cachedWidth_(0), cachedHeight_(0)
    , device_(nullptr) {
}

BlurEffect::~BlurEffect() {
    Shutdown();
}

bool BlurEffect::Initialize(ID3D11Device* device) {
    if (!device) { return false; }
    device_ = device;

    std::wstring dllDir = GetDLLDirectory();
    HRESULT hr;

    // 1. 横向 Pixel Shader
    hr = LoadPSFromCSO(device, dllDir + L"blur_effect_horz_ps.cso", &pixelShaderHorz_);
    if (FAILED(hr)) { return false; }

    // 2. 纵向 Pixel Shader
    hr = LoadPSFromCSO(device, dllDir + L"blur_effect_vert_ps.cso", &pixelShaderVert_);
    if (FAILED(hr)) { return false; }

    // 3. 全屏三角形 Vertex Shader
    const char* vsCode = R"(
        struct VSOutput { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
        VSOutput VSMain(uint id : SV_VertexID) {
            VSOutput o;
            o.uv  = float2((id << 1) & 2, id & 2);
            o.pos = float4(o.uv * float2(2, -2) + float2(-1, 1), 0, 1);
            return o;
        }
    )";
    ID3DBlob* vsBlob = nullptr; ID3DBlob* vsErr = nullptr;
    hr = D3DCompile(vsCode, strlen(vsCode), nullptr, nullptr, nullptr, "VSMain", "vs_5_0", 0, 0, &vsBlob, &vsErr);
    if (FAILED(hr)) {
        if (vsErr) { vsErr->Release(); }
        return false;
    }
    hr = device->CreateVertexShader(vsBlob->GetBufferPointer(), vsBlob->GetBufferSize(), nullptr, &vertexShader);
    vsBlob->Release();
    if (FAILED(hr)) { return false; }

    // 4. 常量缓冲区 (64 bytes)
    D3D11_BUFFER_DESC cbDesc = {};
    cbDesc.Usage = D3D11_USAGE_DYNAMIC; cbDesc.ByteWidth = 64;
    cbDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER; cbDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    hr = device->CreateBuffer(&cbDesc, nullptr, &constantBuffer_);
    if (FAILED(hr)) { return false; }

    // 5. 采样器
    D3D11_SAMPLER_DESC sampDesc = {};
    sampDesc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sampDesc.AddressU = sampDesc.AddressV = sampDesc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.ComparisonFunc = D3D11_COMPARISON_NEVER; sampDesc.MaxLOD = D3D11_FLOAT32_MAX;
    hr = device->CreateSamplerState(&sampDesc, &sampler);
    if (FAILED(hr)) { return false; }

    return true;
}

bool BlurEffect::EnsureIntermediateTexture(UINT width, UINT height) {
    if (cachedWidth_ == width && cachedHeight_ == height &&
        intermediateTexture_ && intermediateSRV_ && intermediateRTV_) {
        return true;
    }

    if (intermediateRTV_)     { intermediateRTV_->Release();     intermediateRTV_     = nullptr; }
    if (intermediateSRV_)     { intermediateSRV_->Release();     intermediateSRV_     = nullptr; }
    if (intermediateTexture_) { intermediateTexture_->Release(); intermediateTexture_ = nullptr; }

    D3D11_TEXTURE2D_DESC desc = {};
    desc.Width = width; desc.Height = height;
    desc.MipLevels = 1; desc.ArraySize = 1;
    desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1; desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;

    HRESULT hr = device_->CreateTexture2D(&desc, nullptr, &intermediateTexture_);
    if (FAILED(hr)) { return false; }

    hr = device_->CreateRenderTargetView(intermediateTexture_, nullptr, &intermediateRTV_);
    if (FAILED(hr)) { return false; }

    hr = device_->CreateShaderResourceView(intermediateTexture_, nullptr, &intermediateSRV_);
    if (FAILED(hr)) { return false; }

    cachedWidth_ = width; cachedHeight_ = height;
    return true;
}

void BlurEffect::Shutdown() {
    if (intermediateRTV_)     { intermediateRTV_->Release();     intermediateRTV_     = nullptr; }
    if (intermediateSRV_)     { intermediateSRV_->Release();     intermediateSRV_     = nullptr; }
    if (intermediateTexture_) { intermediateTexture_->Release(); intermediateTexture_ = nullptr; }
    if (pixelShaderHorz_)     { pixelShaderHorz_->Release();     pixelShaderHorz_     = nullptr; }
    if (pixelShaderVert_)     { pixelShaderVert_->Release();     pixelShaderVert_     = nullptr; }
    if (constantBuffer_)      { constantBuffer_->Release();      constantBuffer_      = nullptr; }
    if (vertexShader)         { vertexShader->Release();         vertexShader         = nullptr; }
    if (sampler)              { sampler->Release();              sampler              = nullptr; }
    device_ = nullptr;
}

bool BlurEffect::Apply(
    ID3D11DeviceContext* context,
    ID3D11ShaderResourceView* inputTexture,
    ID3D11ShaderResourceView* sdfTexture,
    ID3D11RenderTargetView* outputRTV,
    const void* params
) {
    if (!context || !pixelShaderHorz_ || !pixelShaderVert_ || !constantBuffer_) {
        return false;
    }

    // 获取输入纹理尺寸
    ID3D11Resource* res = nullptr;
    inputTexture->GetResource(&res);
    D3D11_TEXTURE2D_DESC texDesc;
    static_cast<ID3D11Texture2D*>(res)->GetDesc(&texDesc);
    res->Release();

    if (!EnsureIntermediateTexture(texDesc.Width, texDesc.Height)) return false;

    // 更新常量缓冲区
    D3D11_MAPPED_SUBRESOURCE mapped;
    HRESULT hr = context->Map(constantBuffer_, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
    if (FAILED(hr)) { return false; }
    memcpy(mapped.pData, params, sizeof(BlurEffectParams));
    context->Unmap(constantBuffer_, 0);

    // 公共状态
    context->VSSetShader(vertexShader, nullptr, 0);
    context->PSSetConstantBuffers(0, 1, &constantBuffer_);
    context->PSSetSamplers(0, 1, &sampler);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->IASetInputLayout(nullptr);

    ID3D11ShaderResourceView* nullSRVs[3] = { nullptr, nullptr, nullptr };

    // ============================================================
    // Pass 1: 横向模糊 — inputTexture → intermediateTexture
    // ============================================================
    context->OMSetRenderTargets(1, &intermediateRTV_, nullptr);
    context->PSSetShader(pixelShaderHorz_, nullptr, 0);
    context->PSSetShaderResources(0, 1, &inputTexture);
    context->Draw(3, 0);
    context->PSSetShaderResources(0, 3, nullSRVs);

    // ============================================================
    // Pass 2: 纵向模糊 + SDF遮罩 — intermediateTexture → outputRTV
    //   t0 = 横向模糊结果, t1 = SDF, t2 = 原始输入（SDF外部还原）
    // ============================================================
    context->OMSetRenderTargets(1, &outputRTV, nullptr);
    context->PSSetShader(pixelShaderVert_, nullptr, 0);
    ID3D11ShaderResourceView* srvPass2[3] = { intermediateSRV_, sdfTexture, inputTexture };
    context->PSSetShaderResources(0, 3, srvPass2);
    context->Draw(3, 0);
    context->PSSetShaderResources(0, 3, nullSRVs);

    return true;
}

#include "../gpu_effect_registry.h"
#include <cstring>

size_t BlurEffect::ParamsSize() const { return sizeof(BlurEffectParams); }

void BlurEffect::BuildParams(const ParamMap& params, float texW, float texH,
    float posX, float posY, void* outBuf, size_t bufSize) const {
    if (bufSize < sizeof(BlurEffectParams)) return;
    auto fget = [&](const char* k, float def) -> float {
        auto it = params.find(k); return it != params.end() ? it->second : def;
    };
    BlurEffectParams p;
    p.texWidth = texW; p.texHeight = texH;
    p.posX = posX; p.posY = posY; p.scaleX = 1.0f; p.scaleY = 1.0f;
    p.blurRadius = fget("radius", p.blurRadius);
    memcpy(outBuf, &p, sizeof(BlurEffectParams));
}

REGISTER_EFFECT(GPUEffectType::Blur, BlurEffect, 30)