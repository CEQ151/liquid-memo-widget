"""GitHub-release based auto update: check, download, silent install, restart.

Pure network/process logic with no Qt dependency; the UI lives in app.py
(UpdateManager / UpdateDialog) and calls into this module from worker threads.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from version import APP_VERSION, GITHUB_OWNER, GITHUB_REPO, GITHUB_URL

API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
_TIMEOUT = 15
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
UPDATE_HELPER_FLAG = "--apply-update"


@dataclass
class ReleaseInfo:
    tag: str                 # e.g. "v1.0.0"
    version: str             # e.g. "1.0.0"
    notes: str               # release body (markdown, or HTML from the atom feed)
    html_url: str
    installer_url: str       # "" when the release has no Setup asset
    installer_name: str
    installer_size: int
    notes_html: bool = False  # True when notes came from the atom feed (HTML)


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.0.0' / '0.0.3-pro' -> (1, 0, 0) / (0, 0, 3). Unparseable parts are 0."""
    parts = []
    for chunk in str(text or "").strip().lstrip("vV").split("."):
        match = re.match(r"\d+", chunk)
        parts.append(int(match.group()) if match else 0)
    return tuple(parts or [0])


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def _get_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{GITHUB_REPO}-updater",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _release_from_payload(data: dict) -> ReleaseInfo:
    tag = str(data.get("tag_name") or "")
    installer_url = installer_name = ""
    installer_size = 0
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if "-Setup-" in name and name.lower().endswith(".exe"):
            installer_url = str(asset.get("browser_download_url") or "")
            installer_name = name
            installer_size = int(asset.get("size") or 0)
            break
    return ReleaseInfo(
        tag=tag,
        version=tag.lstrip("vV"),
        notes=str(data.get("body") or ""),
        html_url=str(data.get("html_url") or f"{GITHUB_URL}/releases"),
        installer_url=installer_url,
        installer_name=installer_name,
        installer_size=installer_size,
    )


