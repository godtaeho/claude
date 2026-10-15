from easyprint.caps import PaperInfo, match_bin, match_paper_by_size

SAMSUNG = [(7, "자동 선택"), (1, "용지함 1"), (4, "다목적 용지함")]
HP = [(15, "자동 선택"), (257, "용지함 1(다목적)"), (258, "용지함 2")]
SINDOH = [(7, "Auto"), (4, "Manual Feed"), (259, "Tray 1")]
CANON = [(7, "자동"), (260, "수동 급지 트레이"), (261, "카세트 1")]


def test_exact_name_first():
    assert match_bin(SAMSUNG, 4, "다목적 용지함") == 2


def test_multipurpose_name_variants():
    assert match_bin(HP, 4, "다목적 용지함") == 1          # 번호 다르고 이름 표기 다름
    assert match_bin(SINDOH, 999, "다목적 용지함") == 1     # 영문 Manual Feed
    assert match_bin(CANON, 4, "다목적 용지함") == 1        # '수동 급지 트레이'


def test_fallback_to_id_and_none():
    assert match_bin(SAMSUNG, 1, "없는 이름") == 1
    assert match_bin(SAMSUNG, 99, "없는 이름") is None
    assert match_bin([], 4, "다목적 용지함") is None


def test_ordinary_tray_not_confused_with_manual():
    assert match_bin(HP, 258, "용지함 2") == 2


def test_paper_by_size():
    papers = [PaperInfo(9, "A4", 210, 297), PaperInfo(300, "봉투 115x216", 115.0, 216.1)]
    assert match_paper_by_size(papers, 115, 216).id == 300
    assert match_paper_by_size(papers, 216, 115) is None  # 방향이 다른 건 다른 용지
    assert match_paper_by_size(papers, 110, 220) is None
