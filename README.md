# Liquid Memo Widget

A Windows 11 desktop memo and todo widget with Liquid Glass visuals, Fluent UI settings, tray controls, and adaptive text contrast.

## Features

- Liquid Glass desktop widget powered by the local `WindowsLiquidGlass` D3D effect engine.
- Todo-focused memo surface with completion archive and urgent pinning.
- Windows 11 Fluent-style settings and history panels.
- System tray menu for settings, history, show/hide, and exit.
- Adaptive text contrast for readability over transparent backgrounds.

## Run From Source

```powershell
python -m pip install -r .\LiquidMemoWidget\requirements.txt
pythonw .\RunLiquidMemoWidget.pyw
```

## Build

```powershell
.\Build.ps1
```

The build output is generated under `dist\LiquidMemoWidget`.

## Package Locally

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then run:

```powershell
.\Package.ps1 -Version 0.0.1
```

This creates:

- `dist\LiquidMemoWidget-Portable-v0.0.1.zip`
- `dist\installer\LiquidMemoWidget-Setup-v0.0.1.exe`

Useful options:

```powershell
.\Package.ps1 -Version 0.0.1 -SkipBuild
.\Package.ps1 -Version 0.0.1 -SkipInstaller
.\Package.ps1 -Version 0.0.1 -InnoSetupPath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

## Releases

Version tags such as `v0.0.1` trigger the GitHub Actions release workflow. The workflow builds
the PyInstaller app, creates a Windows installer with Inno Setup, packages a portable zip, and
publishes both files to GitHub Releases.

## Acknowledgements

This project integrates and adapts the liquid glass rendering core from
[ai12989757/WindowsLiquidGlass](https://github.com/ai12989757/WindowsLiquidGlass).

`WindowsLiquidGlass` provides the D3D screen-capture, rounded-rectangle SDF, GPU effect renderer,
and Qt widget foundation used for the translucent Liquid Glass memo surface. The original upstream
README identifies `WindowsLiquidGlass` as MIT licensed; third-party code and binaries retain their
original ownership and license terms.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.
