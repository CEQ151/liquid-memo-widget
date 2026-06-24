"""QOpenGLWidget that runs the Stage 1 GPU fluid simulation.

Uses PyOpenGL for GL calls (simpler API, matches WebGL reference) but
explicitly calls makeCurrent()/doneCurrent() in _tick() since QTimer
callbacks do NOT have an active GL context.

PyOpenGL's strict error checking is disabled — it can report stale errors
from Qt's own GL setup as if they came from our calls.
"""
from __future__ import annotations

import ctypes
import math
import random
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QElapsedTimer, QTimer, Signal
from PySide6.QtGui import QCursor, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from OpenGL import GL as glmod
from OpenGL.GL import *  # noqa: F403

from .fluid_config import FluidConfig

SHADER_DIR = Path(__file__).parent / "shaders"
_LOG_PATH = Path(__file__).parent.parent.parent / "_fluid_debug.log"

def _log(msg: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# FBO helpers
# ---------------------------------------------------------------------------
def _create_texture_fbo(w: int, h: int, internal_fmt, fmt, typ) -> dict:
    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    glTexImage2D(GL_TEXTURE_2D, 0, internal_fmt, w, h, 0, fmt, typ, None)

    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0)
    status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
    if status != GL_FRAMEBUFFER_COMPLETE:
        raise RuntimeError(f"FBO incomplete status=0x{status:X}")
    glViewport(0, 0, w, h)
    glClearColor(0, 0, 0, 0)
    glClear(GL_COLOR_BUFFER_BIT)
    return {"texture": tex, "fbo": fbo}


class _SingleFBO:
    def __init__(self, w, h, internal_fmt, fmt, typ):
        self.width = w
        self.height = h
        self.texel_size_x = 1.0 / w
        self.texel_size_y = 1.0 / h
        self._fbo = _create_texture_fbo(w, h, internal_fmt, fmt, typ)

    @property
    def fbo(self):
        return self._fbo["fbo"]

    @property
    def texture(self):
        return self._fbo["texture"]

    def attach(self, unit):
        glActiveTexture(GL_TEXTURE0 + unit)
        glBindTexture(GL_TEXTURE_2D, self.texture)
        return unit

    def delete(self):
        glDeleteFramebuffers(1, [self._fbo["fbo"]])
        glDeleteTextures(1, [self._fbo["texture"]])


class _DoubleFBO:
    def __init__(self, w, h, internal_fmt, fmt, typ):
        self.width = w
        self.height = h
        self.texel_size_x = 1.0 / w
        self.texel_size_y = 1.0 / h
        self._read = _SingleFBO(w, h, internal_fmt, fmt, typ)
        self._write = _SingleFBO(w, h, internal_fmt, fmt, typ)

    @property
    def read(self):
        return self._read

    @property
    def write(self):
        return self._write

    def swap(self):
        self._read, self._write = self._write, self._read

    def delete(self):
        self._read.delete()
        self._write.delete()


