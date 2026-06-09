/*
 * 文件名: gpu_effect_base.h
 * 功能: GPU特效基类 - 所有特效的抽象接口
 *
 * 重构说明：
 *   添加了 ParamsSize() 和 BuildParams() 两个纯虚方法。
 *   渲染器通过泛型字符串键值表（ParamMap）传入参数，每个特效自行将其映射到对应的
 *   HLSL 常量缓冲区结构体。
 *   这样渲染器/API/Python wrapper 完全不感知具体特效的参数结构。
 */

#pragma once

#include "gpu_effect_types.h"
#include <d3d11.h>
#include <cstring>
#include <string>
#include <unordered_map>

// 泛型参数表：key = Python 参数名（与 effects_params.py 一致），value = float
// 整数参数也作为 float 存储，特效内部按需 static_cast<int>
using ParamMap = std::unordered_map<std::string, float>;

// ============================================================
//  GPU特效基类
// ============================================================

class GPUEffectBase {
public:
    virtual ~GPUEffectBase() = default;
    
    // 初始化(加载Shader和创建资源)
    virtual bool Initialize(ID3D11Device* device) = 0;
    
    // 应用特效
    virtual bool Apply(
        ID3D11DeviceContext* context,
        ID3D11ShaderResourceView* inputTexture,
        ID3D11ShaderResourceView* sdfTexture,
        ID3D11RenderTargetView* outputRTV,
        const void* params
    ) = 0;
    
    // 清理资源
    virtual void Shutdown() = 0;
    
    // 获取特效类型
    virtual GPUEffectType GetType() const = 0;
    
    // ── 泛型参数接口 ──────────────────────────────────────────────────────────
    // 返回此特效的 HLSL 常量缓冲区大小（字节），用于渲染器分配参数缓冲区
    virtual size_t ParamsSize() const = 0;

    // 将泛型参数表映射为特效专用的 HLSL 常量缓冲区布局，写入 outBuf
    //   params : 所有参数（key=Python名称, value=float）
    //   texW/texH : 当前纹理尺寸（像素）
    //   posX/posY : SDF 在屏幕上的坐标
    //   outBuf/bufSize : 由渲染器预分配的缓冲区（大小 == ParamsSize()）
    virtual void BuildParams(const ParamMap& params,
                             float texW, float texH,
                             float posX, float posY,
                             void* outBuf, size_t bufSize) const = 0;
    
    // 获取最后的错误信息
    virtual const char* GetLastError() const { return lastError; }

protected:
    // 通用资源(子类可使用)
    ID3D11VertexShader* vertexShader = nullptr;
    ID3D11PixelShader* pixelShader = nullptr;
    ID3D11Buffer* constantBuffer = nullptr;
    ID3D11SamplerState* sampler = nullptr;
    
    // 错误信息缓冲区
    char lastError[512] = {0};
    
    // 辅助方法:安全释放COM对象
    template<typename T>
    void SafeRelease(T*& ptr) {
        if (ptr) {
            ptr->Release();
            ptr = nullptr;
        }
    }
    
    // 设置错误信息
    void SetError(const char* error) {
        strcpy_s(lastError, sizeof(lastError), error);
    }
};