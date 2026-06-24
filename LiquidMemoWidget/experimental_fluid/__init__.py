# experimental_fluid — Stage 1 GPU fluid simulation prototype.
#
# Algorithm inspired by Pavel Dobryakov's WebGL-Fluid-Simulation (MIT License,
# https://github.com/PavelDoGreat/WebGL-Fluid-Simulation) and Jos Stam's
# "Stable Fluids" (1999). Shader code is rewritten for OpenGL 3.3 Core /
# PySide6 QOpenGLWidget; no source code is copied verbatim, but the algorithm
# structure (curl -> vorticity -> divergence -> pressure Jacobi -> gradient
# subtract -> advection -> splat) follows that reference.
#
# The fluid solver here now SHIPS: surprise_ink.make_surprise_background() uses
# FluidGLWidget (themed via fluid_config) as the surprise-mode ink-wash background
# when OpenGL is available, falling back to the QPainter surprise_swirl otherwise.
# PyOpenGL is therefore a real runtime dependency (requirements.txt + Build.ps1).
# fluid_demo_window.py / inkwash_tuner.html remain dev-only tools (not shipped).
