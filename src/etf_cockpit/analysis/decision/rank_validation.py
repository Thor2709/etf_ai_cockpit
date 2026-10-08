"""Point-in-time replay, rank validation, promotion and cutover rules.

The replay consumes dated universe membership and evidence supplied by the
caller.  Membership uses half-open ``[valid_from, valid_to)`` intervals and a
complete snapshot marker; there is deliberately no fallback to today's
universe.  Daily close prices are usable at a decision time only when their
explicit ``known_at`` is no later than that cutoff.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

import pandas as pd
import yaml

from etf_cockpit.core.paths import CONFIG_DIR

from etf_cockpit.features.forecast_lab import build_walk_forward_splits
from etf_cockpit.models.monitoring import (
    DatedReturn,
    DatedValue,
    assess_drift,
    compare_net_performance,
)
from etf_cockpit.portfolio.costs import COST_MODEL_ID
from etf_cockpit.portfolio.factor_risk import build_factor_risk_report


_DEFAULT_POLICY_PATH = CONFIG_DIR / "decision_cutover_v1.yaml"
_DEFAULT_DOMAIN_PATH = CONFIG_DIR / "decision_domains_v1.yaml"
_DEFAULT_OPPORTUNITY_PATH = CONFIG_DIR / "decision_opportunity_v1.yaml"
_FEATURE_COLUMNS = {
    "quality": "quality_score",
    "value": "value_score",
    "momentum": "momentum_score",
    "growth": "growth_score",
    "risk": "risk_score",
}
_REPLAY_RANKERS = {"QV", "QVM", "v3"}
_CUTOVER_CONSUMERS = {"screener", "score_history", "instrument_detail"}
_MEMBERSHIP_COLUMNS = {
    "instrument_id",
    "valid_from",
    "valid_to",
    "known_at",
    "snapshot_date",
    "snapshot_complete",
}
_EVIDENCE_COLUMNS = {
    "instrument_id",
    "effective_at",
    "known_at",
    "quality_score",
    "value_score",
    "momentum_score",
    "v3_score",
}


@dataclass(frozen=True)
class RankerSpec:
    """Frozen deterministic formula used to turn cutoff evidence into a rank."""

    version: str
    weights: Mapping[str, float] = field(default_factory=dict)
    score_column: str | None = None


@dataclass(frozen=True)
class RankValidationPolicy:
    """Typed rank replay and promotion settings loaded from the v1 YAML."""

    version: str
    checksum: str
    holding_period_sessions: int
    minimum_universe_support: int
    top_n: int
    bottom_n: int
    minimum_decision_dates: int
    subperiod_count: int
    minimum_group_support: int
    significance_t: float
    minimum_stable_subperiods: int
    drift_minimum_observations: int
    drift_alert_threshold: float
    rankers: Mapping[str, RankerSpec]


@dataclass(frozen=True)
class RankReplayReport:
    """Frozen ranks followed by forward outcomes and their source coverage."""

    rows: pd.DataFrame
    status: str
    insufficient_decision_times: tuple[str, ...]
    config_hashes: Mapping[str, str]
    config_versions: Mapping[str, str]
    pit_availability: Mapping[str, object]
    reason: str | None = None
    execution_allowed: bool = False


@dataclass(frozen=True)
class RankValidationReport:
    """Separate walk-forward development results from a frozen holdout."""

    validation_id: str
    status: str
    development: Mapping[str, Mapping[str, object]]
    holdout: Mapping[str, Mapping[str, object]]
    holdout_decision_times: tuple[str, ...]
    walk_forward_splits: pd.DataFrame
    pit_availability: Mapping[str, object]
    replay_config_hashes: Mapping[str, str]
    reason: str | None = None
    execution_allowed: bool = False


@dataclass(frozen=True)
class RankCutover:
    """Resolved consumer rank; the v3 rank remains available for replay."""

    enabled: bool
    active: bool
    ranker: str
    v3_comparator: str
    promotion_record: Mapping[str, object] | None
    reason: str
    execution_allowed: bool = False


def load_rank_validation_policy(
    path: str | Path = _DEFAULT_POLICY_PATH,
) -> RankValidationPolicy:
    """Load the documented conservative defaults; a missing policy fails closed.

    The default 21-session holding window, 20-member cross-section, Top/Bottom
    five portfolios, 12 decision observations, three chronological
    subperiods, all-subperiod stability, and ``t >= 3`` haircut are explicit
    v1 research choices.  QV and QVM formulas match the DA-004 frozen baselines;
    the balanced challenger is a fixed 40/40/20 Q/V/M weighting.  Monitoring
    defaults match Forecast Lab's four-observation, one-standardized-shift
    rule.  These settings are versioned and hashed with each replay.
    """

    return _rank_validation_policy_for_content(Path(path).read_bytes())


@lru_cache(maxsize=8)
def _rank_validation_policy_for_content(content: bytes) -> RankValidationPolicy:
    """Parse once per distinct file content (frozen result; exceptions are never cached)."""

    parsed = yaml.safe_load(content.decode("utf-8"))
    if not isinstance(parsed, Mapping) or parsed.get("schema_version") != 1:
        raise ValueError("rank validation policy requires schema_version 1")
    version = str(parsed.get("version", "")).strip()
    replay = parsed.get("replay")
    validation = parsed.get("validation")
    monitoring = parsed.get("monitoring")
    raw_rankers = parsed.get("rankers")
    if not version or not all(isinstance(item, Mapping) for item in (replay, validation, monitoring, raw_rankers)):
        raise ValueError("rank validation policy requires versioned replay, validation, monitoring and ranker mappings")

    rankers: dict[str, RankerSpec] = {}
    for name, raw in raw_rankers.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            raise ValueError("ranker specifications must be named mappings")
        ranker_version = str(raw.get("version", "")).strip()
        if not ranker_version:
            raise ValueError(f"ranker {name} requires a frozen version")
        score_column = raw.get("score_column")
        if score_column is not None:
            score_column = str(score_column).strip()
            if not score_column:
                raise ValueError(f"ranker {name} score_column cannot be empty")
            weights: dict[str, float] = {}
        else:
            raw_weights = raw.get("weights")
            if not isinstance(raw_weights, Mapping) or not raw_weights:
                raise ValueError(f"ranker {name} requires frozen weights")
            weights = {}
            for feature, value in raw_weights.items():
                if feature not in _FEATURE_COLUMNS or not _finite(value) or float(value) < 0:
                    raise ValueError(f"ranker {name} has an invalid feature weight")
                weights[str(feature)] = float(value)
            if not math.isclose(math.fsum(weights.values()), 1.0, abs_tol=1e-9):
                raise ValueError(f"ranker {name} weights must sum to one")
        rankers[name] = RankerSpec(ranker_version, weights, score_column)
    if not _REPLAY_RANKERS.issubset(rankers) or not any(name not in _REPLAY_RANKERS for name in rankers):
        raise ValueError("policy requires QV, QVM, v3 and at least one challenger ranker")
    if rankers["QV"].weights != {"quality": 0.5, "value": 0.5}:
        raise ValueError("QV must retain its frozen equal-weight quality/value definition")
    if rankers["QVM"].weights != {"quality": 1 / 3, "value": 1 / 3, "momentum": 1 / 3}:
        raise ValueError("QVM must retain its frozen equal-weight quality/value/momentum definition")
    if rankers["v3"].score_column != "v3_score":
        raise ValueError("v3 must remain the named score-engine-v3 replay comparator")

    subperiod_count = _positive_int(validation.get("subperiod_count"))
    minimum_stable_subperiods = _positive_int(validation.get("minimum_stable_subperiods"))
    if minimum_stable_subperiods > subperiod_count:
        raise ValueError("minimum stable subperiods cannot exceed the configured subperiod count")
    checksum = hashlib.sha256(_normalise_lf(content)).hexdigest()
    return RankValidationPolicy(
        version=version,
        checksum=checksum,
        holding_period_sessions=_positive_int(replay.get("holding_period_sessions")),
        minimum_universe_support=_positive_int(replay.get("minimum_universe_support")),
        top_n=_positive_int(validation.get("top_n")),
        bottom_n=_positive_int(validation.get("bottom_n")),
        minimum_decision_dates=_positive_int(validation.get("minimum_decision_dates")),
        subperiod_count=subperiod_count,
        minimum_group_support=_positive_int(validation.get("minimum_group_support")),
        significance_t=_positive_number(validation.get("significance_t")),
        minimum_stable_subperiods=minimum_stable_subperiods,
        drift_minimum_observations=_positive_int(monitoring.get("minimum_observations")),
        drift_alert_threshold=_positive_number(monitoring.get("alert_threshold")),
        rankers=rankers,
    )


def replay_rank_panel(
    evidence: pd.DataFrame,
    memberships: pd.DataFrame,
    prices: pd.DataFrame,
    costs: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
    cash_returns: pd.DataFrame,
    decision_times: Sequence[datetime | date | str],
    *,
    policy: RankValidationPolicy | None = None,
    policy_path: str | Path = _DEFAULT_POLICY_PATH,
    domain_config_path: str | Path = _DEFAULT_DOMAIN_PATH,
    opportunity_config_path: str | Path = _DEFAULT_OPPORTUNITY_PATH,
) -> RankReplayReport:
    """Freeze ranks from PIT memberships/evidence, then attach net forward outcomes.

    Membership must include ``snapshot_complete`` and ``snapshot_date`` beside
    ``instrument_id``, ``valid_from``, ``valid_to`` and ``known_at``.  A date
    without a complete as-known snapshot, or without evidence for every active
    member, is returned as insufficient; current membership is never queried.
    Costs must come from ISSUE-0128's ``execution-cost-v1`` estimate and be
    supplied as explicit round-trip basis points known by each cutoff.
    """

    active_policy = policy or load_rank_validation_policy(policy_path)
    config_hashes = _frozen_config_hashes(active_policy, domain_config_path, opportunity_config_path)
    config_versions = {
        name: spec.version for name, spec in active_policy.rankers.items()
    } | {"rank_validation": active_policy.version}
    parsed_times = _decision_times(decision_times)
    if not parsed_times:
        return _empty_replay(config_hashes, config_versions, "no decision times were supplied")
    if not _has_columns(evidence, _EVIDENCE_COLUMNS):
        return _empty_replay(config_hashes, config_versions, "dated rank evidence is incomplete")
    if not _has_columns(memberships, _MEMBERSHIP_COLUMNS):
        return _empty_replay(config_hashes, config_versions, "dated complete universe membership is unavailable")
    if not _has_columns(prices, {"instrument_id", "date", "known_at", "adjusted_close"}):
        return _empty_replay(config_hashes, config_versions, "dated adjusted prices with knowledge times are unavailable")
    if not _has_columns(costs, {"instrument_id", "known_at", "round_trip_cost_bps", "cost_model_id"}):
        return _empty_replay(config_hashes, config_versions, "dated ISSUE-0128 round-trip costs are unavailable")

    evidence_frame = evidence.copy()
    membership_frame = memberships.copy()
    price_frame = prices.copy()
    cost_frame = costs.copy()
    for frame, column in ((evidence_frame, "known_at"), (evidence_frame, "effective_at"),
                          (membership_frame, "known_at"), (price_frame, "known_at"),
                          (cost_frame, "known_at")):
        frame[f"_{column}"] = frame[column].map(_aware_timestamp)
    evidence_frame["_effective_date"] = evidence_frame["effective_at"].map(_date_value)
    membership_frame["_valid_from"] = membership_frame["valid_from"].map(_date_value)
    membership_frame["_valid_to"] = membership_frame["valid_to"].map(_optional_date_value)
    membership_frame["_snapshot_date"] = membership_frame["snapshot_date"].map(_date_value)
    price_frame["_date"] = price_frame["date"].map(_date_value)
    for frame in (evidence_frame, membership_frame, price_frame, cost_frame):
        if frame["instrument_id"].isna().any() if "instrument_id" in frame else False:
            return _empty_replay(config_hashes, config_versions, "instrument identifiers are incomplete")

    # Ranks are materialized first. Forward prices and cost outcomes are joined
    # only after every per-date cross-section has been frozen.
    frozen_rows: list[dict[str, object]] = []
    insufficient: dict[str, str] = {}
    for cutoff in parsed_times:
        cutoff_text = cutoff.isoformat().replace("+00:00", "Z")
        decision_day = cutoff.date()
        snapshot = membership_frame.loc[membership_frame["_snapshot_date"].eq(decision_day)].copy()
        if snapshot.empty or not snapshot["snapshot_complete"].map(_true_flag).all():
            insufficient[cutoff_text] = "dated_membership_snapshot_missing_or_incomplete"
            continue
        if snapshot["_known_at"].isna().any() or snapshot["_known_at"].gt(cutoff).any():
            insufficient[cutoff_text] = "membership_not_known_at_decision_time"
            continue
        if snapshot["_valid_from"].isna().any():
            insufficient[cutoff_text] = "membership_effective_dates_incomplete"
            continue
        if snapshot["instrument_id"].astype(str).duplicated().any():
            insufficient[cutoff_text] = "membership_snapshot_has_duplicate_instruments"
            continue
        active = snapshot.loc[
            snapshot["_valid_from"].map(lambda value: value <= decision_day)
            & snapshot["_valid_to"].map(lambda value: value is None or value > decision_day)
        ].copy()
        active["instrument_id"] = active["instrument_id"].astype(str)
        if len(active) < active_policy.minimum_universe_support:
            insufficient[cutoff_text] = "point_in_time_universe_below_minimum_support"
            continue

        available_evidence = evidence_frame.loc[
            evidence_frame["_known_at"].notna()
            & evidence_frame["_effective_date"].notna()
            & evidence_frame["_known_at"].le(cutoff)
            & evidence_frame["_effective_date"].map(lambda value: value <= decision_day)
            & evidence_frame["instrument_id"].astype(str).isin(active["instrument_id"])
        ].copy()
        if available_evidence.empty:
            insufficient[cutoff_text] = "point_in_time_evidence_unavailable"
            continue
        available_evidence["instrument_id"] = available_evidence["instrument_id"].astype(str)
        available_evidence = available_evidence.sort_values(
            ["instrument_id", "_effective_date", "_known_at"], kind="stable"
        )
        latest_keys = available_evidence.groupby("instrument_id", sort=False).tail(1)[
            ["instrument_id", "_effective_date", "_known_at"]
        ]
        latest_key_columns = ["instrument_id", "_effective_date", "_known_at"]
        latest_candidates = available_evidence.merge(
            latest_keys,
            on=latest_key_columns,
            how="inner",
            validate="many_to_one",
        )
        conflict_columns = [column for column in latest_candidates.columns if column not in latest_key_columns]
        conflicting_latest = any(
            len(group[conflict_columns].drop_duplicates()) > 1
            for _, group in latest_candidates.groupby(latest_key_columns, sort=False, dropna=False)
        )
        if conflicting_latest:
            insufficient[cutoff_text] = "point_in_time_evidence_has_ambiguous_latest_rows"
            continue
        latest = latest_candidates.drop_duplicates(subset=latest_key_columns, keep="last")
        if latest["instrument_id"].duplicated().any() or set(latest["instrument_id"]) != set(active["instrument_id"]):
            insufficient[cutoff_text] = "point_in_time_evidence_incomplete_for_membership"
            continue
        required_features = set().union(
            *[set(spec.weights) for spec in active_policy.rankers.values()]
        )
        if any(not _finite(value) for feature in required_features for value in latest[_FEATURE_COLUMNS[feature]]):
            insufficient[cutoff_text] = "point_in_time_rank_inputs_incomplete"
            continue
        latest = latest.merge(
            active.drop(columns=["_known_at", "_valid_from", "_valid_to", "_snapshot_date"], errors="ignore"),
            on="instrument_id",
            how="left",
            validate="one_to_one",
            suffixes=("", "_membership"),
        )
        score_rows: list[dict[str, object]] = []
        for item in latest.to_dict("records"):
            for ranker, spec in active_policy.rankers.items():
                score = (
                    _float_or_none(item.get(spec.score_column))
                    if spec.score_column
                    else math.fsum(float(item[_FEATURE_COLUMNS[feature]]) * weight for feature, weight in spec.weights.items())
                )
                if score is None or not math.isfinite(float(score)):
                    insufficient[cutoff_text] = f"rank_input_unavailable:{ranker}"
                    score_rows = []
                    break
                score_rows.append(
                    {
                        "decision_time": cutoff_text,
                        "decision_date": decision_day.isoformat(),
                        "instrument_id": str(item["instrument_id"]),
                        "ranker": ranker,
                        "score": float(score),
                        "rank": 0,
                        "config_version": spec.version,
                        "config_hash": active_policy.checksum,
                        "quality_score": _float_or_none(item.get("quality_score")),
                        "value_score": _float_or_none(item.get("value_score")),
                        "momentum_score": _float_or_none(item.get("momentum_score")),
                        "size_value": _float_or_none(item.get("size_value")),
                        "sector": item.get("sector"),
                        "size_bucket": item.get("size_bucket"),
                        "execution_allowed": False,
                    }
                )
            if cutoff_text in insufficient:
                break
        if cutoff_text in insufficient:
            continue
        date_rows = pd.DataFrame(score_rows)
        date_rows["rank"] = date_rows.groupby("ranker", sort=False)["score"].rank(
            ascending=False, method="min"
        ).astype(int)
        frozen_rows.extend(date_rows.to_dict("records"))

    frozen = pd.DataFrame(frozen_rows)
    if frozen.empty:
        return RankReplayReport(
            rows=frozen,
            status="insufficient_evidence",
            insufficient_decision_times=tuple(insufficient),
            config_hashes=config_hashes,
            config_versions=config_versions,
            pit_availability={
                "complete": False,
                "covered_decisions": 0,
                "requested_decisions": len(parsed_times),
                "coverage_fraction": 0.0,
                "reasons": dict(insufficient),
            },
            reason="no decision date has a complete point-in-time universe and evidence panel",
        )

    all_sessions = sorted(price_frame["_date"].dropna().unique())
    outcomes: list[dict[str, object]] = []
    for item in frozen.to_dict("records"):
        cutoff = pd.Timestamp(item["decision_time"])
        instrument = str(item["instrument_id"])
        future_sessions = [session for session in all_sessions if session > cutoff.date()]
        window_end = (
            future_sessions[active_policy.holding_period_sessions - 1].isoformat()
            if len(future_sessions) >= active_policy.holding_period_sessions
            else None
        )
        gross, outcome_status = _forward_return(
            price_frame, instrument, cutoff, active_policy.holding_period_sessions
        )
        cost = _point_in_time_cost(cost_frame, instrument, cutoff)
        if outcome_status == "available" and cost is None:
            outcome_status = "round_trip_cost_unavailable"
        net = max(-1.0, gross - float(cost) / 10_000.0) if gross is not None and cost is not None else None
        benchmark = _outcome_for_date(benchmark_returns, item["decision_date"])
        cash = _outcome_for_date(cash_returns, item["decision_date"])
        row = dict(item)
        row.update(
            gross_return=gross,
            round_trip_cost_bps=cost,
            net_return=net,
            benchmark_net_return=benchmark,
            cash_net_return=cash,
            forward_status=outcome_status,
            forward_window_end=window_end,
        )
        outcomes.append(row)
    outcome_frame = pd.DataFrame(outcomes)
    date_complete: dict[str, bool] = {}
    for cutoff in parsed_times:
        cutoff_text = cutoff.isoformat().replace("+00:00", "Z")
        if cutoff_text in insufficient:
            date_complete[cutoff_text] = False
            continue
        date_rows = outcome_frame.loc[outcome_frame["decision_time"].eq(cutoff_text)]
        complete = (
            not date_rows.empty
            and date_rows["net_return"].map(_finite).all()
            and date_rows["benchmark_net_return"].map(_finite).all()
            and date_rows["cash_net_return"].map(_finite).all()
            and date_rows["forward_status"].astype(str).str.startswith("available").all()
        )
        if not complete:
            insufficient[cutoff_text] = "forward_outcome_cost_or_comparator_incomplete"
        date_complete[cutoff_text] = bool(complete)

    covered = sum(date_complete.values())
    total = len(parsed_times)
    complete_all = covered == total
    return RankReplayReport(
        rows=outcome_frame,
        status="complete" if complete_all else "insufficient_evidence",
        insufficient_decision_times=tuple(insufficient),
        config_hashes=config_hashes,
        config_versions=config_versions,
        pit_availability={
            "complete": complete_all,
            "covered_decisions": covered,
            "requested_decisions": total,
            "coverage_fraction": covered / total if total else 0.0,
            "reasons": dict(insufficient),
        },
        reason=None if complete_all else "one or more decision dates lack complete PIT membership, evidence, prices, costs or comparators",
    )


def evaluate_rank_validation(
    replay: RankReplayReport,
    *,
    holdout_decision_times: Sequence[datetime | date | str],
    prices: pd.DataFrame | None = None,
    policy: RankValidationPolicy | None = None,
    policy_path: str | Path = _DEFAULT_POLICY_PATH,
) -> RankValidationReport:
    """Evaluate walk-forward development data and a fixed, untouched holdout.

    ``holdout_decision_times`` must be fixed before inspecting returns.  The
    development selector receives only expanding-window test folds from the
    shared Forecast Lab split builder; holdout outcomes are summarized
    separately and never enter candidate selection.
    """

    active_policy = policy or load_rank_validation_policy(policy_path)
    holdout_times = _decision_times(holdout_decision_times)
    holdout_keys = tuple(item.isoformat().replace("+00:00", "Z") for item in holdout_times)
    rows = replay.rows.copy() if isinstance(replay.rows, pd.DataFrame) else pd.DataFrame()
    empty = pd.DataFrame()
    if rows.empty or not {"decision_time", "ranker", "score", "net_return"}.issubset(rows.columns):
        return _empty_validation(replay, holdout_keys, "rank replay panel is unavailable")
    all_times = tuple(sorted(rows["decision_time"].dropna().astype(str).unique()))
    holdout_set = set(holdout_keys)
    available_holdout = holdout_set & set(all_times)
    if (
        not holdout_set
        or available_holdout != holdout_set
        or any(item >= min(holdout_set) and item not in holdout_set for item in all_times)
    ):
        return _empty_validation(replay, holdout_keys, "holdout must be a chronological terminal window")
    holdout_start_date = min(_date_value(item) for item in holdout_set)
    if "forward_window_end" not in rows.columns:
        return _empty_validation(replay, holdout_keys, "replay outcome windows are unavailable for holdout isolation")
    window_end_by_time: dict[str, str | None] = {}
    for decision_time, group in rows.groupby("decision_time", sort=False):
        values = group["forward_window_end"]
        unique_values = values.dropna().astype(str).unique()
        window_end_by_time[str(decision_time)] = (
            str(unique_values[0])
            if values.notna().all() and len(unique_values) == 1
            else None
        )
    development_times = tuple(
        item
        for item in all_times
        if item not in holdout_set
        and window_end_by_time.get(item) is not None
        and _date_value(window_end_by_time[item]) < holdout_start_date
    )
    splits = build_walk_forward_splits(
        [pd.Timestamp(item).date() for item in development_times],
        minimum_train_dates=3,
        test_dates=1,
    )
    fold_dates = set()
    if not splits.empty:
        for split in splits.itertuples():
            fold_dates.update(
                item
                for item in development_times
                if split.test_start <= pd.Timestamp(item).date().isoformat() <= split.test_end
            )
    dev_rows = rows.loc[rows["decision_time"].astype(str).isin(fold_dates)].copy()
    holdout_rows = rows.loc[rows["decision_time"].astype(str).isin(available_holdout)].copy()
    rankers = sorted(set(rows["ranker"].astype(str)))
    development = {
        name: _rank_metrics(dev_rows, name, active_policy)
        for name in rankers
    }
    holdout = {
        name: _rank_metrics(holdout_rows, name, active_policy)
        for name in rankers
    }
    if prices is not None:
        holdout = {
            name: dict(metrics)
            | {"factor_attribution": _factor_attribution(holdout_rows, name, prices, active_policy)}
            for name, metrics in holdout.items()
        }
        development = {
            name: dict(metrics)
            | {"factor_attribution": _factor_attribution(dev_rows, name, prices, active_policy)}
            for name, metrics in development.items()
        }
    else:
        holdout = {
            name: dict(metrics)
            | {"factor_attribution": {"status": "unavailable", "reason": "point-in-time price history was not supplied", "factors": []}}
            for name, metrics in holdout.items()
        }
        development = {
            name: dict(metrics)
            | {"factor_attribution": {"status": "unavailable", "reason": "point-in-time price history was not supplied", "factors": []}}
            for name, metrics in development.items()
        }
    dates_sufficient = (
        len(fold_dates) >= active_policy.minimum_decision_dates
        and len(available_holdout) >= active_policy.minimum_decision_dates
    )
    neutralisation_sufficient = all(
        item.get("sector_neutral", {}).get("status") == "available"
        and item.get("size_neutral", {}).get("status") == "available"
        for item in (*development.values(), *holdout.values())
    )
    attribution_sufficient = all(
        item.get("factor_attribution", {}).get("status") == "available"
        for item in (*development.values(), *holdout.values())
    )
    fully_covered = replay.status == "complete" and bool(replay.pit_availability.get("complete"))
    status = "available" if dates_sufficient and neutralisation_sufficient and attribution_sufficient and fully_covered else "insufficient_evidence"
    validation_material = {
        "config_hashes": dict(replay.config_hashes),
        "holdout_times": list(holdout_keys),
        "development_times": sorted(fold_dates),
        "rankers": rankers,
        "replay_rows": int(len(rows)),
    }
    validation_id = "rankval_" + hashlib.sha256(_canonical_json(validation_material)).hexdigest()[:20]
    reason = None if status == "available" else "walk-forward, PIT, holdout, neutralisation or Q/V/M factor evidence is incomplete"
    return RankValidationReport(
        validation_id=validation_id,
        status=status,
        development=development,
        holdout=holdout,
        holdout_decision_times=holdout_keys,
        walk_forward_splits=splits.copy() if isinstance(splits, pd.DataFrame) else empty,
        pit_availability=dict(replay.pit_availability),
        replay_config_hashes=dict(replay.config_hashes),
        reason=reason,
    )


def rank_validation_metrics(
    rows: pd.DataFrame,
    ranker: str,
    *,
    policy: RankValidationPolicy | None = None,
    policy_path: str | Path = _DEFAULT_POLICY_PATH,
) -> dict[str, object]:
    """Return rank-IC, spread, monotonicity, portfolio, neutral and turnover metrics."""

    return _rank_metrics(rows.copy(), ranker, policy or load_rank_validation_policy(policy_path))


def select_challenger(report: RankValidationReport) -> str | None:
    """Choose from development walk-forward results only; the holdout is unread."""

    baseline_qv = report.development.get("QV", {})
    baseline_qvm = report.development.get("QVM", {})
    if not _metric_available(baseline_qv) or not _metric_available(baseline_qvm):
        return None
    candidates = []
    for ranker, metrics in report.development.items():
        if ranker in _REPLAY_RANKERS or not _metric_available(metrics):
            continue
        if (
            float(metrics["net_return_mean"]) > float(baseline_qv["net_return_mean"])
            and float(metrics["net_return_mean"]) > float(baseline_qvm["net_return_mean"])
        ):
            candidates.append((float(metrics["net_return_mean"]), ranker))
    return max(candidates, default=(0.0, None), key=lambda item: (item[0], item[1] or ""))[1]


def promotion_decision(
    report: RankValidationReport,
    challenger: str | None,
    *,
    rationale: str,
    policy: RankValidationPolicy | None = None,
    policy_path: str | Path = _DEFAULT_POLICY_PATH,
) -> dict[str, object]:
    """Apply the frozen holdout gate and return the auditable promotion record."""

    active_policy = policy or load_rank_validation_policy(policy_path)
    why = str(rationale or "").strip()
    if not why:
        raise ValueError("promotion decisions require a rationale")
    qv = report.holdout.get("QV", {})
    qvm = report.holdout.get("QVM", {})
    v3 = report.holdout.get("v3", {})
    candidate = report.holdout.get(str(challenger), {}) if challenger else {}
    development_selection = select_challenger(report)
    challenger_was_selected = bool(challenger and challenger == development_selection)
    selected = "v3"
    status = "insufficient_evidence"
    reason = "holdout validation is incomplete"
    candidate_stats = candidate if _metric_available(candidate) else {}
    if report.status == "available" and _metric_available(qv) and _metric_available(v3):
        if float(qv["net_return_mean"]) <= float(v3["net_return_mean"]):
            status = "stay_on_v3"
            reason = "QV did not outperform v3 on the frozen holdout net of costs"
        else:
            selected = "QV"
            status = "baseline_champion"
            reason = "no challenger passed every frozen holdout promotion gate"
            if challenger and challenger_was_selected and _metric_available(candidate_stats) and _metric_available(qvm):
                beats_baselines = (
                    float(candidate_stats["net_return_mean"]) > float(qv["net_return_mean"])
                    and float(candidate_stats["net_return_mean"]) > float(qvm["net_return_mean"])
                )
                t_passes = max(
                    _finite_or(candidate_stats.get("rank_ic_t"), -math.inf),
                    _finite_or(candidate_stats.get("top_minus_bottom_t"), -math.inf),
                ) >= active_policy.significance_t
                stable_periods = _stable_periods(
                    candidate_stats,
                    qv,
                    qvm,
                    active_policy,
                )
                if beats_baselines and t_passes and stable_periods >= active_policy.minimum_stable_subperiods:
                    selected = str(challenger)
                    status = "promoted"
                    reason = "challenger beat QV and QVM net of costs and passed the t and stability gates"
                elif not beats_baselines:
                    reason = "challenger did not beat both QV and QVM net of costs on the frozen holdout"
                elif not t_passes:
                    reason = "challenger failed the configured multiple-testing t haircut"
                else:
                    reason = "challenger subperiods were not stable"
            elif challenger and not challenger_was_selected:
                reason = "challenger was not selected using development-only evidence"
    selected_metrics = report.holdout.get(selected, {})
    qv_ic = _finite_or(qv.get("rank_ic_mean"), math.nan)
    selected_ic = _finite_or(selected_metrics.get("rank_ic_mean"), math.nan)
    incremental_ic = selected_ic - qv_ic if math.isfinite(selected_ic) and math.isfinite(qv_ic) else None
    pit = dict(report.pit_availability)
    pit_complete = pit.get("complete") is True and _finite(pit.get("coverage_fraction")) and float(pit["coverage_fraction"]) == 1.0
    rank_authority = bool(
        status in {"promoted", "baseline_champion"}
        and report.validation_id
        and why
        and pit_complete
        and incremental_ic is not None
    )
    record: dict[str, object] = {
        "schema_version": 1,
        "validation_id": report.validation_id,
        "selected_rank": selected,
        "challenger": challenger,
        "status": status,
        "reason": reason,
        "rationale": why,
        "pit_availability": pit,
        "incremental_ic": incremental_ic,
        "holdout_decision_times": list(report.holdout_decision_times),
        "rank_authority": rank_authority,
        "execution_allowed": False,
    }
    record["record_id"] = "rankpromo_" + hashlib.sha256(_canonical_json(record)).hexdigest()[:20]
    return record


def metric_rank_authority_record(
    metric_id: str,
    promotion_record: Mapping[str, object] | None,
) -> dict[str, object]:
    """Grant metric rank authority only when a complete promotion record proves it."""

    metric = str(metric_id or "").strip()
    if not metric or not _valid_promotion_record(promotion_record):
        return {"metric_id": metric, "rank_authority": False, "execution_allowed": False}
    assert promotion_record is not None
    return {
        "metric_id": metric,
        "rank_authority": True,
        "rationale": str(promotion_record["rationale"]),
        "pit_availability": dict(promotion_record["pit_availability"]),
        "incremental_ic": float(promotion_record["incremental_ic"]),
        "validation_id": str(promotion_record["validation_id"]),
        "promotion_record_id": str(promotion_record["record_id"]),
        "execution_allowed": False,
    }


@lru_cache(maxsize=8)
def _parsed_rank_cutover(text: str) -> tuple[bool, object]:
    parsed = yaml.safe_load(text)
    control = parsed.get("rank_cutover") if isinstance(parsed, Mapping) else None
    if not isinstance(control, Mapping):
        raise ValueError("decision domain config lacks rank_cutover control")
    configured_enabled = control.get("enabled")
    if not isinstance(configured_enabled, bool):
        raise ValueError("rank cutover enabled flag must be boolean")
    return configured_enabled, control.get("promotion_record")


def _configured_rank_cutover(text: str) -> tuple[bool, object]:
    """Parse the cutover control once per distinct config text; the record is returned as a private copy."""

    enabled, record = _parsed_rank_cutover(text)
    return enabled, deepcopy(record)


def resolve_rank_cutover(
    *,
    cutover_enabled: bool | None = None,
    promotion_record: Mapping[str, object] | None = None,
    domain_config_path: str | Path = _DEFAULT_DOMAIN_PATH,
    policy_path: str | Path = _DEFAULT_POLICY_PATH,
) -> RankCutover:
    """Resolve the configured cutover; missing config or record always means v3."""

    try:
        load_rank_validation_policy(policy_path)
        configured_enabled, configured_record = _configured_rank_cutover(
            Path(domain_config_path).read_text(encoding="utf-8")
        )
        selected_record = promotion_record if promotion_record is not None else configured_record
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        return RankCutover(False, False, "v3", "v3", None, "cutover_config_unavailable")
    enabled = configured_enabled if cutover_enabled is None else cutover_enabled
    if not isinstance(enabled, bool):
        return RankCutover(False, False, "v3", "v3", None, "cutover_flag_invalid")
    if not enabled:
        return RankCutover(False, False, "v3", "v3", None, "cutover_configured_off")
    if _valid_stay_on_v3_record(selected_record):
        assert isinstance(selected_record, Mapping)
        return RankCutover(
            True,
            False,
            "v3",
            "v3",
            dict(selected_record),
            "recorded_stay_on_v3:" + str(selected_record["reason"]),
        )
    if not _valid_promotion_record(selected_record):
        return RankCutover(True, False, "v3", "v3", None, "promotion_record_missing_or_invalid")
    assert isinstance(selected_record, Mapping)
    ranker = str(selected_record["selected_rank"])
    if ranker == "v3" or selected_record.get("rank_authority") is not True:
        return RankCutover(True, False, "v3", "v3", dict(selected_record), "promotion_record_keeps_v3_default")
    return RankCutover(True, True, ranker, "v3", dict(selected_record), "promoted_rank_active")


def route_consumer_rank(
    consumer: str,
    rank_scores: Mapping[str, object],
    *,
    promotion_record: Mapping[str, object] | None = None,
    cutover_enabled: bool | None = None,
    domain_config_path: str | Path = _DEFAULT_DOMAIN_PATH,
    policy_path: str | Path = _DEFAULT_POLICY_PATH,
) -> dict[str, object]:
    """Select one rank for a facade consumer while preserving its v3 comparator."""

    if consumer not in _CUTOVER_CONSUMERS:
        raise ValueError("rank cutover consumer is unsupported")
    cutover = resolve_rank_cutover(
        cutover_enabled=cutover_enabled,
        promotion_record=promotion_record,
        domain_config_path=domain_config_path,
        policy_path=policy_path,
    )
    scores = rank_scores if isinstance(rank_scores, Mapping) else {}
    v3 = _float_or_none(scores.get("v3"))
    ranker = cutover.ranker if cutover.active else "v3"
    value = _float_or_none(scores.get(ranker))
    reason = cutover.reason
    active = cutover.active
    if cutover.active and value is None:
        reason = "promoted_rank_score_unavailable_v3_comparator_retained"
    return {
        "consumer": consumer,
        "ranker": ranker,
        "rank_score": value,
        "v3_replay_score": v3,
        "v3_replay_available": v3 is not None,
        "cutover_enabled": cutover.enabled,
        "cutover_active": active,
        "promotion_record_id": (
            str(cutover.promotion_record.get("record_id"))
            if cutover.promotion_record is not None
            else None
        ),
        "reason": reason,
        "execution_allowed": False,
    }


def route_ranked_frame(
    frame: pd.DataFrame,
    consumer: str,
    *,
    promotion_record: Mapping[str, object] | None = None,
    cutover_enabled: bool | None = None,
) -> pd.DataFrame:
    """Attach the active rank to rows carrying ``rank_score__<ranker>`` fields."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    result = frame.copy()
    rank_columns = [column for column in result if str(column).startswith("rank_score__")]
    if not rank_columns:
        return result
    selected: list[dict[str, object]] = []
    for _, row in result.iterrows():
        scores = {
            str(column).removeprefix("rank_score__"): row[column]
            for column in rank_columns
        }
        selected.append(
            route_consumer_rank(
                consumer,
                scores,
                promotion_record=promotion_record,
                cutover_enabled=cutover_enabled,
            )
        )
    routes = pd.DataFrame(selected, index=result.index)
    result["decision_ranker"] = routes["ranker"]
    result["decision_rank_score"] = routes["rank_score"]
    result["v3_replay_score"] = routes["v3_replay_score"]
    if "score" in result.columns:
        result["score"] = result["decision_rank_score"].where(
            result["decision_rank_score"].notna(), result["score"]
        )
    return result


