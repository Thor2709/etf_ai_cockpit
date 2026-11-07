"""Stamp ``filed`` (the proven publication date) on ESEF statement facts imported by the point-in-time backfill.

Usage: python scripts/pit_stamp_esef_filed.py --root PATH --import-log data/pit_history/esef_generic_import_log.jsonl

Facts imported before ``filed`` was recorded carry only ``known_at``; for a filing imported with its registry ``date_added`` as
``known_at`` the import log keeps that date_added and the package sha256, so the publication date is recoverable exactly. Only
facts whose ``filing_version`` equals the sha256 of an ``imported`` log entry are stamped, and only when ``filed`` is empty.
No network; rewrites data/clean/statement_facts.parquet under the chosen root.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file
from etf_cockpit.parsers.sec_facts import esef_publication_date


def stamp_filed(facts: pd.DataFrame, log_lines: list[str]) -> tuple[pd.DataFrame, int]:
    published: dict[str, str] = {}
    for line in log_lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("status") == "imported" and entry.get("sha256") and entry.get("date_added"):
            published[str(entry["sha256"])] = esef_publication_date(str(entry["date_added"]))
    if facts.empty or "filing_version" not in facts.columns:
        return facts, 0
    result = facts.copy()
    if "form" not in result.columns:
        return result, 0  # no proof these are ESEF facts
    if "filed" not in result.columns:
        result["filed"] = None
    empty = result["filed"].isna() | result["filed"].astype(str).str.strip().isin(["", "None"])
    stamp = result["filing_version"].astype(str).map(published)
    mask = empty & stamp.notna() & result["form"].astype(str).eq("ESEF")
    result.loc[mask, "filed"] = stamp[mask]
    return result, int(mask.sum())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--import-log", required=True, type=Path)
    args = parser.parse_args()
    path = args.root / "data" / "clean" / "statement_facts.parquet"
    facts = pd.read_parquet(path)
    stamped, count = stamp_filed(facts, args.import_log.read_text(encoding="utf-8").splitlines())
    if count:
        atomic_write_bytes(path, parquet_payload(stamped), validate_parquet_file)
    print(f"stamped filed on {count} of {len(facts)} ESEF facts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
