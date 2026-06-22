"""GitHub-release based auto update: check, download, silent install, restart.

Pure network/process logic with no Qt dependency; the UI lives in app.py
(UpdateManager / UpdateDialog) and calls into this module from worker threads.
"""

from __future__ import annotations

import ctypes
import hashlib
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
    # SHA256 sidecar for the installer (asset named "<installer>.sha256"). "" for older
    # releases that predate checksum publishing — verification is then skipped (see
    # download_installer). The atom fallback reconstructs the URL from the fixed naming.
    checksum_url: str = ""


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
    assets = {str(a.get("name") or ""): str(a.get("browser_download_url") or "")
              for a in data.get("assets") or []}
    sizes = {str(a.get("name") or ""): int(a.get("size") or 0) for a in data.get("assets") or []}
    installer_url = installer_name = ""
    installer_size = 0
    for name, url in assets.items():
        if "-Setup-" in name and name.lower().endswith(".exe"):
            installer_url, installer_name, installer_size = url, name, sizes.get(name, 0)
            break
    # The checksum sidecar is published as "<installer>.sha256" (absent on older releases).
    checksum_url = assets.get(f"{installer_name}.sha256", "") if installer_name else ""
    return ReleaseInfo(
        tag=tag,
        version=tag.lstrip("vV"),
        notes=str(data.get("body") or ""),
        html_url=str(data.get("html_url") or f"{GITHUB_URL}/releases"),
        installer_url=installer_url,
        installer_name=installer_name,
        installer_size=installer_size,
        checksum_url=checksum_url,
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
        download_base = f"{GITHUB_URL}/releases/download/{tag}"
        releases.append(ReleaseInfo(
            tag=tag,
            version=tag.lstrip("vV"),
            notes=entry.findtext("a:content", "", ns) or "",
            html_url=(link.get("href") if link is not None else None) or f"{GITHUB_URL}/releases",
            installer_url=f"{download_base}/{installer_name}",
            installer_name=installer_name,
            installer_size=0,
            notes_html=True,
            checksum_url=f"{download_base}/{installer_name}.sha256",
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


def sha256_file(path: Path) -> str:
    """Streaming SHA256 of a file as a lowercase hex digest."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_expected_sha256(text: str) -> str:
    """Pull the hex digest out of a `.sha256` sidecar. Accepts the `sha256sum` layout
    (`<hash>  <filename>`) or a bare hash; returns it lowercased, or "" if unparseable."""
    for line in (text or "").splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        if re.fullmatch(r"[0-9a-fA-F]{64}", token):
            return token.lower()
    return ""


def verify_installer_checksum(path: Path, release: ReleaseInfo) -> None:
    """Verify the downloaded installer against the release's `.sha256` sidecar.

    A *fetched* hash that does not match aborts the update (corruption / tampering). But when
    the sidecar can't be obtained — no `checksum_url`, or the fetch fails (older releases have
    no sidecar; the atom fallback only reconstructs the URL by convention) — verification is
    skipped: we have no trusted hash to compare against, and failing closed there would break
    updates to/from those versions. (Strong provenance is the job of code signing, not this.)"""
    if not release.checksum_url:
        _log(f"no checksum sidecar for {release.installer_name}; skipping verification")
        return
    try:
        request = urllib.request.Request(
            release.checksum_url, headers={"User-Agent": f"{GITHUB_REPO}-updater"}
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            expected = _parse_expected_sha256(response.read().decode("utf-8", "replace"))
    except Exception as exc:
        _log(f"checksum fetch failed for {release.installer_name}: {exc!r}; skipping verification")
        return
    if not expected:
        raise RuntimeError("无法解析安装包校验文件")
    if sha256_file(path) != expected:
        raise RuntimeError("安装包校验失败（SHA256 不匹配），已中止更新")


def download_installer(release: ReleaseInfo,
                       progress: Callable[[int, int], None] | None = None) -> Path:
    """Download the Setup asset to %TEMP%, verify its SHA256, and return the local path."""
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
    try:
        verify_installer_checksum(dest, release)
    except Exception:
        # Never leave an unverified / corrupt installer behind for a later run to pick up.
        dest.unlink(missing_ok=True)
        raise
    return dest


def _update_log_path() -> Path:
    return Path(tempfile.gettempdir()) / "LiquidMemoWidget-update.log"


def _log(message: str) -> None:
    """Append a timestamped line to the update log (best-effort, never raises). The log is
    the only postmortem trail for failed silent updates — UAC declines, installer errors,
    checksum mismatches — so don't swallow these without recording them."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with _update_log_path().open("a", encoding="utf-8") as stream:
            stream.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


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


def _wait_for_pid_exit(pid: int, timeout: float) -> bool:
    """Block until `pid` terminates (or timeout elapses). Returns True only when
    the process is confirmed gone — it exited, or it could not be opened so it is
    already gone — and False on timeout, so the caller can refuse to install over
    a still-running app. Pure ctypes so the detached helper needs no third-party
    deps. HANDLE restype is set explicitly to avoid 64-bit handle truncation."""
    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0x00000000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return True  # cannot open the process → treat it as already exited
    try:
        return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) == WAIT_OBJECT_0
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
    then relaunch the app. If the app does not exit within the timeout we abort
    without installing or relaunching, so we never clobber a live, file-locked
    process or spawn a duplicate instance (the persisted pendingUpdateVersion
    surfaces the failed update on the next clean launch). Pure Python — no
    PowerShell — so it is testable and free of shell-quoting hazards. The Inno
    loader self-elevates internally, so a plain CreateProcess still triggers UAC,
    mirroring the old Start-Process path. The relaunch lives in `finally` so the
    app still comes back even if the install fails or the UAC prompt is declined."""
    installer_path = Path(installer)
    if not _wait_for_pid_exit(parent_pid, 30):
        _log(f"app pid {parent_pid} did not exit in time; aborting install of {installer_path.name}")
        return  # app never exited; do not install over a live process or double-launch
    time.sleep(0.5)  # let the OS release file locks the app held
    try:
        subprocess.run(
            [str(installer_path), *_installer_args(_update_log_path())],
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except Exception as exc:
        _log(f"installer launch failed for {installer_path.name}: {exc!r}")
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


# Marker file dropped beside the exe only in the portable zip (see Package.ps1 / release.yml).
# The installer build never contains it, so its presence reliably distinguishes a portable
# build from an installed one.
PORTABLE_MARKER = "portable.flag"


def is_portable_build() -> bool:
    """True for the portable (no-install) build. Portable copies live in arbitrary, possibly
    read-only locations (Desktop, USB, an unzipped folder), so they must not silently run the
    Inno installer over themselves — the UI offers a manual download/release-page path instead."""
    try:
        return (Path(sys.executable).parent / PORTABLE_MARKER).exists()
    except Exception:
        return False