def monitor_champion_rank(
    promotion_record: Mapping[str, object],
    rank_observations: Sequence[DatedValue],
    rank_returns: Sequence[DatedReturn],
    baseline_returns: Sequence[DatedReturn],
    *,
    baseline_id: str,
    as_of: datetime | date,
    policy: RankValidationPolicy | None = None,
    policy_path: str | Path = _DEFAULT_POLICY_PATH,
) -> dict[str, object]:
    """Register a promoted rank for ISSUE-0124 drift/performance review.

    Existing monitoring primitives supply alerts and paired net performance.
    Retirement remains a named human-review state; a drift alert never retires
    or changes the champion automatically.
    """

    active_policy = policy or load_rank_validation_policy(policy_path)
    if not _valid_promotion_record(promotion_record):
        raise ValueError("rank monitoring requires a valid promotion record")
    ranker = str(promotion_record["selected_rank"])
    drift = assess_drift(
        ranker,
        list(rank_observations),
        as_of=as_of,
        settings={
            "minimum_observations": active_policy.drift_minimum_observations,
            "alert_threshold": active_policy.drift_alert_threshold,
        },
    )
    comparison = compare_net_performance(
        ranker,
        list(rank_returns),
        baseline_id,
        list(baseline_returns),
        baseline_is_deterministic=True,
        as_of=as_of,
    )
    review_required = drift.status == "warning" or (
        comparison.status == "available"
        and comparison.excess_net_mean is not None
        and comparison.excess_net_mean < 0
    )
    return {
        "model_id": ranker,
        "promotion_record_id": str(promotion_record["record_id"]),
        "validation_id": str(promotion_record["validation_id"]),
        "drift": drift,
        "performance": comparison,
        "retirement_state": "review_required" if review_required else "active",
        "retirement_requires_reviewer": review_required,
        "execution_allowed": False,
    }


