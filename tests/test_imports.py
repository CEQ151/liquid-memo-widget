"""Import/construction smoke gate for the UI split. Builds each window/dialog
headless (Qt offscreen) so a missing import or an import cycle introduced by the
module split fails CI. The core gate imports only the split UI modules — not app
or the D3D engine — so it stays green on machines without a GPU."""
import types

import pytest

from state_store import AppState


def _stub_app():
    """Minimal duck-typed app: dialogs only read `state` at construction time."""
    return types.SimpleNamespace(state=AppState(), calendar=None, updater=None, tray=None)


def test_split_ui_modules_build_without_engine(qapp):
    import ui_common  # noqa: F401
    import calendar_manager
    import settings_ui
    import update_ui
    import updater

    app = _stub_app()

    sw = settings_ui.SettingsWindow(app)
    assert sw.nav.count() == 4  # 外观 / 行为 / 日历订阅 / 关于

    release = updater.ReleaseInfo(
        tag="v9.9.9", version="9.9.9", notes="n", html_url="u",
        installer_url="", installer_name="", installer_size=0,
    )
    update_ui.UpdateDialog(app, release)
    update_ui.ChangelogDialog("notes")
    calendar_manager.CalendarManager(app)


def test_app_windows_build(qapp):
    try:
        import app as app_mod  # pulls in the D3D engine wrapper
    except Exception as exc:  # no engine/DLL on this host — skip, don't fail the gate
        pytest.skip(f"app/engine not importable here: {exc}")
    app = _stub_app()
    app_mod.HistoryWindow(app)
    add = app_mod.AddTodoPopup(None)
    edit = app_mod.EditDDLPopup(None)
    assert add.height() == 88 and edit.height() == 88
