/*
 * 文件名: color_grading_effect.hlsl
 * 功能: 综合调色特效
 *
 * 集成的调色功能（按处理顺序）：
 *   1. 曝光量 (Exposure)     - EV曝光stops调整
 *   2. 伽马 (Gamma)          - 幂次曲线校正
 *   3. 色彩平衡 (Color Balance) - 阴影/中间调/高光分区着色
 *   4. 色温/色调 (Temp/Tint) - 白平衡冷暖偏移
 *   5. 高光/阴影 (Hi/Shadow) - 压缩亮部，提升暗部
 *   6. 亮度 (Brightness)     - 线性偏移
 *   7. 对比度 (Contrast)     - 围绕0.5中点拉伸
 *   8. 饱和度 (Saturation)   - HSV空间整体饱和度
 *   9. 色相偏移 (Hue Shift)  - HSV色相旋转
 *  10. 自然饱和度 (Vibrance)  - 保护高饱和色，只提升低饱和色
 *  11. 褪色 (Fadeout)        - 提升黑位，模拟胶片感
 *  12. 暗角 (Vignette)       - 边缘压暗
 */

cbuffer ColorGradingParams : register(b0) {
    // Block 0: 基础色调 (16 bytes)
    float brightness;        //  0: 亮度偏移    (-1.0 ~ 1.0,  0 = 默认)
    float contrast;          //  4: 对比度       ( 0.0 ~ 3.0,  1 = 默认)
    float saturation;        //  8: 饱和度       ( 0.0 ~ 3.0,  1 = 默认)
    float hueShift;          // 12: 色相旋转     (-0.5 ~ 0.5,  0 = 默认)

    // Block 1: 曝光与白平衡 (16 bytes)
    float exposure;          // 16: 曝光量(EV)  (-3.0 ~ 3.0,  0 = 默认)
    float gamma;             // 20: 伽马         ( 0.1 ~ 5.0,  1 = 默认)
    float temperature;       // 24: 色温偏移     (-1.0 ~ 1.0,  0=默认, 正=暖/橙, 负=冷/蓝)
    float tintStrength;      // 28: 色调叠加强度 ( 0.0 ~ 1.0,  0 = 不叠加)

    // Block 2: 色调范围 (16 bytes)
    float highlights;        // 32: 高光压缩     (-1.0 ~ 1.0,  0 = 默认, 负=压暗高光)
    float shadows;           // 36: 阴影提升     (-1.0 ~ 1.0,  0 = 默认, 正=提亮阴影)
    float vibrance;          // 40: 自然饱和度   (-1.0 ~ 2.0,  0 = 默认)
    float fadeout;           // 44: 褪色/黑位提升 (0.0 ~ 0.5,  0 = 默认)

    // Block 3: 暗角 (16 bytes)
    float vignetteStrength;  // 48: 暗角强度     ( 0.0 ~ 1.0,  0 = 无暗角)
    float vignetteRadius;    // 52: 暗角起始半径 ( 0.0 ~ 1.0,  0.5 = 默认)
    float vignetteSoftness;  // 56: 暗角柔化程度 ( 0.0 ~ 1.0,  0.5 = 默认)
    float _padding0;         // 60

    // Block 4: 色彩平衡 - 阴影区域着色 (16 bytes)
    float shadowR;           // 64: 阴影区域 R 偏移 (-1 ~ 1)
    float shadowG;           // 68: 阴影区域 G 偏移 (-1 ~ 1)
    float shadowB;           // 72: 阴影区域 B 偏移 (-1 ~ 1)
    float _padding1;         // 76

    // Block 5: 色彩平衡 - 中间调着色 (16 bytes)
    float midtoneR;          // 80: 中间调 R 偏移 (-1 ~ 1)
    float midtoneG;          // 84: 中间调 G 偏移 (-1 ~ 1)
    float midtoneB;          // 88: 中间调 B 偏移 (-1 ~ 1)
    float _padding2;         // 92

    // Block 6: 色彩平衡 - 高光区域着色 (16 bytes)
    float highlightR;        // 96:  高光区域 R 偏移 (-1 ~ 1)
    float highlightG;        // 100: 高光区域 G 偏移 (-1 ~ 1)
    float highlightB;        // 104: 高光区域 B 偏移 (-1 ~ 1)
    float _padding3;         // 108

    // Block 7: 纹理尺寸 (16 bytes)
    float texWidth;          // 112
    float texHeight;         // 116
    float _padding4[2];      // 120-128

    // Block 8: 色调颜色 (16 bytes)
    float tintR;             // 128: 色调颜色 R (0.0 ~ 1.0)
    float tintG;             // 132: 色调颜色 G (0.0 ~ 1.0)
    float tintB;             // 136: 色调颜色 B (0.0 ~ 1.0)
    float _padding5;         // 140

    // Block 9: SDF 位置 (16 bytes)
    float sdfPosX;           // 144: SDF 在屏幕上的 X 坐标
    float sdfPosY;           // 148: SDF 在屏幕上的 Y 坐标
    float _padding6[2];      // 152-160
    // Total: 160 bytes (16字节对齐 ✓)
};

