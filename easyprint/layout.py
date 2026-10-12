"""페이지를 프린터 용지 위 어디에, 어떤 크기로 그릴지 계산한다 (순수 계산, OS 무관)."""
from __future__ import annotations

from dataclasses import dataclass

from .presets import SCALE_ACTUAL, SCALE_FIT


@dataclass(frozen=True)
class DeviceMetrics:
    """프린터 DC 정보. 단위는 모두 장치 픽셀.

    printable_*: 인쇄 가능 영역 크기 (HORZRES/VERTRES)
    physical_*: 실제 용지 크기 (PHYSICALWIDTH/HEIGHT)
    offset_*: 용지 가장자리에서 인쇄 가능 영역까지의 거리 (PHYSICALOFFSETX/Y)
    좌표 원점은 인쇄 가능 영역의 왼쪽 위.
    """
    printable_w: int
    printable_h: int
    physical_w: int
    physical_h: int
    offset_x: int
    offset_y: int
    dpi_x: int
    dpi_y: int


@dataclass(frozen=True)
class Placement:
    rotate: bool  # True 면 원본을 90도 회전해서 그린다
    left: int
    top: int
    right: int
    bottom: int


def should_rotate(src_w: float, src_h: float, dev: DeviceMetrics, auto_rotate: bool) -> bool:
    if not auto_rotate or src_w == src_h:
        return False
    src_landscape = src_w > src_h
    dev_landscape = dev.printable_w > dev.printable_h
    return src_landscape != dev_landscape


def place(src_w_pt: float, src_h_pt: float, dev: DeviceMetrics, scale: str, auto_rotate: bool) -> Placement:
    """원본 페이지(포인트 단위, 1pt = 1/72 inch)를 장치 좌표의 사각형으로 배치한다."""
    if src_w_pt <= 0 or src_h_pt <= 0:
        raise ValueError("페이지 크기가 올바르지 않습니다")
    rotate = should_rotate(src_w_pt, src_h_pt, dev, auto_rotate)
    w_pt, h_pt = (src_h_pt, src_w_pt) if rotate else (src_w_pt, src_h_pt)

    if scale == SCALE_ACTUAL:
        w = w_pt / 72.0 * dev.dpi_x
        h = h_pt / 72.0 * dev.dpi_y
        # 실제 용지 기준 가운데 정렬 → 인쇄 가능 영역 좌표로 변환
        left = (dev.physical_w - w) / 2 - dev.offset_x
        top = (dev.physical_h - h) / 2 - dev.offset_y
    elif scale == SCALE_FIT:
        # 물리 크기 비율을 유지 (가로/세로 DPI 가 다른 프린터 대비)
        w_in, h_in = w_pt / 72.0, h_pt / 72.0
        avail_w_in = dev.printable_w / dev.dpi_x
        avail_h_in = dev.printable_h / dev.dpi_y
        k = min(avail_w_in / w_in, avail_h_in / h_in)
        w = w_in * k * dev.dpi_x
        h = h_in * k * dev.dpi_y
        left = (dev.printable_w - w) / 2
        top = (dev.printable_h - h) / 2
    else:
        raise ValueError(f"알 수 없는 배율 방식: {scale}")

    l, t = round(left), round(top)
    return Placement(rotate, l, t, l + max(1, round(w)), t + max(1, round(h)))