def _fetch_atom_releases() -> list[ReleaseInfo]:
    """Fallback source: the public releases.atom feed on github.com.

    Unlike api.github.com (60 anonymous requests/hour per IP, easily exhausted
    behind shared NAT), the atom feed is not rate limited. It carries the tag,
    release page link and HTML notes; the installer URL is reconstructed from
    the packaging scripts' fixed asset naming, and the download itself goes to
    objects.githubusercontent.com which is also not rate limited.
    """
    request = urllib.request.Request(
        f"{GITHUB_URL}/releases.atom",
        headers={"User-Agent": f"{GITHUB_REPO}-updater"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        root = ET.fromstring(response.read())
    ns = {"a": "http://www.w3.org/2005/Atom"}
    releases: list[ReleaseInfo] = []
    for entry in root.findall("a:entry", ns):
        tag = (entry.findtext("a:id", "", ns) or "").rsplit("/", 1)[-1]
        if not tag:
            continue
        link = entry.find("a:link", ns)
        installer_name = f"LiquidMemoWidget-Setup-{tag}.exe"
        releases.append(ReleaseInfo(
            tag=tag,
            version=tag.lstrip("vV"),
            notes=entry.findtext("a:content", "", ns) or "",
            html_url=(link.get("href") if link is not None else None) or f"{GITHUB_URL}/releases",
            installer_url=f"{GITHUB_URL}/releases/download/{tag}/{installer_name}",
            installer_name=installer_name,
            installer_size=0,
            notes_html=True,
        ))
    if not releases:
        raise RuntimeError("无法从发布源获取版本信息")
    return releases


def fetch_latest_release() -> ReleaseInfo:
    try:
        return _release_from_payload(_get_json(f"{API_BASE}/releases/latest"))
    except Exception as api_error:
        try:
            # Atom entries are ordered newest-first.
            return _fetch_atom_releases()[0]
        except Exception:
            raise api_error


def fetch_release_by_tag(tag: str) -> ReleaseInfo:
    try:
        return _release_from_payload(_get_json(f"{API_BASE}/releases/tags/{tag}"))
    except Exception as api_error:
        try:
            for release in _fetch_atom_releases():
                if release.tag == tag:
                    return release
        except Exception:
            pass
        raise api_error


def download_installer(release: ReleaseInfo,
                       progress: Callable[[int, int], None] | None = None) -> Path:
    """Download the Setup asset to %TEMP%; returns the local path."""
    if not release.installer_url:
        raise RuntimeError("该版本没有提供安装包")
    dest = Path(tempfile.gettempdir()) / release.installer_name
    request = urllib.request.Request(
        release.installer_url, headers={"User-Agent": f"{GITHUB_REPO}-updater"}
    )
    received = 0
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        total = int(response.headers.get("Content-Length") or release.installer_size or 0)
        with dest.open("wb") as stream:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
                received += len(chunk)
                if progress:
                    progress(received, total)
    if total and received < total:
        raise RuntimeError("下载不完整，请重试")
    return dest


def _update_log_path() -> Path:
    return Path(tempfile.gettempdir()) / "LiquidMemoWidget-update.log"


def _installer_args(log_path: Path) -> list[str]:
    """Inno Setup silent-install flags. /VERYSILENT hides the progress window;
    /FORCECLOSEAPPLICATIONS + /SUPPRESSMSGBOXES keep it from erroring on held
    files; /NORESTARTAPPLICATIONS stops Inno's restart manager from relaunching
    the app (the helper owns the relaunch); /LOG leaves a postmortem trail."""
    return [
        "/VERYSILENT",
        "/NORESTART",
        "/SUPPRESSMSGBOXES",
        "/FORCECLOSEAPPLICATIONS",
        "/NORESTARTAPPLICATIONS",
        f"/LOG={log_path}",
    ]


def _helper_command(installer: Path | str, parent_pid: int, target_exe: str) -> list[str]:
    """Re-invoke this same (frozen) executable in update-helper mode."""
    return [sys.executable, UPDATE_HELPER_FLAG, str(installer), str(parent_pid), str(target_exe)]


def _wait_for_pid_exit(pid: int, timeout: float) -> None:
    """Block until `pid` terminates (or timeout elapses). Pure ctypes so the
    detached helper needs no third-party deps; a process we cannot open is
    treated as already gone. HANDLE restype is set explicitly to avoid 64-bit
    handle truncation."""
    SYNCHRONIZE = 0x00100000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return
    try:
        kernel32.WaitForSingleObject(handle, int(timeout * 1000))
    finally:
        kernel32.CloseHandle(handle)


def install_and_restart(installer: Path) -> None:
    """Spawn the detached update helper (this exe in --apply-update mode) and
    return. The helper survives our exit (a DETACHED_PROCESS child is not killed
    with the parent); the caller MUST quit immediately after so the helper's
    PID-wait can proceed and the installer never starts while we still hold file
    locks."""
    subprocess.Popen(
        _helper_command(installer, os.getpid(), sys.executable),
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        close_fds=True,
    )


def apply_update(installer: str, parent_pid: int, target_exe: str) -> None:
    """Update-helper entry, run in a separate detached process (no Qt): wait for
    the app to exit, run the Inno installer silently, delete the temp installer,
    then relaunch the app. Pure Python — no PowerShell — so it is testable and
    free of shell-quoting hazards. The Inno loader self-elevates internally, so a
    plain CreateProcess still triggers UAC, mirroring the old Start-Process path.
    The relaunch lives in `finally` so the app comes back even if the install
    fails or the UAC prompt is declined."""
    installer_path = Path(installer)
    _wait_for_pid_exit(parent_pid, 30)
    time.sleep(0.5)  # let the OS release file locks the app held
    try:
        subprocess.run(
            [str(installer_path), *_installer_args(_update_log_path())],
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except Exception:
        pass
    finally:
        try:
            installer_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            subprocess.Popen([target_exe], creationflags=DETACHED_PROCESS, close_fds=True)
        except Exception:
            pass


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
