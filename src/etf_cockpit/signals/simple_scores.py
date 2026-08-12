from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
import hashlib
import json
from math import isfinite, tanh
from numbers import Integral
from pathlib import Path
import re
from typing import Iterable, Literal

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import BACKTESTS_DIR, DERIVED_DIR, FORECASTS_DIR, RAW_DIR, REPORTS_DIR, ROOT
from etf_cockpit.core.types import SignalResult
from etf_cockpit.data.classification import classification_score_state
from etf_cockpit.data.macro_warehouse import MacroWarehouse, load_risk_free_proxy_mappings
from etf_cockpit.data.score_history import project_classification_score_frame
from etf_cockpit.governance.gate_policy import resolve_authority
from etf_cockpit.data.reference_data import load_reference_dataset
from etf_cockpit.data.news_context import NEWS_CLEAN_PATH, load_news_items
from etf_cockpit.data.universe_store import support_decision
from etf_cockpit.data.yfinance_provider import yfinance_symbol_map_from_config
from etf_cockpit.data.universe_store import load_universe
from etf_cockpit.features.crowding import ClusterReport, build_correlation_clusters
from etf_cockpit.features.cash_comparison import (
    adjusted_endpoint_available_at,
    validate_cash_comparison_result,
    validated_adjusted_price_frame,
)
from etf_cockpit.features.regime import build_benchmark_attribution_lookup, build_market_regime, build_portfolio_fit_lookup
from etf_cockpit.models.calibration import calibration_lookup, evaluate_forecast_calibration, load_forecast_history
from etf_cockpit.models.forecast_scores import (
    filter_forecasts_for_universe,
    forecast_component_maps,
    forecast_return_distributions,
    forecast_score_details,
    load_latest_forecasts,
)
from etf_cockpit.portfolio.costs import estimate_execution_cost
from etf_cockpit.signals.research_states import (
    ALLOWED_EVIDENCE_SOURCE_IDS,
    AnalysisStatus,
    AuthorityDecision,
    GateResult,
    InternalSignalIntent,
    PortfolioReviewState,
    ResearchState,
    internal_intent_for_legacy_action,
    normalise_analysis_status,
    public_authority_payload,
    research_state_for_legacy_action,
)
from etf_cockpit.signals.strategy_templates import strategy_template_frame, strategy_template_labels, template_description
from etf_cockpit.signals.friction_edge import estimate_friction_adjusted_return, estimate_friction_edge
from etf_cockpit.signals.canonical_scoring import CanonicalScore, canonical_score_from_simple_components


SCORE_LEGEND = (
    "8-10: strong positive evidence",
    "6-7.9: positive/watchlist evidence",
    "4-5.9: mixed/hold evidence",
    "0-3.9: weak or negative evidence",
)

PRIMARY_TIER_LABEL = "Primary tier"
SECONDARY_TIER_LABEL = "Secondary tier"
SPAREBANKEN_TIER_LABEL = "Sparebanken"
PRIMARY_ETF_GROUP_LABEL = "Primary tier - ETFs"
PRIMARY_STOCK_GROUP_LABEL = "Primary tier - stocks/equity certificates"
SECONDARY_ETF_GROUP_LABEL = "Secondary tier - ETFs"
SECONDARY_STOCK_GROUP_LABEL = "Secondary tier - stocks/equity certificates"
SPAREBANKEN_GROUP_LABEL = "Sparebanken - Norwegian savings-bank equity-certificate issuers"
PENDING_WORKFLOW_REASON = "Run Refresh yfinance data, then Run algorithms, then Run forecasting models."
CASH_MACRO_ROOT = ROOT
_CASH_COMPARISON_RETURN_WINDOW = 120

ETF_EVIDENCE_WEIGHTS = {
    "momentum": 0.22,
    "trend": 0.18,
    "relative_strength": 0.14,
    "risk": 0.14,
    "liquidity_cost": 0.10,
    "etf_exposure": 0.10,
    "baseline": 0.02,
    "timesfm": 0.015,
    "toto": 0.015,
}

STOCK_EVIDENCE_WEIGHTS = {
    "momentum": 0.18,
    "trend": 0.13,
    "relative_strength": 0.12,
    "risk": 0.12,
    "liquidity_cost": 0.10,
    "stock_value": 0.12,
    "stock_quality": 0.13,
    "analyst_revision": 0.05,
    "baseline": 0.02,
    "timesfm": 0.015,
    "toto": 0.015,
}

COMPONENT_LABELS = {
    "data_quality": "Data quality",
    "momentum": "Momentum algorithm",
    "trend": "Trend algorithm",
    "risk": "Risk/volatility algorithm",
    "relative_strength": "Relative strength algorithm",
    "liquidity_cost": "Liquidity/cost algorithm",
    "etf_exposure": "ETF exposure algorithm",
    "stock_value": "Stock value algorithm",
    "stock_quality": "Stock quality algorithm",
    "analyst_revision": "Analyst/revision evidence",
    "baseline": "Baseline forecast",
    "timesfm": "TimesFM forecast",
    "toto": "Toto forecast",
}

COMPONENT_EXPLANATIONS = {
    "data_quality": "Checks yfinance freshness, adjusted-price availability, history length and obvious data gaps.",
    "momentum": "Measures recent 1-9 month price strength from yfinance adjusted prices.",
    "trend": "Checks whether price behaviour is above or below its medium and long moving averages.",
    "risk": "Scores volatility and drawdown. Smoother prices and smaller drawdowns score higher.",
    "relative_strength": "Compares the instrument with its peer set. A high score means it is leading nearby alternatives.",
    "liquidity_cost": "Estimates whether the instrument is liquid enough that spread, slippage and commission do not overwhelm the edge.",
    "etf_exposure": "Uses available Yahoo fund holdings to assess concentration and diversification. Missing fund data stays N/A.",
    "stock_value": "Scores valuation using yfinance-derived ratios where available. Missing fundamentals stay N/A.",
    "stock_quality": "Scores profitability, leverage and cash-flow quality where yfinance fundamentals are available.",
    "analyst_revision": "Adds low-authority analyst estimate/revision context when Yahoo exposes usable data.",
    "baseline": "Uses a simple statistical forecast from recent adjusted-price history.",
    "timesfm": "Uses the local TimesFM time-series model when a valid forecast row exists.",
    "toto": "Uses the local Toto probabilistic model when a valid forecast row exists.",
}

GOOD_SCORE_TEXT = {
    "data_quality": "Good score: fresh adjusted yfinance data with enough history and no blocking gaps.",
    "momentum": "Good score: price momentum is positive across several months.",
    "trend": "Good score: price is above medium/long trend filters.",
    "risk": "Good score: recent volatility and drawdown are controlled.",
    "relative_strength": "Good score: it is outperforming the configured or candidate peer set.",
    "liquidity_cost": "Good score: average traded value is healthy and estimated costs are small relative to the signal.",
    "etf_exposure": "Good score: holdings are available and no single holding/top-10 group dominates the ETF.",
    "stock_value": "Good score: valuation is attractive relative to available stock evidence.",
    "stock_quality": "Good score: profitability is strong, leverage is acceptable and cash conversion is healthy.",
    "analyst_revision": "Good score: analyst revisions or estimates are improving. This is always low-authority.",
    "baseline": "Good score: the baseline forecast expects a positive risk-adjusted return.",
    "timesfm": "Good score: TimesFM generated a valid positive forecast.",
    "toto": "Good score: Toto generated a valid favourable forecast distribution.",
}

COMPONENT_SOURCE_IDS = {
    "data_quality": "yfinance:prices",
    "momentum": "yfinance:prices",
    "trend": "yfinance:prices",
    "risk": "yfinance:prices",
    "relative_strength": "yfinance:prices",
    "liquidity_cost": "yfinance:prices",
    "etf_exposure": "yfinance:holdings",
    "stock_value": "yfinance:fundamentals",
    "stock_quality": "yfinance:fundamentals",
    "analyst_revision": "yfinance:analyst_estimates",
    "baseline": "model:baseline",
    "timesfm": "model:timesfm",
    "toto": "model:toto",
}
KNOWN_SCORE_SOURCE_IDS = frozenset(COMPONENT_SOURCE_IDS.values())


@dataclass(frozen=True)
class SimpleScoreComponent:
    key: str
    label: str
    score_10: float | None
    raw_score: float | None
    status: str
    explanation: str
    good_score: str
    why: str
    authority: str = "medium"
    score_role: str = "evidence"
    source_id: str | None = None
    source_authority: str | None = None
    as_of_date: str | None = None
    freshness_status: str | None = None
    conflict_id: str | None = None
    evidence_quality: float | str | None = None

    def __post_init__(self) -> None:
        if self.source_id is None:
            object.__setattr__(self, "source_id", COMPONENT_SOURCE_IDS.get(self.key))
        if self.source_authority is None:
            dataset = str(self.source_id or "").split(":", 1)[0].casefold()
            authority = {
                "sec_edgar": "official_regulator",
                "esef": "official_filing",
                "issuer_document": "issuer_document",
                "priips_kid": "issuer_document",
                "index_methodology": "issuer_document",
                "etf_disclosures": "issuer_document",
                "yfinance": "vendor_unofficial",
                "fmp": "vendor_unofficial",
                "eodhd": "vendor_unofficial",
                "model": "model_advisory",
                "community": "manual_context",
                "news": "manual_context",
                "rss": "manual_context",
                "candle": "manual_context",
            }.get(dataset, "unknown" if not dataset else "vendor_unofficial")
            object.__setattr__(self, "source_authority", authority)

    @property
    def score_eligible(self) -> bool:
        return _component_is_score_eligible(self)

    @property
    def provenance(self) -> dict[str, object]:
        return {
            "source_id": self.source_id or "",
            "source_authority": self.source_authority or "unknown",
            "as_of_date": self.as_of_date,
            "freshness_status": self.freshness_status or "unknown",
            "conflict_id": self.conflict_id,
            "evidence_quality": self.evidence_quality,
            "score_eligible": self.score_eligible,
            "executable_authority": False,
        }


@dataclass(frozen=True)
class SimpleInstrumentScore:
    instrument_key: str
    display_id: str
    source_group: str
    asset_type: str
    name: str
    yahoo_symbol: str
    latest_date: str
    latest_price: float | None
    final_score_10: float | None
    decision: str
    one_line_reason: str
    components: list[SimpleScoreComponent]
    warnings: list[str]
    instrument_currency: str | None = None
    isin: str | None = None
    analysis_tier: str = ""
    data_policy: str = ""
    evidence_score_10: float | None = None
    evidence_quality_10: float | None = None
    risk_friction_10: float | None = None
    final_label: str = "manual_review"
    final_action: str = "manual_review"
    model_authority_label: str = "Model evidence unavailable"
    backtest_trust_label: str = "Backtest trust not yet evaluated"
    backtest_trust_score_10: float | None = None
    model_calibration_label: str = "Calibration pending"
    model_calibration_score_10: float | None = None
    market_regime_label: str = "Regime unavailable"
    market_regime_score_10: float | None = None
    portfolio_fit_label: str = "Portfolio fit not evaluated"
    portfolio_fit_score_10: float | None = None
    strategy_templates: list[str] | None = None
    strategy_template_label: str = "no_template"
    strategy_template_descriptions: str = "No template matched. Treat the row as a general evidence review."
    evidence_sample_days: int | None = None
    evidence_maturity_state: str = "unknown"
    evidence_maturity_label: str = "Evidence maturity unknown"
    too_good_to_be_true_warning: str = "No sanity warning"
    evidence_sanity_warnings: list[str] | None = None
    evidence_warning_count: int = 0
    benchmark_id: str | None = None
    benchmark_period_days: int | None = None
    benchmark_return: float | None = None
    instrument_period_return: float | None = None
    benchmark_beta: float | None = None
    benchmark_correlation: float | None = None
    alpha_proxy: float | None = None
    alpha_t_stat: float | None = None
    benchmark_attribution_label: str = "Benchmark attribution pending"
    cash_instrument_return: float | None = None
    cash_return: float | None = None
    excess_over_cash: float | None = None
    cash_instrument_id: str | None = None
    cash_currency: str | None = None
    cash_unit: str | None = None
    cash_dataset_kind: str | None = None
    cash_start_date: str | None = None
    cash_end_date: str | None = None
    cash_horizon_years: float | None = None
    cash_rate: float | None = None
    cash_vintage: str | None = None
    cash_comparison_status: str = "unavailable"
    cash_comparison_reason: str | None = "Cash comparison unavailable; no caller-provided mapping result."
    cash_source_id: str | None = None
    cash_source_authority: str | None = None
    cash_source_checksum: str | None = None
    cash_source_terms: str | None = None
    cash_methodology: str | None = None
    cash_mapping_methodology: str | None = None
    cash_day_count: str | None = None
    cash_compounding: str | None = None
    cash_reinvestment: str | None = None
    cash_effective_at: str | None = None
    cash_published_at: str | None = None
    cash_available_at: str | None = None
    cash_curve_id: str | None = None
    cash_curve_version: str | None = None
    cash_curve_revision: int | None = None
    cash_curve_type: str | None = None
    cash_extrapolation_allowed: bool | None = None
    cash_fallback: bool | None = None
    cash_fallback_from: str | None = None
    cash_interpolation: str | None = None
    cash_freshness: str | None = None
    cash_freshness_status: str | None = None
    cash_decision_time: str | None = None
    cash_knowledge_cutoff: str | None = None
    inflation_context: object = None
    sector_theme_warning: str = "Sector/theme exposure not evaluated"
    backtest_validity: str = "not_evaluated"
    model_contamination_risk: str = "not_evaluated"
    model_authority_reason: str = "Model authority not evaluated"
    calibration_required: bool = True
    rank: int | None = None
    score_rank: int | None = None
    model_versions_used: dict[str, str] | None = None
    forecast_status: str = "unavailable"
    news_inventory: int | None = None
    gross_expected_edge_bps: float | None = None
    estimated_total_cost_bps: float | None = None
    net_expected_edge_bps: float | None = None
    edge_to_cost_ratio: float | None = None
    cost_stress_scenario: str = "not_evaluated"
    crowding_cluster_id: str | None = None
    crowding_cluster_label: str = "Correlation clustering unavailable"
    crowding_warning: str = "correlation_clustering_unavailable"
    crowding_average_peer_correlation: float | None = None
    crowding_sample_size: int | None = None
    crowding_as_of: str | None = None
    crowding_source_dataset: str = "adjusted_price_returns"
    crowding_pair_sample_size: int | None = None
    crowding_cluster_weight: float | None = None
    crowding_cluster_risk_contribution: float | None = None
    crowding_ranking_coverage: float | None = None
    crowding_top_ranked_concentration: float | None = None
    crowding_top_ranked_theme_concentration: float | None = None
    crowding_top_ranked_theme_warning: str = "no_theme_concentration_warning"
    sector_return: float | None = None
    sector_relative_return: float | None = None
    sector_beta: float | None = None
    sector_correlation: float | None = None
    sector_alpha_proxy: float | None = None
    sector_attribution_status: str = "N/A"
    attribution_sample_size: int | None = None
    attribution_as_of: str | None = None
    attribution_source_dataset: str = "adjusted_price_returns"
    theme_return: float | None = None
    theme_relative_return: float | None = None
    theme_beta: float | None = None
    theme_correlation: float | None = None
    theme_alpha_proxy: float | None = None
    theme_attribution_status: str = "N/A"
    theme_sample_size: int | None = None
    friction_status: str = "unavailable"
    friction_reason: str = "Friction-adjusted edge unavailable."
    gross_expected_return: float | None = None
    q10_expected_return: float | None = None
    q50_expected_return: float | None = None
    q90_expected_return: float | None = None
    expected_return_horizon_days: int | None = None
    net_q10_expected_return: float | None = None
    net_expected_return: float | None = None
    net_q90_expected_return: float | None = None
    expected_return_order_value_eur: float | None = None
    expected_return_cost_bps: float | None = None
    expected_return_cost_eur: float | None = None
    expected_return_cost_ratio: float | None = None
    expected_return_distribution_version: str = "expected-return-distribution.v1"
    expected_return_source_dataset: str = "forecast_return_distribution"
    # v2 public authority fields.  ``final_action`` is retained solely as an
    # internal compatibility seam and is omitted by ``to_v2_dict``.
    research_state: ResearchState = ResearchState.MANUAL_REVIEW
    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
    analysis_status: AnalysisStatus = "unavailable"
    research_promotion_allowed: bool = False
    portfolio_review_allowed: bool = False
    execution_allowed: Literal[False] = False
    legacy_action: str | None = None
    internal_intent: InternalSignalIntent = InternalSignalIntent.NONE
    migration_version: str = "2.0"
    gate_policy_version: str = "unavailable"
    gate_policy_checksum: str = "unavailable"
    schema_version: str = "2.0"
    authority_decision: AuthorityDecision | None = None
    canonical_score: CanonicalScore | None = None
    classification_version_id: str = "unavailable"
    classification_invalidation_hash: str = "unavailable"
    classification_dependency_status: str = "legacy_unbound"

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "research_state", ResearchState(str(self.research_state)))
        except ValueError:
            object.__setattr__(self, "research_state", ResearchState.MANUAL_REVIEW)
        try:
            object.__setattr__(self, "portfolio_review_state", PortfolioReviewState(str(self.portfolio_review_state)))
        except ValueError:
            object.__setattr__(self, "portfolio_review_state", PortfolioReviewState.NOT_APPLICABLE)
        if self.legacy_action is None:
            object.__setattr__(self, "legacy_action", str(self.final_action).strip() or None)
        if self.research_state is ResearchState.MANUAL_REVIEW:
            object.__setattr__(self, "research_state", research_state_for_legacy_action(self.final_action))
        if self.internal_intent is InternalSignalIntent.NONE:
            object.__setattr__(self, "internal_intent", internal_intent_for_legacy_action(self.final_action))
        raw_analysis_status = str(self.analysis_status or "").strip().casefold()
        valid_analysis_status = raw_analysis_status in {"complete", "partial", "unavailable"}
        object.__setattr__(self, "analysis_status", normalise_analysis_status(raw_analysis_status))
        if self.authority_decision is not None:
            decision = self.authority_decision
            object.__setattr__(self, "research_state", decision.research_state)
            object.__setattr__(self, "portfolio_review_state", decision.portfolio_review_state)
            object.__setattr__(self, "analysis_status", decision.analysis_status)
            object.__setattr__(self, "research_promotion_allowed", decision.research_promotion_allowed)
            object.__setattr__(self, "portfolio_review_allowed", decision.portfolio_review_allowed)
            object.__setattr__(self, "gate_policy_version", decision.gate_policy_version)
            object.__setattr__(self, "gate_policy_checksum", decision.gate_policy_checksum)
        else:
            # Direct compatibility construction remains fail-closed.
            object.__setattr__(self, "research_promotion_allowed", False)
            object.__setattr__(self, "portfolio_review_allowed", False)
        if valid_analysis_status and self.analysis_status == "unavailable":
            if self.final_score_10 is None:
                derived: AnalysisStatus = "unavailable"
            elif self.warnings:
                derived = "partial"
            else:
                derived = "complete"
            object.__setattr__(self, "analysis_status", derived)
        cash_fields = tuple(
            field_name
            for field_name in self.__dataclass_fields__
            if field_name.startswith("cash_")
        ) + ("excess_over_cash",)
        cash_payload = {
            (
                "cash_return"
                if field_name == "cash_return"
                else field_name[5:] if field_name.startswith("cash_") else field_name
            ): getattr(self, field_name)
            for field_name in cash_fields
        }
        cash_payload["status"] = cash_payload.pop(
            "comparison_status", self.cash_comparison_status
        )
        cash_payload["reason"] = cash_payload.pop(
            "comparison_reason", self.cash_comparison_reason
        )
        cash_payload["execution_allowed"] = False
        status_value = cash_payload["status"]
        raw_status = status_value if isinstance(status_value, str) else "unavailable"
        expected_currency = (
            self.instrument_currency.strip().upper()
            if isinstance(self.instrument_currency, str)
            else ""
        )
        if raw_status == "available" and (
            len(expected_currency) != 3 or not expected_currency.isalpha()
        ):
            expected_currency = "__invalid_instrument_currency__"
        validated_cash = validate_cash_comparison_result(
            cash_payload,
            expected_currency=expected_currency if raw_status == "available" else None,
            expected_instrument_id=self.display_id if raw_status == "available" else None,
        )
        if validated_cash.status != "available":
            for field_name in cash_fields:
                if field_name == "cash_comparison_status":
                    object.__setattr__(self, field_name, "unavailable")
                elif field_name == "cash_comparison_reason":
                    object.__setattr__(
                        self,
                        field_name,
                        validated_cash.reason
                        or "Cash comparison unavailable; invalid direct score evidence.",
                    )
                else:
                    object.__setattr__(self, field_name, None)
            object.__setattr__(self, "inflation_context", None)
        object.__setattr__(self, "execution_allowed", False)

    def to_v2_dict(self) -> dict[str, object]:
        payload = public_authority_payload(
            research_state=self.research_state,
            portfolio_review_state=self.portfolio_review_state,
            analysis_status=self.analysis_status,
            research_promotion_allowed=self.research_promotion_allowed,
            portfolio_review_allowed=self.portfolio_review_allowed,
            legacy_action=self.legacy_action,
            migration_version=self.migration_version,
            gate_policy_version=self.gate_policy_version,
            gate_policy_checksum=self.gate_policy_checksum,
            authority_decision=self.authority_decision,
        )
        if self.canonical_score is not None:
            payload["canonical_score"] = self.canonical_score.as_dict()
        return payload

    def to_public_dict(self) -> dict[str, object]:
        return self.to_v2_dict()

    @property
    def valid_component_count(self) -> int:
        return sum(1 for component in self.components if component.score_10 is not None)

    @property
    def total_component_count(self) -> int:
        return len(self.components)


