"""Advisory top-N selection from frozen OpportunityResult and portfolio inputs.

Asset-specific peer ranks are used only to order their own asset family. The
cross-asset utility uses common saved return, risk, portfolio-impact, liquidity,
cost and evidence inputs after empirical mid-rank normalisation. Policy cutoffs,
weights, bootstrap count, support and tie-breaking are versioned in
``configs/top_n_selection_v1.yaml``; these conservative defaults are policy
choices, not estimated thresholds: N=10 (maximum 25), minimum raw and effective
support=5, 200 bootstrap samples with default seed 0, and utility weights of
0.35 return, 0.20 downside risk, 0.20 marginal impact, 0.10 liquidity, 0.10
cost and 0.05 evidence. Candidate support uses equal candidate weights, so its
Kish effective sample size is the number of supported rows. Bootstrap draws
resample the frozen candidate table with the recorded NumPy seed; they never
re-run analysis or alter the stored base utility. Rank stability is one minus
the population rank standard deviation divided by cohort size, floored at zero;
rank intervals use the 5th and 95th bootstrap percentiles, rounded outward.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import numpy as np
import yaml

from etf_cockpit.analysis.decision.contracts import OpportunityResult
from etf_cockpit.core.values import finite_non_bool_number_or_none as _finite, positive_int_or_none as _positive_int
from etf_cockpit.portfolio.forecast_aggregation import PortfolioForecastSnapshot
from etf_cockpit.portfolio.goals_constraints import (
    ConstraintResult,
    PortfolioPolicy,
    build_what_if_scenario,
    policy_record,
)
from etf_cockpit.portfolio.risk_profiles import (
    RiskProfileVersion,
    VWCEAnchorSnapshot,
    project_risk_profile,
    risk_profile_version_record,
)


SELECTION_RUN_ENTITY_TYPE = "top_n_selection_run.v1"
SELECTION_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "top_n_selection_v1.yaml"
_ASSET_FAMILIES = ("stock", "etf", "ordinary_fund", "bond")
_UTILITY_FIELDS = (
    "net_expected_return",
    "downside_risk",
    "marginal_impact",
    "liquidity",
    "cost",
    "evidence",
)


class SelectionPolicyError(ValueError):
    """The versioned top-N policy is missing or invalid."""


@dataclass(frozen=True)
class SelectionPolicy:
    version: str
    checksum: str
    top_n: int
    maximum_top_n: int
    minimum_raw_support: int
    minimum_effective_support: float
    bootstrap_count: int
    bootstrap_seed: int
    weights: tuple[tuple[str, float], ...]
    tie_break: str
    utility_name: str
    schema_version: str = "top_n_selection.v1"

    def to_record(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "checksum": self.checksum,
            "top_n": self.top_n,
            "maximum_top_n": self.maximum_top_n,
            "minimum_raw_support": self.minimum_raw_support,
            "minimum_effective_support": self.minimum_effective_support,
            "bootstrap_count": self.bootstrap_count,
            "bootstrap_seed": self.bootstrap_seed,
            "weights": dict(self.weights),
            "tie_break": self.tie_break,
            "utility_name": self.utility_name,
        }


@dataclass(frozen=True)
class SelectionCandidate:
    """Selection metadata around the canonical, already-ranked opportunity."""

    opportunity: OpportunityResult
    common_metrics_as_of: str | None = None
    country: str | None = None
    sector: str | None = None
    net_expected_return: float | None = None
    downside_risk: float | None = None
    marginal_impact: float | None = None
    liquidity: float | None = None
    cost: float | None = None
    evidence: float | None = None
    hard_gate_reasons: tuple[str, ...] = ()
    constraint_results: tuple[ConstraintResult, ...] = ()
    what_if_scenario: object | None = None
    constraint_analysis: object | None = None
    constraint_snapshot: object | None = None
    constraint_evidence: Mapping[str, object] | None = None
    portfolio_forecast: PortfolioForecastSnapshot | None = None
    source_hashes: tuple[tuple[str, str], ...] = ()

    @property
    def instrument_id(self) -> str:
        return self.opportunity.instrument


@dataclass(frozen=True)
class SelectionRun:
    run_id: str
    input_hash: str
    status: Literal["available", "partial", "unavailable"]
    mode: Literal["asset_specific", "cross_asset", "unavailable"]
    reason: str | None
    decision_time: str
    top_n: int
    seed: int
    policy: SelectionPolicy
    asset_specific_lists: tuple[tuple[str, tuple[str, ...]], ...]
    candidate_table: tuple[Mapping[str, object], ...]
    selected_ids: tuple[str, ...]
    exclusion_funnel: tuple[tuple[str, int], ...]
    source_snapshot_hashes: tuple[tuple[str, str], ...]
    frozen_inputs: Mapping[str, object]
    portfolio_reference: Mapping[str, object] | None
    portfolio_policy_hash: str | None
    risk_profile_hash: str | None
    execution_allowed: Literal[False] = False

    def to_record(self) -> dict[str, object]:
        """Return the deterministic, JSON-safe append-only run payload."""

        return _json_value(
            {
                "contract": "selection-run.v1",
                "run_id": self.run_id,
                "input_hash": self.input_hash,
                "status": self.status,
                "mode": self.mode,
                "reason": self.reason,
                "decision_time": self.decision_time,
                "top_n": self.top_n,
                "seed": self.seed,
                "policy": self.policy,
                "asset_specific_lists": self.asset_specific_lists,
                "candidate_table": self.candidate_table,
                "selected_ids": self.selected_ids,
                "exclusion_funnel": self.exclusion_funnel,
                "source_snapshot_hashes": self.source_snapshot_hashes,
                "frozen_inputs": self.frozen_inputs,
                "portfolio_reference": self.portfolio_reference,
                "portfolio_policy_hash": self.portfolio_policy_hash,
                "risk_profile_hash": self.risk_profile_hash,
                "execution_allowed": self.execution_allowed,
            }
        )  # type: ignore[return-value]


def load_selection_policy(path: str | Path = SELECTION_CONFIG) -> SelectionPolicy:
    """Load policy values fail-closed; every numeric default is in the YAML."""

    try:
        content = Path(path).read_bytes()
        payload = yaml.safe_load(content.decode("utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SelectionPolicyError("top_n_selection_policy_unavailable_or_invalid") from exc
    expected = {
        "schema_version", "version", "top_n", "maximum_top_n",
        "minimum_raw_support", "minimum_effective_support", "bootstrap_count",
        "bootstrap_seed", "utility_name", "tie_break", "weights",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise SelectionPolicyError("top_n_selection_policy_schema_invalid")
    if payload.get("schema_version") != "top_n_selection.v1":
        raise SelectionPolicyError("top_n_selection_policy_schema_unsupported")
    version = _text(payload.get("version"))
    utility_name = _text(payload.get("utility_name"))
    tie_break = _text(payload.get("tie_break"))
    top_n = _positive_int(payload.get("top_n"))
    maximum_top_n = _positive_int(payload.get("maximum_top_n"))
    minimum_raw_support = _positive_int(payload.get("minimum_raw_support"))
    minimum_effective_support = _finite(payload.get("minimum_effective_support"))
    bootstrap_count = _positive_int(payload.get("bootstrap_count"))
    bootstrap_seed = _nonnegative_int(payload.get("bootstrap_seed"))
    raw_weights = payload.get("weights")
    if (
        not version
        or not utility_name
        or tie_break != "utility_descending_instrument_id_ascending"
        or top_n is None
        or maximum_top_n is None
        or top_n > maximum_top_n
        or minimum_raw_support is None
        or minimum_effective_support is None
        or minimum_effective_support <= 0
        or bootstrap_count is None
        or bootstrap_seed is None
        or not isinstance(raw_weights, Mapping)
        or set(raw_weights) != set(_UTILITY_FIELDS)
    ):
        raise SelectionPolicyError("top_n_selection_policy_values_invalid")
    weights = {name: _finite(raw_weights[name]) for name in _UTILITY_FIELDS}
    if any(value is None or value < 0 for value in weights.values()):
        raise SelectionPolicyError("top_n_selection_weights_invalid")
    if not math.isclose(sum(float(value) for value in weights.values()), 1.0, abs_tol=1e-9):
        raise SelectionPolicyError("top_n_selection_weights_must_sum_to_one")
    checksum = hashlib.sha256(content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()
    return SelectionPolicy(
        version=version,
        checksum=checksum,
        top_n=top_n,
        maximum_top_n=maximum_top_n,
        minimum_raw_support=minimum_raw_support,
        minimum_effective_support=minimum_effective_support,
        bootstrap_count=bootstrap_count,
        bootstrap_seed=bootstrap_seed,
        weights=tuple((name, float(weights[name])) for name in _UTILITY_FIELDS),
        tie_break=tie_break,
        utility_name=utility_name,
    )


def build_selection_run(
    candidates: Sequence[SelectionCandidate],
    *,
    decision_time: str,
    mode: Literal["asset_specific", "cross_asset"] = "cross_asset",
    policy: SelectionPolicy | None = None,
    top_n: int | None = None,
    seed: int | None = None,
    portfolio_snapshot: Mapping[str, object] | None = None,
    reference_anchor: object | None = None,
    portfolio_policy: PortfolioPolicy | None = None,
    risk_profile: RiskProfileVersion | None = None,
) -> SelectionRun:
    """Build one frozen selection table without recalculating OpportunityResult.

    Portfolio guardrails come from canonical ``WhatIfScenario`` results or are
    evaluated by ``goals_constraints.evaluate_constraints``. Profile guardrails
    come from ``risk_profiles.project_risk_profile``. When the caller has no
    portfolio, the canonical VWCE anchor identity is recorded as the reference;
    an absent anchor makes cross-asset selection unavailable.
    """

    selected_policy = policy or load_selection_policy()
    selected_top_n = selected_policy.top_n if top_n is None else _positive_int(top_n)
    if selected_top_n is None or selected_top_n > selected_policy.maximum_top_n:
        raise ValueError("top_n is outside the configured selection range")
    chosen_seed = selected_policy.bootstrap_seed if seed is None else _nonnegative_int(seed)
    if chosen_seed is None:
        raise ValueError("seed must be a non-negative integer")
    if mode not in {"asset_specific", "cross_asset"}:
        raise ValueError("selection mode is unsupported")
    _validate_decision_time(decision_time)
    ordered = tuple(sorted(candidates, key=lambda row: row.instrument_id))
    if len({row.instrument_id for row in ordered}) != len(ordered):
        raise ValueError("selection candidate instrument ids must be unique")

    anchor = _portfolio_reference(portfolio_snapshot, reference_anchor, decision_time)
    effective_mode: Literal["asset_specific", "cross_asset", "unavailable"] = mode
    unavailable_reason: str | None = None
    if not ordered:
        effective_mode = "unavailable"
        unavailable_reason = "opportunity_candidates_unavailable"
    elif mode == "cross_asset" and anchor is None:
        effective_mode = "unavailable"
        unavailable_reason = "reference_portfolio_unavailable"
    elif (
        mode == "cross_asset"
        and portfolio_snapshot is None
        and anchor is not None
        and anchor.get("risk_envelope_status") != "available"
    ):
        unavailable_reason = "vwce_reference_risk_envelope_unavailable"

    profile_record = _profile_record(risk_profile)
    portfolio_policy_record = None if portfolio_policy is None else policy_record(portfolio_policy)
    input_material = {
        "decision_time": decision_time,
        "mode": mode,
        "top_n": selected_top_n,
        "policy": selected_policy.to_record(),
        "candidates": [_candidate_input_record(item) for item in ordered],
        "portfolio_snapshot": _json_value(portfolio_snapshot),
        "reference_anchor": _json_value(reference_anchor),
        "portfolio_reference": anchor,
        "portfolio_policy": portfolio_policy_record,
        "risk_profile": profile_record,
    }
    input_hash = _digest(input_material)
    run_id = _digest({"input_hash": input_hash, "seed": chosen_seed})
    candidate_rows: list[dict[str, object]] = []
    by_family: dict[str, list[SelectionCandidate]] = {family: [] for family in _ASSET_FAMILIES}

    for candidate in ordered:
        family = _asset_family(candidate.opportunity.asset_type)
        if family in by_family:
            by_family[family].append(candidate)
        gate_reasons = _hard_gate_reasons(candidate)
        constraint_reasons = _constraint_reasons(candidate, portfolio_policy, risk_profile)
        opportunity_time = _parse_datetime(candidate.opportunity.decision_time)
        if opportunity_time > _parse_datetime(decision_time):
            gate_reasons = (*gate_reasons, "source_decision_time_after_selection_cutoff")
        reason_codes = [*gate_reasons, *constraint_reasons]
        if mode == "cross_asset":
            if candidate.common_metrics_as_of is None:
                reason_codes.append("common_metrics_point_in_time_unavailable")
            else:
                try:
                    if _parse_datetime(candidate.common_metrics_as_of) > _parse_datetime(decision_time):
                        reason_codes.append("common_metrics_after_selection_cutoff")
                except ValueError:
                    reason_codes.append("common_metrics_point_in_time_invalid")
        if family not in _ASSET_FAMILIES:
            reason_codes.append("asset_family_unavailable_or_unsupported")
        metrics = _common_metrics(candidate)
        row: dict[str, object] = {
            "instrument_id": candidate.instrument_id,
            "asset_family": family,
            "country": _category(candidate.country),
            "sector": _category(candidate.sector),
            "peer_rank": candidate.opportunity.peer_rank,
            "peer_percentile": candidate.opportunity.peer_percentile,
            "peer_support": candidate.opportunity.peer_support,
            "common_metrics": metrics,
            "utility_score": None,
            "utility_rank": None,
            "selection_probability": None,
            "rank_stability": None,
            "rank_interval": None,
            "selected": False,
            "why_selected": [],
            "why_not": list(dict.fromkeys(reason_codes)),
            "constraint_reasons": list(constraint_reasons),
            "hard_gate_reasons": list(_hard_gate_reasons(candidate)),
            "source_snapshot_hashes": _candidate_hashes(candidate),
            "frozen_source_snapshot": _candidate_input_record(candidate),
        }
        candidate_rows.append(row)

    asset_lists: dict[str, tuple[str, ...]] = {}
    if effective_mode == "asset_specific":
        selected: list[str] = []
        row_by_id = {str(row["instrument_id"]): row for row in candidate_rows}
        for family in _ASSET_FAMILIES:
            ranked = sorted(
                (
                    item for item in by_family[family]
                    if not row_by_id[item.instrument_id]["why_not"]
                    and item.opportunity.peer_rank is not None
                ),
                key=lambda item: (item.opportunity.peer_rank, item.instrument_id),
            )
            ids = tuple(item.instrument_id for item in ranked)
            asset_lists[family] = ids
            winners = set(ids[:selected_top_n])
            selected.extend(ids[:selected_top_n])
            for row in candidate_rows:
                if row["asset_family"] != family:
                    continue
                instrument_id = str(row["instrument_id"])
                if row["peer_rank"] is None and not row["why_not"]:
                    row["why_not"] = ["asset_specific_peer_rank_unavailable"]
                elif instrument_id in winners:
                    row["selected"] = True
                    row["why_selected"] = ["top_n_asset_specific_peer_rank"]
                elif not row["why_not"]:
                    row["why_not"] = ["outside_asset_specific_top_n"]
        for family in _ASSET_FAMILIES:
            asset_lists.setdefault(family, ())
        selected_ids = tuple(sorted(selected))
    elif effective_mode == "cross_asset":
        for family in _ASSET_FAMILIES:
            asset_lists[family] = tuple(
                item.instrument_id
                for item in sorted(
                    by_family[family],
                    key=lambda item: (
                        item.opportunity.peer_rank is None,
                        item.opportunity.peer_rank or 0,
                        item.instrument_id,
                    ),
                )
            )
        if unavailable_reason is not None:
            selected_ids = ()
            for row in candidate_rows:
                if not row["why_not"]:
                    row["why_not"] = [unavailable_reason]
        else:
            selected_ids = _rank_cross_asset(
                candidate_rows,
                selected_policy,
                selected_top_n,
                chosen_seed,
            )
            if not selected_ids and any(
                "cross_asset_sample_support_below_minimum" in row["why_not"]
                for row in candidate_rows
            ):
                unavailable_reason = "cross_asset_sample_support_below_minimum"
    else:
        for family in _ASSET_FAMILIES:
            asset_lists[family] = tuple(
                item.instrument_id
                for item in sorted(
                    by_family[family],
                    key=lambda item: (
                        item.opportunity.peer_rank is None,
                        item.opportunity.peer_rank or 0,
                        item.instrument_id,
                    ),
                )
            )
        selected_ids = ()
        for row in candidate_rows:
            if not row["why_not"]:
                row["why_not"] = [unavailable_reason or "cross_asset_selection_unavailable"]

    selected_set = set(selected_ids)
    for row in candidate_rows:
        if row["selected"]:
            continue
        if str(row["instrument_id"]) in selected_set:
            row["selected"] = True
            row["why_selected"] = ["highest_common_utility_within_top_n"]
            row["why_not"] = []
    funnel = Counter(
        str(reason)
        for row in candidate_rows
        if not row["selected"]
        for reason in (row["why_not"] or ["outside_top_n"])
    )
    source_hashes = _run_source_hashes(ordered, input_hash, selected_policy)
    status: Literal["available", "partial", "unavailable"] = (
        "unavailable" if effective_mode == "unavailable" or (unavailable_reason is not None and not selected_ids)
        else "partial" if any(not row["selected"] for row in candidate_rows)
        else "available"
    )
    return SelectionRun(
        run_id=run_id,
        input_hash=input_hash,
        status=status,
        mode=effective_mode,
        reason=unavailable_reason,
        decision_time=decision_time,
        top_n=selected_top_n,
        seed=chosen_seed,
        policy=selected_policy,
        asset_specific_lists=tuple((family, asset_lists[family]) for family in _ASSET_FAMILIES),
        candidate_table=tuple(_deep_freeze(_json_value(row)) for row in candidate_rows),
        selected_ids=selected_ids,
        exclusion_funnel=tuple(sorted(funnel.items())),
        source_snapshot_hashes=source_hashes,
        frozen_inputs=_deep_freeze(_json_value(input_material)),  # type: ignore[arg-type]
        portfolio_reference=None if anchor is None else _deep_freeze(anchor),  # type: ignore[arg-type]
        portfolio_policy_hash=None if portfolio_policy_record is None else _digest(portfolio_policy_record),
        risk_profile_hash=None if profile_record is None else _digest(profile_record),
    )


def persist_selection_run(store: object, run: SelectionRun) -> object:
    """Append one immutable run via the existing generic transactional store."""

    put_many = getattr(store, "put_many", None)
    if not callable(put_many):
        raise TypeError("selection persistence requires TransactionalStore.put_many")
    return put_many(
        ((SELECTION_RUN_ENTITY_TYPE, run.run_id, run.to_record()),),
        immutable=True,
    )[0]


def _rank_cross_asset(
    rows: list[dict[str, object]], policy: SelectionPolicy, top_n: int, seed: int
) -> tuple[str, ...]:
    weights = dict(policy.weights)
    eligible = []
    for row in rows:
        if row["why_not"]:
            continue
        metrics = row["common_metrics"]
        if not isinstance(metrics, Mapping) or any(
            _finite(metrics.get(field)) is None for field in _UTILITY_FIELDS
        ):
            missing = [field for field in _UTILITY_FIELDS if _finite(metrics.get(field)) is None]
            row["why_not"] = ["common_utility_input_unavailable:" + ",".join(missing)]
            continue
        eligible.append(row)
    if not eligible:
        return ()
    if (
        len(eligible) < policy.minimum_raw_support
        or len(eligible) < policy.minimum_effective_support
    ):
        for row in eligible:
            row["why_not"] = ["cross_asset_sample_support_below_minimum"]
        return ()

    metric_rows = [row["common_metrics"] for row in eligible]
    scores = _utility_scores(metric_rows, metric_rows, weights)
    for row, score in zip(eligible, scores, strict=True):
        row["utility_score"] = float(score)
    eligible.sort(key=lambda row: (-float(row["utility_score"]), str(row["instrument_id"])))
    for index, row in enumerate(eligible, start=1):
        row["utility_rank"] = index
        if index > top_n:
            row["why_not"] = ["outside_top_n"]
    selected = tuple(str(row["instrument_id"]) for row in eligible[:top_n])
    _bootstrap_fields(eligible, weights, top_n, policy.bootstrap_count, seed)
    return selected


def _bootstrap_fields(
    rows: list[dict[str, object]],
    weights: Mapping[str, float],
    top_n: int,
    bootstrap_count: int,
    seed: int,
) -> None:
    """Estimate top-N frequency and rank stability from seeded row resamples."""

    rng = np.random.default_rng(seed)
    sample_count = len(rows)
    selection_counts: Counter[str] = Counter()
    ranks: dict[str, list[int]] = {str(row["instrument_id"]): [] for row in rows}
    ids = [str(row["instrument_id"]) for row in rows]
    metric_rows = [row["common_metrics"] for row in rows]
    for _ in range(bootstrap_count):
        sampled = rng.integers(0, sample_count, size=sample_count)
        sampled_metrics = [metric_rows[int(index)] for index in sampled]
        occurrence_scores = _utility_scores(sampled_metrics, sampled_metrics, weights)
        sampled_scores: dict[str, list[float]] = {}
        for index, score in zip(sampled, occurrence_scores, strict=True):
            position = int(index)
            sampled_scores.setdefault(ids[position], []).append(float(score))
        ordered = sorted(
            ((sum(values) / len(values), candidate_id) for candidate_id, values in sampled_scores.items()),
            key=lambda item: (-item[0], item[1]),
        )
        for rank, (_score, candidate_id) in enumerate(ordered, start=1):
            ranks[candidate_id].append(rank)
            if rank <= top_n:
                selection_counts[candidate_id] += 1
    for row in rows:
        candidate_id = str(row["instrument_id"])
        observed = ranks[candidate_id]
        row["selection_probability"] = selection_counts[candidate_id] / bootstrap_count
        row["rank_stability"] = (
            max(0.0, 1.0 - float(np.std(observed, ddof=0)) / max(1, sample_count))
            if observed
            else 0.0
        )
        row["rank_interval"] = (
            [int(math.floor(float(np.quantile(observed, 0.05)))), int(math.ceil(float(np.quantile(observed, 0.95))))]
            if observed
            else None
        )


def _utility_scores(
    metric_rows: Sequence[Mapping[str, object]],
    reference_rows: Sequence[Mapping[str, object]],
    weights: Mapping[str, float],
) -> np.ndarray:
    scores = np.zeros(len(metric_rows), dtype=float)
    for field in _UTILITY_FIELDS:
        values = np.asarray([float(row[field]) for row in metric_rows], dtype=float)
        reference = np.sort(np.asarray([float(row[field]) for row in reference_rows], dtype=float))
        left = np.searchsorted(reference, values, side="left")
        right = np.searchsorted(reference, values, side="right")
        percentile = (left + 0.5 * (right - left)) / len(reference)
        lower_is_better = field in {"downside_risk", "cost"}
        if lower_is_better:
            percentile = 1.0 - percentile
        scores += weights[field] * percentile
    return scores


def _common_metrics(candidate: SelectionCandidate) -> dict[str, float | None]:
    metrics = {
        "net_expected_return": _finite(candidate.net_expected_return),
        "downside_risk": _finite(candidate.downside_risk),
        "marginal_impact": _marginal_impact(candidate),
        "liquidity": _finite(candidate.liquidity),
        "cost": _finite(candidate.cost),
        "evidence": _finite(candidate.evidence if candidate.evidence is not None else candidate.opportunity.confidence),
    }
    return metrics


def _marginal_impact(candidate: SelectionCandidate) -> float | None:
    supplied = _finite(candidate.marginal_impact)
    if supplied is not None:
        return supplied
    if candidate.portfolio_forecast is None:
        return None
    comparison = candidate.portfolio_forecast.comparison
    if comparison.get("status") != "available":
        return None
    # The saved lower-tail return difference is the conservative marginal-fit signal.
    return _finite(comparison.get("q05_return_difference"))


def _constraint_reasons(
    candidate: SelectionCandidate,
    portfolio_policy: PortfolioPolicy | None,
    risk_profile: RiskProfileVersion | None,
) -> tuple[str, ...]:
    scenario = candidate.what_if_scenario
    rows: list[object] = list(candidate.constraint_results)
    if scenario is not None:
        status = str(getattr(scenario, "status", "unavailable"))
        if status == "blocked":
            blockers = tuple(str(item) for item in getattr(scenario, "binding_constraints", ()) or ())
            return tuple("after_trade_constraint_blocked:" + item for item in blockers) or (
                "after_trade_constraint_blocked",
            )
        if status != "ready":
            return ("after_trade_constraints_unavailable",)
        rows.extend(tuple(getattr(scenario, "constraints", ()) or ()))
    if risk_profile is not None:
        if candidate.constraint_analysis is None or candidate.constraint_snapshot is None:
            return ("risk_profile_after_trade_context_unavailable",)
        projection = project_risk_profile(
            risk_profile, candidate.constraint_analysis, candidate.constraint_snapshot
        )
        scenario_record = projection.scenario
        raw_constraints = scenario_record.get("constraints", ())
        if isinstance(raw_constraints, Sequence):
            rows.extend(raw_constraints)
        scenario_status = str(scenario_record.get("status", "unavailable"))
        if scenario_status == "blocked":
            if not rows:
                return ("risk_profile_after_trade_constraint_blocked",)
        if scenario_status != "ready":
            if scenario_status != "blocked":
                return ("risk_profile_after_trade_constraints_unavailable",)
    if portfolio_policy is not None and _policy_has_limits(portfolio_policy):
        if candidate.constraint_analysis is None or candidate.constraint_snapshot is None:
            return ("after_trade_constraint_context_unavailable",)
        user_scenario = build_what_if_scenario(
            candidate.constraint_analysis,
            candidate.constraint_snapshot,
            portfolio_policy,
            evidence=candidate.constraint_evidence,
        )
        if user_scenario.status == "blocked":
            return tuple(
                "after_trade_constraint_blocked:" + item.constraint_id
                for item in user_scenario.constraints
                if item.blocking
            ) or ("after_trade_constraint_blocked",)
        if user_scenario.status != "ready":
            return ("after_trade_constraints_unavailable",)
        rows.extend(user_scenario.constraints)
    reasons: list[str] = []
    for result in rows:
        constraint_id = str(_field(result, "constraint_id", "constraint_unavailable"))
        blocking = _field(result, "blocking", False) is True
        status = str(_field(result, "status", "unavailable"))
        if blocking or status == "blocked":
            reasons.append("after_trade_constraint_blocked:" + constraint_id)
        elif status == "unavailable":
            reasons.append("after_trade_constraint_unavailable:" + constraint_id)
    return tuple(reasons)


def _hard_gate_reasons(candidate: SelectionCandidate) -> tuple[str, ...]:
    supplied = tuple(
        "hard_gate_failed:" + (str(reason).strip() or "reason_unavailable")
        for reason in candidate.hard_gate_reasons
    )
    if candidate.opportunity.status.strip().casefold() == "blocked":
        reason = candidate.opportunity.reason_code.strip() or "opportunity_hard_gate_blocked"
        return (*supplied, "hard_gate_failed:" + reason)
    return supplied


def _policy_has_limits(policy: PortfolioPolicy) -> bool:
    record = policy_record(policy)
    return any(
        value not in (None, {}, [])
        for key, value in record.items()
        if key not in {"policy_id", "version", "schema_version"}
    )


def _portfolio_reference(
    portfolio_snapshot: Mapping[str, object] | None,
    reference_anchor: object | None,
    decision_time: str,
) -> dict[str, object] | None:
    if portfolio_snapshot is not None:
        portfolio_id = _text(portfolio_snapshot.get("portfolio_id"))
        snapshot_id = _text(portfolio_snapshot.get("snapshot_id"))
        as_of = _text(portfolio_snapshot.get("as_of"))
        if portfolio_id and snapshot_id and as_of:
            try:
                if _parse_datetime(as_of) > _parse_datetime(decision_time):
                    return None
            except ValueError:
                return None
            return {
                "kind": "portfolio_snapshot",
                "portfolio_id": portfolio_id,
                "snapshot_id": snapshot_id,
                "as_of": as_of,
                "input_hash": _digest(portfolio_snapshot),
            }
        return None
    if reference_anchor is None:
        return None
    if not isinstance(reference_anchor, VWCEAnchorSnapshot):
        return None
    status = _text(_field(reference_anchor, "status"))
    anchor_id = _text(_field(reference_anchor, "canonical_share_class_id"))
    knowledge_cutoff = _text(_field(reference_anchor, "knowledge_cutoff"))
    effective_date = _text(_field(reference_anchor, "effective_date"))
    if status != "available" or not anchor_id or not knowledge_cutoff:
        return None
    try:
        if _parse_datetime(knowledge_cutoff) > _parse_datetime(decision_time):
            return None
        if effective_date and datetime.fromisoformat(effective_date).date() > _parse_datetime(decision_time).date():
            return None
    except ValueError:
        return None
    return {
        "kind": "vwce_benchmark_hierarchy_reference",
        "instrument_id": anchor_id,
        "anchor_digest": _text(_field(reference_anchor, "anchor_digest")),
        "resolution_digest": _text(_field(reference_anchor, "resolution_digest")),
        "effective_date": _text(_field(reference_anchor, "effective_date")),
        "knowledge_cutoff": _text(_field(reference_anchor, "knowledge_cutoff")),
        "output_currency": _text(_field(reference_anchor, "output_currency")),
        "horizon_years": _finite(_field(reference_anchor, "horizon_years")),
        "risk_envelope_status": _text(_field(reference_anchor, "risk_envelope_status")),
    }


def _candidate_input_record(candidate: SelectionCandidate) -> dict[str, object]:
    return {
        "opportunity": asdict(candidate.opportunity),
        "common_metrics_as_of": candidate.common_metrics_as_of,
        "country": candidate.country,
        "sector": candidate.sector,
        "common_metrics": _common_metrics(candidate),
        "hard_gate_reasons": candidate.hard_gate_reasons,
        "constraint_results": _json_value(candidate.constraint_results),
        "what_if_scenario": _json_value(candidate.what_if_scenario),
        "constraint_analysis": _json_value(candidate.constraint_analysis),
        "constraint_snapshot": _json_value(candidate.constraint_snapshot),
        "constraint_evidence": _json_value(candidate.constraint_evidence),
        "portfolio_forecast": _json_value(candidate.portfolio_forecast),
        "source_hashes": candidate.source_hashes,
    }


def _candidate_hashes(candidate: SelectionCandidate) -> dict[str, str]:
    rows = dict(candidate.source_hashes)
    rows.setdefault("opportunity_universe", candidate.opportunity.universe_hash)
    rows.setdefault("opportunity_policy", candidate.opportunity.config_hash)
    rows.setdefault("opportunity_vintage", candidate.opportunity.source_vintage_hash)
    rows.setdefault("candidate", _digest(_candidate_input_record(candidate)))
    return dict(sorted(rows.items()))


def _run_source_hashes(
    candidates: Sequence[SelectionCandidate], input_hash: str, policy: SelectionPolicy
) -> tuple[tuple[str, str], ...]:
    hashes: dict[str, str] = {
        "selection_inputs": input_hash,
        "selection_policy": policy.checksum,
    }
    for candidate in candidates:
        for name, value in _candidate_hashes(candidate).items():
            hashes[f"{candidate.instrument_id}:{name}"] = value
    return tuple(sorted(hashes.items()))


def _profile_record(profile: RiskProfileVersion | None) -> dict[str, object] | None:
    return None if profile is None else risk_profile_version_record(profile)


def _asset_family(value: object) -> str:
    token = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "equity": "stock",
        "ordinary_fund": "ordinary_fund",
        "fund": "ordinary_fund",
        "mutual_fund": "ordinary_fund",
        "fixed_income": "bond",
        "corporate_bond": "bond",
        "government_bond": "bond",
    }
    token = aliases.get(token, token)
    return token if token in _ASSET_FAMILIES else "unavailable"


def _category(value: object) -> str:
    text = _text(value)
    return text if text is not None else "unavailable"


def _digest(value: object) -> str:
    encoded = json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if is_dataclass(value):
        return _json_value(asdict(value))
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return _json_value(value.item())
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _get(value: object, key: str, nested_key: str | None = None) -> object:
    item = _field(value, key)
    return _field(item, nested_key) if nested_key is not None else item


def _field(value: object, key: str | None, default: object = None) -> object:
    if key is None:
        return default
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("decision_time must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("decision_time requires an explicit timezone")
    return parsed


def _validate_decision_time(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("decision_time must be an ISO timestamp")
    _parse_datetime(value)


__all__ = [
    "SELECTION_RUN_ENTITY_TYPE",
    "SelectionCandidate",
    "SelectionPolicy",
    "SelectionPolicyError",
    "SelectionRun",
    "build_selection_run",
    "load_selection_policy",
    "persist_selection_run",
]
