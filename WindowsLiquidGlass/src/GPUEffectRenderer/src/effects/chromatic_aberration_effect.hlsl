/*
 * 文件名: chromatic_aberration_effect.hlsl
 * 功能: 色散特效Pixel Shader - 基于SDF的RGB通道分离
 */

// ============================================================
//  常量缓冲区 (必须与C++结构体完全匹配，64字节)
// ============================================================

cbuffer ChromaticParams : register(b0) {
    // Transform (16 bytes)
    float2 sdfPosition;      // posX, posY
    float2 sdfScale;         // scaleX, scaleY
    
    // Chromatic params (16 bytes)
    float chromaticStrength;  // 色散强度 (像素)
    float chromaticWidth;     // 色散区域宽度 (像素)
    float chromaticFalloff;   // 衰减曲线指数
    float _padding1;
    
    // Channel offsets (16 bytes)
    float channelOffsetR;     // R通道偏移比例 (default: 1.0)
    float channelOffsetG;     // G通道偏移比例 (default: 0.0)
    float channelOffsetB;     // B通道偏移比例 (default: -1.0)
    float _padding2;
    
    // Texture info (16 bytes)
    float2 texSize;           // 纹理尺寸 (width, height)
    float2 _padding3;
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
//  辅助函数：计算SDF梯度（法向量）
// ============================================================

float2 ComputeSDFGradient(float2 sdfUV, float2 sdfTexelSize) {
    // 使用中心差分计算梯度
    float sdfL = sdfTexture.Sample(linearSampler, sdfUV + float2(-sdfTexelSize.x, 0));
    float sdfR = sdfTexture.Sample(linearSampler, sdfUV + float2(sdfTexelSize.x, 0));
    float sdfU = sdfTexture.Sample(linearSampler, sdfUV + float2(0, -sdfTexelSize.y));
    float sdfD = sdfTexture.Sample(linearSampler, sdfUV + float2(0, sdfTexelSize.y));
    
    float2 gradient = float2(sdfR - sdfL, sdfD - sdfU);
    
    // 归一化为单位向量
    float mag = length(gradient);
    if (mag > 1e-5) {
        gradient = gradient / mag;
    }
    
    return gradient;
}

// ============================================================
//  辅助函数：计算偏移强度
// ============================================================

float ComputeOffsetStrength(float dist) {
    // 色散区域: [-chromaticWidth, 0]
    float chromaStart = -chromaticWidth;
    
    if (dist < chromaStart || dist >= 0.0) {
        return 0.0;  // 核心区域或外部区域，无偏移
    }
    
    // 流动区域: 计算归一化距离 t: 0 (at -chromaticWidth) -> 1 (at edge 0)
    float t = (dist - chromaStart) / chromaticWidth;
    t = saturate(t);
    
    // 应用衰减曲线
    float strength = pow(t, chromaticFalloff);
    
    return strength;
}

// ============================================================
//  Pixel Shader主函数
// ============================================================

float4 PSMain(VSOutput input) : SV_TARGET {
    // 1. 获取当前像素的屏幕坐标(像素单位)
    float2 screenPos = input.pos.xy;
    
    // 2. 获取SDF纹理尺寸
    uint sdfWidth, sdfHeight;
    sdfTexture.GetDimensions(sdfWidth, sdfHeight);
    float2 sdfTexelSize = float2(1.0 / sdfWidth, 1.0 / sdfHeight);
    
    // 3. 计算SDF纹理的UV坐标
    float2 sdfLocalPos = (screenPos - sdfPosition) / sdfScale;
    float2 sdfUV = sdfLocalPos / float2(sdfWidth, sdfHeight);
    
    // 4. 边界检查:只在SDF有效区域处理
    if (sdfUV.x < 0.0 || sdfUV.x > 1.0 || sdfUV.y < 0.0 || sdfUV.y > 1.0) {
        // 超出SDF区域,直接返回原图
        return inputTexture.Load(int3(screenPos, 0));
    }
    
    // 5. 采样SDF距离值
    float dist = sdfTexture.Sample(linearSampler, sdfUV);
    
    // 6. 计算偏移强度
    float offsetStrength = ComputeOffsetStrength(dist);
    
    // 如果偏移强度为0，直接返回原图
    if (offsetStrength < 0.001) {
        return inputTexture.Load(int3(screenPos, 0));
    }
    
    // 7. 计算SDF梯度（法向量方向）
    float2 gradient = ComputeSDFGradient(sdfUV, sdfTexelSize);
    
    // 将梯度从SDF空间转换到屏幕空间
    float2 gradientScreen = gradient * sdfScale;
    gradientScreen = normalize(gradientScreen);
    
    // 8. 计算每个通道的偏移量
    float2 baseOffset = gradientScreen * offsetStrength * chromaticStrength;
    
    // 9. 分别采样RGB三个通道
    float2 inputUV = screenPos / texSize;
    float4 result = float4(0, 0, 0, 1);
    
    // R通道：向外偏移
    float2 offsetR = baseOffset * channelOffsetR;
    float2 uvR = (screenPos + offsetR) / texSize;
    result.r = inputTexture.Sample(linearSampler, uvR).r;
    
    // G通道：可选偏移（通常为0）
    float2 offsetG = baseOffset * channelOffsetG;
    float2 uvG = (screenPos + offsetG) / texSize;
    result.g = inputTexture.Sample(linearSampler, uvG).g;
    
    // B通道：向内偏移
    float2 offsetB = baseOffset * channelOffsetB;
    float2 uvB = (screenPos + offsetB) / texSize;
    result.b = inputTexture.Sample(linearSampler, uvB).b;
    
    // Alpha通道（如果需要的话，可以从原图采样）
    result.a = inputTexture.Sample(linearSampler, inputUV).a;
    
    return result;
}
