from __future__ import annotations

import copy


def hex_to_rgb01(value: str) -> tuple[float, float, float]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return (0.97, 0.98, 1.0)
    return (int(text[0:2], 16) / 255, int(text[2:4], 16) / 255, int(text[4:6], 16) / 255)


def color_overlay_strength(opacity: float) -> float:
    overlay_strength = 0.0 if opacity <= 0 else 0.025 + opacity * 0.85
    return max(0.0, min(0.28, overlay_strength))


def build_effect_params(base_params: dict, tint: str, opacity: float, liquid_strength: float) -> dict:
    params = copy.deepcopy(base_params)

    params["flow"]["enable"] = True
    params["flow"]["params"]["flow_strength"]["value"] = 1.15 + 0.85 * liquid_strength
    params["flow"]["params"]["flow_width"]["value"] = int(24 + 28 * liquid_strength)
    params["flow"]["params"]["flow_falloff"]["value"] = 5.0

    params["chromatic_aberration"]["enable"] = True
    params["chromatic_aberration"]["params"]["chromatic_strength"]["value"] = 0.7 + 1.45 * liquid_strength
    params["chromatic_aberration"]["params"]["chromatic_width"]["value"] = int(18 + 22 * liquid_strength)

    params["highlight"]["enable"] = True
    params["highlight"]["params"]["width"]["value"] = 5.0
    params["highlight"]["params"]["angle"]["value"] = 225
    params["highlight"]["params"]["strength"]["value"] = 0.65 + 0.35 * liquid_strength
    params["highlight"]["params"]["range"]["value"] = 0.36
    params["highlight"]["params"]["diagonal"]["value"] = 1

    params["anti_aliasing"]["enable"] = True
    params["anti_aliasing"]["params"]["blur_radius"]["value"] = 2.0
    params["anti_aliasing"]["params"]["edge_range"]["value"] = 1.2

    params["blur"]["enable"] = False
    params["color_grading"]["enable"] = False
    params["color_overlay"]["enable"] = True
    params["color_overlay"]["params"]["color"]["value"] = hex_to_rgb01(tint)
    params["color_overlay"]["params"]["strength"]["value"] = color_overlay_strength(opacity)

    return params
