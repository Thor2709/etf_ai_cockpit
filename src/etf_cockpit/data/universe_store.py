from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from etf_cockpit.core.atomic_io import atomic_write_json, backup_paths
from etf_cockpit.core.paths import ROOT


UNKNOWN_ISIN_VALUES = {"", "unknown", "needs_verification", "n/a", "na", "none"}
SPAREBANKEN_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("Aurskog Sparebank", "AURG", "AURG.OL", "needs_verification"),
    ("Helgeland Sparebank", "HELG", "HELG.OL", "NO0010029804"),
    ("Høland og Setskog Sparebank", "HSPG", "HSPG.OL", "NO0010012636"),
    ("Sogn Sparebank", "SOGN", "SOGN.OL", "needs_verification"),
    ("Jæren Sparebank", "JAEREN", "JAEREN.OL", "NO0010359433"),
    ("Melhus Sparebank", "MELG", "MELG.OL", "needs_verification"),
    ("Sandnes Sparebank", "SADG", "SADG.OL", "needs_verification"),
    ("Skue Sparebank", "SKUE", "SKUE.OL", "needs_verification"),
    ("SpareBank 1 Nord-Norge", "NONG", "NONG.OL", "NO0006000801"),
    ("SpareBank 1 Ringerike Hadeland", "RING", "RING.OL", "NO0006390400"),
    ("SpareBank 1 SMN", "MING", "MING.OL", "NO0006390301"),
    ("SpareBank 1 Østfold Akershus", "SOAG", "SOAG.OL", "NO0010285562"),
    ("SpareBank 1 Østlandet", "SPOL", "SPOL.OL", "NO0010751910"),
    ("Sparebanken Møre", "MORG", "MORG.OL", "NO0006390004"),
    ("Sparebanken Øst", "SPOG", "SPOG.OL", "NO0006222009"),
)


@dataclass(frozen=True)
class UniverseRecord:
    instrument_id: str
    name: str
    isin: str = ""
    isin_status: str = "verified"
    ticker: str = ""
    asset_type: str = "stock"
    tier: str = "secondary"
    group: str = ""
    enabled: bool = True
    data_policy: str = "daily"
    currency: str = "EUR"
    region: str = ""
    sector: str = ""
    theme: str = ""
    notes: str = ""
    # Added in schema v2.  Missing legacy values are deliberately safe.
    leveraged: bool = False
    inverse: bool = False


@dataclass(frozen=True)
class UniverseValidationReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    unknown_isin_ids: tuple[str, ...]


@dataclass(frozen=True)
class UniverseSaveResult:
    path: Path
    revision: str
    record_count: int
    backup_path: Path | None = None
    pending_refresh: bool = True


@dataclass(frozen=True)
class SupportDecision:
    supported: bool
    score_eligible: bool
    risk_state: str
    reason: str


@dataclass(frozen=True)
class UniverseStoreSnapshot:
    records: tuple[UniverseRecord, ...]
    revision: str
    path: Path


@dataclass(frozen=True)
class LegacyImportResult:
    records: tuple[UniverseRecord, ...]
    warnings: tuple[str, ...] = ()
    source_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CompatibilityExport:
    yaml_path: Path
    csv_path: Path


class UniverseRevisionConflict(RuntimeError):
    pass


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _is_unknown_isin(value: str, status: str) -> bool:
    return status.strip().lower() in {"needs_verification", "unknown", "unresolved"} or value.strip().lower() in UNKNOWN_ISIN_VALUES


