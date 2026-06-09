#include "highlight_effect.h"
#include "../gpu_effect_types.h"
#include <d3dcompiler.h>
#include <fstream>
#include <vector>
#include <windows.h>
#include <stdio.h>

#pragma comment(lib, "d3dcompiler.lib")

static std::wstring GetHighlightDLLDirectory() {
    wchar_t path[MAX_PATH];
    HMODULE hModule = NULL;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCWSTR)&GetHighlightDLLDirectory,
        &hModule
    );
    GetModuleFileNameW(hModule, path, MAX_PATH);
    std::wstring fullPath(path);
    size_t lastSlash = fullPath.find_last_of(L"\\/");
    if (lastSlash != std::wstring::npos)
        return fullPath.substr(0, lastSlash + 1);
    return L"";
}

bool HighlightEffect::Initialize(ID3D11Device* device) {
    if (!device) { return false; }
    if (!LoadShaders(device))      { return false; }
    if (!CreateConstantBuffer(device)) { return false; }
    if (!CreateSamplerState(device))   { return false; }
    return true;
}

bool HighlightEffect::LoadShaders(ID3D11Device* device) {
    HRESULT hr;
    std::wstring dllDir = GetHighlightDLLDirectory();

    // --- Pixel Shader: 尝试从 .cso 加载 ---
    std::wstring csoPath = dllDir + L"highlight_effect_ps.cso";
    std::ifstream psFile(csoPath, std::ios::binary);
    if (psFile.is_open()) {
        std::vector<char> psData((std::istreambuf_iterator<char>(psFile)),
                                  std::istreambuf_iterator<char>());
        psFile.close();
        hr = device->CreatePixelShader(psData.data(), psData.size(), nullptr, &pixelShader);
        if (FAILED(hr)) { return false; }
    } else {
        // 回退：运行时编译
        std::vector<std::wstring> hlslPaths = {
            dllDir + L"..\\src\\effects\\highlight_effect.hlsl",
            L"src\\effects\\highlight_effect.hlsl",
            L"GPUEffectRenderer\\src\\effects\\highlight_effect.hlsl"
        };
        ID3DBlob* psBlob = nullptr;
        ID3DBlob* errorBlob = nullptr;
        bool compiled = false;
        for (const auto& p : hlslPaths) {
            hr = D3DCompileFromFile(p.c_str(), nullptr, D3D_COMPILE_STANDARD_FILE_INCLUDE,
                "PSMain", "ps_5_0", D3DCOMPILE_ENABLE_STRICTNESS, 0, &psBlob, &errorBlob);
            if (SUCCEEDED(hr)) { compiled = true; break; }
            if (errorBlob) { errorBlob->Release(); errorBlob = nullptr; }
        }
        if (!compiled) { return false; }
        hr = device->CreatePixelShader(psBlob->GetBufferPointer(), psBlob->GetBufferSize(), nullptr, &pixelShader);
        psBlob->Release();
        if (FAILED(hr)) { return false; }
    }

    // --- Vertex Shader: 内联编译全屏三角形 ---
    const char* vsCode = R"(
        struct VSOutput { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
        VSOutput VSMain(uint id : SV_VertexID) {
            VSOutput o;
            o.uv = float2((id << 1) & 2, id & 2);
            o.pos = float4(o.uv * float2(2, -2) + float2(-1, 1), 0, 1);
            return o;
        }
    )";
    ID3DBlob* vsBlob = nullptr;
    ID3DBlob* vsErrorBlob = nullptr;
    hr = D3DCompile(vsCode, strlen(vsCode), nullptr, nullptr, nullptr,
                    "VSMain", "vs_5_0", 0, 0, &vsBlob, &vsErrorBlob);
    if (FAILED(hr)) {
        if (vsErrorBlob) { vsErrorBlob->Release(); }
        return false;
    }
    hr = device->CreateVertexShader(vsBlob->GetBufferPointer(), vsBlob->GetBufferSize(), nullptr, &vertexShader);
    vsBlob->Release();
    if (FAILED(hr)) { return false; }
    return true;
}

