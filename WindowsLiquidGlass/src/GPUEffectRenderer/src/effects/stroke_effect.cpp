/*
 * 文件名: stroke_effect.cpp
 * 功能: 边框特效实现
 */

#include "stroke_effect.h"
#include <d3dcompiler.h>
#include <fstream>
#include <vector>
#include <windows.h>
#include <stdio.h>

#pragma comment(lib, "d3dcompiler.lib")

// ============================================================
//  辅助函数：获取DLL所在目录
// ============================================================

static std::wstring GetDLLDirectory() {
    wchar_t path[MAX_PATH];
    HMODULE hModule = NULL;
    
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCWSTR)&GetDLLDirectory,
        &hModule
    );
    
    GetModuleFileNameW(hModule, path, MAX_PATH);
    
    std::wstring fullPath(path);
    size_t lastSlash = fullPath.find_last_of(L"\\/");
    if (lastSlash != std::wstring::npos) {
        return fullPath.substr(0, lastSlash + 1);
    }
    return L"";
}

// ============================================================
//  初始化
// ============================================================

bool StrokeEffect::Initialize(ID3D11Device* device) {
    if (!device) {
        return false;
    }
    
    if (!LoadShaders(device)) {
        return false;
    }
    
    if (!CreateConstantBuffer(device)) {
        return false;
    }
    
    if (!CreateSamplerState(device)) {
        return false;
    }
    return true;
}

// ============================================================
//  加载Shader
// ============================================================

bool StrokeEffect::LoadShaders(ID3D11Device* device) {
    HRESULT hr;
    
    // 获取DLL所在目录
    std::wstring dllDir = GetDLLDirectory();
    
    // === 编译Pixel Shader ===
    
    // 尝试从.cso加载
    std::wstring csoPath = dllDir + L"stroke_effect_ps.cso";
    std::ifstream psFile(csoPath, std::ios::binary);
    
    if (psFile.is_open()) {

        std::vector<char> psData((std::istreambuf_iterator<char>(psFile)),
                                 std::istreambuf_iterator<char>());
        psFile.close();
        
        hr = device->CreatePixelShader(psData.data(), psData.size(), 
                                       nullptr, &pixelShader);
        if (FAILED(hr)) {
            return false;
        }
    }
    else {
        // 运行时编译

        std::vector<std::wstring> hlslPaths = {
            dllDir + L"..\\src\\effects\\stroke_effect.hlsl",
            dllDir + L"stroke_effect.hlsl",
            L"src\\effects\\stroke_effect.hlsl",
            L"GPUEffectRenderer\\src\\effects\\stroke_effect.hlsl"
        };
        
        ID3DBlob* psBlob = nullptr;
        ID3DBlob* errorBlob = nullptr;
        bool compiled = false;
        std::wstring successPath;
        
        for (const auto& path : hlslPaths) {
            hr = D3DCompileFromFile(
                path.c_str(),
                nullptr, D3D_COMPILE_STANDARD_FILE_INCLUDE,
                "PSMain", "ps_5_0",
                D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_DEBUG, 0,
                &psBlob, &errorBlob
            );
            
            if (SUCCEEDED(hr)) {
                compiled = true;
                successPath = path;
                break;
            } else if (errorBlob) {
                errorBlob->Release();
                errorBlob = nullptr;
            }
        }
        
        if (!compiled) {
            return false;
        }
        
        hr = device->CreatePixelShader(psBlob->GetBufferPointer(), 
                                       psBlob->GetBufferSize(),
                                       nullptr, &pixelShader);
        psBlob->Release();
        
        if (FAILED(hr)) {
            return false;
        }
    }
    
    // === 编译Vertex Shader ===
    
    
    const char* vsCode = R"(
        struct VSOutput {
            float4 pos : SV_POSITION;
            float2 uv : TEXCOORD0;
        };
        
        VSOutput VSMain(uint id : SV_VertexID) {
            VSOutput output;
            output.uv = float2((id << 1) & 2, id & 2);
            output.pos = float4(output.uv * float2(2, -2) + float2(-1, 1), 0, 1);
            return output;
        }
    )";
    
    ID3DBlob* vsBlob = nullptr;
    ID3DBlob* vsErrorBlob = nullptr;
    
    hr = D3DCompile(vsCode, strlen(vsCode), nullptr, nullptr, nullptr,
                    "VSMain", "vs_5_0", 0, 0, &vsBlob, &vsErrorBlob);
    
    if (FAILED(hr)) {
        if (vsErrorBlob) {
            vsErrorBlob->Release();
        }
        return false;
    }
    
    hr = device->CreateVertexShader(vsBlob->GetBufferPointer(), 
                                    vsBlob->GetBufferSize(),
                                    nullptr, &vertexShader);
    vsBlob->Release();
    
    if (FAILED(hr)) {
        return false;
    }
    
    return true;
}

