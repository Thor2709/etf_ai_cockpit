"""Versioned, deterministic and non-executable strategy template evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import yaml


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
        stages = raw.get("stages")
        if not benchmark or not version or not isinstance(definition, Mapping) or not isinstance(stages, Mapping):
            raise ValueError(f"incomplete strategy template metadata: {template_id}")
        canonical = {"template_id": template_id, "version": version, "benchmark": benchmark, "definition": definition, "stages": stages}
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        declared = str(raw.get("definition_hash", "")).strip()
        if declared and declared not in {"auto", digest}:
            raise ValueError(f"strategy template hash mismatch: {template_id}")
        templates.append(StrategyTemplate(template_id, str(raw.get("name", template_id)), version, benchmark, dict(definition), {str(key): str(value) for key, value in stages.items()}, bool(raw.get("context_only", False)), False, digest))
        seen.add(template_id)
    if set(seen) != set(TEMPLATE_IDS):
        raise ValueError(f"strategy template registry missing: {sorted(set(TEMPLATE_IDS) - seen)}")
    return tuple(templates)


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
        instrument_id = str(row.get("instrument_id", row.get("id", row.get("symbol", "")))).strip()
        if not instrument_id:
            continue
        if decision_time is not None and _evidence_arrived_after(row, decision_time):
            continue
        for template in registry:
            if _template_matches(template.template_id, row):
                matches.append(TemplateMatch(instrument_id, template.template_id, template.version, template.definition_hash, template.benchmark, _match_reason(template.template_id), template.context_only, (), False))
    return tuple(matches)


def match_templates(snapshot: Iterable[Mapping[str, Any]] | pd.DataFrame, templates: Iterable[StrategyTemplate] | None = None, *, decision_time: object | None = None) -> tuple[TemplateMatch, ...]:
    return compute_template_matches(snapshot, templates, decision_time=decision_time)


def _evidence_arrived_after(row: Mapping[str, Any], decision_time: object) -> bool:
    try:
        decision = pd.Timestamp(decision_time)
    except (TypeError, ValueError):
        return True
    for field in ("known_at", "available_at"):
        value = row.get(field)
        if value in (None, ""):
            continue
        try:
            observed = pd.Timestamp(value)
        except (TypeError, ValueError):
            continue
        if pd.notna(observed) and observed > decision:
            return True
    return False


def _template_matches(template_id: str, row: Mapping[str, Any]) -> bool:
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
        return asset_type in {"etf", "fund"} and _at_least(momentum, 0.0) and _at_least(trend, 0.0)
    if template_id == "trend_following":
        return _at_least(trend, 0.0) and asset_type in {"etf", "fund", "stock", "equity"}
    if template_id == "defensive_rotation":
        return "defensive" in regime or "risk_off" in regime or "risk-off" in regime
    if template_id == "stock_quality_momentum":
        return asset_type in {"stock", "equity"} and _at_least(quality, 0.0) and _at_least(momentum, 0.0)
    if template_id == "stock_value_momentum":
        return asset_type in {"stock", "equity"} and _at_least(value, 0.0) and _at_least(momentum, 0.0)
    if template_id == "low_volatility_watchlist":
        return volatility is not None and volatility >= 0.0 and volatility <= 0.25
    if template_id == "dividend_quality_watchlist":
        return dividend is not None and dividend >= 0.0 and _at_least(quality, 0.0)
    if template_id == "news_context_watchlist":
        return bool(news)
    if template_id == "manual_custom_score_blend":
        return score is not None
    return False


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


__all__ = ["CONTEXT_ONLY_TEMPLATE_IDS", "FORBIDDEN_STRATEGY_TYPES", "STRATEGY_TEMPLATE_DESCRIPTIONS", "TEMPLATE_IDS", "StrategyTemplate", "TemplateMatch", "compute_template_matches", "load_strategy_templates", "match_templates", "strategy_template_frame", "strategy_template_labels", "template_description", "validate_strategy_authority", "write_strategy_template_frame"]
