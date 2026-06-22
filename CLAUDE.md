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
  per-Windows-user key sealing, the opt-in themed mode and its daily pinned row/note UI. The
  personalized payload is committed only as `surprise.enc`; never put its plaintext or passphrase
  in source, tests, documentation, shell arguments, or CI variables.
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

**All interactive content lives in `self.container`** (a transparent child `QWidget` exposed as
`MemoWindow.content`), created directly in `__init__` and kept sized to the window. Both skins
are static surfaces (`geometry_scale = 1.0`), so content fills the window minus a small corner
margin; `_resize_for_content` solves the window height from the content and calls `setFixedSize`.

**Capture-exclusion invariant:** `protect_content_layer()` raises the content layer and calls
`set_window_exclude_from_capture` (`SetWindowDisplayAffinity` / `WDA_EXCLUDEFROMCAPTURE`, now a
plain helper in `window_layer.py`) so screenshots / screen recordings of the desktop don't grab
the widget's own text. It's re-called on show/move/settings-apply with staggered
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
- Collapsed mode also returns `HTBOTTOM` over the bottom resize strip. Todo rows return
  `HTCLIENT` for drag-reordering; calendar rows remain read-only/click-through outside checkbox.
- `window_layer.py` applies tool-window ex-style (no taskbar entry), detaches from any parent,
  and pins topmost.

### Settings → skin dispatch
`apply_settings` resolves `settings.skin` via `_make_skin` (an `"image:<id>"` with a missing file
falls back to `AcrylicSkin`) and dispatches to `_apply_acrylic_mode` / `_apply_image_mode`, which
swap the DWM frost vs. the image layer. `windowTint` tints the acrylic frost; the removed
`glassOpacity` / `liquidStrength` settings were glass-only and no longer exist.

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
markers for its once-per-day completion/note behavior. Disabling it clears those fields and
restores the window mode that was active before activation.

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
