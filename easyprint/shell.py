"""탐색기 '보내기(Send To)' 메뉴 등록 (Windows 전용)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def sendto_shortcut_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "SendTo" / f"{APP_NAME}.lnk"


def _target() -> tuple[str, str, str]:
    """(실행 파일, 인수, 작업 폴더)"""
    if getattr(sys, "frozen", False):  # PyInstaller exe
        exe = sys.executable
        return exe, "", str(Path(exe).parent)
    main = Path(__file__).resolve().parent.parent / "main.py"
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return str(pyw if pyw.exists() else sys.executable), f'"{main}"', str(main.parent)


def is_registered() -> bool:
    return sys.platform == "win32" and sendto_shortcut_path().exists()


def register_sendto() -> Path:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        exe, args, workdir = _target()
        link = sendto_shortcut_path()
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(str(link))
        sc.TargetPath = exe
        sc.Arguments = args
        sc.WorkingDirectory = workdir
        sc.IconLocation = exe
        sc.Description = f"{APP_NAME}으로 출력"
        sc.save()
        return link
    finally:
        pythoncom.CoUninitialize()


def unregister_sendto() -> None:
    try:
        sendto_shortcut_path().unlink()
    except FileNotFoundError:
        pass
