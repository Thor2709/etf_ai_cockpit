"""Versioned, deterministic and non-executable strategy template evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import yaml

from etf_cockpit.backtest.benchmarks import momentum_weights, trend_weights
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkReferenceError,
    load_canonical_benchmark_registry,
)
from etf_cockpit.signals.quality_momentum import quality_momentum_weights


STRATEGY_TEMPLATE_DESCRIPTIONS = {
    "dual_momentum_etf": "ETF template: medium-term momentum, positive trend and acceptable risk.",
    "quality_momentum_stock": "Stock template: stock quality plus price momentum.",
    "value_momentum_stock": "Stock template: attractive valuation with at least acceptable quality and momentum.",
    "defensive_watch": "Defensive template: useful evidence exists, but risk/friction or market regime calls for caution.",
    "no_template": "No template matched. Treat the row as a general evidence review.",
}

TEMPLATE_IDS = (
    "etf_dual_momentum",
    "trend_following",
    "defensive_rotation",
    "stock_quality_momentum",
    "stock_value_momentum",
    "low_volatility_watchlist",
    "dividend_quality_watchlist",
    "news_context_watchlist",
    "manual_custom_score_blend",
)
FORBIDDEN_STRATEGY_TYPES = frozenset({"martingale", "grid", "rl", "rl_agents", "reinforcement_learning"})
CONTEXT_ONLY_TEMPLATE_IDS = frozenset({"news_context_watchlist"})
_STAGE_NAMES = ("analyse", "portfolio", "backtest", "paper", "draft_order", "canary", "bounded_automatic")


@dataclass(frozen=True)
class StrategyTemplate:
    template_id: str
    name: str
    version: str
    benchmark: str
    definition: Mapping[str, Any]
    stages: Mapping[str, str]
    context_only: bool
    execution_allowed: bool
    definition_hash: str

    @property
    def hash(self) -> str:
        return self.definition_hash


@dataclass(frozen=True)
class TemplateMatch:
    instrument_id: str
    template_id: str
    template_version: str
    definition_hash: str
    benchmark: str
    reason: str
    context_only: bool
    actions: tuple[str, ...] = ()
    execution_allowed: bool = False


def load_strategy_templates(path: Path | None = None) -> tuple[StrategyTemplate, ...]:
    """Load and validate the shipped template definitions."""

    source = path or Path(__file__).resolve().parents[3] / "configs" / "strategy_templates_v1.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("execution_allowed") is not False:
        raise ValueError("strategy template registry must be execution_allowed=false")
    rows = payload.get("templates")
    if not isinstance(rows, list):
        raise ValueError("strategy template registry has no templates")
    benchmark_ids = _canonical_benchmark_ids()
    strategy_scope = _load_strategy_scope()
    templates: list[StrategyTemplate] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("strategy template entry must be a mapping")
        template_id = str(raw.get("template_id", "")).strip()
        if not template_id or template_id in seen:
            raise ValueError(f"invalid or duplicate strategy template: {template_id}")
        if template_id in FORBIDDEN_STRATEGY_TYPES:
            raise ValueError(f"forbidden strategy type: {template_id}")
        if raw.get("execution_allowed") is not False:
            raise ValueError(f"strategy template execution authority rejected: {template_id}")
        benchmark = str(raw.get("benchmark", "")).strip()
        version = str(raw.get("version", "")).strip()
        definition = raw.get("definition")
        strategy_id = str(raw.get("strategy_id", "")).strip()
        profile_id = str(raw.get("profile_id", "")).strip()
        if not benchmark or benchmark not in benchmark_ids:
            raise ValueError(f"unknown canonical benchmark: {template_id}: {benchmark}")
        if not version or not strategy_id or not profile_id or not isinstance(definition, Mapping):
            raise ValueError(f"incomplete strategy template metadata: {template_id}")
        stages = _canonical_stages(strategy_scope, strategy_id, profile_id)
        if bool(raw.get("context_only", False)) != (profile_id == "context_only"):
            raise ValueError(f"strategy template context authority does not match canonical profile: {template_id}")
        declared_stages = raw.get("stages")
        if declared_stages is not None and declared_stages != stages:
            raise ValueError(f"strategy template stages do not match canonical policy: {template_id}")
        canonical = {
            "template_id": template_id,
            "version": version,
            "benchmark": benchmark,
            "strategy_id": strategy_id,
            "profile_id": profile_id,
            "definition": definition,
            "stages": stages,
        }
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        declared = str(raw.get("definition_hash", "")).strip()
        if declared and declared not in {"auto", digest}:
            raise ValueError(f"strategy template hash mismatch: {template_id}")
        templates.append(StrategyTemplate(template_id, str(raw.get("name", template_id)), version, benchmark, dict(definition), stages, bool(raw.get("context_only", False)), False, digest))
        seen.add(template_id)
    if set(seen) != set(TEMPLATE_IDS):
        raise ValueError(f"strategy template registry missing: {sorted(set(TEMPLATE_IDS) - seen)}")
    return tuple(templates)


def _canonical_benchmark_ids() -> set[str]:
    try:
        return {item.benchmark_id for item in load_canonical_benchmark_registry().benchmarks}
    except BenchmarkReferenceError as exc:
        raise ValueError("canonical benchmark registry is unavailable") from exc


def _load_strategy_scope() -> Mapping[str, Any]:
    source = Path(__file__).resolve().parents[3] / "configs" / "strategy_scope.yaml"
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("canonical strategy scope is unavailable") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("canonical strategy scope is malformed")
    return payload


def _canonical_stages(scope: Mapping[str, Any], strategy_id: str, profile_id: str) -> dict[str, str]:
    assignments = scope.get("profile_assignments")
    profiles = scope.get("capability_profiles")
    strategies = scope.get("strategies")
    if not isinstance(assignments, Mapping) or not isinstance(profiles, list) or not isinstance(strategies, list):
        raise ValueError("canonical strategy scope is incomplete")
    strategy_ids = {
        str(row.get("strategy_id", ""))
        for row in strategies
        if isinstance(row, Mapping)
    }
    if strategy_id not in strategy_ids:
        raise ValueError(f"unknown canonical strategy: {strategy_id}")
    if str(assignments.get(strategy_id, "")) != profile_id:
        raise ValueError(f"strategy profile assignment mismatch: {strategy_id}")
    profile = next((row for row in profiles if isinstance(row, Mapping) and row.get("profile_id") == profile_id), None)
    if not isinstance(profile, Mapping) or not isinstance(profile.get("cells"), Mapping):
        raise ValueError(f"unknown canonical strategy profile: {profile_id}")
    cells = profile["cells"]
    stages: dict[str, str] = {}
    for stage in _STAGE_NAMES:
        cell = cells.get(stage)
        if not isinstance(cell, Mapping) or not isinstance(cell.get("state"), str):
            raise ValueError(f"canonical strategy profile is missing stage: {profile_id}:{stage}")
        stages[stage] = str(cell["state"])
    return stages


def validate_strategy_authority(strategy_type: str, *, execution_allowed: bool = False) -> None:
    """Reject forbidden strategy classes and every execution authority request."""

    normalised = str(strategy_type).strip().casefold().replace("-", "_")
    if normalised in FORBIDDEN_STRATEGY_TYPES:
        raise ValueError(f"forbidden strategy type rejected: {strategy_type}")
    if execution_allowed:
        raise ValueError("strategy execution authority rejected: execution_allowed must remain false")


def compute_template_matches(snapshot: Iterable[Mapping[str, Any]] | pd.DataFrame, templates: Iterable[StrategyTemplate] | None = None, *, decision_time: object | None = None) -> tuple[TemplateMatch, ...]:
    """Compute stable review matches from a fixed, already point-in-time snapshot."""

    registry = tuple(templates or load_strategy_templates())
    rows = snapshot.to_dict("records") if isinstance(snapshot, pd.DataFrame) else list(snapshot)
    matches: list[TemplateMatch] = []
    for row in rows:
        if not isinstance(row, Mapping) or not _evidence_available_at_decision(row, decision_time):
            continue
        instrument_id = str(row.get("instrument_id", row.get("id", row.get("symbol", "")))).strip()
        if not instrument_id:
            continue
        for template in registry:
            if _template_matches(template.template_id, row, instrument_id):
                matches.append(TemplateMatch(instrument_id, template.template_id, template.version, template.definition_hash, template.benchmark, _match_reason(template.template_id), template.context_only, (), False))
    return tuple(matches)


def match_templates(snapshot: Iterable[Mapping[str, Any]] | pd.DataFrame, templates: Iterable[StrategyTemplate] | None = None, *, decision_time: object | None = None) -> tuple[TemplateMatch, ...]:
    return compute_template_matches(snapshot, templates, decision_time=decision_time)


def _evidence_available_at_decision(row: Mapping[str, Any], decision_time: object | None) -> bool:
    timestamps: list[pd.Timestamp] = []
    for field in ("known_at", "available_at"):
        value = row.get(field)
        if value in (None, ""):
            return False
        try:
            observed = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError):
            return False
        if pd.isna(observed):
            return False
        observed = observed.tz_localize("UTC") if observed.tzinfo is None else observed.tz_convert("UTC")
        timestamps.append(observed)
    if decision_time is None:
        return True
    try:
        decision = pd.Timestamp(decision_time)
    except (TypeError, ValueError, OverflowError):
        return False
    if pd.isna(decision):
        return False
    decision = decision.tz_localize("UTC") if decision.tzinfo is None else decision.tz_convert("UTC")
    return all(observed <= decision for observed in timestamps)


def _template_matches(template_id: str, row: Mapping[str, Any], instrument_id: str) -> bool:
    asset_type = str(row.get("asset_type", row.get("asset_class", ""))).casefold()
    score = _number(row.get("score", row.get("evidence_score")))
    momentum = _number(row.get("momentum"))
    trend = _number(row.get("trend"))
    quality = _number(row.get("quality", row.get("stock_quality")))
    value = _number(row.get("value", row.get("stock_value")))
    volatility = _number(row.get("volatility", row.get("volatility_annualised")))
    dividend = _number(row.get("dividend_yield"))
    news = row.get("news") or row.get("news_context") or row.get("context")
    regime = str(row.get("regime", row.get("market_regime", ""))).casefold()
    if template_id == "etf_dual_momentum":
        return asset_type in {"etf", "fund"} and _canonical_momentum_available(row, instrument_id, momentum) and _canonical_trend_available(row, instrument_id, trend)
    if template_id == "trend_following":
        return asset_type in {"etf", "fund", "stock", "equity"} and _canonical_trend_available(row, instrument_id, trend)
    if template_id == "defensive_rotation":
        return "defensive" in regime or "risk_off" in regime or "risk-off" in regime
    if template_id == "stock_quality_momentum":
        return asset_type in {"stock", "equity"} and _canonical_quality_momentum_available(row, instrument_id, quality, momentum)
    if template_id == "stock_value_momentum":
        return asset_type in {"stock", "equity"} and _canonical_momentum_available(row, instrument_id, momentum) and _positive(value)
    if template_id == "low_volatility_watchlist":
        return _positive(volatility) and volatility <= 0.25
    if template_id == "dividend_quality_watchlist":
        return _positive(dividend) and _positive(quality)
    if template_id == "news_context_watchlist":
        return bool(news)
    if template_id == "manual_custom_score_blend":
        return _positive(score)
    return False


def _canonical_momentum_available(row: Mapping[str, Any], instrument_id: str, fallback: float | None) -> bool:
    history = row.get("price_history")
    if isinstance(history, pd.DataFrame):
        if len(history) < 181:
            return False
        try:
            weights = momentum_weights(history, [instrument_id])
        except (TypeError, ValueError, KeyError):
            return False
        return _positive(weights.get(instrument_id))
    if str(row.get("momentum_status", "")).casefold() not in {"available", "ok"}:
        return False
    return _positive(row.get("momentum_score", fallback))


def _canonical_trend_available(row: Mapping[str, Any], instrument_id: str, fallback: float | None) -> bool:
    history = row.get("price_history")
    config = row.get("config")
    if isinstance(history, pd.DataFrame) and config is not None:
        if len(history) < 200:
            return False
        try:
            weights = trend_weights(config, history, [instrument_id])
        except (TypeError, ValueError, KeyError, AttributeError):
            return False
        return _positive(weights.get(instrument_id))
    if str(row.get("trend_status", "")).casefold() not in {"available", "ok"}:
        return False
    return _positive(row.get("trend_score", fallback))


def _canonical_quality_momentum_available(row: Mapping[str, Any], instrument_id: str, quality: float | None, momentum: float | None) -> bool:
    evidence = row.get("quality_momentum_evidence")
    if isinstance(evidence, pd.DataFrame):
        if "status" not in evidence.columns or not bool((evidence["instrument_id"].astype(str) == instrument_id).any()):
            return False
        try:
            weights = quality_momentum_weights(evidence, [instrument_id], mode="quality_momentum")
        except (TypeError, ValueError, KeyError):
            return False
        return _positive(weights.get(instrument_id))
    if str(row.get("quality_momentum_status", "")).casefold() not in {"available", "ok"}:
        return False
    return _positive(row.get("quality_momentum_score", quality)) and _positive(momentum)


def _match_reason(template_id: str) -> str:
    return {
        "etf_dual_momentum": "ETF momentum and trend evidence are present in the fixed snapshot.",
        "trend_following": "Trend evidence is present in the fixed snapshot.",
        "defensive_rotation": "Defensive regime evidence is present; review context only.",
        "stock_quality_momentum": "Stock quality and momentum evidence are present.",
        "stock_value_momentum": "Stock value and momentum evidence are present.",
        "low_volatility_watchlist": "Volatility evidence is within the watchlist bound.",
        "dividend_quality_watchlist": "Dividend and quality evidence are present.",
        "news_context_watchlist": "Source-linked news/context evidence is present; no trade action.",
        "manual_custom_score_blend": "A user-provided score is present for manual review.",
    }[template_id]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def strategy_template_labels(*, asset_type: str, evidence_score: float | None, risk_friction_score: float | None, component_scores: dict[str, float | None], regime_label: str) -> list[str]:
    labels: list[str] = []
    momentum = component_scores.get("momentum")
    trend = component_scores.get("trend")
    risk = component_scores.get("risk")
    relative = component_scores.get("relative_strength")
    value = component_scores.get("stock_value")
    quality = component_scores.get("stock_quality")
    regime_defensive = "defensive" in regime_label.lower()
    if asset_type == "ETF" and _at_least(momentum, 6.5) and _at_least(trend, 6.0) and _at_least(relative, 5.5) and _at_least(risk, 5.0):
        labels.append("dual_momentum_etf")
    elif asset_type != "ETF":
        if _at_least(quality, 6.5) and _at_least(momentum, 6.0) and _at_least(trend, 5.5):
            labels.append("quality_momentum_stock")
        if _at_least(value, 6.5) and _at_least(quality, 5.0) and _at_least(momentum, 5.5):
            labels.append("value_momentum_stock")
    if (evidence_score is not None and evidence_score >= 5.0) and (regime_defensive or (risk_friction_score is not None and risk_friction_score < 5.0)):
        labels.append("defensive_watch")
    return labels or ["no_template"]


def strategy_template_frame(scoreboard: pd.DataFrame) -> pd.DataFrame:
    columns = ["instrument_id", "symbol", "asset_type", "evidence_score_10", "risk_friction_10", "strategy_template_label", "strategy_template_descriptions", "market_regime_label", "benchmark_id", "benchmark_period_days", "benchmark_return", "instrument_period_return", "cash_return", "excess_over_cash", "cash_comparison_status", "gross_expected_return", "q10_expected_return", "q50_expected_return", "q90_expected_return", "net_q10_expected_return", "net_expected_return", "net_q90_expected_return", "expected_return_horizon_days", "expected_return_order_value_eur", "expected_return_cost_bps", "expected_return_cost_eur", "expected_return_cost_ratio", "expected_return_distribution_version", "expected_return_source_id", "expected_return_source_dataset", "expected_return_source_digest", "expected_return_as_of", "expected_return_known_at", "expected_return_trust", "expected_return_source_bound", "sector_theme_warning", "crowding_top_ranked_concentration", "crowding_top_ranked_theme_concentration", "crowding_top_ranked_theme_warning", "evidence_maturity_state", "evidence_sample_days", "backtest_validity", "execution_allowed"]
    for alternative in ("basket", "benchmark", "cash", "no_action"):
        columns.extend([f"monthly_{alternative}_{suffix}" for suffix in ("return", "version", "source_id", "source_dataset", "source_digest", "as_of", "known_at", "horizon_days", "reference_id", "reference_version", "reference_content_hash", "trust", "source_bound")])
    columns.extend(("monthly_no_action_constituent_id", "monthly_no_action_weight"))
    if scoreboard.empty:
        return pd.DataFrame(columns=columns)
    result = scoreboard[[column for column in columns if column in scoreboard.columns]].copy()
    if "execution_allowed" in result.columns:
        result["execution_allowed"] = False
    return result


def write_strategy_template_frame(scoreboard: pd.DataFrame, path) -> None:
    strategy_template_frame(scoreboard).to_csv(path, index=False)


def template_description(labels: list[str]) -> str:
    return " | ".join(STRATEGY_TEMPLATE_DESCRIPTIONS.get(label, label) for label in labels)


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and float(value) >= threshold


def _positive(value: Any) -> bool:
    number = _number(value)
    return number is not None and number > 0.0


__all__ = ["CONTEXT_ONLY_TEMPLATE_IDS", "FORBIDDEN_STRATEGY_TYPES", "STRATEGY_TEMPLATE_DESCRIPTIONS", "TEMPLATE_IDS", "StrategyTemplate", "TemplateMatch", "compute_template_matches", "load_strategy_templates", "match_templates", "strategy_template_frame", "strategy_template_labels", "template_description", "validate_strategy_authority", "write_strategy_template_frame"]
