# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows 11 desktop memo/todo widget rendered as a translucent surface floating on the desktop.
The window is a lightweight **DWM acrylic frost** (the default "磨砂玻璃" skin) or a static
user-supplied **image background**, with a Qt content layer (todo rows, buttons) on top.
Windows-only (Win32 + DWM); will not run or build on other platforms.

> History: earlier versions also offered a real-time D3D11 "液态玻璃" (liquid glass) skin that
> screen-captured the desktop behind the window and refracted it through GPU effects. That skin
> was removed (it was buggy and heavy); the vendored `WindowsLiquidGlass` engine, the capture /
> effect pipeline, and the `numpy` dependency are all gone. Don't reintroduce a screen-capture
> render path.

UI strings are Chinese. Code/identifiers are English.

## Commands

```powershell
# Run from source (preferred entry point — pythonw = no console window)
python -m pip install -r .\LiquidMemoWidget\requirements.txt
pythonw .\RunLiquidMemoWidget.pyw

# Headless regression suite (Qt uses the offscreen platform in tests/conftest.py)
py -3.13 -m pytest .\tests -q

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

The regression suite lives under `tests/`; there is no linter configured. Releases are produced by
`.github/workflows/release.yml`, triggered by pushing a `v*` tag. **Before tagging a release:**
bump `APP_VERSION` in `LiquidMemoWidget/version.py` and add a `## vX.Y.Z` section to
`CHANGELOG.md` documenting the changes — the workflow extracts that section as the GitHub
Release body (and fails without it); the in-app update dialog and post-update changelog
render the same text.

## Architecture

### Module layout
The Qt app lives under `LiquidMemoWidget/` and uses **flat imports** (bare module names,
resolved via a `sys.path` insert in the entry point), so modules reference each other
directly (`from ui_common import ...`). `from __future__ import annotations` everywhere
keeps type hints lazy, so windows/managers reference each other by duck-typed `self.app`
without import cycles. Key files:
- `ui_common.py` — shared leaf module: fonts/colors/helpers, the `SETTING_*` typography
  constants, `enlarge_control_font`/`set_label_font`, `FluentSettingRow`, `InfoToolTipFilter`,
  `FramelessDragMixin`, `tray_icon`. Imports no app/window/engine code.
- `settings_ui.py` — `SettingsWindow`.  `update_ui.py` — update dialogs + `UpdateManager`.
  `calendar_manager.py` — `CalendarManager` + sync tasks.
- `floating_launcher.py` — the painted 72px launcher plus `FloatingModeController`, pure panel-
  placement helpers, and launcher deadline-status calculation.
- `surprise_crypto.py` / `surprise_mode.py` — authenticated encrypted optional-content loading,
  per-Windows-user key sealing, the opt-in themed mode and its daily pinned row/note UI. Also home
  to `NoteTheme` / `NOTE_THEMES` (the three selectable 拾光纸条 palettes — qinghua/warm/blush —
  keyed by `settings.surpriseNoteTheme`) which colour the note popup, the in-memo row, and (via the
  matching keys in `surprise_swirl`/`surprise_ink`) the swirl background. The personalized payload
  is committed only as `surprise.enc`; never put its plaintext or passphrase in source, tests,
  documentation, shell arguments, or CI variables.
- `surprise_swirl.py` — the animated "fluid" background's `QPainter` fallback, shown only while
  surprise mode is active. Pure `QWidget`/`QPainter` (no GPU, no screen capture); exports
  `SwirlPainterFallback` (the widget), `SwirlThemeTokens`/`SwirlConfig`, `SwirlInteractionController`,
  and `SWIRL_TOKENS_BY_THEME`/`swirl_tokens(theme_key)` (per-note-theme palettes).
- `surprise_ink.py` — `make_surprise_background(parent, theme_key)`: returns the GPU ink-wash
  (`experimental_fluid.FluidGLWidget`, themed via `_INK_PALETTE_BY_THEME`) when OpenGL is usable,
  else the themed `SwirlPainterFallback`. `app.py` drives whichever it returns through `SurpriseSkin`.
