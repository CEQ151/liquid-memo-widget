<div align="center">

# 🪟 Liquid Memo Widget

**A translucent frosted-glass desktop memo & todo widget for Windows 11**

A translucent DWM acrylic frost (or a custom static image background) floating todos, deadlines,
and calendar events on the desktop.

[中文](README.md) · English

![Platform](https://img.shields.io/badge/platform-Windows%2011-0078D6?logo=windows11&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Render](https://img.shields.io/badge/render-DWM%20Acrylic%20%2B%20Qt-5C2D91)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

---

## ✨ Features

### 🎨 Visuals
- **Frosted-glass skin (default)** — a translucent surface built on Windows' own DWM acrylic
  effect: light on resources, crisp text, no GPU screen capture.
- **Image background skin** — upload and crop an image to use as a static background skin,
  switchable any time in settings.
- **Tunable tint** — adjust the frost's low-saturation background tint and customize the normal /
  urgent todo text colors.

> Earlier versions also offered a real-time "liquid glass" D3D11 skin that captured and refracted
> the desktop behind the window. It was removed (buggy and heavy on size).

### ✅ Todos
- **Todo-focused surface** — quickly add and check off items; completed items archive or stay
  dimmed in place (configurable).
- **Deadlines (DDL)** — each todo has its own deadline column accepting flexible formats
  (`6-15 23:59`, `2026/6/15`, `6月15日`); approaching deadlines change color and overdue ones
  are highlighted.
- **Urgent pinning** — mark with `❗` to turn the text red and pin it to the top.
- **Expand / collapse** — expand to see everything, collapse back to a compact square.

### 📅 Calendar Subscription
- **ICS / webcal subscription** — paste a subscription URL in settings to auto-sync the next N
  days (default 7, up to 30) of events into a dedicated "日程" (Schedule) group.
- **Offline cache** — the last sync is persisted so events remain visible after a restart with
  no network; checked-off events stay remembered across re-syncs (dimmed + strikethrough).

### 🖱️ Desktop Interaction
- **Three display modes**: regular floating memo, sliding edge auto-hide, or an animated floating launcher that opens on click and retracts after the pointer leaves.
- **Click-through** — clicks over the translucent surface pass through to the desktop; only
  checkboxes and buttons capture input, so the widget never gets in your way.
- **Native movement and sizing** — move via `⋮⋮`, resize collapsed mode from the bottom edge,
  or freely drag the launcher and have its position remembered.
- **Global wheel scroll** — scroll through content when it overflows.
- **System tray** — tray menu for Settings, History, Show/Hide, and Exit.
- **Launch at login** — toggle start-with-Windows in settings.

> ⚠️ Windows-only (Win32 + DWM); will not run or build on other platforms. UI strings are
> Chinese; code identifiers are English.

---

## 🚀 Run From Source

```powershell
python -m pip install -r .\LiquidMemoWidget\requirements.txt
pythonw .\RunLiquidMemoWidget.pyw    # pythonw = no console window
```

---

## 🔨 Build

```powershell
.\Build.ps1
```

The build output is generated under `dist\LiquidMemoWidget`.

---

## 📦 Package Locally

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then run (replace the version number
with the one you are packaging):

```powershell
.\Package.ps1 -Version <version>
```

This creates:

- `dist\LiquidMemoWidget-Portable-v<version>.zip`
- `dist\installer\LiquidMemoWidget-Setup-v<version>.exe`

Useful options:

```powershell
.\Package.ps1 -Version <version> -SkipBuild
.\Package.ps1 -Version <version> -SkipInstaller
.\Package.ps1 -Version <version> -InnoSetupPath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

If `-Version` is omitted, the script falls back to `$env:RELEASE_VERSION`, then a `v*` tag on
the current commit, then `0.0.1`.

---

## 🏷️ Releases

Version tags such as `v0.0.2` trigger the GitHub Actions release workflow. The workflow builds
the PyInstaller app, creates a Windows installer with Inno Setup, packages a portable zip, and
publishes both files to GitHub Releases.

---

## 🗂️ State File

App state (settings, window position, todos, history, calendar cache) is stored at:

```text
%AppData%\Roaming\DesktopMemo_Pro\liquid-state.json
```

Writes are atomic (temp file + replace); a corrupt file is backed up as
`liquid-state.bad-<timestamp>.json` and a fresh state is returned.

---

## 🙏 Acknowledgements

The earlier real-time liquid glass skin adapted the D3D11 rendering core from
[ai12989757/WindowsLiquidGlass](https://github.com/ai12989757/WindowsLiquidGlass) (MIT licensed).
That skin and its engine have since been removed, and the third-party code is no longer
distributed with the project.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.
