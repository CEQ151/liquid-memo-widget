/*
 * 文件名: stroke_effect.hlsl
 * 功能: 边框特效Pixel Shader
 */

// ============================================================
//  常量缓冲区 (必须与C++结构体完全匹配，64字节)
// ============================================================

cbuffer StrokeParams : register(b0) {
    // Transform (16 bytes)
    float2 sdfPosition;      // posX, posY
    float2 sdfScale;         // scaleX, scaleY
    
    // Stroke params (16 bytes)
    float strokeWidth;
    float smoothness;
    float2 _padding1;
    
    // Color (16 bytes)
    float4 strokeColor;      // RGBA
    
    // Padding (16 bytes)
    float4 _padding2;
};

// ============================================================
//  纹理和采样器
// ============================================================

Texture2D<float4> inputTexture : register(t0);   // 输入纹理(屏幕)
Texture2D<float>  sdfTexture   : register(t1);   // SDF距离场
SamplerState linearSampler     : register(s0);

// ============================================================
//  Vertex Shader输出结构
// ============================================================

struct VSOutput {
    float4 pos : SV_POSITION;
    float2 uv : TEXCOORD0;
};

// ============================================================
//  Pixel Shader主函数
// ============================================================

float4 PSMain(VSOutput input) : SV_TARGET {
    // 1. 获取当前像素的屏幕坐标(像素单位)
    float2 screenPos = input.pos.xy;
    
    // 2. 获取SDF纹理尺寸
    uint sdfWidth, sdfHeight;
    sdfTexture.GetDimensions(sdfWidth, sdfHeight);
    
    // 3. 计算SDF纹理的UV坐标
    float2 sdfLocalPos = (screenPos - sdfPosition) / sdfScale;
    float2 sdfUV = sdfLocalPos / float2(sdfWidth, sdfHeight);
    
    // 4. 边界检查:只在SDF有效区域绘制
    if (sdfUV.x < 0.0 || sdfUV.x > 1.0 || sdfUV.y < 0.0 || sdfUV.y > 1.0) {
        // 超出SDF区域,直接返回原图
        return inputTexture.Load(int3(screenPos, 0));
    }
    
    // 5. 采样SDF距离值
    float dist = sdfTexture.Sample(linearSampler, sdfUV);
    
    // 6. 计算边框遮罩
    float innerEdge = 0.0;
    float outerEdge = strokeWidth;
    
    float innerMask = smoothstep(innerEdge - smoothness, innerEdge + smoothness, dist);
    float outerMask = smoothstep(outerEdge - smoothness, outerEdge + smoothness, dist);
    
    float strokeMask = innerMask - outerMask;
    
    // 7. 采样原始输入纹理
    float4 baseColor = inputTexture.Load(int3(screenPos, 0));
    
    // 8. 混合边框颜色
    float finalAlpha = strokeMask * strokeColor.a;
    float4 finalColor = lerp(baseColor, strokeColor, finalAlpha);
    
    return finalColor;
}