def _normalise_record(record: UniverseRecord) -> UniverseRecord:
    isin = _text(record.isin)
    status = _text(record.isin_status, "verified").lower()
    if _is_unknown_isin(isin, status):
        isin = "needs_verification"
        status = "needs_verification"
    return replace(
        record,
        instrument_id=_text(record.instrument_id),
        name=_text(record.name, _text(record.instrument_id)),
        isin=isin,
        isin_status=status,
        ticker=_text(record.ticker).upper(),
        asset_type=_text(record.asset_type, "stock").lower(),
        tier=_text(record.tier, "secondary").lower(),
        group=_text(record.group),
        data_policy=_text(record.data_policy, "daily").lower(),
        currency=_text(record.currency, "EUR").upper(),
        region=_text(record.region),
        sector=_text(record.sector),
        theme=_text(record.theme),
        notes=_text(record.notes),
        enabled=_as_bool(record.enabled),
        leveraged=_as_bool(record.leveraged),
        inverse=_as_bool(record.inverse),
    )


def validate_universe(
    records: Iterable[UniverseRecord],
    *,
    allow_cross_tier_duplicates: bool = False,
) -> UniverseValidationReport:
    items = tuple(_normalise_record(record) for record in records)
    errors: list[str] = []
    warnings: list[str] = []
    unknown: list[str] = []
    ids: dict[str, tuple[str, str]] = {}
    isins: dict[str, tuple[str, str]] = {}
    tickers: dict[str, tuple[str, str]] = {}
    for record in items:
        record_id = record.instrument_id.casefold()
        ticker = record.ticker.casefold()
        if not record.instrument_id:
            errors.append("instrument_id is required")
        elif record_id in ids:
            prior_id, prior_tier = ids[record_id]
            if not (allow_cross_tier_duplicates and prior_tier != record.tier):
                errors.append(f"duplicate instrument_id: {record.instrument_id}")
            else:
                warnings.append(f"cross-tier duplicate override: instrument_id {record.instrument_id}")
        ids[record_id] = (record.instrument_id, record.tier)
        if not record.ticker:
            errors.append(f"ticker is required: {record.instrument_id}")
        elif ticker in tickers:
            prior_ticker, prior_tier = tickers[ticker]
            if not (allow_cross_tier_duplicates and prior_tier != record.tier):
                errors.append(f"duplicate ticker: {record.ticker}")
            else:
                warnings.append(f"cross-tier duplicate override: ticker {record.ticker}")
        else:
            tickers[ticker] = (record.instrument_id, record.tier)
        if _is_unknown_isin(record.isin, record.isin_status):
            unknown.append(record.instrument_id)
        elif record.isin.casefold() in isins:
            prior_isin, prior_tier = isins[record.isin.casefold()]
            if not (allow_cross_tier_duplicates and prior_tier != record.tier):
                errors.append(f"duplicate isin: {record.isin}")
            else:
                warnings.append(f"cross-tier duplicate override: ISIN {record.isin}")
        else:
            isins[record.isin.casefold()] = (record.instrument_id, record.tier)
        if record.tier not in {"primary", "secondary", "sparebanken"}:
            errors.append(f"invalid tier: {record.tier}")
        decision = support_decision(record.asset_type, record.data_policy, record.leveraged, record.inverse)
        if decision.risk_state == "research_only":
            warnings.append(f"research_only: {record.instrument_id}")
        elif not decision.supported:
            errors.append(f"unsupported asset type/frequency: {record.asset_type}/{record.data_policy}")
        if not record.enabled:
            warnings.append(f"disabled: {record.instrument_id}")
        if _is_unknown_isin(record.isin, record.isin_status):
            warnings.append(f"needs_verification: {record.instrument_id}")
    return UniverseValidationReport(not errors, tuple(errors), tuple(warnings), tuple(sorted(set(unknown))))


def _store_path(root: Path) -> Path:
    return root / "configs" / "universe_store.json"


