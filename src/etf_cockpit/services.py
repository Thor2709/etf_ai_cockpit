from __future__ import annotations

from datetime import date

import pandas as pd

from etf_cockpit.backtest.engine import (
    quality_momentum_evidence_checksum,
    run_backtest,
)
from etf_cockpit.backtest.metrics import max_drawdown
from etf_cockpit.core.config import load_config
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
from etf_cockpit.core.versioning import (
    current_settings_identity,
    current_settings_revision,
    ensure_run_manifest,
    settings_bound_run_id,
)
from etf_cockpit.data.duckdb_store import initialise_store, load_features, load_holdings, load_prices, write_features
from etf_cockpit.data.etf_economics import (
    ETF_ECONOMICS_PATH,
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
from etf_cockpit.data.validation import validate_prices
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.forecast_scores import (
    load_latest_forecasts,
)
from etf_cockpit.models.registry import model_availability, model_diagnostics
from etf_cockpit.portfolio.benchmark_reference_contract import (
    load_canonical_benchmark_registry,
    resolve_vwce_anchor,
)
from etf_cockpit.signals.signal_pipeline import generate_signals
from etf_cockpit.application.derived_cache import (
    _cache_matches_universe,
    _cached_backtest_binding_matches,
    _cached_structure_columns_match,
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
    SignalService,
)
from etf_cockpit.application.snapshot_builder import (
    _build_snapshot,
    build_snapshot,
    CockpitSnapshot,
)
from etf_cockpit.application.chatgpt_review import ChatGPTBridge
from etf_cockpit.application.decision_rank import decision_rank_route


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
