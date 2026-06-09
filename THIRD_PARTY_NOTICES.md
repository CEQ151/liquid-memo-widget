# Third-Party Notices

This project includes and adapts third-party components. Their original authorship and license
terms remain in effect.

## WindowsLiquidGlass

- Upstream repository: <https://github.com/ai12989757/WindowsLiquidGlass>
- Author / owner: `ai12989757` and contributors
- Upstream description: Windows desktop Liquid Glass Qt component
- License: MIT License, as stated by the upstream README

The local `WindowsLiquidGlass/` directory contains the runtime subset used by this project,
including D3D capture, GPU device management, rounded-rectangle SDF generation, GPU effect
rendering, compiled shader objects, and native DLLs.

This project uses `WindowsLiquidGlass` to render the Liquid Glass background behind the memo/todo
widget. The memo application, tray behavior, Fluent settings interface, todo logic, adaptive text
contrast, and packaging scripts are project-specific additions around that rendering core.

## Python Dependencies

Runtime Python dependencies are listed in `LiquidMemoWidget/requirements.txt`. Their licenses are
defined by their respective upstream projects, including but not limited to:

- PySide6
- NumPy
- PySide6-Fluent-Widgets

## Notes

No ownership over third-party code is claimed by this repository. If additional upstream notices
or license files become available, they should be preserved here.
