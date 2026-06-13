"""In-app update UI and orchestration: release card dialogs, the post-update
changelog, and the manager that runs the startup/manual checks. Network/install
logic lives in updater.py; the app is reached through `self.app`."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SmoothScrollArea,
    TitleLabel,
)

import updater
from ui_common import FONT_STACK_QSS, add_soft_shadow
from version import APP_VERSION, GITHUB_URL

if TYPE_CHECKING:
    from app import LiquidMemoApp


class _ReleaseCardDialog(QDialog):
    """Frameless fluent card shared by the update prompt and the changelog dialog."""

    def __init__(self, width: int, height: int) -> None:
        super().__init__(None, Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(width, height)
        self.frame = QFrame(self)
        self.frame.setObjectName("fluentPanel")
        self.frame.setGeometry(0, 0, width, height)
        self.frame.setStyleSheet(
            f"""
            QFrame#fluentPanel {{
                {FONT_STACK_QSS}
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgb(252, 253, 255), stop:1 rgb(240, 244, 250));
                border: 1px solid rgba(255,255,255,210);
                border-radius: 22px;
            }}
            """
        )
        add_soft_shadow(self.frame, blur=34, y=12, alpha=80)
        self.body = QVBoxLayout(self.frame)
        self.body.setContentsMargins(28, 24, 28, 24)
        self.body.setSpacing(14)

    def add_header(self, title: str, subtitle: str) -> None:
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title_label = TitleLabel(title)
        subtitle_label = BodyLabel(subtitle)
        subtitle_label.setStyleSheet("color: rgba(17,24,32,150);")
        titles.addWidget(title_label)
        titles.addWidget(subtitle_label)
        self.body.addLayout(titles)

    def add_notes(self, text: str, html: bool = False) -> None:
        scroll = SmoothScrollArea(self.frame)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            """
            QScrollArea { background: rgba(255,255,255,140); border: 1px solid rgba(17,24,32,18); border-radius: 12px; }
            QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }
            QScrollBar::handle:vertical { background: rgba(17,24,32,60); border-radius: 3px; min-height: 32px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )
        notes = QLabel()
        # Release notes come as markdown from the GitHub API, or as HTML when
        # the rate-limited API fell back to the releases.atom feed.
        notes.setTextFormat(Qt.RichText if html else Qt.MarkdownText)
        notes.setText(text.strip() or ("暂无更新说明" if html else "_暂无更新说明_"))
        notes.setWordWrap(True)
        notes.setOpenExternalLinks(True)
        notes.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        notes.setStyleSheet(
            f"{FONT_STACK_QSS} color: rgb(24,32,40); font-size: 13px;"
            " background: transparent; padding: 14px;"
        )
        scroll.setWidget(notes)
        self.body.addWidget(scroll, 1)


class _DownloadSignals(QObject):
    progress = Signal(int, int)  # received bytes, total bytes
    finished = Signal(str)       # local installer path
    failed = Signal(str)


class _DownloadTask(QRunnable):
    def __init__(self, release: updater.ReleaseInfo, signals: _DownloadSignals) -> None:
        super().__init__()
        self.release = release
        self.signals = signals

    def run(self) -> None:
        try:
            path = updater.download_installer(
                self.release,
                progress=lambda done, total: self.signals.progress.emit(done, total),
            )
            self.signals.finished.emit(str(path))
        except Exception as exc:
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)


class UpdateDialog(_ReleaseCardDialog):
    def __init__(self, app: "LiquidMemoApp", release: updater.ReleaseInfo) -> None:
        super().__init__(520, 560)
        self.app = app
        self.release = release
        self._downloading = False
        self._signals: _DownloadSignals | None = None
        self.setWindowTitle("发现新版本")
        self.add_header(f"发现新版本 {release.tag}", f"当前版本 v{APP_VERSION}，更新内容：")
        self.add_notes(release.notes, release.notes_html)

        self.progress = ProgressBar(self.frame)
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.body.addWidget(self.progress)
        self.status = BodyLabel("")
        self.status.setStyleSheet("color: rgba(17,24,32,150); font-size: 12px;")
        self.status.hide()
        self.body.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.later = PushButton("稍后再说", self.frame)
        self.later.clicked.connect(self.close)
        buttons.addWidget(self.later)
        self.install = PrimaryPushButton("立即更新", self.frame, FluentIcon.UPDATE)
        self.install.clicked.connect(self._start)
        buttons.addWidget(self.install)
        self.body.addLayout(buttons)

    def _start(self) -> None:
        # Outside a packaged build (or with no installer asset) fall back to the
        # release page instead of attempting a silent install.
        if not updater.is_frozen() or not self.release.installer_url:
            QDesktopServices.openUrl(QUrl(self.release.html_url))
            return
        self._downloading = True
        self.install.setEnabled(False)
        self.later.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("正在下载更新…")
        self.status.show()
        signals = _DownloadSignals()
        signals.progress.connect(self._on_progress)
        signals.finished.connect(self._on_downloaded)
        signals.failed.connect(self._on_failed)
        self._signals = signals  # keep alive until the task completes
        QThreadPool.globalInstance().start(_DownloadTask(self.release, signals))

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setValue(int(done * 100 / total))
            self.status.setText(f"正在下载更新… {done / 1048576:.1f} / {total / 1048576:.1f} MB")
        else:
            self.status.setText(f"正在下载更新… {done / 1048576:.1f} MB")

    def _on_downloaded(self, path: str) -> None:
        self.progress.setValue(100)
        self.status.setText("下载完成，正在安装并自动重启…")
        # Record the target version so the next launch can detect a failed install
        # (the running version won't have advanced). Save now — we're about to quit.
        self.app.state.settings.pendingUpdateVersion = self.release.version
        self.app.save()
        updater.install_and_restart(Path(path))
        QTimer.singleShot(600, self.app.quit)

    def _on_failed(self, message: str) -> None:
        self._downloading = False
        self.install.setEnabled(True)
        self.later.setEnabled(True)
        self.status.setText(f"下载失败：{message}")

    def closeEvent(self, event) -> None:
        if self._downloading:
            event.ignore()
            return
        super().closeEvent(event)


