"""Deterministic, advisory fixed-income peer and return screening."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import random
import re
from statistics import median
from typing import Mapping, Sequence

import yaml

from etf_cockpit.analysis.fixed_income_returns import (
    FixedIncomeReturnDecomposition,
    FixedIncomeReturnInput,
    FixedIncomeReturnDistribution,
    calculate_fixed_income_return_decomposition,
    uncalibrated_fixed_income_distribution,
)


FIXED_INCOME_SCREENER_CONTRACT = "fixed-income-screener.v1"
FIXED_INCOME_SCREENER_CONFIG = Path("configs/fixed_income_returns_v1.yaml")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_CONFIG_KEYS = frozenset(
    {
        "schema_version",
        "horizon_days",
        "rate_shock_bps",
        "spread_shock_bps",
        "base_currency",
        "maximum_observation_age_days",
        "minimum_peer_support",
        "top_n",
        "bootstrap_samples",
        "ranking_seed",
        "risk_penalty_bps_per_duration_year",
        "maturity_buckets_years",
        "duration_buckets_years",
    }
)


class FixedIncomeScreenerError(ValueError):
    """Raised when screener inputs or policy configuration are invalid."""


@dataclass(frozen=True)
class FixedIncomeScreenerConfig:
    schema_version: int
    horizon_days: int
    rate_shock_bps: Decimal
    spread_shock_bps: Decimal
    base_currency: str
    maximum_observation_age_days: int
    minimum_peer_support: int
    top_n: int
    bootstrap_samples: int
    ranking_seed: int
    risk_penalty_bps_per_duration_year: Decimal
    maturity_buckets_years: tuple[Decimal, ...]
    duration_buckets_years: tuple[Decimal, ...]


@dataclass(frozen=True)
class FixedIncomeScreenerSecurity:
    instrument_id: str
    security_type: str | None
    issuer_id: str | None
    issuer_sector: str | None
    country: str | None
    currency: str | None
    seniority: str | None
    rating: str | None
    coupon_type: str | None
    maturity_date: date | None
    duration_years: Decimal | None
    liquidity_bucket: str | None
    liquidity_status: str
    return_input: FixedIncomeReturnInput | None
    reason_codes: tuple[str, ...] = ()
    source_lineage: tuple[str, ...] = ()
    portfolio_fit: str = "not_assessed"


@dataclass(frozen=True)
class FixedIncomePeerCohort:
    cohort_id: str
    instrument_id: str
    level: str
    keys: tuple[tuple[str, str], ...]
    peer_instrument_ids: tuple[str, ...]
    support: int
    minimum_support: int
    status: str
    reason_codes: tuple[str, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class FixedIncomeScreenerRow:
    record_id: str
    instrument_id: str
    status: str
    recommendation: str
    yield_to_worst: Decimal | None
    duration_years: Decimal | None
    baseline_total_return: Decimal | None
    net_total_return: Decimal | None
    risk_penalty: Decimal | None
    risk_adjusted_score: Decimal | None
    forecast_status: str
    q05: Decimal | None
    q50: Decimal | None
    q95: Decimal | None
    loss_probability: Decimal | None
    beat_cash_probability: Decimal | None
    beat_benchmark_probability: Decimal | None
    liquidity_status: str
    peer_support: int
    peer_minimum_support: int
    peer_level: str | None
    peer_status: str
    robust_percentile: Decimal | None
    peer_score_ci_q05: Decimal | None
    peer_score_ci_q95: Decimal | None
    rank_stability: Decimal | None
    rank_stability_seed: int
    rank: int | None
    top_n: bool
    portfolio_fit: str
    reason_codes: tuple[str, ...]
    decomposition: FixedIncomeReturnDecomposition | None
    peer_cohort: FixedIncomePeerCohort | None
    distribution: FixedIncomeReturnDistribution | None
    source_lineage: tuple[str, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class FixedIncomeScreenerSnapshot:
    analysis_snapshot_id: str
    decision_time: datetime
    config: FixedIncomeScreenerConfig
    status: str
    rows: tuple[FixedIncomeScreenerRow, ...]
    top_n_instrument_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    execution_allowed: bool = False


def load_fixed_income_screener_config(path: Path) -> FixedIncomeScreenerConfig:
    """Load the typed decision defaults; missing or changed policy fails closed."""

    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise FixedIncomeScreenerError("fixed-income screener config is unavailable") from exc
    if not isinstance(payload, Mapping) or set(payload) != _CONFIG_KEYS:
        raise FixedIncomeScreenerError("fixed-income screener config schema is invalid")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise FixedIncomeScreenerError("fixed-income screener config version is unsupported")
    try:
        base_currency = str(payload["base_currency"]).strip().upper()
        if not _CURRENCY.fullmatch(base_currency):
            raise ValueError("base_currency must be an ISO-style currency code")
        config = FixedIncomeScreenerConfig(
            schema_version=1,
            horizon_days=_positive_int(payload["horizon_days"], "horizon_days"),
            rate_shock_bps=_decimal(payload["rate_shock_bps"], "rate_shock_bps"),
            spread_shock_bps=_decimal(payload["spread_shock_bps"], "spread_shock_bps"),
            base_currency=base_currency,
            maximum_observation_age_days=_positive_int(
                payload["maximum_observation_age_days"], "maximum_observation_age_days"
            ),
            minimum_peer_support=_positive_int(
                payload["minimum_peer_support"], "minimum_peer_support"
            ),
            top_n=_positive_int(payload["top_n"], "top_n"),
            bootstrap_samples=_positive_int(payload["bootstrap_samples"], "bootstrap_samples"),
            ranking_seed=_integer(payload["ranking_seed"], "ranking_seed"),
            risk_penalty_bps_per_duration_year=_decimal(
                payload["risk_penalty_bps_per_duration_year"],
                "risk_penalty_bps_per_duration_year",
            ),
            maturity_buckets_years=_buckets(payload["maturity_buckets_years"], "maturity_buckets_years"),
            duration_buckets_years=_buckets(payload["duration_buckets_years"], "duration_buckets_years"),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise FixedIncomeScreenerError("fixed-income screener config values are invalid") from exc
    if config.risk_penalty_bps_per_duration_year < 0:
        raise FixedIncomeScreenerError("duration risk penalty cannot be negative")
    return config


def build_fixed_income_screener(
    securities: Sequence[FixedIncomeScreenerSecurity],
    *,
    decision_time: datetime,
    config: FixedIncomeScreenerConfig,
) -> FixedIncomeScreenerSnapshot:
    """Build deterministic peer fallback, research ranks and persisted row payloads."""

    if decision_time.tzinfo is None:
        raise FixedIncomeScreenerError("decision_time must be timezone-aware")
    items = tuple(sorted(securities, key=lambda item: item.instrument_id))
    if len({item.instrument_id for item in items}) != len(items):
        raise FixedIncomeScreenerError("security identifiers must be unique")
    for item in items:
        if not item.instrument_id.strip():
            raise FixedIncomeScreenerError("instrument_id is required")
        if (
            item.return_input is not None
            and item.return_input.valuation.decision_time > decision_time
        ):
            raise FixedIncomeScreenerError("security return inputs are future-known")

    provisional = []
    for item in items:
        calculation_failed = False
        try:
            decomposition = (
                calculate_fixed_income_return_decomposition(item.return_input)
                if item.return_input is not None
                else None
            )
        except ValueError:
            decomposition = None
            calculation_failed = True
        distribution = (
            uncalibrated_fixed_income_distribution(decomposition)
            if decomposition is not None
            else None
        )
        reasons = list(item.reason_codes)
        if calculation_failed:
            reasons.append("fixed_income_return_calculation_failed")
        if decomposition is None:
            reasons.append("fixed_income_return_inputs_unavailable")
        else:
            reasons.extend(decomposition.reason_codes)
        if distribution is not None:
            reasons.extend(distribution.reason_codes)
        if item.liquidity_status != "available":
            reasons.append("precise_liquidity_evidence_unavailable")
        duration = (
            decomposition.modified_duration
            if decomposition is not None
            else item.duration_years
        )
        baseline = decomposition.baseline_total_return if decomposition is not None else None
        net = decomposition.net_total_return if decomposition is not None else None
        risk_penalty = (
            duration * config.risk_penalty_bps_per_duration_year / Decimal("10000")
            if duration is not None
            else None
        )
        score_base = net if net is not None else baseline
        score = (
            score_base - risk_penalty
            if score_base is not None and risk_penalty is not None
            else None
        )
        provisional.append(
            {
                "security": item,
                "decomposition": decomposition,
                "distribution": distribution,
                "reasons": list(dict.fromkeys(reasons)),
                "duration": duration,
                "baseline": baseline,
                "net": net,
                "risk_penalty": risk_penalty,
                "score": score,
            }
        )

    peer_securities = tuple(
        replace(
            current["security"],
            duration_years=current["duration"],
        )
        for current in provisional
    )
    peer_by_id = {item.instrument_id: item for item in peer_securities}
    cohorts: dict[str, FixedIncomePeerCohort] = {}
    for current in provisional:
        item = peer_by_id[current["security"].instrument_id]
        cohort = _peer_cohort(item, peer_securities, config)
        current["cohort"] = cohort
        cohorts[cohort.cohort_id] = cohort
        if cohort.status != "supported":
            current["reasons"].extend(cohort.reason_codes)

    rankable = [
        current
        for current in provisional
        if current["score"] is not None
        and current["net"] is not None
        and current["security"].liquidity_status == "available"
        and current["cohort"].status == "supported"
    ]
    ranked = sorted(
        rankable,
        key=lambda current: (-current["score"], current["security"].instrument_id),
    )
    ranks = {
        current["security"].instrument_id: rank
        for rank, current in enumerate(ranked, start=1)
    }

    rows: list[FixedIncomeScreenerRow] = []
    for current in provisional:
        item = current["security"]
        cohort = current["cohort"]
        peers = (
            [
                value["score"]
                for value in provisional
                if value["security"].instrument_id in cohort.peer_instrument_ids
                and value["score"] is not None
            ]
            if cohort.status == "supported"
            else []
        )
        robust = _robust_percentile(current["score"], peers)
        stability, ci_low, ci_high = _bootstrap_peer_rank(
            current["score"],
            peers,
            seed=config.ranking_seed,
            instrument_id=item.instrument_id,
            samples=config.bootstrap_samples,
            top_n=config.top_n,
        )
        reasons = tuple(dict.fromkeys(current["reasons"]))
        rank = ranks.get(item.instrument_id)
        status = "available" if rank is not None else "unavailable" if current["baseline"] is None else "rejected"
        distribution = current["distribution"]
        rows.append(
            FixedIncomeScreenerRow(
                record_id="",
                instrument_id=item.instrument_id,
                status=status,
                recommendation=("research_only" if current["baseline"] is not None else "unavailable"),
                yield_to_worst=(
                    current["decomposition"].yield_to_worst
                    if current["decomposition"] is not None
                    else None
                ),
                duration_years=current["duration"],
                baseline_total_return=current["baseline"],
                net_total_return=current["net"],
                risk_penalty=current["risk_penalty"],
                risk_adjusted_score=current["score"],
                forecast_status=distribution.status if distribution is not None else "unavailable",
                q05=distribution.q05 if distribution is not None else None,
                q50=distribution.q50 if distribution is not None else None,
                q95=distribution.q95 if distribution is not None else None,
                loss_probability=distribution.loss_probability if distribution is not None else None,
                beat_cash_probability=distribution.beat_cash_probability if distribution is not None else None,
                beat_benchmark_probability=distribution.beat_benchmark_probability if distribution is not None else None,
                liquidity_status=item.liquidity_status,
                peer_support=cohort.support,
                peer_minimum_support=config.minimum_peer_support,
                peer_level=cohort.level,
                peer_status=cohort.status,
                robust_percentile=robust,
                peer_score_ci_q05=ci_low,
                peer_score_ci_q95=ci_high,
                rank_stability=stability,
                rank_stability_seed=config.ranking_seed,
                rank=rank,
                top_n=rank is not None and rank <= config.top_n,
                portfolio_fit=item.portfolio_fit,
                reason_codes=reasons,
                decomposition=current["decomposition"],
                peer_cohort=cohort,
                distribution=distribution,
                source_lineage=item.source_lineage,
                execution_allowed=False,
            )
        )

    frozen_inputs = {
        "decision_time": decision_time,
        "config": config,
        "securities": items,
    }
    snapshot_id = _hash(frozen_inputs)
    rows = [replace(row, record_id=_hash((snapshot_id, row.instrument_id))) for row in rows]
    return FixedIncomeScreenerSnapshot(
        analysis_snapshot_id=snapshot_id,
        decision_time=decision_time,
        config=config,
        status="available" if rows else "unavailable",
        rows=tuple(rows),
        top_n_instrument_ids=tuple(
            item["security"].instrument_id
            for item in ranked[: config.top_n]
        ),
        reason_codes=() if rows else ("fixed_income_screener_universe_unavailable",),
        execution_allowed=False,
    )


def _peer_cohort(
    target: FixedIncomeScreenerSecurity,
    securities: Sequence[FixedIncomeScreenerSecurity],
    config: FixedIncomeScreenerConfig,
) -> FixedIncomePeerCohort:
    keys = _security_keys(target, config)
    levels = (
        ("leaf", ("security_type", "issuer_sector", "country", "currency", "seniority", "rating", "coupon_type", "maturity_bucket", "duration_bucket", "liquidity_bucket")),
        ("without_liquidity", ("security_type", "issuer_sector", "country", "currency", "seniority", "rating", "coupon_type", "maturity_bucket", "duration_bucket")),
        ("term_parent", ("security_type", "issuer_sector", "country", "currency", "seniority", "rating", "coupon_type")),
        ("currency_type_parent", ("security_type", "currency", "coupon_type")),
    )
    last_keys: tuple[tuple[str, str], ...] = ()
    last_peers: tuple[str, ...] = ()
    last_level = "unavailable"
    for level, dimensions in levels:
        if any(keys.get(name) is None for name in dimensions):
            continue
        selected = tuple((name, keys[name]) for name in dimensions)
        last_keys = selected
        last_level = level
        peers = tuple(
            sorted(
                item.instrument_id
                for item in securities
                if item.instrument_id != target.instrument_id
                and _same_keys(_security_keys(item, config), selected)
            )
        )
        last_peers = peers
        if len(peers) >= config.minimum_peer_support:
            status = "supported"
            reasons: tuple[str, ...] = ()
            break
    else:
        status = "unavailable"
        reasons = ("peer_support_below_minimum",)
    identity = _hash((level if status == "supported" else last_level, last_keys))
    return FixedIncomePeerCohort(
        cohort_id=identity,
        instrument_id=target.instrument_id,
        level=level if status == "supported" else last_level,
        keys=selected if status == "supported" else last_keys,
        peer_instrument_ids=peers if status == "supported" else last_peers,
        support=len(peers) if status == "supported" else len(last_peers),
        minimum_support=config.minimum_peer_support,
        status=status,
        reason_codes=reasons,
        execution_allowed=False,
    )


def _security_keys(
    item: FixedIncomeScreenerSecurity, config: FixedIncomeScreenerConfig
) -> dict[str, str | None]:
    years = (
        Decimal((item.maturity_date - item.return_input.valuation.settlement_date).days)
        / Decimal("365")
        if item.maturity_date is not None and item.return_input is not None
        else None
    )
    return {
        "security_type": _key(item.security_type),
        "issuer_sector": _key(item.issuer_sector),
        "country": _key(item.country),
        "currency": _key(item.currency),
        "seniority": _key(item.seniority),
        "rating": _key(item.rating),
        "coupon_type": _key(item.coupon_type),
        "maturity_bucket": _bucket(years, config.maturity_buckets_years),
        "duration_bucket": _bucket(item.duration_years, config.duration_buckets_years),
        "liquidity_bucket": _key(item.liquidity_bucket),
    }


def _same_keys(
    candidate: Mapping[str, str | None], selected: tuple[tuple[str, str], ...]
) -> bool:
    return all(candidate.get(key) == value for key, value in selected)


def _robust_percentile(score: Decimal | None, peer_scores: Sequence[Decimal]) -> Decimal | None:
    """Use a bounded midrank so a peer outlier cannot set the scale."""

    if score is None or not peer_scores:
        return None
    lower = sum(value < score for value in peer_scores)
    equal = sum(value == score for value in peer_scores)
    return Decimal(lower + equal / Decimal("2")) / Decimal(len(peer_scores))


def _bootstrap_peer_rank(
    score: Decimal | None,
    peer_scores: Sequence[Decimal],
    *,
    seed: int,
    instrument_id: str,
    samples: int,
    top_n: int,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if score is None or not peer_scores:
        return None, None, None
    derived_seed = seed + int(_hash(instrument_id)[:8], 16)
    rng = random.Random(derived_seed)
    medians: list[Decimal] = []
    top_n_hits = 0
    for _ in range(samples):
        draw = rng.choices(peer_scores, k=len(peer_scores))
        medians.append(median(draw))
        peer_rank = 1 + sum(value > score for value in draw)
        top_n_hits += peer_rank <= top_n
    stability = Decimal(top_n_hits) / Decimal(samples)
    # The interval describes the bootstrapped peer-score median, never the
    # security's uncalibrated expected-return distribution.
    return stability, _quantile(medians, Decimal("0.05")), _quantile(medians, Decimal("0.95"))


def _quantile(values: Sequence[Decimal], probability: Decimal) -> Decimal:
    ordered = sorted(values)
    index = int((Decimal(len(ordered) - 1) * probability).to_integral_value())
    return ordered[index]


def _bucket(value: Decimal | None, boundaries: tuple[Decimal, ...]) -> str | None:
    if value is None or not value.is_finite() or value < 0:
        return None
    for boundary in boundaries:
        if value <= boundary:
            return f"le_{boundary}"
    return f"gt_{boundaries[-1]}"


def _key(value: str | None) -> str | None:
    cleaned = str(value or "").strip().casefold()
    return cleaned or None


def _positive_int(value: object, field: str) -> int:
    result = _integer(value, field)
    if result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _buckets(value: object, field: str) -> tuple[Decimal, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    result = tuple(_decimal(item, field) for item in value)
    if any(item <= 0 for item in result) or tuple(sorted(set(result))) != result:
        raise ValueError(f"{field} must be strictly increasing positive values")
    return result


def _hash(value: object) -> str:
    encoded = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _jsonable(value: object) -> object:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
        return getattr(value, "value")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "FIXED_INCOME_SCREENER_CONFIG",
    "FIXED_INCOME_SCREENER_CONTRACT",
    "FixedIncomePeerCohort",
    "FixedIncomeScreenerConfig",
    "FixedIncomeScreenerError",
    "FixedIncomeScreenerRow",
    "FixedIncomeScreenerSecurity",
    "FixedIncomeScreenerSnapshot",
    "build_fixed_income_screener",
    "load_fixed_income_screener_config",
]
