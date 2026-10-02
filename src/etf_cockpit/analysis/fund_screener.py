"""Deterministic, advisory top-N ordinary-fund screening over sealed results."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

from etf_cockpit.analysis.fixed_income_screener import (
    _bootstrap_peer_rank,
    _robust_percentile,
)
from etf_cockpit.analysis.fund_analysis import FundAnalysisRecord, FundReturnDecomposition
from etf_cockpit.analysis.fund_forecasts import (
    FundRecommendationProjection,
    FundReturnDistribution,
)
from etf_cockpit.analysis.fund_peers import (
    FundPeerCohort,
    FundPeerFund,
    _economic_strategy_id,
    _share_class_representative_rank,
)
from etf_cockpit.data.classification import DEFAULT_LEAF_CONFIDENCE
from etf_cockpit.data.fund_identity import FundStructure

_SCORE_WEIGHT_KEYS = frozenset(
    {"total_return", "distribution", "total_fee_bps", "peer_percentile"}
)
_REPRESENTATIVE_RULE = "earliest_inception_then_share_class_id"
_REPRESENTATIVE_NO_INCEPTION_RULE = "share_class_id_no_inception_evidence"


class FundScreenerError(ValueError):
    """Raised when sealed fund screener inputs or configuration are invalid."""


@dataclass(frozen=True)
class FundScreenerConfig:
    top_n: int
    allow_multiple_classes: bool
    bootstrap_samples: int
    ranking_seed: int
    score_weights: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class FundScreenerInput:
    """Join the existing slice-A, slice-B, and slice-C outputs for one class."""

    peer_fund: FundPeerFund
    distribution: FundReturnDistribution
    recommendation_projection: FundRecommendationProjection
    peer_cohort: FundPeerCohort | None


@dataclass(frozen=True)
class FundScreenerRow:
    economic_strategy_id: str
    fund_id: str
    record_id: str
    share_class_id: str
    representative_share_class_id: str
    share_class_ids: tuple[str, ...]
    representative_rule: str
    status: str
    return_decomposition: FundReturnDecomposition
    total_fee_bps: Decimal | None
    distribution: FundReturnDistribution
    class_recommendations: tuple[FundRecommendationProjection, ...]
    sector: str | None
    country: str | None
    peer_percentile: Decimal | None
    rank_stability: Decimal | None
    rank_stability_seed: int
    peer_median_q05: Decimal | None
    peer_median_q95: Decimal | None
    score: Decimal | None
    ranking_tier: str | None
    reason_codes: tuple[str, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class FundScreenerViewEntry:
    economic_strategy_id: str
    share_class_id: str
    representative_share_class_id: str
    class_recommendations: tuple[FundRecommendationProjection, ...]
    score: Decimal
    tier: str
    rank: int


@dataclass(frozen=True)
class FundScreenerView:
    dimension: str
    bucket: str | tuple[str, str] | None
    entries: tuple[FundScreenerViewEntry, ...]


@dataclass(frozen=True)
class FundScreenerFunnelEntry:
    reason_code: str
    count: int


@dataclass(frozen=True)
class FundScreenerSnapshot:
    analysis_snapshot_id: str
    decision_time: datetime
    config: FundScreenerConfig
    status: str
    rows: tuple[FundScreenerRow, ...]
    views: tuple[FundScreenerView, ...]
    exclusion_funnel: tuple[FundScreenerFunnelEntry, ...]
    reason_codes: tuple[str, ...]
    execution_allowed: bool = False


def parse_fund_screener_config(value: object) -> FundScreenerConfig:
    """Parse the strict ``screener`` section of the fund analysis policy."""

    if not isinstance(value, Mapping) or set(value) != {
        "top_n",
        "allow_multiple_classes",
        "bootstrap_samples",
        "ranking_seed",
        "score_weights",
    }:
        raise FundScreenerError("fund screener configuration keys are invalid")
    top_n = _positive_int(value["top_n"], "top_n")
    allow_multiple_classes = value["allow_multiple_classes"]
    if type(allow_multiple_classes) is not bool:
        raise FundScreenerError("allow_multiple_classes must be a boolean")
    bootstrap_samples = _positive_int(value["bootstrap_samples"], "bootstrap_samples")
    ranking_seed = value["ranking_seed"]
    if type(ranking_seed) is not int:
        raise FundScreenerError("ranking_seed must be an integer")
    raw_weights = value["score_weights"]
    if not isinstance(raw_weights, Mapping) or set(raw_weights) != _SCORE_WEIGHT_KEYS:
        raise FundScreenerError("fund screener score weight keys are invalid")
    weights = tuple(
        (name, _decimal(raw_weights[name], f"score_weights.{name}"))
        for name in sorted(_SCORE_WEIGHT_KEYS)
    )
    if any(weight < 0 for _, weight in weights) or sum(
        (weight for _, weight in weights), Decimal("0")
    ) <= 0:
        raise FundScreenerError("fund screener score weights must be non-negative and non-zero")
    return FundScreenerConfig(
        top_n,
        allow_multiple_classes,
        bootstrap_samples,
        ranking_seed,
        weights,
    )


def load_fund_screener_config(path: Path | None = None) -> FundScreenerConfig:
    """Load the strictly validated screener section from fund analysis policy."""

    from etf_cockpit.analysis.fund_analysis import (
        FUND_ANALYSIS_CONFIG,
        load_fund_analysis_config,
    )

    return load_fund_analysis_config(path or FUND_ANALYSIS_CONFIG).screener


def build_fund_screener(
    funds: Sequence[FundScreenerInput],
    *,
    decision_time: datetime,
    config: FundScreenerConfig,
) -> FundScreenerSnapshot:
    """Build total, sector, country, and country-by-sector views from sealed inputs."""

    decision = _timestamp(decision_time, "decision_time")
    if not isinstance(config, FundScreenerConfig):
        raise FundScreenerError("fund screener config has the wrong contract")
    if len(dict(config.score_weights)) != len(config.score_weights):
        raise FundScreenerError("fund screener score weights must have unique keys")
    config = parse_fund_screener_config(
        {
            "top_n": config.top_n,
            "allow_multiple_classes": config.allow_multiple_classes,
            "bootstrap_samples": config.bootstrap_samples,
            "ranking_seed": config.ranking_seed,
            "score_weights": {
                name: format(weight, "f") for name, weight in config.score_weights
            },
        }
    )
    if not isinstance(funds, Sequence) or isinstance(funds, (str, bytes)):
        raise FundScreenerError("fund screener inputs must be a sequence")
    inputs = tuple(funds)
    for item in inputs:
        _validate_input(item, decision)
    _validate_unique_inputs(inputs)

    grouped: dict[str, list[FundScreenerInput]] = defaultdict(list)
    for item in inputs:
        grouped[_economic_strategy_id(item.peer_fund)].append(item)

    candidates: list[tuple[FundScreenerInput, tuple[FundScreenerInput, ...], str, str]] = []
    for strategy_id, classes in sorted(grouped.items()):
        ordered = tuple(sorted(classes, key=lambda row: row.peer_fund.share_class.share_class_id))
        if config.allow_multiple_classes:
            candidates.extend(
                (item, (item,), item.peer_fund.share_class.share_class_id, _REPRESENTATIVE_RULE)
                for item in ordered
            )
            continue
        ranks = tuple(
            _share_class_representative_rank(item.peer_fund, decision)
            for item in ordered
        )
        if len(ranks) == 1 or all(rank[0] is not None for rank in ranks):
            representative_index = min(range(len(ordered)), key=lambda index: ranks[index])
            representative_rule = _REPRESENTATIVE_RULE
        else:
            representative_index = min(
                range(len(ordered)),
                key=lambda index: ordered[index].peer_fund.share_class.share_class_id,
            )
            representative_rule = _REPRESENTATIVE_NO_INCEPTION_RULE
        candidates.append(
            (
                ordered[representative_index],
                ordered,
                ordered[representative_index].peer_fund.share_class.share_class_id,
                representative_rule,
            )
        )

    preliminary: list[dict[str, object]] = []
    for selected, represented_classes, representative_class_id, representative_rule in candidates:
        record = selected.peer_fund.analysis_record
        decomposition = record.return_decomposition
        distribution = selected.distribution
        reasons: list[str] = []
        if record.status != "available" or record.blockers:
            reasons.append("fund_analysis_blocked")
        if (
            decomposition.status != "available"
            or not isinstance(decomposition.total_return, Decimal)
            or not decomposition.total_return.is_finite()
        ):
            reasons.append("fund_return_unavailable")
        if distribution.status == "unavailable":
            reasons.append("fund_distribution_unavailable")
        if distribution.status not in {"calibrated", "research_only"}:
            reasons.append("fund_distribution_status_unsupported")
        if selected.recommendation_projection.analysis_id != record.record_id:
            reasons.append("fund_recommendation_projection_unavailable")
        if (
            not isinstance(record.total_fee_bps, Decimal)
            or not record.total_fee_bps.is_finite()
            or record.total_fee_bps < 0
        ):
            reasons.append("fund_total_fee_unavailable")
        cohort = selected.peer_cohort
        peer_percentile: Decimal | None = None
        peer_scores: tuple[Decimal, ...] = ()
        if (
            cohort is not None
            and cohort.status == "available"
            and cohort.peer_metric.metric == "total_return"
            and cohort.peer_metric.status == "available"
            and cohort.peer_metric.percentile is not None
            and math.isfinite(cohort.peer_metric.percentile)
            and 0.0 <= cohort.peer_metric.percentile <= 1.0
            and decomposition.total_return is not None
            and cohort.peer_metric.raw_value == float(decomposition.total_return)
        ):
            peer_percentile = Decimal(str(cohort.peer_metric.percentile))
            peer_scores = tuple(
                Decimal(str(observation.value))
                for observation in cohort.cohort.observations
                if observation.applicable
                and observation.value is not None
                and math.isfinite(observation.value)
            )
        else:
            reasons.append("fund_peer_percentile_unavailable")
        if not _has_distribution_score(distribution):
            reasons.append("fund_distribution_values_unavailable")

        sector, sector_reason = _classification_bucket(
            selected.peer_fund, "sector", decision
        )
        country, country_reason = _classification_bucket(
            selected.peer_fund, "legal_domicile", decision
        )
        if sector_reason is not None:
            reasons.append("sector_view_" + sector_reason)
        if country_reason is not None:
            reasons.append("country_view_" + country_reason)
        if sector is None or country is None:
            reasons.append("country_sector_view_classification_incomplete")

        stability: Decimal | None = None
        peer_q05: Decimal | None = None
        peer_q95: Decimal | None = None
        score_return = decomposition.total_return
        if (
            not any(reason in reasons for reason in (
                "fund_analysis_blocked",
                "fund_return_unavailable",
                "fund_distribution_unavailable",
                "fund_distribution_status_unsupported",
                "fund_recommendation_projection_unavailable",
                "fund_total_fee_unavailable",
                "fund_peer_percentile_unavailable",
                "fund_distribution_values_unavailable",
            ))
            and score_return is not None
        ):
            stability, peer_q05, peer_q95 = _bootstrap_peer_rank(
                score_return,
                peer_scores,
                seed=config.ranking_seed,
                instrument_id=selected.peer_fund.context.instrument_id,
                samples=config.bootstrap_samples,
                top_n=config.top_n,
            )
            if stability is None:
                reasons.append("fund_peer_rank_stability_unavailable")

        score_reasons = {
            "fund_analysis_blocked",
            "fund_return_unavailable",
            "fund_distribution_unavailable",
            "fund_distribution_status_unsupported",
            "fund_recommendation_projection_unavailable",
            "fund_total_fee_unavailable",
            "fund_peer_percentile_unavailable",
            "fund_distribution_values_unavailable",
            "fund_peer_rank_stability_unavailable",
        }
        score_available = not any(reason in score_reasons for reason in reasons)
        preliminary.append(
            {
                "selected": selected,
                "represented_classes": represented_classes,
                "representative_class_id": representative_class_id,
                "representative_rule": representative_rule,
                "sector": sector,
                "country": country,
                "peer_percentile": peer_percentile,
                "peer_scores": peer_scores,
                "rank_stability": stability,
                "peer_q05": peer_q05,
                "peer_q95": peer_q95,
                "score_available": score_available,
                "reasons": tuple(dict.fromkeys(reasons)),
            }
        )

    _assign_scores(preliminary, config)
    rows = tuple(
        _row_from_candidate(candidate, config)
        for candidate in sorted(
            preliminary,
            key=lambda value: (
                str(value["selected"].peer_fund.analysis_record.fund_id),
                str(value["representative_class_id"]),
            ),
        )
    )
    views = _build_views(rows, config.top_n)
    funnel_counts = Counter(reason for row in rows for reason in row.reason_codes)
    funnel = tuple(
        FundScreenerFunnelEntry(reason, funnel_counts[reason])
        for reason in sorted(funnel_counts)
    )
    snapshot_reasons = () if any(row.status == "ranked" for row in rows) else (
        "fund_screener_no_rankable_funds",
    )
    snapshot_id = _hash(
        {
            "contract": "fund-screener.v1",
            "decision_time": decision,
            "config": config,
            "inputs": tuple(
                sorted(
                    inputs,
                    key=lambda item: (
                        _economic_strategy_id(item.peer_fund),
                        item.peer_fund.share_class.share_class_id,
                    ),
                )
            ),
        }
    )
    return FundScreenerSnapshot(
        analysis_snapshot_id=snapshot_id,
        decision_time=decision,
        config=config,
        status="available" if not snapshot_reasons else "unavailable",
        rows=rows,
        views=views,
        exclusion_funnel=funnel,
        reason_codes=snapshot_reasons,
    )


def _validate_input(item: FundScreenerInput, decision: datetime) -> None:
    if not isinstance(item, FundScreenerInput):
        raise FundScreenerError("fund screener input has the wrong contract")
    fund = item.peer_fund
    if not isinstance(fund, FundPeerFund) or fund.structure is not FundStructure.ORDINARY_FUND:
        raise FundScreenerError("fund screener accepts ordinary-fund peer inputs only")
    record = fund.analysis_record
    if not isinstance(record, FundAnalysisRecord):
        raise FundScreenerError("fund screener analysis record has the wrong contract")
    if record.share_class_id != fund.share_class.share_class_id:
        raise FundScreenerError("fund record and share-class identity do not match")
    if _timestamp(record.decision_time, "analysis decision_time") != decision:
        raise FundScreenerError("fund analysis decision time does not match the screener cutoff")
    decomposition = record.return_decomposition
    if (
        decomposition.fund_id != record.fund_id
        or decomposition.share_class_id != record.share_class_id
        or decomposition.decision_time != record.decision_time
    ):
        raise FundScreenerError("fund analysis and return identities do not match")
    distribution = item.distribution
    if not isinstance(distribution, FundReturnDistribution):
        raise FundScreenerError("fund return distribution has the wrong contract")
    if (
        distribution.fund_id != record.fund_id
        or distribution.share_class_id != record.share_class_id
        or distribution.economic_strategy_id != _economic_strategy_id(fund)
        or _timestamp(distribution.decision_time, "distribution decision_time") != decision
    ):
        raise FundScreenerError("fund return distribution identity does not match the analysis")
    projection = item.recommendation_projection
    if not isinstance(projection, FundRecommendationProjection):
        raise FundScreenerError("fund recommendation projection has the wrong contract")
    if projection.analysis_id != record.record_id or projection.distribution != distribution:
        raise FundScreenerError("fund recommendation projection identity does not match")
    if item.peer_cohort is not None and not isinstance(item.peer_cohort, FundPeerCohort):
        raise FundScreenerError("fund peer cohort has the wrong contract")
    context = fund.context
    if context.instrument_id != fund.share_class.share_class_id:
        raise FundScreenerError("fund classification and share-class identity do not match")
    if context.share_class_id not in (None, record.share_class_id):
        raise FundScreenerError("fund classification share-class identity does not match")


def _validate_unique_inputs(inputs: Sequence[FundScreenerInput]) -> None:
    identities = [
        (item.peer_fund.analysis_record.fund_id, item.peer_fund.share_class.share_class_id)
        for item in inputs
    ]
    class_ids = [item.peer_fund.share_class.share_class_id for item in inputs]
    if len(identities) != len(set(identities)) or len(class_ids) != len(set(class_ids)):
        raise FundScreenerError("fund screener share-class inputs must be unique")


def _has_distribution_score(distribution: FundReturnDistribution) -> bool:
    values = [distribution.q05, distribution.q50]
    if distribution.status == "calibrated":
        values.extend((distribution.loss_probability, distribution.beat_benchmark_probability))
    return any(isinstance(value, Decimal) and value.is_finite() for value in values)


def _classification_bucket(
    fund: FundPeerFund, field_name: str, decision: datetime
) -> tuple[str | None, str | None]:
    context = fund.context
    if context.classification_status in {"unresolved", "manual_review"}:
        return None, "classification_ambiguous"
    value = getattr(context, field_name)
    if not isinstance(value, str) or not value.strip():
        return None, "classification_missing"
    alternatives = context.alternatives.get(field_name, ())
    if alternatives:
        return None, "classification_ambiguous"
    confidence = context.field_confidence.get(field_name)
    if confidence is None or not math.isfinite(float(confidence)):
        return None, "classification_confidence_unavailable"
    if float(confidence) < DEFAULT_LEAF_CONFIDENCE:
        return None, "classification_confidence_low"
    if _timestamp(context.decision_time, "classification decision_time") > decision:
        return None, "classification_not_known_at_decision"
    if _timestamp(context.effective_at, "classification effective_at") > decision:
        return None, "classification_not_effective_at_decision"
    return value.strip(), None


def _assign_scores(
    candidates: list[dict[str, object]], config: FundScreenerConfig
) -> None:
    weights = dict(config.score_weights)
    tiers = (
        "calibrated",
        "research_only",
    )
    for tier in tiers:
        selected = [
            candidate
            for candidate in candidates
            if candidate["score_available"]
            and candidate["selected"].distribution.status == tier
        ]
        if not selected:
            continue
        return_values = [
            candidate["selected"].peer_fund.analysis_record.return_decomposition.total_return
            for candidate in selected
        ]
        fee_values = [candidate["selected"].peer_fund.analysis_record.total_fee_bps for candidate in selected]
        distribution_values = {
            field_name: [
                getattr(candidate["selected"].distribution, field_name)
                for candidate in selected
                if getattr(candidate["selected"].distribution, field_name) is not None
            ]
            for field_name in ("q05", "q50", "loss_probability", "beat_benchmark_probability")
        }
        for candidate in selected:
            record = candidate["selected"].peer_fund.analysis_record
            distribution = candidate["selected"].distribution
            components: list[tuple[Decimal, Decimal]] = []
            return_pct = _robust_percentile(
                record.return_decomposition.total_return, return_values
            )
            fee_pct = _robust_percentile(record.total_fee_bps, fee_values)
            peer_pct = candidate["peer_percentile"]
            if return_pct is None or fee_pct is None or peer_pct is None:
                candidate["score_available"] = False
                candidate["reasons"] = tuple(
                    dict.fromkeys((*candidate["reasons"], "fund_score_component_unavailable"))
                )
                continue
            if weights["total_return"] > 0:
                components.append((weights["total_return"], return_pct))
            if weights["total_fee_bps"] > 0:
                components.append((weights["total_fee_bps"], Decimal("1") - fee_pct))
            if weights["peer_percentile"] > 0:
                components.append((weights["peer_percentile"], peer_pct))
            distribution_scores: list[Decimal] = []
            for field_name in ("q05", "q50", "loss_probability", "beat_benchmark_probability"):
                value = getattr(distribution, field_name)
                if value is None or (field_name in {"loss_probability", "beat_benchmark_probability"}
                                     and tier != "calibrated"):
                    continue
                metric_values = distribution_values[field_name]
                percentile = _robust_percentile(value, metric_values)
                if percentile is not None:
                    distribution_scores.append(
                        Decimal("1") - percentile
                        if field_name == "loss_probability"
                        else percentile
                    )
            if weights["distribution"] > 0 and distribution_scores:
                components.append(
                    (
                        weights["distribution"],
                        sum(distribution_scores, Decimal("0")) / Decimal(len(distribution_scores)),
                    )
                )
            total_weight = sum((weight for weight, _ in components), Decimal("0"))
            if total_weight <= 0:
                candidate["score_available"] = False
                candidate["reasons"] = tuple(
                    dict.fromkeys((*candidate["reasons"], "fund_score_component_unavailable"))
                )
                continue
            candidate["score"] = sum(
                (weight * score for weight, score in components), Decimal("0")
            ) / total_weight
            candidate["tier"] = tier


def _row_from_candidate(
    candidate: dict[str, object], config: FundScreenerConfig
) -> FundScreenerRow:
    selected: FundScreenerInput = candidate["selected"]
    record = selected.peer_fund.analysis_record
    represented: tuple[FundScreenerInput, ...] = candidate["represented_classes"]
    recommendations = tuple(
        item.recommendation_projection
        for item in sorted(
            represented,
            key=lambda value: value.peer_fund.share_class.share_class_id,
        )
    )
    score_available = bool(candidate["score_available"])
    reasons = list(candidate["reasons"])
    score = candidate.get("score") if score_available else None
    tier = candidate.get("tier") if score_available else None
    if not score_available and not any(
        reason.startswith("fund_") and reason not in {
            "fund_distribution_values_unavailable",
            "fund_peer_percentile_unavailable",
            "fund_total_fee_unavailable",
            "fund_return_unavailable",
            "fund_analysis_blocked",
            "fund_distribution_unavailable",
            "fund_distribution_status_unsupported",
            "fund_recommendation_projection_unavailable",
            "fund_peer_rank_stability_unavailable",
        }
        for reason in reasons
    ):
        reasons.append("fund_not_rankable")
    return FundScreenerRow(
        economic_strategy_id=_economic_strategy_id(selected.peer_fund),
        fund_id=record.fund_id,
        record_id=record.record_id,
        share_class_id=record.share_class_id,
        representative_share_class_id=str(candidate["representative_class_id"]),
        share_class_ids=tuple(
            sorted(item.peer_fund.share_class.share_class_id for item in represented)
        ),
        representative_rule=str(candidate["representative_rule"]),
        status="ranked" if score_available and score is not None else "excluded",
        return_decomposition=record.return_decomposition,
        total_fee_bps=record.total_fee_bps,
        distribution=selected.distribution,
        class_recommendations=recommendations,
        sector=candidate["sector"],
        country=candidate["country"],
        peer_percentile=candidate["peer_percentile"],
        rank_stability=candidate["rank_stability"],
        rank_stability_seed=config.ranking_seed,
        peer_median_q05=candidate["peer_q05"],
        peer_median_q95=candidate["peer_q95"],
        score=score if isinstance(score, Decimal) else None,
        ranking_tier=str(tier) if tier is not None else None,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _build_views(rows: Sequence[FundScreenerRow], top_n: int) -> tuple[FundScreenerView, ...]:
    eligible = [row for row in rows if row.status == "ranked" and row.score is not None]
    views: list[FundScreenerView] = [_make_view("total", None, eligible, top_n)]
    sectors: dict[str, list[FundScreenerRow]] = defaultdict(list)
    countries: dict[str, list[FundScreenerRow]] = defaultdict(list)
    intersections: dict[tuple[str, str], list[FundScreenerRow]] = defaultdict(list)
    for row in eligible:
        if row.sector is not None:
            sectors[row.sector].append(row)
        if row.country is not None:
            countries[row.country].append(row)
        if row.country is not None and row.sector is not None:
            intersections[(row.country, row.sector)].append(row)
    views.extend(_make_view("sector", bucket, grouped, top_n) for bucket, grouped in sorted(sectors.items()))
    views.extend(_make_view("country", bucket, grouped, top_n) for bucket, grouped in sorted(countries.items()))
    views.extend(
        _make_view("country_sector", bucket, grouped, top_n)
        for bucket, grouped in sorted(intersections.items())
    )
    return tuple(views)


def _make_view(
    dimension: str,
    bucket: str | tuple[str, str] | None,
    rows: Sequence[FundScreenerRow],
    top_n: int,
) -> FundScreenerView:
    ranked = sorted(
        rows,
        key=lambda row: (
            0 if row.ranking_tier == "calibrated" else 1,
            -row.score if row.score is not None else Decimal("0"),
            row.economic_strategy_id,
            row.representative_share_class_id,
        ),
    )[:top_n]
    entries = tuple(
        FundScreenerViewEntry(
            economic_strategy_id=row.economic_strategy_id,
            share_class_id=row.share_class_id,
            representative_share_class_id=row.representative_share_class_id,
            class_recommendations=row.class_recommendations,
            score=row.score or Decimal("0"),
            tier=row.ranking_tier or "research_only",
            rank=index,
        )
        for index, row in enumerate(ranked, start=1)
    )
    return FundScreenerView(dimension, bucket, entries)


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise FundScreenerError(f"{field_name} must be a positive integer")
    return value


def _decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, str):
        raise FundScreenerError(f"{field_name} must be encoded as a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise FundScreenerError(f"{field_name} must be a finite decimal") from exc
    if not result.is_finite():
        raise FundScreenerError(f"{field_name} must be a finite decimal")
    return result


def _timestamp(value: datetime | str, field_name: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise FundScreenerError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FundScreenerError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _hash(value: object) -> str:
    encoded = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical(value: object) -> object:
    if is_dataclass(value):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


__all__ = [
    "FundScreenerConfig",
    "FundScreenerError",
    "FundScreenerFunnelEntry",
    "FundScreenerInput",
    "FundScreenerRow",
    "FundScreenerSnapshot",
    "FundScreenerView",
    "FundScreenerViewEntry",
    "build_fund_screener",
    "load_fund_screener_config",
    "parse_fund_screener_config",
]
