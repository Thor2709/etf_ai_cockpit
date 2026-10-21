"""Application-layer facade for backup housekeeping that the UI shell triggers at startup."""

from __future__ import annotations


def sweep_decrypted_backup_temp(*, max_age_seconds: float) -> int:
    """Remove decrypted-backup temp directories older than ``max_age_seconds``; returns how many were removed."""

    from etf_cockpit.data.backup_restore import sweep_stale_plaintext_temp

    return int(sweep_stale_plaintext_temp(max_age_seconds=max_age_seconds))
