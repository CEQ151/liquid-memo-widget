/*
 * 文件名: common.hlsl
 * 功能: GPU特效公共函数库
 */

#ifndef COMMON_HLSL
#define COMMON_HLSL

// ============================================================
//  SDF采样辅助函数
// ============================================================

// 采样SDF距离值
float SampleSDF(Texture2D<float> sdfTex, SamplerState samp, float2 uv) {
    return sdfTex.Sample(samp, uv);
}

// 平滑边缘函数(抗锯齿)
float SmoothEdge(float dist, float edge, float smoothness) {
    return smoothstep(edge - smoothness, edge + smoothness, dist);
}

// ============================================================
//  坐标转换
// ============================================================

// 屏幕坐标转SDF UV坐标
float2 ScreenToSDFUV(float2 screenPos, float2 sdfPos, float2 sdfScale, float2 sdfSize) {
    float2 localPos = (screenPos - sdfPos) / sdfScale;
    return localPos / sdfSize;
}

// 检查UV是否在有效范围
bool IsValidUV(float2 uv) {
    return uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0;
}

// ============================================================
//  颜色混合
// ============================================================

// Alpha混合
float4 AlphaBlend(float4 src, float4 dst) {
    float alpha = src.a + dst.a * (1.0 - src.a);
    float3 rgb = (src.rgb * src.a + dst.rgb * dst.a * (1.0 - src.a)) / alpha;
    return float4(rgb, alpha);
}

#endif // COMMON_HLSL