@dataclass(frozen=True)
class SimpleScoreGroup:
    key: str
    label: str
    scores: list[SimpleInstrumentScore]


SCORE_GROUP_ORDER = (
    "primary_etf",
    "primary_stock",
    "secondary_etf",
    "secondary_stock",
    "sparebanken",
)

SCORE_GROUP_LABELS = {
    "primary_etf": PRIMARY_ETF_GROUP_LABEL,
    "primary_stock": PRIMARY_STOCK_GROUP_LABEL,
    "secondary_etf": SECONDARY_ETF_GROUP_LABEL,
    "secondary_stock": SECONDARY_STOCK_GROUP_LABEL,
    "sparebanken": SPAREBANKEN_GROUP_LABEL,
}


def source_group_for_analysis_tier(analysis_tier: object) -> str:
    tier = str(analysis_tier or "").strip().lower()
    if tier == "sparebanken":
        return SPAREBANKEN_TIER_LABEL
    if tier == "primary":
        return PRIMARY_TIER_LABEL
    return SECONDARY_TIER_LABEL


def score_group_key(score: SimpleInstrumentScore) -> str:
    tier = str(score.analysis_tier or "").strip().lower()
    source_group = str(score.source_group or "").strip().lower()
    if tier == "sparebanken" or source_group == SPAREBANKEN_TIER_LABEL.lower():
        return "sparebanken"
    asset_bucket = "etf" if score.asset_type == "ETF" else "stock"
    tier_bucket = "primary" if tier == "primary" or source_group == PRIMARY_TIER_LABEL.lower() else "secondary"
    return f"{tier_bucket}_{asset_bucket}"


def group_simple_scores(scores: list[SimpleInstrumentScore]) -> list[SimpleScoreGroup]:
    grouped: dict[str, list[SimpleInstrumentScore]] = {key: [] for key in SCORE_GROUP_ORDER}
    for score in scores:
        grouped.setdefault(score_group_key(score), []).append(score)
    return [SimpleScoreGroup(key=key, label=SCORE_GROUP_LABELS[key], scores=grouped.get(key, [])) for key in SCORE_GROUP_ORDER]


def raw_to_score_10(raw_score: float | int | None) -> float | None:
    if raw_score is None:
        return None
    try:
        value = float(raw_score)
    except Exception:
        return None
    if not isfinite(value):
        return None
    return round((_clamp(value) + 1.0) * 5.0, 1)


def decision_from_score(score_10: float | None) -> str:
    if score_10 is None:
        return "Manual Review"
    if score_10 >= 8.0:
        return "Strong Evidence Candidate"
    if score_10 >= 6.5:
        return "Positive Evidence Candidate"
    if score_10 >= 5.0:
        return "Watchlist"
    if score_10 >= 4.0:
        return "Hold Context"
    return "Weak Evidence Review"


def combine_component_scores(
    components: Iterable[SimpleScoreComponent],
    weights: dict[str, float] | None = None,
) -> tuple[float | None, float | None]:
    weight_map = weights or ETF_EVIDENCE_WEIGHTS
    weighted = 0.0
    total_weight = 0.0
    for component in components:
        if not _component_is_score_eligible(component):
            continue
        weight = float(weight_map.get(component.key, 0.0))
        if weight <= 0:
            continue
        weighted += _clamp(component.raw_score) * weight
        total_weight += weight
    if total_weight <= 0:
        return None, None
    raw = weighted / total_weight
    return round(raw, 4), raw_to_score_10(raw)


def _component_is_score_eligible(component: SimpleScoreComponent) -> bool:
    source_id = str(component.source_id or "").strip()
    status = str(component.status or "").strip().lower()
    source_dataset = source_id.split(":", 1)[0].lower() if source_id else ""
    as_of_date = str(component.as_of_date or "").strip()
    freshness_status = str(component.freshness_status or "").strip().lower()
    authority = str(component.source_authority or "").strip().lower()
    allowed_datasets = {
        "yfinance",
        "sec_edgar",
        "esef",
        "issuer_document",
        "priips_kid",
        "index_methodology",
        "etf_disclosures",
        "fmp",
        "eodhd",
        "alphavantage",
        "stooq",
    }
    return (
        component.raw_score is not None
        and component.score_10 is not None
        and bool(source_id)
        and (source_id in KNOWN_SCORE_SOURCE_IDS or source_dataset in allowed_datasets)
        and status == "ok"
        and source_dataset not in {"model", "community", "news", "rss", "candle"}
        and authority not in {"model_advisory", "manual_context", "community", "model"}
        and bool(as_of_date)
        and bool(freshness_status)
        and freshness_status not in {"stale", "stale_block", "unavailable", "missing", "missing_or_pending", "not_checked"}
        and not component.conflict_id
    )


def build_simple_instrument_scores(
    config: AppConfig,
    signals: list[SignalResult],
    forecasts: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    universe_revision: str | None = None,
    cash_comparison_lookup: Mapping[str, Mapping[str, object]] | None = None,
) -> list[SimpleInstrumentScore]:
    if universe_revision is None:
        universe_revision = load_universe().revision
    forecasts = filter_forecasts_for_universe(forecasts, universe_revision)
    candidate_report, _candidate_report_path = load_latest_candidate_report()
    candidate_forecasts = load_latest_forecasts(
        "yfinance_candidate_forecasts_*.csv",
        FORECASTS_DIR,
        universe_revision=universe_revision,
    )
    forecast_history = load_forecast_history()
    calibration = evaluate_forecast_calibration(forecast_history, prices)
    calibration_by_id = calibration_lookup(calibration)
    regime = build_market_regime(prices, candidate_report)
    portfolio_fit = build_portfolio_fit_lookup(prices)
    benchmark_id = config.universe.enabled_ids[0] if config.universe.enabled_ids else None
    metadata = {
        etf.id: {"sector": etf.sector, "theme": etf.theme}
        for etf in config.universe.etfs
        if etf.id in config.universe.enabled_ids
    }
    benchmark_attribution = build_benchmark_attribution_lookup(prices, benchmark_id=benchmark_id, metadata=metadata)
    if cash_comparison_lookup is None:
        cash_comparison_lookup = _build_local_cash_comparison_lookup(config, prices)
    crowding = build_correlation_clusters(prices, metadata)
    backtest_trust = _backtest_trust_lookup(universe_revision=universe_revision)
    universe_scores = build_universe_simple_scores(
        config,
        signals,
        forecasts,
        prices,
        calibration_by_id=calibration_by_id,
        regime=regime,
        portfolio_fit=portfolio_fit,
        benchmark_attribution=benchmark_attribution,
        cash_comparison_lookup=cash_comparison_lookup,
        crowding=crowding,
        backtest_trust=backtest_trust,
    )
    candidate_scores = build_candidate_simple_scores(
        candidate_report,
        candidate_forecasts,
        calibration_by_id=calibration_by_id,
        regime=regime,
        include_latest_input=True,
    )
    scores = sorted(
        [*universe_scores, *candidate_scores],
        key=lambda item: (item.final_score_10 is None, -(item.final_score_10 or -1.0), item.display_id),
    )
    # Concentration evidence is intentionally scoped to an explicit top-ranked
    # cohort. Including every scored row with equal weight would turn the
    # crowding summary into a universe average unrelated to the ranked ideas.
    ranked_instruments = [score.display_id for score in scores[:10]]
    ranked_crowding = build_correlation_clusters(
        prices,
        metadata,
        ranked_instruments=ranked_instruments,
        weights={instrument_id: 1.0 for instrument_id in ranked_instruments},
    )
    ranked_crowding_lookup = {row.instrument_id: row for row in ranked_crowding.rows}
    news_inventory = _news_inventory_lookup()
    ranked = [
        replace(
            score,
            rank=index,
            score_rank=index,
            news_inventory=news_inventory.get(score.display_id),
            forecast_status=_forecast_status_for_components(score.components),
            **_crowding_fields_for_score(ranked_crowding_lookup.get(score.display_id)),
        )
        for index, score in enumerate(scores, start=1)
    ]
    return [
        _with_canonical_score(_attach_authority(_with_classification_dependency(score)))
        for score in ranked
    ]


def _with_classification_dependency(score: SimpleInstrumentScore) -> SimpleInstrumentScore:
    state = classification_score_state(ROOT, score.display_id)
    if str(state.get("status")) == "unavailable":
        return replace(
            score,
            final_score_10=None,
            evidence_score_10=None,
            evidence_quality_10=None,
            risk_friction_10=None,
            rank=None,
            score_rank=None,
            warnings=list(dict.fromkeys([*score.warnings, "classification_unavailable"])),
            classification_version_id=str(state.get("version_id") or "unavailable"),
            classification_invalidation_hash=str(state.get("invalidation_token") or "unavailable"),
            classification_dependency_status="classification_unavailable",
        )
    return replace(
        score,
        classification_version_id=str(state.get("version_id") or "unavailable"),
        classification_invalidation_hash=str(state.get("invalidation_token") or "unavailable"),
        classification_dependency_status="current",
    )


def _with_canonical_score(score: SimpleInstrumentScore) -> SimpleInstrumentScore:
    if score.canonical_score is not None or score.classification_dependency_status != "current":
        return score
    canonical = canonical_score_from_simple_components(
        score.display_id,
        score.asset_type,
        score.latest_date,
        score.components,
    )
    source_vintage_hash = hashlib.sha256(
        (
            f"{canonical.source_vintage_hash}|classification:"
            f"{score.classification_invalidation_hash}"
        ).encode("utf-8")
    ).hexdigest()
    return replace(
        score,
        canonical_score=replace(canonical, source_vintage_hash=source_vintage_hash),
    )


def _crowding_fields_for_score(row: object | None) -> dict[str, object]:
    if row is None:
        return {
            "crowding_cluster_id": None,
            "crowding_cluster_label": "Correlation clustering unavailable",
            "crowding_warning": "correlation_clustering_unavailable",
            "crowding_average_peer_correlation": None,
            "crowding_sample_size": None,
            "crowding_as_of": None,
            "crowding_source_dataset": "adjusted_price_returns",
            "crowding_pair_sample_size": None,
            "crowding_cluster_weight": None,
            "crowding_cluster_risk_contribution": None,
            "crowding_ranking_coverage": None,
            "crowding_top_ranked_concentration": None,
            "crowding_top_ranked_theme_concentration": None,
            "crowding_top_ranked_theme_warning": "no_theme_concentration_warning",
        }
    return {
        "crowding_cluster_id": getattr(row, "cluster_id", None),
        "crowding_cluster_label": getattr(row, "cluster_label", "Correlation cluster"),
        "crowding_warning": getattr(row, "crowding_warning", "no_cluster_warning"),
        "crowding_average_peer_correlation": getattr(row, "average_peer_correlation", None),
        "crowding_sample_size": getattr(row, "sample_size", None),
        "crowding_as_of": getattr(row, "as_of", None),
        "crowding_source_dataset": getattr(row, "source_dataset", "adjusted_price_returns"),
        "crowding_pair_sample_size": getattr(row, "pair_sample_size", None),
        "crowding_cluster_weight": getattr(row, "cluster_weight", None),
        "crowding_cluster_risk_contribution": getattr(row, "cluster_risk_contribution", None),
        "crowding_ranking_coverage": getattr(row, "ranking_coverage", None),
        "crowding_top_ranked_concentration": getattr(row, "top_ranked_concentration", None),
        "crowding_top_ranked_theme_concentration": getattr(row, "top_ranked_theme_concentration", None),
        "crowding_top_ranked_theme_warning": getattr(row, "top_ranked_theme_warning", "no_theme_concentration_warning"),
    }


