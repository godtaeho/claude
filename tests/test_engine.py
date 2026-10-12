import threading

import pymupdf
import pytest
from PIL import Image

from easyprint.documents import Document, UnsupportedFile
from easyprint.engine import ImageDevice, print_files
from easyprint.presets import Preset


@pytest.fixture
def pdf3(tmp_path):
    """A4 세로 2쪽 + A4 가로 1쪽, 각 페이지에 빨간 사각형"""
    path = tmp_path / "문서.pdf"
    doc = pymupdf.open()
    for w, h in [(595, 842), (595, 842), (842, 595)]:
        page = doc.new_page(width=w, height=h)
        page.draw_rect(pymupdf.Rect(0, 0, w, h), color=(1, 0, 0), fill=(1, 0, 0))
    doc.save(path)
    return str(path)


def test_pdf_pages(pdf3):
    with Document(pdf3) as d:
        assert len(d.pages) == 3
        assert d.pages[2].width_pt > d.pages[2].height_pt
        img = d.pages[0].render(72)
        assert img.size == (595, 842) and img.getpixel((10, 10)) == (255, 0, 0)


def test_image_pages_with_alpha_and_dpi(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGBA", (300, 150), (0, 0, 0, 0)).save(path, dpi=(150, 150))
    with Document(path) as d:
        (p,) = d.pages
        assert round(p.width_pt) == 144 and round(p.height_pt) == 72  # 2인치 x 1인치
        img = p.render(150)
        assert img.mode == "RGB" and img.getpixel((0, 0)) == (255, 255, 255)


def test_multiframe_tiff(tmp_path):
    path = tmp_path / "scan.tif"
    frames = [Image.new("L", (100, 140), c) for c in (0, 128, 255)]
    frames[0].save(path, save_all=True, append_images=frames[1:])
    with Document(path) as d:
        assert len(d.pages) == 3


def test_unsupported(tmp_path):
    p = tmp_path / "a.xyz"
    p.write_text("x")
    with pytest.raises(UnsupportedFile):
        Document(p).__enter__()
    with pytest.raises(UnsupportedFile):
        Document(tmp_path / "없음.pdf").__enter__()


def test_print_fills_paper_and_rotates(pdf3):
    dev = ImageDevice(210, 297, dpi=50)
    res = print_files(dev, [pdf3], Preset(name="t", copies=1))
    assert res.pages == 3 and not res.failed
    title, pages = dev.docs[0]
    assert title == "문서.pdf"
    for img in pages:
        # 가로 페이지도 회전되어 용지 중앙이 빨간색, 여백(가장자리)은 흰색
        cx, cy = img.width // 2, img.height // 2
        assert img.getpixel((cx, cy)) == (255, 0, 0)
        assert img.getpixel((1, 1)) == (255, 255, 255)
        assert img.getpixel((cx, 15)) == (255, 0, 0)  # 맞춤 인쇄라 위쪽 근처까지 채워짐


def test_copies_and_duplex_padding(pdf3):
    dev = ImageDevice(210, 297, dpi=20)
    res = print_files(dev, [pdf3], Preset(name="t", copies=2, duplex=2))
    assert res.pages == 6
    assert len(dev.docs[0][1]) == 7  # 1부(3쪽) + 빈 뒷면 1 + 2부(3쪽)


def test_bad_file_does_not_stop_others(pdf3, tmp_path):
    bad = tmp_path / "깨짐.pdf"
    bad.write_bytes(b"not a pdf")
    dev = ImageDevice(210, 297, dpi=20)
    res = print_files(dev, [str(bad), pdf3], Preset(name="t"))
    assert len(res.failed) == 1 and res.printed_files == [pdf3]
    assert len(dev.docs) == 1


def test_cancel(pdf3):
    ev = threading.Event()
    dev = ImageDevice(210, 297, dpi=20)
    seen = []

    def progress(msg):
        seen.append(msg)
        if "2/3쪽" in msg:
            ev.set()

    res = print_files(dev, [pdf3, pdf3], Preset(name="t"), progress=progress, cancel=ev)
    assert res.cancelled and dev.docs == []  # 진행 중 문서는 AbortDoc
