"""Copy the history-dated Norwegian classification evidence into another storage root (insert only, idempotent).

``scripts/sparebank_refresh.py --history`` stamps each bank's classification evidence with the available_at of its
first filing in ``data/storage/cockpit.sqlite3`` (``classification_evidence_v2``). Rows are content-addressed, so copying
them with INSERT OR IGNORE never overwrites or duplicates what the target already holds.

Usage: python scripts/pit_history_merge_classification.py --source-root PATH --target-root PATH
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

EVIDENCE_TYPE = "classification_evidence_v2"
PREFIX = "norway_configured_equity_certificate:"


def merge(source_root: Path, target_root: Path) -> int:
    """Number of rows newly inserted into the target."""

    source = Path(source_root) / "data" / "storage" / "cockpit.sqlite3"
    target = Path(target_root) / "data" / "storage" / "cockpit.sqlite3"
    if not source.is_file() or not target.is_file():
        raise FileNotFoundError("both storage roots need data/storage/cockpit.sqlite3")
    with sqlite3.connect(target) as connection:
        connection.execute("ATTACH DATABASE ? AS src", (str(source),))
        before = connection.execute("SELECT COUNT(*) FROM transactional_records").fetchone()[0]
        connection.execute(
            "INSERT OR IGNORE INTO transactional_records(entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at) "
            "SELECT entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at FROM src.transactional_records "
            "WHERE entity_type = ? AND payload_json LIKE ?",
            (EVIDENCE_TYPE, f'%"evidence_id":"{PREFIX}%'),
        )
        after = connection.execute("SELECT COUNT(*) FROM transactional_records").fetchone()[0]
        connection.commit()
        connection.execute("DETACH DATABASE src")
    return int(after - before)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    args = parser.parse_args(argv)
    print(f"inserted {merge(args.source_root, args.target_root)} classification evidence row(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