def _rank_metrics(rows: pd.DataFrame, ranker: str, policy: RankValidationPolicy) -> dict[str, object]:
    if rows.empty or not {"decision_time", "ranker", "score", "net_return"}.issubset(rows.columns):
        return {"status": "unavailable", "reason": "rank/return panel is incomplete"}
    sample = rows.loc[rows["ranker"].astype(str).eq(ranker)].copy()
    if sample.empty:
        return {"status": "unavailable", "reason": "ranker has no replay observations"}
    daily: list[dict[str, object]] = []
    score_values: list[float] = []
    return_values: list[float] = []
    decile_paths: list[list[float]] = []
    quintile_paths: list[list[float]] = []
    for decision_time, group in sample.groupby("decision_time", sort=True):
        valid = group.loc[group["score"].map(_finite) & group["net_return"].map(_finite)].copy()
        if len(valid) < policy.minimum_universe_support:
            continue
        valid["score"] = pd.to_numeric(valid["score"], errors="coerce")
        valid["net_return"] = pd.to_numeric(valid["net_return"], errors="coerce")
        ordered = valid.sort_values(["score", "instrument_id"], ascending=[False, True], kind="stable")
        top = ordered.head(min(policy.top_n, len(ordered)))
        bottom = ordered.tail(min(policy.bottom_n, len(ordered)))
        top_mean = float(top["net_return"].mean())
        bottom_mean = float(bottom["net_return"].mean())
        ic = valid["score"].corr(valid["net_return"], method="spearman")
        if not _finite(ic):
            continue
        entry: dict[str, object] = {
            "decision_time": str(decision_time),
            "rank_ic": float(ic),
            "top_net_return": top_mean,
            "bottom_net_return": bottom_mean,
            "top_minus_bottom": top_mean - bottom_mean,
            "benchmark_net_return": _mean_column(top, "benchmark_net_return"),
            "cash_net_return": _mean_column(top, "cash_net_return"),
        }
        daily.append(entry)
        score_values.extend(float(value) for value in valid["score"])
        return_values.extend(float(value) for value in valid["net_return"])
        decile = _bucket_means(valid, 10)
        quintile = _bucket_means(valid, 5)
        if decile:
            decile_paths.append(decile)
        if quintile:
            quintile_paths.append(quintile)
    if not daily:
        return {"status": "unavailable", "reason": "no decision date has a complete cross-section"}
    daily_frame = pd.DataFrame(daily)
    ic_values = daily_frame["rank_ic"].astype(float).tolist()
    spread_values = daily_frame["top_minus_bottom"].astype(float).tolist()
    top_values = daily_frame["top_net_return"].astype(float).tolist()
    bench_values = daily_frame["benchmark_net_return"].dropna().astype(float).tolist()
    cash_values = daily_frame["cash_net_return"].dropna().astype(float).tolist()
    sector_neutral = _neutral_metrics(sample, "sector", policy)
    size_neutral = _neutral_metrics(sample, "size_bucket", policy)
    turnovers = _turnover(sample, policy.top_n)
    decile_monotone = [all(left <= right + 1e-12 for left, right in zip(path, path[1:])) for path in decile_paths]
    quintile_monotone = [all(left <= right + 1e-12 for left, right in zip(path, path[1:])) for path in quintile_paths]
    return {
        "status": "available" if len(daily) >= 2 else "insufficient_evidence",
        "decision_count": len(daily),
        "instrument_observation_count": len(score_values),
        "rank_ic_mean": fmean(ic_values),
        "rank_ic_t": _t_stat(ic_values),
        "rank_ic_positive_fraction": sum(value > 0 for value in ic_values) / len(ic_values),
        "top_net_return_mean": fmean(top_values),
        "bottom_net_return_mean": fmean(float(item["bottom_net_return"]) for item in daily),
        "net_return_mean": fmean(top_values),
        "benchmark_net_mean": fmean(bench_values) if bench_values else None,
        "cash_net_mean": fmean(cash_values) if cash_values else None,
        "excess_vs_benchmark": fmean(top_values) - fmean(bench_values) if bench_values else None,
        "excess_vs_cash": fmean(top_values) - fmean(cash_values) if cash_values else None,
        "top_minus_bottom_mean": fmean(spread_values),
        "top_minus_bottom_t": _t_stat(spread_values),
        "decile_monotonicity_fraction": fmean(decile_monotone) if decile_monotone else None,
        "quintile_monotonicity_fraction": fmean(quintile_monotone) if quintile_monotone else None,
        "decile_paths": decile_paths,
        "quintile_paths": quintile_paths,
        "turnover_mean": fmean(turnovers) if turnovers else None,
        "sector_neutral": sector_neutral,
        "size_neutral": size_neutral,
        "per_decision": daily,
        "execution_allowed": False,
    }


