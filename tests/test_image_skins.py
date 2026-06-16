"""Image-skin feature gate: the custom-skin persistence/validation in state_store and the
crop-editor's pure geometry/IO helpers. Widget tests run headless (offscreen Qt)."""
from dataclasses import asdict

from state_store import AppState, CustomSkin


def test_customskin_roundtrips_through_state():
    state = AppState()
    state.settings.customSkins = [CustomSkin(id="abc", name="海边日落", file="abc.png")]
    state.settings.skin = "image:abc"
    restored = AppState.from_dict(asdict(state))
    assert restored.settings.skin == "image:abc"
    assert [s.id for s in restored.settings.customSkins] == ["abc"]
    assert restored.settings.customSkins[0].name == "海边日落"
    assert restored.settings.active_custom_skin().file == "abc.png"


def test_image_skin_pointing_at_missing_id_falls_back_to_acrylic():
    state = AppState()
    state.settings.skin = "image:does-not-exist"  # no matching CustomSkin
    restored = AppState.from_dict(asdict(state))
    assert restored.settings.skin == "acrylic"
    assert restored.settings.active_custom_skin() is None


def test_crop_export_matches_crop_aspect_and_writes_png(qapp, tmp_path):
    from PySide6.QtGui import QColor, QPixmap

    from skin_editor import CropCanvas, export_crop, mean_luminance

    source = QPixmap(400, 300)
    source.fill(QColor(255, 255, 255))
    canvas = CropCanvas(source, aspect=2.0)

    region = canvas.export_region()
    assert not region.isNull()
    assert abs(region.width() / region.height() - 2.0) < 0.2  # honors the crop rect aspect

    dst = tmp_path / "skin.png"
    assert export_crop(canvas, dst)
    assert dst.exists() and dst.stat().st_size > 0
    assert mean_luminance(source) > 0.9  # an all-white image reads as bright -> dark text


def test_crop_dialog_builds_headless(qapp):
    from PySide6.QtGui import QColor, QPixmap

    from skin_editor import CropDialog

    source = QPixmap(640, 480)
    source.fill(QColor(10, 20, 30))
    dialog = CropDialog(source, aspect=1.5)
    assert dialog.canvas is not None
    assert dialog.skin_name == ""
    # Empty name must not accept (keeps the dialog open instead of saving an unnamed skin).
    dialog._on_save()
    assert dialog.skin_name == ""
