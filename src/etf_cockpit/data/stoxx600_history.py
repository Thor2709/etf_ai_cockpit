"""Research-only STOXX history from local, licensed, complete CSV inputs.

The caller must attest complete announcements from history_start through as_of
and provide the snapshot's proven known_at. No membership before history_start
is inferred. Dates without a time are conservatively known at UTC end of day.
Intervals are half open. Unknown entry dates use the explicit coverage bound;
their known_at remains the snapshot or deletion evidence, never that bound.
instrument_id is deliberately supplied by the existing universe store, not ISIN.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timezone
from pathlib import Path

import pandas as pd

from etf_cockpit.data.universe_store import is_valid_isin

SCOPE = "listing:stoxx600:all"


def known_timestamp(value: str) -> str:
    text = str(value).strip()
    if len(text) == 10:
        parsed = datetime.combine(date.fromisoformat(text), time.max, timezone.utc)
    else:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("known_at requires a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _rows(path: Path, columns: set[str]) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not columns <= set(reader.fieldnames or []):
            raise ValueError(f"CSV requires columns {sorted(columns)}")
        rows = list(reader)
    for row in rows:
        if not is_valid_isin(row.get("ISIN")):
            raise ValueError("row requires a valid non-empty ISIN")
        if not str(row.get("name") or "").strip():
            raise ValueError("row requires name")
    return rows


def load_history(snapshot: Path, changes: Path, *, snapshot_known_at: str,
                 history_start: str, complete_history: bool = False) -> pd.DataFrame:
    """Roll back adds/deletes; retain closed intervals and announcement revisions."""
    if complete_history is not True:
        raise ValueError("complete announcement history must be explicitly attested")
    seed = _rows(snapshot, {"ISIN", "name", "country", "as_of"})
    events = _rows(changes, {"effective_date", "announced_date", "action", "ISIN", "name"})
    if not seed or len({row["as_of"] for row in seed}) != 1:
        raise ValueError("snapshot must have one non-empty as_of")
    end = date.fromisoformat(seed[0]["as_of"]).isoformat()
    start = date.fromisoformat(history_start).isoformat()
    snapshot_known = known_timestamp(snapshot_known_at)
    if start > end or snapshot_known[:10] < end:
        raise ValueError("invalid history coverage or snapshot known_at")
    active = {}
    for row in seed:
        if row["ISIN"] in active or not row["country"].strip():
            raise ValueError("duplicate snapshot ISIN or missing country")
        active[row["ISIN"]] = (row["name"], None, snapshot_known)
    seen = set()
    for row in events:
        effective = date.fromisoformat(row["effective_date"]).isoformat()
        announced = known_timestamp(row["announced_date"])
        key = (effective, row["ISIN"])
        if key in seen or row["action"] not in {"add", "delete"}:
            raise ValueError("duplicate/ambiguous change or invalid action")
        if not start < effective <= end or announced[:10] > effective:
            raise ValueError("change outside coverage or announced after effective date")
        seen.add(key)
    result = []

    def emit(isin, name, valid_from, valid_to, entry_known, exit_known):
        base = dict(ISIN=isin, name=name, valid_from=valid_from, valid_to=None,
                    known_at=entry_known, snapshot_date=valid_from, snapshot_complete=False)
        # An exit is not visible until its announcement. Keep the open version.
        if valid_to is not None and entry_known < exit_known:
            result.append(base)
        result.append({**base, "valid_to": valid_to,
                       "known_at": max(entry_known, exit_known)})

    for row in sorted(events, key=lambda r: (r["effective_date"], r["ISIN"]), reverse=True):
        isin, effective = row["ISIN"], row["effective_date"]
        announced = known_timestamp(row["announced_date"])
        if row["action"] == "add":
            if isin not in active:
                raise ValueError("cannot undo add: ISIN absent from later membership")
            name, exit_date, exit_known = active.pop(isin)
            emit(isin, row["name"], effective, exit_date, announced, exit_known if exit_date else announced)
        else:
            if isin in active:
                raise ValueError("cannot undo delete: ISIN present in later membership")
            active[isin] = (row["name"], effective, announced)
    for isin, (name, exit_date, evidence) in sorted(active.items()):
        emit(isin, name, start, exit_date, evidence, evidence)
    return pd.DataFrame(result).sort_values(["known_at", "valid_from", "ISIN"]).reset_index(drop=True)


def membership_rows(history: pd.DataFrame, identities: dict[str, str]) -> list[dict]:
    missing = set(history["ISIN"]) - identities.keys()
    if missing:
        raise ValueError(f"NEEDS_OPUS_DECISION: no verified instrument_id for {sorted(missing)}")
    return [{**{k: row[k] for k in ("valid_from", "valid_to", "known_at", "snapshot_date", "snapshot_complete")},
             "scope": SCOPE, "instrument_id": identities[row["ISIN"]]}
            for row in history.to_dict("records")]
