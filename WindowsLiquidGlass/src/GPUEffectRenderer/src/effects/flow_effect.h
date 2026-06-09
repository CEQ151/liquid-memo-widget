/*
 * 文件名: flow_effect.h
 * 功能: 光流特效 - 基于SDF的光流扭曲效果
 */

#pragma once

#include "../gpu_effect_base.h"

class FlowEffect : public GPUEffectBase {
public:
    FlowEffect() = default;
    ~FlowEffect() { Shutdown(); }
    
    bool Initialize(ID3D11Device* device) override;
    
    bool Apply(
        ID3D11DeviceContext* context,
        ID3D11ShaderResourceView* inputTexture,
        ID3D11ShaderResourceView* sdfTexture,
        ID3D11RenderTargetView* outputRTV,
        const void* params
    ) override;
    
    void Shutdown() override;
    
    GPUEffectType GetType() const override { 
        return GPUEffectType::Flow; 
    }
    
    // 继承自基类的 GetLastError()


    size_t ParamsSize() const override;
    void BuildParams(const ParamMap& params, float texW, float texH,
                     float posX, float posY, void* outBuf, size_t bufSize) const override;

private:
    bool LoadShaders(ID3D11Device* device);
    bool CreateConstantBuffer(ID3D11Device* device);
    bool CreateSamplerState(ID3D11Device* device);
};
