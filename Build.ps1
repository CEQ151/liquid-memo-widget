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
  --add-data "$root\LiquidMemoWidget;LiquidMemoWidget" `
  --add-data "$root\WindowsLiquidGlass;WindowsLiquidGlass" `
  (Join-Path $root "RunLiquidMemoWidget.pyw")
