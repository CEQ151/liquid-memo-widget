"""Large-dialog sizing remains generous without placing controls off-screen."""
from PySide6.QtCore import QRect

from ui_common import scaled_dialog_size


def test_large_screen_gets_full_one_and_a_half_scale():
    area = QRect(0, 0, 2560, 1600)

    assert scaled_dialog_size(1120, 860, available=area).toTuple() == (1680, 1290)
    assert scaled_dialog_size(620, 620, available=area).toTuple() == (930, 930)


def test_dialogs_are_capped_to_small_work_area():
    area = QRect(0, 0, 1463, 866)
    size = scaled_dialog_size(1120, 860, available=area)

    assert size.width() <= int(area.width() * 0.98)
    assert size.height() <= int(area.height() * 0.98)
    assert size.width() > 1120  # still materially wider than the former fixed settings window
