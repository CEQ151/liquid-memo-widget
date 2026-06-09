/*
 * 文件名: highlight_effect.hlsl
 * 功能: 边缘高光特效 - 基于SDF梯度法线的边缘光照
 *
 * 算法原理（类似苹果液态玻璃边缘高光）：
 *   1. 对SDF在高光宽度范围内的像素（sdf ∈ [-highlightWidth, 0)）处理
 *   2. 用中心差分法计算SDF梯度 → 边缘外法线方向
 *   3. dot(法线, 光照方向) > 0 的边缘面向光源 → 产生高光
 *   4. 不透明模式(diagonal=0)：只有面向光源的边缘有高光
 *   5. 透明模式(diagonal=1)：背面边缘也有高光（光穿透对象），强度50%
 */

cbuffer HighlightParams : register(b0) {
    float highlightWidth;      // 0:  高光带宽度（SDF 0向内的像素数）
    float highlightAngle;      // 4:  光照角度（弧度，0=右，逆时针）
    int   highlightMode;       // 8:  模式（0=白色高光，1=提亮+增饱和度）
    int   highlightDiagonal;   // 12: 透明对象对角高光（0=不透明，1=透明）
    float highlightSize;       // 16: 高光强度（0~1，控制整体亮度）
    float highlightRange;      // 20: 高光影响范围（0~1，1.0=默认覆盖，0.5=一半）
    float2 _padding1;          // 24-32
    float texWidth;            // 32: 纹理宽度
    float texHeight;           // 36: 纹理高度
    float2 _padding2;          // 40-48
    float2 sdfPosition;        // 48-56: SDF 屏幕像素坐标 (posX, posY)
    float2 sdfScale;           // 56-64: SDF 缩放比例 (scaleX, scaleY)
};

Texture2D<float4> inputTexture : register(t0);
Texture2D<float>  sdfTexture   : register(t1);
SamplerState linearSampler     : register(s0);

struct VSOutput {
    float4 pos : SV_POSITION;
    float2 uv  : TEXCOORD0;
};

