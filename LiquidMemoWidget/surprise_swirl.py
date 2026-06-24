"""Grey-blue fluid background for the opt-in surprise mode.

The implementation stays entirely in QWidget/QPainter.  Broad solution fields provide depth,
feathered ellipse chains form soft mid-frequency ink bands, and short-lived cursor impulses bend
both layers.  Nothing is stroked as a spiral: direction comes from overlapping translucent
volumes, local displacement and concentration changes.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QObject, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget


@dataclass(frozen=True)
class SwirlThemeTokens:
    """Colour tokens for the muted solution field and its readability layer."""

    bg_top: str = "#8A9BA8"
    bg_bottom: str = "#4A6A7F"
    fluid_deep: str = "#2C3E50"
    fluid_mid: str = "#6A7A8E"
    fluid_mist: str = "#8A9BA8"
    glow_soft: str = "#D0D8E0"
    grain_color: str = "#D0D8E0"
    veil_color: str = "#C9D2DA"
    border_frosted: str = "#E0E8EF"
    text_overlay_safe: str = "#182633"


# One token preset per 拾光纸条 theme, so the QPainter fallback background matches the chosen
# note palette. The "qinghua" entry keeps the original grey-blue look. Keyed by the same theme
# keys as surprise_mode.NOTE_THEMES; swirl_tokens() falls back to qinghua for anything unknown.
SWIRL_TOKENS_BY_THEME: dict[str, "SwirlThemeTokens"] = {
    "qinghua": SwirlThemeTokens(),
    "warm": SwirlThemeTokens(
        bg_top="#C9B79C", bg_bottom="#7E6450",
        fluid_deep="#4A3528", fluid_mid="#927258", fluid_mist="#B89B7C",
        glow_soft="#E8DCC8", grain_color="#E8DCC8", veil_color="#E0D2BE",
        border_frosted="#EDE3D2", text_overlay_safe="#3A2A22",
    ),
    "blush": SwirlThemeTokens(
        bg_top="#D9B8C2", bg_bottom="#8E5E70",
        fluid_deep="#5A2C3E", fluid_mid="#A8788A", fluid_mist="#CDA4B2",
        glow_soft="#F0DCE2", grain_color="#F0DCE2", veil_color="#ECD6DE",
        border_frosted="#F4E6EC", text_overlay_safe="#3A2030",
    ),
}


def swirl_tokens(theme_key: str) -> "SwirlThemeTokens":
    return SWIRL_TOKENS_BY_THEME.get(theme_key, SWIRL_TOKENS_BY_THEME["qinghua"])


@dataclass(frozen=True)
class SwirlConfig:
    """Quality, motion and interaction parameters for the painter backend."""

    target_fps: int = 45
    render_scale: float = 0.60
    background_contrast: float = 1.14
    blob_count: int = 6
    field_count: int = 4
    band_count: int = 6
    band_points: int = 10
    motion_speed: float = 0.65
    band_motion_speed: float = 0.85
    base_flow_strength: float = 17.0
    vortex_count: int = 3
    vortex_strength: float = 24.0
    flow_response: float = 4.8
    velocity_damping: float = 0.972
    return_strength: float = 0.090
    mouse_influence: float = 0.85
    mouse_radius: float = 0.42
    grain_strength: float = 0.024
    veil_opacity: float = 0.24
    pointer_response_seconds: float = 0.36
    pointer_fade_seconds: float = 0.90
    wake_max_points: int = 24
    wake_lifetime: float = 1.20
    wake_radius: float = 0.18
    wake_strength: float = 0.75
    wake_curl_strength: float = 0.30
    wake_highlight_opacity: float = 0.16
    wake_shadow_opacity: float = 0.12


@dataclass(slots=True)
class _WakeImpulse:
    """One normalized, short-lived sample of the cursor-driven flow wake."""

    position: QPointF
    velocity: QPointF
    strength: float
    age: float
    lifetime: float


@dataclass(slots=True)
class _BandControlPoint:
    """Persistent normalized state for one advected mist-band sample."""

    anchor: QPointF
    position: QPointF
    velocity: QPointF


@dataclass(slots=True)
class _BandState:
    """Visual metadata plus the persistent samples that form one broad ribbon."""

    points: list[_BandControlPoint]
    width: float
    phase: float
    role: int
    direction: float


class SwirlInteractionController(QObject):
    """Poll the global cursor and expose a softly damped normalized position.

    MemoWindow is intentionally click-through outside controls, so relying on mouseMoveEvent would
    make interaction intermittent.  Polling does not capture input and preserves native hit tests.
    """

    def __init__(self, target: QWidget, config: SwirlConfig) -> None:
        super().__init__(target)
        self.target = target
        self.config = config
        self.position = QPointF(0.52, 0.44)
        self.velocity = QPointF(0.0, 0.0)
        self.influence = 0.0
        self.wakes: list[_WakeImpulse] = []
        self._last_raw_position: QPointF | None = None
        self._last_raw_inside = False
        self._time_since_wake = 1.0

    def _age_wakes(self, dt: float) -> None:
        alive: list[_WakeImpulse] = []
        velocity_decay = math.exp(-dt * 0.55)
        for wake in self.wakes:
            wake.age += dt
            if wake.age >= wake.lifetime:
                continue
            # A tiny amount of advection keeps the trail fluid without making it chase the cursor.
            wake.position = QPointF(
                wake.position.x() + wake.velocity.x() * dt * 0.038,
                wake.position.y() + wake.velocity.y() * dt * 0.038,
            )
            wake.velocity = QPointF(
                wake.velocity.x() * velocity_decay,
                wake.velocity.y() * velocity_decay,
            )
            alive.append(wake)
        self.wakes = alive

    def _inject_wake(
        self, position: QPointF, velocity: QPointF, speed: float
    ) -> _WakeImpulse | None:
        if speed < 0.035:
            return None
        max_speed = 2.8
        if speed > max_speed:
            velocity = QPointF(velocity.x() * max_speed / speed, velocity.y() * max_speed / speed)
            speed = max_speed
        strength = max(0.18, min(1.0, 0.20 + speed * 0.36))
        wake = _WakeImpulse(
            QPointF(position),
            QPointF(velocity),
            strength,
            0.0,
            max(0.25, self.config.wake_lifetime),
        )
        self.wakes.append(wake)
        limit = max(1, min(32, int(self.config.wake_max_points)))
        if len(self.wakes) > limit:
            del self.wakes[: len(self.wakes) - limit]
        return wake

    def inject_wake(self, position: QPointF, velocity: QPointF, strength: float = 1.0) -> None:
        """Inject a normalized wake sample; useful for previews and deterministic tests."""
        speed = math.hypot(velocity.x(), velocity.y())
        wake = self._inject_wake(position, velocity, speed)
        if wake is not None:
            wake.strength = max(0.0, min(1.0, strength))

    def advance(self, dt: float) -> tuple[QPointF, float]:
        dt = max(0.001, min(0.09, dt))
        self._age_wakes(dt)
        self._time_since_wake += dt
        width = max(1, self.target.width())
        height = max(1, self.target.height())
        local = self.target.mapFromGlobal(QCursor.pos())
        inside = self.target.rect().contains(local)
        raw_position = QPointF(local.x() / width, local.y() / height) if inside else None
        target = QPointF(raw_position) if raw_position is not None else QPointF(0.52, 0.44)
        target_influence = 1.0 if inside else 0.0

        if inside and raw_position is not None and self._last_raw_inside and self._last_raw_position is not None:
            dx = raw_position.x() - self._last_raw_position.x()
            dy = raw_position.y() - self._last_raw_position.y()
            distance = math.hypot(dx, dy)
            speed = distance / dt
            # Sample enough points to describe a continuous tail, but avoid filling the list while
            # the cursor jitters by a sub-pixel amount.
            if distance >= 0.0045 or self._time_since_wake >= 0.075:
                self._inject_wake(raw_position, QPointF(dx / dt, dy / dt), speed)
                self._time_since_wake = 0.0
        self._last_raw_position = QPointF(raw_position) if raw_position is not None else None
        self._last_raw_inside = inside

        # First-order lag has no overshoot or spring-back.  The actual visual interaction is
        # carried by velocity impulses below, while this smoothed position remains available for
        # gentle global biasing and diagnostics.
        response = max(0.08, self.config.pointer_response_seconds)
        blend = 1.0 - math.exp(-dt / response)
        previous = QPointF(self.position)
        self.position = QPointF(
            self.position.x() + (target.x() - self.position.x()) * blend,
            self.position.y() + (target.y() - self.position.y()) * blend,
        )
        self.velocity = QPointF(
            (self.position.x() - previous.x()) / dt,
            (self.position.y() - previous.y()) / dt,
        )

        fade = max(0.10, self.config.pointer_fade_seconds)
        self.influence += (target_influence - self.influence) * (1.0 - math.exp(-dt / fade))
        if self.influence < 0.0005:
            self.influence = 0.0
        return QPointF(self.position), self.influence


class SwirlPainterFallback(QWidget):
    """Reduced-resolution, painter-only fluid solution background.

    Large radial masses provide depth while persistent ribbon samples are advected through a
    lightweight velocity field.  Mouse wakes inject velocity and shear into those samples; no
    stroke or explicit spiral path is drawn anywhere.
    """

    # x, y, horizontal radius, vertical radius, direction, phase
    _FIELD_LAYOUT = (
        (0.16, 0.18, 0.62, 0.43, 1.0, 0.2),
        (0.84, 0.37, 0.55, 0.38, -1.0, 1.8),
        (0.31, 0.76, 0.68, 0.45, -1.0, 3.5),
        (0.78, 0.91, 0.58, 0.40, 1.0, 5.1),
    )

    # Four cubic control points, band width, phase, palette role and flow direction.  Bands are
    # sampled into overlapping feathered volumes; these values never become stroked paths.
    _BAND_LAYOUT = (
        ((-0.18, 0.12), (0.18, -0.02), (0.52, 0.40), (1.18, 0.20), 0.105, 0.3, 3, 1.0),
        ((-0.14, 0.38), (0.28, 0.18), (0.68, 0.62), (1.14, 0.46), 0.125, 1.4, 1, -1.0),
        ((-0.18, 0.72), (0.24, 0.48), (0.58, 0.96), (1.18, 0.70), 0.110, 2.6, 0, 1.0),
        ((0.10, -0.18), (0.00, 0.30), (0.56, 0.58), (0.34, 1.18), 0.090, 3.8, 2, -1.0),
        ((0.78, -0.16), (0.54, 0.24), (1.04, 0.66), (0.76, 1.18), 0.100, 4.9, 3, 1.0),
        ((-0.10, 0.94), (0.30, 0.70), (0.70, 1.04), (1.12, 0.86), 0.080, 5.7, 1, -1.0),
    )

    # x, y, radius relative to the short side, direction, phase.  These centres are never drawn;
    # they only curl the velocity sampled by band control points.
    _VORTEX_LAYOUT = (
        (0.22, 0.24, 0.43, 1.0, 0.4),
        (0.78, 0.48, 0.38, -1.0, 2.2),
        (0.38, 0.82, 0.46, 1.0, 4.3),
        (0.86, 0.88, 0.34, -1.0, 5.6),
    )

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        tokens: SwirlThemeTokens | None = None,
        config: SwirlConfig | None = None,
    ) -> None:
        super().__init__(parent)
        self.tokens = tokens or SwirlThemeTokens()
        self.config = config or SwirlConfig()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._controller = SwirlInteractionController(self, self.config)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(max(16, round(1000 / max(1, self.config.target_fps))))
        self._timer.timeout.connect(self._advance)
        self._clock = QElapsedTimer()
        self._elapsed = 0.0
        self._pointer = QPointF(0.52, 0.44)
        self._pointer_influence = 0.0
        self._running = False
        self._active = True

        self._buffer_size = QSize()
        self._base_layer = QImage()
        self._fluid_frame = QImage()
        self._grain_texture = self._make_grain_texture()
        self._blob_specs = self._make_blob_specs()
        self._band_states = self._make_band_states()

    @property
    def running(self) -> bool:
        return self._running

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if self._active and self.isVisible():
            self.start()
        else:
            self.stop()

    def setActive(self, active: bool) -> None:  # Qt-style convenience for the integration layer.
        self.set_active(active)

    def set_theme(self, theme_key: str) -> None:
        """Recolour in place when the note theme changes — no widget rebuild. Bands/blobs are
        geometry (colour-independent), so only the colour-derived layers are regenerated."""
        self.tokens = swirl_tokens(theme_key)
        self._grain_texture = self._make_grain_texture()
        self._paint_base_layer()
        self._render_frame()
        self.update()

    def start(self) -> None:
        if self._running or not self._active or not self.isVisible():
            return
        self._running = True
        self._clock.start()
        if self._fluid_frame.isNull():
            self._rebuild_buffers()
        self._render_frame()
        self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()
        self._running = False

    def cleanup(self) -> None:
        self.stop()
        self._base_layer = QImage()
        self._fluid_frame = QImage()
        self._grain_texture = QPixmap()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.start()

    def hideEvent(self, event) -> None:
        self.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rebuild_buffers()
        self._render_frame()

    def _advance(self) -> None:
        if not self._clock.isValid():
            self._clock.start()
            dt = 1.0 / max(1, self.config.target_fps)
        else:
            dt = self._clock.nsecsElapsed() / 1_000_000_000.0
            self._clock.restart()
        dt = max(0.001, min(0.09, dt))
        self._elapsed = (self._elapsed + dt) % 10_000.0
        self._pointer, self._pointer_influence = self._controller.advance(dt)
        self._advance_band_states(dt)
        self._render_frame()
        self.update()

    def _target_buffer_size(self) -> QSize:
        scale = max(0.45, min(0.75, self.config.render_scale))
        return QSize(
            max(96, round(self.width() * scale)),
            max(128, round(self.height() * scale)),
        )

    def _rebuild_buffers(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            self._buffer_size = QSize()
            self._base_layer = QImage()
            self._fluid_frame = QImage()
            return
        size = self._target_buffer_size()
        if size == self._buffer_size and not self._base_layer.isNull():
            return
        self._buffer_size = size
        self._base_layer = QImage(size, QImage.Format_ARGB32_Premultiplied)
        self._fluid_frame = QImage(size, QImage.Format_ARGB32_Premultiplied)
        self._paint_base_layer()

    def _paint_base_layer(self) -> None:
        if self._base_layer.isNull():
            return
        width = float(self._base_layer.width())
        height = float(self._base_layer.height())
        self._base_layer.fill(self._contrasted_color(self.tokens.bg_bottom))
        painter = QPainter(self._base_layer)
        painter.setRenderHint(QPainter.Antialiasing)

        base = QLinearGradient(0.0, 0.0, width * 0.92, height)
        base.setColorAt(0.0, self._contrasted_color("#A1AFB9"))
        base.setColorAt(0.38, self._contrasted_color(self.tokens.bg_top))
        base.setColorAt(0.72, self._contrasted_color("#65798A"))
        base.setColorAt(1.0, self._contrasted_color(self.tokens.bg_bottom))
        painter.fillRect(QRectF(0.0, 0.0, width, height), base)

        # Broad static haze prevents empty corners and gives the moving layers depth to recede into.
        haze = QRadialGradient(QPointF(width * 0.24, height * 0.18), max(width, height) * 0.72)
        haze.setColorAt(0.0, QColor(208, 216, 224, 82))
        haze.setColorAt(0.52, QColor(138, 155, 168, 34))
        haze.setColorAt(1.0, QColor(74, 106, 127, 0))
        painter.fillRect(QRectF(0.0, 0.0, width, height), haze)
        painter.end()

    def _contrasted_color(self, value: str | QColor, alpha: int | None = None) -> QColor:
        color = QColor(value)
        amount = max(0.80, min(1.35, self.config.background_contrast))
        result = QColor(
            max(0, min(255, round(128 + (color.red() - 128) * amount))),
            max(0, min(255, round(128 + (color.green() - 128) * amount))),
            max(0, min(255, round(128 + (color.blue() - 128) * amount))),
            color.alpha() if alpha is None else max(0, min(255, alpha)),
        )
        return result

    def _make_blob_specs(self) -> tuple[tuple[float, ...], ...]:
        """Create deterministic blob descriptors once; frames only update their transforms."""
        rng = random.Random(0x6A7A8E)
        count = max(4, min(20, int(self.config.blob_count)))
        fields = max(1, min(int(self.config.field_count), len(self._FIELD_LAYOUT)))
        specs: list[tuple[float, ...]] = []
        for index in range(count):
            specs.append(
                (
                    float(index % fields),
                    rng.uniform(0.16, 0.64),  # orbit fraction
                    rng.uniform(0.38, 0.82),  # size fraction
                    rng.uniform(0.46, 0.92),  # vertical stretch
                    rng.uniform(0.0, math.tau),
                    rng.uniform(0.62, 1.28),  # angular multiplier
                    float(index % 4),  # colour role
                    rng.uniform(0.0, math.tau),  # breathing phase
                )
            )
        return tuple(specs)

    def _make_band_states(self) -> list[_BandState]:
        """Create persistent samples along each initial ribbon curve."""
        count = max(0, min(int(self.config.band_count), len(self._BAND_LAYOUT)))
        point_count = max(8, min(14, int(self.config.band_points)))
        states: list[_BandState] = []
        for layout in self._BAND_LAYOUT[:count]:
            p0, p1, p2, p3, width, phase, role, direction = layout
            curve = (p0, p1, p2, p3)
            points: list[_BandControlPoint] = []
            for index in range(point_count):
                anchor = self._cubic_point(curve, index / (point_count - 1))
                points.append(
                    _BandControlPoint(QPointF(anchor), QPointF(anchor), QPointF(0.0, 0.0))
                )
            states.append(_BandState(points, width, phase, int(role), direction))
        return states

    def _make_grain_texture(self) -> QPixmap:
        rng = random.Random(0xD0D8E0)
        size = 68
        image = QImage(size, size, QImage.Format_RGBA8888)
        grain = QColor(self.tokens.grain_color)
        for y in range(size):
            for x in range(size):
                offset = rng.randrange(-15, 13)
                image.setPixelColor(
                    x,
                    y,
                    QColor(
                        max(0, min(255, grain.red() + offset)),
                        max(0, min(255, grain.green() + offset)),
                        max(0, min(255, grain.blue() + offset)),
                        rng.randrange(8, 25),
                    ),
                )
        return QPixmap.fromImage(image)

    @staticmethod
    def _wake_decay(wake: _WakeImpulse) -> float:
        progress = max(0.0, min(1.0, wake.age / max(0.001, wake.lifetime)))
        remaining = 1.0 - progress
        # Smoothstep decay keeps injected velocity alive through the middle of its lifetime, then
        # eases it to zero without an abrupt stop.
        return remaining * remaining * (3.0 - 2.0 * remaining)

    def _base_flow_velocity(self, position: QPointF, width: float, height: float) -> QPointF:
        """Two low-frequency layers form a continuous, non-looping background current."""
        x = position.x() * width
        y = position.y() * height
        time = self._elapsed * self.config.band_motion_speed
        strength = max(0.0, self.config.base_flow_strength)
        velocity_x = strength * (
            0.64 * math.sin(y * 0.010 + time * 0.34)
            + 0.36 * math.sin((x + y) * 0.0062 - time * 0.22 + 1.35)
        )
        velocity_y = strength * (
            0.60 * math.cos(x * 0.0092 - time * 0.29 + 0.55)
            + 0.34 * math.cos((x - y) * 0.0068 + time * 0.19 + 2.25)
        )
        return QPointF(velocity_x, velocity_y)

    def _vortex_flow_velocity(self, position: QPointF, width: float, height: float) -> QPointF:
        """Sample drifting invisible vortices; only their tangential velocity is rendered."""
        shortest = max(1.0, min(width, height))
        time = self._elapsed * self.config.motion_speed
        velocity_x = 0.0
        velocity_y = 0.0
        count = max(0, min(int(self.config.vortex_count), len(self._VORTEX_LAYOUT)))
        for index, (x, y, radius_factor, direction, phase) in enumerate(
            self._VORTEX_LAYOUT[:count]
        ):
            center_x = width * (x + math.sin(time * (0.11 + index * 0.013) + phase) * 0.055)
            center_y = height * (
                y + math.cos(time * (0.09 + index * 0.011) + phase * 0.73) * 0.045
            )
            dx = position.x() * width - center_x
            dy = position.y() * height - center_y
            distance = math.hypot(dx, dy)
            if distance < 0.001:
                continue
            radius = shortest * radius_factor
            falloff = math.exp(-(distance * distance) / max(1.0, radius * radius))
            tangent_x = -dy / distance
            tangent_y = dx / distance
            strength = self.config.vortex_strength * direction * falloff
            velocity_x += tangent_x * strength
            velocity_y += tangent_y * strength
        return QPointF(velocity_x, velocity_y)

    def _mouse_flow_velocity(self, position: QPointF, width: float, height: float) -> QPointF:
        """Convert live cursor wakes into local drag plus signed cross-stream shear."""
        if not self._controller.wakes:
            return QPointF(0.0, 0.0)
        shortest = max(1.0, min(width, height))
        base_radius = shortest * max(0.05, min(0.32, self.config.wake_radius))
        velocity_x = 0.0
        velocity_y = 0.0
        for wake in self._controller.wakes:
            progress = max(0.0, min(1.0, wake.age / max(0.001, wake.lifetime)))
            radius = base_radius * (1.0 + progress * 0.34)
            dx = position.x() * width - wake.position.x() * width
            dy = position.y() * height - wake.position.y() * height
            distance_squared = dx * dx + dy * dy
            if distance_squared > radius * radius * 6.0:
                continue
            falloff = math.exp(-distance_squared / max(1.0, radius * radius))
            decay = self._wake_decay(wake)

            wake_x = wake.velocity.x() * width
            wake_y = wake.velocity.y() * height
            speed = math.hypot(wake_x, wake_y)
            speed_limit = min(240.0, shortest * 0.78)
            if speed > speed_limit:
                wake_x *= speed_limit / speed
                wake_y *= speed_limit / speed
                speed = speed_limit
            if speed < 0.001:
                continue

            amplitude = (
                self.config.mouse_influence
                * self.config.wake_strength
                * wake.strength
                * falloff
                * decay
            )
            velocity_x += wake_x * amplitude
            velocity_y += wake_y * amplitude

            normal_x = -wake_y / speed
            normal_y = wake_x / speed
            signed_side = max(-1.0, min(1.0, (wake_x * dy - wake_y * dx) / (speed * radius)))
            curl = speed * self.config.wake_curl_strength * signed_side * amplitude
            velocity_x += normal_x * curl
            velocity_y += normal_y * curl

        magnitude = math.hypot(velocity_x, velocity_y)
        limit = shortest * 0.34
        if magnitude > limit:
            velocity_x *= limit / magnitude
            velocity_y *= limit / magnitude
        return QPointF(velocity_x, velocity_y)

    def _flow_velocity(self, position: QPointF, width: float, height: float) -> QPointF:
        base = self._base_flow_velocity(position, width, height)
        vortex = self._vortex_flow_velocity(position, width, height)
        mouse = self._mouse_flow_velocity(position, width, height)
        velocity_x = base.x() + vortex.x() + mouse.x()
        velocity_y = base.y() + vortex.y() + mouse.y()
        magnitude = math.hypot(velocity_x, velocity_y)
        limit = max(40.0, min(width, height) * 0.44)
        if magnitude > limit:
            velocity_x *= limit / magnitude
            velocity_y *= limit / magnitude
        return QPointF(velocity_x / width, velocity_y / height)

    def _advance_band_states(self, dt: float) -> None:
        """Advect persistent ribbon points through the combined velocity field."""
        width = float(max(1, self.width()))
        height = float(max(1, self.height()))
        response = max(0.5, min(12.0, self.config.flow_response))
        blend = 1.0 - math.exp(-response * dt)
        damping = max(0.80, min(0.999, self.config.velocity_damping)) ** (dt * 60.0)
        return_strength = max(0.0, min(0.30, self.config.return_strength))

        for band in self._band_states:
            for point in band.points:
                target = self._flow_velocity(point.position, width, height)
                # This is a weak first-order return velocity, not a spring force.  It prevents a
                # ribbon from leaving the extended canvas after many minutes without oscillation.
                target = QPointF(
                    target.x() + (point.anchor.x() - point.position.x()) * return_strength,
                    target.y() + (point.anchor.y() - point.position.y()) * return_strength,
                )
                velocity = QPointF(
                    point.velocity.x() + (target.x() - point.velocity.x()) * blend,
                    point.velocity.y() + (target.y() - point.velocity.y()) * blend,
                )
                point.velocity = QPointF(velocity.x() * damping, velocity.y() * damping)
                point.position = QPointF(
                    point.position.x() + point.velocity.x() * dt,
                    point.position.y() + point.velocity.y() * dt,
                )

    def _field_center(self, field_index: int, width: float, height: float) -> QPointF:
        x, y, _rx, _ry, _direction, phase = self._FIELD_LAYOUT[field_index]
        time = self._elapsed * self.config.motion_speed
        drift_x = math.sin(time * (0.31 + field_index * 0.035) + phase) * 0.055
        drift_y = math.cos(time * (0.24 + field_index * 0.028) + phase * 0.73) * 0.043
        return QPointF(width * (x + drift_x), height * (y + drift_y))

    @staticmethod
    def _draw_soft_mass(
        painter: QPainter,
        center: QPointF,
        radius_x: float,
        radius_y: float,
        rotation: float,
        color: QColor,
        alpha: int,
        focal_shift: float,
    ) -> None:
        """Draw a feathered ellipse using only a radial field—never an outline."""
        radius_x = max(2.0, radius_x)
        radius_y = max(2.0, radius_y)
        painter.save()
        painter.translate(center)
        painter.rotate(rotation)
        painter.scale(1.0, radius_y / radius_x)
        gradient = QRadialGradient(QPointF(-radius_x * focal_shift, radius_x * 0.04), radius_x * 1.04)
        core = QColor(color)
        core.setAlpha(max(0, min(255, alpha)))
        middle = QColor(core)
        middle.setAlpha(round(core.alpha() * 0.54))
        edge = QColor(core)
        edge.setAlpha(0)
        gradient.setColorAt(0.0, core)
        gradient.setColorAt(0.48, middle)
        gradient.setColorAt(0.82, QColor(middle.red(), middle.green(), middle.blue(), round(middle.alpha() * 0.30)))
        gradient.setColorAt(1.0, edge)
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(0.0, 0.0), radius_x, radius_x)
        painter.restore()

    @classmethod
    def _draw_compound_mass(
        cls,
        painter: QPainter,
        center: QPointF,
        radius_x: float,
        radius_y: float,
        rotation: float,
        color: QColor,
        alpha: int,
        seed: float,
    ) -> None:
        """Build one irregular diffusion body from three overlapping feathered volumes."""
        angle = math.radians(rotation)
        tangent = QPointF(math.cos(angle), math.sin(angle))
        normal = QPointF(-tangent.y(), tangent.x())
        cls._draw_soft_mass(
            painter,
            center,
            radius_x,
            radius_y,
            rotation,
            color,
            round(alpha * 0.64),
            math.sin(seed) * 0.12,
        )
        first = QPointF(
            center.x() + tangent.x() * radius_x * 0.24 + normal.x() * radius_y * 0.12,
            center.y() + tangent.y() * radius_x * 0.24 + normal.y() * radius_y * 0.12,
        )
        second = QPointF(
            center.x() - tangent.x() * radius_x * 0.20 + normal.x() * radius_y * 0.18,
            center.y() - tangent.y() * radius_x * 0.20 + normal.y() * radius_y * 0.18,
        )
        cls._draw_soft_mass(
            painter,
            first,
            radius_x * (0.68 + math.sin(seed * 1.7) * 0.05),
            radius_y * 0.78,
            rotation + 17.0,
            color,
            round(alpha * 0.48),
            0.18,
        )
        cls._draw_soft_mass(
            painter,
            second,
            radius_x * 0.61,
            radius_y * (0.72 + math.cos(seed * 1.3) * 0.05),
            rotation - 21.0,
            color,
            round(alpha * 0.42),
            -0.16,
        )

    @staticmethod
    def _cubic_point(points: tuple[tuple[float, float], ...], amount: float) -> QPointF:
        inverse = 1.0 - amount
        p0, p1, p2, p3 = points
        return QPointF(
            inverse**3 * p0[0]
            + 3.0 * inverse * inverse * amount * p1[0]
            + 3.0 * inverse * amount * amount * p2[0]
            + amount**3 * p3[0],
            inverse**3 * p0[1]
            + 3.0 * inverse * inverse * amount * p1[1]
            + 3.0 * inverse * amount * amount * p2[1]
            + amount**3 * p3[1],
        )

    def _draw_fluid_bands(
        self,
        painter: QPainter,
        width: float,
        height: float,
        palette: tuple[QColor, ...],
    ) -> None:
        """Draw advected control points as overlapping, feathered ribbon volumes."""
        shortest = min(width, height)
        band_time = self._elapsed * self.config.band_motion_speed
        for band in self._band_states:
            color = palette[band.role % len(palette)]
            if band.role == 0:
                painter.setCompositionMode(QPainter.CompositionMode_Multiply)
                base_alpha = 48
            elif band.role == 3:
                painter.setCompositionMode(QPainter.CompositionMode_Screen)
                base_alpha = 44
            elif band.role == 2:
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                base_alpha = 38
            else:
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                base_alpha = 46

            count = len(band.points)
            for index, point in enumerate(band.points):
                previous = band.points[max(0, index - 1)].position
                following = band.points[min(count - 1, index + 1)].position
                # One render-only smoothing pass hides point-to-point corners without pulling the
                # persistent simulation state back toward a prescribed curve.
                normalized = QPointF(
                    point.position.x() * 0.70 + (previous.x() + following.x()) * 0.15,
                    point.position.y() * 0.70 + (previous.y() + following.y()) * 0.15,
                )
                physical_tangent_x = (following.x() - previous.x()) * width
                physical_tangent_y = (following.y() - previous.y()) * height
                rotation = math.degrees(math.atan2(physical_tangent_y, physical_tangent_x))
                amount = index / max(1, count - 1)
                speed = math.hypot(point.velocity.x() * width, point.velocity.y() * height)
                stretch = 1.0 + min(0.30, speed / max(1.0, shortest) * 1.8)
                pulse = 1.0 + math.sin(
                    band_time * 0.21 + band.phase + amount * 1.35
                ) * 0.045
                self._draw_soft_mass(
                    painter,
                    QPointF(normalized.x() * width, normalized.y() * height),
                    shortest * band.width * 1.28 * pulse * stretch,
                    shortest * band.width * (0.48 + 0.025 * math.sin(band.phase + amount * math.pi)),
                    rotation,
                    color,
                    round(base_alpha * (0.82 + 0.18 * math.sin(amount * math.pi))),
                    0.16 * band.direction,
                )

    def _draw_fluid_fields(self, painter: QPainter, width: float, height: float) -> None:
        fields = max(1, min(int(self.config.field_count), len(self._FIELD_LAYOUT)))
        field_centers = [self._field_center(index, width, height) for index in range(fields)]
        palette = (
            self._contrasted_color(self.tokens.fluid_deep),
            self._contrasted_color(self.tokens.fluid_mid),
            self._contrasted_color(self.tokens.fluid_mist),
            self._contrasted_color(self.tokens.glow_soft),
        )
        flow_time = self._elapsed * self.config.motion_speed

        # First establish several room-sized, low-opacity bodies so the whole surface reads as
        # solution, not isolated objects floating over a background.
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        for index, center in enumerate(field_centers):
            _x, _y, radius_x, radius_y, direction, phase = self._FIELD_LAYOUT[index]
            breathe = 1.0 + math.sin(flow_time * 0.28 + phase) * 0.050
            color = palette[(index + 1) % 3]
            self._draw_compound_mass(
                painter,
                center,
                width * radius_x * breathe,
                height * radius_y * breathe,
                direction * math.degrees(flow_time * 0.082 + phase * 0.08),
                color,
                48 if index != 1 else 56,
                phase,
            )

        # Mid-frequency direction survives the broad haze.  Each band is a chain of filled,
        # feathered volumes, so it reads as folded pigment rather than a line laid over the image.
        self._draw_fluid_bands(painter, width, height, palette)

        # Smaller masses orbit the same invisible fields. Overlap and different blend modes form
        # implicit circulation and diffusion boundaries without any geometric swirl stroke.
        minimum = min(width, height)
        for blob_index, spec in enumerate(self._blob_specs):
            field_index = int(spec[0]) % fields
            orbit_fraction, size_fraction, stretch, phase, angular, color_role, breath_phase = spec[1:]
            _x, _y, field_rx, field_ry, direction, field_phase = self._FIELD_LAYOUT[field_index]
            field_center = field_centers[field_index]
            angle = (
                phase
                + direction * flow_time * (0.30 + angular * 0.08)
                + math.sin(flow_time * 0.18 + breath_phase) * 0.20
            )
            orbit_x = width * field_rx * orbit_fraction * 0.50
            orbit_y = height * field_ry * orbit_fraction * 0.42
            center = QPointF(
                field_center.x() + math.cos(angle) * orbit_x,
                field_center.y() + math.sin(angle) * orbit_y,
            )
            breathe = 1.0 + math.sin(flow_time * (0.30 + angular * 0.045) + breath_phase) * 0.085
            radius_x = minimum * size_fraction * (0.34 + field_rx * 0.18) * breathe
            radius_y = radius_x * stretch * (0.90 + math.cos(flow_time * 0.21 + phase) * 0.07)
            role = int(color_role)
            color = palette[role]

            if role == 0:
                painter.setCompositionMode(QPainter.CompositionMode_Multiply)
                alpha = 38
            elif role == 3:
                painter.setCompositionMode(QPainter.CompositionMode_Screen)
                alpha = 46
            else:
                painter.setCompositionMode(QPainter.CompositionMode_SoftLight)
                alpha = 64 if role == 1 else 54
            self._draw_compound_mass(
                painter,
                center,
                radius_x,
                radius_y,
                math.degrees(angle * 0.58 + field_phase),
                color,
                alpha,
                breath_phase + blob_index * 0.31,
            )

        # Wide mist bridges make neighbouring fields appear to diffuse through one another. They
        # are soft filled volumes, not ribbons or paths, and move at a slower frequency than the
        # individual blobs so the composition never reads as a mechanical loop.
        painter.setCompositionMode(QPainter.CompositionMode_Screen)
        for index in range(fields - 1):
            first = field_centers[index]
            second = field_centers[index + 1]
            midpoint = QPointF(
                (first.x() + second.x()) * 0.5 + math.sin(flow_time * 0.24 + index) * width * 0.035,
                (first.y() + second.y()) * 0.5 + math.cos(flow_time * 0.20 + index) * height * 0.025,
            )
            self._draw_soft_mass(
                painter,
                midpoint,
                minimum * (0.46 + index * 0.035),
                minimum * (0.19 + index * 0.018),
                math.degrees(math.atan2(second.y() - first.y(), second.x() - first.x()))
                + math.sin(flow_time * 0.18 + index) * 9.0,
                palette[3],
                24,
                0.20,
            )

    def _draw_readability_veil(self, painter: QPainter, width: float, height: float) -> None:
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        opacity = max(0.08, min(0.55, self.config.veil_opacity))
        fog = QColor(self.tokens.veil_color)

        horizontal = QLinearGradient(0.0, 0.0, width, 0.0)
        horizontal.setColorAt(0.0, QColor(fog.red(), fog.green(), fog.blue(), round(255 * opacity * 0.48)))
        horizontal.setColorAt(0.24, QColor(fog.red(), fog.green(), fog.blue(), round(255 * opacity * 0.78)))
        horizontal.setColorAt(0.50, QColor(fog.red(), fog.green(), fog.blue(), round(255 * opacity)))
        horizontal.setColorAt(0.76, QColor(fog.red(), fog.green(), fog.blue(), round(255 * opacity * 0.78)))
        horizontal.setColorAt(1.0, QColor(fog.red(), fog.green(), fog.blue(), round(255 * opacity * 0.48)))
        painter.fillRect(QRectF(0.0, 0.0, width, height), horizontal)

        # Top and bottom mist quietly anchor the controls and final row without flattening the
        # middle of the composition into an opaque card.
        vertical = QLinearGradient(0.0, 0.0, 0.0, height)
        vertical.setColorAt(0.0, QColor(224, 232, 239, 46))
        vertical.setColorAt(0.18, QColor(208, 216, 224, 12))
        vertical.setColorAt(0.78, QColor(208, 216, 224, 5))
        vertical.setColorAt(1.0, QColor(44, 62, 80, 24))
        painter.fillRect(QRectF(0.0, 0.0, width, height), vertical)

    def _draw_wake_feedback(self, painter: QPainter, width: float, height: float) -> None:
        """Show cursor-driven concentration changes without drawing a cursor ring."""
        if not self._controller.wakes:
            return
        shortest = min(width, height)
        base_radius = shortest * max(0.05, min(0.32, self.config.wake_radius))
        highlight_color = self._contrasted_color(self.tokens.glow_soft)
        shadow_color = self._contrasted_color(self.tokens.fluid_deep)

        for wake in self._controller.wakes:
            decay = self._wake_decay(wake)
            visible_strength = wake.strength * decay
            if visible_strength < 0.012:
                continue
            progress = max(0.0, min(1.0, wake.age / max(0.001, wake.lifetime)))
            radius = base_radius * (1.0 + progress * 0.34)

            velocity_x = wake.velocity.x() * width
            velocity_y = wake.velocity.y() * height
            speed_pixels = math.hypot(velocity_x, velocity_y)
            if speed_pixels > 0.001:
                direction_x = velocity_x / speed_pixels
                direction_y = velocity_y / speed_pixels
            else:
                direction_x, direction_y = 1.0, 0.0
            normal_x, normal_y = -direction_y, direction_x
            rotation = math.degrees(math.atan2(direction_y, direction_x))
            center = QPointF(wake.position.x() * width, wake.position.y() * height)
            stretch = 1.0 + min(0.65, speed_pixels / max(shortest, 1.0) * 0.18)

            # Dark pigment lags behind and to one side; a smaller silver-blue concentration forms
            # just ahead on the opposite side.  Sequential impulses merge into a wake rather than
            # a collection of circular cursor glows.
            shadow_center = QPointF(
                center.x() - direction_x * radius * 0.38 - normal_x * radius * 0.08,
                center.y() - direction_y * radius * 0.38 - normal_y * radius * 0.08,
            )
            painter.setCompositionMode(QPainter.CompositionMode_Multiply)
            self._draw_soft_mass(
                painter,
                shadow_center,
                radius * 1.12 * stretch,
                radius * 0.58,
                rotation,
                shadow_color,
                round(255 * min(0.22, self.config.wake_shadow_opacity) * visible_strength * 0.38),
                -0.18,
            )

            highlight_center = QPointF(
                center.x() + direction_x * radius * 0.22 + normal_x * radius * 0.06,
                center.y() + direction_y * radius * 0.22 + normal_y * radius * 0.06,
            )
            painter.setCompositionMode(QPainter.CompositionMode_Screen)
            self._draw_soft_mass(
                painter,
                highlight_center,
                radius * 0.78 * stretch,
                radius * 0.36,
                rotation,
                highlight_color,
                round(255 * min(0.24, self.config.wake_highlight_opacity) * visible_strength * 0.46),
                0.20,
            )

    def _render_frame(self) -> None:
        if self._fluid_frame.isNull() or self._base_layer.isNull():
            return
        self._fluid_frame.fill(Qt.transparent)
        painter = QPainter(self._fluid_frame)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(0, 0, self._base_layer)
        width = float(self._fluid_frame.width())
        height = float(self._fluid_frame.height())
        self._draw_fluid_fields(painter, width, height)
        self._draw_readability_veil(painter, width, height)
        # Kept above the general veil so the interaction remains perceptible.  Its own very low
        # alpha and feathering preserve text readability.
        self._draw_wake_feedback(painter, width, height)
        painter.end()

    def paintEvent(self, event) -> None:
        if self._fluid_frame.isNull():
            self._rebuild_buffers()
            self._render_frame()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self._fluid_frame.isNull():
            painter.drawImage(QRectF(self.rect()), self._fluid_frame)
        else:
            painter.fillRect(self.rect(), QColor(self.tokens.bg_bottom))

        # Grain is applied after upscaling, so it remains a fine frosted texture rather than
        # becoming large blurry squares. The tile is deterministic and never rebuilt per frame.
        if not self._grain_texture.isNull():
            painter.setCompositionMode(QPainter.CompositionMode_SoftLight)
            painter.setOpacity(max(0.0, min(0.08, self.config.grain_strength)))
            painter.drawTiledPixmap(self.rect(), self._grain_texture)
            painter.setOpacity(1.0)

        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        border = QColor(self.tokens.border_frosted)
        border.setAlpha(80)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(border, 1.0))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 18, 18)
        painter.end()