class ChangelogDialog(_ReleaseCardDialog):
    def __init__(self, notes: str, html: bool = False) -> None:
        super().__init__(520, 520)
        self.setWindowTitle("更新日志")
        self.add_header("更新完成 🎉", f"桌面备忘已更新到 v{APP_VERSION}，本次更新内容：")
        self.add_notes(notes, html)
        buttons = QHBoxLayout()
        buttons.addStretch()
        ok = PrimaryPushButton("知道了", self.frame, FluentIcon.ACCEPT)
        ok.clicked.connect(self.close)
        buttons.addWidget(ok)
        self.body.addLayout(buttons)


class _UpdateCheckSignals(QObject):
    finished = Signal(object)  # updater.ReleaseInfo
    failed = Signal(str)


class _UpdateCheckTask(QRunnable):
    """GitHub API call on a pool thread so the UI and render loop never block."""

    def __init__(self, signals: _UpdateCheckSignals, tag: str | None = None) -> None:
        super().__init__()
        self.signals = signals
        self.tag = tag

    def run(self) -> None:
        try:
            release = updater.fetch_release_by_tag(self.tag) if self.tag else updater.fetch_latest_release()
            self.signals.finished.emit(release)
        except Exception as exc:
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)


class UpdateManager:
    """Owns update flows: post-update changelog, startup silent check, manual check."""

    def __init__(self, app: "LiquidMemoApp") -> None:
        self.app = app
        self._checking = False
        self._signal_refs: list[_UpdateCheckSignals] = []
        self._dialog: QDialog | None = None
        self._prompted_tag = ""

    def on_startup(self) -> None:
        settings = self.app.state.settings
        self._check_failed_update(settings)
        if settings.lastRunVersion != APP_VERSION:
            was_update = bool(settings.lastRunVersion)
            settings.lastRunVersion = APP_VERSION
            self.app.save_later()
            if was_update:
                # Show this version's release notes once after an update.
                self._fetch(
                    tag=f"v{APP_VERSION}",
                    on_done=lambda release: self._show_changelog(release.notes, release.notes_html),
                    on_fail=lambda _msg: self._show_changelog(
                        f"更新说明获取失败，可前往 [GitHub 发布页]({GITHUB_URL}/releases) 查看。"
                    ),
                )
        QTimer.singleShot(8000, lambda: self.check(silent=True))

    def _check_failed_update(self, settings) -> None:
        """If an install was attempted last run but the version did not advance, the
        update failed (UAC declined, installer error, …). Clear the flag and tell the
        user once. The success case falls through to the changelog flow above."""
        pending = settings.pendingUpdateVersion
        if not pending:
            return
        settings.pendingUpdateVersion = ""
        self.app.save_later()
        if updater.parse_version(APP_VERSION) >= updater.parse_version(pending):
            return
        self.app.settings_window.set_update_status(f"上次更新到 v{pending} 失败")
        try:
            self.app.tray.showMessage(
                "更新失败",
                f"未能更新到 v{pending}，可在设置里重试或前往 GitHub 手动下载。",
            )
        except Exception:
            pass

    def check(self, silent: bool = True) -> None:
        if self._checking:
            return
        self._checking = True
        self.app.settings_window.set_update_status("正在检查更新…")
        self._fetch(
            tag=None,
            on_done=lambda release: self._on_checked(release, silent),
            on_fail=lambda message: self._on_check_failed(message, silent),
        )

    def _fetch(self, tag: str | None, on_done, on_fail) -> None:
        signals = _UpdateCheckSignals()
        signals.finished.connect(on_done)
        signals.failed.connect(on_fail)
        self._signal_refs.append(signals)  # keep alive until the task completes
        QThreadPool.globalInstance().start(_UpdateCheckTask(signals, tag))

    def _on_checked(self, release: updater.ReleaseInfo, silent: bool) -> None:
        self._checking = False
        if updater.is_newer(release.version):
            self.app.settings_window.set_update_status(f"发现新版本 {release.tag}")
            # A silent (startup) check only prompts once per version per run;
            # a manual check always re-opens the dialog.
            if not silent or release.tag != self._prompted_tag:
                self._prompted_tag = release.tag
                self._show_dialog(UpdateDialog(self.app, release))
        else:
            self.app.settings_window.set_update_status(f"已是最新版本 v{APP_VERSION}")

    def _on_check_failed(self, message: str, silent: bool) -> None:
        self._checking = False
        self.app.settings_window.set_update_status("" if silent else f"检查更新失败：{message}")

    def _show_changelog(self, notes: str, html: bool = False) -> None:
        self._show_dialog(ChangelogDialog(notes, html))

    def _show_dialog(self, dialog: QDialog) -> None:
        self._dialog = dialog
        self.app._center_widget(dialog)
        dialog.show()
        dialog.activateWindow()
        dialog.raise_()