// ============================================================
//  创建常量缓冲区
// ============================================================

bool StrokeEffect::CreateConstantBuffer(ID3D11Device* device) {
    D3D11_BUFFER_DESC cbDesc = {};
    cbDesc.ByteWidth = sizeof(StrokeEffectParams);
    cbDesc.Usage = D3D11_USAGE_DYNAMIC;
    cbDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    cbDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    
    HRESULT hr = device->CreateBuffer(&cbDesc, nullptr, &constantBuffer);
    
    if (FAILED(hr)) {
        return false;
    }
    
    return true;
}

// ============================================================
//  创建采样器
// ============================================================

bool StrokeEffect::CreateSamplerState(ID3D11Device* device) {
    D3D11_SAMPLER_DESC sampDesc = {};
    sampDesc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sampDesc.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    sampDesc.ComparisonFunc = D3D11_COMPARISON_NEVER;
    sampDesc.MinLOD = 0;
    sampDesc.MaxLOD = D3D11_FLOAT32_MAX;
    
    HRESULT hr = device->CreateSamplerState(&sampDesc, &sampler);
    
    if (FAILED(hr)) {
        return false;
    }
    
    return true;
}

// ============================================================
//  应用特效
// ============================================================

bool StrokeEffect::Apply(
    ID3D11DeviceContext* context,
    ID3D11ShaderResourceView* inputTexture,
    ID3D11ShaderResourceView* sdfTexture,
    ID3D11RenderTargetView* outputRTV,
    const void* params
) {
    if (!context || !inputTexture || !sdfTexture || !outputRTV || !params) {
        return false;
    }
    
    // 更新常量缓冲区
    D3D11_MAPPED_SUBRESOURCE mapped;
    HRESULT hr = context->Map(constantBuffer, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
    if (SUCCEEDED(hr)) {
        memcpy(mapped.pData, params, sizeof(StrokeEffectParams));
        context->Unmap(constantBuffer, 0);
    }
    
    // 设置渲染目标
    context->OMSetRenderTargets(1, &outputRTV, nullptr);
    
    // 设置Shader
    context->VSSetShader(vertexShader, nullptr, 0);
    context->PSSetShader(pixelShader, nullptr, 0);
    
    // 绑定常量缓冲区
    context->PSSetConstantBuffers(0, 1, &constantBuffer);
    
    // 绑定纹理
    ID3D11ShaderResourceView* srvs[2] = { inputTexture, sdfTexture };
    context->PSSetShaderResources(0, 2, srvs);
    
    // 绑定采样器
    context->PSSetSamplers(0, 1, &sampler);
    
    // 设置渲染状态
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->IASetInputLayout(nullptr);
    
    // 绘制全屏三角形
    context->Draw(3, 0);
    
    // 清理绑定
    ID3D11ShaderResourceView* nullSRVs[2] = { nullptr, nullptr };
    context->PSSetShaderResources(0, 2, nullSRVs);
    
    return true;
}

// ============================================================
//  清理
// ============================================================

void StrokeEffect::Shutdown() {
    SafeRelease(pixelShader);
    SafeRelease(vertexShader);
    SafeRelease(constantBuffer);
    SafeRelease(sampler);
}
#include "../gpu_effect_registry.h"

size_t StrokeEffect::ParamsSize() const { return sizeof(StrokeEffectParams); }

void StrokeEffect::BuildParams(const ParamMap& params, float texW, float texH,
                                float posX, float posY, void* outBuf, size_t bufSize) const {
    if (bufSize < sizeof(StrokeEffectParams)) return;
    auto fget = [&](const char* k, float def) -> float {
        auto it = params.find(k); return it != params.end() ? it->second : def;
    };
    StrokeEffectParams p;
    p.posX = posX; p.posY = posY; p.scaleX = 1.0f; p.scaleY = 1.0f;
    p.strokeWidth = fget("stroke_width", p.strokeWidth);
    p.smoothness  = fget("smoothness",   p.smoothness);
    p.color[0] = fget("color_r", p.color[0]);
    p.color[1] = fget("color_g", p.color[1]);
    p.color[2] = fget("color_b", p.color[2]);
    p.color[3] = fget("color_a", p.color[3]);
    memcpy(outBuf, &p, sizeof(StrokeEffectParams));
}

REGISTER_EFFECT(GPUEffectType::Stroke, StrokeEffect, 50)