from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import pandas as pd

from etf_cockpit.backtest.engine import (
    BacktestReport,
    quality_momentum_evidence_checksum,
    run_backtest,
)
from etf_cockpit.backtest.metrics import max_drawdown
from etf_cockpit.chatgpt_bridge.export_pack import export_review_pack
from etf_cockpit.chatgpt_bridge.import_audit import import_audit_json
from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAudit, ChatGPTAuditV2
from etf_cockpit.core.config import AppConfig, load_config
from etf_cockpit.core.atomic_io import (
    atomic_write_group,
    read_atomic_group,
)
from etf_cockpit.core.logging import append_jsonl, configure_logging
from etf_cockpit.core.paths import (
    BACKTESTS_DIR,
    CONFIG_DIR,
    ETF_FUND_TOTAL_RETURN_PATH,
    ensure_project_dirs,
)
from etf_cockpit.core.timing import timed_step
from etf_cockpit.core.types import DataQualityReport, SignalResult
from etf_cockpit.core.workflow import PublicationScopeFactory
from etf_cockpit.core.versioning import (
    current_settings_identity,
    current_settings_revision,
    ensure_run_manifest,
    settings_bound_run_id,
)
from etf_cockpit.data.duckdb_store import initialise_store, load_features, load_holdings, load_prices, write_features
from etf_cockpit.data.etf_economics import (
    ClosureProxyPolicy,
    ETF_ECONOMICS_PATH,
    EtfEconomicsObservation,
    TotalReturnEvidence,
    load_closure_proxy_policy,
    load_etf_economics_records,
    load_total_return_evidence,
)
from etf_cockpit.data.etf_structure import structure_confidence_caps
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
from etf_cockpit.data.fundamentals import load_fundamental_evidence
from etf_cockpit.data.identity_master import (
    IdentityMasterStore,
)
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.import_pipeline import commit_price_import, rollback_latest_price_import as rollback_price_store
from etf_cockpit.data.parsed_disclosures import read_etf_report_records
from etf_cockpit.data.reference_data import (
    ETF_METADATA_CLEAN_PATH,
    commit_reference_import,
)
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH
from etf_cockpit.data.trade_candidate_analysis import (
    load_candidate_price_binding,
)
from etf_cockpit.data.validation import validate_prices
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.forecast_scores import (
    configured_forecast_request_identity,
    forecast_component_maps,
    forecast_return_distributions,
    load_latest_forecasts,
)
from etf_cockpit.models.local_weights import LocalModelStatus
from etf_cockpit.models.registry import model_availability, model_diagnostics
from etf_cockpit.portfolio.benchmark_reference_contract import (
    CanonicalBenchmarkRegistry,
    VwceAnchorEvidence,
    load_canonical_benchmark_registry,
    resolve_vwce_anchor,
)
from etf_cockpit.signals.signal_pipeline import generate_signals
from etf_cockpit.application.derived_cache import (
    _cache_matches_universe,
    _cached_backtest_binding_matches,
    _cached_structure_columns_match,
    _calculation_window,
    _current_universe_revision,
    _forecast_request_identity,
    _price_snapshot_binding,
    _read_bound_cache_payload,
    _reference_binding,
    _reference_identity_hash,
    _universe_cache_meta_path,
    _write_bound_cache_group,
    _write_universe_cache_metadata,
)
from etf_cockpit.application.structural_evidence import (
    _load_local_structural_evidence,
    _load_structure_caps,
)
from etf_cockpit.application.reference_context import (
    _backtest_calculation_context,
    _backtest_prices_for_reference,
    _benchmark_reference_snapshot_inputs,
    _reference_context_from_inputs,
    BENCHMARK_REFERENCE_REGISTRY_PATH,
)
from etf_cockpit.application.economics_inputs import (
    _etf_economics_snapshot_inputs,
    _trusted_etf_economics_records,
)
from etf_cockpit.application.forecast_service import (
    _postprocess_forecast_benchmark_fields,
    ForecastService,
)
from etf_cockpit.application.feature_service import FeatureService
from etf_cockpit.application.backtest_service import (
    _empty_backtest_report,
    _normalise_operational_evidence_rows,
    _open_backtest_calendar_identity_resolver,
    _operational_evidence_input_binding,
    _run_backtest_compatibly,
    BacktestService,
)
from etf_cockpit.application.data_service import DataService
from etf_cockpit.application.signal_service import (
    _run_decision_shadow_guard,
    SignalService,
)