// --- HSV 辅助函数 ---
float3 rgb2hsv(float3 c) {
    float4 K = float4(0.0, -1.0/3.0, 2.0/3.0, -1.0);
    float4 p = lerp(float4(c.bg, K.wz), float4(c.gb, K.xy), step(c.b, c.g));
    float4 q = lerp(float4(p.xyw, c.r), float4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return float3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}
float3 hsv2rgb(float3 c) {
    float4 K = float4(1.0, 2.0/3.0, 1.0/3.0, 3.0);
    float3 p = abs(frac(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * lerp(K.xxx, saturate(p - K.xxx), c.y);
}

float4 PSMain(VSOutput input) : SV_TARGET {
    float2 texSize   = float2(texWidth, texHeight);
    float2 texelSize = 1.0 / texSize;
    float2 uv        = input.pos.xy / texSize;

    // SDF 纹理尺寸及偏移UV（SDF比全屏小，需要用屏幕坐标减去 SDF 位置）
    uint sw, sh;
    sdfTexture.GetDimensions(sw, sh);
    float2 sdfTexelSize = 1.0 / float2(sw, sh);
    float2 sdfUV = (input.pos.xy - sdfPosition) / float2(sw, sh);

    float4 baseColor = inputTexture.Sample(linearSampler, input.uv);

    // 采样 SDF
    float sdf = sdfTexture.Sample(linearSampler, sdfUV);

    // 外部(sdf >= 0) 或 内部超出最大宽度直接返回原图（早期退出优化）
    if (sdf >= 0.0 || sdf < -highlightWidth) {
        return baseColor;
    }

    // 用中心差分法计算 SDF 梯度（边缘外法线，指向 SDF 增大方向）
    float sdfR = sdfTexture.Sample(linearSampler, sdfUV + float2( sdfTexelSize.x, 0));
    float sdfL = sdfTexture.Sample(linearSampler, sdfUV + float2(-sdfTexelSize.x, 0));
    float sdfU = sdfTexture.Sample(linearSampler, sdfUV + float2(0,  sdfTexelSize.y));
    float sdfD = sdfTexture.Sample(linearSampler, sdfUV + float2(0, -sdfTexelSize.y));
    float2 grad = float2(sdfR - sdfL, sdfU - sdfD);
    float gradLen = length(grad);
    float2 normal = (gradLen > 1e-5) ? (grad / gradLen) : float2(0, 0);
    // normal 指向外（SDF 增大方向 = 从形状内部指向外部）

    // 光照方向向量
    float2 lightDir = float2(cos(highlightAngle), sin(highlightAngle));

    // 法线与光照方向的点积：1=正对光源，0=侧向，-1=背对光源
    float facing = dot(normal, lightDir);

    // -------------------------------------------------------
    // 高光范围控制（highlightRange）：
    //   range=1.0: 默认，facing>0 就有高光（影响一半边缘）
    //   range=0.5: facing>0.5 才有高光（影响范围减半）
    // -------------------------------------------------------
    float rangeThreshold = 1.0 - highlightRange;
    float frontFacing = max(0.0, (facing - rangeThreshold) / max(highlightRange, 0.01));
    
    // 宽度衰减：从照射中心向两边平滑衰减
    // 使用低次幂（0.4）：中心附近衰减慢，边缘衰减快
    float widthFactor = pow(saturate(frontFacing), 0.4);
    float effectiveWidth = highlightWidth * widthFactor;

    // 对角高光（透明模式）使用相同的衰减曲线，保持一致性
    float diagonalMask = 0.0;
    if (highlightDiagonal != 0) {
        float backFacing = max(0.0, (-facing - rangeThreshold) / max(highlightRange, 0.01));
        // 使用相同的衰减曲线
        float diagWidthFactor = pow(saturate(backFacing), 0.4);
        float diagEffectiveWidth = highlightWidth * diagWidthFactor;
        
        // 对角高光在其有效宽度内平滑衰减
        if (sdf >= -diagEffectiveWidth && diagEffectiveWidth > 0.01) {
            float diagT = saturate(-sdf / diagEffectiveWidth);
            float diagFalloff = smoothstep(1.0, 0.0, diagT);
            diagonalMask = backFacing * diagFalloff * 0.8; // 对角高光强度最高为主高光的60%
        }
    }

    // 当前像素超出该边缘的有效宽度，跳过（不在高光带内）
    if (sdf < -effectiveWidth) {
        // 若对角高光也无效，返回原图
        if (diagonalMask < 0.001) return baseColor;
        // 否则只用对角高光
        float mask = saturate(diagonalMask * highlightSize);
        if (highlightMode == 0)
            return lerp(baseColor, float4(1, 1, 1, baseColor.a), mask);
        float3 hsvD = rgb2hsv(baseColor.rgb);
        hsvD.z = min(1.0, hsvD.z + 0.8 * mask);
        hsvD.y = min(1.0, hsvD.y + 0.08 * mask);
        return float4(hsv2rgb(hsvD), baseColor.a);
    }

    // 距离衰减：在有效高光带宽（effectiveWidth）内进行内外衰减
    // 只对实际有高光的区域（effectiveWidth > 0）进行衰减
    float t = saturate(-sdf / max(effectiveWidth, 0.01)); // 0=边缘, 1=有效宽度最深处
    float edgeFalloff = smoothstep(1.0, 0.0, t);

    // 主高光mask：角度决定是否有高光，距离决定衰减程度
    float primaryMask = frontFacing * edgeFalloff;

    float mask = saturate((primaryMask + diagonalMask) * highlightSize); // 综合主高光和对角高光，控制整体强度

    // --- 高光mask高斯模糊（2像素半径，5点近似） ---
    float2 blurStep = 2.0 * sdfTexelSize;
    float maskC = mask;
    float maskL = mask, maskR = mask, maskU = mask, maskD = mask;
    // 采样mask的上下左右
    {
        float sdfL = sdfTexture.Sample(linearSampler, sdfUV + float2(-blurStep.x, 0));
        float tL = saturate(-sdfL / max(effectiveWidth, 0.01));
        float edgeFalloffL = smoothstep(1.0, 0.0, tL);
        maskL = saturate((frontFacing * edgeFalloffL + diagonalMask) * highlightSize);

        float sdfR = sdfTexture.Sample(linearSampler, sdfUV + float2(blurStep.x, 0));
        float tR = saturate(-sdfR / max(effectiveWidth, 0.01));
        float edgeFalloffR = smoothstep(1.0, 0.0, tR);
        maskR = saturate((frontFacing * edgeFalloffR + diagonalMask) * highlightSize);

        float sdfU = sdfTexture.Sample(linearSampler, sdfUV + float2(0, blurStep.y));
        float tU = saturate(-sdfU / max(effectiveWidth, 0.01));
        float edgeFalloffU = smoothstep(1.0, 0.0, tU);
        maskU = saturate((frontFacing * edgeFalloffU + diagonalMask) * highlightSize);

        float sdfD = sdfTexture.Sample(linearSampler, sdfUV + float2(0, -blurStep.y));
        float tD = saturate(-sdfD / max(effectiveWidth, 0.01));
        float edgeFalloffD = smoothstep(1.0, 0.0, tD);
        maskD = saturate((frontFacing * edgeFalloffD + diagonalMask) * highlightSize);
    }
    // 高斯权重: 中心0.4，四邻域各0.15
    mask = maskC * 0.4 + (maskL + maskR + maskU + maskD) * 0.15;

    float4 result;
    if (highlightMode == 0) {
        // 模式0：叠加白色高光
        result = lerp(baseColor, float4(1, 1, 1, baseColor.a), mask);
    } else {
        // 模式1：微提亮+微增饱和度（保留原色调，减少过度色彩变化）
        float3 hsv = rgb2hsv(baseColor.rgb);
        hsv.z = min(1.0, hsv.z + 0.8 * mask);    // 亮度：轻微提亮
        hsv.y = min(1.0, hsv.y + 0.08 * mask);   // 饱和度：小幅增加
        result = float4(hsv2rgb(hsv), baseColor.a);
    }
    return result;
}


