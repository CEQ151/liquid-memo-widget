$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

python -m pip install -r (Join-Path $root "LiquidMemoWidget\requirements.txt")
python -m pip install pyinstaller

python -m PyInstaller `
  --noconfirm `
  --clean `
  --noconsole `
  --name LiquidMemoWidget `
  --collect-all qfluentwidgets `
  --collect-all icalendar `
  --collect-all recurring_ical_events `
  --collect-submodules dateutil `
  --collect-data tzdata `
  --hidden-import numpy `
  --hidden-import xml.etree.ElementTree `
  --icon "$root\assets\logo.ico" `
  --add-data "$root\assets\logo.ico;assets" `
  --add-data "$root\LiquidMemoWidget;LiquidMemoWidget" `
  --add-data "$root\WindowsLiquidGlass;WindowsLiquidGlass" `
  (Join-Path $root "RunLiquidMemoWidget.pyw")
