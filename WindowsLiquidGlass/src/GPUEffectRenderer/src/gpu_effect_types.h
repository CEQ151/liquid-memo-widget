/*
 * 文件名: gpu_effect_types.h
 * 功能: GPU特效系统类型定义
 */

#pragma once

#include <DirectXMath.h>

// 特效类型枚举
enum class GPUEffectType {
    Stroke = 0,          // 边框特效
    Flow = 1,            // 光流特效
    ChromaticAberration = 2,  // 色散特效
    Highlight = 3,         // 高光特效
    Blur = 4,            // 高斯模糊特效
    AntiAliasing = 5,    // 抗锯齿特效
    ColorGrading = 6,    // 综合调色特效
    ColorOverlay = 7,    // 颜色叠加滤镜特效
};

// ============================================================
//  特效坐标变换参数 (32字节, 对齐到16字节)
// ============================================================

struct EffectTransform {
    float posX;          // 4 bytes
    float posY;          // 4 bytes
    float scaleX;        // 4 bytes
    float scaleY;        // 4 bytes
    float rotation;      // 4 bytes
    float _padding[3];   // 12 bytes
    // Total: 32 bytes (16字节对齐 ✓)
    
    EffectTransform() 
        : posX(0), posY(0), scaleX(1.0f), scaleY(1.0f), rotation(0) {
        _padding[0] = _padding[1] = _padding[2] = 0;
    }
};

// ============================================================
//  边框特效参数 (64字节, 对齐到16字节)
// ============================================================

struct StrokeEffectParams {
    // 第一部分: EffectTransform (32字节)
    float posX;          // 0-4
    float posY;          // 4-8
    float scaleX;        // 8-12
    float scaleY;        // 12-16
    
    // 第二部分: 边框参数 (16字节)
    float strokeWidth;   // 16-20
    float smoothness;    // 20-24
    float _padding1[2];  // 24-32
    
    // 第三部分: 颜色 (16字节)
    float color[4];      // 32-48 (RGBA)
    
    // 第四部分: 对齐填充 (16字节)
    float _padding2[4];  // 48-64
    
    // Total: 64 bytes (16字节对齐 ✓)
    
    StrokeEffectParams() 
        : posX(0), posY(0), scaleX(1.0f), scaleY(1.0f),
          strokeWidth(1.0f), smoothness(1.0f) {
        color[0] = 1.0f; color[1] = 1.0f; color[2] = 1.0f; color[3] = 1.0f;
        _padding1[0] = _padding1[1] = 0;
        _padding2[0] = _padding2[1] = _padding2[2] = _padding2[3] = 0;
    }
};

// 编译时断言，确保结构体大小正确
static_assert(sizeof(StrokeEffectParams) % 16 == 0, "StrokeEffectParams must be 16-byte aligned");
static_assert(sizeof(StrokeEffectParams) == 64, "StrokeEffectParams must be 64 bytes");

// ============================================================
//  光流特效参数 (64字节, 对齐到16字节)
// ============================================================

struct FlowEffectParams {
    // 第一部分: EffectTransform (16字节)
    float posX;          // 0-4
    float posY;          // 4-8
    float scaleX;        // 8-12
    float scaleY;        // 12-16
    
    // 第二部分: 光流参数 (16字节)
    float flowStrength;  // 16-20: 流动强度 (1.0-5.0)
    float flowWidth;     // 20-24: 流动区域宽度 (像素)
    float flowFalloff;   // 24-28: 衰减曲线指数 (0.5-3.0)
    float _padding1;     // 28-32
    
    // 第三部分: 纹理尺寸信息 (16字节)
    float texWidth;      // 32-36: 纹理宽度
    float texHeight;     // 36-40: 纹理高度
    float _padding2[2];  // 40-48
    
    // 第四部分: 对齐填充 (16字节)
    float _padding3[4];  // 48-64
    
    // Total: 64 bytes (16字节对齐 ✓)
    
    FlowEffectParams() 
        : posX(0), posY(0), scaleX(1.0f), scaleY(1.0f),
          flowStrength(2.0f), flowWidth(60.0f), flowFalloff(5.0f),
          texWidth(0), texHeight(0), _padding1(0) {
        _padding2[0] = _padding2[1] = 0;
        _padding3[0] = _padding3[1] = _padding3[2] = _padding3[3] = 0;
    }
};