- `app.py` — `MemoWindow` (the translucent window), the memo content widgets/popups,
  `HistoryWindow`, the `AcrylicSkin`/`ImageSkin` skins, and `LiquidMemoApp`
  (lifecycle/orchestration); imports the four modules above.
- `updater.py` — Qt-free update logic. New first-party modules ship via `--add-data` and are
  imported at runtime, so splitting `app.py` further needs **no `Build.ps1` change** (only new
  *third-party* imports need a `--hidden-import`).

### Two-layer rendering model
`MemoWindow` (in `LiquidMemoWidget/app.py`) is a plain translucent `QWidget`
(`WA_TranslucentBackground`, frameless `Qt.Tool`, topmost). The window's surface is supplied
by the active skin, not by Qt painting:
- **`AcrylicSkin` (default):** `WindowsWindowEffect.setAcrylicEffect` applies a DWM acrylic frost
  to the hwnd; `set_rounded_corners` rounds it. No screen capture, no GPU effects, no per-frame loop.
- **`ImageSkin`:** an `_ImageBackground` child paints a cover-scaled static image below the content.
- **`SurpriseSkin` (kind `"surprise_swirl"`):** an animated ink-wash surface painted below the
  content, themed to `settings.surpriseNoteTheme` (qinghua blue / warm sepia / blush rose). The
  background widget comes from `surprise_ink.make_surprise_background(parent, theme_key)` — the GPU
  ink-wash (`experimental_fluid.FluidGLWidget`) when OpenGL is available, else the `QPainter`
  `SwirlPainterFallback`. This is the one **animated** skin (a timer-driven loop, started/stopped on
  show/hide); the "no per-frame loop" note above is specific to the static frost/image skins. The
  invariant that still holds for *every* skin is **no desktop screen
  capture** — animation done in-process is fine; sampling/refracting the desktop
  behind the window is the removed glass path and must not come back.

**All interactive content lives in `self.container`** (a transparent child `QWidget` exposed as
`MemoWindow.content`), created directly in `__init__` and kept sized to the window. All three
skins use full-fill geometry (`geometry_scale = 1.0`), so content fills the window minus a small
corner margin; `_resize_for_content` solves the window height from the content and calls
`setFixedSize`.

**Capture-exclusion policy:** `protect_content_layer()` raises the content layer and calls
`protect_window_from_capture` (`window_layer.py`), which applies the process-wide policy via
`SetWindowDisplayAffinity` (`WDA_EXCLUDEFROMCAPTURE` vs `WDA_NONE`). By default the memo, launcher,
and surprise note dialog opt out of capture so screenshots / recordings of the desktop don't grab
the widget's text; the `行为 → 允许被截屏` toggle (`Settings.allowScreenshot`) flips it. The policy
is a module global set by `window_layer.set_capture_exclusion` — the app sets it from settings
before any window is created and re-applies live via `LiquidMemoApp.apply_capture_policy()` when the
toggle changes (the decoupled launcher / note dialog read the policy in their `showEvent` instead of
holding an app reference). It's re-applied on show/move/settings-apply with staggered
`QTimer.singleShot` retries because Windows resets the affinity on various window-state changes.

### Text color is deterministic (no sampling)
There is no live desktop sampling anymore (that was glass-only). `_normal_text_color` picks text
deterministically: `AcrylicSkin` chooses a soft dark/light by the **frost tint's** luminance
(`windowTint`); `ImageSkin` chooses by the **image's mean luminance**, but honors a manual color
when `fontColorMode == "manual"`. `text_needs_halo()` is always `False` (flat surfaces). When
editing text-color logic, do not add a screen-capture/GDI sampler back in.

### Native window behavior (`window_layer.py` + `MemoWindow.nativeEvent`)
The widget handles Win32 messages directly (no Qt-driven move):
- `WM_NCHITTEST` → `HTCAPTION` over the drag handle (native move), `HTCLIENT` over interactive
  controls (checkboxes, buttons), and `HTTRANSPARENT` everywhere else so clicks pass through to
  the desktop. This click-through is the `alwaysVisibleClickThrough` layer mode (the only
  supported `layerMode` — `state_store.py` force-normalizes any other value).
