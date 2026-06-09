/*
 * 文件名: apple_rounded_rect_perfect.hlsl
 * 功能: 苹果圆角矩形SDF生成 - GPU Compute Shader (完全GPU化)
 */

// ============================================================
//  资源绑定
// ============================================================

// 输出SDF (R32_FLOAT)
RWTexture2D<float> OutputSDF : register(u0);

// 常量缓冲区
cbuffer AppleRoundedRectParams : register(b0) {
    float2 rectSize;        // 矩形尺寸 (width, height)
    float cornerRadius;     // 圆角半径 (像素值)
    float radiusRatio;      // 圆角半径比例 [0, 1]
    float2 centerOffset;    // 中心偏移 (用于缩放居中)
    float scale;            // 整体缩放 [0, 1]
    float _padding;
};

// ============================================================
//  计算超椭圆指数 p (GPU版本，与CPU完全一致)
// ============================================================

float ComputeSquircleP(float radiusRatio, float maxRadius, float pMin, float pMax) {
    /*
     * 计算超椭圆指数 p
     * 使用 Hermite 平滑插值 (smoothstep)
     * 
     * Args:
     *   radiusRatio: 圆角半径比例 [0, 1]
     *   maxRadius: 最大圆角半径 (最小边的一半)
     *   pMin: p最小值 (大圆角时, 默认2.0)
     *   pMax: p最大值 (小圆角时, 默认5.0)
     */
    
    if (maxRadius < 1e-6) {
        return pMax;
    }
    
    float t = min(radiusRatio / maxRadius, 1.0);
    float tSmooth = t * t * (3.0 - 2.0 * t);  // smoothstep
    
    return pMax - (pMax - pMin) * tSmooth;
}

// ============================================================
//  苹果圆角SDF - Lp范数 (Squircle)
// ============================================================

float ApplePerfectRoundedRectSDF(float2 pos, float2 size, float radius, float p) {
    // 1. 转换到中心坐标系
    float2 halfSize = size * 0.5;
    float2 localPos = pos - halfSize;

    // 2. 四重对称：折叠到第一象限
    float2 q = abs(localPos);

    // 3. 限制圆角半径
    float r = min(radius, min(halfSize.x, halfSize.y));

    // 4. 无圆角（快速路径）
    if (r < 1e-6) {
        float2 d = q - halfSize;
        float outside = length(max(d, 0.0));
        float inside  = min(max(d.x, d.y), 0.0);
        return outside + inside;
    }

    // 5. 内缩矩形（角部圆心所在的矩形）
    float2 innerHalf = halfSize - float2(r, r);

    // 6. 角部局部坐标
    float2 cl = max(q - innerHalf, 0.0);

    // 7. 角部 vs 直线段
    bool inCorner = (q.x > innerHalf.x) && (q.y > innerHalf.y);

    float sdf;

    if (inCorner) {
        // Lp 范数: (qx^p + qy^p)^(1/p) - r
        float lp = pow(pow(cl.x, p) + pow(cl.y, p), 1.0 / p);
        sdf = lp - r;
    } else {
        // 标准矩形 SDF
        float2 d = q - halfSize;
        float outside = length(max(d, 0.0));
        float inside  = min(max(d.x, d.y), 0.0);
        sdf = outside + inside;
    }

    return sdf;
}

// ============================================================
//  主Compute Shader入口
// ============================================================

[numthreads(8, 8, 1)]
void CSGenerateAppleRoundedRect(uint3 DTid : SV_DispatchThreadID) {
    // 像素中心坐标
    float2 pos = float2(DTid.xy) + 0.5;

    // 应用缩放
    float2 scaledSize = rectSize * scale;
    float scaledRadius = cornerRadius * scale;
    
    // 计算p值 (GPU端自动计算)
    float minDim = min(scaledSize.x, scaledSize.y);
    float maxRadius = minDim * 0.5;
    float rClamped = clamp(scaledRadius, 0.0, maxRadius);
    float p = ComputeSquircleP(rClamped, maxRadius, 2.0, 5.0);

    // 计算位置偏移
    float2 adjustedPos = pos - centerOffset;

    // 计算苹果圆角SDF
    float sdf = ApplePerfectRoundedRectSDF(
        adjustedPos,
        scaledSize,
        scaledRadius,
        p
    );

    OutputSDF[DTid.xy] = sdf;
}

// ============================================================
//  SDF → 掩码
// ============================================================

RWTexture2D<unorm float> OutputMask : register(u1);

cbuffer MaskParams : register(b1) {
    float smoothRadius;
    float3 _padding2;
};

[numthreads(8, 8, 1)]
void CSSDFToMask(uint3 DTid : SV_DispatchThreadID) {
    float sdf = OutputSDF[DTid.xy];
    float alpha = saturate(0.5 - sdf / (2.0 * smoothRadius));
    OutputMask[DTid.xy] = alpha;
}

// ============================================================
//  调试可视化
// ============================================================

RWTexture2D<float4> DebugOutput : register(u2);

[numthreads(8, 8, 1)]
void CSVisualizeDistanceField(uint3 DTid : SV_DispatchThreadID) {
    float sdf = OutputSDF[DTid.xy];

    float4 color;
    if (sdf < 0.0) {
        float t = saturate(-sdf / 50.0);
        color = float4(0.0, 0.5 * t, 1.0, 1.0);
    } else {
        float t = saturate(sdf / 50.0);
        color = float4(1.0, 0.5 * (1.0 - t), 0.0, 1.0);
    }

    if (abs(sdf) < 1.0) {
        color = lerp(color, float4(1, 1, 1, 1), 0.5);
    }

    DebugOutput[DTid.xy] = color;
}