def _payload_revision(payload: Mapping[str, object]) -> str:
    canonical = dict(payload)
    canonical["revision"] = "pending"
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def save_universe(records: Iterable[UniverseRecord], expected_revision: str, *, root: Path | None = None) -> UniverseSaveResult:
    root = (root or ROOT).resolve()
    items = tuple(_normalise_record(record) for record in records)
    report = validate_universe(items)
    if not report.valid:
        raise ValueError("Universe validation failed: " + "; ".join(report.errors))
    path = _store_path(root)
    current_revision = ""
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            current_revision = str(raw.get("revision") or "")
        except (OSError, ValueError, TypeError):
            current_revision = "corrupt"
    if current_revision != expected_revision:
        raise UniverseRevisionConflict(f"Expected revision {expected_revision or '<empty>'}, found {current_revision or '<empty>'}")
    backup_path: Path | None = None
    if path.is_file():
        backup = backup_paths((path,), root / "backups" / "universe")
        backup_path = backup.manifest_path
    payload: dict[str, object] = {
        "schema_version": 2,
        "revision": "pending",
        "records": [asdict(item) for item in items],
    }
    revision = _payload_revision(payload)
    payload["revision"] = revision
    atomic_write_json(path, payload)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    if persisted.get("revision") != revision:
        raise IOError("Universe revision verification failed after atomic write")
    return UniverseSaveResult(path, revision, len(items), backup_path)