def _neutral_metrics(rows: pd.DataFrame, group_column: str, policy: RankValidationPolicy) -> dict[str, object]:
    if group_column not in rows.columns:
        return {"status": "unavailable", "reason": f"{group_column} point-in-time groups are missing"}
    daily_ics: list[float] = []
    daily_spreads: list[float] = []
    for _, group in rows.groupby("decision_time", sort=True):
        valid = group.loc[
            group["score"].map(_finite)
            & group["net_return"].map(_finite)
            & group[group_column].notna()
        ].copy()
        if len(valid) < policy.minimum_universe_support:
            continue
        counts = valid.groupby(group_column, dropna=True)["instrument_id"].transform("count")
        valid = valid.loc[counts >= policy.minimum_group_support].copy()
        if len(valid) < policy.minimum_universe_support:
            continue
        valid["neutral_score"] = valid["score"] - valid.groupby(group_column)["score"].transform("mean")
        ic = valid["neutral_score"].corr(valid["net_return"], method="spearman")
        if not _finite(ic):
            continue
        group_spreads = []
        for _, neutral_group in valid.groupby(group_column, sort=True):
            ordered = neutral_group.sort_values(
                ["neutral_score", "instrument_id"], ascending=[False, True], kind="stable"
            )
            top = ordered.head(min(policy.top_n, len(ordered)))
            bottom = ordered.tail(min(policy.bottom_n, len(ordered)))
            group_spreads.append(float(top["net_return"].mean() - bottom["net_return"].mean()))
        daily_ics.append(float(ic))
        daily_spreads.append(fmean(group_spreads))
    if not daily_ics:
        return {"status": "unavailable", "reason": f"{group_column} neutral sample is too small"}
    return {
        "status": "available",
        "decision_count": len(daily_ics),
        "rank_ic_mean": fmean(daily_ics),
        "rank_ic_t": _t_stat(daily_ics),
        "top_minus_bottom_mean": fmean(daily_spreads),
        "top_minus_bottom_t": _t_stat(daily_spreads),
    }


