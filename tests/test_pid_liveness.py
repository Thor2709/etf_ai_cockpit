from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

import pytest

from etf_cockpit.core import atomic_io, process
from etf_cockpit.data import screen_store


def test_consumers_use_the_canonical_pid_probe() -> None:
    assert atomic_io._pid_alive is process.pid_is_alive
    assert screen_store._pid_alive is process.pid_is_alive


@pytest.mark.parametrize("pid", [0, -1])
def test_pid_probe_rejects_non_positive_pids(pid: int) -> None:
    assert process.pid_is_alive(pid) is False


def test_posix_pid_probe_treats_permission_denied_as_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    def denied(pid: int, signal: int) -> None:
        calls.append((pid, signal))
        raise PermissionError("probe denied")

    monkeypatch.setattr(process.os, "name", "posix")
    monkeypatch.setattr(process.os, "kill", denied)
    assert process.pid_is_alive(42) is True
    assert calls == [(42, 0)]


def test_posix_pid_probe_treats_other_os_errors_as_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process.os, "name", "posix")
    monkeypatch.setattr(process.os, "kill", lambda *_args: (_ for _ in ()).throw(ProcessLookupError()))
    assert process.pid_is_alive(42) is False


class _FakeKernel32:
    def __init__(self, handle: int | None, exit_code: int = 259, query_succeeds: bool = True) -> None:
        self.handle = handle
        self.exit_code = exit_code
        self.query_succeeds = query_succeeds
        self.open_calls: list[tuple[int, bool, int]] = []
        self.exit_calls: list[int] = []
        self.closed: list[int] = []
        self.OpenProcess = _FakeFunction(self._open_process)
        self.GetExitCodeProcess = _FakeFunction(self._get_exit_code_process)
        self.CloseHandle = _FakeFunction(self._close_handle)

    def _open_process(self, access: int, inherit: bool, pid: int) -> int | None:
        self.open_calls.append((access, inherit, pid))
        return self.handle

    def _close_handle(self, handle: int) -> None:
        self.closed.append(handle)

    def _get_exit_code_process(self, handle: int, output) -> bool:
        self.exit_calls.append(handle)
        if not self.query_succeeds:
            return False
        output._obj.value = self.exit_code
        return True


class _FakeFunction:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.argtypes: object = None
        self.restype: object = None

    def __call__(self, *args):
        return self.callback(*args)


class _FakeCtypes:
    def __init__(self, kernel32: _FakeKernel32, last_error: int) -> None:
        self.kernel32 = kernel32
        self.last_error = last_error
        self.wintypes = wintypes
        self.byref = ctypes.byref

    def WinDLL(self, _name: str, *, use_last_error: bool) -> _FakeKernel32:
        assert use_last_error is True
        return self.kernel32

    def get_last_error(self) -> int:
        return self.last_error


@pytest.mark.parametrize(
    ("handle", "last_error", "expected"),
    [(123, 0, True), (None, 5, True), (None, 87, False)],
)
def test_windows_pid_probe_uses_query_only_open_and_closes_handle(
    monkeypatch: pytest.MonkeyPatch,
    handle: int | None,
    last_error: int,
    expected: bool,
) -> None:
    kernel32 = _FakeKernel32(handle)
    monkeypatch.setattr(process.os, "name", "nt")
    monkeypatch.setattr(process, "ctypes", _FakeCtypes(kernel32, last_error))
    assert process.pid_is_alive(42) is expected
    assert kernel32.open_calls == [(0x1000, False, 42)]
    assert kernel32.exit_calls == ([123] if handle else [])
    assert kernel32.closed == ([123] if handle else [])
    assert kernel32.OpenProcess.argtypes == [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    assert kernel32.OpenProcess.restype is wintypes.HANDLE
    assert kernel32.GetExitCodeProcess.argtypes == [wintypes.HANDLE, wintypes.LPDWORD]
    assert kernel32.GetExitCodeProcess.restype is wintypes.BOOL
    assert kernel32.CloseHandle.argtypes == [wintypes.HANDLE]
    assert kernel32.CloseHandle.restype is wintypes.BOOL


@pytest.mark.parametrize(
    ("exit_code", "query_succeeds", "expected"),
    [(259, True, True), (0, True, False), (0, False, True)],
)
def test_windows_pid_probe_checks_exit_code_and_fails_closed_on_query_failure(
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    query_succeeds: bool,
    expected: bool,
) -> None:
    kernel32 = _FakeKernel32(123, exit_code, query_succeeds)
    monkeypatch.setattr(process.os, "name", "nt")
    monkeypatch.setattr(process, "ctypes", _FakeCtypes(kernel32, 0))
    assert process.pid_is_alive(42) is expected
    assert kernel32.exit_calls == [123]
    assert kernel32.closed == [123]


@pytest.mark.parametrize("last_error", [5, 8, 1816])
def test_windows_pid_probe_fails_closed_for_indeterminate_open_errors(
    monkeypatch: pytest.MonkeyPatch, last_error: int
) -> None:
    kernel32 = _FakeKernel32(None)
    monkeypatch.setattr(process.os, "name", "nt")
    monkeypatch.setattr(process, "ctypes", _FakeCtypes(kernel32, last_error))
    assert process.pid_is_alive(42) is True


@pytest.mark.skipif(os.name != "nt", reason="requires Windows OpenProcess semantics")
def test_windows_pid_probe_does_not_terminate_a_child_process() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert process.pid_is_alive(child.pid) is True
        assert child.poll() is None
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="requires Windows OpenProcess semantics")
def test_windows_pid_probe_detects_exited_child_before_popen_handle_closes() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        assert child.wait(timeout=5) == 0
        # Popen retains its process handle after wait; the probe must inspect
        # the exit code rather than treating that still-open handle as alive.
        assert process.pid_is_alive(child.pid) is False
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
