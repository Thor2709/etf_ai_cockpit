"""Canonical v3 scoring contract shared by score and signal surfaces.

The contract deliberately keeps research attractiveness, model expected return,
risk/implementation quality and evidence confidence separate. The legacy
composite remains an explicitly named migration field until downstream readers
move to the separated outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.models.ensemble import effective_ensemble_weights


FORMULA_PATH = CONFIG_DIR / "score_engine_v3.yaml"
FORMULA_VERSION = "score-engine-v3.0.0"
_BLOCKED_FRESHNESS = {"stale", "stale_block", "unavailable", "missing", "unknown", "not_checked"}
_MODEL_AUTHORITIES = {"model", "model_advisory"}


class CanonicalScoreError(ValueError):
    """Raised when the versioned canonical score policy is invalid."""


@dataclass(frozen=True)
class ScorePolicy:
    formula_version: str
    formula_checksum: str
    horizon: str
    asset_type: str
    groups: dict[str, dict[str, float]]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "formula_version": self.formula_version,
            "formula_checksum": self.formula_checksum,
            "horizon": self.horizon,
            "asset_type": self.asset_type,
            "groups": self.groups,
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class CanonicalComponent:
    key: str
    raw_metric: float | None
    score_role: str
    peer_group: str
    source_id: str | None
    source_authority: str
    freshness_status: str
    uncertainty: str
    status: str
    explanation: str
    source_vintage_hash: str | None = None
    conflict_id: str | None = None

    @property
    def eligible(self) -> bool:
        if self.raw_metric is None or not math.isfinite(float(self.raw_metric)):
            return False
        if not self.source_id or self.status.casefold() != "ok":
            return False
        if self.freshness_status.casefold() in _BLOCKED_FRESHNESS or self.conflict_id:
            return False
        if self.score_role != "expected_return" and self.source_authority.casefold() in _MODEL_AUTHORITIES:
            return False
        return True

    def as_dict(self, *, weight: float, contribution_raw: float | None) -> dict[str, object]:
        return {
            "key": self.key,
            "raw_metric": self.raw_metric,
            "score_role": self.score_role,
            "peer_group": self.peer_group,
            "source_id": self.source_id,
            "source_authority": self.source_authority,
            "freshness_status": self.freshness_status,
            "uncertainty": self.uncertainty,
            "status": self.status,
            "explanation": self.explanation,
            "source_vintage_hash": self.source_vintage_hash,
            "conflict_id": self.conflict_id,
            "weight": weight,
            "contribution_raw": contribution_raw,
            "score_eligible": self.eligible,
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class CanonicalScore:
    instrument_id: str
    asset_type: str
    horizon: str
    decision_time: str
    formula_version: str
    formula_checksum: str
    source_vintage_hash: str
    attractiveness_10: float | None
    expected_return_10: float | None
    risk_implementation_10: float | None
    evidence_confidence_10: float | None
    coverage: float
    legacy_composite_raw: float | None
    components: tuple[dict[str, object], ...]
    contributions: tuple[dict[str, object], ...]
    warnings: tuple[str, ...]
    explanations: tuple[str, ...]

    @property
    def legacy_composite_10(self) -> float | None:
        if self.legacy_composite_raw is None:
            return None
        return round((_clamp(self.legacy_composite_raw) + 1.0) * 5.0, 1)

    @property
    def decision_distribution(self) -> dict[str, float | None]:
        """Return separated decision inputs for downstream policy consumers."""

        return {
            "attractiveness": _normalise_10(self.attractiveness_10),
            "expected_return": _normalise_10(self.expected_return_10),
            "risk_implementation": _normalise_10(self.risk_implementation_10),
            "evidence_confidence": _normalise_10(self.evidence_confidence_10),
            "coverage": self.coverage,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 3,
            "instrument_id": self.instrument_id,
            "asset_type": self.asset_type,
            "horizon": self.horizon,
            "decision_time": self.decision_time,
            "formula_version": self.formula_version,
            "formula_checksum": self.formula_checksum,
            "source_vintage_hash": self.source_vintage_hash,
            "attractiveness_10": self.attractiveness_10,
            "expected_return_10": self.expected_return_10,
            "risk_implementation_10": self.risk_implementation_10,
            "evidence_confidence_10": self.evidence_confidence_10,
            "coverage": self.coverage,
            "legacy_composite_raw": self.legacy_composite_raw,
            "legacy_composite_10": self.legacy_composite_10,
            "decision_distribution": self.decision_distribution,
            "components": list(self.components),
            "contributions": list(self.contributions),
            "warnings": list(self.warnings),
            "explanations": list(self.explanations),
            "execution_allowed": False,
        }


def load_score_policy(asset_type: str = "ETF", *, path: Path = FORMULA_PATH) -> ScorePolicy:
    try:
        raw_bytes = path.read_bytes()
        normalised_bytes = raw_bytes.replace(b"\r\n", b"\n")
        payload = yaml.safe_load(normalised_bytes.decode("utf-8")) or {}
        formula_version = str(payload.get("formula_version") or "").strip()
        horizons = payload.get("horizons") or {}
        horizon = str(horizons.get("primary") or "").strip()
        policies = payload.get("asset_policies") or {}
        selected = policies.get(str(asset_type).upper()) or policies.get("ETF")
        if not formula_version or not horizon or not isinstance(selected, dict):
            raise CanonicalScoreError("score_engine_v3.yaml is missing version, horizon or asset policy")
        groups: dict[str, dict[str, float]] = {}
        for group in ("attractiveness", "expected_return", "risk_implementation"):
            values = selected.get(group)
            if not isinstance(values, dict):
                raise CanonicalScoreError(f"score policy group is missing: {group}")
            groups[group] = {str(key): float(value) for key, value in values.items() if float(value) > 0}
            if sum(groups[group].values()) <= 0:
                raise CanonicalScoreError(f"score policy group has no positive weights: {group}")
        return ScorePolicy(formula_version, hashlib.sha256(normalised_bytes).hexdigest(), horizon, str(asset_type).upper(), groups)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        if isinstance(exc, CanonicalScoreError):
            raise
        raise CanonicalScoreError(f"could not load canonical score policy: {type(exc).__name__}") from exc


def build_canonical_score(
    *,
    instrument_id: str,
    asset_type: str,
    decision_time: str | date,
    components: Iterable[CanonicalComponent],
    legacy_component_weights: Mapping[str, float] | None = None,
    legacy_penalties: Mapping[str, float] | None = None,
    policy: ScorePolicy | None = None,
    source_vintage_hash: str | None = None,
) -> CanonicalScore:
    selected_policy = policy or load_score_policy(asset_type)
    timestamp = str(decision_time.isoformat() if isinstance(decision_time, date) else decision_time)
    source_components = tuple(components)
    group_results: dict[str, tuple[float | None, float, list[dict[str, object]], list[dict[str, object]]]] = {}
    all_component_rows: list[dict[str, object]] = []
    contributions: list[dict[str, object]] = []
    warnings: list[str] = []
    explanations: list[str] = []
    total_configured = 0.0
    total_active = 0.0
    for group, weights in selected_policy.groups.items():
        configured = sum(weights.values())
        active_weight = 0.0
        weighted = 0.0
        group_rows: list[dict[str, object]] = []
        group_contributions: list[dict[str, object]] = []
        for component in source_components:
            if _component_group(component) != group:
                continue
            weight = float(weights.get(component.key, 0.0))
            if weight <= 0:
                continue
            contribution = None
            if component.eligible:
                active_weight += weight
                contribution = _clamp(float(component.raw_metric)) * weight
                weighted += contribution
                group_contributions.append({"key": component.key, "group": group, "contribution_raw": contribution})
                explanations.append(f"{component.key}: {component.explanation}")
            group_rows.append(component.as_dict(weight=weight, contribution_raw=contribution))
        score = None if active_weight <= 0 else _score_10(weighted / active_weight)
        coverage = active_weight / configured if configured else 0.0
        if coverage < 1.0:
            warnings.append(f"{group}_coverage:{coverage:.3f}")
        total_configured += configured
        total_active += active_weight
        group_results[group] = (score, coverage, group_rows, group_contributions)
        for contribution in group_contributions:
            contribution["contribution_raw"] = round(float(contribution["contribution_raw"]) / active_weight, 10) if active_weight else None
        all_component_rows.extend(group_rows)
        contributions.extend(group_contributions)
    overall_coverage = total_active / total_configured if total_configured else 0.0
    confidence = _confidence_score(source_components, overall_coverage)
    legacy_raw = _legacy_composite(source_components, legacy_component_weights, legacy_penalties)
    vintage_hash = source_vintage_hash or source_vintage_fingerprint(source_components, timestamp)
    return CanonicalScore(
        instrument_id=str(instrument_id),
        asset_type=str(asset_type).upper(),
        horizon=selected_policy.horizon,
        decision_time=timestamp,
        formula_version=selected_policy.formula_version,
        formula_checksum=selected_policy.formula_checksum,
        source_vintage_hash=vintage_hash,
        attractiveness_10=group_results["attractiveness"][0],
        expected_return_10=group_results["expected_return"][0],
        risk_implementation_10=group_results["risk_implementation"][0],
        evidence_confidence_10=confidence,
        coverage=round(overall_coverage, 6),
        legacy_composite_raw=legacy_raw,
        components=tuple(all_component_rows),
        contributions=tuple(contributions),
        warnings=tuple(dict.fromkeys(warnings)),
        explanations=tuple(dict.fromkeys(explanations)),
    )


def canonical_score_from_simple_components(
    instrument_id: str,
    asset_type: str,
    decision_time: str,
    components: Iterable[Any],
) -> CanonicalScore:
    converted = (
        CanonicalComponent(
            key=str(getattr(component, "key", "")),
            raw_metric=_number(getattr(component, "raw_score", None)),
            score_role=_component_group_name(str(getattr(component, "score_role", "evidence"))),
            peer_group=str(getattr(component, "peer_group", None) or "universe"),
            source_id=str(getattr(component, "source_id", "") or "") or None,
            source_authority=str(getattr(component, "source_authority", "unknown") or "unknown"),
            freshness_status=str(getattr(component, "freshness_status", "unknown") or "unknown"),
            uncertainty=_uncertainty(getattr(component, "evidence_quality", None)),
            status="ok" if str(getattr(component, "status", "")).casefold() == "ok" else str(getattr(component, "status", "unavailable")),
            explanation=str(getattr(component, "why", "") or getattr(component, "explanation", "") or "Score component evidence."),
            source_vintage_hash=str(getattr(component, "source_vintage_hash", "") or "") or None,
            conflict_id=str(getattr(component, "conflict_id", "") or "") or None,
        )
        for component in components
    )
    return build_canonical_score(instrument_id=instrument_id, asset_type=asset_type, decision_time=decision_time, components=converted)


def canonical_score_from_signal_row(
    row: Mapping[str, object],
    config: AppConfig,
    decision_time: str | date,
    *,
    toto_available: bool = False,
    timesfm_available: bool = False,
) -> CanonicalScore:
    instrument_id = str(row.get("etf_id") or row.get("instrument_id") or "unknown")
    as_of = str(decision_time.isoformat() if isinstance(decision_time, date) else decision_time)
    price_freshness = "ok" if as_of not in {"", "None", "nan"} else "unknown"
    source = "yfinance:prices"
    components = [
        _signal_component("momentum", row.get("score_momentum"), "attractiveness", source, price_freshness, "Momentum evidence."),
        _signal_component("trend", row.get("score_trend"), "attractiveness", source, price_freshness, "Trend evidence."),
        _signal_component("relative_strength", row.get("score_relative_strength"), "attractiveness", source, price_freshness, "Relative-strength evidence."),
        _signal_component("risk", row.get("score_risk"), "risk_implementation", source, price_freshness, "Risk quality evidence."),
        _signal_component("rebalance", row.get("score_rebalance"), "risk_implementation", "local:allocation", price_freshness, "Allocation drift evidence."),
        _signal_component("liquidity_cost", _liquidity_quality(row.get("cost_penalty")), "risk_implementation", source, price_freshness, "Configured cost quality."),
        _signal_component("baseline", row.get("score_baseline_ml"), "expected_return", "model:baseline", price_freshness, "Baseline expected-return evidence.", authority="model_advisory"),
        _signal_component("timesfm", row.get("score_timesfm"), "expected_return", "model:timesfm", price_freshness, "TimesFM challenger expected-return evidence.", authority="model_advisory", status="ok" if timesfm_available else "unavailable"),
        _signal_component("toto", row.get("score_toto"), "expected_return", "model:toto", price_freshness, "Toto challenger expected-return evidence.", authority="model_advisory", status="ok" if toto_available else "unavailable"),
    ]
    weights = effective_ensemble_weights(
        config.models.ensemble.get("weights", {}),
        toto_available=toto_available,
        timesfm_available=timesfm_available,
    )
    return build_canonical_score(
        instrument_id=instrument_id,
        asset_type="ETF",
        decision_time=decision_time,
        components=components,
        legacy_component_weights={str(key): float(value) for key, value in weights.items()},
        legacy_penalties={
            "cost_penalty": _number(row.get("cost_penalty")) or 0.0,
            "turnover_penalty": _number(row.get("turnover_penalty")) or 0.0,
        },
    )


def source_vintage_fingerprint(components: Iterable[CanonicalComponent], decision_time: str) -> str:
    payload = {
        "decision_time": decision_time,
        "sources": sorted(
            (
                {
                    "source_id": component.source_id,
                    "source_vintage_hash": component.source_vintage_hash,
                }
                for component in components
                if component.source_id
            ),
            key=lambda value: (str(value["source_id"]), str(value["source_vintage_hash"])),
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _component_group(component: CanonicalComponent) -> str:
    role = _component_group_name(component.score_role)
    return role if role in {"attractiveness", "expected_return", "risk_implementation"} else "attractiveness"


def _component_group_name(role: str) -> str:
    value = str(role).casefold()
    if value in {"risk", "risk_friction", "risk_implementation"}:
        return "risk_implementation"
    if value in {"model_confirmation", "expected_return", "forecast"}:
        return "expected_return"
    return "attractiveness"


def _confidence_score(components: Iterable[CanonicalComponent], coverage: float) -> float | None:
    eligible = [component for component in components if component.eligible]
    if not eligible:
        return None
    values = []
    for component in eligible:
        authority = {
            "official_regulator": 1.0,
            "official_filing": 1.0,
            "issuer_document": 0.9,
            "vendor_verified": 0.8,
            "vendor_unofficial": 0.6,
            "model_advisory": 0.25,
        }.get(component.source_authority.casefold(), 0.3)
        freshness = 1.0 if component.freshness_status.casefold() == "ok" else 0.5
        uncertainty = {"low": 1.0, "medium": 0.8, "high": 0.5}.get(component.uncertainty.casefold(), 0.4)
        values.append(authority * freshness * uncertainty)
    return round(max(0.0, min(10.0, 10.0 * (sum(values) / len(values)) * coverage)), 1)


def _legacy_composite(
    components: Iterable[CanonicalComponent],
    weights: Mapping[str, float] | None,
    penalties: Mapping[str, float] | None,
) -> float | None:
    if not weights:
        return None
    values = {
        component.key: _number(component.raw_metric)
        for component in components
        if component.eligible and _number(component.raw_metric) is not None
    }
    active_weights = {key: float(weight) for key, weight in weights.items() if key in values and float(weight) > 0}
    weight_total = sum(active_weights.values())
    if not values or weight_total <= 0:
        return None
    result = sum(weight * float(values[key]) for key, weight in active_weights.items()) / weight_total
    for key, penalty in (penalties or {}).items():
        result -= max(0.0, float(penalty))
    return round(_clamp(result), 4)


def _signal_component(key: str, raw: object, role: str, source_id: str, freshness: str, explanation: str, *, authority: str = "vendor_unofficial", status: str = "ok") -> CanonicalComponent:
    return CanonicalComponent(key, _number(raw), role, "configured-universe", source_id, authority, freshness, "medium", status, explanation)


def _liquidity_quality(value: object) -> float | None:
    penalty = _number(value)
    return None if penalty is None else _clamp(1.0 - penalty / 0.08)


def _uncertainty(value: object) -> str:
    try:
        quality = float(value)
    except (TypeError, ValueError):
        return "high"
    return "low" if quality >= 8 else "medium" if quality >= 5 else "high"


def _number(value: object) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and math.isfinite(number) else None


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def _score_10(value: float) -> float:
    return round((_clamp(value) + 1.0) * 5.0, 1)


def _normalise_10(value: float | None) -> float | None:
    return None if value is None else round(max(0.0, min(1.0, float(value) / 10.0)), 6)
