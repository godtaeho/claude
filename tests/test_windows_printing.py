"""실제 Windows 인쇄 경로 검증 ('Microsoft Print to PDF' 로 출력 후 결과 PDF 확인). Windows 에서만 실행."""
import sys

import pymupdf
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")

PDF_PRINTER = "Microsoft Print to PDF"


@pytest.fixture(scope="module")
def wp():
    from easyprint import winprint
    if PDF_PRINTER not in winprint.list_printers():
        pytest.skip(f"'{PDF_PRINTER}' 프린터가 없음")
    return winprint


@pytest.fixture
def src_pdf(tmp_path):
    path = tmp_path / "원본.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 세로
    page.draw_rect(pymupdf.Rect(50, 50, 545, 792), color=(1, 0, 0), fill=(1, 0, 0))
    doc.save(path)
    return str(path)


def _user_defaults(wp):
    with wp._Printer(PDF_PRINTER) as p:
        dm = wp.DEVMODEW.from_buffer_copy(p.user_devmode()[:220])
    return dm.dmPaperSize, dm.dmOrientation


def test_capabilities(wp):
    caps = wp.get_capabilities(PDF_PRINTER)
    ids = {p.id for p in caps.papers}
    assert 9 in ids and 8 in ids, caps.papers  # A4, A3
    a3 = next(p for p in caps.papers if p.id == 8)
    assert round(a3.width_mm) == 297 and round(a3.height_mm) == 420


@pytest.mark.parametrize("paper_id,orient,expect_mm", [
    (8, 2, (420, 297)),   # A3 가로
    (9, 1, (210, 297)),   # A4 세로
    (27, 2, (220, 110)),  # 봉투 DL 가로
])
def test_print_uses_preset_not_printer_defaults(wp, src_pdf, tmp_path, paper_id, orient, expect_mm):
    from easyprint.engine import print_files
    from easyprint.presets import Preset

    caps = wp.get_capabilities(PDF_PRINTER)
    if paper_id not in {p.id for p in caps.papers}:
        pytest.skip(f"용지 {paper_id} 미지원")
    before = _user_defaults(wp)
    out = tmp_path / "결과.pdf"
    preset = Preset(name="t", printer=PDF_PRINTER, paper_id=paper_id, orientation=orient)
    dev = wp.WinPrinterDevice(PDF_PRINTER, preset, output_file=str(out))
    try:
        res = print_files(dev, [src_pdf], preset)
    finally:
        dev.close()
    assert not res.failed and res.pages == 1, res
    assert dev.warnings == []

    with pymupdf.open(out) as doc:
        r = doc[0].rect
        w_mm, h_mm = r.width / 72 * 25.4, r.height / 72 * 25.4
    assert abs(w_mm - expect_mm[0]) < 3 and abs(h_mm - expect_mm[1]) < 3, (w_mm, h_mm)
    # 프린터 기본 설정은 그대로여야 함
    assert _user_defaults(wp) == before


def test_custom_envelope_115x216(wp, src_pdf, tmp_path):
    """사무실 봉투 설정(115x216 세로). 드라이버가 사용자 지정 크기를 거부하면 경고로 알려야 한다."""
    from easyprint.engine import print_files
    from easyprint.presets import default_presets

    env = next(p for p in default_presets() if p.name == "편지봉투")
    preset = type(env)(**{**env.to_dict(), "printer": PDF_PRINTER, "bin_id": 0, "bin_name": ""})
    out = tmp_path / "봉투.pdf"
    before = _user_defaults(wp)
    dev = wp.WinPrinterDevice(PDF_PRINTER, preset, output_file=str(out))
    try:
        res = print_files(dev, [src_pdf], preset)
    finally:
        dev.close()
    assert not res.failed and res.pages == 1
    with pymupdf.open(out) as doc:
        r = doc[0].rect
        size = (round(r.width / 72 * 25.4), round(r.height / 72 * 25.4))
    print("custom 115x216 ->", size, dev.warnings)
    if dev.warnings:
        pytest.xfail(f"이 드라이버는 사용자 지정 크기를 지원하지 않음: {dev.warnings} / 결과 {size}")
    assert abs(size[0] - 115) <= 2 and abs(size[1] - 216) <= 2, size
    assert _user_defaults(wp) == before