# ============================================================================
class FluidGLWidget(QOpenGLWidget):
    fps_changed = Signal(float)

    def __init__(self, config=None, parent=None):
        # NOTE: QSurfaceFormat.setDefaultFormat() must be called BEFORE
        # QApplication is created — see fluid_demo_window.configure_gl_format().
        super().__init__(parent)
        self.cfg = config or FluidConfig()

        self._vbo = 0
        self._vao = 0
        self._programs = {}
        # uniform-location cache: per-program {name: location}, filled lazily on
        # first lookup so the per-frame _step/_render never call glGetUniformLocation.
        self._uloc = {}
        self._cur_name = None
        self._cur_cache = {}

        self._velocity = None
        self._dye = None
        self._pressure = None
        self._divergence = None
        self._curl = None

        self._tex_internal = 0
        self._tex_format = 0
        self._tex_type = 0

        self._timer = QElapsedTimer()
        self._timer.start()
        self._last_ms = self._timer.elapsed()
        self._fps_frames = 0
        self._fps_last_emit = self._timer.elapsed()

        self._paused = False
        self._mouse_x = 0.0
        self._mouse_y = 0.0
        self._prev_mouse_x = 0.0
        self._prev_mouse_y = 0.0
        self._mouse_moved = False
        # When embedded behind a click-through window (surprise mode) the widget never
        # receives Qt mouse events, so ink is driven by polling the global cursor instead.
        self._track_global_cursor = False
        self._global_cursor_prev = None
        self._ambient_timer = 0.0
        self._palette_idx = 0

        self._frame_timer = QTimer(self)
        self._frame_timer.setTimerType(Qt.PreciseTimer)
        self._frame_timer.setInterval(16)
        self._frame_timer.timeout.connect(self._tick)

        self._tick_count = 0
        self._paint_count = 0

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------------
    def initializeGL(self):
        try:
            self._initializeGL_impl()
        except Exception:
            _log("initializeGL CRASH:\n" + traceback.format_exc())
            raise

    def _initializeGL_impl(self):
        _log("=== initializeGL begin ===")

        # Disable PyOpenGL's strict error checking — it can report stale
        # errors from Qt's own GL setup.  PyOpenGL 3.x stores the checker
        # on the _ErrorChecker class inside OpenGL.error.
        try:
            import OpenGL.error
            OpenGL.error._ErrorChecker._checker = lambda *a, **kw: None
        except Exception as e:
            _log(f"could not disable PyOpenGL error checker: {e}")

        glDisable(GL_BLEND)
        glClearColor(0, 0, 0, 1)

        # texture format probe — only floating-point formats; RGBA8 would
        # clamp velocity/pressure to [0,1] and break the simulation.
        for internal, fmt, typ in [
            (GL_RGBA16F, GL_RGBA, GL_HALF_FLOAT),
            (GL_RGBA32F, GL_RGBA, GL_FLOAT),
        ]:
            try:
                _create_texture_fbo(4, 4, internal, fmt, typ)
                self._tex_internal, self._tex_format, self._tex_type = internal, fmt, typ
                break
            except RuntimeError:
                continue
        if not self._tex_internal:
            raise RuntimeError("No floating-point renderable texture format available")
        _log(f"tex fmt internal=0x{self._tex_internal:X} type=0x{self._tex_type:X}")

        # VAO
        self._vao = glGenVertexArrays(1)
        glBindVertexArray(self._vao)
        verts = (GLfloat * 8)(-1, -1, -1, 1, 1, 1, 1, -1)
        self._vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(verts), verts, GL_STATIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, None)
        glBindVertexArray(0)
        _log("VAO+VBO done")

        self._compile_programs()
        self._init_framebuffers(self.width(), self.height())

        for _ in range(8):
            self._splat(random.random(), random.random(),
                        (random.random() - 0.5) * 600,
                        (random.random() - 0.5) * 600,
                        self._ink(0.7))
        _log("seed splats done, starting timer")
        self._last_ms = self._timer.elapsed()
        self._frame_timer.start()
        _log("=== initializeGL done ===")

    def _compile_programs(self):
        vert_src = (SHADER_DIR / "base.vert").read_text(encoding="utf-8")

        def _load(name):
            frag_src = (SHADER_DIR / f"{name}.frag").read_text(encoding="utf-8")

            def _compile(stage, src):
                s = glCreateShader(stage)
                glShaderSource(s, src)
                glCompileShader(s)
                if not glGetShaderiv(s, GL_COMPILE_STATUS):
                    log = glGetShaderInfoLog(s).decode("utf-8", "replace")
                    raise RuntimeError(f"shader [{name}]: {log}")
                return s

            vs = _compile(GL_VERTEX_SHADER, vert_src)
            fs = _compile(GL_FRAGMENT_SHADER, frag_src)
            prog = glCreateProgram()
            glAttachShader(prog, vs)
            glAttachShader(prog, fs)
            glLinkProgram(prog)
            if not glGetProgramiv(prog, GL_LINK_STATUS):
                log = glGetProgramInfoLog(prog).decode("utf-8", "replace")
                raise RuntimeError(f"link [{name}]: {log}")
            glDeleteShader(vs)
            glDeleteShader(fs)
            return prog

        self._programs = {n: _load(n) for n in [
            "clear", "curl", "vorticity", "divergence", "pressure",
            "gradient_subtract", "advection", "diffuse", "splat", "display",
        ]}
        self._uloc = {}
        _log(f"{len(self._programs)} programs compiled")

    def _init_framebuffers(self, w, h):
        # Release the previous set first — resizeGL re-enters this on every window
        # resize and PyOpenGL will not free orphaned GL objects for us.
        for fbo in (self._velocity, self._dye, self._pressure, self._divergence, self._curl):
            if fbo is not None:
                fbo.delete()
        sim_w, sim_h = self._aspect_resolution(self.cfg.sim_resolution, w, h)
        dye_w, dye_h = self._aspect_resolution(self.cfg.dye_resolution, w, h)
        i, f, t = self._tex_internal, self._tex_format, self._tex_type
        self._velocity = _DoubleFBO(sim_w, sim_h, i, f, t)
        self._dye = _DoubleFBO(dye_w, dye_h, i, f, t)
        self._pressure = _DoubleFBO(sim_w, sim_h, i, f, t)
        self._divergence = _SingleFBO(sim_w, sim_h, i, f, t)
        self._curl = _SingleFBO(sim_w, sim_h, i, f, t)
        _log(f"FBO sim={sim_w}x{sim_h} dye={dye_w}x{dye_h}")

    @staticmethod
    def _aspect_resolution(res, w, h):
        aspect = w / h if h else 1.0
        if aspect < 1.0:
            aspect = 1.0 / aspect
        mn = round(res)
        mx = round(res * aspect)
        return (mx, mn) if w > h else (mn, mx)

    def resizeGL(self, w, h):
        self._init_framebuffers(w, h)

    # ------------------------------------------------------------------
    def _blit_to(self, target):
        glBindVertexArray(self._vao)
        if target is None:
            # QOpenGLWidget renders into its own internal framebuffer, NOT
            # framebuffer 0.  Binding 0 here produces a black window even
            # though every shader/FBO call succeeded.
            glBindFramebuffer(GL_FRAMEBUFFER, self.defaultFramebufferObject())
            dpr = self.devicePixelRatioF()
            glViewport(0, 0,
                       max(1, int(self.width() * dpr)),
                       max(1, int(self.height() * dpr)))
        else:
            glViewport(0, 0, target.width, target.height)
            glBindFramebuffer(GL_FRAMEBUFFER, target.fbo)
        glDrawArrays(GL_TRIANGLE_FAN, 0, 4)

    def _use_program(self, name):
        p = self._programs[name]
        glUseProgram(p)
        self._cur_name = name
        self._cur_cache = self._uloc.setdefault(name, {})
        return p

    def _loc(self, name):
        """Uniform location for the currently bound program (cached)."""
        cache = self._cur_cache
        loc = cache.get(name, -2)
        if loc == -2:  # -1 is "not found" and worth caching; -2 means "unknown yet"
            loc = glGetUniformLocation(self._programs[self._cur_name], name)
            cache[name] = loc
        return loc

    def _ink(self, scale=1.0):
        """Neutral ink concentration to deposit; the palette is applied at display."""
        a = self.cfg.ink_amount * scale
        return (a, a, a)

    # ------------------------------------------------------------------
    def _splat(self, x, y, dx, dy, color):
        aspect = self.width() / self.height() if self.height() else 1.0
        radius = self.cfg.splat_radius / 100.0
        if aspect > 1.0:
            radius *= aspect

        self._use_program("splat")
        glUniform1i(self._loc("uTarget"), self._velocity.read.attach(0))
        glUniform1f(self._loc("aspectRatio"), aspect)
        glUniform3f(self._loc("color"), dx, dy, 0.0)
        glUniform2f(self._loc("point"), x, y)
        glUniform1f(self._loc("radius"), radius)
        self._blit_to(self._velocity.write)
        self._velocity.swap()

        glUniform1i(self._loc("uTarget"), self._dye.read.attach(0))
        glUniform3f(self._loc("color"), color[0], color[1], color[2])
        self._blit_to(self._dye.write)
        self._dye.swap()

    # ------------------------------------------------------------------
    def _step(self, dt):
        v = self._velocity
        cfg = self.cfg

        # 1. curl
        self._use_program("curl")
        glUniform2f(self._loc("texelSize"), v.texel_size_x, v.texel_size_y)
        glUniform1i(self._loc("uVelocity"), v.read.attach(0))
        self._blit_to(self._curl)

        # 2. vorticity
        self._use_program("vorticity")
        glUniform2f(self._loc("texelSize"), v.texel_size_x, v.texel_size_y)
        glUniform1i(self._loc("uVelocity"), v.read.attach(0))
        glUniform1i(self._loc("uCurl"), self._curl.attach(1))
        glUniform1f(self._loc("curl"), cfg.curl_strength)
        glUniform1f(self._loc("dt"), dt)
        self._blit_to(v.write)
        v.swap()

        # 3. divergence
        self._use_program("divergence")
        glUniform2f(self._loc("texelSize"), v.texel_size_x, v.texel_size_y)
        glUniform1i(self._loc("uVelocity"), v.read.attach(0))
        self._blit_to(self._divergence)

        # 4. clear pressure
        self._use_program("clear")
        glUniform1i(self._loc("uTexture"), self._pressure.read.attach(0))
        glUniform1f(self._loc("value"), cfg.pressure_decay)
        self._blit_to(self._pressure.write)
        self._pressure.swap()

        # 5. pressure Jacobi
        self._use_program("pressure")
        glUniform2f(self._loc("texelSize"), v.texel_size_x, v.texel_size_y)
        glUniform1i(self._loc("uDivergence"), self._divergence.attach(0))
        for _ in range(cfg.pressure_iterations):
            glUniform1i(self._loc("uPressure"), self._pressure.read.attach(1))
            self._blit_to(self._pressure.write)
            self._pressure.swap()

        # 6. gradient subtract
        self._use_program("gradient_subtract")
        glUniform2f(self._loc("texelSize"), v.texel_size_x, v.texel_size_y)
        glUniform1i(self._loc("uPressure"), self._pressure.read.attach(0))
        glUniform1i(self._loc("uVelocity"), v.read.attach(1))
        self._blit_to(v.write)
        v.swap()

        # 7. advect velocity (decay = 1 + damping*dt -> motion settles quickly)
        self._use_program("advection")
        glUniform2f(self._loc("texelSize"), v.texel_size_x, v.texel_size_y)
        vid = v.read.attach(0)
        glUniform1i(self._loc("uVelocity"), vid)
        glUniform1i(self._loc("uSource"), vid)
        glUniform1f(self._loc("dt"), dt)
        glUniform1f(self._loc("decay"), 1.0 + cfg.velocity_damping * 1.4 * dt)
        self._blit_to(v.write)
        v.swap()

        # 8. advect dye (decay = 1/persistence -> ink keeps `persistence` each step)
        glUniform2f(self._loc("texelSize"), v.texel_size_x, v.texel_size_y)
        glUniform1i(self._loc("uVelocity"), v.read.attach(0))
        glUniform1i(self._loc("uSource"), self._dye.read.attach(1))
        glUniform1f(self._loc("decay"), 1.0 / max(cfg.dye_persistence, 1e-4))
        self._blit_to(self._dye.write)
        self._dye.swap()

        # 9. diffuse dye (晕开) — gentle so it bleeds without leaving cross artefacts
        if cfg.dye_diffusion > 0.001:
            d = self._dye
            self._use_program("diffuse")
            glUniform2f(self._loc("texelSize"), d.texel_size_x, d.texel_size_y)
            glUniform1i(self._loc("uSource"), d.read.attach(0))
            glUniform1f(self._loc("amount"), cfg.dye_diffusion * 0.25)
            self._blit_to(d.write)
            d.swap()

    def _render(self):
        glDisable(GL_BLEND)
        cfg = self.cfg
        self._use_program("display")
        glUniform2f(self._loc("texelSize"), 1.0 / self._dye.width, 1.0 / self._dye.height)
        glUniform1i(self._loc("uDye"), self._dye.read.attach(0))
        glUniform3f(self._loc("uPaper"), *cfg.paper)
        glUniform3f(self._loc("uMid"), *cfg.ink_mid)
        glUniform3f(self._loc("uDeep"), *cfg.ink_deep)
        glUniform1f(self._loc("uDensity"), cfg.ink_density)
        glUniform1f(self._loc("uGamma"), cfg.tone_gamma)
        glUniform1f(self._loc("uEdge"), cfg.edge_strength)
        glUniform1f(self._loc("uDry"), cfg.dry_brush)
        glUniform1f(self._loc("uPaperTex"), cfg.paper_texture)
        self._blit_to(None)

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._update_mouse(event)

    def mouseMoveEvent(self, event):
        self._update_mouse(event)
        self._mouse_moved = True

    def _update_mouse(self, event):
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        self._prev_mouse_x = self._mouse_x
        self._prev_mouse_y = self._mouse_y
        self._mouse_x = event.position().x() / w
        self._mouse_y = 1.0 - event.position().y() / h

    def set_global_cursor_tracking(self, enabled: bool) -> None:
        """Drive ink from the global cursor (QCursor.pos) instead of Qt mouse events.

        Needed when the widget sits behind a click-through window (surprise mode),
        where it never receives mouseMoveEvent.
        """
        self._track_global_cursor = enabled
        self._global_cursor_prev = None

    def _brush_splat(self, x, y, px, py):
        # Brush model: a slow stroke lays down more ink, a fast one less (飞白).
        dx = max(-8000.0, min(8000.0, (x - px) * self.cfg.splat_force))
        dy = max(-8000.0, min(8000.0, (y - py) * self.cfg.splat_force))
        speed = math.hypot(x - px, y - py)
        if abs(dx) > 0.5 or abs(dy) > 0.5:
            self._splat(x, y, dx, dy, self._ink(min(1.0, 0.3 + speed * 14.0)))

    def _apply_mouse(self):
        if not self._mouse_moved:
            return
        self._mouse_moved = False
        self._brush_splat(self._mouse_x, self._mouse_y, self._prev_mouse_x, self._prev_mouse_y)

    def _poll_global_cursor(self):
        local = self.mapFromGlobal(QCursor.pos())
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        if not (0 <= local.x() < w and 0 <= local.y() < h):
            self._global_cursor_prev = None  # left the widget — don't streak across on re-entry
            return
        x = local.x() / w
        y = 1.0 - local.y() / h
        if self._global_cursor_prev is not None:
            self._brush_splat(x, y, *self._global_cursor_prev)
        self._global_cursor_prev = (x, y)

    # ------------------------------------------------------------------
    def _tick(self):
        """QTimer callback — must make GL context current explicitly."""
        if self._velocity is None:
            return
        try:
            self.makeCurrent()
            now = self._timer.elapsed()
            dt = (now - self._last_ms) / 1000.0
            self._last_ms = now
            dt = min(dt, self.cfg.max_dt)

            self._ambient_timer += dt
            if self._ambient_timer >= self.cfg.ambient_splat_interval:
                self._ambient_timer = 0.0
                # Bias ambient ink toward the side margins so the centre stays as
                # 留白 (clear paper) for text.
                ex = random.random() * 0.28 if random.random() < 0.5 else 1.0 - random.random() * 0.28
                self._splat(ex, random.random(),
                            (random.random() - 0.5) * self.cfg.ambient_splat_force,
                            (random.random() - 0.5) * self.cfg.ambient_splat_force,
                            self._ink(0.5))

            if self._track_global_cursor:
                self._poll_global_cursor()
            else:
                self._apply_mouse()
            if not self._paused:
                self._step(dt)

            self._fps_frames += 1
            if now - self._fps_last_emit >= 500:
                fps = self._fps_frames * 1000.0 / (now - self._fps_last_emit)
                self.fps_changed.emit(fps)
                self._fps_frames = 0
                self._fps_last_emit = now

            self._tick_count += 1
            if self._tick_count <= 5:
                _log(f"_tick #{self._tick_count} dt={dt:.4f}")
        except Exception:
            _log("EXCEPTION in _tick:\n" + traceback.format_exc())
        finally:
            self.doneCurrent()

        self.update()

    def paintGL(self):
        if self._velocity is None:
            return
        try:
            self._render()
            self._paint_count += 1
            if self._paint_count <= 5:
                _log(f"paintGL #{self._paint_count}")
        except Exception:
            _log("EXCEPTION in paintGL:\n" + traceback.format_exc())

    # ------------------------------------------------------------------
    def reset_fluid(self):
        self.makeCurrent()
        for t in [self._velocity.read, self._velocity.write,
                   self._dye.read, self._dye.write,
                   self._pressure.read, self._pressure.write]:
            glBindFramebuffer(GL_FRAMEBUFFER, t.fbo)
            glClearColor(0, 0, 0, 0)
            glClear(GL_COLOR_BUFFER_BIT)
        self.doneCurrent()
        _log("reset done")

    def set_config(self, cfg):
        """Swap config live. Palette/tone/motion apply next frame; sim/dye
        resolution is read only at init, so those need a restart to change."""
        self.cfg = cfg

    def toggle_pause(self):
        self._paused = not self._paused
        _log(f"paused={self._paused}")

    def is_paused(self):
        return self._paused