// 编译时断言，确保结构体大小正确
static_assert(sizeof(FlowEffectParams) % 16 == 0, "FlowEffectParams must be 16-byte aligned");
static_assert(sizeof(FlowEffectParams) == 64, "FlowEffectParams must be 64 bytes");

// ============================================================
//  色散特效参数 (64字节, 对齐到16字节)
// ============================================================

struct ChromaticEffectParams {
    // 第一部分: EffectTransform (16字节)
    float posX;           // 0-4
    float posY;           // 4-8
    float scaleX;         // 8-12
    float scaleY;         // 12-16
    
    // 第二部分: 色散参数 (16字节)
    float chromaticStrength;  // 16-20: 色散强度 (像素, 0.0-10.0)
    float chromaticWidth;      // 20-24: 色散区域宽度 (像素)
    float chromaticFalloff;    // 24-28: 衰减曲线指数 (0.5-3.0)
    float _padding1;           // 28-32
    
    // 第三部分: RGB通道偏移比例 (16字节)
    float channelOffsetR;      // 32-36: R通道偏移比例 (default: 1.0)
    float channelOffsetG;      // 36-40: G通道偏移比例 (default: 0.0)
    float channelOffsetB;      // 40-44: B通道偏移比例 (default: -1.0)
    float _padding2;           // 44-48
    
    // 第四部分: 纹理尺寸信息 (16字节)
    float texWidth;            // 48-52: 纹理宽度
    float texHeight;           // 52-56: 纹理高度
    float _padding3[2];        // 56-64
    
    // Total: 64 bytes (16字节对齐 ✓)
    
    ChromaticEffectParams() 
        : posX(0), posY(0), scaleX(1.0f), scaleY(1.0f),
          chromaticStrength(5.0f), chromaticWidth(80.0f), chromaticFalloff(2.0f),
          channelOffsetR(1.0f), channelOffsetG(0.0f), channelOffsetB(-1.0f),
          texWidth(0), texHeight(0), _padding1(0), _padding2(0) {
        _padding3[0] = _padding3[1] = 0;
    }
};

// 编译时断言，确保结构体大小正确
static_assert(sizeof(ChromaticEffectParams) % 16 == 0, "ChromaticEffectParams must be 16-byte aligned");
static_assert(sizeof(ChromaticEffectParams) == 64, "ChromaticEffectParams must be 64 bytes");

// ============================================================
//  高光特效参数 (64字节, 对齐到16字节)
// ============================================================

struct HighlightEffectParams {
    // 第一部分: 高光参数 (24字节)
    float highlightWidth;      // 高光宽度（像素）
    float highlightAngle;      // 高光角度（弧度，0为水平右侧，逆时针）
    int   highlightMode;       // 模式（0=白色高光，1=提亮原色）
    int   highlightDiagonal;   // 是否对角生成高光（0/1）
    float highlightSize;       // 高光大小（光线宽度，像素）
    float highlightRange;      // 高光影响范围（0~1，1.0=默认，0.5=一半）
    float _padding1[2];        // 填充
    // 第二部分: 纹理尺寸 (8字节)
    float texWidth;
    float texHeight;
    float _padding2[2];        // 填充 40-48
    // 第三部分: SDF 变换 (16字节)
    float posX;                // 48: SDF 在屏幕上的 X 坐标
    float posY;                // 52: SDF 在屏幕上的 Y 坐标
    float scaleX;              // 56: SDF 横向缩放
    float scaleY;              // 60: SDF 纵向缩放
    // Total: 64 bytes
    HighlightEffectParams()
        : highlightWidth(20.0f), highlightAngle(0.0f), highlightMode(0), highlightDiagonal(0),
          highlightSize(10.0f), highlightRange(1.0f), texWidth(0), texHeight(0),
          posX(0), posY(0), scaleX(1.0f), scaleY(1.0f) {
        _padding1[0] = _padding1[1] = 0;
        _padding2[0] = _padding2[1] = 0;
    }
};

static_assert(sizeof(HighlightEffectParams) % 16 == 0, "HighlightEffectParams must be 16-byte aligned");
static_assert(sizeof(HighlightEffectParams) == 64, "HighlightEffectParams must be 64 bytes");

// ============================================================
//  高斯模糊特效参数 (64字节, 对齐到16字节)
// ============================================================