def _factor_attribution(
    rows: pd.DataFrame,
    ranker: str,
    prices: pd.DataFrame,
    policy: RankValidationPolicy,
) -> dict[str, object]:
    required = {"instrument_id", "date", "known_at", "adjusted_close"}
    if not _has_columns(prices, required):
        return {"status": "unavailable", "reason": "factor risk requires point-in-time adjusted-price history", "factors": []}
    contributions: list[dict[str, object]] = []
    for decision_time, group in rows.loc[rows["ranker"].astype(str).eq(ranker)].groupby("decision_time", sort=True):
        cutoff = _aware_timestamp(decision_time)
        if cutoff is None:
            continue
        valid = group.loc[group["score"].map(_finite)].sort_values(
            ["score", "instrument_id"], ascending=[False, True], kind="stable"
        )
        selected = valid.head(min(policy.top_n, len(valid)))
        if len(selected) < 3:
            continue
        price_rows = prices.copy()
        price_rows["_known"] = price_rows["known_at"].map(_aware_timestamp)
        price_rows["_date"] = price_rows["date"].map(_date_value)
        price_rows = price_rows.loc[
            price_rows["_known"].notna()
            & price_rows["_known"].le(cutoff)
            & price_rows["_date"].map(lambda value: value is not None and value <= cutoff.date())
            & price_rows["instrument_id"].astype(str).isin(valid["instrument_id"].astype(str))
        ]
        prices_for_risk = price_rows.rename(columns={"instrument_id": "etf_id"})[["etf_id", "date", "adjusted_close"]]
        allocation = pd.DataFrame(
            {
                "etf_id": selected["instrument_id"].astype(str),
                "current_weight": 1.0 / len(selected),
                "market_value_eur": selected["size_value"].map(_float_or_none).fillna(1.0)
                if "size_value" in selected
                else 1.0,
            }
        )
        features = pd.DataFrame(
            {
                "etf_id": valid["instrument_id"].astype(str),
                "date": pd.Timestamp(cutoff.date()),
                "quality_score_10": valid["quality_score"],
                "value_score_10": valid["value_score"],
                "momentum_120d": valid["momentum_score"],
            }
        )
        try:
            report = build_factor_risk_report(
                prices_for_risk,
                allocation,
                latest_features=features,
                window=252,
            )
        except (ArithmeticError, KeyError, TypeError, ValueError):
            continue
        portfolio = report.get("portfolio_contributions")
        if not isinstance(portfolio, pd.DataFrame) or portfolio.empty:
            continue
        for row in portfolio.to_dict("records"):
            factor = str(row.get("factor", ""))
            if factor in {"quality", "value", "momentum"}:
                contributions.append(
                    {
                        "decision_time": str(decision_time),
                        "factor": factor,
                        "variance_contribution": _float_or_none(row.get("variance_contribution")),
                        "variance_share": _float_or_none(row.get("variance_share")),
                        "factor_model_version": report.get("model_version"),
                    }
                )
    factors = {item["factor"] for item in contributions}
    status = "available" if {"quality", "value", "momentum"}.issubset(factors) else "unavailable"
    return {
        "status": status,
        "method": "portfolio.factor_risk Q/V/M variance attribution",
        "factors": contributions,
        "reason": None if status == "available" else "Q/V/M factor-risk contributions were not all estimable",
    }


