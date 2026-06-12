# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows 11 desktop memo/todo widget rendered as a translucent "Liquid Glass" surface.
It is a real-time GPU screen-capture widget: it continuously captures the desktop region
behind itself and refracts it through D3D11 effects, with a Qt content layer (todo rows,
buttons) floating on top. Windows-only (Win32 + D3D11); will not run or build on other platforms.

UI strings are Chinese. Code/identifiers are English.

## Commands

```powershell
# Run from source (preferred entry point — pythonw = no console window)
python -m pip install -r .\LiquidMemoWidget\requirements.txt
pythonw .\RunLiquidMemoWidget.pyw

# Build a PyInstaller bundle into dist\LiquidMemoWidget\
.\Build.ps1

# Package portable zip + Inno Setup installer (needs Inno Setup 6 on PATH or via -InnoSetupPath)
.\Package.ps1 -Version 0.0.1
.\Package.ps1 -Version 0.0.1 -SkipInstaller   # zip only
```

**PyInstaller pitfall:** app sources under `LiquidMemoWidget/` ship via `--add-data` and are
imported only at runtime, so PyInstaller never analyzes their imports. Any new stdlib or
third-party module imported there must also be added to `Build.ps1` as `--hidden-import`
(this shipped a launch crash once: `xml.etree` was missing). Smoke-test
`dist\LiquidMemoWidget\LiquidMemoWidget.exe` after changing imports.

There are **no automated tests and no linter configured**. `one_d3d_widget.py` has a manual
`__main__` smoke-test entry that renders a standalone glass square. Releases are produced by
`.github/workflows/release.yml`, triggered by pushing a `v*` tag. **Before tagging a release:**
bump `APP_VERSION` in `LiquidMemoWidget/version.py` and add a `## vX.Y.Z` section to
`CHANGELOG.md` documenting the changes — the workflow extracts that section as the GitHub
Release body (and fails without it); the in-app update dialog and post-update changelog
render the same text.

## Architecture

### Two-layer rendering model
`MemoWindow` (in `LiquidMemoWidget/app.py`) subclasses `OneGPUWidget` from the vendored
`WindowsLiquidGlass` engine. The window itself is the D3D-rendered glass surface. **All
interactive content lives in `self.container`** (a transparent child `QWidget` exposed as
`MemoWindow.content`), never directly on the window — the D3D background cannot host
transparent children otherwise.

**Critical invariant:** the content layer must be excluded from screen capture via
`set_window_exclude_from_capture` (`SetWindowDisplayAffinity` / `WDA_EXCLUDEFROMCAPTURE`).
Otherwise the next captured frame includes the widget's own text and refracts it into noise.
`protect_content_layer()` enforces this and is re-called aggressively (on show, move, settings
apply, with staggered `QTimer.singleShot` retries) because Windows resets the affinity on
various window-state changes.

### One capture system, validated before present
`MemoWindow._on_frame` **overrides** the stock `OneGPUWidget._on_frame` loop: every captured
frame is read back (`copy_resource_to_numpy`) and checked by `_frame_looks_blank` before
effects render and present. This exists because Windows desktop duplication intermittently
delivers all-black frames for this `WDA_EXCLUDEFROMCAPTURE` window's region — presenting
them unchecked makes the glass flash black↔transparent (a real shipped bug, twice). Blank
frames are dropped (and their pool resource freed) while the last good output stays on
screen. The loop runs at `REST_FPS` (20) idle / `MOVE_FPS` (30) while dragging — the glass
is a static transform of the background, so 60fps is never needed.

The adaptive-contrast sampler (`_sample_background`) reuses `_latest_frame` cached by that
loop and analyzes it with numpy. Do NOT add a separate GDI/`grabWindow` screen capture for
sampling: periodic GDI captures of an excluded window's region force DWM capture
recompositions that feed black frames into the duplication stream (the original flicker
trigger).