struct BlurEffectParams {
    // 第一部分: 模糊参数 (4字节)
    float blurRadius;      // 模糊半径（像素）
    float _padding1[3];    // 填充
    // 第二部分: 纹理尺寸 (8字节)
    float texWidth;
    float texHeight;
    float _padding2[2];    // 填充 24-32
    // 第三部分: SDF 变换 (16字节)
    float posX;            // 32: SDF 在屏幕上的 X 坐标
    float posY;            // 36: SDF 在屏幕上的 Y 坐标
    float scaleX;          // 40: SDF 横向缩放
    float scaleY;          // 44: SDF 纵向缩放
    float _padding4[4];    // 填充到64字节
    // Total: 64 bytes
    BlurEffectParams()
        : blurRadius(3.0f), texWidth(0), texHeight(0),
          posX(0), posY(0), scaleX(1.0f), scaleY(1.0f) {
        _padding1[0] = _padding1[1] = _padding1[2] = 0;
        _padding2[0] = _padding2[1] = 0;
        _padding4[0] = _padding4[1] = _padding4[2] = _padding4[3] = 0;
    }
};

static_assert(sizeof(BlurEffectParams) % 16 == 0, "BlurEffectParams must be 16-byte aligned");
static_assert(sizeof(BlurEffectParams) == 64, "BlurEffectParams must be 64 bytes");

// ============================================================
//  抗锯齿特效参数 (64字节, 对齐到16字节)
// ============================================================

struct AntiAliasingEffectParams {
    // 第一部分: SDF变换 (16字节)
    float posX;          // 0-4
    float posY;          // 4-8
    float scaleX;        // 8-12
    float scaleY;        // 12-16

    // 第二部分: 抗锯齿参数 (16字节)
    float blurRadius;    // 16-20: 高斯模糊半径（像素）
    float edgeRange;     // 20-24: 边缘处理范围（像素，从边缘向内外扩展）
    float strength;      // 24-28: 抗锯齿强度 (0.0-1.0)
    float _padding1;     // 28-32

    // 第三部分: 纹理尺寸 (16字节)
    float texWidth;      // 32-36
    float texHeight;     // 36-40
    float _padding2[2];  // 40-48

    // 第四部分: 填充 (16字节)
    float _padding3[4];  // 48-64

    // Total: 64 bytes (16字节对齐 ✓)

    AntiAliasingEffectParams()
        : posX(0), posY(0), scaleX(1.0f), scaleY(1.0f),
          blurRadius(0.5f), edgeRange(0.5f), strength(1.0f),
          texWidth(0), texHeight(0), _padding1(0) {
        _padding2[0] = _padding2[1] = 0;
        _padding3[0] = _padding3[1] = _padding3[2] = _padding3[3] = 0;
    }
};

static_assert(sizeof(AntiAliasingEffectParams) % 16 == 0, "AntiAliasingEffectParams must be 16-byte aligned");
static_assert(sizeof(AntiAliasingEffectParams) == 64, "AntiAliasingEffectParams must be 64 bytes");

// ============================================================
//  综合调色特效参数 (144字节, 对齐到16字节)
//  集成：曝光/伽马/色彩平衡/色温色调/高光阴影/亮度/对比度/饱和度/色相/自然饱和度/褪色/暗角
// ============================================================

struct ColorGradingParams {
    // Block 0: 基础色调 (16 bytes)
    float brightness;        //  0: 亮度偏移    (-1.0 ~ 1.0,  0 = 默认)
    float contrast;          //  4: 对比度       ( 0.0 ~ 3.0,  1 = 默认)
    float saturation;        //  8: 饱和度       ( 0.0 ~ 3.0,  1 = 默认)
    float hueShift;          // 12: 色相旋转     (-0.5 ~ 0.5,  0 = 默认)

    // Block 1: 曝光与白平衡 (16 bytes)
    float exposure;          // 16: 曝光量(EV)  (-3.0 ~ 3.0,  0 = 默认)
    float gamma;             // 20: 伽马         ( 0.1 ~ 5.0,  1 = 默认)
    float temperature;       // 24: 色温偏移     (-1.0 ~ 1.0,  0=默认, 正=暖, 负=冷)
    float tintStrength;      // 28: 色调叠加强度 ( 0.0 ~ 1.0,  0 = 不叠加)

