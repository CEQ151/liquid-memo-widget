"""Authenticated surprise payload and Windows key sealing tests."""
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidTag
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QWidget

from surprise_crypto import (
    decrypt_with_key,
    encrypt_payload,
    key_from_passphrase,
    protect_key,
    unprotect_key,
)
from state_store import AppState, TodoItem
from surprise_mode import SurpriseActivationDialog, SurpriseNoteDialog, SurpriseService, SurpriseTodoRow


def _payload():
    return {
        "pendingText": "pending",
        "completedText": "completed",
        "deadlineText": "never",
        "drawText": "draw",
        "reviewText": "review",
        "notes": ["note-a", "note-b"],
    }


def test_payload_encrypts_and_authenticates():
    encrypted = encrypt_payload(_payload(), "correct horse battery staple")
    envelope = json.loads(encrypted)
    key = key_from_passphrase("correct horse battery staple", envelope)

    assert decrypt_with_key(envelope, key) == _payload()
    assert b"note-a" not in encrypted


def test_wrong_passphrase_cannot_decrypt():
    envelope = json.loads(encrypt_payload(_payload(), "correct horse battery staple"))
    wrong_key = key_from_passphrase("this is definitely the wrong password", envelope)

    with pytest.raises(InvalidTag):
        decrypt_with_key(envelope, wrong_key)


def test_dpapi_roundtrip_for_current_windows_user():
    key = bytes(range(32))

    assert unprotect_key(protect_key(key)) == key


def test_surprise_state_roundtrips_and_normalizes_index():
    payload = asdict(AppState())
    payload["settings"].update(
        surpriseEnabled=True,
        surpriseKeyBlob="sealed-key",
        preSurpriseWindowMode="normal",
        surpriseCompletedDate="2099-01-01",
        surpriseNoteDate="2099-01-01",
        surpriseNoteIndex="4",
    )

    restored = AppState.from_dict(payload)

    assert restored.version == 6
    assert restored.settings.surpriseEnabled is True
    assert restored.settings.surpriseKeyBlob == "sealed-key"
    assert restored.settings.preSurpriseWindowMode == "normal"
    assert restored.settings.surpriseNoteIndex == 4


def test_swirl_fallback_set_theme_recolours_in_place(qapp):
    from surprise_swirl import SwirlPainterFallback, swirl_tokens

    bg = SwirlPainterFallback(tokens=swirl_tokens("qinghua"))
    assert bg.tokens is swirl_tokens("qinghua")

    bg.set_theme("warm")  # in-place recolour, no widget rebuild
    assert bg.tokens is swirl_tokens("warm")
    assert bg.tokens.text_overlay_safe == "#3A2A22"

    bg.cleanup()


def test_surprise_swirl_skin_persists_only_with_marker():
    payload = asdict(AppState())
    payload["settings"].update(skin="surprise_swirl", preSurpriseSkin="acrylic")

    restored = AppState.from_dict(payload)

    # "surprise_swirl" is a valid stored skin (so an active session survives a restart) and the
    # pre-activation skin marker round-trips.
    assert restored.settings.skin == "surprise_swirl"
    assert restored.settings.preSurpriseSkin == "acrylic"


def test_unknown_skin_falls_back_to_acrylic():
    payload = asdict(AppState())
    payload["settings"].update(skin="glass")  # removed skin

    assert AppState.from_dict(payload).settings.skin == "acrylic"


