<div align="center">

# 🪟 Liquid Memo Widget

**A "Liquid Glass" desktop memo & todo widget for Windows 11**

A real-time GPU screen-capture widget: it continuously captures the desktop behind itself and
refracts it through D3D11 effects, floating todos, deadlines, and calendar events on a
translucent glass surface.

[中文](README.md) · English

![Platform](https://img.shields.io/badge/platform-Windows%2011-0078D6?logo=windows11&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Render](https://img.shields.io/badge/render-D3D11%20%2B%20Qt-5C2D91)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

---

## ✨ Features

### 🎨 Visuals
- **Real-time liquid glass** powered by the local `WindowsLiquidGlass` D3D11 engine — it
  continuously captures the desktop region behind the window and refracts it with flow,
  chromatic aberration, and highlight effects.
- **Adaptive text contrast** automatically samples background luminance and complexity to pick
  dark/light text; over extremely busy backgrounds (terminals, text-heavy pages) it switches to
  high-visibility neon colors, and `autoEnhanced` mode adds a soft halo behind text.
- **Tunable glass** — adjust window tint, glass opacity, and liquid strength in settings.

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
- **Click-through** — clicks over the glass pass through to the desktop; only checkboxes and
  buttons capture input, so the widget never gets in your way.
- **Native drag** — move the window via the `⋮⋮` handle; `-` minimizes and double-clicking the
  corner icon restores it.
- **Global wheel scroll** — scroll through content when it overflows.
- **System tray** — tray menu for Settings, History, Show/Hide, and Exit.
- **Launch at login** — toggle start-with-Windows in settings.

> ⚠️ Windows-only (Win32 + D3D11); will not run or build on other platforms. UI strings are
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

This project integrates and adapts the liquid glass rendering core from
[ai12989757/WindowsLiquidGlass](https://github.com/ai12989757/WindowsLiquidGlass).

`WindowsLiquidGlass` provides the D3D screen-capture, rounded-rectangle SDF, GPU effect renderer,
and Qt widget foundation used for the translucent Liquid Glass memo surface. The original upstream
README identifies `WindowsLiquidGlass` as MIT licensed; third-party code and binaries retain their
original ownership and license terms.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.
