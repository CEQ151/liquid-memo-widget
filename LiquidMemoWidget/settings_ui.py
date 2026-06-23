"""Settings window (appearance / behavior / calendar subscriptions / about).
Talks to the app only through the duck-typed `self.app` handle."""
from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    CheckBox,
    ColorDialog,
    ComboBox,
    FluentIcon,
    HyperlinkButton,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SmoothScrollArea,
    SpinBox,
    SwitchButton,
    TitleLabel,
    ToolTipFilter,
    ToolTipPosition,
    TransparentToolButton,
    setCustomStyleSheet,
)

from ui_common import (
    FONT_STACK_QSS,
    FluentSettingRow,
    FramelessDragMixin,
    InfoToolTipFilter,
    SETTING_CONTROL_FONT_PX,
    SETTING_NAV_FONT_PX,
    SETTING_ROW_TITLE_FONT_PX,
    SETTING_STATUS_FONT_PX,
    SETTING_TITLE_FONT_PX,
    add_soft_shadow,
    enlarge_control_font,
    scaled_dialog_size,
    set_label_font,
)
from skin_editor import CropDialog, export_crop, image_open_filter, load_skin_pixmap
from startup import is_startup_enabled, set_startup
from state_store import CalendarFeed, CustomSkin, Settings, skins_dir
from version import APP_VERSION, GITHUB_URL

if TYPE_CHECKING:
    from app import LiquidMemoApp


