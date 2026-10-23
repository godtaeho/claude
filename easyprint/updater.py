"""자동 업데이트 / 자동 설치 (Windows exe 전용).

흐름
  1) GitHub Releases 의 최신 버전을 확인 (공개 저장소라 로그인 불필요)
  2) 새 버전이면 EasyPrint.exe 를 내려받아 SHA-256 으로 검증
  3) 실행 중인 exe 는 이름만 바꿔 두고(Windows 는 실행 중인 exe 의 이름 변경을 허용) 새 exe 를 제자리에 놓음
     → 다음 실행부터 새 버전. '지금 다시 시작'을 누르면 바로 적용
  4) 남은 옛 파일(.old)은 다음 실행 때 지움

처음 실행 시에는 %LOCALAPPDATA%\\Programs\\EasyPrint 에 자신을 설치하고 바탕화면/시작 메뉴 바로가기를 만든다.
(항상 쓰기 가능한 위치라 관리자 권한 없이 업데이트할 수 있음)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__

REPO = "godtaeho/claude"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
EXE_ASSET = "EasyPrint.exe"
SHA_ASSET = "EasyPrint.exe.sha256"
CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000  # 켜 둔 채로 있으면 6시간마다 다시 확인
TIMEOUT = 20


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    size: int


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text or "")
    if not nums:
        raise ValueError(f"버전 형식이 아닙니다: {text!r}")
    return tuple(int(n) for n in nums[:4])


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _get(url: str, accept: str = "application/octet-stream"):
    req = urllib.request.Request(url, headers={"User-Agent": f"EasyPrint/{__version__}", "Accept": accept})
    return urllib.request.urlopen(req, timeout=TIMEOUT)  # Windows 프록시/인증서 설정을 그대로 사용


def check(current: str = __version__, fetch=_get) -> UpdateInfo | None:
    """새 버전이 있으면 UpdateInfo, 없으면 None. 검증용 해시가 없는 릴리스는 설치하지 않는다."""
    try:
        with fetch(LATEST_API, "application/vnd.github+json") as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:  # 아직 릴리스가 하나도 없음
            return None
        raise
    tag = data.get("tag_name", "")
    if data.get("draft") or data.get("prerelease") or not is_newer(tag, current):
        return None
    assets = {a.get("name"): a for a in data.get("assets", [])}
    exe = assets.get(EXE_ASSET)
    if not exe:
        raise UpdateError(f"릴리스 {tag}에 {EXE_ASSET} 파일이 없습니다")
    sha = ""
    if SHA_ASSET in assets:
        with fetch(assets[SHA_ASSET]["browser_download_url"]) as r:
            words = r.read().decode("ascii", "ignore").split()
        sha = words[0].lower() if words else ""
    if not sha and str(exe.get("digest", "")).startswith("sha256:"):
        sha = exe["digest"].split(":", 1)[1].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise UpdateError(f"릴리스 {tag}의 검증용 해시가 없어 설치하지 않습니다")
    return UpdateInfo(tag.lstrip("vV"), exe["browser_download_url"], sha, int(exe.get("size") or 0))


def download(info: UpdateInfo, dest: Path, fetch=_get,
             progress: Callable[[int, int], None] = lambda done, total: None) -> Path:
    """내려받아 크기/해시를 검증한다. 실패하면 받은 파일을 지운다."""
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    done = 0
    try:
        with fetch(info.url) as r, open(part, "wb") as f:
            while chunk := r.read(1024 * 256):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                progress(done, info.size)
        if info.size and done != info.size:
            raise UpdateError(f"내려받은 크기가 다릅니다 ({done} / {info.size} 바이트)")
        if h.hexdigest() != info.sha256:
            raise UpdateError("내려받은 파일의 해시가 맞지 않습니다 (손상 또는 변조)")
        os.replace(part, dest)
        return dest
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def old_path(exe: Path) -> Path:
    return exe.with_name(exe.name + ".old")


def apply(new_file: Path, exe: Path) -> None:
    """실행 중인 exe 를 새 파일로 교체한다. 실패하면 원래대로 되돌린다."""
    exe, new_file, old = Path(exe), Path(new_file), old_path(Path(exe))
    if old.exists():
        old.unlink()  # 지난 업데이트의 잔여물 (지우지 못하면 예외 → 이번 업데이트 중단)
    os.replace(exe, old)  # 실행 중이어도 이름 변경은 가능
    try:
        os.replace(new_file, exe)
    except BaseException:
        os.replace(old, exe)
        raise


def cleanup(exe: Path) -> None:
    for p in (old_path(Path(exe)), Path(exe).with_name(Path(exe).name + ".new.part"),
              Path(exe).with_name(Path(exe).name + ".new")):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass  # 아직 이전 프로세스가 끝나지 않았으면 다음에 지움


def update_now(exe: Path, current: str = __version__, fetch=_get,
               progress: Callable[[int, int], None] = lambda d, t: None) -> str | None:
    """확인 → 다운로드 → 교체까지 한 번에. 설치한 새 버전 문자열 또는 None."""
    info = check(current, fetch)
    if not info:
        return None
    new = download(info, Path(exe).with_name(Path(exe).name + ".new"), fetch, progress)
    apply(new, exe)
    return info.version


# ---------------------------------------------------------------- 실행 파일 위치 / 재시작

def is_frozen_exe() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def current_exe() -> Path:
    return Path(sys.executable).resolve()


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / "EasyPrint"


def installed_exe() -> Path:
    return install_dir() / EXE_ASSET


def spawn(exe: Path, args: list[str]) -> None:
    """exe 를 독립된 새 프로세스로 띄운다 (onefile 임시 폴더를 공유하지 않도록 환경 초기화)."""
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe), *args], env=env, close_fds=True, creationflags=flags,
                     cwd=str(Path(exe).parent))


def _shortcut(path: Path, target: Path, desc: str) -> None:
    import win32com.client
    sc = win32com.client.Dispatch("WScript.Shell").CreateShortCut(str(path))
    sc.TargetPath = str(target)
    sc.WorkingDirectory = str(target.parent)
    sc.IconLocation = str(target)
    sc.Description = desc
    sc.save()


def create_shortcuts(target: Path) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        folders = win32com.client.Dispatch("WScript.Shell").SpecialFolders
        for key in ("Desktop", "Programs"):  # 바탕화면(OneDrive 리디렉션 포함), 시작 메뉴
            try:
                _shortcut(Path(folders(key)) / f"{APP_NAME}.lnk", target, f"{APP_NAME} - 원하는 형식으로 바로 출력")
            except Exception:
                pass
    finally:
        pythoncom.CoUninitialize()


def ensure_installed(argv: list[str]) -> bool:
    """설치 위치가 아닌 곳(다운로드 폴더 등)에서 실행됐으면 설치 후 설치본을 실행한다.

    True 를 돌려주면 호출한 쪽은 바로 종료해야 한다.
    """
    if not is_frozen_exe() or os.environ.get("EASYPRINT_NO_INSTALL"):
        return False
    here, target = current_exe(), installed_exe()
    if os.path.normcase(str(here)) == os.path.normcase(str(target)):
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".install")
        shutil.copy2(here, tmp)
        if target.exists():
            apply(tmp, target)  # 설치본이 실행 중이어도 교체 가능
        else:
            os.replace(tmp, target)
    except OSError:
        return False  # 설치 실패 시 지금 위치에서 그냥 실행
    try:
        create_shortcuts(target)
        from . import shell
        if shell.is_registered():
            shell.register_sendto(target)  # '보내기' 메뉴도 설치본을 가리키게
    except Exception:
        pass
    spawn(target, argv)
    return True
