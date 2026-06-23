"""Pure-logic tests for the updater: version comparison, installer/helper command
assembly, release-asset selection, checksum verification, portable detection, and the
apply_update flow (subprocess mocked). No Qt, no network, no real process spawning."""
from pathlib import Path
import subprocess
import sys

import pytest

import updater


@pytest.fixture(autouse=True)
def isolate_update_log(tmp_path, monkeypatch):
    """Never mix mocked updater failures into the real app's %TEMP% diagnostic log."""
    monkeypatch.setattr(updater, "_update_log_path", lambda: tmp_path / "update.log")


class _FakeResponse:
    """Minimal urlopen() stand-in: a context manager exposing read()."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def read(self, *_args) -> bytes:
        return self._data


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


def test_install_and_restart_spawns_detached_helper(tmp_path, monkeypatch):
    installer = tmp_path / "Setup.exe"
    installer.write_text("stub")
    calls = {}
    monkeypatch.setattr(updater.sys, "executable", "C:/App/App.exe")
    monkeypatch.setattr(updater.os, "getpid", lambda: 4321)

    def fake_popen(cmd, **kwargs):
        calls.update(cmd=cmd, kwargs=kwargs)
        return type("P", (), {"pid": 9876})()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)

    updater.install_and_restart(installer)

    assert calls["cmd"] == [
        "C:/App/App.exe", updater.UPDATE_HELPER_FLAG, str(installer), "4321", "C:/App/App.exe"
    ]
    assert calls["kwargs"]["creationflags"] & updater.DETACHED_PROCESS


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
    assert rel.checksum_url == ""  # no sidecar in this release


def test_release_from_payload_captures_checksum_sidecar():
    payload = {
        "tag_name": "v2.3.4",
        "assets": [
            {"name": "LiquidMemoWidget-Setup-v2.3.4.exe", "browser_download_url": "s", "size": 5},
            {"name": "LiquidMemoWidget-Setup-v2.3.4.exe.sha256", "browser_download_url": "c", "size": 1},
        ],
    }
    rel = updater._release_from_payload(payload)
    assert rel.installer_url == "s"
    assert rel.checksum_url == "c"


def test_parse_expected_sha256_accepts_sha256sum_and_bare_forms():
    digest = "a" * 64
    assert updater._parse_expected_sha256(f"{digest}  LiquidMemoWidget-Setup.exe") == digest
    assert updater._parse_expected_sha256(digest.upper()) == digest  # normalized to lowercase
    assert updater._parse_expected_sha256("not-a-hash") == ""
    assert updater._parse_expected_sha256("") == ""


def test_sha256_file_matches_hashlib(tmp_path):
    import hashlib

    blob = b"liquid-memo-widget" * 4096
    f = tmp_path / "blob.bin"
    f.write_bytes(blob)
    assert updater.sha256_file(f) == hashlib.sha256(blob).hexdigest()


def test_verify_installer_checksum_pass_fail_and_skip(tmp_path, monkeypatch):
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"installer-bytes")
    digest = updater.sha256_file(installer)
    rel = updater.ReleaseInfo(
        tag="v1", version="1", notes="", html_url="",
        installer_url="u", installer_name="Setup.exe", installer_size=0,
        checksum_url="https://example/Setup.exe.sha256",
    )

    # Matching hash: passes silently.
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, **k: _FakeResponse(f"{digest}  Setup.exe".encode()))
    updater.verify_installer_checksum(installer, rel)

    # Wrong hash: must raise.
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, **k: _FakeResponse(f"{'0' * 64}  Setup.exe".encode()))
    with pytest.raises(RuntimeError):
        updater.verify_installer_checksum(installer, rel)

    # No sidecar published: skipped (no raise, no network).
    rel.checksum_url = ""
    updater.verify_installer_checksum(installer, rel)

    # Sidecar URL present but unfetchable (e.g. atom-reconstructed URL for a pre-sidecar
    # release that 404s): skip rather than fail-closed, so the update isn't blocked.
    rel.checksum_url = "https://example/missing.sha256"

    def boom(*_a, **_k):
        raise OSError("404")

    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    updater.verify_installer_checksum(installer, rel)  # no raise


def test_is_portable_build_detects_marker(tmp_path, monkeypatch):
    exe = tmp_path / "LiquidMemoWidget.exe"
    exe.write_text("stub")
    monkeypatch.setattr(updater.sys, "executable", str(exe))
    assert updater.is_portable_build() is False
    (tmp_path / updater.PORTABLE_MARKER).write_text("portable")
    assert updater.is_portable_build() is True


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


def test_apply_update_forces_verified_stuck_app_then_installs(tmp_path, monkeypatch):
    installer = tmp_path / "Setup.exe"
    installer.write_text("stub")
    calls = {}
    monkeypatch.setattr(updater, "_wait_for_pid_exit", lambda pid, timeout: False)
    monkeypatch.setattr(
        updater, "_terminate_pid",
        lambda pid, exe: calls.__setitem__("terminate", (pid, exe)) or True,
    )
    monkeypatch.setattr(updater.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        updater.subprocess, "run",
        lambda cmd, **kwargs: calls.__setitem__("run", cmd) or type("R", (), {"returncode": 0})(),
    )
    monkeypatch.setattr(
        updater.subprocess, "Popen",
        lambda cmd, **kwargs: calls.__setitem__("popen", cmd) or type("P", (), {"pid": 99})(),
    )

    updater.apply_update(str(installer), 4321, "C:/App/App.exe")

    assert calls["terminate"] == (4321, "C:/App/App.exe")
    assert calls["run"][0] == str(installer)
    assert calls["popen"] == ["C:/App/App.exe"]
    assert not installer.exists()


def test_apply_update_aborts_when_verified_termination_fails(tmp_path, monkeypatch):
    installer = tmp_path / "Setup.exe"
    installer.write_text("stub")
    calls = {}
    monkeypatch.setattr(updater, "_wait_for_pid_exit", lambda pid, timeout: False)
    monkeypatch.setattr(updater, "_terminate_pid", lambda pid, exe: False)
    monkeypatch.setattr(updater.subprocess, "run", lambda cmd, **kwargs: calls.__setitem__("run", cmd))
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kwargs: calls.__setitem__("popen", cmd))

    updater.apply_update(str(installer), 4321, "C:/App/App.exe")

    assert "run" not in calls
    assert "popen" not in calls
    assert installer.exists()


def test_terminate_pid_refuses_image_mismatch():
    # The image-path check and the kill share one handle now, so exercise it with a real process:
    # its image is the python exe, so an expected path that doesn't match must refuse to terminate.
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=updater.CREATE_NO_WINDOW,
    )
    try:
        assert updater._terminate_pid(process.pid, "C:/App/Definitely-Not-Me.exe") is False
        assert process.poll() is None  # untouched — the mismatch refused the kill
    finally:
        process.kill()


def test_terminate_pid_stops_verified_stuck_process():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=updater.CREATE_NO_WINDOW,
    )
    try:
        assert updater._wait_for_pid_exit(process.pid, 0.05) is False
        assert updater._terminate_pid(process.pid, sys.executable) is True
        assert process.wait(timeout=3) == 0
    finally:
        if process.poll() is None:
            process.kill()