class SettingsWindow(FramelessDragMixin, QDialog):
    def __init__(self, app: "LiquidMemoApp") -> None:
        super().__init__(None, Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.app = app
        self._last_startup_checked = is_startup_enabled()
        self._version_taps: list[float] = []
        self.setWindowTitle("设置")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(scaled_dialog_size(1120, 860))
        self._build()

    def _build(self) -> None:
        self.frame = QFrame(self)
        self.frame.setObjectName("fluentPanel")
        self.frame.setGeometry(0, 0, self.width(), self.height())
        self.frame.setStyleSheet(
            f"""
            QFrame#fluentPanel {{
                {FONT_STACK_QSS}
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgb(252, 253, 255), stop:1 rgb(240, 244, 250));
                border: 1px solid rgba(255,255,255,210);
                border-radius: 22px;
            }}
            QFrame#colorSwatch {{
                border: 1px solid rgba(17,24,32,38);
                border-radius: 9px;
            }}
            """
        )
        add_soft_shadow(self.frame, blur=40, y=14, alpha=90)

        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(38, 34, 38, 36)
        layout.setSpacing(24)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = TitleLabel("设置")
        set_label_font(title, SETTING_TITLE_FONT_PX)
        subtitle = BodyLabel("调整桌面备忘的玻璃、颜色、启动和窗口行为。")
        subtitle.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,150); font-size: {SETTING_STATUS_FONT_PX}px;")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        reset = PushButton("恢复默认外观", self.frame, FluentIcon.RETURN)
        reset.setToolTip("仅恢复「外观」分类的默认值，不影响行为与日历订阅设置")
        reset.installEventFilter(ToolTipFilter(reset, showDelay=300, position=ToolTipPosition.BOTTOM))
        reset.clicked.connect(self.reset_defaults)
        enlarge_control_font(reset)
        header.addWidget(reset)
        close = PrimaryPushButton("完成", self.frame, FluentIcon.ACCEPT)
        close.clicked.connect(self._finish)
        enlarge_control_font(close)
        header.addWidget(close)
        layout.addLayout(header)

        divider = QFrame(self.frame)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(17,24,32,24); border: none;")
        layout.addWidget(divider)

        body = QHBoxLayout()
        body.setSpacing(24)
        self.nav = QListWidget(self.frame)
        self.nav.setFixedWidth(240)
        self.nav.setFrameShape(QFrame.NoFrame)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setStyleSheet(
            f"""
            QListWidget {{
                {FONT_STACK_QSS}
                background: transparent;
                border: none;
                outline: none;
                font-size: {SETTING_NAV_FONT_PX}px;
            }}
            QListWidget::item {{
                color: rgb(24, 32, 40);
                padding: 0px 14px;
                margin: 2px 0px;
                border-radius: 9px;
            }}
            QListWidget::item:hover {{
                background: rgba(17, 24, 32, 14);
            }}
            QListWidget::item:selected {{
                background: rgba(0, 103, 192, 30);
                color: rgb(0, 71, 138);
            }}
            """
        )
        self.stack = QStackedWidget(self.frame)
        self.stack.setStyleSheet("background: transparent;")
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        layout.addLayout(body, 1)
        self.form: QVBoxLayout | None = None

        self._section("外观")
        self.skin = self._combo_row(
            "皮肤",
            "磨砂玻璃省性能、文字易读，是默认皮肤；图片皮肤使用你上传的图片作为静态背景。",
            {"磨砂玻璃（推荐）": "acrylic"},
            self.app.state.settings.skin,
        )
        self._refresh_skin_combo()  # append any saved image skins + select the active one
        self.skin.currentIndexChanged.connect(self._apply)
        self._image_skins_card()
        self.window_color = self._color_row("窗口颜色", "控制磨砂玻璃的低饱和背景染色。", self.app.state.settings.windowTint)
        self.text_color = self._color_row("待办字体颜色", "选择后自动切到手动颜色，并立即应用到普通待办。", self.app.state.settings.todoTextColor, True)
        self.urgent_color = self._color_row("加急字体颜色", "选择后自动切到手动颜色，并立即应用到加急待办。", self.app.state.settings.urgentTextColor, True)
        self.font_mode = self._combo_row(
            "字体颜色模式",
            "自动模式会根据桌面背景选择深色或浅色文字；增强模式会加极轻柔光保护阅读性。",
            {"自动颜色 + 高对比增强": "autoEnhanced", "自动颜色": "auto", "手动颜色": "manual"},
            self.app.state.settings.fontColorMode,
        )
        self.font_mode.currentIndexChanged.connect(self._apply)

        self._section("行为")
        self.complete = self._combo_row("勾选完成之后", "选择完成事项是直接归档，还是留在列表中淡化显示。", {"自动归档消失": "archive", "加分割线并淡化": "dim"}, self.app.state.settings.completeBehavior)
        self.complete.currentIndexChanged.connect(self._apply)
        self.position = self._combo_row("默认启动位置", "应用启动时窗口出现的位置。", {"右上角": "topRight", "右下角": "bottomRight", "左上角": "topLeft", "左下角": "bottomLeft", "上次位置": "last", "使用当前位置": "current"}, self.app.state.window.startPosition)
        self.position.currentIndexChanged.connect(self._apply)
        self.startup = self._switch_row("开机自启动", "登录 Windows 后自动启动桌面备忘。", self._last_startup_checked)
        self.startup.checkedChanged.connect(lambda _checked: self._apply())
        self.window_mode = self._combo_row(
            "窗口显示模式",
            "普通窗口持续显示；贴边隐藏会滑出屏幕；悬浮图标点击后展开，移开后自动收回。",
            {"普通悬浮窗口": "normal", "贴边自动隐藏": "edgeHide", "悬浮图标": "floatingLauncher"},
            self.app.state.settings.windowMode,
        )
        self._nav_base_style = self.nav.styleSheet()
        self.window_mode.currentIndexChanged.connect(self._apply)

        self._section("提醒")
        self.notify_enabled = self._switch_row(
            "启用系统提醒", "日程或待办临近截止时，在屏幕右下角弹出 Windows 系统通知。",
            self.app.state.settings.notificationsEnabled,
        )
        self.notify_enabled.checkedChanged.connect(lambda _checked: self._apply())
        self.notify_minutes = self._spinbox_row(
            "提前提醒（分钟）", "在开始/截止时间前这么多分钟提醒；全天日程固定当天上午 9 点提醒。",
            self.app.state.settings.notifyMinutesBefore, 1, 1440,
        )
        self.notify_minutes.valueChanged.connect(lambda _value: self._apply())
        self.near_highlight_days = self._spinbox_row(
            "临期高亮（天）", "待办截止或日程开始前这么多天，时间会显示为橙色。",
            self.app.state.settings.nearHighlightDays, 1, 30,
        )
        self.near_highlight_days.valueChanged.connect(lambda _value: self._apply())

        self._section("日历订阅")
        self.calendar_enabled = self._switch_row(
            "启用日历订阅", "开启后自动同步勾选的日历订阅中近 N 天的日程。", self.app.state.settings.calendarEnabled
        )
        self.calendar_enabled.checkedChanged.connect(lambda _checked: self._apply())
        self._feeds_card()
        self.calendar_days = self._spinbox_row(
            "同步未来天数", "只同步从今天起这么多天内的日程。", self.app.state.settings.calendarSyncDays, 1, 30
        )
        self.calendar_days.valueChanged.connect(lambda _value: self._apply())
        self._calendar_status_row()

        self._section("关于")
        github_link = HyperlinkButton(GITHUB_URL, "GitHub 仓库", None, FluentIcon.GITHUB)
        enlarge_control_font(github_link)
        self.form.addWidget(FluentSettingRow("项目主页", "查看源码、提交反馈或为项目点个 Star。", github_link))
        self._update_row()
        self._surprise_status_row()
        self.auto_update = self._switch_row(
            "自动检查更新", "启动后在后台检查新版本（每 12 小时一次）；关闭后仅在点击「检查更新」时检查。",
            self.app.state.settings.autoCheckUpdates,
        )
        self.auto_update.checkedChanged.connect(lambda _checked: self._apply())

        self.form.addStretch()
        self.nav.setCurrentRow(0)
        surprise = getattr(self.app, "surprise", None)
        self.apply_surprise_theme(bool(surprise and surprise.active))

    def _section(self, title: str) -> None:
        # Each section becomes a nav entry + its own scrollable page; the row helpers
        # keep appending to self.form, which now points at the newest page's layout.
        if self.form is not None:
            self.form.addStretch()
        scroll = SmoothScrollArea(self.stack)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            """
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }
            QScrollBar::handle:vertical { background: rgba(17,24,32,60); border-radius: 3px; min-height: 32px; }
            QScrollBar::handle:vertical:hover { background: rgba(17,24,32,100); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        self.form = QVBoxLayout(page)
        self.form.setContentsMargins(0, 4, 12, 4)
        self.form.setSpacing(14)
        scroll.setWidget(page)
        self.stack.addWidget(scroll)
        item = QListWidgetItem(title)
        item.setSizeHint(QSize(0, 66))
        self.nav.addItem(item)

    def _color_row(self, title: str, content: str, color: str, activates_manual_text_color: bool = False) -> QWidget:
        control = QWidget()
        control.setProperty("selectedColor", color)
        control.setProperty("activatesManualTextColor", activates_manual_text_color)
        control.setFixedWidth(330)
        layout = QHBoxLayout(control)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        swatch = QFrame()
        swatch.setObjectName("colorSwatch")
        swatch.setFixedSize(38, 38)
        button = PushButton(color, control, FluentIcon.PALETTE)
        button.setFixedWidth(265)
        enlarge_control_font(button)
        button.clicked.connect(lambda: self._pick_color(control, swatch, button, title))
        layout.addWidget(swatch)
        layout.addWidget(button, 1)
        self._style_color_control(control, swatch, button, color)
        self.form.addWidget(FluentSettingRow(title, content, control))
        return control

    def _style_color_control(self, control: QWidget, swatch: QFrame, button: PushButton, color: str) -> None:
        control.setProperty("selectedColor", color)
        swatch.setStyleSheet(f"QFrame#colorSwatch {{ background: {color}; }}")
        button.setText(color)

    def _combo_row(self, title: str, content: str, options: dict[str, str], current: str) -> ComboBox:
        combo = ComboBox()
        combo.setFixedWidth(360)
        enlarge_control_font(combo)
        for text, data in options.items():
            combo.addItem(text, userData=data)
        index = combo.findData(current)
        combo.setCurrentIndex(max(0, index))
        self.form.addWidget(FluentSettingRow(title, content, combo))
        return combo

    def _switch_row(self, title: str, content: str, checked: bool) -> SwitchButton:
        switch = SwitchButton()
        switch.setChecked(checked)
        enlarge_control_font(switch)
        # The On/Off label carries its own copy of switch_button.qss, which shadows
        # rules set on the SwitchButton itself.
        label_qss = (
            f"SwitchButton>QLabel {{ font: {SETTING_CONTROL_FONT_PX}px"
            " 'Times New Roman','Microsoft YaHei','Segoe UI Emoji'; }"
        )
        setCustomStyleSheet(switch.label, label_qss, label_qss)
        self.form.addWidget(FluentSettingRow(title, content, switch))
        return switch

    def _feeds_card(self) -> None:
        """Subscription list: one checkbox row per calendar (checked = shown in the memo
        window), delete moves a feed to the archive, and the archive can be restored."""
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = BodyLabel("订阅的日历")
        set_label_font(title, SETTING_ROW_TITLE_FONT_PX)
        header.addWidget(title)
        info = TransparentToolButton(FluentIcon.INFO, card)
        info.setFixedSize(26, 26)
        info.setIconSize(QSize(16, 16))
        info.setCursor(Qt.WhatsThisCursor)
        info.setToolTip(
            "粘贴 Google / Outlook / Apple 的 ICS 或 webcal 日历地址，可添加多个订阅；"
            "只有勾选的日历会在备忘录窗口中展示。删除的链接会自动存档，可从「恢复已删除」找回。"
        )
        info.installEventFilter(InfoToolTipFilter(info, showDelay=200, position=ToolTipPosition.TOP))
        header.addWidget(info)
        header.addStretch()
        self.feed_restore_button = PushButton("恢复已删除", card, FluentIcon.HISTORY)
        enlarge_control_font(self.feed_restore_button)
        self.feed_restore_button.clicked.connect(self._show_restore_menu)
        header.addWidget(self.feed_restore_button)
        layout.addLayout(header)

        self.feed_rows_layout = QVBoxLayout()
        self.feed_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_rows_layout.setSpacing(2)
        layout.addLayout(self.feed_rows_layout)

        add_row = QHBoxLayout()
        add_row.setSpacing(10)
        self.feed_input = LineEdit()
        self.feed_input.setPlaceholderText("https://… .ics 或 webcal://…")
        self.feed_input.setClearButtonEnabled(True)
        enlarge_control_font(self.feed_input)
        self.feed_input.returnPressed.connect(self._add_feed)
        add_button = PushButton("添加", card, FluentIcon.ADD)
        enlarge_control_font(add_button)
        add_button.clicked.connect(self._add_feed)
        add_row.addWidget(self.feed_input, 1)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        self.form.addWidget(card)
        self.refresh_feed_list()

    @staticmethod
    def _feed_label(feed: CalendarFeed) -> str:
        text = feed.name or feed.url
        return text if len(text) <= 46 else text[:45] + "…"

    def refresh_feed_list(self) -> None:
        if not hasattr(self, "feed_rows_layout"):
            return
        while self.feed_rows_layout.count():
            item = self.feed_rows_layout.takeAt(0)
            if item.widget():
                item.widget().hide()  # deleteLater is deferred; hide now so rows never overlap
                item.widget().deleteLater()
        settings = self.app.state.settings
        if not settings.calendarFeeds:
            empty = BodyLabel("尚未添加日历订阅")
            empty.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,120); font-size: {SETTING_STATUS_FONT_PX}px;")
            self.feed_rows_layout.addWidget(empty)
        for feed in settings.calendarFeeds:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            box = CheckBox(self._feed_label(feed))
            box.setChecked(feed.enabled)
            enlarge_control_font(box)
            box.setToolTip(feed.url)
            box.installEventFilter(InfoToolTipFilter(box, showDelay=400, position=ToolTipPosition.TOP))
            box.toggled.connect(lambda checked, fid=feed.id: self._toggle_feed(fid, checked))
            remove = TransparentToolButton(FluentIcon.DELETE, row)
            remove.setFixedSize(28, 28)
            remove.setIconSize(QSize(15, 15))
            remove.setToolTip("删除此订阅（可从「恢复已删除」找回）")
            remove.installEventFilter(ToolTipFilter(remove, showDelay=300, position=ToolTipPosition.TOP))
            remove.clicked.connect(lambda _checked=False, fid=feed.id: self._delete_feed(fid))
            row_layout.addWidget(box, 1)
            row_layout.addWidget(remove)
            self.feed_rows_layout.addWidget(row)
        self.feed_restore_button.setVisible(bool(settings.calendarFeedArchive))

    def _feeds_changed(self) -> None:
        self.refresh_feed_list()
        self.app.save()
        self.app.calendar.on_settings_changed()

    def _add_feed(self) -> None:
        url = self.feed_input.text().strip()
        if not url:
            return
        settings = self.app.state.settings
        if any(feed.url == url for feed in settings.calendarFeeds):
            self.feed_input.clear()
            return
        archived = next((feed for feed in settings.calendarFeedArchive if feed.url == url), None)
        if archived:
            settings.calendarFeedArchive.remove(archived)
            archived.enabled = True
            settings.calendarFeeds.append(archived)
        else:
            settings.calendarFeeds.append(CalendarFeed(url=url))
        self.feed_input.clear()
        self._feeds_changed()

    def _delete_feed(self, feed_id: str) -> None:
        settings = self.app.state.settings
        feed = next((feed for feed in settings.calendarFeeds if feed.id == feed_id), None)
        if feed is None:
            return
        settings.calendarFeeds.remove(feed)
        # Archive it (dedupe by URL, newest first, bounded) so deletion is recoverable.
        settings.calendarFeedArchive = [f for f in settings.calendarFeedArchive if f.url != feed.url]
        settings.calendarFeedArchive.insert(0, feed)
        del settings.calendarFeedArchive[12:]
        state = self.app.state
        state.calendarEvents = [event for event in state.calendarEvents if event.feedId != feed_id]
        state.calendarDoneKeys = [key for key in state.calendarDoneKeys if not key.startswith(feed_id + "|")]
        self._feeds_changed()

    def _toggle_feed(self, feed_id: str, checked: bool) -> None:
        settings = self.app.state.settings
        feed = next((feed for feed in settings.calendarFeeds if feed.id == feed_id), None)
        if feed is None or feed.enabled == checked:
            return
        feed.enabled = checked
        self.app.save()
        self.app.calendar.on_settings_changed()

    def _show_restore_menu(self) -> None:
        settings = self.app.state.settings
        if not settings.calendarFeedArchive:
            return
        menu = RoundMenu(parent=self)
        for feed in list(settings.calendarFeedArchive):
            action = Action(FluentIcon.CALENDAR, self._feed_label(feed), menu)
            action.triggered.connect(lambda _checked=False, fid=feed.id: self._restore_feed(fid))
            menu.addAction(action)
        menu.exec(self.feed_restore_button.mapToGlobal(
            QPoint(0, self.feed_restore_button.height() + 4)
        ))

    def _restore_feed(self, feed_id: str) -> None:
        settings = self.app.state.settings
        feed = next((feed for feed in settings.calendarFeedArchive if feed.id == feed_id), None)
        if feed is None:
            return
        settings.calendarFeedArchive.remove(feed)
        if not any(existing.url == feed.url for existing in settings.calendarFeeds):
            feed.enabled = True
            settings.calendarFeeds.append(feed)
        self._feeds_changed()

    def _spinbox_row(self, title: str, content: str, value: int, minimum: int, maximum: int) -> SpinBox:
        spin = SpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setFixedWidth(180)
        enlarge_control_font(spin)
        self.form.addWidget(FluentSettingRow(title, content, spin))
        return spin

    def _calendar_status_row(self) -> None:
        control = QWidget()
        control.setFixedWidth(440)
        layout = QHBoxLayout(control)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.calendar_status_label = BodyLabel("")
        self.calendar_status_label.setWordWrap(True)
        self.calendar_status_label.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,150); font-size: {SETTING_STATUS_FONT_PX}px;")
        sync_button = PushButton("立即同步")
        sync_button.clicked.connect(self._sync_calendar_now)
        enlarge_control_font(sync_button)
        layout.addWidget(self.calendar_status_label, 1)
        layout.addWidget(sync_button)
        self.form.addWidget(FluentSettingRow("同步状态", "手动触发一次同步，或查看上次结果。", control))
        self.refresh_calendar_status()

    def _update_row(self) -> None:
        control = QWidget()
        control.setFixedWidth(440)
        layout = QHBoxLayout(control)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.update_status_label = BodyLabel(f"当前版本 v{APP_VERSION}")
        self.update_status_label.setWordWrap(True)
        self.update_status_label.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,150); font-size: {SETTING_STATUS_FONT_PX}px;")
        self.update_status_label.installEventFilter(self)
        check_button = PushButton("检查更新", control, FluentIcon.SYNC)
        check_button.clicked.connect(lambda: self.app.updater.check(silent=False))
        enlarge_control_font(check_button)
        layout.addWidget(self.update_status_label, 1)
        layout.addWidget(check_button)
        self.form.addWidget(FluentSettingRow("检查更新", "从 GitHub Releases 获取新版本，自动下载并安装。", control))

    def _surprise_status_row(self) -> None:
        control = QWidget()
        control.setFixedWidth(440)
        layout = QHBoxLayout(control)
        layout.setContentsMargins(0, 0, 0, 0)
        self.surprise_status_label = BodyLabel("特别模式已激活")
        set_label_font(self.surprise_status_label, SETTING_STATUS_FONT_PX)
        restore = PushButton("恢复普通模式", control, FluentIcon.RETURN)
        enlarge_control_font(restore)
        restore.clicked.connect(lambda: getattr(self.app, "surprise", None) and self.app.surprise.deactivate())
        layout.addWidget(self.surprise_status_label, 1)
        layout.addWidget(restore)
        self.surprise_row = FluentSettingRow("特别模式", "清除本机保存的专属密钥并恢复原主题。", control)
        self.form.addWidget(self.surprise_row)
        self.sync_surprise_state()

    def sync_surprise_state(self) -> None:
        if hasattr(self, "surprise_row"):
            surprise = getattr(self.app, "surprise", None)
            self.surprise_row.setVisible(bool(surprise and surprise.active))

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "update_status_label", None) and event.type() == QEvent.MouseButtonPress:
            surprise = getattr(self.app, "surprise", None)
            if event.button() == Qt.LeftButton and surprise is not None and not surprise.active:
                now = time.monotonic()
                self._version_taps = [stamp for stamp in self._version_taps if now - stamp <= 5.0]
                self._version_taps.append(now)
                if len(self._version_taps) >= 7:
                    self._version_taps.clear()
                    surprise.show_activation_dialog(self)
                return True
        return super().eventFilter(watched, event)

    def apply_surprise_theme(self, active: bool) -> None:
        top = "#FFF8FB" if active else "rgb(252,253,255)"
        bottom = "#FFE3EC" if active else "rgb(240,244,250)"
        self.frame.setStyleSheet(
            f"QFrame#fluentPanel {{ {FONT_STACK_QSS} background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {top},stop:1 {bottom}); border: 1px solid rgba(255,255,255,210); border-radius: 22px; }}"
            " QFrame#colorSwatch { border: 1px solid rgba(17,24,32,38); border-radius: 9px; }"
        )
        selected_bg = "rgba(232,93,147,42)" if active else "rgba(0,103,192,30)"
        selected_text = "#7A2447" if active else "rgb(0,71,138)"
        self.nav.setStyleSheet(
            self._nav_base_style
            + f" QListWidget::item:selected {{ background: {selected_bg}; color: {selected_text}; }}"
        )
        self.sync_surprise_state()

    def set_update_status(self, text: str) -> None:
        if hasattr(self, "update_status_label"):
            self.update_status_label.setText(text or f"当前版本 v{APP_VERSION}")

    def _sync_calendar_now(self) -> None:
        self._apply(save_now=True)
        self.app.calendar.sync_now()

    def refresh_calendar_status(self, syncing: bool = False) -> None:
        if not hasattr(self, "calendar_status_label"):
            return
        state = self.app.state
        if syncing:
            text = "正在同步…"
        elif state.calendarLastError:
            text = f"同步失败：{state.calendarLastError}"
        elif state.calendarLastSync:
            text = f"上次同步 {self._format_local_time(state.calendarLastSync)}（{len(state.calendarEvents)} 条）"
        else:
            text = "尚未同步"
        self.calendar_status_label.setText(text)

    @staticmethod
    def _format_local_time(iso_utc: str) -> str:
        try:
            return datetime.fromisoformat(iso_utc).astimezone().strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            return str(iso_utc)[:16]

    def _pick_color(self, control: QWidget, swatch: QFrame, button: PushButton, title: str) -> None:
        current = str(control.property("selectedColor") or "#F8FBFF")
        dialog = ColorDialog(QColor(current), title, self)
        if dialog.exec() == QDialog.Accepted:
            self._color_selected(control, swatch, button, dialog.color.name(), save_now=True)

    def _color_selected(self, control: QWidget, swatch: QFrame, button: PushButton, color: str, save_now: bool = False) -> None:
        self._style_color_control(control, swatch, button, color)
        if bool(control.property("activatesManualTextColor")):
            self._set_font_color_mode("manual")
        self._apply(save_now=save_now)

    def _set_font_color_mode(self, mode: str) -> None:
        index = self.font_mode.findData(mode)
        if index < 0 or self.font_mode.currentIndex() == index:
            return
        previous = self.font_mode.blockSignals(True)
        self.font_mode.setCurrentIndex(index)
        self.font_mode.blockSignals(previous)

    def _control_color(self, control: QWidget, fallback: str) -> str:
        return str(control.property("selectedColor") or fallback)

    # ── Image skins (custom background pictures) ──────────────────────────────────────────
    def _refresh_skin_combo(self) -> None:
        """Rebuild the skin picker: the built-in frost skin plus one entry per saved image skin.
        The built-in is always present and never removable; image skins reflect customSkins. Run
        with signals blocked so rebuilding never fires _apply."""
        combo = self.skin
        blocked = combo.blockSignals(True)
        combo.clear()
        combo.addItem("磨砂玻璃（推荐）", userData="acrylic")
        for skin in self.app.state.settings.customSkins:
            combo.addItem(skin.name or "未命名图片", userData=f"image:{skin.id}")
        index = combo.findData(self.app.state.settings.skin)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(blocked)

    def _image_skins_card(self) -> None:
        """Management card for image skins: a preview/list with per-row delete plus an add
        button that drives the upload → crop → name → save flow. Mirrors _feeds_card."""
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = BodyLabel("图片皮肤")
        set_label_font(title, SETTING_ROW_TITLE_FONT_PX)
        header.addWidget(title)
        info = TransparentToolButton(FluentIcon.INFO, card)
        info.setFixedSize(26, 26)
        info.setIconSize(QSize(16, 16))
        info.setCursor(Qt.WhatsThisCursor)
        info.setToolTip(
            "上传一张图片并裁切，保存为静态背景皮肤；保存后可在上方「皮肤」中选择。"
            "内置的磨砂玻璃皮肤不可删除。"
        )
        info.installEventFilter(InfoToolTipFilter(info, showDelay=200, position=ToolTipPosition.TOP))
        header.addWidget(info)
        header.addStretch()
        layout.addLayout(header)

        self.skin_rows_layout = QVBoxLayout()
        self.skin_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.skin_rows_layout.setSpacing(4)
        layout.addLayout(self.skin_rows_layout)

        add_row = QHBoxLayout()
        add_row.addStretch()
        add_button = PushButton("添加图片皮肤", card, FluentIcon.ADD)
        enlarge_control_font(add_button)
        add_button.clicked.connect(self._add_image_skin)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        self.form.addWidget(card)
        self.refresh_image_skin_list()

    def refresh_image_skin_list(self) -> None:
        if not hasattr(self, "skin_rows_layout"):
            return
        while self.skin_rows_layout.count():
            item = self.skin_rows_layout.takeAt(0)
            if item.widget():
                item.widget().hide()  # deleteLater is deferred; hide now so rows never overlap
                item.widget().deleteLater()
        skins = self.app.state.settings.customSkins
        if not skins:
            empty = BodyLabel("尚未添加图片皮肤")
            empty.setStyleSheet(f"{FONT_STACK_QSS} color: rgba(17,24,32,120); font-size: {SETTING_STATUS_FONT_PX}px;")
            self.skin_rows_layout.addWidget(empty)
            return
        for skin in skins:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 4, 0, 4)
            row_layout.setSpacing(12)
            thumb = QLabel()
            thumb.setFixedSize(72, 44)
            thumb.setStyleSheet("background: rgba(17,24,32,20); border-radius: 6px;")
            pixmap = load_skin_pixmap(skin.image_path())
            if pixmap is not None:
                scaled = pixmap.scaled(72, 44, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                thumb.setPixmap(scaled.copy((scaled.width() - 72) // 2, (scaled.height() - 44) // 2, 72, 44))
            name = BodyLabel(skin.name or "未命名图片")
            set_label_font(name, SETTING_CONTROL_FONT_PX)
            remove = TransparentToolButton(FluentIcon.DELETE, row)
            remove.setFixedSize(28, 28)
            remove.setIconSize(QSize(15, 15))
            remove.setToolTip("删除此图片皮肤（无法恢复）")
            remove.installEventFilter(ToolTipFilter(remove, showDelay=300, position=ToolTipPosition.TOP))
            remove.clicked.connect(lambda _checked=False, sid=skin.id: self._delete_image_skin(sid))
            row_layout.addWidget(thumb)
            row_layout.addWidget(name, 1)
            row_layout.addWidget(remove)
            self.skin_rows_layout.addWidget(row)

    def _add_image_skin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", image_open_filter())
        if not path:
            return
        source = QPixmap(path)
        if source.isNull():
            return  # unreadable / unsupported file — silently ignore, the picker filters by type
        window = self.app.window
        aspect = (window.width() / window.height()) if (window and window.height()) else 1.4
        dialog = CropDialog(source, aspect, self)
        if dialog.exec() != QDialog.Accepted:
            return
        skin = CustomSkin(name=dialog.skin_name)
        skin.file = f"{skin.id}.png"
        if not export_crop(dialog.canvas, skins_dir() / skin.file):
            return
        self.app.state.settings.customSkins.append(skin)
        self.app.save()
        self._refresh_skin_combo()
        self.refresh_image_skin_list()
        # Auto-select the new skin; the index change fires _apply, which applies the image skin.
        index = self.skin.findData(f"image:{skin.id}")
        if index >= 0:
            self.skin.setCurrentIndex(index)

    def _delete_image_skin(self, skin_id: str) -> None:
        settings = self.app.state.settings
        skin = next((s for s in settings.customSkins if s.id == skin_id), None)
        if skin is None:
            return
        try:
            image_path = skin.image_path()
            if image_path.exists():
                image_path.unlink()
        except OSError:
            pass
        settings.customSkins = [s for s in settings.customSkins if s.id != skin_id]
        was_active = settings.skin == f"image:{skin_id}"
        if was_active:
            settings.skin = "acrylic"  # deleting the live skin falls back to the frost skin
        self.app.save()
        self._refresh_skin_combo()
        self.refresh_image_skin_list()
        if was_active:
            # The combo now points at acrylic (signals blocked during rebuild), so re-render the
            # window directly rather than relying on a currentIndexChanged that won't fire.
            self.app.window.apply_settings()

    def sync_from_state(self) -> None:
        settings = self.app.state.settings
        blockers = [
            self.skin.blockSignals(True),
            self.font_mode.blockSignals(True),
            self.complete.blockSignals(True),
            self.position.blockSignals(True),
            self.startup.blockSignals(True),
            self.window_mode.blockSignals(True),
            self.notify_enabled.blockSignals(True),
            self.notify_minutes.blockSignals(True),
            self.near_highlight_days.blockSignals(True),
            self.calendar_enabled.blockSignals(True),
            self.calendar_days.blockSignals(True),
            self.auto_update.blockSignals(True),
        ]
        self._refresh_skin_combo()  # rebuild entries (custom skins may have changed) + reselect
        self._set_color_control(self.window_color, settings.windowTint)
        self._set_color_control(self.text_color, settings.todoTextColor)
        self._set_color_control(self.urgent_color, settings.urgentTextColor)
        self.font_mode.setCurrentIndex(max(0, self.font_mode.findData(settings.fontColorMode)))
        self.complete.setCurrentIndex(max(0, self.complete.findData(settings.completeBehavior)))
        self.position.setCurrentIndex(max(0, self.position.findData(self.app.state.window.startPosition)))
        self._last_startup_checked = is_startup_enabled()
        self.startup.setChecked(self._last_startup_checked)
        self.window_mode.setCurrentIndex(max(0, self.window_mode.findData(settings.windowMode)))
        self.notify_enabled.setChecked(settings.notificationsEnabled)
        self.notify_minutes.setValue(settings.notifyMinutesBefore)
        self.near_highlight_days.setValue(settings.nearHighlightDays)
        self.calendar_enabled.setChecked(settings.calendarEnabled)
        self.calendar_days.setValue(settings.calendarSyncDays)
        self.auto_update.setChecked(settings.autoCheckUpdates)
        self.refresh_feed_list()
        self.refresh_image_skin_list()
        self.refresh_calendar_status()
        self.sync_surprise_state()
        for widget, blocked in zip(
            [self.skin, self.font_mode, self.complete, self.position, self.startup,
             self.window_mode, self.notify_enabled, self.notify_minutes, self.near_highlight_days,
             self.calendar_enabled, self.calendar_days, self.auto_update],
            blockers,
        ):
            widget.blockSignals(blocked)

    def _set_color_control(self, control: QWidget, color: str) -> None:
        swatch = control.findChild(QFrame, "colorSwatch")
        button = control.findChild(PushButton)
        if swatch and button:
            self._style_color_control(control, swatch, button, color)

    def _finish(self) -> None:
        self._apply(save_now=True)
        self.hide()

    def reset_defaults(self) -> None:
        # Appearance only. Behavior, startup and the calendar subscription must survive a
        # reset — wiping the whole Settings() used to silently disable and clear the user's
        # calendar feeds.
        defaults = Settings()
        settings = self.app.state.settings
        settings.skin = defaults.skin
        settings.windowTint = defaults.windowTint
        settings.todoTextColor = defaults.todoTextColor
        settings.urgentTextColor = defaults.urgentTextColor
        settings.fontColorMode = defaults.fontColorMode
        self.sync_from_state()
        self._apply(save_now=True)

    def _apply(self, *_args, save_now: bool = False) -> None:
        settings = self.app.state.settings
        window_mode_before = settings.windowMode
        settings.skin = str(self.skin.currentData())
        settings.windowTint = self._control_color(self.window_color, settings.windowTint)
        settings.todoTextColor = self._control_color(self.text_color, settings.todoTextColor)
        settings.urgentTextColor = self._control_color(self.urgent_color, settings.urgentTextColor)
        settings.fontColorMode = str(self.font_mode.currentData())
        settings.completeBehavior = str(self.complete.currentData())
        settings.layerMode = "alwaysVisibleClickThrough"
        # Surprise mode forces (and owns) the floatingLauncher window mode. The combo isn't synced
        # at activation, so writing its stale value here would silently revert the forced mode.
        surprise = getattr(self.app, "surprise", None)
        if not (surprise is not None and surprise.active):
            settings.windowMode = str(self.window_mode.currentData())
        settings.notificationsEnabled = self.notify_enabled.isChecked()
        settings.notifyMinutesBefore = int(self.notify_minutes.value())
        settings.nearHighlightDays = int(self.near_highlight_days.value())
        settings.autoCheckUpdates = self.auto_update.isChecked()
        self.app.state.window.startPosition = str(self.position.currentData())
        if self.app.state.window.startPosition == "current":
            self.app.state.window.x = self.app.window.x()
            self.app.state.window.y = self.app.window.y()
        startup_checked = self.startup.isChecked()
        settings.startWithWindows = startup_checked
        if startup_checked != self._last_startup_checked:
            set_startup(startup_checked)
            self._last_startup_checked = startup_checked

        # Calendar: detect a change so we only (re)sync when the subscription actually changes.
        # (Feed add/delete/toggle bypasses _apply and calls on_settings_changed directly.)
        calendar_before = (settings.calendarEnabled, settings.calendarSyncDays)
        settings.calendarEnabled = self.calendar_enabled.isChecked()
        settings.calendarSyncDays = int(self.calendar_days.value())
        calendar_changed = calendar_before != (settings.calendarEnabled, settings.calendarSyncDays)

        if save_now:
            self.app.save()
        else:
            self.app.save_later()
        self.app.window.apply_settings()
        if window_mode_before != settings.windowMode:
            controller = getattr(self.app, "floating", None)
            if controller is not None:
                controller.apply_mode()
        if calendar_changed:
            self.app.calendar.on_settings_changed()
        # Re-scan so toggling on / lowering the lead time reminds immediately; no-ops when
        # disabled, and the per-key dedup keeps it from re-toasting on every settings edit.
        self.app.notifier.check_now()
