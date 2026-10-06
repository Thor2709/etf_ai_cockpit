"""Dependency-free persistent sidecar guards for local filesystem protocols."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable
import errno
import os
from pathlib import Path
import time
from typing import IO, Any, Iterator


_DEFAULT_POLL_SECONDS = 0.01
_WINDOWS_LOCK_VIOLATION = 33
_WINDOWS_SHARING_VIOLATION = 32
_monotonic = time.monotonic
_sleep = time.sleep


class PersistentFileGuard:
    """Hold an exclusive OS lock on a never-unlinked local sidecar file.

    The sidecar is deliberately persistent: only the OS lock is ephemeral, so
    stale metadata cannot be mistaken for the synchronization primitive.  The
    guard is intended for local filesystems; callers retain the handle for the
    whole critical section and must propagate ACL, filesystem and unlock
    failures rather than treating them as contention.
    """

    def __init__(
        self,
        path: Path,
        *,
        timeout_seconds: float = 5.0,
        poll_seconds: float = _DEFAULT_POLL_SECONDS,
        deadline: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if timeout_seconds < 0:
            raise ValueError("guard timeout must be non-negative")
        if poll_seconds <= 0:
            raise ValueError("guard poll interval must be positive")
        self.path = Path(path).resolve()
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.deadline = deadline
        self.clock = clock or _monotonic
        self._handle: IO[bytes] | None = None
        self._overlapped: Any = None

    def acquire(self) -> "PersistentFileGuard":
        if self._handle is not None:
            raise RuntimeError("file guard is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        deadline = self.deadline
        if deadline is None:
            deadline = self.clock() + self.timeout_seconds
        try:
            while True:
                try:
                    if os.name == "nt":
                        self._try_windows_lock(handle)
                    else:
                        self._try_posix_lock(handle)
                except BlockingIOError:
                    if self.clock() >= deadline:
                        raise TimeoutError(f"timed out waiting for file guard: {self.path}")
                    _sleep(self.poll_seconds)
                    continue
                self._handle = handle
                return self
        except BaseException:
            handle.close()
            self._overlapped = None
            raise

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        unlock_error: BaseException | None = None
        try:
            if os.name == "nt":
                self._unlock_windows(handle)
            else:
                self._unlock_posix(handle)
        except BaseException as error:  # preserve exact unlock failure
            unlock_error = error
        try:
            handle.close()
        except BaseException as error:
            if unlock_error is None:
                unlock_error = error
        finally:
            self._handle = None
            self._overlapped = None
        if unlock_error is not None:
            raise unlock_error

    def __enter__(self) -> "PersistentFileGuard":
        return self.acquire()

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        self.release()

    @staticmethod
    def _try_posix_lock(handle: IO[bytes]) -> None:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                raise BlockingIOError(errno.EAGAIN, "file guard is contended") from error
            raise

    @staticmethod
    def _unlock_posix(handle: IO[bytes]) -> None:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]

    def _try_windows_lock(self, handle: IO[bytes]) -> None:
        import ctypes
        from ctypes import wintypes
        import msvcrt

        class Overlapped(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.c_void_p),
                ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE),
            ]

        overlap = Overlapped()
        self._overlapped = overlap
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        lock_file = kernel32.LockFileEx
        lock_file.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(Overlapped),
        ]
        lock_file.restype = wintypes.BOOL
        flags = 0x00000001 | 0x00000002  # FAIL_IMMEDIATELY | EXCLUSIVE_LOCK
        result = lock_file(
            wintypes.HANDLE(msvcrt.get_osfhandle(handle.fileno())),
            flags,
            0,
            1,
            0,
            ctypes.byref(overlap),
        )
        if result:
            return
        code = ctypes.get_last_error()
        self._overlapped = None
        if code in {_WINDOWS_LOCK_VIOLATION, _WINDOWS_SHARING_VIOLATION}:
            raise BlockingIOError(errno.EAGAIN, "file guard is contended")
        raise ctypes.WinError(code)

    def _unlock_windows(self, handle: IO[bytes]) -> None:
        import ctypes
        from ctypes import wintypes
        import msvcrt

        overlap = self._overlapped
        if overlap is None:
            raise RuntimeError("Windows file guard has no lock state")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        unlock_file = kernel32.UnlockFileEx
        unlock_file.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        unlock_file.restype = wintypes.BOOL
        result = unlock_file(
            wintypes.HANDLE(msvcrt.get_osfhandle(handle.fileno())),
            0,
            1,
            0,
            ctypes.byref(overlap),
        )
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def persistent_file_guard(
    path: Path,
    *,
    timeout_seconds: float = 5.0,
    poll_seconds: float = _DEFAULT_POLL_SECONDS,
    deadline: float | None = None,
    clock: Callable[[], float] | None = None,
) -> Iterator[PersistentFileGuard]:
    """Acquire and release one persistent local sidecar guard."""

    guard = PersistentFileGuard(
        path,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
        deadline=deadline,
        clock=clock,
    )
    guard.acquire()
    try:
        yield guard
    except BaseException as body_error:
        try:
            guard.release()
        except BaseException as release_error:
            raise body_error from release_error
        raise
    else:
        guard.release()
