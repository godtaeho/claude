"""Windows 프린터 제어 (ctypes 로 Win32 API 직접 호출).

핵심: 프린터의 '기본 설정'은 절대 건드리지 않는다.
  1) DocumentProperties 로 현재 사용자 기본 DEVMODE 를 '복사'해 오고
  2) 복사본의 용지/방향/컬러/급지함/양면만 바꾼 뒤 드라이버에 검증(merge)시키고
  3) 그 DEVMODE 로 CreateDC 를 만들어 이번 작업에만 사용한다.
SetPrinter / SetDefaultPrinter 는 호출하지 않으므로 다른 프로그램 인쇄 설정에 영향이 없다.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from PIL import Image

from .caps import PaperInfo, PrinterCaps
from .layout import DeviceMetrics, Placement
from .presets import DMBIN_AUTO, DMPAPER_USER, DUPLEX_SIMPLEX, Preset

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("winprint 모듈은 Windows 전용입니다")

from PIL import ImageWin  # noqa: E402  (Windows 에서만 존재)

winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# ---- 상수 (wingdi.h / winspool.h)
DM_ORIENTATION = 0x00000001
DM_PAPERSIZE = 0x00000002
DM_PAPERLENGTH = 0x00000004
DM_PAPERWIDTH = 0x00000008
DM_COPIES = 0x00000100
DM_DEFAULTSOURCE = 0x00000200
DM_COLOR = 0x00000800
DM_DUPLEX = 0x00001000
DM_COLLATE = 0x00008000
DM_FORMNAME = 0x00010000

DM_OUT_BUFFER = 2
DM_IN_BUFFER = 8

DC_PAPERS = 2
DC_PAPERSIZE = 3
DC_BINS = 6
DC_DUPLEX = 7
DC_BINNAMES = 12
DC_PAPERNAMES = 16
DC_COLORDEVICE = 32

HORZRES = 8
VERTRES = 10
LOGPIXELSX = 88
LOGPIXELSY = 90
PHYSICALWIDTH = 110
PHYSICALHEIGHT = 111
PHYSICALOFFSETX = 112
PHYSICALOFFSETY = 113

HALFTONE = 4

PRINTER_ENUM_LOCAL = 0x00000002
PRINTER_ENUM_CONNECTIONS = 0x00000004


class DEVMODEW(ctypes.Structure):
    """프린터용 DEVMODEW (공개 부분 220 바이트). 뒤에 dmDriverExtra 만큼 드라이버 전용 데이터가 붙는다."""
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmOrientation", ctypes.c_short),
        ("dmPaperSize", ctypes.c_short),
        ("dmPaperLength", ctypes.c_short),
        ("dmPaperWidth", ctypes.c_short),
        ("dmScale", ctypes.c_short),
        ("dmCopies", ctypes.c_short),
        ("dmDefaultSource", ctypes.c_short),
        ("dmPrintQuality", ctypes.c_short),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmNup", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


assert ctypes.sizeof(DEVMODEW) == 220


class DOCINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_int),
        ("lpszDocName", wintypes.LPCWSTR),
        ("lpszOutput", wintypes.LPCWSTR),
        ("lpszDatatype", wintypes.LPCWSTR),
        ("fwType", wintypes.DWORD),
    ]


class PRINTER_INFO_4W(ctypes.Structure):
    _fields_ = [
        ("pPrinterName", wintypes.LPWSTR),
        ("pServerName", wintypes.LPWSTR),
        ("Attributes", wintypes.DWORD),
    ]


class PRINTER_INFO_5W(ctypes.Structure):
    _fields_ = [
        ("pPrinterName", wintypes.LPWSTR),
        ("pPortName", wintypes.LPWSTR),
        ("Attributes", wintypes.DWORD),
        ("DeviceNotSelectedTimeout", wintypes.DWORD),
        ("TransmissionRetryTimeout", wintypes.DWORD),
    ]


# ---- 함수 시그니처
winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
winspool.OpenPrinterW.restype = wintypes.BOOL
winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
winspool.ClosePrinter.restype = wintypes.BOOL
winspool.DocumentPropertiesW.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR,
                                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
winspool.DocumentPropertiesW.restype = wintypes.LONG
winspool.DeviceCapabilitiesW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.WORD,
                                         ctypes.c_void_p, ctypes.c_void_p]
winspool.DeviceCapabilitiesW.restype = ctypes.c_int
winspool.GetDefaultPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
winspool.GetDefaultPrinterW.restype = wintypes.BOOL
winspool.EnumPrintersW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
winspool.EnumPrintersW.restype = wintypes.BOOL
winspool.GetPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD)]
winspool.GetPrinterW.restype = wintypes.BOOL

gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
gdi32.CreateDCW.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.GetDeviceCaps.restype = ctypes.c_int
gdi32.StartDocW.argtypes = [wintypes.HDC, ctypes.POINTER(DOCINFOW)]
gdi32.StartDocW.restype = ctypes.c_int
gdi32.EndDoc.argtypes = [wintypes.HDC]
gdi32.EndDoc.restype = ctypes.c_int
gdi32.AbortDoc.argtypes = [wintypes.HDC]
gdi32.AbortDoc.restype = ctypes.c_int
gdi32.StartPage.argtypes = [wintypes.HDC]
gdi32.StartPage.restype = ctypes.c_int
gdi32.EndPage.argtypes = [wintypes.HDC]
gdi32.EndPage.restype = ctypes.c_int
gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetStretchBltMode.restype = ctypes.c_int
gdi32.SetBrushOrgEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.SetBrushOrgEx.restype = wintypes.BOOL


class PrinterError(Exception):
    pass


def _err(msg: str) -> PrinterError:
    code = ctypes.get_last_error()
    return PrinterError(f"{msg} (Windows 오류 {code}: {ctypes.FormatError(code).strip()})" if code else msg)


# ---------------------------------------------------------------- 프린터 목록

def default_printer() -> str:
    size = wintypes.DWORD(0)
    winspool.GetDefaultPrinterW(None, ctypes.byref(size))
    if not size.value:
        return ""
    buf = ctypes.create_unicode_buffer(size.value)
    if not winspool.GetDefaultPrinterW(buf, ctypes.byref(size)):
        return ""
    return buf.value


def list_printers() -> list[str]:
    flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    needed, returned = wintypes.DWORD(0), wintypes.DWORD(0)
    winspool.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(returned))
    if not needed.value:
        return []
    buf = ctypes.create_string_buffer(needed.value)
    if not winspool.EnumPrintersW(flags, None, 4, buf, needed, ctypes.byref(needed), ctypes.byref(returned)):
        raise _err("프린터 목록을 가져오지 못했습니다")
    arr = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_4W))
    names = [arr[i].pPrinterName for i in range(returned.value)]
    return sorted({n for n in names if n}, key=str.lower)


class _Printer:
    def __init__(self, name: str):
        self.name = name
        self.handle = wintypes.HANDLE()
        if not winspool.OpenPrinterW(name, ctypes.byref(self.handle), None):
            raise _err(f"프린터를 열 수 없습니다: {name}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        winspool.ClosePrinter(self.handle)

    def port(self) -> str | None:
        needed = wintypes.DWORD(0)
        winspool.GetPrinterW(self.handle, 5, None, 0, ctypes.byref(needed))
        if not needed.value:
            return None
        buf = ctypes.create_string_buffer(needed.value)
        if not winspool.GetPrinterW(self.handle, 5, buf, needed, ctypes.byref(needed)):
            return None
        return ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_5W))[0].pPortName

    def user_devmode(self) -> ctypes.Array:
        """현재 사용자의 기본 DEVMODE 를 복사해서 돌려준다 (원본은 변경되지 않음)."""
        size = winspool.DocumentPropertiesW(None, self.handle, self.name, None, None, 0)
        if size <= 0:
            raise _err(f"프린터 설정을 읽을 수 없습니다: {self.name}")
        buf = ctypes.create_string_buffer(size)
        if winspool.DocumentPropertiesW(None, self.handle, self.name, buf, None, DM_OUT_BUFFER) < 0:
            raise _err(f"프린터 설정을 읽을 수 없습니다: {self.name}")
        return buf

    def merge(self, devmode_in: ctypes.Array) -> ctypes.Array:
        """수정한 DEVMODE 를 드라이버에 검증시켜 드라이버 전용 영역까지 맞춘 새 DEVMODE 를 받는다."""
        out = ctypes.create_string_buffer(len(devmode_in))
        if winspool.DocumentPropertiesW(None, self.handle, self.name, out, devmode_in,
                                        DM_IN_BUFFER | DM_OUT_BUFFER) < 0:
            raise _err("프린터 드라이버가 출력 설정을 거부했습니다")
        return out


# ---------------------------------------------------------------- 프린터 기능 조회

def _devcaps(name: str, port: str | None, cap: int, devmode=None):
    n = winspool.DeviceCapabilitiesW(name, port, cap, None, devmode)
    return n if n > 0 else 0


def _names(name, port, cap, width, count) -> list[str]:
    if not count:
        return []
    buf = ctypes.create_unicode_buffer(width * count)
    winspool.DeviceCapabilitiesW(name, port, cap, buf, None)
    raw = ctypes.wstring_at(ctypes.addressof(buf), width * count)
    return [raw[i * width:(i + 1) * width].split("\0", 1)[0].strip() for i in range(count)]


def _words(name, port, cap, count) -> list[int]:
    if not count:
        return []
    arr = (wintypes.WORD * count)()
    winspool.DeviceCapabilitiesW(name, port, cap, arr, None)
    return list(arr)


def get_capabilities(printer: str) -> PrinterCaps:
    name = printer or default_printer()
    if not name:
        raise PrinterError("설치된 기본 프린터가 없습니다")
    with _Printer(name) as p:
        port = p.port()

    n_papers = _devcaps(name, port, DC_PAPERS)
    ids = _words(name, port, DC_PAPERS, n_papers)
    names = _names(name, port, DC_PAPERNAMES, 64, n_papers)
    sizes: list[tuple[float, float]] = [(0.0, 0.0)] * n_papers
    if n_papers:
        pts = (wintypes.POINT * n_papers)()
        if winspool.DeviceCapabilitiesW(name, port, DC_PAPERSIZE, pts, None) > 0:
            sizes = [(pt.x / 10.0, pt.y / 10.0) for pt in pts]  # 0.1mm 단위
    papers = []
    seen = set()
    for i, pid in enumerate(ids):
        if pid in seen:
            continue
        seen.add(pid)
        nm = names[i] if i < len(names) and names[i] else f"용지 {pid}"
        w, h = sizes[i] if i < len(sizes) else (0.0, 0.0)
        papers.append(PaperInfo(pid, nm, w, h))

    n_bins = _devcaps(name, port, DC_BINS)
    bin_ids = _words(name, port, DC_BINS, n_bins)
    bin_names = _names(name, port, DC_BINNAMES, 24, n_bins)
    bins = [(bid, bin_names[i] if i < len(bin_names) and bin_names[i] else f"급지함 {bid}")
            for i, bid in enumerate(bin_ids)]

    color = winspool.DeviceCapabilitiesW(name, port, DC_COLORDEVICE, None, None) == 1
    duplex = winspool.DeviceCapabilitiesW(name, port, DC_DUPLEX, None, None) == 1
    return PrinterCaps(name, papers, bins, color, duplex)


# ---------------------------------------------------------------- 출력

def build_devmode(printer: str, preset: Preset) -> tuple[ctypes.Array, list[str]]:
    """이번 출력에만 쓸 DEVMODE 를 만든다. (devmode 버퍼, 경고 목록)"""
    warnings: list[str] = []
    with _Printer(printer) as p:
        buf = p.user_devmode()
        dm = DEVMODEW.from_buffer(buf)

        dm.dmFields |= DM_ORIENTATION | DM_PAPERSIZE | DM_COLOR | DM_COPIES | DM_COLLATE
        dm.dmOrientation = preset.orientation
        dm.dmPaperSize = preset.paper_id
        dm.dmFields &= ~DM_FORMNAME  # 폼 이름이 용지 번호보다 우선하는 드라이버 대비
        if preset.paper_id == DMPAPER_USER:
            dm.dmFields |= DM_PAPERLENGTH | DM_PAPERWIDTH
            dm.dmPaperWidth = int(round(preset.custom_width_mm * 10))
            dm.dmPaperLength = int(round(preset.custom_height_mm * 10))
        else:
            dm.dmFields &= ~(DM_PAPERLENGTH | DM_PAPERWIDTH)
        dm.dmColor = 2 if preset.color else 1  # DMCOLOR_COLOR / DMCOLOR_MONOCHROME
        dm.dmCopies = 1  # 매수는 프로그램이 직접 반복 출력 (드라이버마다 처리 방식이 달라서)
        dm.dmCollate = 0
        if preset.bin_id != DMBIN_AUTO:
            dm.dmFields |= DM_DEFAULTSOURCE
            dm.dmDefaultSource = preset.bin_id
        if preset.duplex != DUPLEX_SIMPLEX or dm.dmFields & DM_DUPLEX:
            dm.dmFields |= DM_DUPLEX
            dm.dmDuplex = preset.duplex
        del dm  # from_buffer 참조 해제 (버퍼 크기 변경 방지용 export 해제)

        out = p.merge(buf)
        chk = DEVMODEW.from_buffer(out)
        if chk.dmPaperSize != preset.paper_id:
            warnings.append(f"프린터가 용지 '{preset.paper_name}'을(를) 다른 용지로 바꿨습니다 (번호 {chk.dmPaperSize})")
        if chk.dmOrientation != preset.orientation:
            warnings.append("프린터가 용지 방향 설정을 바꿨습니다")
        del chk
    return out, warnings


class WinPrinterDevice:
    """이번 출력 작업 전용 프린터 DC."""

    def __init__(self, printer: str, preset: Preset, output_file: str | None = None):
        self.output_file = output_file  # 지정하면 프린터 대신 파일로 (Print to PDF 테스트용)
        self.name = printer or default_printer()
        if not self.name:
            raise PrinterError("설치된 기본 프린터가 없습니다")
        self._devmode, self.warnings = build_devmode(self.name, preset)
        self.hdc = gdi32.CreateDCW("WINSPOOL", self.name, None, self._devmode)
        if not self.hdc:
            raise _err(f"프린터에 연결할 수 없습니다: {self.name}")
        cap = lambda i: gdi32.GetDeviceCaps(self.hdc, i)  # noqa: E731
        self.metrics = DeviceMetrics(
            printable_w=cap(HORZRES), printable_h=cap(VERTRES),
            physical_w=cap(PHYSICALWIDTH), physical_h=cap(PHYSICALHEIGHT),
            offset_x=cap(PHYSICALOFFSETX), offset_y=cap(PHYSICALOFFSETY),
            dpi_x=cap(LOGPIXELSX) or 300, dpi_y=cap(LOGPIXELSY) or 300,
        )
        self._doc_open = False
        self._docinfo = None

    def start_doc(self, title: str) -> None:
        self._docinfo = DOCINFOW(ctypes.sizeof(DOCINFOW), title[:200], self.output_file, None, 0)
        if gdi32.StartDocW(self.hdc, ctypes.byref(self._docinfo)) <= 0:
            raise _err("인쇄 작업을 시작할 수 없습니다")
        self._doc_open = True

    def start_page(self) -> None:
        if gdi32.StartPage(self.hdc) <= 0:
            raise _err("페이지를 시작할 수 없습니다")

    def draw(self, img: Image.Image, pl: Placement) -> None:
        gdi32.SetStretchBltMode(self.hdc, HALFTONE)
        gdi32.SetBrushOrgEx(self.hdc, 0, 0, None)
        ImageWin.Dib(img).draw(self.hdc, (pl.left, pl.top, pl.right, pl.bottom))

    def end_page(self) -> None:
        if gdi32.EndPage(self.hdc) <= 0:
            raise _err("페이지를 프린터로 보내지 못했습니다")

    def end_doc(self) -> None:
        if self._doc_open:
            self._doc_open = False
            if gdi32.EndDoc(self.hdc) <= 0:
                raise _err("인쇄 작업을 마치지 못했습니다")

    def abort_doc(self) -> None:
        if self._doc_open:
            self._doc_open = False
            gdi32.AbortDoc(self.hdc)

    def close(self) -> None:
        self.abort_doc()
        if self.hdc:
            gdi32.DeleteDC(self.hdc)
            self.hdc = None
