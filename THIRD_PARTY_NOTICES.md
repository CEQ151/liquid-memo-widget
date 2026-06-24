# Third-Party Notices

This project includes and adapts third-party components. Their original authorship and license
terms remain in effect.

> Note: earlier versions vendored the `WindowsLiquidGlass` D3D11 "liquid glass" rendering engine
> (<https://github.com/ai12989757/WindowsLiquidGlass>, MIT). That real-time refraction skin was
> removed; the widget now renders as a lightweight DWM acrylic / static-image surface, so the
> engine and its native DLLs / compiled shaders are no longer included.

## Python Dependencies

Runtime Python dependencies are listed in `LiquidMemoWidget/requirements.txt`. Their licenses are
defined by their respective upstream projects, including but not limited to:

- PySide6
- PySide6-Fluent-Widgets
- PyOpenGL
- cryptography
- icalendar
- recurring-ical-events

## Ink-wash fluid background

The optional animated ink-wash background renders with a GLSL fluid solver written for OpenGL 3.3
Core / PySide6 `QOpenGLWidget`. No source is copied verbatim, but the algorithm structure (curl →
vorticity → divergence → pressure Jacobi → gradient-subtract → advection → splat) is adapted from:

- Pavel Dobryakov, *WebGL-Fluid-Simulation* (<https://github.com/PavelDoGreat/WebGL-Fluid-Simulation>, MIT)
- Jos Stam, *Stable Fluids* (SIGGRAPH 1999)

## Notes

No ownership over third-party code is claimed by this repository. If additional upstream notices
or license files become available, they should be preserved here.