    // Block 2: 色调范围 (16 bytes)
    float highlights;        // 32: 高光压缩     (-1.0 ~ 1.0,  0 = 默认)
    float shadows;           // 36: 阴影提升     (-1.0 ~ 1.0,  0 = 默认)
    float vibrance;          // 40: 自然饱和度   (-1.0 ~ 2.0,  0 = 默认)
    float fadeout;           // 44: 褪色黑位提升  ( 0.0 ~ 0.5,  0 = 默认)

    // Block 3: 暗角 (16 bytes)
    float vignetteStrength;  // 48: 暗角强度     ( 0.0 ~ 1.0,  0 = 无暗角)
    float vignetteRadius;    // 52: 暗角起始半径 ( 0.0 ~ 1.0,  0.5 = 默认)
    float vignetteSoftness;  // 56: 暗角柔化程度 ( 0.0 ~ 1.0,  0.5 = 默认)
    float _padding0;         // 60

    // Block 4: 色彩平衡 - 阴影区域 (16 bytes)
    float shadowR;           // 64
    float shadowG;           // 68
    float shadowB;           // 72
    float _padding1;         // 76

    // Block 5: 色彩平衡 - 中间调 (16 bytes)
    float midtoneR;          // 80
    float midtoneG;          // 84
    float midtoneB;          // 88
    float _padding2;         // 92

    // Block 6: 色彩平衡 - 高光区域 (16 bytes)
    float highlightR;        // 96
    float highlightG;        // 100
    float highlightB;        // 104
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
    float posX;              // 144: SDF 在屏幕上的 X 坐标
    float posY;              // 148: SDF 在屏幕上的 Y 坐标
    float _padding6[2];      // 152-160

    // Total: 160 bytes (16字节对齐 ✓)

    ColorGradingParams()
        : brightness(0.0f), contrast(1.0f), saturation(1.0f), hueShift(0.0f),
          exposure(0.0f), gamma(1.0f), temperature(0.0f), tintStrength(0.0f),
          highlights(0.0f), shadows(0.0f), vibrance(0.0f), fadeout(0.0f),
          vignetteStrength(0.0f), vignetteRadius(0.5f), vignetteSoftness(0.5f),
          shadowR(0), shadowG(0), shadowB(0),
          midtoneR(0), midtoneG(0), midtoneB(0),
          highlightR(0), highlightG(0), highlightB(0),
          texWidth(0), texHeight(0),
          tintR(1.0f), tintG(1.0f), tintB(1.0f),
          posX(0.0f), posY(0.0f),
          _padding0(0), _padding1(0), _padding2(0), _padding3(0), _padding5(0) {
        _padding4[0] = _padding4[1] = 0;
        _padding6[0] = _padding6[1] = 0;
    }
};

static_assert(sizeof(ColorGradingParams) % 16 == 0,   "ColorGradingParams must be 16-byte aligned");
static_assert(sizeof(ColorGradingParams) == 160,       "ColorGradingParams must be 160 bytes");

// ============================================================
//  颜色叠加滤镜特效参数 (32字节, 对齐到16字节)
// ============================================================

struct ColorOverlayParams {
    // Block 0: 叠加颜色 (16 bytes)
    float overlayR;     //  0: 叠加颜色 R (0.0 ~ 1.0)
    float overlayG;     //  4: 叠加颜色 G (0.0 ~ 1.0)
    float overlayB;     //  8: 叠加颜色 B (0.0 ~ 1.0)
    float overlayA;     // 12: 叠加强度   (0.0 ~ 1.0)

    // Block 1: SDF 位置 (16 bytes)
    float posX;         // 16: SDF 在屏幕上的 X 坐标
    float posY;         // 20: SDF 在屏幕上的 Y 坐标
    float _padding[2];  // 24-32

    // Total: 32 bytes (16字节对齐 ✓)

    ColorOverlayParams()
        : overlayR(1.0f), overlayG(1.0f), overlayB(1.0f), overlayA(0.0f),
          posX(0.0f), posY(0.0f) {
        _padding[0] = _padding[1] = 0;
    }
};

static_assert(sizeof(ColorOverlayParams) % 16 == 0, "ColorOverlayParams must be 16-byte aligned");
static_assert(sizeof(ColorOverlayParams) == 32,     "ColorOverlayParams must be 32 bytes");
