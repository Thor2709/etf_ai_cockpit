"""Import a user-downloaded FinanceDatabase copy as current, low-authority identity hints.

Reads ``database/{equities,etfs}/<EXCHANGE>.csv`` plus ``SOURCE.json`` (version,
revision, per-file sha256) from a local folder; no network access. Every file is
verified against its recorded sha256 before any row is read. Rows become
``community``-authority ``financedatabase`` identity rows observed at the import
time; they attach to an existing instrument only through an exact ISIN, CUSIP or
FIGI match, so an official identity always outranks them. Rows flagged
``delisted`` are skipped and no validity interval is inferred. Nothing here
enables execution or reaches a broker or provider.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore, IdentitySourceRow

SOURCE = "financedatabase"
_KINDS = ("equities", "etfs")
_IDENTIFIERS = ("isin", "cusip", "figi")
_ATTRIBUTES = {"symbol": "provider_symbol", "name": "name", "currency": "currency", "mic": "mic"}


def import_financedatabase(
    source_dir: Path, store: IdentityMasterStore, *, imported_at: datetime
) -> dict[str, Any]:
    if imported_at.tzinfo is None:
        raise ValueError("imported_at must be timezone-aware")
    source_dir = Path(source_dir)
    meta = json.loads((source_dir / "SOURCE.json").read_text(encoding="utf-8"))
    version, revision = str(meta["version"]), str(meta["revision"])
    expected = {
        Path(item["file"]).as_posix().rsplit("/database/", 1)[-1]: str(item["sha256"]).lower()
        for item in meta["files"]
        if "/database/" in Path(item["file"]).as_posix()
    }
    stamp = imported_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary: dict[str, Any] = {
        "source": SOURCE, "version": version, "revision": revision, "imported_at": imported_at.isoformat(),
        "rows_imported": 0, "rows_skipped_delisted": 0, "resolved": 0, "unresolved": 0, "quarantined": 0,
        "files": {}, "execution_allowed": False,
    }
    batches: list[tuple[str, str, bytes]] = []
    for kind in _KINDS:
        for path in sorted((source_dir / "database" / kind).glob("*.csv")):
            relative = f"{kind}/{path.name}"
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if expected.get(relative) != digest:
                raise ValueError(f"{relative}: sha256 {digest} does not match SOURCE.json")
            summary["files"][relative] = digest
            batches.append((relative, digest, payload))
    for relative, digest, payload in batches:
        rows: list[IdentitySourceRow] = []
        for record in csv.DictReader(io.StringIO(payload.decode("utf-8"), newline="")):
            if str(record.get("delisted", "")).strip().casefold() == "true":
                summary["rows_skipped_delisted"] += 1
                continue
            symbol = str(record.get("symbol", "")).strip()
            if not symbol:
                continue
            source_id = f"{SOURCE}:{version}:{revision[:8]}:{relative}:{symbol}"
            rows.append(
                IdentitySourceRow(
                    row_id=f"{source_id}:{stamp}",
                    instrument_id="",
                    object_type="instrument",
                    object_id="",
                    parent_object_id=None,
                    relationship=None,
                    identifiers=_picked(record, {name: name for name in _IDENTIFIERS}),
                    attributes=_picked(record, _ATTRIBUTES),
                    source=SOURCE,
                    authority=SourceAuthority.COMMUNITY,
                    source_id=source_id,
                    available_at=imported_at.isoformat(),
                    retrieved_at=imported_at.isoformat(),
                    source_checksum=digest,
                )
            )
        result = store.import_rows(rows)
        summary["rows_imported"] += len(rows)
        summary["resolved"] += len(result.resolved_row_ids)
        summary["unresolved"] += len(result.unresolved_row_ids)
        summary["quarantined"] += len(result.quarantined_row_ids)
    return summary


def _picked(record: Mapping[str, str | None], fields: Mapping[str, str]) -> dict[str, str]:
    return {target: str(record[column]).strip() for column, target in fields.items() if str(record.get(column) or "").strip()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="folder holding SOURCE.json and database/")
    parser.add_argument("--root", required=True, type=Path, help="local storage root of the identity master")
    args = parser.parse_args(argv)
    try:
        with IdentityMasterStore(args.root) as store:
            summary = import_financedatabase(args.source, store, imported_at=datetime.now(timezone.utc))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"import refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
