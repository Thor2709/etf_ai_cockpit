"""Retained copies of user-picked evidence documents (application; ADR-0002)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.paths import RAW_DIR
from etf_cockpit.core.workflow import (
    PublicationScopeFactory,
    publication_scope,
)


def _retain_picker_source(
    path: Path | None,
    subdirectory: str,
    *,
    publish_guard: PublicationScopeFactory | None = None,
) -> Path | None:
    """Retain uploaded bytes under the raw evidence directory before parsing."""

    if path is None or not path.is_file():
        return None
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    suffix = path.suffix.lower() or ".pdf"
    destination = RAW_DIR / subdirectory / f"{digest}{suffix}"
    with publication_scope(publish_guard):
        atomic_write_bytes(
            destination,
            payload,
            validator=lambda candidate: hashlib.sha256(candidate.read_bytes()).hexdigest() == digest,
        )
    return destination
