"""운영체제별 프린터 백엔드. Windows 는 실제 프린터, 그 외에는 개발/테스트용 가상 프린터."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .caps import PaperInfo, PrinterCaps
from .presets import DMPAPER_USER, ORIENT_LANDSCAPE, Preset


class WinBackend:
    def __init__(self):
        from . import winprint
        self._wp = winprint

    def list_printers(self) -> list[str]:
        return self._wp.list_printers()

    def default_printer(self) -> str:
        return self._wp.default_printer()

    def get_capabilities(self, printer: str) -> PrinterCaps:
        return self._wp.get_capabilities(printer)

    def open_device(self, printer: str, preset: Preset):
        return self._wp.WinPrinterDevice(printer, preset)


class FakeBackend:
    """Windows 가 아닌 곳에서 화면 확인/테스트용. 출력 결과를 PNG 로 저장한다."""

    PAPERS = [PaperInfo(9, "A4", 210, 297), PaperInfo(8, "A3", 297, 420),
              PaperInfo(27, "Envelope DL", 110, 220), PaperInfo(28, "Envelope C5", 162, 229)]

    def __init__(self, out_dir: str | None = None):
        self.out_dir = Path(out_dir or os.environ.get("EASYPRINT_FAKE_OUT", "fake_print_output"))

    def list_printers(self) -> list[str]:
        return ["가상 컬러 프린터", "가상 흑백 프린터"]

    def default_printer(self) -> str:
        return "가상 컬러 프린터"

    def get_capabilities(self, printer: str) -> PrinterCaps:
        name = printer or self.default_printer()
        mono = "흑백" in name
        return PrinterCaps(name, list(self.PAPERS) if not mono else self.PAPERS[:1],
                           [(7, "자동 선택"), (4, "수동 급지"), (2, "트레이 1")], not mono, not mono)

    def open_device(self, printer: str, preset: Preset):
        from .engine import ImageDevice
        if preset.paper_id == DMPAPER_USER:
            w, h = preset.custom_width_mm, preset.custom_height_mm
        else:
            p = next((x for x in self.PAPERS if x.id == preset.paper_id), self.PAPERS[0])
            w, h = p.width_mm, p.height_mm
        if (preset.orientation == ORIENT_LANDSCAPE) != (w > h):
            w, h = h, w
        backend = self

        class _SavingDevice(ImageDevice):
            def close(self):
                backend.out_dir.mkdir(parents=True, exist_ok=True)
                for d, (title, pages) in enumerate(self.docs, 1):
                    for i, img in enumerate(pages, 1):
                        img.save(backend.out_dir / f"{d:02d}_{Path(title).stem}_{i:03d}.png")

        return _SavingDevice(w, h)


def get_backend():
    if sys.platform == "win32" and not os.environ.get("EASYPRINT_FAKE"):
        return WinBackend()
    return FakeBackend()
