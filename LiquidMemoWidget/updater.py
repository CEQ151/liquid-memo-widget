"""GitHub-release based auto update: check, download, silent install, restart.

Pure network/process logic with no Qt dependency; the UI lives in app.py
(UpdateManager / UpdateDialog) and calls into this module from worker threads.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
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


def install_and_restart(installer: Path) -> None:
    """Run the Inno installer silently after this process exits, then relaunch.

    The helper PowerShell child survives our exit (Windows children are not
    killed with the parent). Robustness against the previously shipped races:
    - waits for this exact PID to terminate (no fixed sleep) so the installer
      never starts while the app is still shutting down and holding file locks;
    - /FORCECLOSEAPPLICATIONS + /SUPPRESSMSGBOXES stop Inno from popping error
      dialogs if something still holds a file, /NORESTARTAPPLICATIONS stops the
      restart manager from relaunching the app a second time (the helper owns
      the relaunch);
    - the relaunch lives in `finally`, so the app comes back even when the
      install fails or the UAC prompt is declined;
    - /LOG writes a diagnosis trail to %TEMP% for postmortems.

    The caller must quit immediately after.
    """
    exe = sys.executable
    quoted_installer = str(installer).replace("'", "''")
    quoted_exe = exe.replace("'", "''")
    log_path = Path(tempfile.gettempdir()) / "LiquidMemoWidget-update.log"
    quoted_log = str(log_path).replace("'", "''")
    script = (
        f"Wait-Process -Id {os.getpid()} -Timeout 30 -ErrorAction SilentlyContinue; "
        "Start-Sleep -Milliseconds 500; "
        "try { "
        f"Start-Process -FilePath '{quoted_installer}' -ArgumentList "
        "'/SILENT','/NORESTART','/SUPPRESSMSGBOXES','/FORCECLOSEAPPLICATIONS',"
        # Embedded quotes: PowerShell 5.1 joins ArgumentList without quoting, and
        # Inno aborts when the /LOG file path (which breaks on a space) is invalid.
        f"'/NORESTARTAPPLICATIONS','/LOG=\"{quoted_log}\"' -Wait "
        "} catch {} finally { "
        f"Start-Process -FilePath '{quoted_exe}' }}"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-Command", script],
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
