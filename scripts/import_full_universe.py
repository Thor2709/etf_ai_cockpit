"""Stage a conservative full-universe census through the canonical importer.

Open defaults: expect 11,737 company census rows and 220 ETF records; stage
100, then 1,000 cumulative candidates, then all remaining candidates; use four
ordered thread workers for independent row identity checks; inspect the
adjacent ``holdings_u1i`` directory when it exists; and use ``secondary``,
``daily`` and ``EUR`` for missing tier, data-policy and currency values, matching
the canonical import service. Missing holdings evidence is treated as
unavailable, never as proof that an ETF is not a fund of funds. Only
verified-ISIN stocks and explicitly enabled, resolved ETFs are enabled.
Unresolved identities are registered disabled only if the canonical store
accepts them; otherwise they remain in the row-level audit CSV with a reason.
No market data, provider, broker, or execution interface is called.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass
import hashlib
import json
import io
import os
from pathlib import Path
import re
import sys
from typing import Mapping, Sequence

from etf_cockpit.application import mcp_universe_ops
from etf_cockpit.data.universe_store import UniverseRecord, is_valid_isin, load_universe, validate_universe


AUDIT_FIELDS = (
    "source",
    "source_row",
    "instrument_id",
    "isin",
    "ticker",
    "bucket",
    "reason",
    "merged_into",
)
BUCKETS = frozenset({"imported", "disabled", "quarantined", "merged_duplicate"})
_KEY_RE = re.compile(r"[^a-z0-9]+")
_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]{0,31}$")
_TRUE = frozenset({"1", "true", "yes", "y", "on", "enabled"})
_FALSE = frozenset({"0", "false", "no", "n", "off", "disabled"})


@dataclass(frozen=True)
class AuditEntry:
    source: str
    source_row: int
    instrument_id: str
    isin: str
    ticker: str
    bucket: str
    reason: str
    merged_into: str = ""
    record: Mapping[str, object] | None = None


def _normalise_key(value: object) -> str:
    return _KEY_RE.sub("_", str(value).strip().casefold()).strip("_")


def _normalise_mapping(value: Mapping[str, object], *, label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    originals: dict[str, str] = {}
    for key, item in value.items():
        normalised = _normalise_key(key)
        if normalised in originals:
            raise ValueError(f"{label} contains normalized key collision: {originals[normalised]} / {key}")
        originals[normalised] = str(key)
        result[normalised] = item
    return result


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text(value).casefold()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def _duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    normalised: dict[str, str] = {}
    for key, value in pairs:
        semantic_key = _normalise_key(key)
        if semantic_key in normalised:
            raise ValueError(f"candidate JSON contains normalized key collision: {normalised[semantic_key]} / {key}")
        normalised[semantic_key] = key
        result[key] = value
    return result


def read_companies(path: Path) -> tuple[Mapping[str, object], ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("company census has no header")
        _normalise_mapping({name: "" for name in reader.fieldnames}, label="company census header")
        rows: list[Mapping[str, object]] = []
        for row in reader:
            if row is None:
                continue
            rows.append(_normalise_mapping(row, label=f"company census row {reader.line_num}"))
    return tuple(rows)


def read_candidate_records(path: Path) -> tuple[Mapping[str, object], ...]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle, object_pairs_hook=_duplicate_json_keys)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
        raise ValueError("candidate JSON must be an object containing a records list")
    records = payload["records"]
    if not all(isinstance(record, Mapping) for record in records):
        raise ValueError("candidate records must all be objects")
    return tuple(_normalise_mapping(record, label=f"candidate record {index}") for index, record in enumerate(records, 1))


def _candidate_index(records: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    by_isin: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        if _text(record.get("asset_type")).casefold() != "stock":
            continue
        isin = _text(record.get("isin")).upper()
        if isin:
            by_isin[isin].append(record)
    return {
        isin: sorted(
            candidates,
            key=lambda item: (
                _text(item.get("isin_status")).casefold() != "verified",
                not bool(_text(item.get("ticker"))),
                _text(item.get("instrument_id")).casefold(),
            ),
        )[0]
        for isin, candidates in by_isin.items()
    }


def _fund_of_funds(record: Mapping[str, object]) -> bool:
    kind = _text(record.get("asset_type")).casefold().replace("-", "_").replace(" ", "_")
    return (
        kind in {"fund_of_funds", "funds_of_funds", "fof"}
        or _boolean(record.get("fund_of_funds")) is True
        or _boolean(record.get("is_fund_of_funds")) is True
    )


def fund_of_funds_from_holdings(path: Path | None) -> frozenset[str]:
    """Return parent filename stems with explicit fund/ETF holdings evidence."""

    if path is None or not path.is_dir():
        return frozenset()
    parents: set[str] = set()
    for holdings_path in sorted(path.glob("*.csv"), key=lambda item: item.name.casefold()):
        with holdings_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = csv.reader(handle)
            header: list[str] | None = None
            ticker_index = asset_index = -1
            for row in rows:
                names = [_normalise_key(item) for item in row]
                if "ticker" in names and "asset_class" in names:
                    header = names
                    ticker_index = names.index("ticker")
                    asset_index = names.index("asset_class")
                    break
            if header is None:
                continue
            for row in rows:
                if max(ticker_index, asset_index) >= len(row):
                    continue
                asset = _text(row[asset_index]).casefold()
                ticker = _text(row[ticker_index])
                if asset in {"etf", "exchange traded fund", "fund", "mutual fund", "investment fund"} and ticker:
                    parents.add(holdings_path.stem.upper())
                    break
    return frozenset(parents)


def _make_record(
    *,
    instrument_id: str,
    name: str,
    isin: str,
    isin_status: str,
    ticker: str,
    asset_type: str,
    enabled: bool,
    reason: str,
    source: Mapping[str, object],
) -> dict[str, object]:
    original_notes = _text(source.get("notes"))
    notes = "; ".join(value for value in (original_notes, f"DATA-DU: {reason}") if value)
    return {
        "canonical_id": instrument_id,
        "name": name or instrument_id,
        "isin": isin,
        "isin_status": isin_status,
        "ticker": ticker,
        "asset_type": asset_type,
        "tier": _text(source.get("tier")) or "secondary",
        "group": _text(source.get("group")),
        "enabled": enabled,
        "data_policy": _text(source.get("data_policy")) or "daily",
        "currency": _text(source.get("currency")) or "EUR",
        "region": _text(source.get("region")) or _text(source.get("country")),
        "sector": _text(source.get("sector")),
        "theme": _text(source.get("theme")),
        "notes": notes,
        "leveraged": _boolean(source.get("leveraged")) is True,
        "inverse": _boolean(source.get("inverse")) is True,
    }


def _entry(
    *,
    source: str,
    source_row: int,
    instrument_id: str,
    isin: str,
    ticker: str,
    enabled: bool,
    reason: str,
    source_record: Mapping[str, object],
    asset_type: str,
    isin_status: str,
) -> AuditEntry:
    record = _make_record(
        instrument_id=instrument_id,
        name=_text(source_record.get("name")),
        isin=isin,
        isin_status=isin_status,
        ticker=ticker,
        asset_type=asset_type,
        enabled=enabled,
        reason=reason,
        source=source_record,
    )
    errors = validate_universe((_universe_record(record),)).errors
    if errors:
        return AuditEntry(source, source_row, instrument_id, isin, ticker, "quarantined", "canonical_validation: " + "; ".join(errors))
    return AuditEntry(source, source_row, instrument_id, isin, ticker, "imported" if enabled else "disabled", reason, record=record)


def _universe_record(record: Mapping[str, object]) -> UniverseRecord:
    return UniverseRecord(
        instrument_id=_text(record.get("canonical_id")),
        name=_text(record.get("name")),
        isin=_text(record.get("isin")),
        isin_status=_text(record.get("isin_status")) or "needs_verification",
        ticker=_text(record.get("ticker")),
        asset_type=_text(record.get("asset_type")) or "stock",
        tier=_text(record.get("tier")) or "secondary",
        group=_text(record.get("group")),
        enabled=_boolean(record.get("enabled")) is True,
        data_policy=_text(record.get("data_policy")) or "daily",
        currency=_text(record.get("currency")) or "EUR",
        region=_text(record.get("region")),
        sector=_text(record.get("sector")),
        theme=_text(record.get("theme")),
        notes=_text(record.get("notes")),
        leveraged=_boolean(record.get("leveraged")) is True,
        inverse=_boolean(record.get("inverse")) is True,
    )


def _company_entry(
    indexed_row: tuple[int, Mapping[str, object]],
    candidates_by_isin: Mapping[str, Mapping[str, object]],
) -> AuditEntry:
    offset, row = indexed_row
    source_row = offset + 2
    isin = _text(row.get("holding_isin")).upper()
    candidate = candidates_by_isin.get(isin)
    row_verified = _boolean(row.get("verified"))
    candidate_verified = bool(
        candidate
        and _text(candidate.get("isin_status")).casefold() == "verified"
        and _text(candidate.get("isin")).upper() == isin
        and is_valid_isin(isin)
    )
    yfinance_ticker = _text(row.get("yfinance_ticker"))
    issuer_ticker = _text(row.get("issuer_ticker"))
    candidate_ticker = _text(candidate.get("ticker")) if candidate else ""
    if row_verified is True and candidate_verified and candidate_ticker and _TICKER_RE.fullmatch(candidate_ticker):
        ticker = candidate_ticker
    elif row_verified is True and _text(row.get("yfinance_status")).casefold() in {"resolved", "verified"} and yfinance_ticker:
        ticker = yfinance_ticker
    elif row_verified is True:
        ticker = issuer_ticker
    else:
        ticker = candidate_ticker or yfinance_ticker or issuer_ticker
    instrument_id = _text(candidate.get("instrument_id")) if candidate else ""
    if not instrument_id and is_valid_isin(isin):
        instrument_id = isin
    if not instrument_id or not ticker:
        missing = "missing_canonical_identity" if not instrument_id else "missing_ticker"
        return AuditEntry("company", source_row, instrument_id, isin, ticker, "quarantined", missing)
    explicit_fund_of_funds = _fund_of_funds(row)
    if row_verified is True and is_valid_isin(isin) and _TICKER_RE.fullmatch(ticker) and not explicit_fund_of_funds:
        candidate_enabled = _boolean(candidate.get("enabled")) if candidate else True
        if candidate_enabled is not True:
            return _entry(
                source="company",
                source_row=source_row,
                instrument_id=instrument_id,
                isin=isin,
                ticker=ticker,
                enabled=False,
                reason="source_disabled",
                source_record=candidate or row,
                asset_type="stock",
                isin_status="verified",
            )
        return _entry(
            source="company",
            source_row=source_row,
            instrument_id=instrument_id,
            isin=isin,
            ticker=ticker,
            enabled=True,
            reason="verified_isin_stock",
            source_record=candidate or row,
            asset_type="stock",
            isin_status="verified",
        )
    status = "verified" if row_verified is True and is_valid_isin(isin) else "needs_verification"
    if explicit_fund_of_funds:
        reason = "fund_of_funds"
    elif row_verified is True and not is_valid_isin(isin):
        reason = "verified_flag_without_valid_isin"
    elif row_verified is None:
        reason = "verification_flag_unavailable_or_malformed"
    else:
        reason = "identity_needs_verification"
    if not is_valid_isin(isin):
        isin = _text(candidate.get("isin")) if candidate else isin
    return _entry(
        source="company",
        source_row=source_row,
        instrument_id=instrument_id,
        isin=isin,
        ticker=ticker,
        enabled=False,
        reason=reason,
        source_record=candidate or row,
        asset_type="etf" if explicit_fund_of_funds else "stock",
        isin_status=status,
    )


def _etf_entry(
    indexed_record: tuple[int, Mapping[str, object]],
    funds_of_funds: frozenset[str],
) -> AuditEntry | None:
    offset, source = indexed_record
    asset_type = _text(source.get("asset_type")).casefold()
    if asset_type not in {"etf", "exchange_traded_fund"}:
        return None
    source_row = offset + 1
    instrument_id = _text(source.get("instrument_id"))
    isin = _text(source.get("isin")).upper()
    ticker = _text(source.get("ticker"))
    verified = _text(source.get("isin_status")).casefold() == "verified" and is_valid_isin(isin)
    explicit_fof = _fund_of_funds(source) or isin in funds_of_funds or instrument_id.upper() in funds_of_funds
    source_enabled = _boolean(source.get("enabled")) is True
    if not instrument_id or not ticker:
        return AuditEntry("etf", source_row, instrument_id, isin, ticker, "quarantined", "missing_canonical_identity_or_ticker")
    if explicit_fof:
        reason = "fund_of_funds"
        enabled = False
    elif verified and source_enabled and _TICKER_RE.fullmatch(ticker):
        reason = "resolved_etf"
        enabled = True
    else:
        reason = "identity_needs_verification" if not verified else "source_disabled"
        enabled = False
    return _entry(
        source="etf",
        source_row=source_row,
        instrument_id=instrument_id,
        isin=isin,
        ticker=ticker,
        enabled=enabled,
        reason=reason,
        source_record=source,
        asset_type="etf",
        isin_status="verified" if verified else "needs_verification",
    )


def _same_verified_isin(first: AuditEntry, second: AuditEntry) -> bool:
    return bool(first.record and second.record) and (
        _text(first.record.get("isin_status")).casefold() == "verified"
        and _text(second.record.get("isin_status")).casefold() == "verified"
        and first.isin
        and first.isin.casefold() == second.isin.casefold()
    )


def _record_identity_equal(first: AuditEntry, second: AuditEntry) -> bool:
    if _same_verified_isin(first, second):
        return True
    if not first.record or not second.record:
        return False
    first_id = _text(first.record.get("canonical_id")).casefold()
    second_id = _text(second.record.get("canonical_id")).casefold()
    return bool(first_id and first_id == second_id and first.isin.casefold() == second.isin.casefold())


def _deduplicate_and_reject_collisions(
    entries: Sequence[AuditEntry],
    existing_records: Sequence[UniverseRecord],
) -> tuple[AuditEntry, ...]:
    output = list(entries)
    candidates = [index for index, entry in enumerate(output) if entry.record is not None]
    duplicate_groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index in candidates:
        entry = output[index]
        if entry.record and _text(entry.record.get("isin_status")).casefold() == "verified" and entry.isin:
            duplicate_groups[("isin", entry.isin.casefold())].append(index)
        elif entry.record:
            canonical_id = _text(entry.record.get("canonical_id")).casefold()
            if canonical_id:
                duplicate_groups[("id_isin", canonical_id, entry.isin.casefold())].append(index)
    parents = {index: index for index in candidates}

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parents[max(first_root, second_root)] = min(first_root, second_root)

    for group in duplicate_groups.values():
        for index in group[1:]:
            union(group[0], index)
    merged_groups: dict[int, list[int]] = defaultdict(list)
    for index in candidates:
        if output[index].record:
            merged_groups[find(index)].append(index)
    duplicate_indices: set[int] = set()
    for group in merged_groups.values():
        if len(group) < 2:
            continue
        winner = min(group, key=lambda index: (output[index].bucket != "imported", index))
        for index in group:
            if index == winner:
                continue
            duplicate_indices.add(index)
            duplicate_reason = (
                "duplicate_verified_isin"
                if _same_verified_isin(output[index], output[winner])
                else "duplicate_canonical_id"
            )
            output[index] = AuditEntry(
                output[index].source,
                output[index].source_row,
                output[index].instrument_id,
                output[index].isin,
                output[index].ticker,
                "merged_duplicate",
                duplicate_reason,
                output[winner].instrument_id,
            )

    collisions: dict[int, set[str]] = defaultdict(set)
    by_ticker: dict[str, list[int]] = defaultdict(list)
    by_id: dict[str, list[int]] = defaultdict(list)
    for index in candidates:
        if index in duplicate_indices or output[index].record is None:
            continue
        entry = output[index]
        if entry.ticker:
            by_ticker[entry.ticker.casefold()].append(index)
        canonical_id = _text(entry.record.get("canonical_id"))
        if canonical_id:
            by_id[canonical_id.casefold()].append(index)
    for label, groups in (("ticker", by_ticker), ("instrument_id", by_id)):
        for value, group in groups.items():
            if len(group) < 2:
                continue
            for position, first_index in enumerate(group):
                for second_index in group[position + 1 :]:
                    if not _record_identity_equal(output[first_index], output[second_index]):
                        collisions[first_index].add(f"{label}:{value}")
                        collisions[second_index].add(f"{label}:{value}")
    for index in candidates:
        if index in duplicate_indices or output[index].record is None:
            continue
        entry = output[index]
        for existing in existing_records:
            same_verified_isin = (
                entry.record
                and _text(entry.record.get("isin_status")).casefold() == "verified"
                and existing.isin_status.casefold() == "verified"
                and entry.isin
                and entry.isin.casefold() == existing.isin.casefold()
            )
            if same_verified_isin:
                output[index] = AuditEntry(
                    entry.source,
                    entry.source_row,
                    entry.instrument_id,
                    entry.isin,
                    entry.ticker,
                    "merged_duplicate",
                    "already_in_universe",
                    existing.instrument_id,
                )
                break
            same_id = entry.instrument_id.casefold() == existing.instrument_id.casefold()
            same_ticker = entry.ticker.casefold() == existing.ticker.casefold()
            if same_id or same_ticker:
                collisions[index].add(f"existing_identity:{existing.instrument_id}")
    for index, reasons in collisions.items():
        entry = output[index]
        output[index] = AuditEntry(
            entry.source,
            entry.source_row,
            entry.instrument_id,
            entry.isin,
            entry.ticker,
            "quarantined",
            "identity_collision: " + ", ".join(sorted(reasons)),
        )
    return tuple(output)


def classify_census(
    companies: Sequence[Mapping[str, object]],
    candidate_records: Sequence[Mapping[str, object]],
    *,
    identity_workers: int = 4,
    existing_records: Sequence[UniverseRecord] = (),
    funds_of_funds: frozenset[str] = frozenset(),
) -> tuple[AuditEntry, ...]:
    if identity_workers < 1:
        raise ValueError("identity_workers must be positive")
    candidates_by_isin = _candidate_index(candidate_records)
    company_jobs = list(enumerate(companies))
    etf_jobs = list(enumerate(candidate_records))
    if identity_workers == 1:
        entries = [_company_entry(job, candidates_by_isin) for job in company_jobs]
        entries.extend(item for job in etf_jobs if (item := _etf_entry(job, funds_of_funds)) is not None)
    else:
        with ThreadPoolExecutor(max_workers=identity_workers) as executor:
            entries = list(executor.map(lambda job: _company_entry(job, candidates_by_isin), company_jobs))
            etfs = list(executor.map(lambda job: _etf_entry(job, funds_of_funds), etf_jobs))
        entries.extend(item for item in etfs if item is not None)
    return _deduplicate_and_reject_collisions(entries, existing_records)


def audit_bytes(entries: Sequence[AuditEntry]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=AUDIT_FIELDS, lineterminator="\n")
    writer.writeheader()
    for entry in entries:
        if entry.bucket not in BUCKETS:
            raise ValueError(f"invalid audit bucket: {entry.bucket}")
        writer.writerow(
            {
                "source": entry.source,
                "source_row": entry.source_row,
                "instrument_id": entry.instrument_id,
                "isin": entry.isin,
                "ticker": entry.ticker,
                "bucket": entry.bucket,
                "reason": entry.reason,
                "merged_into": entry.merged_into,
            }
        )
    return output.getvalue().encode("utf-8")


def write_audit(entries: Sequence[AuditEntry], path: Path) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(audit_bytes(entries))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_stages(value: str, candidate_count: int | None = None) -> tuple[int | None, ...]:
    parts = [item.strip().casefold() for item in value.split(",") if item.strip()]
    if not parts or parts[-1] != "all" or parts.count("all") != 1:
        raise ValueError("stages must be increasing positive counts followed by all")
    limits: list[int | None] = []
    previous = 0
    for part in parts[:-1]:
        try:
            limit = int(part)
        except ValueError as exc:
            raise ValueError("stages must be increasing positive counts followed by all") from exc
        if limit <= previous:
            raise ValueError("stage counts must be positive and strictly increasing")
        limits.append(limit)
        previous = limit
    limits.append(None)
    if candidate_count is not None:
        return tuple(min(limit, candidate_count) if limit is not None else candidate_count for limit in limits)
    return tuple(limits)


def _source_checksum(rows: Sequence[Mapping[str, object]]) -> str:
    normalised = [{str(key): _text(value) for key, value in row.items()} for row in rows]
    encoded = json.dumps(normalised, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_stages(
    entries: Sequence[AuditEntry],
    *,
    root: Path,
    stages: str = "100,1000,all",
    ops: object = mcp_universe_ops,
) -> tuple[int, ...]:
    rows = [dict(entry.record) for entry in entries if entry.record is not None]
    targets = parse_stages(stages, len(rows))
    root = root.resolve()
    setattr(ops, "ROOT", root)
    snapshot = load_universe(root)
    if snapshot.integrity_errors:
        raise ValueError("universe integrity errors block import: " + "; ".join(snapshot.integrity_errors))
    committed: list[int] = []
    start = 0
    for target in targets:
        end = int(target)
        batch = rows[start:end]
        start = end
        if not batch:
            continue
        expected_checksum = _source_checksum(batch)
        preview = ops.preview_universe_import(batch, source_kind="provider")
        if not preview.get("valid"):
            errors = "; ".join(_text(item) for item in preview.get("errors", ()))
            raise ValueError("universe preview rejected a stage" + (f": {errors}" if errors else ""))
        if preview.get("source_checksum") != expected_checksum:
            raise ValueError("universe preview checksum does not match staged rows")
        revision = preview.get("expected_revision")
        if not isinstance(revision, str) or not revision:
            raise ValueError("universe preview did not return a revision")
        if len(preview.get("candidates", ())) != len(batch):
            raise ValueError("universe preview did not preserve every staged candidate")
        result = ops.commit_universe_import(batch, source_kind="provider", expected_revision=revision)
        if result.get("execution_allowed") is not False:
            raise ValueError("canonical universe importer returned an unsafe execution state")
        committed.append(len(batch))
    return tuple(committed)


def import_census(
    entries: Sequence[AuditEntry],
    *,
    root: Path,
    audit: Path,
    stages: str = "100,1000,all",
    ops: object = mcp_universe_ops,
) -> tuple[int, ...]:
    committed = run_stages(entries, root=root, stages=stages, ops=ops)
    write_audit(entries, audit)
    return committed


def _expected_count(actual: int, expected: int, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} row count mismatch: expected {expected}, found {actual}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--census", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--stages", default="100,1000,all")
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--holdings", type=Path, help="holdings folder; defaults to the sibling holdings_u1i directory")
    parser.add_argument("--identity-workers", type=int, default=4)
    parser.add_argument("--expected-company-rows", type=int, default=11_737)
    parser.add_argument("--expected-etf-rows", type=int, default=220)
    args = parser.parse_args(argv)
    try:
        if args.identity_workers < 1:
            raise ValueError("identity-workers must be positive")
        companies = read_companies(args.census)
        candidate_records = read_candidate_records(args.candidates)
        etf_count = sum(_text(record.get("asset_type")).casefold() in {"etf", "exchange_traded_fund"} for record in candidate_records)
        _expected_count(len(companies), args.expected_company_rows, "company census")
        _expected_count(etf_count, args.expected_etf_rows, "ETF census")
        holdings_path = args.holdings or (args.candidates.parent / "holdings_u1i")
        holdings = fund_of_funds_from_holdings(holdings_path)
        existing = load_universe(args.root.resolve())
        if existing.integrity_errors:
            raise ValueError("universe integrity errors block import: " + "; ".join(existing.integrity_errors))
        entries = classify_census(
            companies,
            candidate_records,
            identity_workers=args.identity_workers,
            existing_records=existing.records,
            funds_of_funds=holdings,
        )
        _expected_count(sum(entry.source == "company" for entry in entries), args.expected_company_rows, "company audit")
        _expected_count(sum(entry.source == "etf" for entry in entries), args.expected_etf_rows, "ETF audit")
        committed = import_census(entries, root=args.root, audit=args.audit, stages=args.stages)
        counts = Counter(entry.bucket for entry in entries)
        print(
            "census rows: "
            f"companies={sum(entry.source == 'company' for entry in entries)} "
            f"etfs={sum(entry.source == 'etf' for entry in entries)}"
        )
        print("audit buckets: " + " ".join(f"{bucket}={counts[bucket]}" for bucket in sorted(BUCKETS)))
        print("committed stage sizes: " + ",".join(str(value) for value in committed))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"import refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
