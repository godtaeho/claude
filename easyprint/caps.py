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
