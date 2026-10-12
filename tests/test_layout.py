import pytest

from easyprint.layout import DeviceMetrics, place

A4_PT = (595.28, 841.89)
# 600dpi A4 세로, 여백 4.23mm(100px)
A4_DEV = DeviceMetrics(4760, 6814, 4960, 7014, 100, 100, 600, 600)
A4_LAND_DEV = DeviceMetrics(6814, 4760, 7014, 4960, 100, 100, 600, 600)


def test_fit_keeps_aspect_and_centers():
    pl = place(*A4_PT, A4_DEV, "fit", True)
    assert not pl.rotate
    w, h = pl.right - pl.left, pl.bottom - pl.top
    assert w <= A4_DEV.printable_w and h <= A4_DEV.printable_h
    assert abs(w / h - A4_PT[0] / A4_PT[1]) < 0.002
    assert abs(pl.left - (A4_DEV.printable_w - pl.right)) <= 1
    assert abs(pl.top - (A4_DEV.printable_h - pl.bottom)) <= 1


def test_actual_size_is_true_scale_centered_on_paper():
    pl = place(*A4_PT, A4_DEV, "actual", True)
    assert abs((pl.right - pl.left) - 4960) <= 1  # 210mm @600dpi
    assert abs(pl.left + 100) <= 1 and abs(pl.top + 100) <= 1  # 용지 가장자리 = 인쇄영역 원점 - 오프셋


def test_auto_rotate_portrait_page_on_landscape_paper():
    pl = place(*A4_PT, A4_LAND_DEV, "fit", True)
    assert pl.rotate
    assert pl.right - pl.left > pl.bottom - pl.top
    assert not place(*A4_PT, A4_LAND_DEV, "fit", False).rotate


def test_envelope_document_on_dl_landscape():
    # 220x110mm 문서를 DL 가로 용지에
    w_pt, h_pt = 220 / 25.4 * 72, 110 / 25.4 * 72
    dev = DeviceMetrics(5000, 2400, 5197, 2598, 98, 99, 600, 600)
    pl = place(w_pt, h_pt, dev, "fit", True)
    assert not pl.rotate and pl.right - pl.left <= 5000


def test_anisotropic_dpi():
    dev = DeviceMetrics(2400, 6000, 2480, 7016, 40, 508, 300, 600)
    pl = place(*A4_PT, dev, "fit", False)
    w_in = (pl.right - pl.left) / 300
    h_in = (pl.bottom - pl.top) / 600
    assert abs(w_in / h_in - A4_PT[0] / A4_PT[1]) < 0.003


def test_bad_input():
    with pytest.raises(ValueError):
        place(0, 10, A4_DEV, "fit", True)
    with pytest.raises(ValueError):
        place(10, 10, A4_DEV, "zoom", True)
