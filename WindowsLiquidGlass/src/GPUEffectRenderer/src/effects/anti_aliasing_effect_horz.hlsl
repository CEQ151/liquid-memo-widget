/*
 * 文件名: anti_aliasing_effect_horz.hlsl
 * 功能: 抗锯齿 Pass1 - 横向1D高斯模糊
 *       对全图做水平方向卷积，结果传给 vert pass 继续处理
 */

cbuffer AntiAliasingParams : register(b0) {
    float2 sdfPosition;
    float2 sdfScale;
    float  blurRadius;
    float  edgeRange;
    float  strength;
    float  _padding1;
    float  texWidth;
    float  texHeight;
    float2 _padding2;
    float4 _padding3;
};

Texture2D<float4> inputTexture : register(t0);
SamplerState linearSampler     : register(s0);

struct VSOutput {
    float4 pos : SV_POSITION;
    float2 uv  : TEXCOORD0;
};

static const int MAX_RADIUS = 32;

float4 PSMain(VSOutput input) : SV_TARGET {
    float2 texelSize = 1.0 / float2(texWidth, texHeight);

    float sigma  = max(blurRadius / 2.0, 0.001);
    float sigma2 = 2.0 * sigma * sigma;

    int radius = (int)ceil(blurRadius);
    radius = clamp(radius, 1, MAX_RADIUS);

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
