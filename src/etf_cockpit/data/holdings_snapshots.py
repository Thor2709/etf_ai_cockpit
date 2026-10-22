"""Append-only raw holdings snapshots using existing guard/atomic publication.

The first collection is <as_of>.json, revisions are <as_of>.<hash>.json;
historical imports live in a separate directory and never replace collections.
Each envelope preserves exact bytes, source, capture time and canonical row
names. This is acquisition evidence, not the score-eligible parquet store.
Collected reads enforce receipt and publication times. Licensed/manual history
uses its explicit source known_at for historical replay. Revision numbers are
per fund/date/origin, allocated under the existing interprocess guard; historical
corrections must advance their source knowledge time as well as receipt time.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import safe_file_stem
from etf_cockpit.data.fund_holdings import holdings_store_guard
from etf_cockpit.data.ishares_holdings import parse_ishares_csv, utc_timestamp
from etf_cockpit.data.market_calendar import ListingCalendarEvidence, MarketCalendarService


def _directory(root: Path, instrument_id: str) -> Path:
    if not instrument_id.strip():
        raise ValueError("instrument identity required")
    return Path(root) / "data" / "raw" / "holdings_snapshots" / safe_file_stem(instrument_id)


def _read(path: Path) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    raw = base64.b64decode(record["payload_base64"], validate=True)
    if hashlib.sha256(raw).hexdigest() != record["content_hash"]:
        raise ValueError("holdings snapshot hash mismatch")
    return record


def write_snapshot(root: Path, payload: bytes, *, instrument_id: str, source_url: str,
                   fetched_at: str | datetime, listing: ListingCalendarEvidence,
                   origin: str = "collected", known_at: str | datetime | None = None,
                   licence_ref: str | None = None, **parser_options) -> dict:
    receipt = utc_timestamp(fetched_at)
    if origin not in {"collected", "historical"} or (origin == "collected" and known_at is not None):
        raise ValueError("unsupported snapshot origin or publication override")
    if origin == "historical" and (known_at is None or not licence_ref or not licence_ref.strip()):
        raise ValueError("historical files require proven known_at and licence/manual provenance")
    parsed = parse_ishares_csv(payload, instrument_id=instrument_id, source_url=source_url,
                               listing=listing, known_at=known_at, **parser_options)
    if date.fromisoformat(parsed["as_of"]) > receipt.date():
        raise ValueError("future as-of snapshot")
    if origin == "historical" and utc_timestamp(parsed["known_at"]) > receipt:
        raise ValueError("historical publication is after receipt")
    directory = _directory(root, instrument_id)
    target_dir = directory if origin == "collected" else directory / "historical"
    digest = hashlib.sha256(payload).hexdigest()
    with holdings_store_guard(directory / "snapshots"):
        existing = [_read(path) for path in sorted(target_dir.glob(parsed["as_of"] + "*.json"))]
        for record in existing:
            if record["content_hash"] == digest:
                if origin == "historical" and (record["known_at"] != parsed["known_at"] or record["licence_ref"] != licence_ref):
                    raise ValueError("conflicting historical provenance for identical payload")
                return dict(status="unchanged", snapshot=record)
        if existing and receipt <= max(utc_timestamp(row["fetched_at"]) for row in existing):
            raise ValueError("revision receipt time must advance")
        if (origin == "historical" and existing and utc_timestamp(parsed["known_at"]) <=
                max(utc_timestamp(row["known_at"]) for row in existing)):
            raise ValueError("historical revision source known_at must advance")
        revision = len(existing) + 1
        suffix = "" if revision == 1 else "." + digest
        destination = target_dir / (parsed["as_of"] + suffix + ".json")
        if destination.exists():
            raise ValueError("refusing snapshot overwrite")
        record = dict(parsed, schema_version=1, content_hash=digest, source_url=source_url,
                      fetched_at=receipt.isoformat(), origin=origin, revision=revision,
                      licence_ref=licence_ref, payload_base64=base64.b64encode(payload).decode("ascii"))
        atomic_write_json(destination, record)
        return dict(status="created" if revision == 1 else "revision", snapshot=record)


def import_historical(root: Path, path: Path, *, known_at: str | datetime,
                      licence_ref: str, **options) -> dict:
    """Import a licensed/manual CSV with its documented publication timestamp.

    source_url may be a documented local file URI for manually supplied files;
    licence_ref is the licence reference or explicit manual provenance note.
    """
    return write_snapshot(root, Path(path).read_bytes(), origin="historical",
                          known_at=known_at, licence_ref=licence_ref, **options)


def load_snapshots(root: Path, instrument_id: str, *, decision_time: str | datetime) -> list[dict]:
    """Latest revision per date/origin available by the decision timestamp."""
    cutoff = utc_timestamp(decision_time)
    latest = {}
    for path in sorted(_directory(root, instrument_id).glob("**/*.json")):
        row = _read(path)
        if row["instrument_id"] != instrument_id:
            raise ValueError("snapshot identity mismatch")
        available = utc_timestamp(row["known_at"])
        if row["origin"] == "collected":
            available = max(available, utc_timestamp(row["fetched_at"]))
        elif row["origin"] != "historical":
            raise ValueError("unknown snapshot origin")
        if available > cutoff:
            continue
        key = (row["as_of"], row["origin"])
        if key not in latest or row["revision"] > latest[key]["revision"]:
            latest[key] = row
    return [latest[key] for key in sorted(latest)]


def gap_report(root: Path, instrument_id: str, *, start: date, end: date,
               listing: ListingCalendarEvidence, decision_time: str | datetime,
               calendar: MarketCalendarService | None = None) -> list[str]:
    """Inclusive missing business dates; never synthesize zero holdings."""
    cutoff = utc_timestamp(decision_time)
    if start > end or end > cutoff.date() or listing.instrument_id != instrument_id:
        raise ValueError("invalid gap interval or identity")
    present = {row["as_of"] for row in load_snapshots(root, instrument_id, decision_time=cutoff)}
    service = calendar or MarketCalendarService()
    missing = []
    day = start
    while day <= end:
        if service.is_business_day(listing, day, knowledge_cutoff=cutoff) and day.isoformat() not in present:
            missing.append(day.isoformat())
        day += timedelta(days=1)
    return missing