bool HighlightEffect::CreateConstantBuffer(ID3D11Device* device) {
    D3D11_BUFFER_DESC cbDesc = {};
    cbDesc.ByteWidth = sizeof(HighlightEffectParams);
    cbDesc.Usage = D3D11_USAGE_DYNAMIC;
    cbDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    cbDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    HRESULT hr = device->CreateBuffer(&cbDesc, nullptr, &constantBuffer);
    if (FAILED(hr)) { return false; }
    return true;
}

bool HighlightEffect::CreateSamplerState(ID3D11Device* device) {
    D3D11_SAMPLER_DESC sampDesc = {};
    sampDesc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sampDesc.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.ComparisonFunc = D3D11_COMPARISON_NEVER;
    sampDesc.MinLOD = 0;
    sampDesc.MaxLOD = D3D11_FLOAT32_MAX;
    HRESULT hr = device->CreateSamplerState(&sampDesc, &sampler);
    if (FAILED(hr)) { return false; }
    return true;
}

bool HighlightEffect::Apply(
    ID3D11DeviceContext* context,
    ID3D11ShaderResourceView* inputTexture,
    ID3D11ShaderResourceView* sdfTexture,
    ID3D11RenderTargetView* outputRTV,
    const void* params)
{
    if (!context || !inputTexture || !sdfTexture || !outputRTV || !params) return false;

    // 更新常量缓冲区
    D3D11_MAPPED_SUBRESOURCE mapped;
    HRESULT hr = context->Map(constantBuffer, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
    if (SUCCEEDED(hr)) {
        memcpy(mapped.pData, params, sizeof(HighlightEffectParams));
        context->Unmap(constantBuffer, 0);
    }

    // 渲染管线设置
    context->OMSetRenderTargets(1, &outputRTV, nullptr);
    context->VSSetShader(vertexShader, nullptr, 0);
    context->PSSetShader(pixelShader, nullptr, 0);
    context->PSSetConstantBuffers(0, 1, &constantBuffer);
    ID3D11ShaderResourceView* srvs[2] = { inputTexture, sdfTexture };
    context->PSSetShaderResources(0, 2, srvs);
    context->PSSetSamplers(0, 1, &sampler);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->IASetInputLayout(nullptr);

    context->Draw(3, 0);

    // 解绑
    ID3D11ShaderResourceView* nullSRVs[2] = { nullptr, nullptr };
    context->PSSetShaderResources(0, 2, nullSRVs);
    return true;
}

void HighlightEffect::Shutdown() {
    SafeRelease(pixelShader);
    SafeRelease(vertexShader);
    SafeRelease(constantBuffer);
    SafeRelease(sampler);
}


#include "../gpu_effect_registry.h"
#include <cstring>
#include <cmath>

size_t HighlightEffect::ParamsSize() const { return sizeof(HighlightEffectParams); }

void HighlightEffect::BuildParams(const ParamMap& params, float texW, float texH,
    float posX, float posY, void* outBuf, size_t bufSize) const {
    if (bufSize < sizeof(HighlightEffectParams)) return;
    auto fget = [&](const char* k, float def) -> float {
        auto it = params.find(k); return it != params.end() ? it->second : def;
    };
    HighlightEffectParams p;
    p.texWidth  = texW; p.texHeight = texH;
    p.posX = posX; p.posY = posY; p.scaleX = 1.0f; p.scaleY = 1.0f;
    p.highlightWidth    = fget("width",    p.highlightWidth);
    // angle 传入度数，转换为弧度
    float angleDeg = fget("angle", p.highlightAngle * (180.0f / 3.14159265f));
    p.highlightAngle    = angleDeg * (3.14159265f / 180.0f);
    p.highlightSize     = fget("strength", p.highlightSize);
    p.highlightRange    = fget("range",    p.highlightRange);
    p.highlightMode     = static_cast<int>(fget("mode",     static_cast<float>(p.highlightMode)));
    p.highlightDiagonal = static_cast<int>(fget("diagonal", static_cast<float>(p.highlightDiagonal)));
    memcpy(outBuf, &p, sizeof(HighlightEffectParams));
}

REGISTER_EFFECT(GPUEffectType::Highlight, HighlightEffect, 40)