Texture2D<float4> inputTexture : register(t0);
Texture2D<float>  sdfTexture   : register(t1);
SamplerState      linearSampler : register(s0);

struct VSOutput {
    float4 pos : SV_POSITION;
    float2 uv  : TEXCOORD0;
};

// ============================================================
//  辅助函数
// ============================================================

// RGB → HSV
float3 RGBtoHSV(float3 c) {
    float4 K = float4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    float4 p = lerp(float4(c.bg, K.wz), float4(c.gb, K.xy), step(c.b, c.g));
    float4 q = lerp(float4(p.xyw, c.r), float4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return float3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

// HSV → RGB
float3 HSVtoRGB(float3 c) {
    float4 K = float4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    float3 p = abs(frac(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * lerp(K.xxx, saturate(p - K.xxx), c.y);
}

// 计算像素亮度（感知加权）
float Luminance(float3 c) {
    return dot(c, float3(0.2126, 0.7152, 0.0722));
}

// 色彩平衡遮罩（阴影/中间调/高光权重）
// 基于亮度的柔和分区，三个权重之和约为1
void ColorBalanceMasks(float lum, out float shadowMask, out float midtoneMask, out float highlightMask) {
    // 阴影：暗部最强，向亮部衰减
    shadowMask    = saturate(1.0 - smoothstep(0.0, 0.6, lum));
    // 高光：亮部最强，向暗部衰减
    highlightMask = saturate(smoothstep(0.4, 1.0, lum));
    // 中间调：0.5处最强，向两端衰减（用bell curve）
    midtoneMask   = saturate(1.0 - abs(lum - 0.5) * 2.5);
    // 归一化（可选，保证不过曝）
    float total = shadowMask + midtoneMask + highlightMask + 1e-6;
    shadowMask    /= total;
    midtoneMask   /= total;
    highlightMask /= total;
}

// ============================================================
//  Pixel Shader
// ============================================================

float4 PSMain(VSOutput input) : SV_TARGET {
    float4 col = inputTexture.Sample(linearSampler, input.uv);

    // SDF 遮罩：只对SDF内部像素应用调色，外部直接返回原图
    uint sdfW, sdfH;
    sdfTexture.GetDimensions(sdfW, sdfH);
    float2 sdfUV = (input.pos.xy - float2(sdfPosX, sdfPosY)) / float2(sdfW, sdfH);
    float sdf = sdfTexture.Sample(linearSampler, sdfUV);
    if (sdf >= 0.0) {
        return float4(col.rgb, 1.0);
    }

    float3 c = col.rgb;

    // ----------------------------------------------------------
    // 1. 曝光量 (Exposure)
    //    将 EV stops 转换为线性乘数：1 stop = ×2
    // ----------------------------------------------------------
    c *= pow(2.0, exposure);

    // ----------------------------------------------------------
    // 2. 伽马 (Gamma)
    //    c = c^(1/gamma)，gamma>1 压暗，<1 提亮中间调
    // ----------------------------------------------------------
    if (gamma > 0.01) {
        c = pow(max(c, 0.0), 1.0 / gamma);
    }

    // ----------------------------------------------------------
    // 3. 色彩平衡 (Color Balance)
    //    分阴影/中间调/高光三区域，独立着色
    // ----------------------------------------------------------
    {
        float lum = Luminance(c);
        float sM, mM, hM;
        ColorBalanceMasks(lum, sM, mM, hM);

        float3 shadowShift    = float3(shadowR,    shadowG,    shadowB)    * sM;
        float3 midtoneShift   = float3(midtoneR,   midtoneG,   midtoneB)   * mM;
        float3 highlightShift = float3(highlightR, highlightG, highlightB) * hM;

        c += (shadowShift + midtoneShift + highlightShift) * 0.5;
        c = saturate(c);
    }

    // ----------------------------------------------------------
    // 4. 色温 (Temperature) + 色调颜色叠加 (Tint)
    //    temperature > 0: 暖色调（+R, -B），< 0: 冷色调（-R, +B）
    //    tintStrength > 0: 将像素颜色与 tintColor 混合（颜色滤镜）
    //        强度=0: 原图不变；强度=1: 全部变为 tintColor
    // ----------------------------------------------------------
    c.r = saturate(c.r + temperature * 0.2);
    c.b = saturate(c.b - temperature * 0.2);
    if (tintStrength > 0.001) {
        float3 tintColor = float3(tintR, tintG, tintB);
        c = lerp(c, tintColor, tintStrength);
    }

    // ----------------------------------------------------------
    // 5. 高光压缩 / 阴影提升
    //    highlights < 0: 压暗高光（亮部向中间靠拢）
    //    shadows    > 0: 提亮阴影（暗部向中间靠拢）
    // ----------------------------------------------------------
    {
        float lum = Luminance(c);
        // 高光遮罩：亮部平滑权重
        float hiMask  = smoothstep(0.3, 1.0, lum);
        // 阴影遮罩：暗部平滑权重
        float shMask  = 1.0 - smoothstep(0.0, 0.7, lum);

        // highlights < 0 时压低高光；> 0 时提亮高光
        c += highlights * hiMask * 0.5;
        // shadows > 0 时提亮阴影；< 0 时压低阴影
        c += shadows * shMask * 0.5;
        c = saturate(c);
    }

    // ----------------------------------------------------------
    // 6. 亮度 (Brightness)
    //    简单线性偏移
    // ----------------------------------------------------------
    c = saturate(c + brightness);

    // ----------------------------------------------------------
    // 7. 对比度 (Contrast)
    //    以 0.5 为中点拉伸/压缩
    // ----------------------------------------------------------
    c = saturate((c - 0.5) * contrast + 0.5);

    // ----------------------------------------------------------
    // 8. 饱和度 (Saturation) + 9. 色相偏移 (Hue Shift)
    //    在 HSV 空间操作
    // ----------------------------------------------------------
    {
        float3 hsv = RGBtoHSV(c);
        // 色相偏移：hueShift ∈ [-0.5, 0.5]，对应 -180°~180°
        hsv.x = frac(hsv.x + hueShift);
        // 饱和度整体缩放
        hsv.y = saturate(hsv.y * saturation);
        c = HSVtoRGB(hsv);
    }

    // ----------------------------------------------------------
    // 10. 自然饱和度 (Vibrance)
    //     只提升低饱和像素，保护已经饱和的颜色
    //     使得图像整体更鲜艳，但不会导致高饱和区过曝
    // ----------------------------------------------------------
    if (abs(vibrance) > 0.001) {
        float3 hsv = RGBtoHSV(c);
        // 当前饱和度越低，vibrance影响越大；高饱和时接近0影响
        float vibranceMask = 1.0 - hsv.y;
        hsv.y = saturate(hsv.y + vibrance * vibranceMask * 0.8);
        c = HSVtoRGB(hsv);
    }

    // ----------------------------------------------------------
    // 11. 褪色/胶片感 (Fadeout)
    //     提升黑位（Lift blacks），模拟胶片打印的柔和阴影
    //     fadeout = 0 时无效果，0.3 时阴影被提亮成灰
    // ----------------------------------------------------------
    c = lerp(c, float3(1, 1, 1) * fadeout, fadeout);

    // ----------------------------------------------------------
    // 12. 暗角 (Vignette)
    //     基于UV到屏幕中心距离的椭圆形压暗
    // ----------------------------------------------------------
    if (vignetteStrength > 0.001) {
        float2 centeredUV = input.uv - 0.5;
        // 椭圆距离（使用纹理宽高比修正为圆形暗角）
        float aspect = texWidth / max(texHeight, 1.0);
        centeredUV.x *= aspect;
        float dist = length(centeredUV) * 2.0;  // [0, ~1.4] 范围

        // smoothstep 控制暗角边缘柔化
        // dist < vignetteRadius: 无暗角
        // dist > vignetteRadius + softness: 最大暗角
        float vignetteStart = vignetteRadius;
        float vignetteEnd   = vignetteRadius + vignetteSoftness;
        float vignetteMask  = smoothstep(vignetteStart, vignetteEnd, dist);

        // 压暗（multiply towards black）
        c *= (1.0 - vignetteMask * vignetteStrength);
    }

    // 注意：Desktop Duplication 截图 alpha 通道恒为 0，color grading 作为全帧处理
    // 强制输出 alpha=1，确保像素不因透明而消失
    return float4(saturate(c), 1.0);
}
