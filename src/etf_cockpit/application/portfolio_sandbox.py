"""Application facade and persistence boundary for local portfolio candidates."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Mapping

from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    StoredRecord,
    TransactionalStore,
)
from etf_cockpit.portfolio.sandbox import (
    PORTFOLIO_SANDBOX_SCHEMA,
    PortfolioAnalysis,
    PortfolioCandidate,
    analyse_candidate,
    candidate_id,
    create_candidate,
)
from etf_cockpit.application.overlap import build_direct_overlap_view


PORTFOLIO_SANDBOX_ENTITY = "portfolio_sandbox"


class PortfolioSandboxPersistenceError(RuntimeError):
    """Raised when local candidate state cannot be accessed safely."""


@dataclass(frozen=True)
class SavedPortfolioCandidate:
    candidate: PortfolioCandidate
    revision: int
    updated_at: str
    source_stale: bool


def draft_portfolio_candidate(snapshot: object, *, name: str = "Portfolio candidate") -> PortfolioCandidate:
    config = getattr(snapshot, "config")
    targets = {key: float(value.target_weight) for key, value in config.targets.positions.items()}
    return build_portfolio_candidate(
        snapshot,
        name=name,
        analysis_notional_eur=_default_notional(snapshot),
        target_weights=targets,
        cash_weight=float(config.targets.cash_target_weight),
    )


def build_portfolio_candidate(
    snapshot: object,
    *,
    name: str,
    analysis_notional_eur: object,
    target_weights: Mapping[str, object],
    cash_weight: object,
) -> PortfolioCandidate:
    return create_candidate(
        getattr(snapshot, "config"),
        getattr(snapshot, "holdings"),
        name=name,
        analysis_notional_eur=analysis_notional_eur,
        target_weights=dict(target_weights),
        cash_weight=cash_weight,
        source_revision=str(getattr(snapshot, "universe_revision", "") or "unknown"),
        source_as_of=_source_as_of(snapshot),
    )


def analyse_portfolio_candidate(snapshot: object, candidate: PortfolioCandidate) -> PortfolioAnalysis:
    holdings = getattr(snapshot, "holdings")
    current: dict[str, float] = {}
    for _, row in holdings.iterrows():
        instrument_id = str(row.get("etf_id", row.get("instrument_id", ""))).strip()
        if instrument_id:
            current[instrument_id] = current.get(instrument_id, 0.0) + float(row.get("current_weight", 0.0))
    ids = sorted(set(current) | set(candidate.targets))
    overlap = build_direct_overlap_view(
        snapshot,
        ids,
        current_weights=current,
        target_weights=candidate.targets,
    )
    return analyse_candidate(
        getattr(snapshot, "config"),
        holdings,
        candidate,
        current_revision=str(getattr(snapshot, "universe_revision", "") or "unknown"),
        overlap=overlap,
    )


def save_portfolio_candidate(
    snapshot: object,
    *,
    name: str,
    analysis_notional_eur: object,
    target_weights: Mapping[str, object],
    cash_weight: object,
    expected_revision: int,
    root: Path = ROOT,
) -> SavedPortfolioCandidate:
    candidate = build_portfolio_candidate(
        snapshot,
        name=name,
        analysis_notional_eur=analysis_notional_eur,
        target_weights=target_weights,
        cash_weight=cash_weight,
    )
    payload = _candidate_payload(candidate)
    try:
        with TransactionalStore(root) as store:
            record = store.put(
                PORTFOLIO_SANDBOX_ENTITY,
                candidate.candidate_id,
                payload,
                expected_revision=expected_revision,
            )
    except StorageRevisionConflict:
        raise
    except (OSError, sqlite3.Error, StorageSchemaError) as exc:
        raise PortfolioSandboxPersistenceError(f"local portfolio storage is unavailable: {exc}") from exc
    return SavedPortfolioCandidate(candidate, record.revision, record.updated_at, source_stale=False)


def load_portfolio_candidate(snapshot: object, name: str, *, root: Path = ROOT) -> SavedPortfolioCandidate:
    identity = candidate_id(name)
    try:
        with TransactionalStore(root) as store:
            record = store.get(PORTFOLIO_SANDBOX_ENTITY, identity)
    except (OSError, sqlite3.Error, StorageSchemaError) as exc:
        raise PortfolioSandboxPersistenceError(f"local portfolio storage is unavailable: {exc}") from exc
    if record is None:
        raise ValueError("no saved portfolio candidate has this name")
    candidate = _candidate_from_record(snapshot, record)
    analysis = analyse_portfolio_candidate(snapshot, candidate)
    return SavedPortfolioCandidate(candidate, record.revision, record.updated_at, analysis.source_stale)


def _candidate_payload(candidate: PortfolioCandidate) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": PORTFOLIO_SANDBOX_SCHEMA,
        "candidate_id": candidate.candidate_id,
        "name": candidate.name,
        "analysis_notional_eur": candidate.analysis_notional_eur,
        "target_weights": [[key, value] for key, value in candidate.target_weights],
        "cash_weight": candidate.cash_weight,
        "source_revision": candidate.source_revision,
        "source_checksum": candidate.source_checksum,
        "source_as_of": candidate.source_as_of,
        "execution_allowed": False,
    }
    return {**body, "payload_checksum": _payload_checksum(body)}


def _candidate_from_record(snapshot: object, record: StoredRecord) -> PortfolioCandidate:
    payload = record.payload
    required = {
        "schema_version",
        "candidate_id",
        "name",
        "analysis_notional_eur",
        "target_weights",
        "cash_weight",
        "source_revision",
        "source_checksum",
        "source_as_of",
        "execution_allowed",
        "payload_checksum",
    }
    if set(payload) != required:
        raise ValueError("saved portfolio candidate has an invalid field set")
    if payload.get("schema_version") != PORTFOLIO_SANDBOX_SCHEMA:
        raise ValueError("saved portfolio candidate schema is unsupported")
    checksum = str(payload.get("payload_checksum", ""))
    body = {key: value for key, value in payload.items() if key != "payload_checksum"}
    if not checksum or checksum != _payload_checksum(body):
        raise ValueError("saved portfolio candidate checksum does not match")
    if payload.get("execution_allowed") is not False:
        raise ValueError("saved portfolio candidate violates the no-execution contract")
    raw_targets = payload.get("target_weights")
    if not isinstance(raw_targets, list) or any(not isinstance(item, list) or len(item) != 2 for item in raw_targets):
        raise ValueError("saved portfolio candidate target weights are malformed")
    target_pairs = [(str(item[0]), item[1]) for item in raw_targets]
    if len({item[0] for item in target_pairs}) != len(target_pairs):
        raise ValueError("saved portfolio candidate contains duplicate instruments")
    validated = build_portfolio_candidate(
        snapshot,
        name=str(payload.get("name", "")),
        analysis_notional_eur=payload.get("analysis_notional_eur"),
        target_weights=dict(target_pairs),
        cash_weight=payload.get("cash_weight"),
    )
    if validated.candidate_id != record.entity_id or validated.candidate_id != str(payload.get("candidate_id", "")):
        raise ValueError("saved portfolio candidate identity does not match its name")
    source_checksum = str(payload.get("source_checksum", ""))
    if len(source_checksum) != 64:
        raise ValueError("saved portfolio candidate source checksum is invalid")
    return replace(
        validated,
        source_revision=str(payload.get("source_revision", "") or "unknown"),
        source_checksum=source_checksum,
        source_as_of=str(payload["source_as_of"]).strip() if payload.get("source_as_of") else None,
    )


def _payload_checksum(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_as_of(snapshot: object) -> str | None:
    report = getattr(snapshot, "data_report", None)
    value = getattr(report, "as_of_date", None)
    return str(value) if value is not None else None


def _default_notional(snapshot: object) -> float:
    holdings = getattr(snapshot, "holdings")
    if "market_value_eur" in holdings:
        value = float(holdings["market_value_eur"].sum())
        if value > 0:
            return value
    return 100_000.0


__all__ = [
    "PORTFOLIO_SANDBOX_ENTITY",
    "PortfolioAnalysis",
    "PortfolioCandidate",
    "PortfolioSandboxPersistenceError",
    "SavedPortfolioCandidate",
    "analyse_portfolio_candidate",
    "build_portfolio_candidate",
    "candidate_id",
    "draft_portfolio_candidate",
    "load_portfolio_candidate",
    "save_portfolio_candidate",
]
