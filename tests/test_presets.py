import json

import pytest

from easyprint.presets import (DMPAPER_A3, DMPAPER_USER, ORIENT_LANDSCAPE, Preset, PresetStore,
                               default_presets)


def test_defaults_match_requested_formats():
    names = [p.name for p in default_presets()]
    assert names == ["A4 세로 컬러", "A3 가로 컬러", "편지봉투"]
    a3 = default_presets()[1]
    assert a3.paper_id == DMPAPER_A3 and a3.orientation == ORIENT_LANDSCAPE and a3.color


def test_first_run_uses_defaults_and_roundtrips(tmp_path):
    path = tmp_path / "presets.json"
    s = PresetStore.load(path)
    assert len(s.presets) == 3 and s.last_used == "A4 세로 컬러"
    s.upsert(Preset(name="회의자료 A3 흑백", paper_id=DMPAPER_A3, orientation=2, color=False, copies=5))
    s.last_used = "회의자료 A3 흑백"
    s.save()
    s2 = PresetStore.load(path)
    assert s2.names()[-1] == "회의자료 A3 흑백"
    p = s2.get("회의자료 A3 흑백")
    assert p.color is False and p.copies == 5 and s2.last_used == p.name
    assert "회의자료" in path.read_text(encoding="utf-8")  # 한글 그대로 저장


def test_upsert_replaces_same_name(tmp_path):
    s = PresetStore.load(tmp_path / "p.json")
    s.upsert(Preset(name="편지봉투", copies=3))
    assert len(s.presets) == 3 and s.get("편지봉투").copies == 3


def test_delete_and_last_one_protected(tmp_path):
    s = PresetStore.load(tmp_path / "p.json")
    s.last_used = "편지봉투"
    s.delete("편지봉투")
    assert s.last_used == "A4 세로 컬러"
    s.delete("A3 가로 컬러")
    with pytest.raises(ValueError):
        s.delete("A4 세로 컬러")


def test_move(tmp_path):
    s = PresetStore.load(tmp_path / "p.json")
    s.move("편지봉투", -1)
    assert s.names() == ["A4 세로 컬러", "편지봉투", "A3 가로 컬러"]
    s.move("A4 세로 컬러", -1)
    assert s.names()[0] == "A4 세로 컬러"


def test_broken_file_is_backed_up(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text("{ not json", encoding="utf-8")
    s = PresetStore.load(path)
    assert len(s.presets) == 3 and s.load_warning
    assert (tmp_path / "presets.broken.json").exists()


def test_invalid_entries_skipped_and_values_clamped(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps({"presets": [
        {"name": ""}, {"name": "ok", "copies": 5000, "duplex": 9, "scale": "x", "unknown": 1},
        {"name": "ok", "copies": 2},
    ]}), encoding="utf-8")
    s = PresetStore.load(path)
    assert s.names() == ["ok"]
    p = s.get("ok")
    assert p.copies == 999 and p.duplex == 1 and p.scale == "fit"


def test_custom_size_validation():
    with pytest.raises(ValueError):
        Preset(name="x", paper_id=DMPAPER_USER, custom_width_mm=5).validate()
    Preset(name="x", paper_id=DMPAPER_USER, custom_width_mm=220, custom_height_mm=105).validate()
