"""출력 형식(프리셋) 정의와 저장/불러오기.

프리셋은 프린터 기본 설정과 무관하게, 출력 시점에만 적용되는 설정 묶음이다.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# Windows DEVMODE 상수 (wingdi.h)
DMPAPER_A3 = 8
DMPAPER_A4 = 9
DMPAPER_ENV_DL = 27  # 110 x 220 mm (국내 규격 소봉투 105 x 220 mm 와 거의 동일)
DMPAPER_USER = 256  # 사용자 지정 크기

ORIENT_PORTRAIT = 1
ORIENT_LANDSCAPE = 2

DUPLEX_SIMPLEX = 1
DUPLEX_LONG = 2  # DMDUP_VERTICAL: 긴 쪽 넘김
DUPLEX_SHORT = 3  # DMDUP_HORIZONTAL: 짧은 쪽 넘김

DMBIN_AUTO = 0  # 0 이면 급지함을 지정하지 않음(프린터 판단)

SCALE_FIT = "fit"
SCALE_ACTUAL = "actual"

DEFAULT_PRINTER = ""  # 빈 문자열 = Windows 기본 프린터


@dataclass
class Preset:
    name: str
    printer: str = DEFAULT_PRINTER
    paper_id: int = DMPAPER_A4
    paper_name: str = "A4"
    custom_width_mm: float = 220.0
    custom_height_mm: float = 105.0
    orientation: int = ORIENT_PORTRAIT
    color: bool = True
    bin_id: int = DMBIN_AUTO
    bin_name: str = ""
    duplex: int = DUPLEX_SIMPLEX
    scale: str = SCALE_FIT
    auto_rotate: bool = True
    copies: int = 1

    @classmethod
    def from_dict(cls, data: dict) -> "Preset":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        if not str(clean.get("name", "")).strip():
            raise ValueError("프리셋 이름이 없습니다")
        p = cls(**clean)
        p.validate()
        return p

    def validate(self) -> None:
        self.name = str(self.name).strip()
        self.paper_id = int(self.paper_id)
        self.orientation = ORIENT_LANDSCAPE if int(self.orientation) == ORIENT_LANDSCAPE else ORIENT_PORTRAIT
        self.color = bool(self.color)
        self.bin_id = int(self.bin_id)
        self.duplex = int(self.duplex) if int(self.duplex) in (DUPLEX_SIMPLEX, DUPLEX_LONG, DUPLEX_SHORT) else DUPLEX_SIMPLEX
        self.scale = self.scale if self.scale in (SCALE_FIT, SCALE_ACTUAL) else SCALE_FIT
        self.auto_rotate = bool(self.auto_rotate)
        self.copies = max(1, min(999, int(self.copies)))
        self.custom_width_mm = float(self.custom_width_mm)
        self.custom_height_mm = float(self.custom_height_mm)
        if self.paper_id == DMPAPER_USER and not (
            10 <= self.custom_width_mm <= 1000 and 10 <= self.custom_height_mm <= 1000
        ):
            raise ValueError("사용자 지정 용지 크기는 10~1000mm 사이여야 합니다")

    def to_dict(self) -> dict:
        return asdict(self)


def default_presets() -> list[Preset]:
    return [
        Preset(name="A4 세로 컬러", paper_id=DMPAPER_A4, paper_name="A4",
               orientation=ORIENT_PORTRAIT, color=True),
        Preset(name="A3 가로 컬러", paper_id=DMPAPER_A3, paper_name="A3",
               orientation=ORIENT_LANDSCAPE, color=True),
        Preset(name="편지봉투", paper_id=DMPAPER_ENV_DL, paper_name="Envelope DL",
               orientation=ORIENT_LANDSCAPE, color=True),
    ]


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "EasyPrint"


@dataclass
class PresetStore:
    path: Path
    presets: list[Preset] = field(default_factory=list)
    last_used: str = ""
    load_warning: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "PresetStore":
        path = Path(path) if path else config_dir() / "presets.json"
        store = cls(path=path)
        if not path.exists():
            store.presets = default_presets()
            store.last_used = store.presets[0].name
            return store
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            presets = []
            for item in data.get("presets", []):
                try:
                    p = Preset.from_dict(item)
                except (TypeError, ValueError):
                    continue
                if not any(x.name == p.name for x in presets):
                    presets.append(p)
            store.presets = presets or default_presets()
            store.last_used = str(data.get("last_used", ""))
        except (OSError, ValueError, AttributeError) as e:
            # 파일이 깨졌으면 백업해 두고 기본값으로 시작
            backup = path.with_suffix(".broken.json")
            try:
                shutil.copyfile(path, backup)
            except OSError:
                pass
            store.presets = default_presets()
            store.load_warning = f"설정 파일을 읽지 못해 기본값으로 시작합니다 ({e}). 백업: {backup}"
        if not store.get(store.last_used):
            store.last_used = store.presets[0].name
        return store

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "last_used": self.last_used,
            "presets": [p.to_dict() for p in self.presets],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def names(self) -> list[str]:
        return [p.name for p in self.presets]

    def get(self, name: str) -> Preset | None:
        return next((p for p in self.presets if p.name == name), None)

    def upsert(self, preset: Preset) -> None:
        preset.validate()
        for i, p in enumerate(self.presets):
            if p.name == preset.name:
                self.presets[i] = preset
                return
        self.presets.append(preset)

    def delete(self, name: str) -> None:
        if len(self.presets) <= 1:
            raise ValueError("마지막 남은 형식은 삭제할 수 없습니다")
        self.presets = [p for p in self.presets if p.name != name]
        if self.last_used == name:
            self.last_used = self.presets[0].name

    def move(self, name: str, delta: int) -> None:
        idx = next(i for i, p in enumerate(self.presets) if p.name == name)
        new = max(0, min(len(self.presets) - 1, idx + delta))
        self.presets.insert(new, self.presets.pop(idx))