def load_universe(root: Path | None = None) -> UniverseStoreSnapshot:
    root = (root or ROOT).resolve()
    path = _store_path(root)
    if not path.exists():
        return UniverseStoreSnapshot((), "", path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = tuple(_normalise_record(UniverseRecord(**raw)) for raw in payload.get("records", ()))
    return UniverseStoreSnapshot(records, _text(payload.get("revision")), path)


def add_record(records: Iterable[UniverseRecord], record: UniverseRecord) -> tuple[UniverseRecord, ...]:
    items = tuple(records) + (_normalise_record(record),)
    report = validate_universe(items)
    if not report.valid:
        raise ValueError("Universe validation failed: " + "; ".join(report.errors))
    return items


def edit_record(records: Iterable[UniverseRecord], instrument_id: str, **changes: object) -> tuple[UniverseRecord, ...]:
    items = tuple(records)
    for index, record in enumerate(items):
        if record.instrument_id == instrument_id:
            allowed = set(asdict(record))
            unknown = sorted(set(changes) - allowed)
            if unknown:
                raise ValueError(f"Unknown universe fields: {', '.join(unknown)}")
            updated = _normalise_record(replace(record, **changes))
            candidate = items[:index] + (updated,) + items[index + 1 :]
            report = validate_universe(candidate)
            if not report.valid:
                raise ValueError("Universe validation failed: " + "; ".join(report.errors))
            return candidate
    raise KeyError(f"Unknown instrument_id: {instrument_id}")


def disable_record(records: Iterable[UniverseRecord], instrument_id: str) -> tuple[UniverseRecord, ...]:
    return edit_record(records, instrument_id, enabled=False)


def remove_record(records: Iterable[UniverseRecord], instrument_id: str) -> tuple[UniverseRecord, ...]:
    items = tuple(records)
    if not any(record.instrument_id == instrument_id for record in items):
        raise KeyError(f"Unknown instrument_id: {instrument_id}")
    return tuple(record for record in items if record.instrument_id != instrument_id)


def support_decision(asset_type: str, frequency: str, leveraged: bool, inverse: bool) -> SupportDecision:
    normalized = _text(asset_type).lower()
    cadence = _text(frequency).lower()
    if normalized in {"futures", "future", "options", "option", "derivative"}:
        return SupportDecision(False, False, "research_only", f"{asset_type} is research-only and is not scored by the daily pipeline.")
    if normalized in {"crypto", "cryptocurrency"}:
        return SupportDecision(False, False, "unsupported", "Crypto is unsupported unless a separately configured proxy is approved; no silent scoring.")
    if normalized not in {"etf", "stock", "equity", "equity_certificate", "certificate"}:
        return SupportDecision(False, False, "unsupported", f"{asset_type} is unsupported and cannot be scored.")
    # ``yfinance_only`` is the historical provider-policy marker, not an
    # intraday cadence.  Keep it compatible with the daily pipeline.
    if cadence not in {"daily", "daily_close", "yfinance_now_multi_provider_later", "yfinance_only"}:
        return SupportDecision(False, False, "unsupported_frequency", "Intraday and non-daily frequencies are unsupported for current scoring.")
    if leveraged or inverse:
        return SupportDecision(True, False, "high_risk_manual_review", "Leveraged or inverse instruments require manual review and are not score eligible by default.")
    return SupportDecision(True, True, "normal", "Daily ETF/stock/equity-certificate scoring is supported.")


def _field(row: Mapping[str, object], *names: str) -> str:
    lower = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        value = lower.get(name.lower())
        if value not in (None, ""):
            return _text(value)
    return ""


def _record_from_mapping(raw: Mapping[str, object], *, default_tier: str) -> UniverseRecord:
    ticker = _field(raw, "ticker", "yahoo_symbol", "yahoo_ticker", "provider_symbol", "symbol")
    isin = _field(raw, "isin", "ISIN") or "needs_verification"
    status = _field(raw, "isin_status", "isin_state") or ("needs_verification" if _is_unknown_isin(isin, "") else "verified")
    tier = (_field(raw, "tier", "analysis_tier") or default_tier).lower()
    group = _field(raw, "group", "source_group") or ("Sparebanken" if tier == "sparebanken" else "")
    instrument_id = _field(raw, "instrument_id", "id", "symbol", "ticker") or ticker
    asset_type = _field(raw, "asset_type", "instrument_type", "type") or ("equity_certificate" if tier == "sparebanken" else "stock")
    leveraged = _field(raw, "leveraged", "is_leveraged").lower() in {"true", "1", "yes", "on"}
    inverse = _field(raw, "inverse", "is_inverse").lower() in {"true", "1", "yes", "on"}
    return _normalise_record(
        UniverseRecord(
            instrument_id=instrument_id,
            name=_field(raw, "name", "security_name", "company") or instrument_id,
            isin=isin,
            isin_status=status,
            ticker=ticker,
            asset_type=asset_type,
            tier=tier,
            group=group,
            enabled=_field(raw, "enabled").lower() not in {"false", "0", "no", "disabled"},
            data_policy=_field(raw, "data_policy", "frequency", "price_frequency") or "daily",
            currency=_field(raw, "currency") or "NOK" if tier == "sparebanken" else _field(raw, "currency") or "EUR",
            region=_field(raw, "region") or ("Norway" if tier == "sparebanken" else ""),
            sector=_field(raw, "sector") or ("Banks" if tier == "sparebanken" else ""),
            theme=_field(raw, "theme"),
            notes=_field(raw, "notes", "comment"),
            leveraged=leveraged,
            inverse=inverse,
        )
    )


def _sparebanken_fallback() -> tuple[UniverseRecord, ...]:
    return tuple(
        _record_from_mapping(
            {"name": name, "symbol": symbol, "yahoo_symbol": ticker, "isin": isin, "analysis_tier": "sparebanken"},
            default_tier="sparebanken",
        )
        for name, symbol, ticker, isin in SPAREBANKEN_ROWS
    )


def import_legacy_universe(primary_yaml: Path, candidate_csv: Path | None = None) -> LegacyImportResult:
    primary_yaml = Path(primary_yaml)
    payload = yaml.safe_load(primary_yaml.read_text(encoding="utf-8")) if primary_yaml.exists() else {}
    primary_rows = (payload.get("etfs", ()) or ()) if isinstance(payload, dict) else ()
    records: list[UniverseRecord] = [_record_from_mapping(raw, default_tier="primary") for raw in primary_rows if isinstance(raw, Mapping)]
    warnings: list[str] = []
    candidate_path = Path(candidate_csv) if candidate_csv else None
    candidate_rows: list[Mapping[str, object]] = []
    if candidate_path and candidate_path.exists():
        with candidate_path.open(newline="", encoding="utf-8-sig") as handle:
            candidate_rows = list(csv.DictReader(handle))
    fallback = _sparebanken_fallback()
    fallback_by_id = {record.instrument_id.casefold(): record for record in fallback}
    fallback_by_ticker = {record.ticker.casefold(): record for record in fallback}
    if candidate_rows:
        for raw in candidate_rows:
            records.append(_record_from_mapping(raw, default_tier="secondary"))
        # The legacy feed can be partial and historically mixed Sparebanken
        # rows into the secondary tier.  Canonical fallback identity always
        # wins, including when NONG is present as a secondary candidate.
        canonical_ids = set(fallback_by_id)
        canonical_tickers = set(fallback_by_ticker)
        records = [
            record
            for record in records
            if record.instrument_id.casefold() not in canonical_ids
            and record.ticker.casefold() not in canonical_tickers
        ]
        records.extend(fallback)
    else:
        warnings.append("candidate CSV unavailable; retained built-in Sparebanken identity rows")
        records.extend(fallback)
    # Preserve one authoritative row per canonical ID even if an unusual
    # legacy source repeats a row under a case variant.
    seen: set[str] = set()
    deduped: list[UniverseRecord] = []
    for record in records:
        key = record.instrument_id.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return LegacyImportResult(tuple(deduped), tuple(warnings), tuple(path for path in (primary_yaml, candidate_path) if path is not None and path.exists()))


def migrate_legacy_universe(
    root: Path | None = None,
    *,
    primary_yaml: Path | None = None,
    candidate_csv: Path | None = None,
    expected_revision: str | None = None,
) -> tuple[LegacyImportResult, UniverseSaveResult]:
    """Import legacy YAML/CSV inputs and publish one revisioned local store."""

    root = (root or ROOT).resolve()
    primary = primary_yaml or (root / "configs" / "universe.yaml")
    candidates = candidate_csv
    if candidates is None:
        candidate_dir = root / "data" / "raw" / "trade_candidates"
        found = sorted(candidate_dir.glob("yahoo_trade_candidates_*.csv")) if candidate_dir.exists() else []
        candidates = found[-1] if found else None
    imported = import_legacy_universe(primary, candidates)
    current = load_universe(root)
    revision = current.revision if expected_revision is None else expected_revision
    saved = save_universe(imported.records, expected_revision=revision, root=root)
    return imported, saved


def export_compatibility(records: Iterable[UniverseRecord], export_root: Path) -> CompatibilityExport:
    export_root = Path(export_root)
    export_root.mkdir(parents=True, exist_ok=True)
    items = tuple(_normalise_record(record) for record in records)
    yaml_path = export_root / "universe.yaml"
    yaml_payload = {"etfs": [{"id": row.instrument_id, "name": row.name, "isin": row.isin, "ticker": row.ticker, "provider_symbol": row.ticker, "instrument_type": row.asset_type, "analysis_tier": row.tier, "data_policy": row.data_policy, "currency": row.currency, "region": row.region, "sector": row.sector, "theme": row.theme, "enabled": row.enabled, "leveraged": row.leveraged, "inverse": row.inverse, "role": "core" if row.tier == "primary" else "watchlist", "notes": row.notes} for row in items if row.tier == "primary"]}
    yaml_path.write_text(yaml.safe_dump(yaml_payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    csv_path = export_root / "yahoo_trade_candidates.csv"
    fieldnames = ["instrument_id", "name", "isin", "isin_status", "ticker", "asset_type", "analysis_tier", "group", "enabled", "data_policy", "currency", "region", "sector", "theme", "notes", "leveraged", "inverse"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in items:
            if row.tier != "primary":
                writer.writerow({"instrument_id": row.instrument_id, "name": row.name, "isin": row.isin, "isin_status": row.isin_status, "ticker": row.ticker, "asset_type": row.asset_type, "analysis_tier": row.tier, "group": row.group, "enabled": row.enabled, "data_policy": row.data_policy, "currency": row.currency, "region": row.region, "sector": row.sector, "theme": row.theme, "notes": row.notes, "leveraged": row.leveraged, "inverse": row.inverse})
    return CompatibilityExport(yaml_path, csv_path)
