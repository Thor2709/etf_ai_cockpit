"""Stream a local GLEIF CSV into an immutable, content-addressed mapping.

File date and source are mandatory provenance, not proof of historical identity.
Mapping known_at must be supplied separately by ingestion; historical LEI
changes cannot be inferred from today's file. Conflicting joins fail closed.
The expected bulk headers are configurable because live shape is unverified.
"""
from __future__ import annotations

import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.data.universe_store import is_valid_isin


def load_mapping(path: Path, *, source: str, file_date: str, store_dir: Path,
                 isin_column: str = "ISIN", lei_column: str = "LEI"):
    """Return a read-only mapping, unmapped ISIN tuple, and immutable store path."""
    if not source.strip():
        raise ValueError("mapping source is required")
    date.fromisoformat(file_date)
    mapping, unmapped = {}, set()
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {isin_column, lei_column} <= set(reader.fieldnames or []):
            raise ValueError("GLEIF CSV headers do not match configured shape")
        for row in reader:
            isin, lei = row[isin_column].strip(), row[lei_column].strip()
            if not is_valid_isin(isin):
                raise ValueError("mapping row requires ISIN")
            if not lei:
                unmapped.add(isin)
                continue
            if not re.fullmatch(r"[A-Z0-9]{18}[0-9]{2}", lei):
                raise ValueError("invalid LEI")
            if isin in mapping and mapping[isin] != lei:
                raise ValueError("conflicting ISIN-to-LEI mapping")
            mapping[isin] = lei
    unmapped -= mapping.keys()
    payload = json.dumps(dict(source=source, file_date=file_date, sha256=digest.hexdigest(),
                              mapping=dict(sorted(mapping.items())), unmapped=sorted(unmapped)),
                         sort_keys=True).encode()
    target = Path(store_dir) / (hashlib.sha256(payload).hexdigest() + ".json")
    if target.exists():
        if target.read_bytes() != payload:
            raise ValueError("immutable mapping checksum mismatch")
    else:
        atomic_write_bytes(target, payload, lambda p: json.loads(p.read_text()))
    return MappingProxyType(mapping), tuple(sorted(unmapped)), target
