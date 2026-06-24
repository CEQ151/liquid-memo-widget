"""Configuration for the grey-blue ink-wash fluid background.

All tunable parameters live here. The defaults are the values dialed in with
the web tuner (experimental_fluid/inkwash_tuner.html): a warm 宣纸 paper with a
vivid blue ink. Colour and tone are applied at *display* time (concentration
drives value), so changing the palette does not require the simulation to
re-converge — the exported tuner JSON maps 1:1 onto the fields below.
"""
from __future__ import annotations

from dataclasses import dataclass


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


# Maps the web tuner's exported JSON keys (inkwash_tuner.html) onto FluidConfig
# fields. Tuner-only keys (showText / textHalo / scrim — readability preview)
# are intentionally absent and ignored on import.
_TUNER_KEY_MAP = {
    "paper": "paper_hex",
    "inkMid": "ink_mid_hex",
    "inkDeep": "ink_deep_hex",
    "inkDensity": "ink_density",
    "toneGamma": "tone_gamma",
    "edgeStrength": "edge_strength",
    "dryBrush": "dry_brush",
    "paperTexture": "paper_texture",
    "curl": "curl_strength",
    "dyeDiffusion": "dye_diffusion",
    "dyePersistence": "dye_persistence",
    "velocityDamping": "velocity_damping",
    "brushSize": "splat_radius",
    "inkAmount": "ink_amount",
}


@dataclass
class FluidConfig:
    # --- simulation resolution ---
    sim_resolution: int = 128          # velocity / pressure grid
    dye_resolution: int = 1024         # ink (concentration) grid
    pressure_iterations: int = 20      # Jacobi iterations per frame

    # --- ink-wash palette (applied at display; concentration drives value) ---
    paper_hex: str = "#eae5c8"         # 宣纸底色（暖米）
    ink_mid_hex: str = "#3d7ab3"       # 中墨（蓝）
    ink_deep_hex: str = "#0154a7"      # 浓墨（深蓝）

    # --- tone / 浓淡 ---
    ink_density: float = 0.4           # 浓度倍率
    tone_gamma: float = 0.58           # 浓淡对比
    edge_strength: float = 0.5         # 边缘晕染（柔和水痕）
    dry_brush: float = 0.22            # 飞白干笔
    paper_texture: float = 0.09        # 宣纸纹理强度

    # --- motion / 墨性 ---
    curl_strength: float = 16.5        # vorticity confinement
    dye_diffusion: float = 0.18        # 晕开扩散（每帧轻模糊）
    dye_persistence: float = 0.964     # 留墨（每步保留比例，越大越不褪）
    velocity_damping: float = 0.78     # 速度衰减（越大越快静止）
    pressure_decay: float = 0.8        # pressure clear multiplier each frame

    # --- splat (brush) ---
    splat_radius: float = 0.07         # 笔刷大小
    splat_force: float = 6000.0        # mouse delta -> velocity
    ink_amount: float = 0.2            # 落墨量

    # --- timing ---
    max_dt: float = 1.0 / 30.0         # clamp to avoid blow-ups

    # --- background ambient splats (so the scene never goes fully static) ---
    ambient_splat_interval: float = 2.2   # seconds between ambient splats
    ambient_splat_force: float = 320.0

    @property
    def paper(self) -> tuple[float, float, float]:
        return _hex_to_rgb(self.paper_hex)

    @property
    def ink_mid(self) -> tuple[float, float, float]:
        return _hex_to_rgb(self.ink_mid_hex)

    @property
    def ink_deep(self) -> tuple[float, float, float]:
        return _hex_to_rgb(self.ink_deep_hex)

    @classmethod
    def from_tuner_dict(cls, data: dict) -> "FluidConfig":
        """Build a config from the web tuner's exported parameter dict.

        Starts from defaults and overrides only the recognised keys, so partial
        or future-extended JSON still loads cleanly.
        """
        cfg = cls()
        for tuner_key, field in _TUNER_KEY_MAP.items():
            value = data.get(tuner_key)
            if value is not None:
                setattr(cfg, field, value)
        return cfg

    @classmethod
    def from_tuner_json(cls, path) -> "FluidConfig":
        """Load a config from a tuner JSON file (the 'copy parameters' output)."""
        import json
        from pathlib import Path
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_tuner_dict(json.loads(text))
