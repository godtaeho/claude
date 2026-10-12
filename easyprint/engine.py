"""여러 파일을 하나의 프린터 장치로 출력하는 흐름 (OS 무관)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from PIL import Image

from .documents import Document, UnsupportedFile
from .layout import DeviceMetrics, Placement, place
from .presets import DUPLEX_SIMPLEX, Preset


class Device(Protocol):
    metrics: DeviceMetrics
    warnings: list[str]

    def start_doc(self, title: str) -> None: ...
    def start_page(self) -> None: ...
    def draw(self, img: Image.Image, pl: Placement) -> None: ...
    def end_page(self) -> None: ...
    def end_doc(self) -> None: ...
    def abort_doc(self) -> None: ...
    def close(self) -> None: ...


@dataclass
class JobResult:
    printed_files: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (파일, 이유)
    pages: int = 0
    cancelled: bool = False
    warnings: list[str] = field(default_factory=list)


ProgressFn = Callable[[str], None]


def render_dpi(page_w_pt: float, pl: Placement) -> float:
    """배치될 픽셀 크기에 딱 맞는 렌더링 DPI."""
    w_px = (pl.bottom - pl.top) if pl.rotate else (pl.right - pl.left)
    return w_px / (page_w_pt / 72.0)


def print_files(device: Device, files: list[str], preset: Preset,
                progress: ProgressFn = lambda s: None,
                cancel: threading.Event | None = None) -> JobResult:
    res = JobResult(warnings=list(getattr(device, "warnings", [])))
    cancel = cancel or threading.Event()
    m = device.metrics
    for n, path in enumerate(files, 1):
        name = Path(path).name
        if cancel.is_set():
            res.cancelled = True
            break
        progress(f"[{n}/{len(files)}] {name} 준비 중...")
        try:
            with Document(path) as doc:
                pages = doc.pages
                # 양면 + 여러 부 + 홀수 페이지: 다음 부가 이전 부의 뒷면에 찍히지 않게 빈 페이지 추가
                pad = preset.duplex != DUPLEX_SIMPLEX and preset.copies > 1 and len(pages) % 2 == 1
                device.start_doc(name)
                try:
                    for c in range(preset.copies):
                        for i, page in enumerate(pages, 1):
                            if cancel.is_set():
                                raise _Cancelled
                            progress(f"[{n}/{len(files)}] {name}  {i}/{len(pages)}쪽"
                                     + (f"  ({c + 1}/{preset.copies}부)" if preset.copies > 1 else ""))
                            pl = place(page.width_pt, page.height_pt, m, preset.scale, preset.auto_rotate)
                            img = page.render(render_dpi(page.width_pt, pl))
                            if pl.rotate:
                                img = img.transpose(Image.Transpose.ROTATE_90)
                            device.start_page()
                            device.draw(img, pl)
                            device.end_page()
                            res.pages += 1
                        if pad and c < preset.copies - 1:
                            device.start_page()
                            device.end_page()
                except _Cancelled:
                    device.abort_doc()
                    res.cancelled = True
                    break
                except BaseException:
                    device.abort_doc()
                    raise
                device.end_doc()
                res.printed_files.append(path)
        except UnsupportedFile as e:
            res.failed.append((path, str(e)))
        except Exception as e:  # 한 파일이 실패해도 나머지는 계속 출력
            res.failed.append((path, f"{type(e).__name__}: {e}"))
    return res


class _Cancelled(Exception):
    pass


class ImageDevice:
    """테스트/미리보기용 가상 프린터: 각 페이지를 용지 크기 이미지로 그린다."""

    def __init__(self, paper_w_mm: float, paper_h_mm: float, dpi: int = 50, margin_mm: float = 5.0):
        px = lambda mm: round(mm / 25.4 * dpi)  # noqa: E731
        off = px(margin_mm)
        self.metrics = DeviceMetrics(px(paper_w_mm) - 2 * off, px(paper_h_mm) - 2 * off,
                                     px(paper_w_mm), px(paper_h_mm), off, off, dpi, dpi)
        self.warnings: list[str] = []
        self.docs: list[tuple[str, list[Image.Image]]] = []
        self._page: Image.Image | None = None

    def start_doc(self, title):
        self.docs.append((title, []))

    def start_page(self):
        m = self.metrics
        self._page = Image.new("RGB", (m.physical_w, m.physical_h), "white")

    def draw(self, img, pl):
        m = self.metrics
        resized = img.convert("RGB").resize((pl.right - pl.left, pl.bottom - pl.top))
        self._page.paste(resized, (pl.left + m.offset_x, pl.top + m.offset_y))

    def end_page(self):
        self.docs[-1][1].append(self._page)
        self._page = None

    def end_doc(self):
        pass

    def abort_doc(self):
        if self.docs:
            self.docs.pop()

    def close(self):
        pass
