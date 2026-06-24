"""Encrypted surprise-mode lifecycle and its two small UI surfaces."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import math

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    QRectF,
    QRandomGenerator,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import setThemeColor

from surprise_crypto import decrypt_with_key, key_from_passphrase, protect_key, read_envelope, unprotect_key
from ui_common import add_soft_shadow
from window_layer import protect_window_from_capture


NORMAL_ACCENT = "#009FAA"
SURPRISE_ACCENT = "#E85D93"
SURPRISE_TEXT = "#4A2334"
SURPRISE_MUTED = "#8C6574"


@dataclass(frozen=True)
class NoteTheme:
    """Colour + wording for one selectable 拾光纸条 look. Drives the note popup
    (panel / paper / seal / button / text) and the in-memo SurpriseTodoRow."""

    key: str
    eyebrow_text: str
    title_text: str
    seal_char: str
    paper_top: str           # atmosphere card base gradient (3 stops)
    paper_mid: str
    paper_bottom: str
    glow_rgb: tuple[int, int, int]          # atmosphere radial glow tint
    note_top: tuple[int, int, int, int]     # inner paper gradient (rgba)
    note_bottom: tuple[int, int, int, int]
    text: str                # title + note + row text
    eyebrow: str
    accent: str              # button / draw button / checkbox
    accent_hover: str
    accent_pressed: str
    muted: str               # deadline / secondary text
    seal_rgb: tuple[int, int, int]
    row_tint: tuple[int, int, int]          # in-memo row card fill


NOTE_THEMES: dict[str, NoteTheme] = {
    "qinghua": NoteTheme(
        key="qinghua", eyebrow_text="A NOTE FOR TODAY", title_text="今日拾光", seal_char="心",
        paper_top="#F4F1E4", paper_mid="#EEE9D2", paper_bottom="#E6E0C4",
        glow_rgb=(150, 186, 214),
        note_top=(255, 255, 250, 232), note_bottom=(247, 244, 232, 212),
        text="#143b61", eyebrow="#5b7fa0",
        accent="#3d7ab3", accent_hover="#4f8cc4", accent_pressed="#2f6699",
        muted="#6b7f93", seal_rgb=(47, 106, 163), row_tint=(238, 233, 210),
    ),
    "warm": NoteTheme(
        key="warm", eyebrow_text="A LETTER FOR YOU", title_text="致我所爱", seal_char="念",
        paper_top="#F6EEDA", paper_mid="#EFE7D4", paper_bottom="#E6DBC0",
        glow_rgb=(230, 185, 166),
        note_top=(255, 252, 246, 232), note_bottom=(248, 240, 228, 212),
        text="#43302f", eyebrow="#a07d63",
        accent="#c08a6a", accent_hover="#cf9a7a", accent_pressed="#a9755a",
        muted="#8a6f5e", seal_rgb=(181, 65, 58), row_tint=(239, 231, 212),
    ),
    "blush": NoteTheme(
        key="blush", eyebrow_text="A NOTE FOR TODAY", title_text="今日拾光", seal_char="意",
        paper_top="#FBF2F0", paper_mid="#F6EBE9", paper_bottom="#EEDFE0",
        glow_rgb=(240, 194, 207),
        note_top=(255, 252, 252, 230), note_bottom=(250, 242, 242, 210),
        text="#4A2334", eyebrow="#b98a9c",
        accent="#c96a86", accent_hover="#d57c96", accent_pressed="#b85877",
        muted="#8C6574", seal_rgb=(184, 86, 122), row_tint=(246, 235, 233),
    ),
}

DEFAULT_NOTE_THEME = "qinghua"


def note_theme(key: str) -> NoteTheme:
    return NOTE_THEMES.get(key, NOTE_THEMES[DEFAULT_NOTE_THEME])


def _restore_pre_surprise_skin(settings) -> None:
    """On leaving surprise mode, restore the skin chosen before activation; the swirl is only valid
    while active, so drop any lingering "surprise_swirl" selection back to the frost skin."""
    if settings.preSurpriseSkin:
        settings.skin = settings.preSurpriseSkin
    elif settings.skin == "surprise_swirl":
        settings.skin = "acrylic"
    settings.preSurpriseSkin = ""


def _poetic_font(pixel_size: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont("STKaiti", -1, weight)
    font.setPixelSize(pixel_size)
    font.setFamilies(["STKaiti", "KaiTi", "FangSong", "Microsoft YaHei UI", "Segoe UI Emoji"])
    return font


def _ui_font(pixel_size: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont("Microsoft YaHei UI", -1, weight)
    font.setPixelSize(pixel_size)
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
    return font


class _AtmospherePanel(QFrame):
    """Painter-rendered card: one clean edge, soft light, and a short-lived star reveal."""

    def __init__(self, parent: QWidget, mood: str, theme: NoteTheme | None = None) -> None:
        super().__init__(parent)
        self.mood = mood
        self.theme = theme  # None -> original pink look (kept for the activation dialog)
        self._sparkle = 0.0
        self._sparkle_animation: QVariantAnimation | None = None
        self.setAttribute(Qt.WA_TranslucentBackground)

    def play_sparkles(self) -> None:
        if self._sparkle_animation is not None:
            self._sparkle_animation.stop()
            self._sparkle_animation.deleteLater()
        animation = QVariantAnimation(self)
        animation.setDuration(760)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.valueChanged.connect(self._set_sparkle)
        animation.finished.connect(lambda: self._finish_sparkles(animation))
        self._sparkle_animation = animation
        animation.start()

    def _finish_sparkles(self, animation: QVariantAnimation) -> None:
        self._set_sparkle(0.0)
        if self._sparkle_animation is animation:
            self._sparkle_animation = None
        animation.deleteLater()

    def _set_sparkle(self, value) -> None:
        self._sparkle = float(value)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = 28 if self.mood == "note" else 24

        theme = self.theme
        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if theme is not None:
            base.setColorAt(0.0, QColor(theme.paper_top))
            base.setColorAt(0.52, QColor(theme.paper_mid))
            base.setColorAt(1.0, QColor(theme.paper_bottom))
        else:
            base.setColorAt(0.0, QColor("#FFFCFD"))
            base.setColorAt(0.52, QColor("#FFF7F9"))
            base.setColorAt(1.0, QColor("#F8EEF2"))
        painter.setBrush(base)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, radius, radius)

        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        gr, gg, gb = theme.glow_rgb if theme is not None else (244, 184, 207)
        glow = QRadialGradient(QPointF(rect.right() - 48, rect.top() + 28), rect.width() * 0.52)
        glow.setColorAt(0.0, QColor(gr, gg, gb, 74))
        glow.setColorAt(0.55, QColor(gr, gg, gb, 24))
        glow.setColorAt(1.0, QColor(gr, gg, gb, 0))
        painter.fillRect(rect, glow)
        warmth = QRadialGradient(QPointF(rect.left() + 40, rect.bottom() - 18), rect.width() * 0.45)
        warmth.setColorAt(0.0, QColor(235, 202, 154, 30))
        warmth.setColorAt(1.0, QColor(235, 202, 154, 0))
        painter.fillRect(rect, warmth)
        # A soft halo cradling the title — only on the note card, tinted to the active theme.
        if theme is not None and self.mood == "note":
            halo = QRadialGradient(
                QPointF(rect.center().x(), rect.top() + rect.height() * 0.16), rect.width() * 0.36
            )
            halo.setColorAt(0.0, QColor(gr, gg, gb, 56))
            halo.setColorAt(0.6, QColor(gr, gg, gb, 18))
            halo.setColorAt(1.0, QColor(gr, gg, gb, 0))
            painter.fillRect(rect, halo)
        painter.restore()

        # One almost-white outline keeps the frameless card crisp without boxing every child.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 210), 1.0))
        painter.drawRoundedRect(rect, radius, radius)

        # A restrained hand-drawn arc is the only permanent ornament.
        painter.setPen(QPen(QColor(198, 155, 100, 78), 1.2, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(QRectF(rect.right() - 98, rect.top() + 22, 66, 42), 14 * 16, 112 * 16)

        if self._sparkle > 0.0:
            fade = math.sin(math.pi * self._sparkle)
            painter.setPen(Qt.NoPen)
            points = ((0.12, 0.26), (0.21, 0.72), (0.73, 0.18), (0.84, 0.64), (0.92, 0.35))
            for index, (px, py) in enumerate(points):
                x = rect.left() + rect.width() * px
                y = rect.top() + rect.height() * py - self._sparkle * (5 + index)
                size = 2.1 + (index % 2) * 1.1
                painter.setBrush(QColor(198, 155, 100, round(150 * fade)))
                star = QPainterPath()
                star.moveTo(x, y - size)
                star.lineTo(x + size * 0.34, y - size * 0.34)
                star.lineTo(x + size, y)
                star.lineTo(x + size * 0.34, y + size * 0.34)
                star.lineTo(x, y + size)
                star.lineTo(x - size * 0.34, y + size * 0.34)
                star.lineTo(x - size, y)
                star.lineTo(x - size * 0.34, y - size * 0.34)
                star.closeSubpath()
                painter.drawPath(star)
        painter.end()


class _NotePaper(QFrame):
    def __init__(self, parent: QWidget | None = None, theme: NoteTheme | None = None) -> None:
        super().__init__(parent)
        self.theme = theme or NOTE_THEMES[DEFAULT_NOTE_THEME]
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        theme = self.theme
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paper = QLinearGradient(rect.topLeft(), rect.bottomRight())
        paper.setColorAt(0.0, QColor(*theme.note_top))
        paper.setColorAt(1.0, QColor(*theme.note_bottom))
        painter.setPen(Qt.NoPen)
        painter.setBrush(paper)
        painter.drawRoundedRect(rect, 18, 18)

        # Tiny deterministic fibres make the card feel printed, without a texture asset.
        painter.setBrush(QColor(139, 89, 105, 13))
        for x_ratio, y_ratio in ((.13, .23), (.28, .71), (.43, .34), (.57, .79), (.76, .29), (.88, .68)):
            painter.drawEllipse(QPointF(rect.width() * x_ratio, rect.height() * y_ratio), 0.9, 0.9)
        # Opening quotation marks are paths instead of a glyph, so they render consistently even
        # when a user's optional calligraphy font is unavailable. Tinted to the theme accent.
        quote_color = QColor(theme.accent)
        quote_color.setAlpha(52)
        painter.setPen(Qt.NoPen)
        painter.setBrush(quote_color)
        for offset in (0, 17):
            quote = QPainterPath()
            quote.addEllipse(QRectF(24 + offset, 20, 10, 10))
            quote.moveTo(26 + offset, 27)
            quote.quadTo(24 + offset, 38, 18 + offset, 41)
            quote.quadTo(28 + offset, 39, 32 + offset, 29)
            quote.closeSubpath()
            painter.drawPath(quote)

        # A seal stamp (印) in the bottom-right corner — the romantic 落印 touch.
        sr, sg, sb = theme.seal_rgb
        size = 36.0
        seal = QRectF(rect.right() - size - 16, rect.bottom() - size - 14, size, size)
        painter.setBrush(QColor(sr, sg, sb, 30))
        painter.setPen(QPen(QColor(sr, sg, sb, 165), 1.6))
        painter.drawRoundedRect(seal, 7, 7)
        painter.setPen(QColor(sr, sg, sb, 205))
        painter.setFont(_poetic_font(21, QFont.DemiBold))
        painter.drawText(seal, Qt.AlignCenter, theme.seal_char)
        painter.end()


class _SurpriseCheckBox(QCheckBox):
    """A tiny painter checkbox; avoids platform/theme indicator assets and always shows a tick."""

    def __init__(self, parent: QWidget | None = None, accent: str = "#C75C86") -> None:
        super().__init__(parent)
        self._accent = accent
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1.5, 1.5, 19, 19)
        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self._accent))
            painter.drawRoundedRect(rect, 6.5, 6.5)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 238), 2.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            tick = QPainterPath(QPointF(6.2, 11.0))
            tick.lineTo(9.5, 14.1)
            tick.lineTo(16.0, 7.7)
            painter.drawPath(tick)
        else:
            border = QColor(self._accent)
            border.setAlpha(120)
            painter.setBrush(QColor(255, 255, 255, 185))
            painter.setPen(QPen(border, 1.1))
            painter.drawRoundedRect(rect, 6.5, 6.5)
        painter.end()


def _make_button(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.PointingHandCursor)
    button.setFont(_ui_font(16, QFont.DemiBold if primary else QFont.Normal))
    button.setFixedHeight(44)
    button.setMinimumWidth(104)
    button.setObjectName("surprisePrimary" if primary else "surpriseQuiet")
    if primary:
        button.setStyleSheet(
            "QPushButton#surprisePrimary { color: white; background: #C75C86; border: none; border-radius: 13px; padding: 0 22px; }"
            "QPushButton#surprisePrimary:hover { background: #D56D96; }"
            "QPushButton#surprisePrimary:pressed { background: #B94E77; }"
        )
    else:
        button.setStyleSheet(
            "QPushButton#surpriseQuiet { color: #765261; background: rgba(255,255,255,125); border: none; border-radius: 13px; padding: 0 20px; }"
            "QPushButton#surpriseQuiet:hover { background: rgba(255,255,255,205); }"
            "QPushButton#surpriseQuiet:pressed { background: rgba(242,225,231,210); }"
        )
    return button


def _start_open_animation(dialog: QDialog, target: QPoint) -> None:
    previous = getattr(dialog, "_open_animation", None)
    if previous is not None:
        previous.stop()
        previous.deleteLater()
    dialog.setWindowOpacity(0.0)
    start = target + QPoint(0, 10)
    dialog.move(start)
    group = QParallelAnimationGroup(dialog)
    movement = QPropertyAnimation(dialog, b"pos", group)
    movement.setDuration(240)
    movement.setStartValue(start)
    movement.setEndValue(target)
    movement.setEasingCurve(QEasingCurve.OutCubic)
    opacity = QPropertyAnimation(dialog, b"windowOpacity", group)
    opacity.setDuration(190)
    opacity.setStartValue(0.0)
    opacity.setEndValue(1.0)
    opacity.setEasingCurve(QEasingCurve.OutCubic)
    dialog._open_animation = group
    group.finished.connect(lambda: _finish_open_animation(dialog, group))
    group.start()


def _finish_open_animation(dialog: QDialog, group: QParallelAnimationGroup) -> None:
    if getattr(dialog, "_open_animation", None) is group:
        dialog._open_animation = None
    dialog.setWindowOpacity(1.0)
    group.deleteLater()


def _start_close_animation(dialog: QDialog) -> None:
    """Fade + sink the dialog out, then hide it (symmetric to the open animation)."""
    previous = getattr(dialog, "_close_animation", None)
    if previous is not None:
        previous.stop()
        previous.deleteLater()
    start = dialog.pos()
    group = QParallelAnimationGroup(dialog)
    movement = QPropertyAnimation(dialog, b"pos", group)
    movement.setDuration(180)
    movement.setStartValue(start)
    movement.setEndValue(start + QPoint(0, 8))
    movement.setEasingCurve(QEasingCurve.InCubic)
    opacity = QPropertyAnimation(dialog, b"windowOpacity", group)
    opacity.setDuration(180)
    opacity.setStartValue(1.0)
    opacity.setEndValue(0.0)
    opacity.setEasingCurve(QEasingCurve.InCubic)
    dialog._close_animation = group
    group.finished.connect(lambda: _finish_close_animation(dialog, group))
    group.start()


def _finish_close_animation(dialog: QDialog, group: QParallelAnimationGroup) -> None:
    if getattr(dialog, "_close_animation", None) is group:
        dialog._close_animation = None
    dialog.hide()
    dialog.setWindowOpacity(1.0)
    group.deleteLater()


def _style_surprise_button(button: QPushButton, theme: NoteTheme) -> None:
    """Recolour a primary surprise button (objectName 'surprisePrimary') to the theme."""
    button.setStyleSheet(
        f"QPushButton#surprisePrimary {{ color: white; background: {theme.accent}; border: none; border-radius: 13px; padding: 0 22px; }}"
        f"QPushButton#surprisePrimary:hover {{ background: {theme.accent_hover}; }}"
        f"QPushButton#surprisePrimary:pressed {{ background: {theme.accent_pressed}; }}"
    )


class SurpriseActivationDialog(QDialog):
    def __init__(self, service: "SurpriseService", parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.service = service
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(640, 350)
        self.panel = _AtmospherePanel(self, "activation")
        self.panel.setGeometry(16, 12, self.width() - 32, self.height() - 30)
        add_soft_shadow(self.panel, blur=34, y=10, alpha=58)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(42, 32, 42, 30)
        layout.setSpacing(10)
        eyebrow = QLabel("A SMALL SECRET")
        eyebrow.setFont(_ui_font(11, QFont.DemiBold))
        eyebrow.setStyleSheet("color: #B98A9C; letter-spacing: 2px; background: transparent;")
        layout.addWidget(eyebrow)
        title = QLabel("有一件小事，想悄悄交给你")
        title.setFont(_ui_font(27, QFont.DemiBold))
        title.setStyleSheet(f"color: {SURPRISE_TEXT}; background: transparent;")
        layout.addWidget(title)
        hint = QLabel("输入口令后，这份心意只会留在当前 Windows 账户。")
        hint.setFont(_ui_font(14))
        hint.setStyleSheet(f"color: {SURPRISE_MUTED}; background: transparent;")
        layout.addWidget(hint)
        layout.addSpacing(8)
        self.input = QLineEdit()
        self.input.setEchoMode(QLineEdit.Password)
        self.input.setPlaceholderText("特别口令")
        self.input.setFont(_ui_font(17))
        self.input.setFixedHeight(52)
        self.input.setStyleSheet(
            "QLineEdit { color: #4A2334; background: rgba(255,255,255,205); border: none; border-radius: 15px; padding: 0 18px; selection-background-color: #E9A7C0; }"
            "QLineEdit:focus { background: rgba(255,255,255,238); }"
        )
        self.input.returnPressed.connect(self._activate)
        layout.addWidget(self.input)
        self.status = QLabel("")
        self.status.setFont(_ui_font(13))
        self.status.setFixedHeight(22)
        self.status.setStyleSheet("color: #B24B70; background: transparent;")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = _make_button("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        activate = _make_button("打开", primary=True)
        activate.clicked.connect(self._activate)
        buttons.addWidget(activate)
        layout.addLayout(buttons)
        self._open_animation: QParallelAnimationGroup | None = None

    def _activate(self) -> None:
        try:
            self.service.activate(self.input.text())
        except Exception:
            self.input.clear()
            self.status.setText("口令不正确，或者专属内容不可用。")
            return
        self.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        target = self.pos()
        _start_open_animation(self, target)
        self.panel.play_sparkles()
        QTimer.singleShot(160, self.input.setFocus)


class SurpriseNoteDialog(QDialog):
    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        theme = NOTE_THEMES[DEFAULT_NOTE_THEME]
        self.setFixedSize(840, 520)
        self.panel = _AtmospherePanel(self, "note", theme)
        self.panel.setGeometry(16, 12, self.width() - 32, self.height() - 30)
        add_soft_shadow(self.panel, blur=48, y=14, alpha=64)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(50, 38, 50, 34)
        layout.setSpacing(12)
        self.eyebrow = QLabel(theme.eyebrow_text)
        self.eyebrow.setFont(_ui_font(11, QFont.DemiBold))
        self.eyebrow.setStyleSheet(f"color: {theme.eyebrow}; letter-spacing: 2px; background: transparent;")
        layout.addWidget(self.eyebrow, 0, Qt.AlignHCenter)
        self.title = QLabel(theme.title_text)
        self.title.setFont(_poetic_font(38, QFont.DemiBold))
        self.title.setStyleSheet(f"color: {theme.text}; background: transparent;")
        layout.addWidget(self.title, 0, Qt.AlignHCenter)
        self.rule = QFrame()
        self.rule.setFixedSize(46, 2)
        self.rule.setStyleSheet("background: rgba(198,155,100,125); border: none; border-radius: 1px;")
        layout.addWidget(self.rule, 0, Qt.AlignHCenter)
        self.paper = _NotePaper(self.panel, theme)
        paper_layout = QVBoxLayout(self.paper)
        paper_layout.setContentsMargins(44, 34, 44, 32)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setFont(_poetic_font(30, QFont.Medium))
        self.note.setStyleSheet(f"color: {theme.text}; background: transparent;")
        self.note.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        paper_layout.addWidget(self.note, 1)
        layout.addWidget(self.paper, 1)
        self.close_btn = _make_button("收下", primary=True)
        _style_surprise_button(self.close_btn, theme)
        self.close_btn.clicked.connect(lambda: _start_close_animation(self))
        layout.addWidget(self.close_btn, 0, Qt.AlignRight)
        self._open_animation: QParallelAnimationGroup | None = None
        self._close_animation: QParallelAnimationGroup | None = None

    def show_note(self, text: str, anchor: QWidget | None = None, theme_key: str = DEFAULT_NOTE_THEME) -> None:
        theme = note_theme(theme_key)
        self.panel.theme = theme
        self.paper.theme = theme
        self.eyebrow.setText(theme.eyebrow_text)
        self.eyebrow.setStyleSheet(f"color: {theme.eyebrow}; letter-spacing: 2px; background: transparent;")
        self.title.setText(theme.title_text)
        self.title.setStyleSheet(f"color: {theme.text}; background: transparent;")
        self.note.setStyleSheet(f"color: {theme.text}; background: transparent;")
        _style_surprise_button(self.close_btn, theme)
        self.note.setText(text)
        self.panel.update()
        self.paper.update()
        screen = anchor.screen() if anchor is not None else None
        fallback = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else (
            fallback.availableGeometry() if fallback is not None else QRect(0, 0, 1920, 1080)
        )
        metrics = QFontMetrics(self.note.font())
        text_height = metrics.boundingRect(QRect(0, 0, 660, 1200), Qt.TextWordWrap, text).height()
        height = max(520, min(int(area.height() * 0.82), 400 + text_height))
        self.setFixedSize(min(840, int(area.width() * 0.82)), height)
        self.panel.setGeometry(16, 12, self.width() - 32, self.height() - 30)
        target = area.center() - QPoint(self.width() // 2, self.height() // 2)
        self.move(target)
        self.show()
        self.raise_()
        self.activateWindow()
        _start_open_animation(self, target)
        self.panel.play_sparkles()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        protect_window_from_capture(int(self.winId()))


class SurpriseTodoRow(QFrame):
    def __init__(self, service: "SurpriseService", parent: QWidget) -> None:
        super().__init__(parent)
        self.service = service
        theme = note_theme(service.app.state.settings.surpriseNoteTheme)
        completed = service.completed_today()
        self.setObjectName("surpriseTodoRow")
        self.setFixedHeight(94)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tr, tg, tb = theme.row_tint
        self.setStyleSheet(
            f"QFrame#surpriseTodoRow {{ background: rgba({tr},{tg},{tb},165);"
            " border: 1px solid rgba(198,155,100,46); border-radius: 15px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 10, 13, 10)
        layout.setSpacing(11)
        self.checkbox = _SurpriseCheckBox(accent=theme.accent)
        self.checkbox.setChecked(completed)
        self.checkbox.setEnabled(not completed)
        self.checkbox.stateChanged.connect(self._complete)
        layout.addWidget(self.checkbox, 0, Qt.AlignTop)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(5)
        text = service.payload["completedText"] if completed else service.payload["pendingText"]
        self.label = QLabel(text)
        self.label.setFont(_ui_font(17, QFont.DemiBold))
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"color: {theme.text}; background: transparent;")
        content.addWidget(self.label)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        ddl = QLabel(service.payload["deadlineText"])
        ddl.setFont(_ui_font(12))
        ddl.setStyleSheet(f"color: {theme.muted}; background: transparent;")
        meta_row.addWidget(ddl)
        meta_row.addStretch()
        self.draw = QPushButton(
            service.payload["reviewText"] if service.note_drawn_today() else service.payload["drawText"]
        )
        self.draw.setCursor(Qt.PointingHandCursor)
        self.draw.setFont(_ui_font(12, QFont.DemiBold))
        self.draw.setFixedHeight(28)
        self.draw.setStyleSheet(
            f"QPushButton {{ color: {theme.accent}; background: rgba(255,255,255,150); border: none; border-radius: 9px; padding: 0 11px; }}"
            f"QPushButton:hover {{ color: {theme.accent_pressed}; background: rgba(255,255,255,225); }}"
            "QPushButton:pressed { background: rgba(255,255,255,255); }"
        )
        self.draw.setVisible(completed)
        self.draw.clicked.connect(service.show_daily_note)
        meta_row.addWidget(self.draw)
        content.addLayout(meta_row)
        layout.addLayout(content, 1)

    def _complete(self, state: int) -> None:
        if state:
            self.service.complete_today()


class SurpriseService:
    def __init__(self, app) -> None:
        self.app = app
        self.payload: dict | None = None
        self.note_dialog = SurpriseNoteDialog()
        self._midnight_timer = QTimer()
        self._midnight_timer.setSingleShot(True)
        settings = app.state.settings
        if settings.surpriseEnabled and settings.surpriseKeyBlob:
            try:
                self.payload = decrypt_with_key(read_envelope(), unprotect_key(settings.surpriseKeyBlob))
            except Exception:
                settings.surpriseEnabled = False
                settings.surpriseKeyBlob = ""
                settings.surpriseCompletedDate = ""
                settings.surpriseNoteDate = ""
                settings.surpriseNoteIndex = -1
                if settings.preSurpriseWindowMode in {"normal", "edgeHide", "floatingLauncher"}:
                    settings.windowMode = settings.preSurpriseWindowMode
                settings.preSurpriseWindowMode = ""
                _restore_pre_surprise_skin(settings)
                app.save()

    @property
    def active(self) -> bool:
        return self.payload is not None and self.app.state.settings.surpriseEnabled

    def bind_ui(self) -> None:
        self._midnight_timer.timeout.connect(self._on_midnight)
        self._schedule_midnight()
        self.apply_theme()

    def stop(self) -> None:
        self._midnight_timer.stop()
        self.note_dialog.hide()

    def activate(self, passphrase: str) -> None:
        envelope = read_envelope()
        key = key_from_passphrase(passphrase, envelope)
        payload = decrypt_with_key(envelope, key)
        settings = self.app.state.settings
        settings.preSurpriseWindowMode = settings.windowMode
        settings.preSurpriseSkin = settings.skin
        settings.surpriseKeyBlob = protect_key(key)
        settings.surpriseEnabled = True
        settings.windowMode = "floatingLauncher"
        # Auto-switch to the swirl on activation; the user can still pick another skin afterwards.
        settings.skin = "surprise_swirl"
        self.payload = payload
        self.app.save()
        self.apply_theme()
        # Rebuild the settings UI so the (now valid) 灵动水墨 entry appears and is selected.
        self.app.settings_window.sync_from_state()
        self.app.floating.apply_mode()
        QTimer.singleShot(120, self.app.floating.expand_panel)

    def deactivate(self) -> None:
        settings = self.app.state.settings
        settings.surpriseEnabled = False
        settings.surpriseKeyBlob = ""
        settings.surpriseCompletedDate = ""
        settings.surpriseNoteDate = ""
        settings.surpriseNoteIndex = -1
        if settings.preSurpriseWindowMode in {"normal", "edgeHide", "floatingLauncher"}:
            settings.windowMode = settings.preSurpriseWindowMode
        settings.preSurpriseWindowMode = ""
        _restore_pre_surprise_skin(settings)
        self.payload = None
        self.app.save()
        self.apply_theme()
        self.app.settings_window.sync_from_state()
        self.app.settings_window.sync_surprise_state()
        self.app.floating.apply_mode()

    def show_activation_dialog(self, parent: QWidget) -> None:
        dialog = SurpriseActivationDialog(self, parent)
        dialog.move(parent.frameGeometry().center() - QPoint(dialog.width() // 2, dialog.height() // 2))
        dialog.exec()

    def make_row(self, parent: QWidget) -> SurpriseTodoRow | None:
        return SurpriseTodoRow(self, parent) if self.active else None

    def completed_today(self) -> bool:
        # >= (not ==) so winding the system clock backward can't re-open a day already completed;
        # an empty stored date sorts before any real date, so "not yet done" still reads False.
        return self.app.state.settings.surpriseCompletedDate >= date.today().isoformat()

    def note_drawn_today(self) -> bool:
        return self.app.state.settings.surpriseNoteDate >= date.today().isoformat()

    def complete_today(self) -> None:
        self.app.state.settings.surpriseCompletedDate = date.today().isoformat()
        self.app.save()
        self.app.window.refresh()
        self.app.floating.launcher.play_surprise_burst()

    def show_daily_note(self) -> None:
        if not self.active or not self.completed_today():
            return
        settings = self.app.state.settings
        notes = self.payload["notes"]
        if not notes:
            return
        # Re-roll when today's note isn't drawn yet, or when the stored index is out of range — e.g.
        # a later payload shipped fewer notes — so a stale index can never raise IndexError below.
        if not self.note_drawn_today() or not (0 <= settings.surpriseNoteIndex < len(notes)):
            count = len(notes)
            previous = settings.surpriseNoteIndex
            index = QRandomGenerator.global_().bounded(count)
            if count > 1 and index == previous:
                index = (index + 1 + QRandomGenerator.global_().bounded(count - 1)) % count
            settings.surpriseNoteIndex = index
            settings.surpriseNoteDate = date.today().isoformat()
            self.app.save()
            self.app.window.refresh()
        self.note_dialog.show_note(notes[settings.surpriseNoteIndex], self.app.window, settings.surpriseNoteTheme)

    def apply_theme(self) -> None:
        qt = QApplication.instance()
        if qt is not None:
            qt.setProperty("surpriseMode", self.active)
        setThemeColor(SURPRISE_ACCENT if self.active else NORMAL_ACCENT, save=False)
        floating = getattr(self.app, "floating", None)
        if floating is not None:
            floating.launcher.set_surprise_mode(self.active)
        # window / settings_window / history_window are all parent-less top-level widgets exposing
        # apply_surprise_theme, so this single sweep covers them — no separate named loop needed.
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, "apply_surprise_theme"):
                widget.apply_surprise_theme(self.active)

    def _schedule_midnight(self) -> None:
        now = datetime.now()
        tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        self._midnight_timer.start(max(1000, int((tomorrow - now).total_seconds() * 1000) + 1000))

    def _on_midnight(self) -> None:
        if self.active and hasattr(self.app, "window"):
            self.app.window.refresh()
        self._schedule_midnight()
