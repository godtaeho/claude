"""프린터가 지원하는 용지/급지함/기능 정보."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PaperInfo:
    id: int
    name: str
    width_mm: float
    height_mm: float

    @property
    def label(self) -> str:
        if self.width_mm and self.height_mm:
            return f"{self.name}  ({self.width_mm:g} x {self.height_mm:g} mm)"
        return self.name


@dataclass
class PrinterCaps:
    name: str
    papers: list[PaperInfo]
    bins: list[tuple[int, str]]
    color: bool
    duplex: bool


# 다목적 용지함/수동 급지를 가리키는 이름들 (드라이버마다 표기가 다름)
MANUAL_FEED_HINTS = ("다목적", "수동", "mp", "multi", "bypass", "by-pass", "manual", "수동급지")


def _norm(s: str) -> str:
    return "".join(s.lower().split())


def match_bin(bins: list[tuple[int, str]], bin_id: int, bin_name: str) -> int | None:
    """저장된 급지함을 이 프린터의 급지함 목록에서 찾는다. 반환: bins 의 인덱스 또는 None.

    1) 이름이 같으면 그것  2) 다목적/수동 계열 이름이면 같은 계열  3) 번호가 같으면 그것
    """
    want = _norm(bin_name)
    if want:
        for i, (_, name) in enumerate(bins):
            if _norm(name) == want:
                return i
        if any(h in want for h in MANUAL_FEED_HINTS):
            # '다목적'을 원하면 '다목적'이 들어간 이름을 우선, 없으면 수동 급지 계열
            for keys in (("다목적", "mp", "multi"), MANUAL_FEED_HINTS):
                for i, (_, name) in enumerate(bins):
                    n = _norm(name)
                    if any(k in n for k in keys) and any(k in want for k in MANUAL_FEED_HINTS):
                        return i
    for i, (bid, _) in enumerate(bins):
        if bid == bin_id:
            return i
    return None


def match_paper_by_size(papers: list[PaperInfo], width_mm: float, height_mm: float,
                        tol: float = 1.0) -> PaperInfo | None:
    """프린터에 같은 크기(가로x세로, ±tol mm)로 등록된 용지가 있으면 돌려준다."""
    for p in papers:
        if abs(p.width_mm - width_mm) <= tol and abs(p.height_mm - height_mm) <= tol:
            return p
    return None
