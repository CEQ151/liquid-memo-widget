/*
 * 文件名: blur_effect_horz.hlsl
 * 功能: 横向高斯模糊 (Pass 1)
 * 只做横向1D卷积，不检查SDF
 */

cbuffer BlurParams : register(b0) {
    float blurRadius;
    float _padding1[3];
    float4 _padding2;
    float4 _padding3;
    float4 _padding4;
};

Texture2D<float4> inputTexture : register(t0);
SamplerState linearSampler     : register(s0);

struct VSOutput {
    float4 pos : SV_POSITION;
    float2 uv  : TEXCOORD0;
};

static const int MAX_RADIUS = 64;

float4 PSMain(VSOutput input) : SV_TARGET {
    uint w, h;
    inputTexture.GetDimensions(w, h);
    float2 texelSize = 1.0 / float2(w, h);

    float sigma  = max(blurRadius / 2.0, 0.001);
    float sigma2 = 2.0 * sigma * sigma;

    int radius = (int)ceil(blurRadius);
    radius = max(1, min(radius, MAX_RADIUS));

    float4 color = float4(0, 0, 0, 0);
    float  total = 0.0;

    for (int x = -MAX_RADIUS; x <= MAX_RADIUS; x++) {
        if (abs(x) > radius) continue;
        float weight = exp(-(float)(x * x) / sigma2);
        float2 sampleUV = input.uv + float2(x, 0) * texelSize;
        color += inputTexture.Sample(linearSampler, sampleUV) * weight;
        total += weight;
    }

    return color / total;
}
