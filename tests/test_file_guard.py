from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from etf_cockpit.core.file_guard import PersistentFileGuard, persistent_file_guard


def test_exclusive_contention_times_out_and_release_unblocks(tmp_path: Path) -> None:
    path = tmp_path / ".persistent.guard"
    first = PersistentFileGuard(path, timeout_seconds=1).acquire()
    try:
        contender = PersistentFileGuard(path, timeout_seconds=0.05, poll_seconds=0.005)
        with pytest.raises(TimeoutError):
            contender.acquire()
        first.release()
        contender.acquire()
        contender.release()
    finally:
        first.release()


def test_context_cleanup_is_reverse_safe_on_body_failure(tmp_path: Path) -> None:
    path = tmp_path / ".persistent.guard"
    with pytest.raises(ValueError, match="body failure"):
        with persistent_file_guard(path, timeout_seconds=1):
            raise ValueError("body failure")
    with persistent_file_guard(path, timeout_seconds=1):
        pass


def test_release_error_closes_handle_and_is_not_repeated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".persistent.guard"
    guard = PersistentFileGuard(path, timeout_seconds=1).acquire()
    unlock_name = "_unlock_windows" if os.name == "nt" else "_unlock_posix"
    monkeypatch.setattr(guard, unlock_name, lambda _handle: (_ for _ in ()).throw(OSError("unlock failed")))
    with pytest.raises(OSError, match="unlock failed"):
        guard.release()
    assert guard._handle is None
    guard.release()


def test_repeated_acquire_release_does_not_grow_process_handles(tmp_path: Path) -> None:
    path = tmp_path / ".persistent.guard"

    def count_handles() -> int:
        if os.name == "nt":
            from ctypes import wintypes

            count = ctypes.c_ulong(0)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_current_process = kernel32.GetCurrentProcess
            get_current_process.restype = wintypes.HANDLE
            get_count = kernel32.GetProcessHandleCount
            get_count.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulong)]
            get_count.restype = wintypes.BOOL
            if not get_count(get_current_process(), ctypes.byref(count)):
                raise ctypes.WinError(ctypes.get_last_error())
            return int(count.value)
        return len(list(Path("/proc/self/fd").iterdir()))

    before = count_handles()
    for _ in range(50):
        with persistent_file_guard(path, timeout_seconds=1):
            pass
    after = count_handles()
    assert after <= before + 2


def test_hard_killed_holder_releases_native_lock(tmp_path: Path) -> None:
    path = tmp_path / ".persistent.guard"
    script = (
        "from pathlib import Path; import sys; "
        "from etf_cockpit.core.file_guard import PersistentFileGuard; "
        "g=PersistentFileGuard(Path(sys.argv[1]), timeout_seconds=10).acquire(); "
        "print('ready', flush=True); import time; time.sleep(30)"
    )
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        child.terminate()
        child.wait(timeout=5)
        deadline = time.monotonic() + 2
        while True:
            try:
                with persistent_file_guard(path, timeout_seconds=0.2):
                    return
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
