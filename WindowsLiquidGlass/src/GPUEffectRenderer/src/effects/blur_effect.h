/*
 * 文件名: blur_effect.h
 * 功能: 高斯模糊特效类声明
 */

#pragma once

#include "../gpu_effect_base.h"
#include "../gpu_effect_types.h"

class BlurEffect : public GPUEffectBase {
public:
    BlurEffect();
    ~BlurEffect() override;

    bool Initialize(ID3D11Device* device) override;
    void Shutdown() override;
    
    bool Apply(
        ID3D11DeviceContext* context,
        ID3D11ShaderResourceView* inputTexture,
        ID3D11ShaderResourceView* sdfTexture,
        ID3D11RenderTargetView* outputRTV,
        const void* params
    ) override;
    
    GPUEffectType GetType() const override { return GPUEffectType::Blur; }


    size_t ParamsSize() const override;
    void BuildParams(const ParamMap& params, float texW, float texH,
                     float posX, float posY, void* outBuf, size_t bufSize) const override;

private:
    // 横向 pass shader
    ID3D11PixelShader* pixelShaderHorz_;
    // 纵向 pass shader
    ID3D11PixelShader* pixelShaderVert_;
    ID3D11Buffer*      constantBuffer_;

    // 中间纹理（横向结果暂存）
    ID3D11Texture2D*          intermediateTexture_;
    ID3D11ShaderResourceView* intermediateSRV_;
    ID3D11RenderTargetView*   intermediateRTV_;

    // 缓存尺寸（用于判断是否需要重建中间纹理）
    UINT cachedWidth_;
    UINT cachedHeight_;

    // 保存 device 引用用于懒创建中间纹理
    ID3D11Device* device_;

    bool EnsureIntermediateTexture(UINT width, UINT height);
};
