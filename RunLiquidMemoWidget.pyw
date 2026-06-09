from pathlib import Path
import sys


sys.dont_write_bytecode = True
APP_DIR = Path(__file__).resolve().parent / "LiquidMemoWidget"
sys.path.insert(0, str(APP_DIR))

from app import LiquidMemoApp  # noqa: E402


if __name__ == "__main__":
    app = LiquidMemoApp()
    raise SystemExit(app.run())
