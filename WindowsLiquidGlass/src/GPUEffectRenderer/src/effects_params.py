"""特效参数定义

每个参数格式：
    type:    "float" | "int" | "bool" | "color" | "vec3"
    default: 默认值
    min/max: 数值范围（float/int 类型）
    options: 可选值列表（int 枚举类型）
    label:   UI 显示名称
    desc:    参数说明

添加新特效时：
  1. 在 EffectType 枚举中新增值
  2. 在 EFFECT_TYPE_MAPPING 中新增映射
  3. 在 EFFECTS_PARAMS 中新增参数定义
  4. 在 C++ 侧写 REGISTER_EFFECT 宏，其余文件无需修改
"""

from enum import IntEnum


class EffectType(IntEnum):
    """特效类型枚举（值与 C++ GPUEffectType 一致）"""
    STROKE              = 0
    FLOW                = 1
    CHROMATIC_ABERRATION = 2
    HIGHLIGHT           = 3
    BLUR                = 4
    ANTI_ALIASING       = 5
    COLOR_GRADING       = 6
    COLOR_OVERLAY       = 7


EFFECT_TYPE_MAPPING = {
    EffectType.STROKE:               "stroke",
    EffectType.FLOW:                 "flow",
    EffectType.CHROMATIC_ABERRATION: "chromatic_aberration",
    EffectType.HIGHLIGHT:            "highlight",
    EffectType.BLUR:                 "blur",
    EffectType.ANTI_ALIASING:        "anti_aliasing",
    EffectType.COLOR_GRADING:        "color_grading",
    EffectType.COLOR_OVERLAY:        "color_overlay",
}



