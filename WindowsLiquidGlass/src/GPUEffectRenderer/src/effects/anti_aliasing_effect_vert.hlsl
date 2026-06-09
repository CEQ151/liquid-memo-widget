/*
 * 文件名: anti_aliasing_effect_vert.hlsl
 * 功能: 抗锯齿 Pass2 - 纵向1D高斯模糊 + SDF Alpha遮罩
 *
 * 逻辑（对应 Python SDAntiAliasingEffect._apply_edge_smoothing）：
 *   dist < -edgeRange  → 深内部：直接返回原图（t2），不做任何处理
 *   dist > +edgeRange  → 外部  ：完全透明 (0,0,0,0)
 *   |dist| <= edgeRange → 边缘  ：
 *       RGB  = lerp(原图rgb, 模糊rgb, (1 - |dist|/edgeRange) * strength)
 *       Alpha 内侧 (dist < 0)：原图 alpha 不变
 *       Alpha 外侧 (0 <= dist <= edgeRange)：alpha * (1 - dist/edgeRange)
 *
 * 纹理绑定:
 *   t0 = 横向模糊后的中间纹理
 *   t1 = SDF 距离场
 *   t2 = 原始输入纹理
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

Texture2D<float4> horzBlurred   : register(t0);  // Pass1 横向模糊结果
Texture2D<float>  sdfTexture    : register(t1);  // SDF 距离场
Texture2D<float4> originalTex   : register(t2);  // 原始输入（未模糊）
SamplerState linearSampler      : register(s0);

struct VSOutput {
    float4 pos : SV_POSITION;
    float2 uv  : TEXCOORD0;
};

static const int MAX_RADIUS = 32;

float4 PSMain(VSOutput input) : SV_TARGET {
    // ---- 计算 SDF UV ----
    float2 screenPos = input.pos.xy;
    uint sdfW, sdfH;
    sdfTexture.GetDimensions(sdfW, sdfH);
    float2 sdfLocalPos = (screenPos - sdfPosition) / sdfScale;
    float2 sdfUV = sdfLocalPos / float2(sdfW, sdfH);

    // SDF 区域外：完全透明
    if (sdfUV.x < 0.0 || sdfUV.x > 1.0 || sdfUV.y < 0.0 || sdfUV.y > 1.0) {
        return float4(0.0, 0.0, 0.0, 0.0);
    }

    float dist = sdfTexture.Sample(linearSampler, sdfUV);

    // 外部区域 (dist > edgeRange)：完全透明
    if (dist > edgeRange) {
        return float4(0.0, 0.0, 0.0, 0.0);
    }

    // 原始像素颜色
    float4 origColor = originalTex.Sample(linearSampler, input.uv);

    // 深内部 (dist < -edgeRange)：跳过模糊，直接返回原图
    if (dist < -edgeRange) {
        return origColor;
    }

    // ---- 边缘区域：纵向高斯模糊 t0 ----
    float2 texelSize = 1.0 / float2(texWidth, texHeight);
    float sigma  = max(blurRadius / 2.0, 0.001);
    float sigma2 = 2.0 * sigma * sigma;

    int radius = (int)ceil(blurRadius);
    radius = clamp(radius, 1, MAX_RADIUS);

    float4 blurColor = float4(0, 0, 0, 0);
    float  totalW    = 0.0;

    for (int y = -MAX_RADIUS; y <= MAX_RADIUS; y++) {
        if (abs(y) > radius) continue;
        float weight = exp(-(float)(y * y) / sigma2);
        float2 sampleUV = input.uv + float2(0, y) * texelSize;
        blurColor += horzBlurred.Sample(linearSampler, sampleUV) * weight;
        totalW    += weight;
    }
    float4 blurredColor = (totalW > 0.0) ? (blurColor / totalW) : origColor;

    // ---- RGB 混合 ----
    // 边界处(|dist|=0)权重最大，远离边缘降为0
    float blendWeight = (1.0 - abs(dist) / edgeRange) * strength;
    blendWeight = clamp(blendWeight, 0.0, 1.0);
    float3 blendedRGB = lerp(origColor.rgb, blurredColor.rgb, blendWeight);

    // ---- Alpha 遮罩 ----
    float alpha;
    if (dist < edgeRange) {
        // 内侧边缘：保持原始 alpha
        alpha = origColor.a;
    } else {
        // 外侧边缘 (0 <= dist <= edgeRange)：线性衰减到 0
        float t = dist / edgeRange;
        alpha = origColor.a * (1.0 - t);
    }

    return float4(blendedRGB, alpha);
}
