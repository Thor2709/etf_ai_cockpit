"""Windows-user-bound storage for provider credentials."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from etf_cockpit.security.policy import SecurityPolicyError


class CredentialVaultError(SecurityPolicyError):
    """A provider credential could not be read or safely persisted."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class CredentialVault:
    """Store provider credentials encrypted by the current Windows user."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None

    def get(self, account: str) -> str | None:
        name = _account_name(account)
        if not _dpapi_available():
            return None
        path = self._path()
        if path is None or not path.exists():
            return None
        try:
            entries = self._read_entries(path)
        except CredentialVaultError:
            raise
        except Exception:
            raise CredentialVaultError(
                "The stored credential cannot be recovered for this Windows user; re-enter it."
            ) from None
        return entries.get(name)

    def set(self, account: str, value: str) -> None:
        name = _account_name(account)
        secret = str(value)
        if not secret.strip():
            raise CredentialVaultError("A non-empty provider credential is required.")
        path = self._path(required=True)
        assert path is not None
        _invalidate_probe_cache(name)
        try:
            entries = self._read_entries(path) if path.exists() else {}
            entries[name] = secret
            self._write_entries(path, entries)
        except CredentialVaultError:
            raise
        except Exception:
            raise CredentialVaultError("The provider credential could not be protected and saved.") from None

    def delete(self, account: str) -> None:
        name = _account_name(account)
        if not _dpapi_available():
            raise CredentialVaultError("Windows DPAPI is unavailable; credentials remain disabled.")
        path = self._path()
        _invalidate_probe_cache(name)
        if path is not None and path.exists():
            try:
                entries = self._read_entries(path)
                entries.pop(name, None)
                if entries:
                    self._write_entries(path, entries)
                else:
                    path.unlink(missing_ok=True)
            except CredentialVaultError:
                raise
            except Exception:
                raise CredentialVaultError("The provider credential could not be deleted safely.") from None

    def status(self) -> dict[str, str]:
        """Report whether credentials can be safely stored for this user."""

        if not _dpapi_available():
            return {"status": "unavailable", "reason": "Windows DPAPI is unavailable; credentials remain disabled."}
        if self._path() is None:
            return {"status": "unavailable", "reason": "The Windows user credential location is unavailable."}
        return {"status": "available", "reason": "Credentials are protected for the current Windows user."}

    def _path(self, *, required: bool = False) -> Path | None:
        if required and not _dpapi_available():
            raise CredentialVaultError("Windows DPAPI is unavailable; credentials remain disabled.")
        if self.path is not None:
            return self.path
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "etf-ai-cockpit" / "provider_credentials.dpapi"
        if required:
            raise CredentialVaultError("The Windows user credential location is unavailable.")
        return None

    @staticmethod
    def _read_entries(path: Path) -> dict[str, str]:
        try:
            encrypted = path.read_bytes()
            payload = json.loads(_unprotect(encrypted).decode("utf-8"))
        except CredentialVaultError:
            raise
        except Exception:
            raise CredentialVaultError(
                "The stored credential cannot be recovered for this Windows user; re-enter it."
            ) from None
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("credentials"), dict)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in payload["credentials"].items())
        ):
            raise CredentialVaultError("The credential vault is invalid; re-enter provider credentials.")
        return payload["credentials"]

    @staticmethod
    def _write_entries(path: Path, entries: dict[str, str]) -> None:
        payload = json.dumps(
            {"schema_version": 1, "credentials": entries},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encrypted = _protect(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def _account_name(account: str) -> str:
    name = str(account).strip()
    if not name:
        raise CredentialVaultError("A provider name is required.")
    return name


def _protect(payload: bytes) -> bytes:
    if not _dpapi_available():
        raise CredentialVaultError("Windows DPAPI is unavailable; credentials remain disabled.")
    try:
        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        source, source_buffer = _blob(payload)
        protected = _DataBlob()
        if not crypt32.CryptProtectData(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(protected)):
            raise CredentialVaultError("Windows DPAPI could not protect the provider credential.")
        try:
            return ctypes.string_at(protected.pbData, protected.cbData)
        finally:
            kernel32.LocalFree(protected.pbData)
    except CredentialVaultError:
        raise
    except Exception:
        raise CredentialVaultError("Windows DPAPI could not protect the provider credential.") from None


def _unprotect(payload: bytes) -> bytes:
    if not _dpapi_available():
        raise CredentialVaultError("Windows DPAPI is unavailable; the stored credential cannot be recovered.")
    try:
        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        source, source_buffer = _blob(payload)
        unprotected = _DataBlob()
        if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(unprotected)):
            raise CredentialVaultError(
                "The stored credential cannot be recovered for this Windows user; re-enter it."
            )
        try:
            return ctypes.string_at(unprotected.pbData, unprotected.cbData)
        finally:
            kernel32.LocalFree(unprotected.pbData)
    except CredentialVaultError:
        raise
    except Exception:
        raise CredentialVaultError(
            "The stored credential cannot be recovered for this Windows user; re-enter it."
        ) from None


def _blob(payload: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(payload, max(len(payload), 1))
    return _DataBlob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi_available() -> bool:
    return os.name == "nt"


def _invalidate_probe_cache(provider_name: str) -> None:
    try:
        from etf_cockpit.data.provider_registry import invalidate_cached_probe_results

        invalidate_cached_probe_results(provider_name)
    except Exception:
        raise CredentialVaultError("The credential changed, but cached provider probes could not be invalidated.") from None


__all__ = ["CredentialVault", "CredentialVaultError"]