def _news_inventory_lookup() -> dict[str, int]:
    """Count canonical local news rows without inventing missing inventory."""

    if not NEWS_CLEAN_PATH.exists():
        return {}
    try:
        frame = load_news_items(NEWS_CLEAN_PATH)
    except Exception:
        return {}
    if frame.empty or "instrument_id" not in frame.columns:
        return {}
    scoped = frame.loc[frame["instrument_id"].notna()].copy()
    if scoped.empty:
        return {}
    return {str(instrument_id): int(rows) for instrument_id, rows in scoped.groupby("instrument_id", sort=True).size().items()}


def _forecast_versions_for_instrument(forecasts: pd.DataFrame, instrument_id: str) -> dict[str, str]:
    if forecasts.empty or "etf_id" not in forecasts.columns or "model_name" not in forecasts.columns:
        return {}
    rows = forecasts.loc[forecasts["etf_id"].astype(str).eq(str(instrument_id))]
    if rows.empty:
        return {}
    version_column = next((column for column in ("model_version", "version", "model_id") if column in rows.columns), None)
    if version_column is None:
        return {}
    versions: dict[str, str] = {}
    for _, row in rows.iterrows():
        model_name = str(row.get("model_name") or "").strip().casefold()
        version = str(row.get(version_column) or "").strip()
        if model_name and version and version.casefold() not in {"nan", "none", "unavailable"}:
            versions[model_name] = version
    return dict(sorted(versions.items()))


def _forecast_status_for_components(components: Iterable[SimpleScoreComponent]) -> str:
    rows = [component for component in components if component.key in {"baseline", "timesfm", "toto"}]
    if not rows:
        return "unavailable"
    valid = sum(component.score_10 is not None for component in rows)
    if valid == len(rows):
        return "available"
    return "partial" if valid else "unavailable"


def _attach_authority(score: SimpleInstrumentScore) -> SimpleInstrumentScore:
    """Publish the same typed authority envelope on scoreboard release rows."""

    evidence_present = any(
        component.status == "ok"
        and component.score_10 is not None
        and component.source_id in ALLOWED_EVIDENCE_SOURCE_IDS
        for component in score.components
    )
    warning_text = " ".join(score.warnings).casefold()
    gates = [
        GateResult(gate_id="identity", passed=bool(score.display_id.strip()), message="Instrument identity is present"),
        GateResult(
            gate_id="data_quality",
            passed=not any(token in warning_text for token in ("data", "stale", "missing")),
            message="Score data has no blocking warning",
        ),
        GateResult(
            gate_id="evidence",
            passed=evidence_present,
            message="Source-linked score evidence is available" if evidence_present else "Source-linked score evidence is unavailable",
        ),
        GateResult(
            gate_id="model_validity",
            passed=score.final_score_10 is not None and score.backtest_validity != "not_evaluated",
            message="Score and backtest validity are explicit",
        ),
        GateResult(
            gate_id="risk",
            passed=not any(token in warning_text for token in ("risk", "drawdown", "concentration")),
            message="No blocking risk warning",
        ),
        GateResult(
            gate_id="valuation",
            passed=any(
                component.key in {"stock_value", "etf_exposure"} and component.score_10 is not None
                for component in score.components
            ),
            message="Valuation context is available",
        ),
        GateResult(gate_id="signal", passed=not bool(score.warnings), message="No score warnings"),
        GateResult(
            gate_id="portfolio_fit",
            passed=score.portfolio_fit_label != "Portfolio fit not evaluated",
            message="Portfolio fit is evaluated",
        ),
        GateResult(
            gate_id="cost",
            passed=score.edge_to_cost_ratio is not None,
            message="Edge-to-cost context is available",
        ),
    ]
    decision = resolve_authority(research_state_for_legacy_action(score.final_action), gates, None)
    return replace(score, authority_decision=decision)


def simple_scoreboard_frame(
    scores: list[SimpleInstrumentScore],
    *,
    include_legacy: bool = False,
) -> pd.DataFrame:
    """Build the v2 scoreboard frame.

    Legacy ``final_action`` can be requested by diagnostic/compatibility
    callers, but is not part of the release-facing default frame.
    """

    rows: list[dict[str, object]] = []
    revision_values: list[object] = []
    for score in scores:
        revision_values.append(score.cash_curve_revision)
        row: dict[str, object] = {
            "instrument_id": score.display_id,
            "symbol": score.yahoo_symbol,
            "name": score.name,
            "instrument_currency": score.instrument_currency,
            "isin": score.isin,
            "isin_status": _isin_status(score.isin),
            "asset_type": score.asset_type,
            "analysis_tier": score.analysis_tier,
            "data_policy": score.data_policy,
            "source_group": score.source_group,
            "current_price": score.latest_price,
            "latest_price_date": score.latest_date,
            "evidence_score_10": score.evidence_score_10,
            "evidence_quality_10": score.evidence_quality_10,
            "risk_friction_10": score.risk_friction_10,
            "final_label": score.final_label,
            "research_state": score.research_state.value,
            "portfolio_review_state": score.portfolio_review_state.value,
            "analysis_status": score.analysis_status,
            "research_promotion_allowed": score.research_promotion_allowed,
            "portfolio_review_allowed": score.portfolio_review_allowed,
            "execution_allowed": False,
            "legacy_action": score.legacy_action,
            "migration_version": score.migration_version,
            "gate_policy_version": score.gate_policy_version,
            "gate_policy_checksum": score.gate_policy_checksum,
            "schema_version": "2.0",
            "decision": score.decision,
            "blocked_by": ", ".join(score.warnings),
            "reason_short": score.one_line_reason,
            "model_authority_label": score.model_authority_label,
            "backtest_trust_label": score.backtest_trust_label,
            "backtest_trust_score_10": score.backtest_trust_score_10,
            "model_calibration_label": score.model_calibration_label,
            "model_calibration_score_10": score.model_calibration_score_10,
            "market_regime_label": score.market_regime_label,
            "market_regime_score_10": score.market_regime_score_10,
            "portfolio_fit_label": score.portfolio_fit_label,
            "portfolio_fit_score_10": score.portfolio_fit_score_10,
            "strategy_template_label": score.strategy_template_label,
            "strategy_template_descriptions": score.strategy_template_descriptions,
            "evidence_sample_days": score.evidence_sample_days,
            "evidence_maturity_state": score.evidence_maturity_state,
            "evidence_maturity_label": score.evidence_maturity_label,
            "too_good_to_be_true_warning": score.too_good_to_be_true_warning,
            "evidence_sanity_warnings": " | ".join(score.evidence_sanity_warnings or []),
            "evidence_warning_count": score.evidence_warning_count,
            "benchmark_id": score.benchmark_id,
            "benchmark_period_days": score.benchmark_period_days,
            "benchmark_return": score.benchmark_return,
            "instrument_period_return": score.instrument_period_return,
            "benchmark_beta": score.benchmark_beta,
            "benchmark_correlation": score.benchmark_correlation,
            "alpha_proxy": score.alpha_proxy,
            "alpha_t_stat": score.alpha_t_stat,
            "benchmark_attribution_label": score.benchmark_attribution_label,
            "cash_instrument_return": score.cash_instrument_return,
            "cash_return": score.cash_return,
            "excess_over_cash": score.excess_over_cash,
            "cash_instrument_id": score.cash_instrument_id,
            "cash_currency": score.cash_currency,
            "cash_unit": score.cash_unit,
            "cash_dataset_kind": score.cash_dataset_kind,
            "cash_start_date": score.cash_start_date,
            "cash_end_date": score.cash_end_date,
            "cash_horizon_years": score.cash_horizon_years,
            "cash_rate": score.cash_rate,
            "cash_vintage": score.cash_vintage,
            "cash_comparison_status": score.cash_comparison_status,
            "cash_comparison_reason": score.cash_comparison_reason,
            "cash_source_id": score.cash_source_id,
            "cash_source_authority": score.cash_source_authority,
            "cash_source_checksum": score.cash_source_checksum,
            "cash_source_terms": score.cash_source_terms,
            "cash_methodology": score.cash_methodology,
            "cash_mapping_methodology": score.cash_mapping_methodology,
            "cash_day_count": score.cash_day_count,
            "cash_compounding": score.cash_compounding,
            "cash_reinvestment": score.cash_reinvestment,
            "cash_effective_at": score.cash_effective_at,
            "cash_published_at": score.cash_published_at,
            "cash_available_at": score.cash_available_at,
            "cash_curve_id": score.cash_curve_id,
            "cash_curve_version": score.cash_curve_version,
            "cash_curve_revision": score.cash_curve_revision,
            "cash_curve_type": score.cash_curve_type,
            "cash_extrapolation_allowed": score.cash_extrapolation_allowed,
            "cash_fallback": score.cash_fallback,
            "cash_fallback_from": score.cash_fallback_from,
            "cash_interpolation": score.cash_interpolation,
            "cash_freshness": score.cash_freshness,
            "cash_freshness_status": score.cash_freshness_status,
            "cash_decision_time": score.cash_decision_time,
            "cash_knowledge_cutoff": score.cash_knowledge_cutoff,
            "inflation_context": score.inflation_context,
            "sector_theme_warning": score.sector_theme_warning,
            "backtest_validity": score.backtest_validity,
            "model_contamination_risk": score.model_contamination_risk,
            "model_authority_reason": score.model_authority_reason,
            "calibration_required": score.calibration_required,
            "gross_expected_edge_bps": score.gross_expected_edge_bps,
            "estimated_total_cost_bps": score.estimated_total_cost_bps,
            "net_expected_edge_bps": score.net_expected_edge_bps,
            "edge_to_cost_ratio": score.edge_to_cost_ratio,
            "cost_stress_scenario": score.cost_stress_scenario,
            "gross_expected_return": score.gross_expected_return,
            "q10_expected_return": score.q10_expected_return,
            "q50_expected_return": score.q50_expected_return,
            "q90_expected_return": score.q90_expected_return,
            "expected_return_horizon_days": score.expected_return_horizon_days,
            "net_q10_expected_return": score.net_q10_expected_return,
            "net_expected_return": score.net_expected_return,
            "net_q90_expected_return": score.net_q90_expected_return,
            "expected_return_order_value_eur": score.expected_return_order_value_eur,
            "expected_return_cost_bps": score.expected_return_cost_bps,
            "expected_return_cost_eur": score.expected_return_cost_eur,
            "expected_return_cost_ratio": score.expected_return_cost_ratio,
            "expected_return_distribution_version": score.expected_return_distribution_version,
            "expected_return_source_dataset": score.expected_return_source_dataset,
            "crowding_cluster_id": score.crowding_cluster_id,
            "crowding_cluster_label": score.crowding_cluster_label,
            "crowding_warning": score.crowding_warning,
            "crowding_average_peer_correlation": score.crowding_average_peer_correlation,
            "crowding_sample_size": score.crowding_sample_size,
            "crowding_as_of": score.crowding_as_of,
            "crowding_source_dataset": score.crowding_source_dataset,
            "crowding_pair_sample_size": score.crowding_pair_sample_size,
            "crowding_cluster_weight": score.crowding_cluster_weight,
            "crowding_cluster_risk_contribution": score.crowding_cluster_risk_contribution,
            "crowding_ranking_coverage": score.crowding_ranking_coverage,
            "crowding_top_ranked_concentration": score.crowding_top_ranked_concentration,
            "crowding_top_ranked_theme_concentration": score.crowding_top_ranked_theme_concentration,
            "crowding_top_ranked_theme_warning": score.crowding_top_ranked_theme_warning,
            "sector_return": score.sector_return,
            "sector_relative_return": score.sector_relative_return,
            "sector_beta": score.sector_beta,
            "sector_correlation": score.sector_correlation,
            "sector_alpha_proxy": score.sector_alpha_proxy,
            "sector_attribution_status": score.sector_attribution_status,
            "attribution_sample_size": score.attribution_sample_size,
            "attribution_as_of": score.attribution_as_of,
            "attribution_source_dataset": score.attribution_source_dataset,
            "theme_return": score.theme_return,
            "theme_relative_return": score.theme_relative_return,
            "theme_beta": score.theme_beta,
            "theme_correlation": score.theme_correlation,
            "theme_alpha_proxy": score.theme_alpha_proxy,
            "theme_attribution_status": score.theme_attribution_status,
            "theme_sample_size": score.theme_sample_size,
            "friction_status": score.friction_status,
            "friction_reason": score.friction_reason,
            "formula_version": score.canonical_score.formula_version if score.canonical_score else "unavailable",
            "formula_checksum": score.canonical_score.formula_checksum if score.canonical_score else "unavailable",
            "source_vintage_hash": score.canonical_score.source_vintage_hash if score.canonical_score else "unavailable",
            "classification_version_id": score.classification_version_id,
            "classification_invalidation_hash": score.classification_invalidation_hash,
            "classification_dependency_status": score.classification_dependency_status,
            "canonical_attractiveness_10": score.canonical_score.attractiveness_10 if score.canonical_score else None,
            "canonical_expected_return_10": score.canonical_score.expected_return_10 if score.canonical_score else None,
            "canonical_risk_implementation_10": score.canonical_score.risk_implementation_10 if score.canonical_score else None,
            "canonical_evidence_confidence_10": score.canonical_score.evidence_confidence_10 if score.canonical_score else None,
            "canonical_coverage": score.canonical_score.coverage if score.canonical_score else 0.0,
            "canonical_warnings": " | ".join(score.canonical_score.warnings) if score.canonical_score else "canonical_score_unavailable",
            "valid_components": score.valid_component_count,
            "total_components": score.total_component_count,
            "source_quality": "research_grade_yfinance",
        }
        if include_legacy:
            row["final_action"] = score.final_action
        for component in score.components:
            row[f"{component.key}_score_10"] = component.score_10
            row[f"{component.key}_status"] = component.status
            row[f"{component.key}_authority"] = component.authority
        rows.append(row)
    frame = pd.DataFrame(rows)
    frame["cash_curve_revision"] = _strict_nullable_revision_array(revision_values)
    return frame


def _strict_nullable_revision_array(values: list[object]) -> pd.arrays.IntegerArray:
    normalised: list[int | None] = []
    for value in values:
        if value is None or pd.isna(value):
            normalised.append(None)
            continue
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise ValueError("cash_curve_revision must be a nullable integer")
        normalised.append(int(value))
    return pd.array(normalised, dtype="Int64")


def write_simple_scoreboard(scores: list[SimpleInstrumentScore], path: Path | None = None) -> Path:
    output_path = path or DERIVED_DIR / "scoreboard.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = simple_scoreboard_frame(scores)
    requests = (
        AtomicWriteRequest(output_path, parquet_payload(frame), validate_parquet_file),
        AtomicWriteRequest(output_path.with_suffix(".csv"), frame.to_csv(index=False).encode("utf-8"), lambda item: pd.read_csv(item)),
        AtomicWriteRequest(output_path.with_suffix(".json"), frame.to_json(orient="records", indent=2).encode("utf-8"), lambda item: pd.read_json(item)),
        AtomicWriteRequest(
            output_path.parent / "strategy_templates.csv",
            strategy_template_frame(frame).to_csv(index=False).encode("utf-8"),
            lambda item: pd.read_csv(item),
        ),
    )
    atomic_write_group(requests)
    return output_path


def load_simple_scoreboard(path: Path | None = None, *, root: Path | None = None) -> pd.DataFrame:
    """Load the canonical fail-closed projection of the persisted scoreboard."""

    output_path = path or DERIVED_DIR / "scoreboard.parquet"
    if not output_path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(output_path)
    except Exception:
        return pd.DataFrame()
    return project_classification_score_frame(frame, root=root)


