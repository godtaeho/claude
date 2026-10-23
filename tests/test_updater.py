import hashlib
import io
import json
import sys
import urllib.error

import pytest

from easyprint import updater
from easyprint.updater import UpdateError, UpdateInfo

NEW_EXE = b"MZ new easyprint build" * 1000
SHA = hashlib.sha256(NEW_EXE).hexdigest()
BASE = "https://github.com/godtaeho/claude/releases/download/v9.9.9/"


def release(tag="v9.9.9", sha_text=SHA, exe=True, digest=None, **extra):
    assets = []
    if exe:
        a = {"name": "EasyPrint.exe", "browser_download_url": BASE + "EasyPrint.exe", "size": len(NEW_EXE)}
        if digest:
            a["digest"] = digest
        assets.append(a)
    if sha_text is not None:
        assets.append({"name": "EasyPrint.exe.sha256", "browser_download_url": BASE + "EasyPrint.exe.sha256"})
    return {"tag_name": tag, "assets": assets, **extra}


def make_fetch(rel, body=NEW_EXE, sha_text=SHA):
    def fetch(url, accept=""):
        if url == updater.LATEST_API:
            if rel == 404:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return io.BytesIO(json.dumps(rel).encode())
        if url.endswith(".sha256"):
            return io.BytesIO(f"{sha_text}  EasyPrint.exe\n".encode())
        if url.endswith(".exe"):
            return io.BytesIO(body)
        raise AssertionError(url)
    return fetch


def test_versions():
    assert updater.parse_version("v1.10.0") == (1, 10, 0)
    assert updater.is_newer("v1.10.0", "1.9.9")
    assert not updater.is_newer("1.2.0", "1.2.0")
    assert not updater.is_newer("v1.1.9", "1.2.0")


def test_check_finds_newer_release():
    info = updater.check("1.2.0", make_fetch(release()))
    assert info == UpdateInfo("9.9.9", BASE + "EasyPrint.exe", SHA, len(NEW_EXE))


def test_check_no_update_cases():
    assert updater.check("9.9.9", make_fetch(release())) is None
    assert updater.check("1.0", make_fetch(release(prerelease=True))) is None
    assert updater.check("1.0", make_fetch(404)) is None  # 릴리스가 아직 없음


def test_check_uses_github_digest_when_no_sha_file():
    info = updater.check("1.0", make_fetch(release(sha_text=None, digest="sha256:" + SHA)))
    assert info.sha256 == SHA


def test_check_refuses_unverifiable_release():
    with pytest.raises(UpdateError):
        updater.check("1.0", make_fetch(release(sha_text=None)))
    with pytest.raises(UpdateError):
        updater.check("1.0", make_fetch(release(exe=False)))


def test_update_now_replaces_exe(tmp_path):
    exe = tmp_path / "EasyPrint.exe"
    exe.write_bytes(b"old build")
    seen = []
    ver = updater.update_now(exe, "1.2.0", make_fetch(release()), progress=lambda d, t: seen.append((d, t)))
    assert ver == "9.9.9"
    assert exe.read_bytes() == NEW_EXE
    assert updater.old_path(exe).read_bytes() == b"old build"
    assert seen[-1] == (len(NEW_EXE), len(NEW_EXE))
    updater.cleanup(exe)
    assert not updater.old_path(exe).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["EasyPrint.exe"]


def test_tampered_download_is_rejected_and_exe_untouched(tmp_path):
    exe = tmp_path / "EasyPrint.exe"
    exe.write_bytes(b"old build")
    bad = NEW_EXE[:-1] + b"X"
    with pytest.raises(UpdateError):
        updater.update_now(exe, "1.2.0", make_fetch(release(), body=bad))
    assert exe.read_bytes() == b"old build"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["EasyPrint.exe"]


def test_truncated_download_is_rejected(tmp_path):
    exe = tmp_path / "EasyPrint.exe"
    exe.write_bytes(b"old")
    with pytest.raises(UpdateError):
        updater.update_now(exe, "1.2.0", make_fetch(release(), body=NEW_EXE[:100]))
    assert exe.read_bytes() == b"old"


def test_apply_rolls_back_when_new_file_missing(tmp_path):
    exe = tmp_path / "EasyPrint.exe"
    exe.write_bytes(b"old")
    with pytest.raises(OSError):
        updater.apply(tmp_path / "없음.exe", exe)
    assert exe.read_bytes() == b"old" and not updater.old_path(exe).exists()


def test_not_frozen_means_no_install():
    assert updater.ensure_installed([]) is False  # 파이썬으로 실행 중이면 설치/업데이트 안 함


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")
def test_replace_running_exe_on_windows(tmp_path):
    """실제 Windows 에서 '실행 중인 exe' 를 교체할 수 있는지 (자동 업데이트의 핵심 전제)."""
    import os
    import shutil
    import subprocess
    import time

    exe = tmp_path / "running.exe"
    shutil.copy2(os.path.join(os.environ["SystemRoot"], "System32", "ping.exe"), exe)
    proc = subprocess.Popen([str(exe), "-n", "8", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        time.sleep(1)
        assert proc.poll() is None, "테스트용 프로세스가 실행 중이어야 함"
        with pytest.raises(PermissionError):
            exe.write_bytes(b"x")  # 실행 중인 exe 는 덮어쓸 수 없음 (그래서 이름 변경 방식을 씀)
        new = tmp_path / "running.exe.new"
        new.write_bytes(b"new build")
        updater.apply(new, exe)
        assert exe.read_bytes() == b"new build"
        assert updater.old_path(exe).exists()
        updater.cleanup(exe)  # 아직 실행 중이라 못 지워도 예외 없이 넘어가야 함
    finally:
        proc.kill()
        proc.wait()
    time.sleep(0.5)
    updater.cleanup(exe)
    assert not updater.old_path(exe).exists()  # 프로세스 종료 후에는 정리됨
