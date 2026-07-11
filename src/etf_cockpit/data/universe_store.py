from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from etf_cockpit.core.atomic_io import atomic_write_json


@dataclass(frozen=True)
class UniverseRecord:
    instrument_id: str
    name: str
    isin: str
    isin_status: str
    ticker: str
    asset_type: str
    tier: str
    group: str
    enabled: bool
    data_policy: str
    currency: str
    region: str
    sector: str
    theme: str
    notes: str


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


@dataclass(frozen=True)
class SupportDecision:
    supported: bool
    score_eligible: bool
    risk_state: str
    reason: str


class UniverseRevisionConflict(RuntimeError):
    pass


def validate_universe(records: Iterable[UniverseRecord]) -> UniverseValidationReport:
    items = tuple(records)
    errors: list[str] = []
    warnings: list[str] = []
    unknown: list[str] = []
    ids: dict[str, str] = {}
    isins: dict[str, str] = {}
    tickers: dict[str, str] = {}
    for record in items:
        if record.instrument_id in ids:
            errors.append(f"duplicate instrument_id: {record.instrument_id}")
        ids[record.instrument_id] = record.tier
        if record.isin_status == "needs_verification" or record.isin.lower() in {"", "unknown", "needs_verification"}:
            unknown.append(record.instrument_id)
        elif record.isin in isins:
            errors.append(f"duplicate isin: {record.isin}")
        else:
            isins[record.isin] = record.instrument_id
        if record.ticker in tickers:
            errors.append(f"duplicate ticker: {record.ticker}")
        else:
            tickers[record.ticker] = record.instrument_id
        decision = support_decision(record.asset_type, record.data_policy, False, False)
        if not decision.supported:
            errors.append(f"unsupported asset type: {record.asset_type}")
        if not record.enabled:
            warnings.append(f"disabled: {record.instrument_id}")
    return UniverseValidationReport(not errors, tuple(errors), tuple(warnings), tuple(sorted(set(unknown))))


def save_universe(records: Iterable[UniverseRecord], expected_revision: str, *, root: Path) -> UniverseSaveResult:
    items = tuple(records)
    report = validate_universe(items)
    if not report.valid:
        raise ValueError("Universe validation failed: " + "; ".join(report.errors))
    path = root / "configs" / "universe_store.json"
    current_revision = ""
    if path.exists():
        try:
            current_revision = str(json.loads(path.read_text(encoding="utf-8")).get("revision") or "")
        except (OSError, ValueError, TypeError):
            current_revision = "corrupt"
    if current_revision != expected_revision:
        raise UniverseRevisionConflict(f"Expected revision {expected_revision or '<empty>'}, found {current_revision or '<empty>'}")
    payload = {"schema_version": 1, "revision": "pending", "records": [asdict(item) for item in items]}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    revision = hashlib.sha256(encoded).hexdigest()
    payload["revision"] = revision
    atomic_write_json(path, payload)
    if json.loads(path.read_text(encoding="utf-8")).get("revision") != revision:
        raise IOError("Universe revision verification failed after atomic write")
    return UniverseSaveResult(path, revision, len(items))


def support_decision(asset_type: str, frequency: str, leveraged: bool, inverse: bool) -> SupportDecision:
    normalized = asset_type.strip().lower()
    if normalized not in {"etf", "stock", "equity_certificate", "certificate"}:
        return SupportDecision(False, False, "unsupported", f"{asset_type} is research-only or unsupported.")
    if frequency.strip().lower() not in {"daily", "daily_close", "yfinance_now_multi_provider_later"}:
        return SupportDecision(False, False, "unsupported_frequency", "Only daily close data is supported for current scoring.")
    if leveraged or inverse:
        return SupportDecision(True, False, "high_risk_manual_review", "Leveraged or inverse instruments require manual review and are not score eligible by default.")
    return SupportDecision(True, True, "normal", "Daily ETF/stock/equity-certificate scoring is supported.")
