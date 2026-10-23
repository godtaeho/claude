"""간편출력 실행 파일. 인수로 파일 경로를 주면 목록에 바로 추가된다 (탐색기 '보내기' 메뉴용)."""
import sys
import tempfile
import traceback
from pathlib import Path


def _report_crash() -> None:
    """예상치 못한 오류를 로그로 남긴다. (exe 는 콘솔이 없어서 그냥 두면 원인을 알 수 없음)"""
    text = traceback.format_exc()
    log = Path(tempfile.gettempdir()) / "EasyPrint-error.log"
    try:
        log.write_text(text, encoding="utf-8")
    except OSError:
        pass
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":  # 점검 모드: 창 없이 바로 종료
        Path(sys.argv[2] + ".crash").write_text(text, encoding="utf-8")
        sys.exit(3)
    try:
        import tkinter
        from tkinter import messagebox
        tkinter.Tk().withdraw()
        messagebox.showerror("간편출력", f"오류로 종료합니다.\n\n{text[-1500:]}\n\n로그: {log}")
    except Exception:
        pass
    sys.exit(1)


if __name__ == "__main__":
    try:
        from easyprint.app import run
        run()
    except SystemExit:
        raise
    except BaseException:
        _report_crash()
