#include "color_grading_effect.h"
#include "../gpu_effect_types.h"
#include <d3dcompiler.h>
#include <fstream>
#include <vector>
#include <windows.h>
#include <stdio.h>

#pragma comment(lib, "d3dcompiler.lib")

static std::wstring GetColorGradingDLLDirectory() {
    wchar_t path[MAX_PATH];
    HMODULE hModule = NULL;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCWSTR)&GetColorGradingDLLDirectory,
        &hModule
    );
    GetModuleFileNameW(hModule, path, MAX_PATH);
    std::wstring fullPath(path);
    size_t lastSlash = fullPath.find_last_of(L"\\/");
    if (lastSlash != std::wstring::npos)
        return fullPath.substr(0, lastSlash + 1);
    return L"";
}

bool ColorGradingEffect::Initialize(ID3D11Device* device) {
    if (!device) return false;
    if (!LoadShaders(device))          return false;
    if (!CreateConstantBuffer(device)) return false;
    if (!CreateSamplerState(device))   return false;
    return true;
}

bool ColorGradingEffect::LoadShaders(ID3D11Device* device) {
    HRESULT hr;
    std::wstring dllDir = GetColorGradingDLLDirectory();

    // --- Pixel Shader: 尝试从 .cso 加载 ---
    std::wstring csoPath = dllDir + L"color_grading_effect_ps.cso";
    std::ifstream psFile(csoPath, std::ios::binary);
    if (psFile.is_open()) {
        std::vector<char> psData((std::istreambuf_iterator<char>(psFile)),
                                  std::istreambuf_iterator<char>());
        psFile.close();
        hr = device->CreatePixelShader(psData.data(), psData.size(), nullptr, &pixelShader);
        if (FAILED(hr)) { return false; }
    } else {
        // 回退：运行时编译 HLSL
        std::vector<std::wstring> hlslPaths = {
            dllDir + L"..\\src\\effects\\color_grading_effect.hlsl",
            L"src\\effects\\color_grading_effect.hlsl",
            L"GPUEffectRenderer\\src\\effects\\color_grading_effect.hlsl"
        };
        ID3DBlob* psBlob    = nullptr;
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

    // --- Vertex Shader: 内联全屏三角形 ---
    const char* vsCode = R"(
        struct VSOutput { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
        VSOutput VSMain(uint id : SV_VertexID) {
            VSOutput o;
            o.uv  = float2((id << 1) & 2, id & 2);
            o.pos = float4(o.uv * float2(2, -2) + float2(-1, 1), 0, 1);
            return o;
        }
    )";
    ID3DBlob* vsBlob     = nullptr;
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

bool ColorGradingEffect::CreateConstantBuffer(ID3D11Device* device) {
    D3D11_BUFFER_DESC cbDesc = {};
    cbDesc.ByteWidth      = sizeof(ColorGradingParams);
    cbDesc.Usage          = D3D11_USAGE_DYNAMIC;
    cbDesc.BindFlags      = D3D11_BIND_CONSTANT_BUFFER;
    cbDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    HRESULT hr = device->CreateBuffer(&cbDesc, nullptr, &constantBuffer);
    if (FAILED(hr)) { return false; }
    return true;
}

bool ColorGradingEffect::CreateSamplerState(ID3D11Device* device) {
    D3D11_SAMPLER_DESC sampDesc = {};
    sampDesc.Filter         = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sampDesc.AddressU       = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.AddressV       = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.AddressW       = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.ComparisonFunc = D3D11_COMPARISON_NEVER;
    sampDesc.MinLOD         = 0;
    sampDesc.MaxLOD         = D3D11_FLOAT32_MAX;
    HRESULT hr = device->CreateSamplerState(&sampDesc, &sampler);
    if (FAILED(hr)) { return false; }
    return true;
}

bool ColorGradingEffect::Apply(
    ID3D11DeviceContext* context,
    ID3D11ShaderResourceView* inputTexture,
    ID3D11ShaderResourceView* sdfTexture,
    ID3D11RenderTargetView* outputRTV,
    const void* params)
{
    if (!context || !inputTexture || !outputRTV || !params) return false;

    // 更新常量缓冲区
    D3D11_MAPPED_SUBRESOURCE mapped;
    HRESULT hr = context->Map(constantBuffer, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
    if (SUCCEEDED(hr)) {
        memcpy(mapped.pData, params, sizeof(ColorGradingParams));
        context->Unmap(constantBuffer, 0);
    }

    // 渲染管线设置
    context->OMSetRenderTargets(1, &outputRTV, nullptr);
    context->VSSetShader(vertexShader, nullptr, 0);
    context->PSSetShader(pixelShader, nullptr, 0);
    context->PSSetConstantBuffers(0, 1, &constantBuffer);
    // 绑定 inputTexture(t0) 和 sdfTexture(t1)
    ID3D11ShaderResourceView* srvs[2] = { inputTexture, sdfTexture };
    context->PSSetShaderResources(0, 2, srvs);
    context->PSSetSamplers(0, 1, &sampler);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->IASetInputLayout(nullptr);

    context->Draw(3, 0);

    // 解绑
    ID3D11ShaderResourceView* nullSRVs[2] = { nullptr, nullptr };
    context->PSSetShaderResources(0, 2, nullSRVs);
    ID3D11RenderTargetView* nullRTV = nullptr;
    context->OMSetRenderTargets(1, &nullRTV, nullptr);

    return true;
}

void ColorGradingEffect::Shutdown() {
    SafeRelease(vertexShader);
    SafeRelease(pixelShader);
    SafeRelease(constantBuffer);
    SafeRelease(sampler);
}

#include "../gpu_effect_registry.h"
#include <cstring>

size_t ColorGradingEffect::ParamsSize() const { return sizeof(ColorGradingParams); }

void ColorGradingEffect::BuildParams(const ParamMap& params, float texW, float texH,
    float posX, float posY, void* outBuf, size_t bufSize) const {
    if (bufSize < sizeof(ColorGradingParams)) return;
    auto fget = [&](const char* k, float def) -> float {
        auto it = params.find(k); return it != params.end() ? it->second : def;
    };
    ColorGradingParams p;
    p.texWidth = texW; p.texHeight = texH;
    p.posX = posX; p.posY = posY;
    p.brightness = fget("brightness", p.brightness);
    p.contrast   = fget("contrast",   p.contrast);
    p.saturation = fget("saturation", p.saturation);
    p.hueShift   = fget("hue_shift",  p.hueShift);
    p.exposure   = fget("exposure",   p.exposure);
    p.gamma      = fget("gamma",      p.gamma);
    p.temperature = fget("temperature", p.temperature);
    p.highlights = fget("highlights", p.highlights);
    p.shadows    = fget("shadows",    p.shadows);
    p.vibrance   = fget("vibrance",   p.vibrance);
    p.fadeout    = fget("fadeout",    p.fadeout);
    p.vignetteStrength = fget("vignette_strength", p.vignetteStrength);
    p.vignetteRadius   = fget("vignette_radius",   p.vignetteRadius);
    p.vignetteSoftness = fget("vignette_softness", p.vignetteSoftness);
    p.shadowR    = fget("shadow_color_r", p.shadowR);
    p.shadowG    = fget("shadow_color_g", p.shadowG);
    p.shadowB    = fget("shadow_color_b", p.shadowB);
    p.midtoneR   = fget("midtone_color_r", p.midtoneR);
    p.midtoneG   = fget("midtone_color_g", p.midtoneG);
    p.midtoneB   = fget("midtone_color_b", p.midtoneB);
    p.highlightR = fget("highlight_color_r", p.highlightR);
    p.highlightG = fget("highlight_color_g", p.highlightG);
    p.highlightB = fget("highlight_color_b", p.highlightB);
    memcpy(outBuf, &p, sizeof(ColorGradingParams));
}

REGISTER_EFFECT(GPUEffectType::ColorGrading, ColorGradingEffect, 60)