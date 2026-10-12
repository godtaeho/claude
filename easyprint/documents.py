"""출력할 파일을 페이지 이미지로 바꾼다.

- PDF: PyMuPDF 로 렌더링
- 이미지: Pillow 로 읽기 (여러 프레임 TIFF/GIF 포함)
- 워드/엑셀/파워포인트/한글: 설치된 프로그램(COM 자동화)으로 임시 PDF 변환 후 출력
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pymupdf
from PIL import Image, ImageSequence

PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
WORD_EXT = {".doc", ".docx", ".rtf", ".odt"}
EXCEL_EXT = {".xls", ".xlsx", ".xlsm", ".csv"}
PPT_EXT = {".ppt", ".pptx"}
HWP_EXT = {".hwp", ".hwpx"}
OFFICE_EXT = WORD_EXT | EXCEL_EXT | PPT_EXT | HWP_EXT
SUPPORTED_EXT = PDF_EXT | IMAGE_EXT | OFFICE_EXT

FILE_DIALOG_TYPES = [
    ("출력 가능한 파일", " ".join(f"*{e}" for e in sorted(SUPPORTED_EXT))),
    ("PDF", "*.pdf"),
    ("이미지", " ".join(f"*{e}" for e in sorted(IMAGE_EXT))),
    ("한글", "*.hwp *.hwpx"),
    ("Office 문서", " ".join(f"*{e}" for e in sorted(WORD_EXT | EXCEL_EXT | PPT_EXT))),
    ("모든 파일", "*.*"),
]

MAX_RENDER_DPI = 300


class UnsupportedFile(Exception):
    pass


@dataclass
class Page:
    width_pt: float
    height_pt: float
    render: Callable[[float], Image.Image]  # 목표 DPI → RGB 또는 L 이미지


def is_supported(path: str | os.PathLike) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXT


def _flatten(img: Image.Image) -> Image.Image:
    """투명 배경은 흰색으로 합치고, GDI 로 그릴 수 있는 RGB/L 로 맞춘다."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    if img.mode in ("RGB", "L"):
        return img
    if img.mode == "1":
        return img.convert("L")
    return img.convert("RGB")