def decision_rank_route(
    consumer: str,
    rank_scores: Mapping[str, object] | None = None,
    *,
    promotion_record: Mapping[str, object] | None = None,
    cutover_enabled: bool | None = None,
) -> dict[str, object]:
    """Route a facade consumer through the configured, record-gated rank cutover."""

    from etf_cockpit.analysis.decision.rank_validation import route_consumer_rank

    return route_consumer_rank(
        consumer,
        rank_scores or {},
        promotion_record=promotion_record,
        cutover_enabled=cutover_enabled,
    )


@dataclass
class CockpitSnapshot:
    config: AppConfig
    prices: pd.DataFrame
    holdings: pd.DataFrame
    features: pd.DataFrame
    latest_features: pd.DataFrame
    data_report: DataQualityReport
    signals: list[SignalResult]
    forecasts: pd.DataFrame
    backtest: BacktestReport
    model_status: dict[str, bool]
    model_inventory: list[LocalModelStatus]
    candidate_price_binding: Mapping[str, object] | None = None
    # Revision of the canonical universe used to build cached derived data.
    universe_revision: str = ""
    etf_economics_records: tuple[EtfEconomicsObservation, ...] = ()
    etf_fund_total_return: Mapping[str, TotalReturnEvidence] | None = None
    etf_benchmark_total_return: Mapping[str, TotalReturnEvidence] | None = None
    etf_closure_policy: ClosureProxyPolicy | None = None
    benchmark_reference_registry: CanonicalBenchmarkRegistry = field(default_factory=CanonicalBenchmarkRegistry)
    benchmark_reference_instrument: Mapping[str, object] | None = None
    benchmark_reference_currency: str | None = None
    benchmark_reference_horizon_years: float | None = None
    benchmark_reference_start_date: str | None = None
    benchmark_reference_end_date: str | None = None
    benchmark_reference_decision_time: str | None = None
    benchmark_reference_portfolio_ids: tuple[str, ...] = ()
    vwce_anchor_evidence: VwceAnchorEvidence | None = None
    vwce_listing_id: str | None = None
    vwce_conversion_evidence: Mapping[str, object] | None = None


