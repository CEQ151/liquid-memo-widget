/*
 * 文件名: color_overlay_effect.hlsl
 * 功能: 颜色滤镜叠加特效 - 在SDF内部将指定颜色叠加到输入图像上
 *
 * 参数:
 *   overlayR/G/B : 叠加颜色 RGB (0.0 ~ 1.0)
 *   overlayA     : 叠加强度 (0.0 = 不叠加, 1.0 = 完全替换为叠加色)
 *
 * SDF 遮罩: sdf < 0 的区域（内部）才应用叠加，外部直接返回原图
 */

cbuffer ColorOverlayParams : register(b0) {
    // Block 0: 叠加颜色 (16 bytes)
    float overlayR;     //  0: 叠加颜色 R (0.0 ~ 1.0)
    float overlayG;     //  4: 叠加颜色 G (0.0 ~ 1.0)
    float overlayB;     //  8: 叠加颜色 B (0.0 ~ 1.0)
    float overlayA;     // 12: 叠加强度   (0.0 ~ 1.0)

    // Block 1: SDF 位置 (16 bytes)
    float sdfPosX;      // 16: SDF 在屏幕上的 X 坐标
    float sdfPosY;      // 20: SDF 在屏幕上的 Y 坐标
    float _padding[2];  // 24-32

    // Total: 32 bytes (16字节对齐 ✓)
};

Texture2D<float4> inputTexture : register(t0);
Texture2D<float>  sdfTexture   : register(t1);
SamplerState      linearSampler : register(s0);

struct VSOutput {
    float4 pos : SV_POSITION;
    float2 uv  : TEXCOORD0;
};

float4 PSMain(VSOutput input) : SV_TARGET {
    float4 col = inputTexture.Sample(linearSampler, input.uv);

    // SDF 遮罩：只在 SDF 内部（sdf < 0）应用叠加
    uint sdfW, sdfH;
    sdfTexture.GetDimensions(sdfW, sdfH);
    float2 sdfUV = (input.pos.xy - float2(sdfPosX, sdfPosY)) / float2(sdfW, sdfH);
    float sdf = sdfTexture.Sample(linearSampler, sdfUV);
    if (sdf >= 0.0) {
        return float4(col.rgb, 1.0);
    }

    // 将原始颜色与叠加颜色按强度 overlayA 混合
    float3 result = lerp(col.rgb, float3(overlayR, overlayG, overlayB), overlayA);
    return float4(result, 1.0);
}
