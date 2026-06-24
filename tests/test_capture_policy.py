"""Screen-capture opt-out policy (Settings.allowScreenshot) coverage."""
from dataclasses import asdict

import window_layer
from state_store import AppState


def test_allow_screenshot_roundtrips_and_normalizes():
    payload = asdict(AppState())
    payload["settings"]["allowScreenshot"] = 1  # truthy non-bool

    restored = AppState.from_dict(payload)

    assert restored.settings.allowScreenshot is True
    # Default keeps the historical "hidden from capture" behavior.
    assert AppState.from_dict(asdict(AppState())).settings.allowScreenshot is False


def test_protect_window_follows_capture_policy(monkeypatch):
    calls = []
    monkeypatch.setattr(
        window_layer, "set_window_exclude_from_capture",
        lambda hwnd, exclude=True: calls.append(exclude) or True,
    )
    try:
        window_layer.set_capture_exclusion(True)   # allowScreenshot == False
        window_layer.protect_window_from_capture(1234)
        window_layer.set_capture_exclusion(False)  # allowScreenshot == True
        window_layer.protect_window_from_capture(1234)
    finally:
        window_layer.set_capture_exclusion(True)   # restore default for other tests

    assert calls == [True, False]