class ChatGPTBridge:
    def __init__(self, config: AppConfig):
        self.config = config

    def export_review_pack(
        self,
        as_of_date: date,
        holdings: pd.DataFrame,
        features: pd.DataFrame,
        signals: list[SignalResult],
        backtest: BacktestReport,
        data_report: DataQualityReport | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> Path:
        return export_review_pack(
            self.config,
            holdings,
            features,
            signals,
            backtest,
            as_of_date=as_of_date,
            data_report=data_report,
            publish_guard=publish_guard,
        )

    def import_audit_json(self, path: Path) -> ChatGPTAudit | ChatGPTAuditV2:
        return import_audit_json(path, self.config)


def build_snapshot(
    force_sample: bool = False,
    *,
    publish_guard: PublicationScopeFactory | None = None,
) -> CockpitSnapshot:
    with timed_step("snapshot", "build"):
        return _build_snapshot(force_sample=force_sample, publish_guard=publish_guard)


def _build_snapshot(
    force_sample: bool = False,
    *,
    publish_guard: PublicationScopeFactory | None = None,
) -> CockpitSnapshot:
    configure_logging()
    ensure_project_dirs()
    config = load_config()
    universe_revision = _current_universe_revision()
    data_service = DataService(config)
    try:
        data_service.update_prices(force_sample=force_sample, publish_guard=publish_guard)
    except TypeError as exc:
        if "publish_guard" not in str(exc):
            raise
        data_service.update_prices(force_sample=force_sample)
    current_ids = set(config.universe.enabled_ids)
    prices = data_service.load_prices()
    if not prices.empty and "etf_id" in prices:
        prices = prices[prices["etf_id"].astype(str).isin(current_ids)].copy()
    holdings_source = load_holdings()
    holdings = holdings_source
    if not holdings.empty and "etf_id" in holdings:
        configured_ids = set(config.universe.configured_enabled_ids)
        holdings = holdings[holdings["etf_id"].astype(str).isin(configured_ids)].copy()
    holdings_for_validation = holdings if not holdings.empty else None
    data_report = data_service.validate_prices(prices, holdings=holdings_for_validation)
    benchmark_reference = _benchmark_reference_snapshot_inputs(
        config,
        data_report.as_of_date,
        holdings_source,
    )
    reference_context = _reference_context_from_inputs(
        benchmark_reference,
        purpose="comparison",
        analysis_id=f"snapshot:{pd.Timestamp(data_report.as_of_date).date().isoformat()}",
    )
    calculation_window = _calculation_window(reference_context, data_report.as_of_date, prices)
    price_binding = (
        None
        if calculation_window is None
        else _price_snapshot_binding(prices, calculation_window=calculation_window)
    )
    feature_service = FeatureService(config, reference_context=reference_context)
    if prices.empty:
        features = pd.DataFrame(columns=["date", "etf_id"])
        latest = pd.DataFrame(columns=["date", "etf_id"])
    else:
        features = feature_service.compute_features(
            data_report.as_of_date,
            prices,
            publish_guard=publish_guard,
        )
        latest = latest_features(features, data_report.as_of_date)
    status = model_availability(config)
    inventory = model_diagnostics(config)
    request_identity = configured_forecast_request_identity(config)
    forecasts = (
        load_latest_forecasts(
            universe_revision=universe_revision,
            reference_identity=reference_context.identity,
            price_binding=price_binding,
            forecast_request_identity=request_identity,
        )
        if price_binding is not None
        else pd.DataFrame()
    )
    structure_caps = _load_structure_caps(config.universe.enabled_ids, data_report.as_of_date)
    signals = (
        []
        if latest.empty
        else generate_signals(
            config,
            latest,
            holdings,
            data_report,
            as_of_date=data_report.as_of_date,
            toto_available=status["toto"],
            timesfm_available=status["timesfm"],
            forecast_scores=forecast_component_maps(forecasts),
            forecast_distributions=forecast_return_distributions(forecasts),
            structure_confidence_caps=structure_caps,
        )
    )
    _run_decision_shadow_guard(
        config,
        signals,
        decision_time=data_report.as_of_date,
        latest_features=latest,
        price_history=features,
    )
    backtest = (
        _empty_backtest_report("Backtest skipped because no clean prices exist for the current two-tier universe yet.")
        if prices.empty
        else BacktestService(
            config,
            universe_revision=universe_revision,
            reference_context=reference_context,
        ).load_or_run_backtest(
            data_report.as_of_date,
            publish_guard=publish_guard,
        )
    )
    (
        etf_economics_records,
        etf_fund_total_return,
        etf_benchmark_total_return,
        etf_closure_policy,
    ) = _etf_economics_snapshot_inputs(prices, data_report.as_of_date)
    return CockpitSnapshot(
        config=config,
        prices=prices,
        holdings=holdings,
        features=features,
        latest_features=latest,
        data_report=data_report,
        signals=signals,
        forecasts=forecasts,
        backtest=backtest,
        model_status=status,
        model_inventory=inventory,
        candidate_price_binding=load_candidate_price_binding(),
        universe_revision=universe_revision,
        etf_economics_records=etf_economics_records,
        etf_fund_total_return=etf_fund_total_return,
        etf_benchmark_total_return=etf_benchmark_total_return,
        etf_closure_policy=etf_closure_policy,
        benchmark_reference_registry=benchmark_reference["registry"],  # type: ignore[arg-type]
        benchmark_reference_instrument=benchmark_reference["instrument"],  # type: ignore[arg-type]
        benchmark_reference_currency=benchmark_reference["currency"],  # type: ignore[arg-type]
        benchmark_reference_horizon_years=benchmark_reference["horizon_years"],  # type: ignore[arg-type]
        benchmark_reference_start_date=benchmark_reference["start_date"],  # type: ignore[arg-type]
        benchmark_reference_end_date=benchmark_reference["end_date"],  # type: ignore[arg-type]
        benchmark_reference_decision_time=benchmark_reference["decision_time"],  # type: ignore[arg-type]
        benchmark_reference_portfolio_ids=benchmark_reference["reference_ids"],  # type: ignore[arg-type]
        vwce_anchor_evidence=benchmark_reference["anchor"],  # type: ignore[arg-type]
        vwce_listing_id=benchmark_reference["listing_id"],  # type: ignore[arg-type]
        vwce_conversion_evidence=None,
    )


# Compatibility surface (tests/fixtures/refactor_surface/compat_names_v1.json): implementations move to
# etf_cockpit.application.* during the ADR-0002 refactor; these names stay importable and patchable here.
__all__ = [
    "BACKTESTS_DIR",
    "BENCHMARK_REFERENCE_REGISTRY_PATH",
    "BacktestService",
    "CONFIG_DIR",
    "ChatGPTBridge",
    "CockpitSnapshot",
    "DataService",
    "ETF_ECONOMICS_PATH",
    "ETF_FUND_TOTAL_RETURN_PATH",
    "ETF_METADATA_CLEAN_PATH",
    "FUND_HOLDINGS_PATH",
    "FeatureService",
    "ForecastService",
    "IDENTITY_PATH",
    "IdentityMasterStore",
    "SignalService",
    "YFinanceProvider",
    "_backtest_calculation_context",
    "_backtest_prices_for_reference",
    "_benchmark_reference_snapshot_inputs",
    "_build_snapshot",
    "_cache_matches_universe",
    "_cached_backtest_binding_matches",
    "_cached_structure_columns_match",
    "_current_universe_revision",
    "_empty_backtest_report",
    "_etf_economics_snapshot_inputs",
    "_forecast_request_identity",
    "_load_local_structural_evidence",
    "_load_structure_caps",
    "_normalise_operational_evidence_rows",
    "_open_backtest_calendar_identity_resolver",
    "_operational_evidence_input_binding",
    "_postprocess_forecast_benchmark_fields",
    "_price_snapshot_binding",
    "_read_bound_cache_payload",
    "_reference_binding",
    "_reference_context_from_inputs",
    "_reference_identity_hash",
    "_run_backtest_compatibly",
    "_trusted_etf_economics_records",
    "_universe_cache_meta_path",
    "_write_bound_cache_group",
    "_write_universe_cache_metadata",
    "append_jsonl",
    "atomic_write_group",
    "baseline_forecast",
    "build_snapshot",
    "commit_price_import",
    "commit_reference_import",
    "compute_features",
    "configure_logging",
    "current_settings_identity",
    "current_settings_revision",
    "date",
    "decision_rank_route",
    "ensure_project_dirs",
    "ensure_run_manifest",
    "generate_signals",
    "initialise_store",
    "latest_features",
    "load_canonical_benchmark_registry",
    "load_closure_proxy_policy",
    "load_config",
    "load_etf_economics_records",
    "load_features",
    "load_fundamental_evidence",
    "load_holdings",
    "load_latest_forecasts",
    "load_prices",
    "load_total_return_evidence",
    "max_drawdown",
    "model_availability",
    "model_diagnostics",
    "pd",
    "quality_momentum_evidence_checksum",
    "read_atomic_group",
    "read_document_registry",
    "read_etf_report_records",
    "resolve_vwce_anchor",
    "rollback_price_store",
    "run_backtest",
    "settings_bound_run_id",
    "storage_layout",
    "structure_confidence_caps",
    "validate_prices",
    "write_features",
]
