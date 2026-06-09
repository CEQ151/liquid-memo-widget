/*
 * 文件名: anti_aliasing_effect.h
 * 功能: 基于SDF的抗锯齿特效类声明（两 pass 可分离高斯模糊）
 */

#pragma once

#include "../gpu_effect_base.h"
#include "../gpu_effect_types.h"

class AntiAliasingEffect : public GPUEffectBase {
public:
    AntiAliasingEffect();
    ~AntiAliasingEffect() override { Shutdown(); }

    bool Initialize(ID3D11Device* device) override;
    void Shutdown() override;

    bool Apply(
        ID3D11DeviceContext* context,
        ID3D11ShaderResourceView* inputTexture,
        ID3D11ShaderResourceView* sdfTexture,
        ID3D11RenderTargetView* outputRTV,
        const void* params
    ) override;

    GPUEffectType GetType() const override { return GPUEffectType::AntiAliasing; }


    size_t ParamsSize() const override;
    void BuildParams(const ParamMap& params, float texW, float texH,
                     float posX, float posY, void* outBuf, size_t bufSize) const override;

private:
    // Pass1: 横向模糊 shader
    ID3D11PixelShader* pixelShaderHorz_;
    // Pass2: 纵向模糊 + SDF 遮罩 shader
    ID3D11PixelShader* pixelShaderVert_;
    ID3D11Buffer*      constantBuffer_;

    // 中间纹理（横向结果暂存）
    ID3D11Texture2D*          intermediateTexture_;
    ID3D11ShaderResourceView* intermediateSRV_;
    ID3D11RenderTargetView*   intermediateRTV_;

    UINT cachedWidth_;
    UINT cachedHeight_;
    ID3D11Device* device_;

    bool LoadShaders(ID3D11Device* device);
    bool CreateSamplerState(ID3D11Device* device);
    bool EnsureIntermediateTexture(UINT width, UINT height);
};
