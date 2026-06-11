"""GitHub-release based auto update: check, download, silent install, restart.

Pure network/process logic with no Qt dependency; the UI lives in app.py
(UpdateManager / UpdateDialog) and calls into this module from worker threads.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from version import APP_VERSION, GITHUB_OWNER, GITHUB_REPO, GITHUB_URL

API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
_TIMEOUT = 15
CREATE_NO_WINDOW = 0x08000000


@dataclass
class ReleaseInfo:
    tag: str                 # e.g. "v1.0.0"
    version: str             # e.g. "1.0.0"
    notes: str               # release body (markdown)
    html_url: str
    installer_url: str       # "" when the release has no Setup asset
    installer_name: str
    installer_size: int


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


def fetch_latest_release() -> ReleaseInfo:
    return _release_from_payload(_get_json(f"{API_BASE}/releases/latest"))


def fetch_release_by_tag(tag: str) -> ReleaseInfo:
    return _release_from_payload(_get_json(f"{API_BASE}/releases/tags/{tag}"))


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


def install_and_restart(installer: Path) -> None:
    """Run the Inno installer silently after this process exits, then relaunch.

    The helper PowerShell child survives our exit (Windows children are not
    killed with the parent); the 2s sleep lets the app fully quit so the
    installer can replace files. The caller must quit immediately after.
    """
    exe = sys.executable
    quoted_installer = str(installer).replace("'", "''")
    quoted_exe = exe.replace("'", "''")
    script = (
        "Start-Sleep -Seconds 2; "
        f"Start-Process -FilePath '{quoted_installer}' "
        "-ArgumentList '/SILENT','/NORESTART' -Wait; "
        f"Start-Process -FilePath '{quoted_exe}'"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-Command", script],
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