def build_universe_simple_scores(
    config: AppConfig,
    signals: list[SignalResult],
    forecasts: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    calibration_by_id: dict[str, dict[str, object]] | None = None,
    regime: dict[str, object] | None = None,
    portfolio_fit: dict[str, dict[str, object]] | None = None,
    benchmark_attribution: dict[str, dict[str, object]] | None = None,
    cash_comparison_lookup: Mapping[str, Mapping[str, object]] | None = None,
    backtest_trust: dict[str, dict[str, object]] | None = None,
    crowding: ClusterReport | None = None,
) -> list[SimpleInstrumentScore]:
    raw_forecast_scores = forecast_component_maps(forecasts)
    return_distributions = forecast_return_distributions(forecasts)
    forecast_details = forecast_score_details(forecasts)
    latest_prices = _latest_price_lookup(prices)
    price_quality = _price_quality_lookup(prices)
    liquidity = _price_liquidity_lookup(prices)
    etf_exposure = _etf_exposure_lookup()
    symbol_map = yfinance_symbol_map_from_config(config)
    etf_lookup = config.universe.by_id()
    calibration_by_id = calibration_by_id or {}
    regime = regime or {}
    portfolio_fit = portfolio_fit or {}
    benchmark_attribution = benchmark_attribution or {}
    cash_comparison_lookup = cash_comparison_lookup or {}
    backtest_trust = backtest_trust or {}
    crowding_lookup = {row.instrument_id: row for row in (crowding.rows if crowding else ())}
    output: list[SimpleInstrumentScore] = []

    enabled_ids = set(config.universe.enabled_ids)
    seen_ids: set[str] = set()

    for signal in signals:
        identity = etf_lookup.get(signal.etf_id)
        if signal.etf_id not in enabled_ids or identity is None:
            continue
        seen_ids.add(signal.etf_id)
        price_info = latest_prices.get(signal.etf_id, {})
        quality_info = price_quality.get(signal.etf_id, {})
        liquidity_info = liquidity.get(signal.etf_id, {})
        exposure_info = etf_exposure.get(signal.etf_id)
        as_of_date = _noneable_str(price_info.get("date")) or _noneable_str(signal.signal_date)
        components = _attach_component_provenance(
            [
            _data_quality_component(quality_info, [*signal.blocked_by, *signal.warnings]),
            _component(
                "momentum",
                signal.components.momentum,
                _momentum_why(signal.supporting_metrics),
                authority="high",
            ),
            _component(
                "trend",
                signal.components.trend,
                _trend_why(signal.supporting_metrics),
                authority="high",
            ),
            _component(
                "risk",
                signal.components.risk,
                _risk_why(signal.supporting_metrics),
                authority="high",
                role="risk_friction",
            ),
            _component(
                "relative_strength",
                signal.components.relative_strength,
                f"Relative strength input is {raw_to_score_10(signal.components.relative_strength)}/10 after comparing with the configured ETF universe.",
                authority="high",
            ),
            _liquidity_component(liquidity_info),
            _etf_exposure_component(exposure_info),
            _forecast_component(signal.etf_id, "baseline", raw_forecast_scores, forecast_details, forecasts),
            _forecast_component(signal.etf_id, "timesfm", raw_forecast_scores, forecast_details, forecasts),
            _forecast_component(signal.etf_id, "toto", raw_forecast_scores, forecast_details, forecasts),
            ],
            as_of_date,
        )
        _raw_final, evidence_score = combine_component_scores(components, ETF_EVIDENCE_WEIGHTS)
        quality_score = _evidence_quality_score(components, warnings=[*signal.blocked_by, *signal.warnings], asset_type="ETF")
        risk_friction = _risk_friction_score(components, warnings=[*signal.blocked_by, *signal.warnings])
        final_label, final_action, decision = final_label_from_scores(
            evidence_score,
            quality_score,
            risk_friction,
            warnings=[*signal.blocked_by, *signal.warnings],
        )
        calibration_info = _calibration_info(calibration_by_id, signal.etf_id)
        fit_info = _portfolio_fit_info(portfolio_fit, signal.etf_id)
        attribution_info = _benchmark_attribution_info(benchmark_attribution, signal.etf_id)
        cash_info = _cash_comparison_info(
            cash_comparison_lookup,
            signal.etf_id,
            expected_currency=identity.currency,
        )
        crowding_info = _crowding_info(crowding_lookup, signal.etf_id)
        trust_info = _backtest_trust_info(backtest_trust, signal.etf_id, candidate=False)
        maturity = _evidence_maturity(
            rows=quality_info.get("rows"),
            final_score=evidence_score,
            evidence_quality=quality_score,
            risk_friction=risk_friction,
            metrics=signal.supporting_metrics,
            existing_warnings=[*signal.blocked_by, *signal.warnings],
        )
        validity = _model_backtest_validity(
            components,
            calibration_score=_safe_float(calibration_info.get("score")),
            backtest_score=_safe_float(trust_info.get("score")),
            candidate=False,
        )
        template_labels = strategy_template_labels(
            asset_type="ETF",
            evidence_score=evidence_score,
            risk_friction_score=risk_friction,
            component_scores=_component_score_map(components),
            regime_label=str(regime.get("regime_label") or ""),
        )
        output.append(
            SimpleInstrumentScore(
                instrument_key=f"configured:{signal.etf_id}",
                display_id=signal.etf_id,
                source_group=PRIMARY_TIER_LABEL,
                asset_type=_display_asset_type(identity),
                name=identity.name,
                yahoo_symbol=symbol_map.get(signal.etf_id, identity.ticker),
                instrument_currency=identity.currency,
                latest_date=str(price_info.get("date", signal.signal_date)),
                latest_price=_safe_float(price_info.get("price")),
                isin=identity.isin,
                analysis_tier=str(_config_extra(identity, "analysis_tier", "primary")),
                data_policy=str(_config_extra(identity, "data_policy", "yfinance_now_multi_provider_later")),
                final_score_10=evidence_score,
                decision=decision,
                one_line_reason=_summary_reason(decision, evidence_score, components, quality_score=quality_score, risk_friction_score=risk_friction),
                components=components,
                warnings=[*signal.blocked_by, *signal.warnings],
                evidence_score_10=evidence_score,
                evidence_quality_10=quality_score,
                risk_friction_10=risk_friction,
                final_label=final_label,
                final_action=final_action,
                model_authority_label=_model_authority_label(components),
                model_versions_used=dict(getattr(signal, "model_versions_used", {}) or {}),
                backtest_trust_label=str(trust_info["label"]),
                backtest_trust_score_10=_safe_float(trust_info.get("score")),
                model_calibration_label=str(calibration_info["label"]),
                model_calibration_score_10=_safe_float(calibration_info.get("score")),
                market_regime_label=str(regime.get("regime_label") or "Regime unavailable"),
                market_regime_score_10=_safe_float(regime.get("regime_score_10")),
                portfolio_fit_label=str(fit_info["label"]),
                portfolio_fit_score_10=_safe_float(fit_info.get("score")),
                strategy_templates=template_labels,
                strategy_template_label=", ".join(template_labels),
                strategy_template_descriptions=template_description(template_labels),
                evidence_sample_days=maturity["sample_days"],
                evidence_maturity_state=str(maturity["state"]),
                evidence_maturity_label=str(maturity["label"]),
                too_good_to_be_true_warning=str(maturity["too_good_to_be_true_warning"]),
                evidence_sanity_warnings=list(maturity["warnings"]),
                evidence_warning_count=int(maturity["warning_count"]),
                benchmark_id=_noneable_str(attribution_info.get("benchmark_id")),
                benchmark_period_days=_safe_int(attribution_info.get("period_days")),
                benchmark_return=_safe_float(attribution_info.get("benchmark_return")),
                instrument_period_return=_safe_float(attribution_info.get("instrument_return")),
                benchmark_beta=_safe_float(attribution_info.get("beta_to_benchmark")),
                benchmark_correlation=_safe_float(attribution_info.get("correlation_to_benchmark")),
                alpha_proxy=_safe_float(attribution_info.get("alpha_proxy")),
                alpha_t_stat=_safe_float(attribution_info.get("alpha_t_stat")),
                benchmark_attribution_label=str(attribution_info["label"]),
                **cash_info,
                crowding_cluster_id=crowding_info["cluster_id"],
                crowding_cluster_label=crowding_info["cluster_label"],
                crowding_warning=crowding_info["crowding_warning"],
                crowding_average_peer_correlation=crowding_info["average_peer_correlation"],
                crowding_sample_size=crowding_info["sample_size"],
                crowding_as_of=crowding_info["as_of"],
                crowding_source_dataset=crowding_info["source_dataset"],
                crowding_pair_sample_size=crowding_info["pair_sample_size"],
                crowding_cluster_weight=crowding_info["cluster_weight"],
                crowding_cluster_risk_contribution=crowding_info["cluster_risk_contribution"],
                crowding_ranking_coverage=crowding_info["ranking_coverage"],
                crowding_top_ranked_concentration=crowding_info["top_ranked_concentration"],
                crowding_top_ranked_theme_concentration=crowding_info["top_ranked_theme_concentration"],
                crowding_top_ranked_theme_warning=crowding_info["top_ranked_theme_warning"],
                sector_return=_safe_float(attribution_info.get("sector_return")),
                sector_relative_return=_safe_float(attribution_info.get("sector_relative_return")),
                sector_beta=_safe_float(attribution_info.get("sector_beta")),
                sector_correlation=_safe_float(attribution_info.get("sector_correlation")),
                sector_alpha_proxy=_safe_float(attribution_info.get("sector_alpha_proxy")),
                sector_attribution_status=str(attribution_info.get("sector_attribution_status", "N/A")),
                attribution_sample_size=_safe_int(attribution_info.get("sample_size")),
                attribution_as_of=_noneable_str(attribution_info.get("as_of")),
                attribution_source_dataset=str(attribution_info.get("source_dataset") or "adjusted_price_returns"),
                theme_return=_safe_float(attribution_info.get("theme_return")),
                theme_relative_return=_safe_float(attribution_info.get("theme_relative_return")),
                theme_beta=_safe_float(attribution_info.get("theme_beta")),
                theme_correlation=_safe_float(attribution_info.get("theme_correlation")),
                theme_alpha_proxy=_safe_float(attribution_info.get("theme_alpha_proxy")),
                theme_attribution_status=str(attribution_info.get("theme_attribution_status", "N/A")),
                theme_sample_size=_safe_int(attribution_info.get("theme_sample_size")),
                sector_theme_warning=_sector_theme_warning(identity),
                backtest_validity=str(validity["backtest_validity"]),
                model_contamination_risk=str(validity["model_contamination_risk"]),
                model_authority_reason=str(validity["model_authority_reason"]),
                calibration_required=bool(validity["calibration_required"]),
                forecast_status=_forecast_status_for_components(components),
                **_friction_edge_fields(
                    evidence_score,
                    components,
                    volatility=_safe_float(signal.supporting_metrics.get("vol_60d_ann")),
                    costs=_configured_friction_costs(config, signal.etf_id),
                    expected_return_distribution=return_distributions.get(signal.etf_id) or {},
                    order_value_eur=_positive_order_value(signal.supporting_metrics.get("trade_value_eur")),
                    cost_estimate=_order_size_cost_estimate(
                        config,
                        signal.etf_id,
                        signal.supporting_metrics.get("trade_value_eur"),
                    ),
                ),
            )
        )
    for etf_id in config.universe.enabled_ids:
        if etf_id in seen_ids:
            continue
        identity = etf_lookup.get(etf_id)
        if identity is None:
            continue
        output.append(_pending_configured_score(identity, symbol_map.get(etf_id, identity.ticker)))
    return [_with_canonical_score(score) for score in output]


def build_candidate_simple_scores(
    candidate_report: pd.DataFrame | None,
    candidate_forecasts: pd.DataFrame | None,
    *,
    calibration_by_id: dict[str, dict[str, object]] | None = None,
    regime: dict[str, object] | None = None,
    include_latest_input: bool = False,
) -> list[SimpleInstrumentScore]:
    report = candidate_report.copy() if candidate_report is not None else pd.DataFrame()
    forecasts = candidate_forecasts.copy() if candidate_forecasts is not None else pd.DataFrame()
    candidate_input = _latest_candidate_input_frame() if include_latest_input else pd.DataFrame()
    if not candidate_input.empty:
        input_ids = set(candidate_input["instrument_id"].dropna().astype(str))
        if "instrument_id" in report:
            report = report[report["instrument_id"].astype(str).isin(input_ids)].copy()
        else:
            report = pd.DataFrame()
        existing_ids = set(report["instrument_id"].dropna().astype(str)) if "instrument_id" in report else set()
        missing_rows = candidate_input[~candidate_input["instrument_id"].astype(str).isin(existing_ids)].copy()
        if not missing_rows.empty:
            report = pd.concat([report, missing_rows], ignore_index=True, sort=False)
    if report.empty and forecasts.empty:
        return []

    raw_forecast_scores = forecast_component_maps(forecasts)
    return_distributions = forecast_return_distributions(forecasts)
    forecast_details = forecast_score_details(forecasts)
    source = _candidate_source_frame(report, forecasts)
    relative_reference = _candidate_relative_reference(source)
    etf_exposure = _etf_exposure_lookup()
    calibration_by_id = calibration_by_id or {}
    regime = regime or {}
    output: list[SimpleInstrumentScore] = []

    for _, row in source.iterrows():
        instrument_id = str(row.get("instrument_id") or row.get("etf_id") or "").strip()
        if not instrument_id:
            continue
        asset_type = _infer_candidate_asset_type(row)
        decision = support_decision(
            str(row.get("instrument_type") or row.get("asset_type") or asset_type).strip().lower(),
            str(row.get("data_policy") or "yfinance_only").strip().lower(),
            _as_bool(row.get("leveraged", False)),
            _as_bool(row.get("inverse", False)),
        )
        if not decision.score_eligible:
            # Keep unsupported/research-only/high-risk candidates out of the
            # normal scoring output. They remain available in the source
            # report for explicit manual research.
            continue
        if _candidate_row_is_pending(row):
            output.append(_pending_candidate_score(row, asset_type))
            continue
        blocked = _split_flags(row.get("blocked_by"))
        as_of_date = _noneable_str(row.get("latest_date"))
        component_rows = [
            _candidate_data_quality_component(row, blocked),
            _component("momentum", _candidate_momentum_raw(row), _candidate_momentum_why(row), authority="high"),
            _component("trend", _candidate_trend_raw(row), _candidate_trend_why(row), authority="high"),
            _component("risk", _candidate_risk_raw(row), _candidate_risk_why(row), authority="high", role="risk_friction"),
            _component(
                "relative_strength",
                _candidate_relative_strength_raw(row, relative_reference),
                _candidate_relative_strength_why(row, relative_reference),
                authority="high",
            ),
            _candidate_liquidity_component(row),
        ]
        if asset_type == "ETF":
            component_rows.append(_etf_exposure_component(etf_exposure.get(instrument_id)))
        else:
            component_rows.extend(
                [
                    _optional_score_component(
                        "stock_value",
                        row.get("value_score_10"),
                        _candidate_value_why(row),
                        authority="medium",
                    ),
                    _optional_score_component(
                        "stock_quality",
                        row.get("quality_score_10"),
                        _candidate_quality_why(row),
                        authority="medium",
                    ),
                    _optional_score_component(
                        "analyst_revision",
                        row.get("analyst_revision_score_10"),
                        _candidate_revision_why(row),
                        authority="low",
                    ),
                ]
            )
        component_rows.extend(
            [
                _forecast_component(instrument_id, "baseline", raw_forecast_scores, forecast_details, forecasts),
                _forecast_component(instrument_id, "timesfm", raw_forecast_scores, forecast_details, forecasts),
                _forecast_component(instrument_id, "toto", raw_forecast_scores, forecast_details, forecasts),
            ]
        )
        components = _attach_component_provenance(component_rows, as_of_date)
        weight_map = ETF_EVIDENCE_WEIGHTS if asset_type == "ETF" else STOCK_EVIDENCE_WEIGHTS
        _raw_final, evidence_score = combine_component_scores(components, weight_map)
        quality_score = _evidence_quality_score(components, warnings=blocked, asset_type=asset_type)
        risk_friction = _risk_friction_score(components, warnings=blocked)
        final_label, final_action, decision = final_label_from_scores(evidence_score, quality_score, risk_friction, warnings=blocked)
        calibration_info = _calibration_info(calibration_by_id, instrument_id)
        trust_info = _backtest_trust_info({}, instrument_id, candidate=True)
        maturity = _evidence_maturity(
            rows=row.get("rows"),
            final_score=evidence_score,
            evidence_quality=quality_score,
            risk_friction=risk_friction,
            metrics=row.to_dict(),
            existing_warnings=blocked,
        )
        validity = _model_backtest_validity(
            components,
            calibration_score=_safe_float(calibration_info.get("score")),
            backtest_score=_safe_float(trust_info.get("score")),
            candidate=True,
        )
        template_labels = strategy_template_labels(
            asset_type=asset_type,
            evidence_score=evidence_score,
            risk_friction_score=risk_friction,
            component_scores=_component_score_map(components),
            regime_label=str(regime.get("regime_label") or ""),
        )
        output.append(
            SimpleInstrumentScore(
                instrument_key=f"candidate:{instrument_id}",
                display_id=instrument_id,
                source_group=source_group_for_analysis_tier(row.get("analysis_tier") or "secondary"),
                asset_type=asset_type,
                name=str(row.get("name") or instrument_id),
                yahoo_symbol=str(row.get("yahoo_symbol") or instrument_id),
                latest_date=str(row.get("latest_date") or "unknown"),
                latest_price=_safe_float(row.get("latest_price")),
                isin=_noneable_str(row.get("isin")),
                analysis_tier=str(row.get("analysis_tier") or "secondary"),
                data_policy=str(row.get("data_policy") or "yfinance_only"),
                final_score_10=evidence_score,
                decision=decision,
                one_line_reason=_summary_reason(decision, evidence_score, components, flags=blocked, quality_score=quality_score, risk_friction_score=risk_friction),
                components=components,
                warnings=blocked,
                evidence_score_10=evidence_score,
                evidence_quality_10=quality_score,
                risk_friction_10=risk_friction,
                final_label=final_label,
                final_action=final_action,
                model_authority_label=_model_authority_label(components),
                model_versions_used=_forecast_versions_for_instrument(forecasts, instrument_id),
                backtest_trust_label=str(trust_info["label"]),
                backtest_trust_score_10=_safe_float(trust_info.get("score")),
                model_calibration_label=str(calibration_info["label"]),
                model_calibration_score_10=_safe_float(calibration_info.get("score")),
                market_regime_label=str(regime.get("regime_label") or "Regime unavailable"),
                market_regime_score_10=_safe_float(regime.get("regime_score_10")),
                portfolio_fit_label="Candidate portfolio fit pending: not in clean portfolio price panel.",
                portfolio_fit_score_10=None,
                strategy_templates=template_labels,
                strategy_template_label=", ".join(template_labels),
                strategy_template_descriptions=template_description(template_labels),
                evidence_sample_days=maturity["sample_days"],
                evidence_maturity_state=str(maturity["state"]),
                evidence_maturity_label=str(maturity["label"]),
                too_good_to_be_true_warning=str(maturity["too_good_to_be_true_warning"]),
                evidence_sanity_warnings=list(maturity["warnings"]),
                evidence_warning_count=int(maturity["warning_count"]),
                benchmark_attribution_label="Benchmark attribution pending: candidate price history is not yet in the clean yfinance price panel.",
                sector_theme_warning="Sector/theme concentration pending: candidate metadata is not yet normalised into the configured universe.",
                backtest_validity=str(validity["backtest_validity"]),
                model_contamination_risk=str(validity["model_contamination_risk"]),
                model_authority_reason=str(validity["model_authority_reason"]),
                calibration_required=bool(validity["calibration_required"]),
                forecast_status=_forecast_status_for_components(components),
                **_friction_edge_fields(
                    evidence_score,
                    components,
                    volatility=_safe_float(row.get("volatility_60d_ann")),
                    expected_return_distribution=return_distributions.get(instrument_id) or {},
                    order_value_eur=None,
                    cost_estimate=None,
                ),
            )
        )
    return [_with_canonical_score(score) for score in output]