- `WM_ENTERSIZEMOVE/WM_EXITSIZEMOVE` bracket a native move (`_begin_window_move`/`_end_window_move`,
  which just track state, persist position, and re-protect the content layer — the frost / image
  follows the window natively, so there's nothing to spin up).
- Todo rows return `HTCLIENT` for drag-reordering; calendar rows remain
  read-only/click-through outside their checkbox.
- `window_layer.py` applies tool-window ex-style (no taskbar entry), detaches from any parent,
  and pins topmost.

### Settings → skin dispatch
`apply_settings` resolves `settings.skin` via `_make_skin` and dispatches on the resolved skin's
`kind` to `_apply_acrylic_mode` / `_apply_image_mode` / `_apply_surprise_swirl_mode`, which swap
the DWM frost, the image layer, or the animated swirl layer. `_make_skin` precedence:
`"surprise_swirl"` resolves to `SurpriseSkin` **only while surprise mode is active** (otherwise it
falls back to `AcrylicSkin`, so the encrypted-only swirl can never render or appear in the picker
without the decrypted payload); an `"image:<id>"` with a missing file falls back to `AcrylicSkin`;
otherwise `AcrylicSkin`. The swirl is a real, *selectable* skin: activation auto-switches to it
(remembering the prior skin in `preSurpriseSkin`) but the user can pick frost/image while still in
surprise mode, and deactivation restores `preSurpriseSkin`. The swirl/ink-wash colour follows
`settings.surpriseNoteTheme` (`SurpriseSkin.text_override` + `make_surprise_background(parent,
theme_key)`; `MemoWindow._surprise_swirl_theme` rebuilds the background widget when the theme
changes). `windowTint` tints the acrylic frost; the removed `glassOpacity` / `liquidStrength`
settings were glass-only and no longer exist.

### State & persistence (`state_store.py`)
Dataclasses `AppState / Settings / WindowState / TodoItem` serialize to
`%APPDATA%\Roaming\DesktopMemo_Pro\liquid-state.json`. Writes are atomic (temp file +
`replace`); a corrupt file is backed up as `liquid-state.bad-<timestamp>.json` and a fresh
state is returned. Saves are normally debounced through `LiquidMemoApp.save_later()` (350ms);
use `save()` directly only when immediate persistence is required. Completed todos move to
`history` (archive) or stay dimmed in-place depending on `completeBehavior`.
`Settings.windowMode` is one of `normal`, `edgeHide`, or `floatingLauncher`; v4
`edgeAutoHide` state migrates into that enum. The launcher position is stored independently from
the memo position and clamped to the live monitor layout when shown.
State v6 adds the optional encrypted-mode flags, a DPAPI-protected derived key, and date/index
markers for its once-per-day completion/note behavior, plus `surpriseNoteTheme` (the selectable
拾光纸条 palette, also driving the swirl colour) and `preSurpriseSkin` (the skin to restore on
exit, mirroring `preSurpriseWindowMode`). Activation forces `windowMode = floatingLauncher` and
auto-selects `skin = "surprise_swirl"`. Disabling it clears the encrypted-mode fields and restores
both the window mode and the skin that were active before activation. `"surprise_swirl"` is an
accepted stored `skin` value (so an active session survives a restart) but only renders / appears
in the picker while surprise mode is active.

### Encrypted optional payload
`tools/encrypt_surprise.py` reads a gitignored private JSON and prompts twice for the passphrase;
it writes `LiquidMemoWidget/surprise.enc` using scrypt plus AES-256-GCM. Only that ciphertext is
distributed. At first activation the derived key is sealed with Windows DPAPI and stored in the
normal app state, so the same Windows user does not have to type the passphrase again. To rebuild
the payload locally:

```powershell
py -3.13 .\tools\encrypt_surprise.py .\private\surprise.json
```

The plaintext input is intentionally ignored by Git and should be deleted after encryption.

### App lifecycle (`LiquidMemoApp`)
Owns the `QApplication`, the `MemoWindow`, the `SettingsWindow`/`HistoryWindow` dialogs, and
the system tray (`QSystemTrayIcon`). `setQuitOnLastWindowClosed(False)` — closing the window
hides it; exit happens only via the tray menu. `startup.py` toggles a `HKCU\...\Run` registry
entry for launch-at-login.
`FloatingModeController` owns the separate launcher top-level window and decides at startup and
runtime whether to show the memo, edge-dock it, or expose only the launcher. In launcher mode the
memo is an anchored popover and must not overwrite the saved normal-window position.

### Auto-update (`updater.py` + `update_ui.py`)
In-app update over GitHub Releases: `updater.py` is Qt-free network/process logic;
`update_ui.py` owns the dialogs and the `UpdateManager` orchestration. Flow: fetch latest release
(GitHub API, falling back to the rate-limit-free `releases.atom` feed) → if newer, prompt with
release notes → download the `-Setup-*.exe` to `%TEMP%` → **verify SHA256** → spawn a detached
`--apply-update` helper (this same exe) that asks the app to shut down, waits briefly, and—only
after verifying the stuck PID still belongs to that exact executable—force-terminates it if a Qt
worker prevents process exit; it then runs the Inno installer silently and relaunches.
`pendingUpdateVersion` persists across the restart so a failed install surfaces a notice next
launch. The helper records checksum, exit, installer-return-code, and relaunch events in
`%TEMP%\LiquidMemoWidget-update.log`.

**Release-asset contract** (produced by `release.yml` / `Package.ps1`, consumed by `updater.py`):
- `LiquidMemoWidget-Setup-vX.Y.Z.exe` + `.sha256` sidecar (`<hash>  <name>`, sha256sum layout)
- `LiquidMemoWidget-Portable-vX.Y.Z.zip` + `.sha256` sidecar
- The installer is verified against its sidecar before the silent install (mismatch aborts;
  a release with no sidecar — older versions — skips verification rather than fail-closed).
- The portable zip carries a `portable.flag` marker (never in the installer). `is_portable_build()`
  detects it: a portable copy must NOT silent-install over itself, so its update button just opens
  the release page.

The silent startup check is throttled (`Settings.lastUpdateCheckAt`, every 12h), gated by
`Settings.autoCheckUpdates` (a 关于-section toggle), and won't re-prompt for a version the user
dismissed (`Settings.lastDismissedUpdateVersion`); a manual "检查更新" bypasses all of these.

### GPU fluid ink-wash (`LiquidMemoWidget/experimental_fluid/`)
An OpenGL 3.3 Core / `QOpenGLWidget` + PyOpenGL fluid solver (curl → vorticity → divergence →
pressure Jacobi → gradient-subtract → advection → splat, GLSL in `shaders/`). The algorithm was
ported from the WebGL reference (`WebGL-Fluid-Simulation/`, kept locally but **gitignored** — it's
a port source, not needed at runtime; see `THIRD_PARTY_NOTICES.md`). Run the standalone tuner demo:
`python -m LiquidMemoWidget.experimental_fluid.fluid_demo_window`.

This **ships**: `surprise_ink.make_surprise_background(parent, theme_key)` returns `FluidGLWidget`
(themed via `fluid_config.FluidConfig`) as the surprise-mode background when OpenGL is usable, and
falls back to the QPainter `surprise_swirl.SwirlPainterFallback` otherwise. Both expose the same
lifecycle (`start`/`stop`/`setActive`/`cleanup`/`setGeometry`/`set_theme`); `MemoWindow` drives
whichever it gets through `SurpriseSkin`.
- **PyOpenGL is a real dependency** — present in `requirements.txt` and bundled by `Build.ps1`
  (`--collect-all OpenGL`, the `OpenGL.platform.win32` / `PySide6.QtOpenGL*` hidden-imports). The
  whole `experimental_fluid/` (incl. `shaders/`) ships via the existing `--add-data LiquidMemoWidget`.
- `set_theme(theme_key)` recolours in place (GL uploads the palette uniforms each frame; the swirl
  re-bakes its colour layers), so a note-theme switch never rebuilds the GL context.
- `fluid_demo_window.py` / `inkwash_tuner.html` are dev-only tools (committed, not used at runtime).
  `_fluid_debug.log` (repo root) and `experimental_fluid/fenxi.txt` / `surprise_bg_spike.py` are
  scratch, gitignored; don't treat them as sources of truth.
