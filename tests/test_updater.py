"""Pure-logic tests for the updater: version comparison, installer/helper command
assembly, release-asset selection, and the apply_update flow (subprocess mocked).
No Qt, no network, no real process spawning."""
from pathlib import Path

import updater


def test_parse_version_and_is_newer():
    assert updater.parse_version("v1.0.0") == (1, 0, 0)
    assert updater.parse_version("0.0.3-pro") == (0, 0, 3)
    assert updater.parse_version("") == (0,)
    assert updater.is_newer("1.0.10", "1.0.9") is True
    assert updater.is_newer("1.0.0", "1.0.0") is False
    assert updater.is_newer("0.9.9", "1.0.0") is False


def test_installer_args_uses_verysilent_and_log():
    args = updater._installer_args(Path("C:/Temp/up.log"))
    assert "/VERYSILENT" in args
    assert "/SILENT" not in args  # superseded by /VERYSILENT
    assert any(a.startswith("/LOG=") and a.endswith("up.log") for a in args)
    assert "/NORESTARTAPPLICATIONS" in args


def test_helper_command_shape():
    cmd = updater._helper_command("C:/Temp/Setup.exe", 1234, "C:/App/App.exe")
    assert cmd[1:] == ["--apply-update", "C:/Temp/Setup.exe", "1234", "C:/App/App.exe"]
    assert cmd[1] == updater.UPDATE_HELPER_FLAG


def test_release_from_payload_picks_setup_exe():
    payload = {
        "tag_name": "v2.3.4",
        "body": "notes",
        "html_url": "https://example/release",
        "assets": [
            {"name": "LiquidMemoWidget-Portable-v2.3.4.zip", "browser_download_url": "z", "size": 1},
            {"name": "LiquidMemoWidget-Setup-v2.3.4.exe", "browser_download_url": "s", "size": 99},
        ],
    }
    rel = updater._release_from_payload(payload)
    assert rel.version == "2.3.4"
    assert rel.installer_name.endswith("Setup-v2.3.4.exe")
    assert rel.installer_url == "s"
    assert rel.installer_size == 99


def test_apply_update_waits_installs_cleans_and_relaunches(tmp_path, monkeypatch):
    installer = tmp_path / "Setup.exe"
    installer.write_text("stub")
    calls = {}

    def fake_wait(pid, timeout):
        calls["wait"] = (pid, timeout)
        return True  # app exited cleanly

    monkeypatch.setattr(updater, "_wait_for_pid_exit", fake_wait)
    monkeypatch.setattr(updater.time, "sleep", lambda _s: None)

    def fake_run(cmd, **kwargs):
        calls["run"] = cmd
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kwargs: calls.__setitem__("popen", cmd))

    updater.apply_update(str(installer), 4321, "C:/App/App.exe")

    assert calls["wait"][0] == 4321
    assert calls["run"][0] == str(installer)
    assert "/VERYSILENT" in calls["run"]
    assert not installer.exists()  # temp installer cleaned up
    assert calls["popen"] == ["C:/App/App.exe"]  # app relaunched


def test_apply_update_relaunches_even_when_install_fails(tmp_path, monkeypatch):
    installer = tmp_path / "Setup.exe"
    installer.write_text("stub")
    calls = {}
    monkeypatch.setattr(updater, "_wait_for_pid_exit", lambda pid, timeout: True)
    monkeypatch.setattr(updater.time, "sleep", lambda _s: None)

    def boom(cmd, **kwargs):
        raise OSError("install blew up")

    monkeypatch.setattr(updater.subprocess, "run", boom)
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kwargs: calls.__setitem__("popen", cmd))

    updater.apply_update(str(installer), 1, "C:/App/App.exe")

    assert calls["popen"] == ["C:/App/App.exe"]  # finally-block relaunch still ran


def test_apply_update_aborts_when_app_does_not_exit(tmp_path, monkeypatch):
    # If the app never exits within the wait timeout, the helper must NOT install
    # (it would clobber a live, file-locked process) nor relaunch (it would spawn
    # a second instance). It leaves the installer in place and bails.
    installer = tmp_path / "Setup.exe"
    installer.write_text("stub")
    calls = {}
    monkeypatch.setattr(updater, "_wait_for_pid_exit", lambda pid, timeout: False)
    monkeypatch.setattr(updater.time, "sleep", lambda _s: None)
    monkeypatch.setattr(updater.subprocess, "run", lambda cmd, **kwargs: calls.__setitem__("run", cmd))
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kwargs: calls.__setitem__("popen", cmd))

    updater.apply_update(str(installer), 4321, "C:/App/App.exe")

    assert "run" not in calls    # never installed over the live app
    assert "popen" not in calls  # never spawned a duplicate instance
    assert installer.exists()    # installer left untouched
