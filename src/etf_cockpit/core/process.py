"""Small, non-destructive process inspection helpers."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87
_STILL_ACTIVE = 259


def pid_is_alive(pid: int) -> bool:
    """Return whether *pid* currently names a live process.

    Windows uses ``OpenProcess`` with query-only access so probing a PID does
    not signal or terminate it.  POSIX uses the conventional signal-zero
    probe, which does not deliver a signal; permission denial still proves
    that the process exists.
    """

    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            # Explicit signatures keep pointer-sized process handles intact
            # on 64-bit Windows while remaining compatible with test doubles.
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
        except AttributeError:
            pass
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        # An inability to inspect the PID is indeterminate.  Returning alive
        # prevents callers from reclaiming a lock they cannot prove stale.
        return True
    if not handle:
        try:
            error = ctypes.get_last_error()
        except Exception:
            return True
        # OpenProcess documents ERROR_INVALID_PARAMETER as the definitive
        # nonexistent-process result.  Every other failure is indeterminate.
        if error == _ERROR_ACCESS_DENIED:
            return True
        return error != _ERROR_INVALID_PARAMETER
    try:
        exit_code = wintypes.DWORD()
        try:
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
        except Exception:
            return True
        return int(exit_code.value) == _STILL_ACTIVE
    finally:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            # The process was successfully opened; a close failure must not
            # turn a positive liveness result into an unsafe reclamation.
            pass