def _stable_periods(
    challenger: Mapping[str, object],
    qv: Mapping[str, object],
    qvm: Mapping[str, object],
    policy: RankValidationPolicy,
) -> int:
    c_rows = {str(item["decision_time"]): item for item in challenger.get("per_decision", []) if isinstance(item, Mapping)}
    qv_rows = {str(item["decision_time"]): item for item in qv.get("per_decision", []) if isinstance(item, Mapping)}
    qvm_rows = {str(item["decision_time"]): item for item in qvm.get("per_decision", []) if isinstance(item, Mapping)}
    common = sorted(set(c_rows) & set(qv_rows) & set(qvm_rows))
    if len(common) < policy.subperiod_count:
        return 0
    stable = 0
    for period in _split_periods(common, policy.subperiod_count):
        candidate_net = fmean(float(c_rows[item]["top_net_return"]) for item in period)
        qv_net = fmean(float(qv_rows[item]["top_net_return"]) for item in period)
        qvm_net = fmean(float(qvm_rows[item]["top_net_return"]) for item in period)
        candidate_spread = fmean(float(c_rows[item]["top_minus_bottom"]) for item in period)
        if candidate_net > qv_net and candidate_net > qvm_net and candidate_spread > 0:
            stable += 1
    return stable


def _forward_return(
    prices: pd.DataFrame,
    instrument_id: str,
    cutoff: pd.Timestamp,
    holding_period_sessions: int,
) -> tuple[float | None, str]:
    all_sessions = sorted(
        value
        for value in prices.get("_date", prices["date"].map(_date_value)).dropna().unique()
        if value > cutoff.date()
    )
    frame = prices.loc[prices["instrument_id"].astype(str).eq(instrument_id)].copy()
    frame["_known"] = frame["known_at"].map(_aware_timestamp)
    frame["_date"] = frame.get("_date", frame["date"].map(_date_value))
    frame["_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.loc[frame["_date"].notna()]
    frame = frame.sort_values(["_date", "_known"], kind="stable")
    entry_rows = frame.loc[
        frame["_date"].map(lambda value: value <= cutoff.date())
        & frame["_known"].notna()
        & frame["_known"].le(cutoff)
        & frame["_close"].map(_finite)
        & frame["_close"].gt(0)
    ]
    if entry_rows.empty:
        return None, "entry_price_unavailable_at_decision_time"
    entry_date = entry_rows["_date"].max()
    entry_candidates = entry_rows.loc[entry_rows["_date"].eq(entry_date)]
    if len(entry_candidates) != 1:
        return None, "entry_price_ambiguous"
    entry = float(entry_candidates.iloc[0]["_close"])
    if len(all_sessions) < holding_period_sessions:
        return None, "forward_price_window_not_matured"
    target_date = all_sessions[holding_period_sessions - 1]
    future = frame.loc[frame["_date"].map(lambda value: cutoff.date() < value <= target_date)]
    if "delisted" in future.columns:
        delisted = future.loc[future["delisted"].map(_true_flag)]
    else:
        delisted = future.iloc[0:0]
    if not delisted.empty:
        terminal_date = delisted["_date"].min()
        terminal_rows = delisted.loc[delisted["_date"].eq(terminal_date)]
        if "delisting_return" in terminal_rows and len(terminal_rows):
            terminal_return = _finite_or(terminal_rows.iloc[-1]["delisting_return"], math.nan)
            if math.isfinite(terminal_return):
                return terminal_return, "available_delisting_return"
        terminal_price = terminal_rows.iloc[-1]["_close"] if len(terminal_rows) else None
        if _finite(terminal_price) and float(terminal_price) >= 0:
            return float(terminal_price) / entry - 1.0, "available_delisted_terminal_price"
        return None, "delisting_terminal_value_unavailable"
    target = frame.loc[frame["_date"].eq(target_date)]
    if len(target) != 1 or not _finite(target.iloc[0]["_close"]) or float(target.iloc[0]["_close"]) <= 0:
        return None, "target_price_unavailable"
    return float(target.iloc[0]["_close"]) / entry - 1.0, "available"


def _point_in_time_cost(costs: pd.DataFrame, instrument_id: str, cutoff: pd.Timestamp) -> float | None:
    rows = costs.loc[
        costs["instrument_id"].astype(str).eq(instrument_id)
        & costs["cost_model_id"].astype(str).eq(COST_MODEL_ID)
    ].copy()
    rows["_known"] = rows["known_at"].map(_aware_timestamp)
    rows = rows.loc[rows["_known"].notna() & rows["_known"].le(cutoff)]
    if rows.empty:
        return None
    latest = rows["_known"].max()
    rows = rows.loc[rows["_known"].eq(latest)]
    if len(rows) != 1:
        return None
    value = rows.iloc[0]["round_trip_cost_bps"]
    if not _finite(value) or float(value) < 0:
        return None
    return float(value)


def _outcome_for_date(frame: pd.DataFrame, decision_date: str) -> float | None:
    if not isinstance(frame, pd.DataFrame) or not {"decision_date", "net_return"}.issubset(frame.columns):
        return None
    rows = frame.loc[frame["decision_date"].astype(str).eq(str(decision_date))]
    if len(rows) != 1 or not _finite(rows.iloc[0]["net_return"]):
        return None
    return float(rows.iloc[0]["net_return"])


def _frozen_config_hashes(
    policy: RankValidationPolicy,
    domain_path: str | Path,
    opportunity_path: str | Path,
) -> dict[str, str]:
    from etf_cockpit.analysis.decision.domains import load_domain_registry
    from etf_cockpit.analysis.decision.opportunity import load_opportunity_policy

    domain_registry = load_domain_registry(domain_path)
    opportunity_policy = load_opportunity_policy(opportunity_path)
    return {
        "decision_domains_v1": domain_registry.checksum,
        "decision_opportunity_v1": opportunity_policy.checksum,
        "decision_cutover_v1": policy.checksum,
    }


def _empty_replay(hashes: Mapping[str, str], versions: Mapping[str, str], reason: str) -> RankReplayReport:
    return RankReplayReport(
        pd.DataFrame(),
        "insufficient_evidence",
        (),
        dict(hashes),
        dict(versions),
        {"complete": False, "covered_decisions": 0, "requested_decisions": 0, "coverage_fraction": 0.0, "reasons": {}},
        reason,
    )


def _empty_validation(replay: RankReplayReport, holdout: tuple[str, ...], reason: str) -> RankValidationReport:
    return RankValidationReport(
        validation_id="",
        status="insufficient_evidence",
        development={},
        holdout={},
        holdout_decision_times=holdout,
        walk_forward_splits=pd.DataFrame(),
        pit_availability=dict(replay.pit_availability),
        replay_config_hashes=dict(replay.config_hashes),
        reason=reason,
    )


def _valid_promotion_record(record: Mapping[str, object] | None) -> bool:
    if not isinstance(record, Mapping):
        return False
    pit = record.get("pit_availability")
    return bool(
        record.get("schema_version") == 1
        and isinstance(record.get("record_id"), str)
        and bool(str(record.get("record_id")).strip())
        and isinstance(record.get("validation_id"), str)
        and bool(str(record.get("validation_id")).strip())
        and isinstance(record.get("selected_rank"), str)
        and bool(str(record.get("selected_rank")).strip())
        and record.get("status") in {"promoted", "baseline_champion"}
        and bool(str(record.get("rationale", "")).strip())
        and isinstance(pit, Mapping)
        and pit.get("complete") is True
        and _finite(pit.get("coverage_fraction"))
        and float(pit["coverage_fraction"]) == 1.0
        and _finite(record.get("incremental_ic"))
        and record.get("rank_authority") is True
    )


def _valid_stay_on_v3_record(record: Mapping[str, object] | None) -> bool:
    if not isinstance(record, Mapping):
        return False
    pit = record.get("pit_availability")
    return bool(
        record.get("schema_version") == 1
        and record.get("status") == "stay_on_v3"
        and record.get("selected_rank") == "v3"
        and isinstance(record.get("record_id"), str)
        and bool(str(record.get("record_id")).strip())
        and isinstance(record.get("validation_id"), str)
        and bool(str(record.get("validation_id")).strip())
        and bool(str(record.get("reason", "")).strip())
        and bool(str(record.get("rationale", "")).strip())
        and isinstance(pit, Mapping)
        and record.get("rank_authority") is False
    )


def _decision_times(values: Sequence[datetime | date | str]) -> tuple[pd.Timestamp, ...]:
    result: list[pd.Timestamp] = []
    for value in values:
        timestamp = _aware_timestamp(value)
        if timestamp is None:
            raise ValueError("decision times must be timezone-aware")
        result.append(timestamp)
    if len(set(result)) != len(result):
        raise ValueError("decision times must be unique")
    return tuple(sorted(result))


def _aware_timestamp(value: object) -> pd.Timestamp | None:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if timestamp.tzinfo is None:
        return None
    return timestamp.tz_convert("UTC")


def _date_value(value: object) -> date | None:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return None if pd.isna(timestamp) else timestamp.date()


def _optional_date_value(value: object) -> date | None:
    if value is None or value is pd.NaT or pd.isna(value):
        return None
    return _date_value(value)


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("rank validation integer settings must be positive integers")
    return value


def _positive_number(value: object) -> float:
    if not _finite(value) or float(value) <= 0:
        raise ValueError("rank validation thresholds must be finite and positive")
    return float(value)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _float_or_none(value: object) -> float | None:
    return float(value) if _finite(value) else None


def _finite_or(value: object, default: float) -> float:
    return float(value) if _finite(value) else default


def _true_flag(value: object) -> bool:
    return value is True or (isinstance(value, bool) and value) or str(value).casefold() == "true"


def _has_columns(frame: pd.DataFrame, columns: set[str]) -> bool:
    return isinstance(frame, pd.DataFrame) and columns.issubset(frame.columns)


def _mean_column(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    values = [float(value) for value in frame[column] if _finite(value)]
    return fmean(values) if values else None


def _bucket_means(frame: pd.DataFrame, buckets: int) -> list[float]:
    if len(frame) < buckets * 2 or frame["score"].nunique() < buckets:
        return []
    ordered = frame.sort_values(["score", "instrument_id"], kind="stable").copy()
    ordered["bucket"] = pd.qcut(
        ordered["score"].rank(method="first"),
        q=buckets,
        labels=False,
        duplicates="drop",
    )
    means = ordered.groupby("bucket", observed=True)["net_return"].mean().sort_index()
    return [float(value) for value in means]


def _t_stat(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    scale = stdev(float(value) for value in values)
    if not math.isfinite(scale) or scale <= 0:
        return None
    value = fmean(float(item) for item in values) / (scale / math.sqrt(len(values)))
    return value if math.isfinite(value) else None


def _turnover(rows: pd.DataFrame, top_n: int) -> list[float]:
    previous: dict[str, float] | None = None
    turnover: list[float] = []
    for _, group in rows.groupby("decision_time", sort=True):
        valid = group.loc[group["score"].map(_finite)].sort_values(
            ["score", "instrument_id"], ascending=[False, True], kind="stable"
        )
        selected = valid.head(min(top_n, len(valid)))
        current = {str(item): 1.0 / len(selected) for item in selected["instrument_id"]} if len(selected) else {}
        if previous is not None:
            turnover.append(0.5 * math.fsum(abs(current.get(item, 0.0) - previous.get(item, 0.0)) for item in set(current) | set(previous)))
        previous = current
    return turnover


def _split_periods(values: Sequence[str], count: int) -> list[list[str]]:
    if len(values) < count:
        return []
    return [list(values[index * len(values) // count : (index + 1) * len(values) // count]) for index in range(count)]


def _metric_available(metrics: Mapping[str, object]) -> bool:
    return metrics.get("status") == "available" and _finite(metrics.get("net_return_mean"))


def _normalise_lf(content: bytes) -> bytes:
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


__all__ = [
    "RankCutover",
    "RankReplayReport",
    "RankValidationPolicy",
    "RankValidationReport",
    "RankerSpec",
    "evaluate_rank_validation",
    "load_rank_validation_policy",
    "metric_rank_authority_record",
    "monitor_champion_rank",
    "promotion_decision",
    "rank_validation_metrics",
    "replay_rank_panel",
    "resolve_rank_cutover",
    "route_consumer_rank",
    "route_ranked_frame",
    "select_challenger",
]