class Document:
    """출력할 파일 하나. with 문으로 열고, pages 를 여러 번(매수만큼) 순회할 수 있다."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.pages: list[Page] = []
        self._pdf = None
        self._tmp: str | None = None

    def __enter__(self) -> "Document":
        try:
            self._open()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _open(self) -> None:
        p = self.path
        if not p.exists():
            raise UnsupportedFile(f"파일이 없습니다: {p}")
        ext = p.suffix.lower()
        if ext in PDF_EXT:
            self._open_pdf(p)
        elif ext in IMAGE_EXT:
            self._open_image(p)
        elif ext in OFFICE_EXT:
            self._tmp = tempfile.mkdtemp(prefix="easyprint_")
            self._open_pdf(convert_to_pdf(p, Path(self._tmp)))
        else:
            raise UnsupportedFile(f"지원하지 않는 파일 형식입니다: {ext or '(확장자 없음)'}")
        if not self.pages:
            raise UnsupportedFile(f"출력할 페이지가 없습니다: {p.name}")

    def _open_pdf(self, path: Path) -> None:
        try:
            doc = pymupdf.open(path)
        except Exception as e:
            raise UnsupportedFile(f"PDF를 열 수 없습니다: {path.name} ({e})") from e
        self._pdf = doc
        if doc.needs_pass:
            raise UnsupportedFile("암호가 걸린 PDF는 출력할 수 없습니다")
        for page in doc:
            rect = page.rect  # 페이지 회전이 반영된 표시 크기 (pt)

            def render(dpi: float, page=page) -> Image.Image:
                pix = page.get_pixmap(dpi=max(72, int(min(dpi, MAX_RENDER_DPI))), alpha=False)
                return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            self.pages.append(Page(rect.width, rect.height, render))

    def _open_image(self, path: Path) -> None:
        try:
            im = Image.open(path)
        except Exception as e:
            raise UnsupportedFile(f"이미지를 열 수 없습니다: {path.name} ({e})") from e
        with im:
            for frame in ImageSequence.Iterator(im):
                frame = _flatten(frame.copy())
                dpi = frame.info.get("dpi") or im.info.get("dpi") or (96, 96)
                try:
                    dx, dy = float(dpi[0]) or 96.0, float(dpi[1]) or 96.0
                except (TypeError, ValueError, IndexError):
                    dx = dy = 96.0
                self.pages.append(Page(frame.width / dx * 72, frame.height / dy * 72,
                                       lambda _dpi, f=frame: f))

    def close(self) -> None:
        self.pages = []
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None


# ---------------------------------------------------------------- 문서 변환 (Windows 전용)

def convert_to_pdf(src: Path, out_dir: Path) -> Path:
    if sys.platform != "win32":
        raise UnsupportedFile("오피스/한글 문서 변환은 Windows 에서만 가능합니다")
    import pythoncom
    import win32com.client

    src = src.resolve()
    out = (out_dir / (src.stem + ".pdf")).resolve()
    ext = src.suffix.lower()
    pythoncom.CoInitialize()
    try:
        if ext in WORD_EXT:
            _word_to_pdf(win32com.client, src, out)
        elif ext in EXCEL_EXT:
            _excel_to_pdf(win32com.client, src, out)
        elif ext in PPT_EXT:
            _ppt_to_pdf(win32com.client, src, out)
        elif ext in HWP_EXT:
            _hwp_to_pdf(win32com.client, src, out)
    finally:
        pythoncom.CoUninitialize()
    if not out.exists():
        raise UnsupportedFile(f"PDF 변환에 실패했습니다: {src.name}")
    return out


def _dispatch(client, progid: str, program: str):
    try:
        return client.DispatchEx(progid)
    except Exception as e:  # pywintypes.com_error
        raise UnsupportedFile(f"{program}이(가) 설치되어 있지 않거나 실행할 수 없습니다") from e


def _word_to_pdf(client, src: Path, out: Path) -> None:
    app = _dispatch(client, "Word.Application", "Microsoft Word")
    try:
        app.Visible = False
        app.DisplayAlerts = 0
        doc = app.Documents.Open(str(src), ConfirmConversions=False, ReadOnly=True,
                                 AddToRecentFiles=False, Visible=False)
        try:
            doc.ExportAsFixedFormat(str(out), 17)  # wdExportFormatPDF
        finally:
            doc.Close(False)
    finally:
        app.Quit()


def _excel_to_pdf(client, src: Path, out: Path) -> None:
    app = _dispatch(client, "Excel.Application", "Microsoft Excel")
    try:
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True, AddToMru=False)
        try:
            wb.ExportAsFixedFormat(0, str(out))  # xlTypePDF
        finally:
            wb.Close(False)
    finally:
        app.Quit()


def _ppt_to_pdf(client, src: Path, out: Path) -> None:
    app = _dispatch(client, "PowerPoint.Application", "Microsoft PowerPoint")
    try:
        pres = app.Presentations.Open(str(src), ReadOnly=True, Untitled=False, WithWindow=False)
        try:
            pres.SaveAs(str(out), 32)  # ppSaveAsPDF
        finally:
            pres.Close()
    finally:
        app.Quit()


def _hwp_to_pdf(client, src: Path, out: Path) -> None:
    hwp = _dispatch(client, "HWPFrame.HwpObject", "한컴오피스 한글")
    try:
        try:
            # 보안 모듈이 등록돼 있으면 '파일 접근 허용' 팝업이 생략된다 (없으면 팝업에서 '허용' 선택)
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass
        if not hwp.Open(str(src), "", "forceopen:true;suspendpassword:true;versionwarning:false"):
            raise UnsupportedFile(f"한글 문서를 열지 못했습니다: {src.name}")
        hwp.SaveAs(str(out), "PDF", "")
    finally:
        try:
            hwp.Clear(1)
        except Exception:
            pass
        hwp.Quit()
