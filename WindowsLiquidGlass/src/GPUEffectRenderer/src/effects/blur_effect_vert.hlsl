/*
 * 文件名: blur_effect_vert.hlsl
 * 功能: 纵向高斯模糊 (Pass 2)
 * 做纵向1D卷积，并用SDF遮罩还原外部区域
 */

cbuffer BlurParams : register(b0) {
    float blurRadius;
    float _padding1[3];
    float4 _padding2;       // bytes 16-32（texWidth/texHeight在C++里，着色器不使用）
    float2 sdfPosition;     // bytes 32-40: SDF 屏幕像素坐标 (posX, posY)
    float2 sdfScale;        // bytes 40-48: SDF 缩放比例 (scaleX, scaleY)
    float4 _padding4;       // bytes 48-64
};

Texture2D<float4> inputTexture  : register(t0); // 横向模糊后的中间纹理
Texture2D<float>  sdfTexture    : register(t1); // SDF 距离场
Texture2D<float4> originalTexture : register(t2); // 原始输入纹理（用于SDF外部还原）
SamplerState linearSampler      : register(s0);

struct VSOutput {
    float4 pos : SV_POSITION;
    float2 uv  : TEXCOORD0;
};

static const int MAX_RADIUS = 64;

float4 PSMain(VSOutput input) : SV_TARGET {
    uint w, h;
    inputTexture.GetDimensions(w, h);
    float2 texelSize = 1.0 / float2(w, h);

    // SDF 检查（SDF位于屏幕上 sdfPosition 处）
    uint sw, sh;
    sdfTexture.GetDimensions(sw, sh);
    float2 sdfUV = (input.pos.xy - sdfPosition) / float2(sw, sh);
    float sdf = sdfTexture.Sample(linearSampler, sdfUV);

    // SDF 外部：返回原始图像（不是横向模糊后的）
    if (sdf >= 0.0 || blurRadius < 0.5) {
        return originalTexture.Sample(linearSampler, input.uv);
    }

    float sigma  = max(blurRadius / 2.0, 0.001);
    float sigma2 = 2.0 * sigma * sigma;

    int radius = (int)ceil(blurRadius);
    radius = max(1, min(radius, MAX_RADIUS));

    float4 color = float4(0, 0, 0, 0);
    float  total = 0.0;

    for (int y = -MAX_RADIUS; y <= MAX_RADIUS; y++) {
        if (abs(y) > radius) continue;
        float weight = exp(-(float)(y * y) / sigma2);
        float2 sampleUV = input.uv + float2(0, y) * texelSize;
        color += inputTexture.Sample(linearSampler, sampleUV) * weight;
        total += weight;
    }

    return color / total;
}
