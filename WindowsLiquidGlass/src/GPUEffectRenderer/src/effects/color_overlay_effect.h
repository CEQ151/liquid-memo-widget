/*
 * 文件名: color_overlay_effect.h
 * 功能: 颜色滤镜叠加特效 - 在SDF内部叠加指定RGBA颜色
 */

#pragma once
#include "../gpu_effect_base.h"

class ColorOverlayEffect : public GPUEffectBase {
public:
    ColorOverlayEffect() = default;
    ~ColorOverlayEffect() { Shutdown(); }

    bool Initialize(ID3D11Device* device) override;
    bool Apply(
        ID3D11DeviceContext* context,
        ID3D11ShaderResourceView* inputTexture,
        ID3D11ShaderResourceView* sdfTexture,
        ID3D11RenderTargetView* outputRTV,
        const void* params
    ) override;
    void Shutdown() override;
    GPUEffectType GetType() const override { return GPUEffectType::ColorOverlay; }


    size_t ParamsSize() const override;
    void BuildParams(const ParamMap& params, float texW, float texH,
                     float posX, float posY, void* outBuf, size_t bufSize) const override;

private:
    bool LoadShaders(ID3D11Device* device);
    bool CreateConstantBuffer(ID3D11Device* device);
    bool CreateSamplerState(ID3D11Device* device);
};
