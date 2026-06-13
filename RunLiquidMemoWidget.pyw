from pathlib import Path
import sys


sys.dont_write_bytecode = True
APP_DIR = Path(__file__).resolve().parent / "LiquidMemoWidget"
sys.path.insert(0, str(APP_DIR))


def _run() -> int:
    # Update-helper mode: this same frozen exe is re-invoked as
    #   <exe> --apply-update <installer> <parent_pid> <target_exe>
    # by updater.install_and_restart. Do the wait/install/relaunch in pure Python
    # with no Qt/QApplication, then exit.
    if len(sys.argv) >= 5 and sys.argv[1] == "--apply-update":
        import updater
        _, _, installer, parent_pid, target_exe = sys.argv[:5]
        updater.apply_update(installer, int(parent_pid), target_exe)
        return 0
    from app import LiquidMemoApp
    return LiquidMemoApp().run()


if __name__ == "__main__":
    raise SystemExit(_run())
