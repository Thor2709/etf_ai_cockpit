"""Run decision v1 beside the canonical score and persist a local artefact."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timezone
import hashlib
import math
from pathlib import Path
import re
from typing import Mapping, Sequence

import pandas as pd

from etf_cockpit.analysis.decision.domains import load_domain_registry
from etf_cockpit.analysis.decision.etf import (
    _exposure_scored_metrics,
    _load_etf_registries,
    _vehicle_scored_metrics,
    compose_etf_decision,
)
from etf_cockpit.analysis.decision.opportunity import (
    build_opportunity_results,
    load_opportunity_policy,
)
from etf_cockpit.analysis.peer_cohorts import PeerObservation
from etf_cockpit.analysis.decision.stock import (
    _stock_scored_metrics,
    _valuation_scored_metrics,
    compose_stock_decision,
    load_stock_decision_map,
)
from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import (
    LOG_DIR,
    ROOT,
    STATEMENT_FACTS_PATH,
)
from etf_cockpit.data.classification import read_instrument_context
from etf_cockpit.data.etf_economics import (
    calculate_etf_economics,
    load_etf_economics_records,
)
from etf_cockpit.data.fundamentals import FUNDAMENTAL_CLEAN_PATH
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
from etf_cockpit.data.stock_research import (
    build_stock_research_report,
    load_stock_research_frame,
)


_PROJECT_CONFIG_DIR = Path(__file__).resolve().parents[4] / "configs"
_DECISION_REGISTRY_PATH = _PROJECT_CONFIG_DIR / "decision_domains_v1.yaml"
_SAFE_RUN_ID = re.compile(r"[^A-Za-z0-9_.-]+")


def run_decision_shadow(
    config: object,
    signals: Sequence[object],
    *,
    decision_time: str | date,
    latest_features: pd.DataFrame | None = None,
    output_directory: Path = LOG_DIR,
    candidates: Sequence[Mapping[str, object]] | None = None,
    failures: Sequence[Mapping[str, str]] = (),
) -> Path:
    """Write one immutable-by-run versioned JSON companion to the v3 signal log.

    Local source gaps are kept as unavailable composer evidence. Each configured
    instrument is scored at the common decision cutoff; no source is synthesized.
    ``candidates`` is a narrow deterministic seam for tests and replay callers.
    """

    cutoff = _decision_timestamp(decision_time)
    signal_rows = tuple(signals)
    run_id = str(_member(signal_rows[0], "run_id", "")) if signal_rows else ""
    if not run_id:
        run_id = f"signals_{cutoff.strftime('%Y%m%d_%H%M%S')}"
    run_id = _SAFE_RUN_ID.sub("_", run_id).strip("_.") or "signals_unavailable"
    failure_rows = [dict(item) for item in failures]
    candidate_rows: Sequence[Mapping[str, object]]
    if candidates is not None:
        candidate_rows = candidates
    else:
        try:
            candidate_rows = _compose_universe(
                config,
                signal_rows,
                cutoff,
                latest_features=latest_features,
            )
        except Exception as exc:
            candidate_rows = ()
            failure_rows.append(
                {
                    "instrument": "universe",
                    "reason_code": f"COMPOSER_INPUTS_FAILED:{type(exc).__name__}",
                }
            )

    config_hashes = _config_hashes()
    try:
        results = build_opportunity_results(
            candidate_rows,
            decision_time=cutoff.isoformat().replace("+00:00", "Z"),
        )
        for candidate in candidate_rows:
            if candidate.get("failure_reason"):
                failure_rows.append(
                    {
                        "instrument": str(candidate.get("instrument", "unavailable")),
                        "reason_code": str(candidate["failure_reason"]),
                    }
                )
        result_payloads = [
            {
                **asdict(result),
                "schema_version": 1,
                "formula_version": _policy_version(),
            }
            for _, result in sorted(results.items())
        ]
    except Exception as exc:
        result_payloads = []
        failure_rows.append(
            {
                "instrument": "universe",
                "reason_code": f"OPPORTUNITY_CALCULATION_FAILED:{type(exc).__name__}",
            }
        )

    instrument_assessments = []
    for candidate in candidate_rows:
        assessment = candidate.get("assessment")
        instrument_assessments.append(
            {
                "instrument": str(candidate.get("instrument", "unavailable")),
                "assessment": _jsonable(assessment),
            }
        )
    payload = {
        "schema_version": 1,
        "artifact_version": "decision-opportunity-shadow-v1",
        "run_id": run_id,
        "decision_time": cutoff.isoformat().replace("+00:00", "Z"),
        "config_hashes": config_hashes,
        "status": "complete" if not failure_rows else "partial",
        "results": result_payloads,
        "instrument_assessments": instrument_assessments,
        "failures": failure_rows,
        "execution_allowed": False,
    }
    destination = Path(output_directory) / f"decision_opportunity_{run_id}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, payload)
    return destination


def _compose_universe(
    config: object,
    signals: Sequence[object],
    decision: datetime,
    *,
    latest_features: pd.DataFrame | None,
) -> tuple[Mapping[str, object], ...]:
    """Compose all enabled instruments against one point-in-time peer snapshot.

    Peer observations are equally weighted by instrument. This avoids making
    undocumented confidence adjustments to the existing domain normalizer.
    ETFs join the same exposure peer group only when their dominant sector is
    at least the configured 35% exposure share.
    """

    universe = _member(config, "universe")
    identities = _member(universe, "etfs", ()) or ()
    enabled = set(_member(universe, "enabled_ids", ()) or ())
    if not identities or not enabled:
        return ()
    policy = load_opportunity_policy()
    signal_by_id = {str(_member(item, "etf_id", "")): item for item in signals}
    economics_records = load_etf_economics_records()
    prepared: list[dict[str, object]] = []
    failures: list[Mapping[str, object]] = []
    for identity in identities:
        instrument = str(_member(identity, "id", "")).strip()
        if not instrument or instrument not in enabled:
            continue
        try:
            context = read_instrument_context(
                ROOT,
                instrument,
                effective_at=decision,
                decision_time=decision,
            )
            configured_type = str(_member(identity, "instrument_type", "ETF"))
            instrument_type = str(context.instrument_type or configured_type)
            if instrument_type.casefold() in {"stock", "equity"}:
                prepared.append(
                    _prepare_stock_candidate(instrument, context, decision, signal_by_id.get(instrument))
                )
            else:
                prepared.append(
                    _prepare_etf_candidate(
                        instrument,
                        context,
                        decision,
                        economics_records,
                        signal_by_id.get(instrument),
                    )
                )
        except Exception as exc:
            failures.append(
                {
                    "instrument": instrument,
                    "asset_type": str(_member(identity, "instrument_type", "ETF")),
                    "peer_id": "unavailable",
                    "failure_reason": f"COMPOSER_INPUTS_FAILED:{type(exc).__name__}",
                }
            )

    stock_observations = _observations(prepared, "stock_metrics", decision)
    vehicle_observations = _observations(prepared, "vehicle_metrics", decision)
    exposure_observations = _observations(prepared, "exposure_metrics", decision)
    exposure_groups = {
        "ETF_EXPOSURE_PEERS": {
            str(item["instrument"]): str(item["peer_id"])
            for item in prepared
            if str(item.get("asset_type", "")).casefold() not in {"stock", "equity"}
            and str(item.get("peer_id", "unavailable")) != "unavailable"
        }
    }
    rows: list[Mapping[str, object]] = []
    for item in prepared:
        try:
            if item["asset_type"] == "stock":
                rows.append(
                    _compose_stock_candidate(
                        item,
                        decision,
                        stock_observations,
                        policy.minimum_peer_support,
                    )
                )
            else:
                rows.append(
                    _compose_etf_candidate(
                        item,
                        decision,
                        vehicle_observations,
                        exposure_observations,
                        exposure_groups,
                        policy.minimum_peer_support,
                    )
                )
        except Exception as exc:
            failures.append(
                {
                    "instrument": str(item["instrument"]),
                    "asset_type": str(item["asset_type"]),
                    "peer_id": str(item.get("peer_id", "unavailable")),
                    "failure_reason": f"COMPOSER_FAILED:{type(exc).__name__}",
                }
            )
    return tuple((*rows, *failures))


def _prepare_stock_candidate(
    instrument: str, context: object, decision: datetime, signal: object
) -> dict[str, object]:
    statements = load_stock_research_frame(
        STATEMENT_FACTS_PATH,
        instrument_id=instrument,
        as_known_at=decision,
    )
    sector = str(_member(context, "sector", "") or "")
    research = build_stock_research_report(
        statements,
        instrument_id=instrument,
        sector=sector,
        classification_context={"sector": sector, "classification_status": "resolved" if sector else "unavailable"},
        as_known_at=decision,
        strict_comparability=True,
    )
    stock_map = load_stock_decision_map(_DECISION_REGISTRY_PATH)
    stock_metrics, _ = _stock_scored_metrics(research, {}, stock_map)
    registry = load_domain_registry(_DECISION_REGISTRY_PATH)
    valuation_definitions = tuple(
        item for item in registry.metrics if item.domain == "valuation"
    )
    valuation_metrics = _valuation_scored_metrics(
        research, valuation_definitions, context
    )
    return {
        "instrument": instrument,
        "asset_type": "stock",
        "context": context,
        "research": research,
        "signal": signal,
        "stock_metrics": tuple((*stock_metrics, *valuation_metrics)),
        "peer_id": f"sector:{sector}" if sector else "unavailable",
    }


def _compose_stock_candidate(
    prepared: Mapping[str, object],
    decision: datetime,
    peer_observations: Sequence[PeerObservation],
    minimum_support: int,
) -> Mapping[str, object]:
    instrument = str(prepared["instrument"])
    composed = compose_stock_decision(
        instrument,
        prepared["context"],
        _time_text(decision),
        prepared["research"],
        peer_observations=peer_observations,
        registry_path=_DECISION_REGISTRY_PATH,
        minimum_support=minimum_support,
    )
    return {
        "instrument": instrument,
        "asset_type": "stock",
        "assessment": composed.get("assessment"),
        "underwriting_domains": composed.get("underwriting_domains", ()),
        "domain_labels": composed.get("underwriting_domain_labels", {}),
        "underwriting_z_score": composed.get("underwriting_z_score"),
        "valuation_domain": composed.get("valuation_domain"),
        "valuation_z_score": composed.get("valuation_z_score"),
        "critical_domains": composed.get("critical_underwriting_domains", ()),
        "signal": prepared.get("signal"),
        "peer_id": prepared.get("peer_id", "unavailable"),
    }


def _prepare_etf_candidate(
    instrument: str,
    context: object,
    decision: datetime,
    economics_records: Sequence[object],
    signal: object,
) -> dict[str, object]:
    records = tuple(
        item
        for item in economics_records
        if str(_member(item, "instrument_id", "")) == instrument
        and _time_is_at_or_before(_member(item, "as_of"), decision)
        and _time_is_at_or_before(_member(item, "known_at"), decision)
    )
    economics = calculate_etf_economics(instrument, records, as_of=decision)
    look_through = _look_through(instrument, decision)
    vehicle_registry, exposure_registry, _ = _load_etf_registries(
        _DECISION_REGISTRY_PATH
    )
    vehicle_metrics = _vehicle_scored_metrics(
        vehicle_registry,
        economics,
        None,
        None,
        look_through,
        {},
        {},
        context,
        decision,
    )
    exposure_metrics = _exposure_scored_metrics(
        exposure_registry, look_through, decision
    )
    peer_id = _exposure_peer_id(look_through, load_opportunity_policy().minimum_exposure_peer_sector_share)
    return {
        "instrument": instrument,
        "asset_type": str(_member(context, "instrument_type", "ETF") or "ETF"),
        "context": context,
        "economics": economics,
        "look_through": look_through,
        "signal": signal,
        "vehicle_metrics": tuple(vehicle_metrics),
        "exposure_metrics": tuple(exposure_metrics),
        "peer_id": peer_id,
    }


def _compose_etf_candidate(
    prepared: Mapping[str, object],
    decision: datetime,
    peer_observations: Sequence[PeerObservation],
    exposure_peer_observations: Sequence[PeerObservation],
    comparison_groups: Mapping[str, Mapping[str, str]],
    minimum_support: int,
) -> Mapping[str, object]:
    instrument = str(prepared["instrument"])
    assessment = compose_etf_decision(
        instrument,
        prepared["context"],
        _time_text(decision),
        etf_economics=prepared["economics"],
        look_through=prepared["look_through"],
        peer_observations=peer_observations,
        exposure_peer_observations=exposure_peer_observations,
        comparison_groups=comparison_groups,
        registry_path=_DECISION_REGISTRY_PATH,
        minimum_support=minimum_support,
    )
    vehicle_score = _opportunity_slot_score(assessment, "Vehicle Rank")
    exposure_score = _opportunity_slot_score(assessment, "Exposure Opportunity Rank")
    return {
        "instrument": instrument,
        "asset_type": str(prepared["asset_type"]),
        "assessment": assessment,
        "domain_slots": assessment.domain_slots,
        "exposure_domain_slots": assessment.exposure_domain_slots,
        "critical_domains": assessment.critical_domains,
        "vehicle_z_score": vehicle_score,
        "exposure_z_score": exposure_score,
        "signal": prepared.get("signal"),
        "peer_id": prepared.get("peer_id", "unavailable"),
        "source_vintage_hash": assessment.source_vintage_hash,
    }


def _observations(
    prepared: Sequence[Mapping[str, object]], key: str, decision: datetime
) -> tuple[PeerObservation, ...]:
    observations: list[PeerObservation] = []
    for item in prepared:
        context = item.get("context")
        if context is None:
            continue
        for metric in item.get(key, ()) or ():
            value = _member(metric, "raw_value")
            if (
                str(_member(metric, "status", "")).upper() != "AVAILABLE"
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not _time_is_at_or_before(_member(metric, "effective_at"), decision)
                or not _time_is_at_or_before(_member(metric, "known_at"), decision)
            ):
                continue
            observations.append(
                PeerObservation(
                    instrument_id=str(item["instrument"]),
                    context=context,
                    metric=str(_member(metric, "metric_id")),
                    value=float(value),
                    weight=1.0,
                    effective_at=str(_member(metric, "effective_at")),
                    known_at=str(_member(metric, "known_at")),
                )
            )
    return tuple(observations)


def _exposure_peer_id(look_through: object | None, minimum_share: float) -> str:
    exposures = _member(look_through, "exposures", {})
    sectors = _member(exposures, "sector", {}) if isinstance(exposures, Mapping) else {}
    if not isinstance(sectors, Mapping) or not sectors:
        return "unavailable"
    candidates = sorted(
        (
            (float(weight), str(sector))
            for sector, weight in sectors.items()
            if isinstance(weight, (int, float))
            and not isinstance(weight, bool)
            and math.isfinite(float(weight))
            and float(weight) >= minimum_share
        ),
        key=lambda item: (-item[0], item[1]),
    )
    return f"sector:{candidates[0][1]}" if candidates else "unavailable"


def _look_through(instrument: str, decision: datetime) -> object | None:
    try:
        from etf_cockpit.analysis.look_through import calculate_look_through

        holdings = pd.read_parquet(FUND_HOLDINGS_PATH)
        try:
            fundamentals = pd.read_parquet(FUNDAMENTAL_CLEAN_PATH)
        except (FileNotFoundError, OSError, ValueError, ImportError):
            fundamentals = pd.DataFrame()
        return calculate_look_through(
            holdings,
            instrument_id=instrument,
            decision_time=decision,
            constituent_fundamentals=fundamentals,
        )
    except (FileNotFoundError, OSError, ValueError, TypeError, ImportError):
        return None


def _opportunity_slot_score(assessment: object, name: str) -> float | None:
    for slot in _member(assessment, "opportunity_slots", ()) or ():
        if str(_member(slot, "opportunity", "")) == name:
            if str(_member(slot, "status", "")).upper() != "AVAILABLE":
                return None
            value = _member(slot, "score")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _config_hashes() -> dict[str, str]:
    return {
        "decision_opportunity_v1": _file_hash(_PROJECT_CONFIG_DIR / "decision_opportunity_v1.yaml"),
        "decision_domains_v1": _file_hash(_DECISION_REGISTRY_PATH),
        "score_engine_v3": _file_hash(_PROJECT_CONFIG_DIR / "score_engine_v3.yaml"),
    }


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def _policy_version() -> str:
    try:
        return load_opportunity_policy().version
    except (OSError, ValueError):
        return "unavailable"


def _decision_timestamp(value: str | date) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time(23, 59, 59), tzinfo=timezone.utc)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _time_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _time_is_at_or_before(value: object, cutoff: datetime) -> bool:
    if not isinstance(value, (str, date, datetime)):
        return False
    try:
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize("UTC")
        else:
            parsed = parsed.tz_convert("UTC")
        return parsed.to_pydatetime() <= cutoff
    except (TypeError, ValueError, OverflowError):
        return False


def _member(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return str(value)


__all__ = ["run_decision_shadow"]
