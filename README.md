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
