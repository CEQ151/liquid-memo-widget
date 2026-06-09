/*
 * 文件名: flow_effect.hlsl
 * 功能: 光流特效Pixel Shader - 基于SDF的光流扭曲（带抗锯齿）
 */

// ============================================================
//  常量缓冲区 (必须与C++结构体完全匹配，64字节)
// ============================================================

cbuffer FlowParams : register(b0) {
    // Transform (16 bytes)
    float2 sdfPosition;      // posX, posY
    float2 sdfScale;         // scaleX, scaleY
    
    // Flow params (16 bytes)
    float flowStrength;      // 流动强度 (1.0-5.0)
    float flowWidth;         // 流动区域宽度 (像素)
    float flowFalloff;       // 衰减曲线指数 (0.5-3.0)
    float _padding1;
    
    // Texture info (16 bytes)
    float2 texSize;          // 纹理尺寸 (width, height)
    float2 _padding2;
    
    // Padding (16 bytes)
    float4 _padding3;
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
//  辅助函数：计算单个采样点的光流
// ============================================================

float4 SampleFlowAtPosition(float2 screenPos) {
    // 1. 获取SDF纹理尺寸
    uint sdfWidth, sdfHeight;
    sdfTexture.GetDimensions(sdfWidth, sdfHeight);
    
    // 2. 计算SDF纹理的UV坐标
    float2 sdfLocalPos = (screenPos - sdfPosition) / sdfScale;
    float2 sdfUV = sdfLocalPos / float2(sdfWidth, sdfHeight);
    
    // 3. 边界检查:只在SDF有效区域处理
    if (sdfUV.x < 0.0 || sdfUV.x > 1.0 || sdfUV.y < 0.0 || sdfUV.y > 1.0) {
        // 超出SDF区域,直接返回原图
        return inputTexture.Load(int3(screenPos, 0));
    }
    
    // 4. 采样SDF距离值
    float dist = sdfTexture.Sample(linearSampler, sdfUV);
    
    // 5. 计算缩放因子
    float scale = 1.0;
    
    // 外部区域检查
    if (dist >= 0.0) {
        // 超出内部区域,直接返回原图
        return inputTexture.Load(int3(screenPos, 0));
    }
    
    // 流动区域边界
    float flowStart = -flowWidth;
    
    if (dist >= flowStart && dist < 0.0) {
        // 流动区域: 计算渐变缩放
        // 归一化距离 t: 0 (at -flow_width) -> 1 (at edge 0)
        float t = (dist - flowStart) / flowWidth;
        t = saturate(t);  // clamp to [0, 1]
        
        // 应用衰减曲线
        float t_falloff = pow(t, flowFalloff);
        
        // 缩放插值: 1.0 -> flowStrength
        scale = 1.0 + (flowStrength - 1.0) * t_falloff;
    }
    
    // 6. 计算重映射坐标 (相对于图像中心缩放)
    float2 center = texSize * 0.5;
    float2 remappedPos = center + (screenPos - center) / scale;
    
    // 7. 采样重映射后的纹理
    // 边界检查
    if (remappedPos.x < 0.0 || remappedPos.x >= texSize.x ||
        remappedPos.y < 0.0 || remappedPos.y >= texSize.y) {
        // 超出边界，使用边缘像素 (BORDER_REPLICATE)
        remappedPos = clamp(remappedPos, float2(0, 0), texSize - 1.0);
    }
    
    // 使用线性插值采样
    float2 remappedUV = remappedPos / texSize;
    return inputTexture.Sample(linearSampler, remappedUV);
}

// ============================================================
//  Pixel Shader主函数（带4x超采样抗锯齿）
// ============================================================

float4 PSMain(VSOutput input) : SV_TARGET {
    float2 screenPos = input.pos.xy;
    
    // 4x超采样抗锯齿
    // 在当前像素周围采样4个子像素点（Rotated Grid模式）
    // 偏移量：0.25像素，呈菱形分布
    const float offset = 0.25;
    const float2 offsets[4] = {
        float2(-offset, 0.0),      // 左
        float2(offset, 0.0),       // 右
        float2(0.0, -offset),      // 上
        float2(0.0, offset)        // 下
    };
    
    // 累加4个子采样结果
    float4 color = float4(0, 0, 0, 0);
    
    [unroll]
    for (int i = 0; i < 4; i++) {
        float2 samplePos = screenPos + offsets[i];
        color += SampleFlowAtPosition(samplePos);
    }
    
    // 平均4个采样结果
    return color * 0.25;
}