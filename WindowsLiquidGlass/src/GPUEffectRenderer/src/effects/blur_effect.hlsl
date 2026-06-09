/*
 * 文件名: blur_effect.hlsl
 * 功能: 高斯模糊特效 - 对SDF内部应用高斯模糊
 * 正确实现：每步1像素，blurRadius控制采样半径大小
 */

cbuffer BlurParams : register(b0) {
    float blurRadius;
    float _padding1[3];
    float4 _padding2;       // bytes 16-32（texWidth/texHeight在C++里，着色器不使用）
    float2 sdfPosition;     // bytes 32-40: SDF 屏幕像素坐标 (posX, posY)
    float2 sdfScale;        // bytes 40-48: SDF 缩放比例 (scaleX, scaleY)
    float4 _padding4;       // bytes 48-64
};

Texture2D<float4> inputTexture : register(t0);
Texture2D<float>  sdfTexture   : register(t1);
SamplerState linearSampler     : register(s0);

struct VSOutput {
    float4 pos : SV_POSITION;
    float2 uv  : TEXCOORD0;
};

float4 PSMain(VSOutput input) : SV_TARGET {
    uint w, h;
    inputTexture.GetDimensions(w, h);
    float2 texelSize = 1.0 / float2(w, h);

    // 原始颜色
    float4 baseColor = inputTexture.Sample(linearSampler, input.uv);

    // 参数检查
    if (blurRadius < 0.5) return baseColor;

    // SDF 检查：只对内部应用模糊（SDF位于屏幕上 sdfPosition 处）
    uint sw, sh;
    sdfTexture.GetDimensions(sw, sh);
    float2 sdfUV = (input.pos.xy - sdfPosition) / float2(sw, sh);
    float sdf = sdfTexture.Sample(linearSampler, sdfUV);
    if (sdf >= 0.0) return baseColor;

    // ============================================================
    // 正确的高斯模糊：
    // - 每步固定1像素（texelSize）
    // - sigma = blurRadius / 2.0
    // - 对半径内每个像素按高斯公式计算权重
    // ============================================================
    float sigma  = max(blurRadius / 2.0, 0.001);
    float sigma2 = 2.0 * sigma * sigma;
    static const int MAX_RADIUS = 32; // 允许最大半径32像素

    int radius = (int)ceil(blurRadius);
    radius = max(1, min(radius, MAX_RADIUS)); // 防止越界

    float4 blurColor = float4(0, 0, 0, 0);
    float  total     = 0.0;

    for (int y = -MAX_RADIUS; y <= MAX_RADIUS; y++) {
        for (int x = -MAX_RADIUS; x <= MAX_RADIUS; x++) {
            if (abs(x) > radius || abs(y) > radius) continue; // 超出实际半径的跳过
            float dist2  = float(x * x + y * y);
            float weight = exp(-dist2 / sigma2);

            float2 sampleUV = input.uv + float2(x, y) * texelSize;
            blurColor      += inputTexture.Sample(linearSampler, sampleUV) * weight;
            total          += weight;
        }
    }

    return blurColor / total;
}