### Capture pipeline goes stale and must be reset
DWM display capture becomes invalid after idle / display changes. `reset_capture_pipeline()`
tears down and re-initializes the capture source; `refresh_capture_after_idle()` decides
between a full reset (>45s idle) and a cheap position resync. When touching move/show/settings
flows, preserve these reset calls — dropping them produces a frozen or blank glass surface.

### Native window behavior (`window_layer.py` + `MemoWindow.nativeEvent`)
The widget runs with `qt_move=False` and handles Win32 messages directly:
- `WM_NCHITTEST` → `HTCAPTION` over the drag handle (native move), `HTCLIENT` over interactive
  controls (checkboxes, buttons), and `HTTRANSPARENT` everywhere else so clicks pass through to
  the desktop. This click-through is the `alwaysVisibleClickThrough` layer mode (the only
  supported `layerMode` — `state_store.py` force-normalizes any other value).
- `WM_ENTERSIZEMOVE/WM_EXITSIZEMOVE` bracket a native move; during a move the frame loop drops
  to 30 fps and auto-contrast is paused, then restored on exit.
- `window_layer.py` applies tool-window ex-style (no taskbar entry), detaches from any parent,
  and pins topmost.

### Adaptive text contrast (`update_auto_contrast` + `liquid_effects.py`)
When `fontColorMode != "manual"`, a 220ms timer samples the desktop behind the window,
computes a luminance/edge "complexity" score, and picks text color: dark/light for calm
backgrounds, or one of `HIGH_VISIBILITY_COLORS` (neon) when the background is "extremely busy"
(e.g. terminal/text-heavy). `autoEnhanced` mode additionally applies a soft halo
(`QGraphicsDropShadowEffect`) behind text. The sampled background is blended with the window
tint using `color_overlay_strength(glassOpacity)` to estimate the *effective* color seen
through the glass.

### Effect parameters
`liquid_effects.build_effect_params` is the single place that maps user settings
(`windowTint`, `glassOpacity`, `liquidStrength`) onto the engine's `EFFECTS_PARAMS` dict
(flow, chromatic aberration, highlight, anti-aliasing, color overlay). Effects are only
re-uploaded when the `_effect_signature` tuple changes, to avoid per-frame churn.

### State & persistence (`state_store.py`)
Dataclasses `AppState / Settings / WindowState / TodoItem` serialize to
`%APPDATA%\Roaming\DesktopMemoWidget\liquid-state.json`. Writes are atomic (temp file +
`replace`); a corrupt file is backed up as `liquid-state.bad-<timestamp>.json` and a fresh
state is returned. Saves are normally debounced through `LiquidMemoApp.save_later()` (350ms);
use `save()` directly only when immediate persistence is required. Completed todos move to
`history` (archive) or stay dimmed in-place depending on `completeBehavior`.

### App lifecycle (`LiquidMemoApp`)
Owns the `QApplication`, the `MemoWindow`, the `SettingsWindow`/`HistoryWindow` dialogs, and
the system tray (`QSystemTrayIcon`). `setQuitOnLastWindowClosed(False)` — closing the window
hides it; exit happens only via the tray menu. `startup.py` toggles a `HKCU\...\Run` registry
entry for launch-at-login.

## Vendored dependency: `WindowsLiquidGlass/`

This is an adapted copy of [ai12989757/WindowsLiquidGlass](https://github.com/ai12989757/WindowsLiquidGlass)
providing the D3D screen-capture, rounded-rect SDF, GPU effect renderer, and Qt glass widget.
It ships **prebuilt `.dll` and compiled shader (`.cso`) binaries** under each module's `bin/`.
The C++/HLSL sources are built via the per-module `build.bat` / `bulider.bat` scripts (require
a Windows D3D toolchain) — they are **not** part of the normal Python build and you rarely need
to rebuild them. Treat this directory as a third-party boundary; the integration surface used
by the app is just `OneGPUWidget`, `EffectType`, `EFFECTS_PARAMS`, and
`set_window_exclude_from_capture` imported in `app.py`. See `THIRD_PARTY_NOTICES.md`.