def load_latest_candidate_report(directory: Path = REPORTS_DIR) -> tuple[pd.DataFrame, Path | None]:
    files = sorted(directory.glob("yfinance_trade_candidate_analysis_*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return pd.DataFrame(), None
    path = files[0]
    return pd.read_csv(path), path


def _latest_candidate_input_frame(directory: Path = RAW_DIR / "trade_candidates") -> pd.DataFrame:
    files = sorted(directory.glob("yahoo_trade_candidates_*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return pd.DataFrame()
    frame = pd.read_csv(files[0])
    if "instrument_id" not in frame or "yahoo_symbol" not in frame:
        return pd.DataFrame()
    return frame


def _pending_configured_score(identity, yahoo_symbol: str) -> SimpleInstrumentScore:
    asset_type = _display_asset_type(identity)
    analysis_tier = str(_config_extra(identity, "analysis_tier", "primary"))
    return SimpleInstrumentScore(
        instrument_key=f"configured:{identity.id}",
        display_id=identity.id,
        source_group=source_group_for_analysis_tier(analysis_tier),
        asset_type=asset_type,
        name=identity.name,
        yahoo_symbol=yahoo_symbol,
        instrument_currency=identity.currency,
        latest_date="pending refresh",
        latest_price=None,
        isin=identity.isin or "needs_verification",
        analysis_tier=analysis_tier,
        data_policy=str(_config_extra(identity, "data_policy", "yfinance_now_multi_provider_later")),
        final_score_10=None,
        decision="Pending Refresh",
        one_line_reason=PENDING_WORKFLOW_REASON,
        components=_pending_components(asset_type),
        warnings=["pending_refresh"],
        evidence_score_10=None,
        evidence_quality_10=None,
        risk_friction_10=None,
        final_label="pending_refresh",
        final_action="manual_review",
        model_authority_label="Model evidence pending",
        backtest_trust_label="Backtest pending",
        model_calibration_label="Calibration pending",
        market_regime_label="Regime unavailable until refreshed",
        portfolio_fit_label=_pending_candidate_portfolio_label(source_group_for_analysis_tier(analysis_tier)),
        strategy_template_label="pending_refresh",
        strategy_template_descriptions="Run the workflow buttons to calculate algorithms and optional model confirmation.",
        evidence_maturity_state="pending_refresh",
        evidence_maturity_label="No refreshed local yfinance evidence exists for this instrument yet.",
        too_good_to_be_true_warning="No evidence yet",
        evidence_sanity_warnings=["pending_refresh"],
        evidence_warning_count=1,
        benchmark_attribution_label="Benchmark attribution pending until yfinance prices are refreshed.",
        sector_theme_warning="Sector/theme context is metadata-only until refreshed.",
        backtest_validity="not_evaluated",
        model_contamination_risk="not_evaluated",
        model_authority_reason="No model row exists yet; models cannot affect the score.",
        calibration_required=True,
    )


def _pending_candidate_score(row: pd.Series, asset_type: str) -> SimpleInstrumentScore:
    instrument_id = str(row.get("instrument_id") or "").strip()
    source_group = source_group_for_analysis_tier(row.get("analysis_tier") or "secondary")
    return SimpleInstrumentScore(
        instrument_key=f"candidate:{instrument_id}",
        display_id=instrument_id,
        source_group=source_group,
        asset_type=asset_type,
        name=str(row.get("name") or instrument_id),
        yahoo_symbol=str(row.get("yahoo_symbol") or instrument_id),
        latest_date="pending refresh",
        latest_price=None,
        isin=_noneable_str(row.get("isin")),
        analysis_tier=str(row.get("analysis_tier") or "secondary"),
        data_policy=str(row.get("data_policy") or "yfinance_only"),
        final_score_10=None,
        decision="Pending Refresh",
        one_line_reason=PENDING_WORKFLOW_REASON,
        components=_pending_components(asset_type),
        warnings=["pending_refresh"],
        evidence_score_10=None,
        evidence_quality_10=None,
        risk_friction_10=None,
        final_label="pending_refresh",
        final_action="manual_review",
        model_authority_label="Model evidence pending",
        backtest_trust_label="Backtest pending",
        model_calibration_label="Calibration pending",
        market_regime_label="Regime unavailable until refreshed",
        portfolio_fit_label=_pending_candidate_portfolio_label(source_group),
        strategy_template_label="pending_refresh",
        strategy_template_descriptions="Run the workflow buttons to calculate algorithms and optional model confirmation.",
        evidence_maturity_state="pending_refresh",
        evidence_maturity_label="No refreshed local yfinance evidence exists for this instrument yet.",
        too_good_to_be_true_warning="No evidence yet",
        evidence_sanity_warnings=["pending_refresh"],
        evidence_warning_count=1,
        benchmark_attribution_label="Benchmark attribution pending until yfinance prices are refreshed.",
        sector_theme_warning="Sector/theme context is metadata-only until refreshed.",
        backtest_validity="not_evaluated",
        model_contamination_risk="not_evaluated",
        model_authority_reason="No model row exists yet; models cannot affect the score.",
        calibration_required=True,
    )


def _pending_components(asset_type: str) -> list[SimpleScoreComponent]:
    keys = ["data_quality", "momentum", "trend", "risk", "relative_strength", "liquidity_cost"]
    if asset_type == "ETF":
        keys.append("etf_exposure")
    elif _is_stock_like_asset_type(asset_type):
        keys.extend(["stock_value", "stock_quality", "analyst_revision"])
    keys.extend(["baseline", "timesfm", "toto"])
    return [_pending_component(key) for key in keys]


def _pending_component(key: str) -> SimpleScoreComponent:
    role = "model_confirmation" if key in {"baseline", "timesfm", "toto"} else "risk_friction" if key == "risk" else "evidence"
    authority = "low" if role == "model_confirmation" else "hard" if key == "data_quality" else "medium"
    return SimpleScoreComponent(
        key=key,
        label=COMPONENT_LABELS[key],
        score_10=None,
        raw_score=None,
        status="N/A",
        explanation=COMPONENT_EXPLANATIONS[key],
        good_score=GOOD_SCORE_TEXT[key],
        why=PENDING_WORKFLOW_REASON,
        authority=authority,
        score_role=role,
    )


def _display_asset_type(identity) -> str:
    value = str(_config_extra(identity, "instrument_type", identity.asset_class) or identity.asset_class or "").strip().lower()
    if value == "etf":
        return "ETF"
    if value == "certificate":
        return "Certificate"
    if value == "stock":
        return "Stock"
    if value in {"equity_certificate", "equity certificate"}:
        return "Equity certificate"
    return "ETF" if "etf" in value else "Stock" if value == "equity" else value.title() or "Instrument"


def _config_extra(identity, key: str, default: object = None) -> object:
    extra = getattr(identity, "model_extra", None) or {}
    if key in extra:
        return extra[key]
    return getattr(identity, key, default)


def _candidate_row_is_pending(row: pd.Series) -> bool:
    latest_date = _noneable_str(row.get("latest_date"))
    latest_price = _safe_float(row.get("latest_price"))
    rows = _safe_float(row.get("rows"))
    score = _safe_float(row.get("final_score_10"))
    has_report_marker = any(_noneable_str(row.get(column)) for column in ("blocked_by", "decision", "final_label"))
    return latest_date is None and latest_price is None and rows is None and score is None and not has_report_marker


def _component(
    key: str,
    raw_score: float | int | None,
    why: str,
    *,
    authority: str = "medium",
    role: str = "evidence",
) -> SimpleScoreComponent:
    score = raw_to_score_10(raw_score)
    return SimpleScoreComponent(
        key=key,
        label=COMPONENT_LABELS[key],
        score_10=score,
        raw_score=None if score is None else _clamp(float(raw_score)),
        status="OK" if score is not None else "N/A",
        explanation=COMPONENT_EXPLANATIONS[key],
        good_score=GOOD_SCORE_TEXT[key],
        why=why if score is not None else "Not enough valid yfinance data for this component, so it is excluded from the final score.",
        authority=authority,
        score_role=role,
    )


def _component_freshness_status(as_of_date: str | None) -> str | None:
    parsed = _parse_date(as_of_date)
    if parsed is None:
        return None
    return "stale" if _business_days_between(parsed, date.today()) > 10 else "ok"


def _attach_component_provenance(
    components: list[SimpleScoreComponent],
    as_of_date: str | None,
) -> list[SimpleScoreComponent]:
    clean_date = _noneable_str(as_of_date)
    freshness = _component_freshness_status(clean_date)
    return [
        replace(
            component,
            as_of_date=component.as_of_date or clean_date,
            freshness_status=component.freshness_status or freshness,
        )
        for component in components
    ]


def _forecast_component(
    instrument_id: str,
    model_name: str,
    raw_forecast_scores: dict[str, dict[str, float]],
    forecast_details: pd.DataFrame,
    forecasts: pd.DataFrame,
) -> SimpleScoreComponent:
    raw = raw_forecast_scores.get(model_name, {}).get(instrument_id)
    if raw is not None:
        selected = _forecast_detail_row(forecast_details, model_name, instrument_id)
        why = "Valid forecast row is available and included in the weighted final score."
        if selected is not None:
            why = (
                f"Selected {int(selected['horizon_days'])} trading-day forecast expects "
                f"{_fmt_pct(selected['expected_return'])}; this maps to {raw_to_score_10(raw)}/10."
            )
        return _component(model_name, raw, why, authority="low", role="model_confirmation")

    reason = _missing_forecast_reason(forecasts, model_name, instrument_id)
    return SimpleScoreComponent(
        key=model_name,
        label=COMPONENT_LABELS[model_name],
        score_10=None,
        raw_score=None,
        status="N/A",
        explanation=COMPONENT_EXPLANATIONS[model_name],
        good_score=GOOD_SCORE_TEXT[model_name],
        why=reason,
        authority="low",
        score_role="model_confirmation",
    )


def _forecast_detail_row(forecast_details: pd.DataFrame, model_name: str, instrument_id: str) -> pd.Series | None:
    if forecast_details.empty:
        return None
    frame = forecast_details[
        (forecast_details["model_name"].astype(str).str.lower() == model_name)
        & (forecast_details["etf_id"].astype(str) == instrument_id)
    ]
    if frame.empty:
        return None
    return frame.iloc[-1]


def _missing_forecast_reason(forecasts: pd.DataFrame, model_name: str, instrument_id: str) -> str:
    if forecasts.empty or not {"etf_id", "model_name"}.issubset(forecasts.columns):
        return f"No {COMPONENT_LABELS[model_name].lower()} file is loaded, so it is excluded from the final score."
    rows = forecasts[
        (forecasts["etf_id"].astype(str) == instrument_id)
        & (forecasts["model_name"].astype(str).str.lower() == model_name)
    ]
    if rows.empty:
        return f"No {COMPONENT_LABELS[model_name].lower()} row exists for this instrument."
    statuses = ", ".join(sorted({str(value) for value in rows.get("status", pd.Series(dtype=str)).dropna().unique()}))
    reason_values = []
    for column in ("reason_unavailable", "error_message"):
        if column in rows:
            reason_values.extend(str(value).strip() for value in rows[column].dropna().unique() if str(value).strip())
    suffix = f" Reason: {reason_values[0]}" if reason_values else ""
    return f"{COMPONENT_LABELS[model_name]} rows are present but not valid/allowed for scoring. Status: {statuses or 'unknown'}.{suffix}"


def _candidate_source_frame(report: pd.DataFrame, forecasts: pd.DataFrame) -> pd.DataFrame:
    if not report.empty:
        return report.copy()
    if forecasts.empty or "etf_id" not in forecasts:
        return pd.DataFrame()
    ids = sorted({str(value) for value in forecasts["etf_id"].dropna().unique()})
    return pd.DataFrame({"instrument_id": ids, "name": ids, "yahoo_symbol": ids})


def _candidate_relative_reference(frame: pd.DataFrame) -> float | None:
    for column in ("return_6m", "return_12m", "return_3m"):
        if column not in frame:
            continue
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if not values.empty:
            return float(values.median())
    return None


def _data_quality_component(info: dict[str, object], warnings: list[str]) -> SimpleScoreComponent:
    raw, why = _data_quality_raw_and_reason(
        latest_date=str(info.get("date") or ""),
        rows=_safe_float(info.get("rows")),
        missing_adjusted=_safe_float(info.get("missing_adjusted_close")),
        non_adjusted_count=_safe_float(info.get("non_adjusted_count")),
        warnings=warnings,
    )
    return _component("data_quality", raw, why, authority="hard", role="evidence_quality")


def _candidate_data_quality_component(row: pd.Series, warnings: list[str]) -> SimpleScoreComponent:
    raw, why = _data_quality_raw_and_reason(
        latest_date=str(row.get("latest_date") or ""),
        rows=_safe_float(row.get("rows")),
        missing_adjusted=0.0,
        non_adjusted_count=0.0,
        warnings=warnings,
    )
    return _component("data_quality", raw, why, authority="hard", role="evidence_quality")


def _data_quality_raw_and_reason(
    *,
    latest_date: str,
    rows: float | None,
    missing_adjusted: float | None,
    non_adjusted_count: float | None,
    warnings: list[str],
) -> tuple[float | None, str]:
    score = 9.0
    reason: list[str] = ["Source is yfinance, so evidence is labelled research-grade rather than institutional."]
    latest = _parse_date(latest_date)
    if latest is None:
        return -1.0, "No valid latest price date is available; this is a hard data-quality review item."
    age_days = _business_days_between(latest, date.today())
    reason.append(f"Latest price date is {latest.isoformat()} ({age_days} business days old).")
    if age_days > 10:
        score = min(score, 2.0)
        reason.append("Price data is more than 10 business days old, so evidence should be manually reviewed.")
    elif age_days > 3:
        score -= 1.5
        reason.append("Price data is outside the preferred freshness window.")
    if rows is None or rows < 120:
        score = min(score, 2.0)
        reason.append("Less than 120 valid price rows are available.")
    elif rows < 252:
        score -= 2.0
        reason.append("Less than one trading year of price history is available.")
    if (missing_adjusted or 0) > 0 or (non_adjusted_count or 0) > 0:
        score = min(score, 2.0)
        reason.append("Adjusted close is missing or not marked adjusted for at least one row.")
    hard_warning_tokens = {"missing_price_data", "missing_latest_price", "insufficient_12m_history", "stale_price"}
    if hard_warning_tokens & set(warnings):
        score = min(score, 3.0)
        reason.append("Blocking warning flags are present: " + ", ".join(sorted(hard_warning_tokens & set(warnings))) + ".")
    return _score_10_to_raw(score), " ".join(reason)


def _liquidity_component(info: dict[str, object]) -> SimpleScoreComponent:
    avg_turnover = _safe_float(info.get("avg_turnover_20"))
    spread_proxy = _safe_float(info.get("spread_proxy_20"))
    raw, why = _liquidity_raw_and_reason(avg_turnover, spread_proxy)
    return _component("liquidity_cost", raw, why, authority="high", role="risk_friction")


def build_priips_kid_cost_evidence(record: object) -> SimpleScoreComponent:
    """Expose complete, fresh issuer KID cost evidence at the score seam.

    The helper is intentionally opt-in: the approved score weights and primary
    yfinance path are unchanged.  A numeric score is produced only from an
    explicitly parsed percentage/currency cost (or SRI fallback); incomplete,
    conflicted or stale records remain observable but score-ineligible.
    """

    document_date = _noneable_str(getattr(record, "document_date", None))
    source_sha = _noneable_str(getattr(record, "source_sha256", None))
    source_id = f"priips_kid:{source_sha}" if source_sha else ""
    freshness = _component_freshness_status(document_date)
    warnings = tuple(str(item).strip() for item in (getattr(record, "warnings", ()) or ()) if str(item).strip())
    conflict_id = "methodology_holdings_conflict" if "methodology_holdings_conflict" in warnings else None
    cost_fields = getattr(record, "cost_fields", {})
    cost_text = " ".join(str(value) for value in cost_fields.values()) if isinstance(cost_fields, dict) else ""
    malformed_cost = bool(re.search(r"What are the costs|cost_table_malformed", cost_text, re.IGNORECASE)) or "cost_table_malformed" in warnings
    ongoing_text = cost_fields.get("ongoing_costs") if isinstance(cost_fields, dict) else None
    numeric_match = re.search(r"(?<![A-Za-z])(\d+(?:[.,]\d+)?)\s*%", str(ongoing_text or ""))
    explicit_value = None if numeric_match is None else _safe_float(numeric_match.group(1).replace(",", "."))
    sri = _safe_int(getattr(record, "sri", None))
    key = "liquidity_cost"
    value_reason = "No explicit numeric KID cost percentage is available."
    if explicit_value is not None:
        # A disclosed percentage is a cost penalty, not a positive return
        # signal.  Keep the penalty bounded by the raw-score contract without
        # inventing a preferred cost ceiling that the KID does not disclose.
        raw_score = _clamp(-explicit_value)
        score_10 = raw_to_score_10(raw_score)
        value_reason = f"Issuer KID reports an explicit cost percentage of {explicit_value:g}%; no proxy cost was invented."
    else:
        key = "risk"
        # PRIIPs SRI is defined from 1 (lowest risk) through 7 (highest risk).
        # Map that bounded domain inversely onto the [-1, 1] raw-score domain.
        raw_score = (
            None
            if sri is None
            else _clamp(1.0 - 2.0 * ((float(sri) - 1.0) / (7.0 - 1.0)))
        )
        score_10 = None if raw_score is None else raw_to_score_10(raw_score)
        if sri is not None:
            value_reason = f"Issuer KID reports explicit summary risk indicator {sri}; no cost proxy was invented."
    eligible_record = bool(
        getattr(record, "score_eligible", False)
        and not bool(getattr(record, "manual_review", False))
        and not warnings
        and bool(source_id)
        and (explicit_value is not None or sri is not None)
        and not malformed_cost
        and freshness == "ok"
    )
    if not eligible_record:
        raw_score = None
        score_10 = None
    status = "OK" if score_10 is not None else "N/A"
    if warnings:
        value_reason += " Manual review is required: " + ", ".join(warnings) + "."
    elif freshness in {"stale", "stale_block", "missing", "missing_or_pending", "unknown"}:
        value_reason += f" KID freshness is {freshness or 'unknown'} and is excluded."
    return SimpleScoreComponent(
        key=key,
        label=COMPONENT_LABELS[key],
        score_10=score_10,
        raw_score=raw_score,
        status=status,
        explanation=COMPONENT_EXPLANATIONS[key],
        good_score=GOOD_SCORE_TEXT[key],
        why=value_reason if score_10 is not None else "KID evidence is unavailable or excluded from scoring. " + value_reason,
        authority="high",
        score_role="risk_friction" if key in {"risk", "liquidity_cost"} else "evidence",
        source_id=source_id or "priips_kid:unavailable",
        source_authority="issuer_document",
        as_of_date=document_date,
        freshness_status=freshness,
        conflict_id=conflict_id,
        evidence_quality=1.0 if eligible_record else "manual_review",
    )


# Compatibility-friendly aliases for evidence-ledger/import callers.
build_kid_cost_evidence = build_priips_kid_cost_evidence
priips_kid_cost_component = build_priips_kid_cost_evidence


def _candidate_liquidity_component(row: pd.Series) -> SimpleScoreComponent:
    avg_turnover = _safe_float(row.get("median_turnover_60d_eur"))
    spread_proxy = _safe_float(row.get("high_low_spread_proxy_20"))
    raw, why = _liquidity_raw_and_reason(avg_turnover, spread_proxy)
    return _component("liquidity_cost", raw, why, authority="high", role="risk_friction")


def _liquidity_raw_and_reason(avg_turnover_eur: float | None, spread_proxy: float | None) -> tuple[float | None, str]:
    if avg_turnover_eur is None or avg_turnover_eur <= 0:
        return None, "No usable yfinance volume/turnover data is available for a liquidity-cost estimate."
    if avg_turnover_eur >= 10_000_000:
        score = 9.5
    elif avg_turnover_eur >= 2_000_000:
        score = 8.0
    elif avg_turnover_eur >= 500_000:
        score = 6.5
    elif avg_turnover_eur >= 100_000:
        score = 5.0
    elif avg_turnover_eur >= 25_000:
        score = 3.5
    else:
        score = 2.0
    spread_text = "spread proxy unavailable"
    if spread_proxy is not None and spread_proxy > 0:
        spread_bps = spread_proxy * 10_000.0
        spread_text = f"high-low spread proxy is about {spread_bps:.0f} bps"
        if spread_bps > 350:
            score -= 2.0
        elif spread_bps > 200:
            score -= 1.0
        elif spread_bps < 80:
            score += 0.5
    score = _clamp_score_10(score)
    why = f"Average traded value proxy is EUR {avg_turnover_eur:,.0f}; {spread_text}. Costs are estimated conservatively from yfinance OHLCV."
    return _score_10_to_raw(score), why


def _etf_exposure_component(info: dict[str, object] | None) -> SimpleScoreComponent:
    if not info:
        return SimpleScoreComponent(
            key="etf_exposure",
            label=COMPONENT_LABELS["etf_exposure"],
            score_10=None,
            raw_score=None,
            status="N/A",
            explanation=COMPONENT_EXPLANATIONS["etf_exposure"],
            good_score=GOOD_SCORE_TEXT["etf_exposure"],
            why="Yahoo fund holdings are unavailable for this ETF, so exposure is not included in the evidence score and quality is reduced slightly.",
            authority="medium",
            score_role="evidence",
        )
    top_weight = _safe_float(info.get("top_weight_sum")) or 0.0
    largest = _safe_float(info.get("largest_weight")) or 0.0
    count = int(_safe_float(info.get("holding_count")) or 0)
    top10_penalty = min(top_weight / 0.60, 1.0) * 4.0
    largest_penalty = min(largest / 0.15, 1.0) * 3.0
    partial_penalty = 1.0 if top_weight < 0.50 else 0.0
    score = _clamp_score_10(10.0 - top10_penalty - largest_penalty - partial_penalty)
    why = (
        f"Yahoo exposes {count} top-holding rows. Top available holdings sum to {top_weight:.1%}; "
        f"largest holding is {largest:.1%}. Holdings may be partial."
    )
    return _component("etf_exposure", _score_10_to_raw(score), why, authority="medium")


def _optional_score_component(key: str, score_10: object, why: str, *, authority: str) -> SimpleScoreComponent:
    score = _safe_float(score_10)
    if score is None:
        return SimpleScoreComponent(
            key=key,
            label=COMPONENT_LABELS[key],
            score_10=None,
            raw_score=None,
            status="N/A",
            explanation=COMPONENT_EXPLANATIONS[key],
            good_score=GOOD_SCORE_TEXT[key],
            why=why,
            authority=authority,
            score_role="evidence",
        )
    score = _clamp_score_10(score)
    raw = _score_10_to_raw(score)
    return SimpleScoreComponent(
        key=key,
        label=COMPONENT_LABELS[key],
        score_10=round(score, 1),
        raw_score=raw,
        status="OK",
        explanation=COMPONENT_EXPLANATIONS[key],
        good_score=GOOD_SCORE_TEXT[key],
        why=why,
        authority=authority,
        score_role="evidence",
    )


def _infer_candidate_asset_type(row: pd.Series) -> str:
    explicit = str(row.get("instrument_type") or "").strip().lower()
    if explicit == "etf":
        return "ETF"
    if explicit == "stock":
        return "Stock"
    if explicit == "certificate":
        return "Certificate"
    if explicit in {"equity_certificate", "equity certificate", "egenkapitalbevis"}:
        return "Equity certificate"
    text = " ".join(str(row.get(column) or "") for column in ("name", "notes", "instrument_id", "yahoo_symbol")).lower()
    return "ETF" if "etf" in text or "ucits" in text else "Stock"


def _evidence_quality_score(
    components: list[SimpleScoreComponent],
    *,
    warnings: list[str],
    asset_type: str,
) -> float | None:
    data_quality = _score_by_key(components, "data_quality")
    if data_quality is None:
        return None
    expected = [component for component in components if component.score_role in {"evidence", "risk_friction", "model_confirmation"}]
    valid = [component for component in expected if component.score_10 is not None]
    completeness = len(valid) / len(expected) if expected else 0.0
    model_components = [component for component in components if component.score_role == "model_confirmation"]
    valid_models = [component for component in model_components if component.score_10 is not None]
    model_score = 10.0 * len(valid_models) / len(model_components) if model_components else 0.0
    warning_penalty = min(2.0, 0.4 * len(warnings))
    missing_penalty = 0.0
    if asset_type == "ETF" and _score_by_key(components, "etf_exposure") is None:
        missing_penalty += 1.0
    if _is_stock_like_asset_type(asset_type):
        if _score_by_key(components, "stock_value") is None:
            missing_penalty += 0.8
        if _score_by_key(components, "stock_quality") is None:
            missing_penalty += 0.8
    quality = (0.50 * data_quality) + (0.25 * completeness * 10.0) + (0.15 * model_score) + 1.0
    return round(_clamp_score_10(quality - warning_penalty - missing_penalty), 1)


def _risk_friction_score(components: list[SimpleScoreComponent], *, warnings: list[str]) -> float | None:
    risk = _score_by_key(components, "risk")
    liquidity = _score_by_key(components, "liquidity_cost")
    values = [(risk, 0.60), (liquidity, 0.40)]
    weighted = _weighted_score_10(values)
    if weighted is None:
        return None
    if {"deep_current_drawdown", "high_60d_volatility"} & set(warnings):
        weighted -= 1.0
    return round(_clamp_score_10(weighted), 1)


def final_label_from_scores(
    evidence_score: float | None,
    evidence_quality: float | None,
    risk_friction: float | None,
    *,
    warnings: list[str],
    current_holding: bool = False,
) -> tuple[str, str, str]:
    hard_flags = {"missing_price_data", "missing_latest_price", "insufficient_12m_history", "stale_price"}
    if hard_flags & set(warnings):
        return "blocked_data_quality", "manual_review", "Manual Review"
    if evidence_score is None or evidence_quality is None or risk_friction is None:
        return "manual_review", "manual_review", "Manual Review"
    if evidence_quality < 4.0:
        return "low_quality_manual_review", "manual_review", "Manual Review"
    if evidence_score >= 8.0 and evidence_quality >= 7.0 and risk_friction >= 6.0:
        return "strong_evidence_candidate", "add_candidate", "Strong Evidence Candidate"
    if evidence_score >= 6.5 and evidence_quality >= 6.0 and risk_friction >= 5.0:
        return "positive_evidence_candidate", "add_candidate", "Positive Evidence Candidate"
    if current_holding and evidence_score >= 4.0:
        return "hold_context", "hold", "Hold Context"
    if evidence_score >= 5.0:
        return "watchlist", "no_trade", "Watchlist"
    if evidence_score >= 4.0:
        return "mixed_evidence_review", "no_trade", "Hold Context"
    return "weak_evidence_review", "manual_review", "Weak Evidence Review"


def _model_authority_label(components: list[SimpleScoreComponent]) -> str:
    valid = {component.key for component in components if component.score_role == "model_confirmation" and component.score_10 is not None}
    if {"timesfm", "toto"} <= valid:
        return "Independent AI confirmation available"
    if {"timesfm", "toto"} & valid:
        return "Partial AI forecast evidence"
    if "baseline" in valid:
        return "Model evidence: baseline only"
    return "Model evidence unavailable"


def _model_backtest_validity(
    components: list[SimpleScoreComponent],
    *,
    calibration_score: float | None,
    backtest_score: float | None,
    candidate: bool,
) -> dict[str, object]:
    optional_models = [
        component
        for component in components
        if component.key in {"timesfm", "toto"} and component.score_10 is not None
    ]
    baseline_available = _score_by_key(components, "baseline") is not None
    calibration_required = bool(optional_models)
    if candidate:
        backtest_validity = "not_backtested_candidate"
    elif backtest_score is None:
        backtest_validity = "unverified_backtest"
    elif backtest_score >= 6.0:
        backtest_validity = "usable_low_authority"
    else:
        backtest_validity = "weak_or_low_quality"

    if optional_models and calibration_score is None:
        contamination_risk = "unverified_model_history_overlap"
        authority_reason = "TimesFM/Toto evidence is present but local OOS calibration is pending, so it remains low-authority and cannot override deterministic evidence."
        if backtest_validity == "usable_low_authority":
            backtest_validity = "model_claim_unverified"
    elif optional_models and calibration_score is not None:
        contamination_risk = "reduced_by_local_calibration"
        authority_reason = "Optional model evidence has local calibration evidence, but it remains confirmation only."
    elif baseline_available:
        contamination_risk = "baseline_only_low"
        authority_reason = "Only deterministic baseline model evidence is available; it is low-authority confirmation."
    else:
        contamination_risk = "no_model_evidence"
        authority_reason = "No valid model evidence is available, so final scoring relies on deterministic yfinance evidence."

    return {
        "backtest_validity": backtest_validity,
        "model_contamination_risk": contamination_risk,
        "model_authority_reason": authority_reason,
        "calibration_required": calibration_required,
    }


def _backtest_trust_label() -> str:
    return "Backtest trust pending"


def _component_score_map(components: list[SimpleScoreComponent]) -> dict[str, float | None]:
    return {component.key: component.score_10 for component in components}


def _friction_edge_fields(
    evidence_score: float | None,
    components: list[SimpleScoreComponent],
    *,
    volatility: float | None = None,
    costs: dict[str, float] | None = None,
    scenario: str = "base",
    expected_return_distribution: dict[str, object] | None = None,
    order_value_eur: float | None = None,
    cost_estimate: dict[str, object] | None = None,
) -> dict[str, object]:
    # Production callers supply the distribution and order-size estimate.  A
    # missing distribution therefore stays unavailable and never falls back
    # to the ordinal score proxy.  The old branch remains for direct migration
    # callers until their readers move to the v1 distribution fields.
    if expected_return_distribution is not None or order_value_eur is not None or cost_estimate is not None:
        result = estimate_friction_adjusted_return(
            expected_return_distribution,
            order_value_eur=order_value_eur,
            cost_estimate=cost_estimate,
        )
        if not isinstance(result.status, str) or result.status != "available":
            return _unavailable_friction_fields(result.reason)
        gross_bps = None if result.q50_return is None else result.q50_return * 10_000.0
        net_bps = None if result.net_expected_return is None else result.net_expected_return * 10_000.0
        return {
            "gross_expected_edge_bps": gross_bps,
            "estimated_total_cost_bps": result.cost_bps,
            "net_expected_edge_bps": net_bps,
            "edge_to_cost_ratio": result.return_to_cost_ratio,
            "cost_stress_scenario": "base_order_size",
            "friction_status": result.status,
            "friction_reason": result.reason,
            "gross_expected_return": result.q50_return,
            "q10_expected_return": result.q10_return,
            "q50_expected_return": result.q50_return,
            "q90_expected_return": result.q90_return,
            "expected_return_horizon_days": result.horizon_days,
            "net_q10_expected_return": result.net_q10_return,
            "net_expected_return": result.net_expected_return,
            "net_q90_expected_return": result.net_q90_return,
            "expected_return_order_value_eur": result.order_value_eur,
            "expected_return_cost_bps": result.cost_bps,
            "expected_return_cost_eur": result.cost_eur,
            "expected_return_cost_ratio": result.return_to_cost_ratio,
            "expected_return_distribution_version": result.distribution_version,
            "expected_return_source_dataset": result.source_dataset,
        }
    selected_scenario = str(scenario or "base").strip().lower()
    if evidence_score is None:
        return _unavailable_friction_fields("Friction-adjusted edge unavailable because the evidence score is missing.")
    result = estimate_friction_edge(evidence_score, volatility, costs, selected_scenario)
    return {
        "gross_expected_edge_bps": result.gross_bps,
        "estimated_total_cost_bps": result.cost_bps,
        "net_expected_edge_bps": result.net_bps,
        "edge_to_cost_ratio": result.edge_to_cost_ratio,
        "cost_stress_scenario": result.scenario,
        "friction_status": result.status,
        "friction_reason": result.reason,
        "gross_expected_return": None,
        "q10_expected_return": None,
        "q50_expected_return": None,
        "q90_expected_return": None,
        "expected_return_horizon_days": None,
        "net_q10_expected_return": None,
        "net_expected_return": None,
        "net_q90_expected_return": None,
        "expected_return_order_value_eur": None,
        "expected_return_cost_bps": None,
        "expected_return_cost_eur": None,
        "expected_return_cost_ratio": None,
        "expected_return_distribution_version": "migration-legacy-v0",
        "expected_return_source_dataset": "score_to_edge_proxy_legacy",
    }


def _unavailable_friction_fields(reason: str) -> dict[str, object]:
    return {
        "gross_expected_edge_bps": None,
        "estimated_total_cost_bps": None,
        "net_expected_edge_bps": None,
        "edge_to_cost_ratio": None,
        "cost_stress_scenario": "unavailable",
        "friction_status": "unavailable",
        "friction_reason": reason,
        "gross_expected_return": None,
        "q10_expected_return": None,
        "q50_expected_return": None,
        "q90_expected_return": None,
        "expected_return_horizon_days": None,
        "net_q10_expected_return": None,
        "net_expected_return": None,
        "net_q90_expected_return": None,
        "expected_return_order_value_eur": None,
        "expected_return_cost_bps": None,
        "expected_return_cost_eur": None,
        "expected_return_cost_ratio": None,
        "expected_return_distribution_version": "expected-return-distribution.v1",
        "expected_return_source_dataset": "forecast_return_distribution",
    }


def _configured_friction_costs(config: AppConfig, instrument_id: str) -> dict[str, float] | None:
    try:
        base = estimate_execution_cost(config, instrument_id, 0.0).total_cost_bps
    except Exception:
        return None
    return {"low": base * 0.75, "base": base, "high": base * 1.5}


def _positive_order_value(value: object) -> float | None:
    parsed = _safe_float(value)
    return abs(parsed) if parsed is not None and parsed != 0.0 else None


def _order_size_cost_estimate(config: AppConfig, instrument_id: str, value: object) -> dict[str, object] | None:
    order_value = _positive_order_value(value)
    if order_value is None:
        return None
    try:
        return estimate_execution_cost(config, instrument_id, order_value).as_dict()
    except Exception:
        return None


def _calibration_info(lookup: dict[str, dict[str, object]], instrument_id: str) -> dict[str, object]:
    info = lookup.get(str(instrument_id))
    if not info:
        return {
            "score": None,
            "label": "Calibration pending: no matured local forecast rows",
        }
    return info


def _portfolio_fit_info(lookup: dict[str, dict[str, object]], instrument_id: str) -> dict[str, object]:
    info = lookup.get(str(instrument_id))
    if not info:
        return {
            "score": None,
            "label": "Portfolio fit pending: not enough yfinance overlap with the benchmark.",
        }
    return info


def _sector_theme_warning(identity: object | None) -> str:
    if identity is None:
        return "Sector/theme concentration not evaluated: instrument is missing from configured universe metadata."
    role = str(getattr(identity, "role", "") or "").lower()
    sector = str(getattr(identity, "sector", "") or "").strip()
    theme = str(getattr(identity, "theme", "") or "").strip()
    if role in {"sector", "theme"} or sector or theme:
        labels = []
        if sector:
            labels.append(f"sector {sector}")
        if theme:
            labels.append(f"theme {theme}")
        descriptor = ", ".join(labels) if labels else f"role {role}"
        return f"Sector/theme warning: {descriptor}. Benchmark attribution may reflect concentrated exposure or regime effects."
    return "No specific sector/theme tag in configured metadata; benchmark attribution is still descriptive, not causal."


def _benchmark_attribution_info(lookup: dict[str, dict[str, object]], instrument_id: str) -> dict[str, object]:
    info = lookup.get(str(instrument_id))
    if not info:
        return {
            "benchmark_id": None,
            "period_days": None,
            "label": "Benchmark attribution pending: not enough clean yfinance price overlap.",
            "instrument_return": None,
            "benchmark_return": None,
            "beta_to_benchmark": None,
            "correlation_to_benchmark": None,
            "alpha_proxy": None,
            "alpha_t_stat": None,
            "sector_return": None,
            "sector_relative_return": None,
            "sector_beta": None,
            "sector_correlation": None,
            "sector_alpha_proxy": None,
            "sector_attribution_status": "N/A",
            "theme_return": None,
            "theme_relative_return": None,
            "theme_beta": None,
            "theme_correlation": None,
            "theme_alpha_proxy": None,
            "theme_attribution_status": "N/A",
            "theme_sample_size": None,
            "sample_size": None,
            "as_of": None,
            "source_dataset": "adjusted_price_returns",
        }
    return info


def _cash_comparison_info(
    lookup: Mapping[str, Mapping[str, object]],
    instrument_id: str,
    *,
    expected_currency: str,
) -> dict[str, object]:
    validated = validate_cash_comparison_result(
        lookup.get(str(instrument_id)),
        expected_currency=expected_currency,
        expected_instrument_id=instrument_id,
    )
    value = validated.as_dict()
    return {
        "cash_instrument_return": value.get("instrument_return"),
        "cash_return": value.get("cash_return"),
        "excess_over_cash": value.get("excess_over_cash"),
        "cash_instrument_id": value.get("instrument_id"),
        "cash_currency": value.get("currency"),
        "cash_unit": value.get("unit"),
        "cash_dataset_kind": value.get("dataset_kind"),
        "cash_start_date": value.get("start_date"),
        "cash_end_date": value.get("end_date"),
        "cash_horizon_years": value.get("horizon_years"),
        "cash_rate": value.get("rate"),
        "cash_vintage": value.get("vintage"),
        "cash_comparison_status": value["status"],
        "cash_comparison_reason": value.get("reason"),
        "cash_source_id": value.get("source_id"),
        "cash_source_authority": value.get("source_authority"),
        "cash_source_checksum": value.get("source_checksum"),
        "cash_source_terms": value.get("source_terms"),
        "cash_methodology": value.get("methodology"),
        "cash_mapping_methodology": value.get("mapping_methodology"),
        "cash_day_count": value.get("day_count"),
        "cash_compounding": value.get("compounding"),
        "cash_reinvestment": value.get("reinvestment"),
        "cash_effective_at": value.get("effective_at"),
        "cash_published_at": value.get("published_at"),
        "cash_available_at": value.get("available_at"),
        "cash_curve_id": value.get("curve_id"),
        "cash_curve_version": value.get("curve_version"),
        "cash_curve_revision": value.get("curve_revision"),
        "cash_curve_type": value.get("curve_type"),
        "cash_extrapolation_allowed": value.get("extrapolation_allowed"),
        "cash_fallback": value.get("fallback"),
        "cash_fallback_from": value.get("fallback_from"),
        "cash_interpolation": value.get("interpolation"),
        "cash_freshness": value.get("freshness"),
        "cash_freshness_status": value.get("freshness_status"),
        "cash_decision_time": value.get("decision_time"),
        "cash_knowledge_cutoff": value.get("knowledge_cutoff"),
        "inflation_context": value.get("inflation_context"),
    }


def _build_local_cash_comparison_lookup(
    config: AppConfig,
    prices: pd.DataFrame,
    *,
    as_of: object | None = None,
) -> dict[str, Mapping[str, object]]:
    mappings = load_risk_free_proxy_mappings()
    if not mappings:
        return {
            instrument_id: {
                "status": "unavailable",
                "reason": "No valid local risk-free proxy mapping is configured.",
                "execution_allowed": False,
            }
            for instrument_id in config.universe.enabled_ids
        }
    if prices.empty or not {
        "etf_id",
        "date",
        "adjusted_close",
    }.issubset(prices.columns):
        return {}
    warehouse = MacroWarehouse()
    output: dict[str, Mapping[str, object]] = {}
    frame = prices.loc[:, ["etf_id", "date", "adjusted_close"]].copy()
    try:
        decision = pd.Timestamp.now(tz="UTC") if as_of is None else pd.Timestamp(as_of)
    except (TypeError, ValueError, OverflowError):
        return {}
    if pd.isna(decision) or decision.tzinfo is None:
        return {}
    decision = decision.tz_convert("UTC")
    identities = config.universe.by_id()
    for instrument_id in config.universe.enabled_ids:
        identity = identities.get(instrument_id)
        raw_rows = frame.loc[frame["etf_id"].astype(str) == instrument_id]
        if raw_rows.empty:
            continue
        try:
            rows = validated_adjusted_price_frame(
                raw_rows.loc[:, ["date", "adjusted_close"]]
            ).rename(columns={"value": "adjusted_close"})
        except (TypeError, ValueError) as exc:
            output[instrument_id] = {
                "status": "unavailable",
                "reason": f"adjusted price evidence is malformed: {exc}",
                "execution_allowed": False,
            }
            continue
        rows["date"] = pd.to_datetime(rows["date"], utc=True)
        rows = rows.sort_values("date")
        rows = rows.loc[
            rows["date"].dt.normalize() + pd.Timedelta(days=1) <= decision
        ]
        if identity is None or len(rows) < 2:
            continue
        comparison_rows = rows.tail(_CASH_COMPARISON_RETURN_WINDOW + 1)
        start_date = comparison_rows.iloc[0]["date"].date().isoformat()
        end_date = comparison_rows.iloc[-1]["date"].date().isoformat()
        adjusted_prices = comparison_rows.loc[:, ["date", "adjusted_close"]]
        output[instrument_id] = warehouse.cash_comparison(
            root=CASH_MACRO_ROOT,
            mappings=mappings,
            instrument_id=instrument_id,
            currency=identity.currency,
            start_date=start_date,
            end_date=end_date,
            decision_time=adjusted_endpoint_available_at(end_date),
            adjusted_prices=adjusted_prices,
        )
    return output


def _crowding_info(lookup: dict[str, object], instrument_id: str) -> dict[str, object]:
    row = lookup.get(str(instrument_id))
    if row is None:
        return {
            "cluster_id": None,
            "cluster_label": "Correlation clustering unavailable",
            "crowding_warning": "correlation_clustering_unavailable",
            "average_peer_correlation": None,
            "sample_size": None,
            "pair_sample_size": None,
            "cluster_weight": None,
            "cluster_risk_contribution": None,
            "ranking_coverage": None,
            "top_ranked_concentration": None,
            "top_ranked_theme_concentration": None,
            "top_ranked_theme_warning": "no_theme_concentration_warning",
            "as_of": None,
            "source_dataset": "adjusted_price_returns",
        }
    return {
        "cluster_id": getattr(row, "cluster_id", None),
        "cluster_label": getattr(row, "cluster_label", "Correlation cluster"),
        "crowding_warning": getattr(row, "crowding_warning", "no_cluster_warning"),
        "average_peer_correlation": getattr(row, "average_peer_correlation", None),
        "sample_size": getattr(row, "sample_size", None),
        "pair_sample_size": getattr(row, "pair_sample_size", None),
        "cluster_weight": getattr(row, "cluster_weight", None),
        "cluster_risk_contribution": getattr(row, "cluster_risk_contribution", None),
        "ranking_coverage": getattr(row, "ranking_coverage", None),
        "top_ranked_concentration": getattr(row, "top_ranked_concentration", None),
        "top_ranked_theme_concentration": getattr(row, "top_ranked_theme_concentration", None),
        "top_ranked_theme_warning": getattr(row, "top_ranked_theme_warning", "no_theme_concentration_warning"),
        "as_of": getattr(row, "as_of", None),
        "source_dataset": getattr(row, "source_dataset", "adjusted_price_returns"),
    }


def _cache_revision_matches(path: Path, universe_revision: str) -> bool:
    metadata_path = Path(f"{path}.meta.json")
    if not metadata_path.exists():
        return False
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(payload, dict) and str(payload.get("universe_revision") or "") == universe_revision


def _backtest_trust_lookup(
    directory: Path = BACKTESTS_DIR,
    *,
    universe_revision: str | None = None,
) -> dict[str, dict[str, object]]:
    if universe_revision is None:
        universe_revision = load_universe().revision
    results_path = directory / "backtest_results.csv"
    signal_path = directory / "signal_log.csv"
    if not results_path.exists():
        return {}
    if not _cache_revision_matches(results_path, universe_revision):
        return {}
    try:
        results = pd.read_csv(results_path)
    except Exception:
        return {}
    if results.empty or "strategy_name" not in results:
        return {}
    signal_row = results[results["strategy_name"].astype(str) == "signal_strategy"]
    if signal_row.empty:
        return {}
    row = signal_row.iloc[-1]
    quality = str(row.get("backtest_quality") or "low")
    wf_periods = int(_safe_float(row.get("n_walk_forward_periods")) or 0)
    pbo = _safe_float(row.get("pbo_probability_backtest_overfitting"))
    sensitivity = str(row.get("parameter_sensitivity_status") or "unknown")
    base_score = _backtest_quality_score(quality, wf_periods, pbo, sensitivity)
    signal_counts: dict[str, int] = {}
    if signal_path.exists() and _cache_revision_matches(signal_path, universe_revision):
        try:
            signal_log = pd.read_csv(signal_path)
            if "etf_id" in signal_log:
                signal_counts = {str(key): int(value) for key, value in signal_log["etf_id"].astype(str).value_counts().items()}
        except Exception:
            signal_counts = {}
    output: dict[str, dict[str, object]] = {"__strategy__": {"score": base_score, "quality": quality, "wf": wf_periods, "pbo": pbo, "sensitivity": sensitivity}}
    for instrument_id, count in signal_counts.items():
        coverage_bonus = min(count / max(wf_periods, 1), 1.0) if wf_periods else 0.0
        score = _clamp_score_10(base_score - 1.0 + coverage_bonus)
        output[instrument_id] = {
            "score": round(score, 1),
            "label": _backtest_label(score, quality, wf_periods, pbo, sensitivity, count),
        }
    return output


def _backtest_trust_info(lookup: dict[str, dict[str, object]], instrument_id: str, *, candidate: bool) -> dict[str, object]:
    if candidate:
        return {"score": None, "label": "Candidate not backtested: no local walk-forward history for this ad-hoc row."}
    info = lookup.get(str(instrument_id))
    if info:
        return info
    strategy = lookup.get("__strategy__")
    if not strategy:
        return {"score": None, "label": "Backtest trust pending: run the backtest to evaluate this method."}
    score = _safe_float(strategy.get("score"))
    label = _backtest_label(
        score or 0.0,
        str(strategy.get("quality") or "low"),
        int(_safe_float(strategy.get("wf")) or 0),
        _safe_float(strategy.get("pbo")),
        str(strategy.get("sensitivity") or "unknown"),
        0,
    )
    return {"score": score, "label": label}


def _backtest_quality_score(quality: str, wf_periods: int, pbo: float | None, sensitivity: str) -> float:
    score = 4.0
    if quality == "medium":
        score += 2.0
    if wf_periods >= 20:
        score += 1.0
    elif wf_periods >= 5:
        score += 0.5
    if pbo is not None:
        if pbo <= 0.33:
            score += 1.0
        elif pbo > 0.66:
            score -= 1.0
    if sensitivity == "stable":
        score += 1.0
    elif sensitivity == "fragile":
        score -= 1.0
    return round(_clamp_score_10(score), 1)


def _backtest_label(score: float, quality: str, wf_periods: int, pbo: float | None, sensitivity: str, signal_count: int) -> str:
    level = "Medium trust" if score >= 6.0 else "Low trust"
    pbo_text = "n/a" if pbo is None else f"{pbo:.2f}"
    return (
        f"{level}: {quality} backtest, {wf_periods} walk-forward periods, "
        f"PBO {pbo_text}, sensitivity {sensitivity}, instrument signals {signal_count}."
    )


def _candidate_momentum_raw(row: pd.Series) -> float | None:
    weighted = _weighted_values(
        [
            (_safe_float(row.get("return_3m")), 0.40),
            (_safe_float(row.get("return_6m")), 0.35),
            (_safe_float(row.get("return_12m")), 0.25),
        ]
    )
    return None if weighted is None else _clamp(tanh(weighted / 0.20))


def _candidate_trend_raw(row: pd.Series) -> float | None:
    parts: list[tuple[float, float]] = []
    for column, weight in (("sma50_signal", 0.40), ("sma200_signal", 0.60)):
        value = _bool_like(row.get(column))
        if value is not None:
            parts.append((1.0 if value else -1.0, weight))
    return _weighted_values(parts)


def _candidate_risk_raw(row: pd.Series) -> float | None:
    vol = _safe_float(row.get("volatility_60d_ann"))
    drawdown = _safe_float(row.get("current_drawdown"))
    parts: list[tuple[float, float]] = []
    if vol is not None:
        parts.append((_clamp((0.30 - vol) / 0.30), 0.55))
    if drawdown is not None:
        parts.append((_clamp((drawdown + 0.25) / 0.25), 0.45))
    return _weighted_values(parts)


def _candidate_relative_strength_raw(row: pd.Series, reference: float | None) -> float | None:
    if reference is None:
        return None
    value = _safe_float(row.get("return_6m"))
    if value is None:
        value = _safe_float(row.get("return_12m"))
    if value is None:
        value = _safe_float(row.get("return_3m"))
    if value is None:
        return None
    return _clamp(tanh((value - reference) / 0.15))


def _candidate_momentum_why(row: pd.Series) -> str:
    return (
        f"Medium-term yfinance returns: 3m {_fmt_pct(row.get('return_3m'))}, "
        f"6m {_fmt_pct(row.get('return_6m'))}, 12m {_fmt_pct(row.get('return_12m'))}."
    )


def _candidate_trend_why(row: pd.Series) -> str:
    return f"SMA50 is {_fmt_bool(row.get('sma50_signal'))}; SMA200 is {_fmt_bool(row.get('sma200_signal'))}."


def _candidate_risk_why(row: pd.Series) -> str:
    return f"Current drawdown {_fmt_pct(row.get('current_drawdown'))}; 60-day annualised volatility {_fmt_pct(row.get('volatility_60d_ann'))}."


def _candidate_relative_strength_why(row: pd.Series, reference: float | None) -> str:
    if reference is None:
        return "No candidate peer return reference is available."
    return f"Compares this candidate's 6m/12m return with the candidate-list median of {_fmt_pct(reference)}."


def _candidate_value_why(row: pd.Series) -> str:
    if _safe_float(row.get("value_score_10")) is None:
        return "No usable yfinance valuation fields are present in the latest candidate report, so stock value is excluded."
    return (
        f"Value score uses available yfinance valuation fields. "
        f"Earnings yield {_fmt_pct(row.get('earnings_yield'))}; FCF yield {_fmt_pct(row.get('fcf_yield'))}."
    )


def _candidate_quality_why(row: pd.Series) -> str:
    if _safe_float(row.get("quality_score_10")) is None:
        return "No usable yfinance profitability/leverage fields are present in the latest candidate report, so stock quality is excluded."
    return (
        f"Quality score uses available yfinance profitability and safety fields. "
        f"ROE {_fmt_pct(row.get('roe'))}; operating margin {_fmt_pct(row.get('operating_margin'))}; debt/equity {_fmt_number(row.get('debt_to_equity'))}."
    )


def _candidate_revision_why(row: pd.Series) -> str:
    if _safe_float(row.get("analyst_revision_score_10")) is None:
        return "No usable yfinance analyst revision data is present in the latest candidate report, so this low-authority component is excluded."
    return "Analyst/revision score uses available Yahoo estimate or recommendation context and remains low-authority."


def _latest_price_lookup(prices: pd.DataFrame) -> dict[str, dict[str, object]]:
    if prices.empty or not {"etf_id", "date"}.issubset(prices.columns):
        return {}
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    price_column = "adjusted_close" if "adjusted_close" in frame else "close"
    rows = (
        frame.dropna(subset=["date"])
        .sort_values(["etf_id", "date"])
        .groupby("etf_id", sort=False)
        .tail(1)
    )
    return {
        str(row["etf_id"]): {
            "date": row["date"].date().isoformat(),
            "price": _safe_float(row.get(price_column)),
        }
        for _, row in rows.iterrows()
    }


def _price_quality_lookup(prices: pd.DataFrame) -> dict[str, dict[str, object]]:
    if prices.empty or not {"etf_id", "date"}.issubset(prices.columns):
        return {}
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if "adjusted_close" not in frame:
        frame["adjusted_close"] = pd.NA
    if "is_adjusted" not in frame:
        frame["is_adjusted"] = True
    output: dict[str, dict[str, object]] = {}
    for etf_id, group in frame.groupby("etf_id", sort=False):
        output[str(etf_id)] = {
            "date": group["date"].max().date().isoformat() if group["date"].notna().any() else "",
            "rows": int(group["adjusted_close"].notna().sum()),
            "missing_adjusted_close": int(group["adjusted_close"].isna().sum()),
            "non_adjusted_count": int((group["is_adjusted"].astype(str).str.lower() == "false").sum()),
        }
    return output


def _price_liquidity_lookup(prices: pd.DataFrame) -> dict[str, dict[str, object]]:
    if prices.empty or not {"etf_id", "date", "close", "volume"}.issubset(prices.columns):
        return {}
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("close", "high", "low", "volume"):
        if column not in frame:
            frame[column] = pd.NA
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    output: dict[str, dict[str, object]] = {}
    for etf_id, group in frame.sort_values("date").groupby("etf_id", sort=False):
        tail = group.tail(20)
        turnover = (tail["close"] * tail["volume"]).replace([float("inf"), float("-inf")], pd.NA).dropna()
        spread = ((tail["high"] - tail["low"]) / tail["close"]).replace([float("inf"), float("-inf")], pd.NA).dropna()
        output[str(etf_id)] = {
            "avg_turnover_20": float(turnover.mean()) if not turnover.empty else None,
            "spread_proxy_20": float(spread.mean()) if not spread.empty else None,
        }
    return output


def _etf_exposure_lookup() -> dict[str, dict[str, object]]:
    try:
        holdings = load_reference_dataset("etf_holdings")
    except Exception:
        return {}
    if holdings.empty or not {"etf_id", "weight"}.issubset(holdings.columns):
        return {}
    frame = holdings.copy()
    frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce")
    output: dict[str, dict[str, object]] = {}
    for etf_id, group in frame.dropna(subset=["weight"]).groupby("etf_id", sort=False):
        weights = group["weight"].sort_values(ascending=False)
        output[str(etf_id)] = {
            "holding_count": int(len(weights)),
            "top_weight_sum": float(weights.head(10).sum()),
            "largest_weight": float(weights.iloc[0]) if not weights.empty else None,
        }
    return output


def _evidence_maturity(
    *,
    rows: object,
    final_score: float | None,
    evidence_quality: float | None,
    risk_friction: float | None,
    metrics: dict[str, object],
    existing_warnings: list[str],
) -> dict[str, object]:
    rows_number = _safe_float(rows)
    sample_days = None if rows_number is None else max(0, int(rows_number))
    warnings: list[str] = []

    if sample_days is None:
        state = "unknown"
        label = "Evidence maturity unknown: no valid price-row count is available."
        warnings.append("Sample length is unknown, so maturity cannot be trusted.")
    elif sample_days < 120:
        state = "young_noisy"
        label = f"Young/noisy evidence: only {sample_days} valid price rows."
        warnings.append("Less than 120 valid price rows are available.")
    elif sample_days < 252:
        state = "young"
        label = f"Young evidence: {sample_days} valid price rows, less than one trading year."
        warnings.append("Less than one trading year of valid price rows is available.")
    elif sample_days < 504:
        state = "developing"
        label = f"Developing evidence: {sample_days} valid price rows."
    else:
        state = "mature_price_history"
        label = f"Mature price-history proxy: {sample_days} valid price rows."

    if final_score is not None:
        if sample_days is not None and sample_days < 252 and final_score >= 7.5:
            warnings.append("High score is based on less than one trading year of price history.")
        if evidence_quality is None and final_score >= 7.5:
            warnings.append("High score has unknown evidence quality.")
        elif evidence_quality is not None and final_score >= 8.0 and evidence_quality < 7.0:
            warnings.append("High score conflicts with weaker evidence quality.")
        if risk_friction is None and final_score >= 7.5:
            warnings.append("High score has unknown risk/friction support.")
        elif risk_friction is not None and final_score >= 8.0 and risk_friction < 6.0:
            warnings.append("High score conflicts with weaker risk/friction support.")

    drawdown = _first_metric(metrics, ("current_drawdown", "drawdown_current"))
    return_3m = _first_metric(metrics, ("return_3m", "momentum_60d"))
    return_6m = _first_metric(metrics, ("return_6m", "momentum_120d"))
    return_12m = _first_metric(metrics, ("return_12m", "momentum_180d"))
    if drawdown is not None:
        if return_3m is not None and return_3m >= 0.20 and drawdown > -0.05:
            warnings.append("Large 3-month return with very small current drawdown should be treated as a sanity-check item.")
        if return_6m is not None and return_6m >= 0.35 and drawdown > -0.08:
            warnings.append("Large 6-month return with limited current drawdown needs benchmark and slippage review.")
        if return_12m is not None and return_12m >= 0.60 and drawdown > -0.10:
            warnings.append("Large 12-month return with limited current drawdown may be regime-driven or overfit.")

    warnings = _unique_strings(warnings)
    too_good = next(
        (warning for warning in warnings if "High score" in warning or "Large " in warning),
        "No sanity warning",
    )
    return {
        "sample_days": sample_days,
        "state": state,
        "label": label,
        "warnings": warnings,
        "too_good_to_be_true_warning": too_good,
        "warning_count": len(_unique_strings([*existing_warnings, *warnings])),
    }


def _first_metric(metrics: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _safe_float(metrics.get(key))
        if value is not None:
            return value
    return None


def _unique_strings(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _summary_reason(
    decision: str,
    final_score: float | None,
    components: list[SimpleScoreComponent],
    *,
    flags: list[str] | None = None,
    quality_score: float | None = None,
    risk_friction_score: float | None = None,
) -> str:
    if final_score is None:
        return "Manual Review: no valid yfinance algorithm or model components were available."
    valid = [component for component in components if component.score_10 is not None]
    best = max(valid, key=lambda component: component.score_10, default=None)
    weakest = min(valid, key=lambda component: component.score_10, default=None)
    flag_text = f" Flags: {', '.join(flags)}." if flags else ""
    quality_text = "" if quality_score is None else f" Quality {quality_score:.1f}/10."
    friction_text = "" if risk_friction_score is None else f" Risk/friction {risk_friction_score:.1f}/10."
    if best and weakest:
        return (
            f"{decision}: final {final_score:.1f}/10 from {len(valid)} valid components. "
            f"Strongest: {best.label} {best.score_10:.1f}/10; weakest: {weakest.label} {weakest.score_10:.1f}/10."
            f"{quality_text}{friction_text}{flag_text}"
        )
    return f"{decision}: final {final_score:.1f}/10 from available yfinance evidence.{quality_text}{friction_text}{flag_text}"


def _momentum_why(metrics: dict[str, object]) -> str:
    return f"Momentum from yfinance adjusted prices: 60d {_fmt_pct(metrics.get('momentum_60d'))}, 120d {_fmt_pct(metrics.get('momentum_120d'))}."


def _trend_why(metrics: dict[str, object]) -> str:
    trend = _safe_float(metrics.get("trend_200"))
    if trend is None:
        return "Long-trend value is unavailable."
    return "Price is above its 200-day trend filter." if trend > 0 else "Price is below its 200-day trend filter."


def _risk_why(metrics: dict[str, object]) -> str:
    return f"Current drawdown {_fmt_pct(metrics.get('drawdown_current'))}; 60-day annualised volatility {_fmt_pct(metrics.get('vol_60d_ann'))}."


def _weighted_values(values: Iterable[tuple[float | None, float]]) -> float | None:
    weighted = 0.0
    total_weight = 0.0
    for value, weight in values:
        if value is None or weight <= 0:
            continue
        weighted += float(value) * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return _clamp(weighted / total_weight)


def _weighted_score_10(values: Iterable[tuple[float | None, float]]) -> float | None:
    weighted = 0.0
    total_weight = 0.0
    for value, weight in values:
        if value is None or weight <= 0:
            continue
        weighted += float(value) * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return weighted / total_weight


def _score_by_key(components: list[SimpleScoreComponent], key: str) -> float | None:
    for component in components:
        if component.key == key:
            return component.score_10
    return None


def _safe_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        number = float(value)
    except Exception:
        return None
    return number if isfinite(number) else None


def _as_bool(value: object) -> bool:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _safe_int(value: object) -> int | None:
    number = _safe_float(value)
    return None if number is None else int(number)


def _noneable_str(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def _clamp_score_10(value: float) -> float:
    return max(0.0, min(10.0, float(value)))


def _score_10_to_raw(score_10: float | None) -> float | None:
    if score_10 is None:
        return None
    return _clamp((float(score_10) / 5.0) - 1.0)


def _parse_date(value: object) -> date | None:
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _business_days_between(start: date, end: date) -> int:
    if start >= end:
        return 0
    days = pd.bdate_range(start=start, end=end, inclusive="right")
    return int(len(days))


def _fmt_pct(value: object) -> str:
    number = _safe_float(value)
    return "n/a" if number is None else f"{number:+.1%}"


def _fmt_bool(value: object) -> str:
    bool_value = _bool_like(value)
    if bool_value is None:
        return "n/a"
    return "positive" if bool_value else "negative"


def _fmt_number(value: object) -> str:
    number = _safe_float(value)
    return "n/a" if number is None else f"{number:.2f}"


def _bool_like(value: object) -> bool | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _split_flags(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.replace("|", ",").split(",") if part.strip()]


def _pending_candidate_portfolio_label(source_group: str) -> str:
    if source_group == SPAREBANKEN_TIER_LABEL:
        return "Sparebanken portfolio context is yfinance-only and pending until refreshed."
    return "Secondary tier portfolio context is yfinance-only and pending until refreshed."


def _is_stock_like_asset_type(asset_type: str) -> bool:
    return asset_type in {"Stock", "Certificate", "Equity certificate"}


def _isin_status(isin: object) -> str:
    value = str(isin or "").strip()
    if not value:
        return "missing"
    if value.lower() == "needs_verification":
        return "needs_verification"
    return "verified"