def test_activation_daily_completion_and_restore_do_not_touch_user_todos(qapp, monkeypatch):
    import surprise_mode as surprise_module

    envelope = json.loads(encrypt_payload(_payload(), "generic integration passphrase"))
    state = AppState()
    state.settings.windowMode = "normal"
    state.todos = [TodoItem(id="regular", text="regular todo")]
    window = QWidget()
    window.refresh_calls = 0
    window.refresh = lambda: setattr(window, "refresh_calls", window.refresh_calls + 1)
    launcher = SimpleNamespace(bursts=0)
    launcher.set_surprise_mode = lambda _active: None
    launcher.play_surprise_burst = lambda: setattr(launcher, "bursts", launcher.bursts + 1)
    floating = SimpleNamespace(apply_calls=0, expand_calls=0, launcher=launcher)
    floating.apply_mode = lambda: setattr(floating, "apply_calls", floating.apply_calls + 1)
    floating.expand_panel = lambda: setattr(floating, "expand_calls", floating.expand_calls + 1)
    settings_window = QWidget()
    settings_window.sync_calls = 0
    settings_window.sync_surprise_state = lambda: setattr(
        settings_window, "sync_calls", settings_window.sync_calls + 1
    )
    settings_window.sync_from_state = lambda: None
    app = SimpleNamespace(
        state=state,
        window=window,
        settings_window=settings_window,
        history_window=QWidget(),
        floating=floating,
        saves=0,
    )
    app.save = lambda: setattr(app, "saves", app.saves + 1)
    monkeypatch.setattr(surprise_module, "read_envelope", lambda: envelope)
    monkeypatch.setattr(surprise_module, "protect_key", lambda _key: "sealed-key")
    monkeypatch.setattr(surprise_module.QTimer, "singleShot", lambda _delay, callback: callback())

    service = SurpriseService(app)
    app.surprise = service
    service.activate("generic integration passphrase")

    assert service.active
    assert state.settings.windowMode == "floatingLauncher"
    assert state.settings.preSurpriseWindowMode == "normal"
    assert state.settings.surpriseKeyBlob == "sealed-key"
    # Activation auto-switches to the swirl skin and remembers the prior one.
    assert state.settings.skin == "surprise_swirl"
    assert state.settings.preSurpriseSkin == "acrylic"
    assert floating.apply_calls == 1
    assert floating.expand_calls == 1

    service.complete_today()
    assert service.completed_today()
    assert launcher.bursts == 1
    assert [(todo.id, todo.done) for todo in state.todos] == [("regular", False)]
    assert state.history == []

    shown = []
    service.note_dialog.show_note = lambda text, _anchor, _theme: shown.append(text)
    service.show_daily_note()
    first_index = state.settings.surpriseNoteIndex
    service.show_daily_note()
    assert service.note_drawn_today()
    assert state.settings.surpriseNoteIndex == first_index
    assert shown == [_payload()["notes"][first_index]] * 2

    service.deactivate()
    assert not service.active
    assert state.settings.windowMode == "normal"
    assert state.settings.surpriseKeyBlob == ""
    # Deactivation restores the pre-activation skin and clears the marker.
    assert state.settings.skin == "acrylic"
    assert state.settings.preSurpriseSkin == ""
    assert [(todo.id, todo.done) for todo in state.todos] == [("regular", False)]

    service.note_dialog.close()
    window.close()
    settings_window.close()
    app.history_window.close()


def test_surprise_row_stays_inside_compact_memo_width(qapp):
    service = SimpleNamespace(
        payload=_payload(),
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(surpriseNoteTheme="qinghua"))),
        completed_today=lambda: True,
        note_drawn_today=lambda: False,
        show_daily_note=lambda: None,
        complete_today=lambda: None,
    )
    host = QWidget()
    host.resize(400, 94)
    row = SurpriseTodoRow(service, host)
    row.resize(host.size())
    host.show()
    qapp.processEvents()

    assert row.height() == 94
    assert row.label.font().pixelSize() == 17
    assert row.draw.geometry().right() <= row.contentsRect().right()

    host.close()


def test_surprise_mode_reserves_a_readable_memo_width(qapp):
    from app import MemoWindow, SURPRISE_MIN_WIDTH

    memo = SimpleNamespace(app=SimpleNamespace(surprise=SimpleNamespace(active=True)))

    assert MemoWindow._adaptive_width(memo, [], [], QRect(0, 0, 1920, 1080)) == SURPRISE_MIN_WIDTH


def test_surprise_dialogs_use_single_painted_surface_and_dynamic_note_height(qapp):
    activation = SurpriseActivationDialog(SimpleNamespace(activate=lambda _value: None))
    note = SurpriseNoteDialog()

    assert activation.panel.styleSheet() == ""
    note.show_note("A remembered moment, written slowly enough to keep.")
    qapp.processEvents()
    assert note.height() >= 520
    assert note.panel.styleSheet() == ""

    activation.close()
    note.close()