EFFECTS_PARAMS = {

    # ================================================================
    #  描边特效
    # ================================================================
    # "stroke": {
    #     "enable": False,
    #     "stroke_width": {
    #         "type": "float", 
    #         "value": 2.0,
    #         "default": 2.0, "min": 0.0, "max": 50.0,
    #         "label": "描边宽度", "desc": "描边宽度（像素）",
    #     },
    #     "color": {
    #         "type": "color", 
    #         "value": (1.0, 0.0, 0.0, 1.0),
    #         "default": (1.0, 0.0, 0.0, 1.0),
    #         "label": "描边颜色", "desc": "RGBA，范围 0~1",
    #     },
    #     "smoothness": {
    #         "type": "float", 
    #         "value": 1.0,
    #         "default": 1.0, "min": 0.0, "max": 5.0,
    #         "label": "平滑度", "desc": "值越大边缘越柔和",
    #     },
    # },

    # ================================================================
    #  光流特效
    # ================================================================
    "flow": {
        "enable": True,
        "label": "光流特效", "desc": "控制光流效果的参数",
        "params": {
            "flow_strength": {
                "type": "float", 
                "value": 2.0,
                "default": 2.0, "min": 1.0, "max": 5.0,
                "label": "流动强度", "desc": "边缘放大幅度，值越大膨胀越明显",
            },
            "flow_width": {
                "type": "int", 
                "value": 60,
                "default": 60, "min": 0, "max": 200,
                "label": "流动宽度", "desc": "流动带宽度（像素）",
            },
            "flow_falloff": {
                "type": "float", 
                "value": 5.0,
                "default": 5.0, "min": 0.5, "max": 10.0,
                "label": "衰减曲线", "desc": "过渡平滑指数，值越大边缘越锐利",
            },
        }
    },

    # ================================================================
    #  色散特效
    # ================================================================
    "chromatic_aberration": {
        "enable": True,
        "label": "色散特效", "desc": "控制色散效果的参数",
        "params": {
            "chromatic_strength": {
                "type": "float", 
                "value": 5.0,
                "default": 5.0, "min": 0.0, "max": 20.0,
                "label": "色散强度", "desc": "RGB 通道最大偏移距离（像素)",
            },
            "chromatic_width": {
                "type": "int", 
                "value": 60,
                "default": 60, "min": 0, "max": 200,
                "label": "色散宽度", "desc": "色散带宽度（像素）",
            },
            "chromatic_falloff": {
                "type": "float", 
                "value": 3.0,
                "default": 3.0, "min": 0.5, "max": 5.0,
                "label": "衰减曲线", "desc": "过渡平滑指数",
            },
            "offset_r": {
                "type": "float", 
                "value": 1.0,
                "default": 1.0, "min": -1.0, "max": 1.0,
                "label": "R 通道方向", "desc": "R 通道沿梯度方向偏移比例",
            },
            "offset_g": {
                "type": "float", 
                "value": 0.0,
                "default": 0.0, "min": -1.0, "max": 1.0,
                "label": "G 通道方向", "desc": "G 通道沿梯度方向偏移比例",
            },
            "offset_b": {
                "type": "float", "value": -1.0,
                "default": -1.0, "min": -1.0, "max": 1.0,
                "label": "B 通道方向", "desc": "B 通道沿梯度方向偏移比例",
            },
        }
    },

    # ================================================================
    #  边缘高光特效
    # ================================================================
    "highlight": {
        "enable": True,
        "label": "边缘高光特效", "desc": "控制边缘高光效果的参数",
        "params": {
            "width": {
                "type": "float", "value": 5.0,
                "default": 5.0, "min": 0.0, "max": 50.0,
                "label": "高光宽度", "desc": "SDF 从 0 向内的高光带宽度（像素）",
            },
            "angle": {
                "type": "int", "value": 225,
                "default": 225, "min": 0, "max": 360,
                "label": "光照角度", "desc": "光源方向（度），0=右，90=上",
            },
            "strength": {
                "type": "float", "value": 1.0,
                "default": 1.0, "min": 0.0, "max": 1.0,
                "label": "高光强度", "desc": "整体亮度系数",
            },
            "range": {
                "type": "float", "value": 0.3,
                "default": 0.3, "min": 0.0, "max": 1.0,
                "label": "覆盖范围", "desc": "高光在边缘圆周上的覆盖比例，1=半圈",
            },
            "mode": {
                "type": "int", "value": 1, "default": 1, "min": 0, "max": 1,
                "label": "高光模式", "desc": "0=叠加白色高光，1=提亮+微增饱和度",
            },
            "diagonal": {
                "type": "int", "value": 1, "default": 1, "min": 0, "max": 1,
                "label": "对角高光", "desc": "0=不透明对象，1=透明对象（背面也有高光）",
            },
        }
    },

    # ================================================================
    #  高斯模糊特效
    # ================================================================
    "blur": {
        "enable": False,
        "label": "高斯模糊特效", "desc": "控制高斯模糊效果的参数",
        "params": {
            "radius": {
                "type": "int", "value": 10, "default": 10, "min": 0, "max": 50,
                "label": "模糊半径", "desc": "高斯模糊半径（像素），值越大越模糊",
            },
        }
    },

    # ================================================================
    #  抗锯齿特效
    # ================================================================
    "anti_aliasing": {
        "enable": True,
        "label": "抗锯齿特效", "desc": "控制抗锯齿效果的参数",
        "params": {
            "blur_radius": {
                "type": "float", "value": 2.5, "default": 2.5, "min": 0.0, "max": 10.0,
                "label": "模糊半径", "desc": "边缘高斯模糊强度",
            },
            "edge_range": {
                "type": "float", "value": 1.0, "default": 0.5, "min": 0.0, "max": 5.0,
                "label": "边缘范围", "desc": "SDF=0 向内外各扩展处理的像素距离",
            },
            "strength": {
                "type": "float", "value": 1.0, "default": 1.0, "min": 0.0, "max": 1.0,
                "label": "强度", "desc": "抗锯齿混合权重",
            },
        }
    },

    # ================================================================
    #  综合调色特效
    # ================================================================
    "color_grading": {
        "enable": False,
        "label": "综合调色特效", "desc": "控制综合调色效果的参数",
        "params": {
            # --- 基础色调 ---
            "brightness": {
                "type": "float", "value": 0.0, "default": 0.0, "min": -1.0, "max": 1.0,
                "label": "亮度", "desc": "线性亮度偏移，0=不变",
            },
            "contrast": {
                "type": "float", "value": 1.0, "default": 1.0, "min": 0.0, "max": 3.0,
                "label": "对比度", "desc": "以 0.5 为中点拉伸，1=不变",
            },
            "saturation": {
                "type": "float", "value": 1.0, "default": 1.0, "min": 0.0, "max": 3.0,
                "label": "饱和度", "desc": "HSV 整体饱和度缩放，1=不变",
            },
            "hue_shift": {
                "type": "float", "value": 0.0, "default": 0.0, "min": -0.5, "max": 0.5,
                "label": "色相偏移", "desc": "HSV 色相旋转，0=不变，±0.5=±180°",
            },
            # --- 曝光与白平衡 ---
            "exposure": {
                "type": "float", "value": 0.0, "default": 0.0, "min": -3.0, "max": 3.0,
                "label": "曝光量", "desc": "EV 档位，+1=加一档曝光（×2 亮度）",
            },
            "gamma": {
                "type": "float", "value": 1.0, "default": 1.0, "min": 0.1, "max": 5.0,
                "label": "伽马", "desc": "幂次校正，>1 压暗中间调，<1 提亮",
            },
            "temperature": {
                "type": "float", "value": 0.0, "default": 0.0, "min": -1.0, "max": 1.0,
                "label": "色温", "desc": "正=暖色调(橙)，负=冷色调(蓝)",
            },
            # # 色调已经独立为一个特效了，因为不独立颜色只能是黑色，不知道是什么BUG
            # "tint_strength": {
            #     "type": "float", "value": 0.0, "default": 0.0, "min": 0.0, "max": 1.0,
            #     "label": "色调强度", "desc": "与色调颜色插值叠加的强度，0=不叠加",
            # },
            # "tint_color": {
            #     "type": "color", "value": (1.0, 1.0, 1.0), "default": (1.0, 1.0, 1.0),
            #     "label": "色调颜色", "desc": "叠加的目标色调颜色 (R,G,B)，范围 0~1",
            # },
            # --- 高光/阴影 ---
            "highlights": {
                "type": "float", "value": 0.0, "default": 0.0, "min": -1.0, "max": 1.0,
                "label": "高光", "desc": "负=压暗亮部，正=提亮亮部",
            },
            "shadows": {
                "type": "float", "value": 0.0, "default": 0.0, "min": -1.0, "max": 1.0,
                "label": "阴影", "desc": "正=提亮暗部，负=压暗暗部",
            },
            # --- 高级饱和度 ---
            "vibrance": {
                "type": "float", "value": 0.0, "default": 0.0, "min": -1.0, "max": 2.0,
                "label": "自然饱和度", "desc": "优先提升低饱和色，保护高饱和色不过曝",
            },
            # --- 风格化 ---
            "fadeout": {
                "type": "float", "value": 0.0, "default": 0.0, "min": 0.0, "max": 0.5,
                "label": "褪色", "desc": "提升黑位，模拟胶片打印感",
            },
            # --- 暗角 ---
            "vignette_strength": {
                "type": "float", "value": 0.0, "default": 0.0, "min": 0.0, "max": 1.0,
                "label": "暗角强度", "desc": "0=无暗角，1=最强暗角",
            },
            "vignette_radius": {
                "type": "float", "value": 0.5, "default": 0.5, "min": 0.0, "max": 1.0,
                "label": "暗角半径", "desc": "暗角开始位置，0=从中心，1=几乎无暗角",
            },
            "vignette_softness": {
                "type": "float", "value": 0.5, "default": 0.5, "min": 0.0, "max": 1.0,
                "label": "暗角柔化", "desc": "暗角过渡区宽度，值越大边缘越柔和",
            },
            # --- 色彩平衡 ---
            "shadow_color": {
                "type": "vec3", "value": (0.0, 0.0, 0.0), "default": (0.0, 0.0, 0.0), "min": -1.0, "max": 1.0,
                "label": "阴影着色", "desc": "给暗部区域添加 RGB 颜色倾向",
            },
            "midtone_color": {
                "type": "vec3", "value": (0.0, 0.0, 0.0), "default": (0.0, 0.0, 0.0), "min": -1.0, "max": 1.0,
                "label": "中间调着色", "desc": "给中灰区域添加 RGB 颜色倾向",
            },
            "highlight_color": {
                "type": "vec3", "value": (0.0, 0.0, 0.0), "default": (0.0, 0.0, 0.0), "min": -1.0, "max": 1.0,
                "label": "高光着色", "desc": "给亮部区域添加 RGB 颜色倾向",
            },
        }
    },

    # ================================================================
    #  颜色叠加滤镜特效
    # ================================================================
    "color_overlay": {
        "enable": True,
        "label": "颜色叠加特效", "desc": "控制颜色叠加效果的参数",
        "params": {
            "color": {
                "type": "color",
                "value": (1.0, 0.0, 1.0),
                "default": (1.0, 0.0, 1.0),
                "label": "叠加颜色",
                "desc": "RGB 为叠加目标颜色",
            },
            "strength": {
                "type": "float",
                "value": 0.1,
                "default": 0.1,
                "min": 0.0,
                "max": 1.0,
                "label": "叠加强度",
                "desc": "叠加颜色的混合权重，0=无叠加，1=完全叠加",
            },
        }
    },
}