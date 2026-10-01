"""Presentation-facing compatibility facade for the first ISSUE-0071 wave.

Pages, components and selectors depend on this application boundary instead
of importing storage/provider implementations directly. The underlying
implementations remain compatible while later slices move them behind typed
ports and application commands.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import sqlite3

import pandas as pd

from etf_cockpit.core.paths import LOG_DIR, STATEMENT_FACTS_PATH
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.etf_structure import project_etf_structure
from etf_cockpit.data.event_calendar import load_calendar_events, normalise_event_decision_time
from etf_cockpit.data.capital_allocation import capital_allocation_analysis
from etf_cockpit.data.market_adjustments import CorporateActionCoverage
from etf_cockpit.data.duckdb_store import PRICE_PARQUET, load_prices
from etf_cockpit.data.fx_data import FX_CLEAN_PATH, load_fx_rates
from etf_cockpit.data.local_storage import StorageRevisionConflict, StorageSchemaError, TransactionalStore, storage_layout
from etf_cockpit.data.market_adjustments import CorporateActionStore
from etf_cockpit.data.macro_warehouse import MacroWarehouse, load_risk_free_proxy_mappings
from etf_cockpit.data.provenance import price_staleness_status
from etf_cockpit.data.stock_research import valuation_analysis
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.parsed_disclosures import read_etf_report_records
from etf_cockpit.features.cash_comparison import (
    cash_comparison_from_projection,  # noqa: F401
    cash_comparison_to_projection,  # noqa: F401
)

from etf_cockpit.analysis.fixed_income_analytics import (
    FixedIncomeAnalyticsError,
    FixedIncomeValuationInput,
    calculate_fixed_income_analytics,
)
from etf_cockpit.data.bond_analytics_store import read_bond_analytics
from etf_cockpit.analysis.fixed_income_risk import (
    FixedIncomeRiskError,
    FixedIncomeRiskInput,
    calculate_fixed_income_risk,
)
from etf_cockpit.analysis.etf_tax_context import (
    ETFContextAssumptions,  # noqa: F401
    NetReturnScenario,  # noqa: F401
    build_currency_context,  # noqa: F401
    calculate_core_quality_tax_bias,  # noqa: F401
    calculate_net_return_scenario,  # noqa: F401
    load_tax_hedge_assumptions,  # noqa: F401
)
from etf_cockpit.data.fixed_income_risk_store import read_fixed_income_risk
from etf_cockpit.application.portfolio_valuation import load_portfolio_valuation_history  # noqa: F401
from etf_cockpit.portfolio.performance_series import (
    PerformanceSeries,
    build_portfolio_performance_series,
    performance_series_frame,  # noqa: F401
)
from etf_cockpit.portfolio.holdings_table import build_portfolio_holdings_table
from etf_cockpit.portfolio.forecast_aggregation import (
    PortfolioForecastSnapshot,
    build_portfolio_forecast_snapshot,
)
from etf_cockpit.portfolio.calendar import build_portfolio_calendar

from etf_cockpit.chatgpt_bridge.audit_packet import *  # noqa: F401,F403
from etf_cockpit.data.backup_restore import *  # noqa: F401,F403
from etf_cockpit.data.bitemporal import *  # noqa: F401,F403
from etf_cockpit.data.bulk_cache import *  # noqa: F401,F403
from etf_cockpit.data.decision_journal import *  # noqa: F401,F403
from etf_cockpit.data.forward_evidence_diary import *  # noqa: F401,F403
from etf_cockpit.data.event_calendar import *  # noqa: F401,F403
from etf_cockpit.data.etf_economics import *  # noqa: F401,F403
from etf_cockpit.data.export_tables import *  # noqa: F401,F403
from etf_cockpit.data.fund_documents import *  # noqa: F401,F403
from etf_cockpit.data.fund_holdings import *  # noqa: F401,F403
from etf_cockpit.data.fundamentals import *  # noqa: F401,F403
from etf_cockpit.data.fx_data import *  # noqa: F401,F403
from etf_cockpit.data.market_adjustments import *  # noqa: F401,F403
from etf_cockpit.application.market_clock import *  # noqa: F401,F403
from etf_cockpit.data.health import *  # noqa: F401,F403
from etf_cockpit.data.hybrid_platform import *  # noqa: F401,F403
from etf_cockpit.data.import_export import *  # noqa: F401,F403
from etf_cockpit.data.legal_terms import *  # noqa: F401,F403
from etf_cockpit.data.catalogue import *  # noqa: F401,F403
from etf_cockpit.data.macro_warehouse import *  # noqa: F401,F403
from etf_cockpit.data.anomaly_ledger import *  # noqa: F401,F403
from etf_cockpit.data.stock_research import *  # noqa: F401,F403
from etf_cockpit.backtest.event_engine import *  # noqa: F401,F403
from etf_cockpit.governance.release_certification import *  # noqa: F401,F403
from etf_cockpit.governance.supply_chain_intake import *  # noqa: F401,F403
from etf_cockpit.data.local_storage import *  # noqa: F401,F403
from etf_cockpit.data.identity_master import (
    IdentityMasterSchemaError,
    IdentityMasterStore,
    identity_master_exists,
)
from etf_cockpit.data.fixed_income_terms import (
    FixedIncomeTermsSchemaError,
    FixedIncomeTermsStore,
    fixed_income_terms_exists,
)
from etf_cockpit.data.fixed_income_market_data import (
    FixedIncomeMarketDataSchemaError,
    FixedIncomeMarketDataStore,
    fixed_income_market_data_exists,
)
from etf_cockpit.data.classification import (
    ClassificationOverride,
    ClassificationSchemaError,
    ClassificationStore,
    classification_store_exists,
    read_instrument_context,
    read_classification_projection,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.peer_cohort_store import read_peer_cohort_projection
from etf_cockpit.analysis.financial_sector_adapters import (
    FinancialMetricEvidence,
    FinancialAdapterError,
    FinancialInstitutionProjection,
    build_financial_institution_projection,
    financial_adapter_definition,
    unavailable_financial_projection,
    verify_financial_projection,
)
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.analysis.real_asset_sector_adapters import (
    RealAssetAdapterError,
    RealAssetProjection,
    unavailable_real_asset_projection,
    verify_real_asset_projection,
)
from etf_cockpit.analysis.cyclical_sector_adapters import (
    CyclicalAdapterError,
    CyclicalProjection,
    unavailable_cyclical_projection,
    verify_cyclical_projection,
)
from etf_cockpit.analysis.innovation_sector_adapters import (
    InnovationAdapterError,
    InnovationProjection,
    unavailable_innovation_projection,
    verify_innovation_projection,
)


from etf_cockpit.data.manual_notes import *  # noqa: F401,F403
from etf_cockpit.data.news_context import *  # noqa: F401,F403
from etf_cockpit.data.oam_adapters import *  # noqa: F401,F403
from etf_cockpit.data.parsed_disclosures import *  # noqa: F401,F403
from etf_cockpit.data.etf_structure import *  # noqa: F401,F403
from etf_cockpit.data.provider_registry import *  # noqa: F401,F403
from etf_cockpit.data.privacy import *  # noqa: F401,F403
from etf_cockpit.data.reference_data import *  # noqa: F401,F403
from etf_cockpit.data.run_changes import *  # noqa: F401,F403
from etf_cockpit.application.run_change_context import upstream_run_context  # noqa: F401
from etf_cockpit.data.score_history import *  # noqa: F401,F403
from etf_cockpit.data.source_policy import *  # noqa: F401,F403
from etf_cockpit.data.statement_normalisation import *  # noqa: F401,F403
from etf_cockpit.data.trust_artifacts import *  # noqa: F401,F403
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH
from etf_cockpit.data.universe_store import *  # noqa: F401,F403
from etf_cockpit.data.universe_import import *  # noqa: F401,F403
from etf_cockpit.application.api import *  # noqa: F401,F403
from etf_cockpit.application.contracts import *  # noqa: F401,F403
from etf_cockpit.application.screening import *  # noqa: F401,F403
from etf_cockpit.application.screening_data import *  # noqa: F401,F403
from etf_cockpit.data.screen_store import *  # noqa: F401,F403
from etf_cockpit.core.versioning import *  # noqa: F401,F403
from etf_cockpit.core.job_scheduler import *  # noqa: F401,F403
from etf_cockpit.core.resource_profiles import *  # noqa: F401,F403
from etf_cockpit.core.resource_profiles import HardwareSnapshot, resource_profile_report
from etf_cockpit.models.forecast_scores import *  # noqa: F401,F403
from etf_cockpit.models.forecast_scores import (
    CANONICAL_DISTRIBUTION_HORIZONS_DAYS,  # noqa: F401
    PRIMARY_MODEL_HORIZON_DAYS,  # noqa: F401
    forecast_return_distributions as load_forecast_return_distributions,
)  # noqa: F401
from etf_cockpit.models.model_zoo import *  # noqa: F401,F403
from etf_cockpit.models.coverage_audit import *  # noqa: F401,F403
from etf_cockpit.models.local_weights import *  # noqa: F401,F403
from etf_cockpit.portfolio.allocation import *  # noqa: F401,F403
from etf_cockpit.portfolio.costs import *  # noqa: F401,F403
from etf_cockpit.portfolio.factor_risk import *  # noqa: F401,F403
from etf_cockpit.portfolio.factor_risk import build_factor_risk_report
from etf_cockpit.portfolio.attribution import *  # noqa: F401,F403
from etf_cockpit.portfolio.rebalancing import *  # noqa: F401,F403
from etf_cockpit.portfolio.proposal_policy import *  # noqa: F401,F403
from etf_cockpit.portfolio.robust_risk import *  # noqa: F401,F403
from etf_cockpit.portfolio.risk import *  # noqa: F401,F403
from etf_cockpit.portfolio.risk_analytics import *  # noqa: F401,F403
from etf_cockpit.portfolio.currency import CurrencyProjection, project_portfolio_currency as _project_portfolio_currency
from etf_cockpit.portfolio.exposure_cube import build_portfolio_exposure_cube
from etf_cockpit.application.portfolio_sandbox import *  # noqa: F401,F403
from etf_cockpit.portfolio.sandbox import PortfolioAnalysis, select_holdings_view  # noqa: F401
from etf_cockpit.portfolio.goals_constraints import (
    PORTFOLIO_GOALS_SCHEMA,
    PortfolioPolicy,
    alert_record,
    build_alerts,
    build_what_if_scenario,
    policy_editor_value,
    policy_from_record,
    policy_record,
    source_snapshot_hash,
    validate_portfolio_policy,
    what_if_record,
)
from etf_cockpit.portfolio.risk_profiles import (
    RiskProfileError,
    build_risk_profile_workspace,
    unavailable_risk_profile_workspace,
)
from etf_cockpit.application.overlap import *  # noqa: F401,F403
from etf_cockpit.application.overlap import load_direct_holdings
from etf_cockpit.signals.simple_scores import *  # noqa: F401,F403
from etf_cockpit.signals.feature_drivers import (  # noqa: F401
    _canonical_cohort_time,
    _classification,
    _combined_authority_classification,
    _component_id,
    _derive_peer_percentiles,
    _flags,
    _freshness_classification,
    _normalise_interaction,
    _normalise_peer_percentile_alias,
    _scalar_text,
    _source_provenance_text,
    _source_vintage_hash,
    normalise_bound_claim,
)


def load_portfolio_performance_series(
    *,
    metric: str = "twr_index",
    date_range: str = "inception",
    aggregation: str = "day",
    currency: str = "EUR",
    custom_start: object = None,
    custom_end: object = None,
) -> PerformanceSeries:
    """Load saved valuation and local FX evidence for one portfolio view."""
    report = load_portfolio_valuation_history()
    snapshots = report.get("snapshots")
    try:
        fx_rates = load_fx_rates()
    except (OSError, ValueError, TypeError, ImportError):
        fx_rates = pd.DataFrame()
    return build_portfolio_performance_series(
        snapshots if isinstance(snapshots, pd.DataFrame) else None,
        metric=metric,
        date_range=date_range,
        aggregation=aggregation,
        currency=currency,
        custom_start=custom_start,  # type: ignore[arg-type]
        custom_end=custom_end,  # type: ignore[arg-type]
        fx_rates=fx_rates,
    )


def load_portfolio_forecast_aggregation(
    snapshot: object,
    analysis: PortfolioAnalysis,
    *,
    horizon_days: int,
    output_currency: str = "EUR",
    analysis_run_id: str | None = None,
) -> PortfolioForecastSnapshot:
    """Load an exact-horizon portfolio forecast from bound saved inputs."""

    projection = load_portfolio_holdings_projection(
        snapshot,
        analysis,
        horizon_days=horizon_days,
        output_currency=output_currency,
        analysis_run_id=analysis_run_id,
    )
    portfolio_meta = projection.get("portfolio_snapshot")
    portfolio_meta = portfolio_meta if isinstance(portfolio_meta, Mapping) else {}
    performance_meta = projection.get("performance_snapshot")
    performance_meta = performance_meta if isinstance(performance_meta, Mapping) else {}
    holding_rows = projection.get("rows", ())
    positions: dict[str, dict[str, object]] = {}
    if isinstance(holding_rows, Sequence) and not isinstance(holding_rows, (str, bytes)):
        for row in holding_rows:
            if not isinstance(row, Mapping):
                continue
            instrument_id = str(row.get("instrument_id", "")).strip()
            weight_cell = row.get("weight")
            value_cell = row.get("value")
            weight = weight_cell.get("value") if isinstance(weight_cell, Mapping) and weight_cell.get("status") == "available" else None
            market_value = value_cell.get("value") if isinstance(value_cell, Mapping) and value_cell.get("status") == "available" else None
            if instrument_id:
                positions[instrument_id] = {"weight": weight, "market_value": market_value}

    def _available_amount(field: str) -> float | None:
        cell = performance_meta.get(field)
        value = cell.get("value") if isinstance(cell, Mapping) and cell.get("status") == "available" else None
        return float(value) if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value)) else None

    securities_value = _available_amount("securities_value_output_currency")
    cash_value = _available_amount("cash_value_output_currency")
    portfolio_value = _available_amount("total_value_output_currency")
    security_reconciliation = performance_meta.get("reconciliation")
    total_reconciliation = performance_meta.get("portfolio_value_reconciliation")
    position_values = [
        position.get("market_value")
        for position in positions.values()
    ]
    value_components_reconciled = bool(
        isinstance(security_reconciliation, Mapping)
        and security_reconciliation.get("status") == "available"
        and security_reconciliation.get("value") is True
        and isinstance(total_reconciliation, Mapping)
        and total_reconciliation.get("status") == "available"
        and total_reconciliation.get("value") is True
        and securities_value is not None
        and cash_value is not None
        and portfolio_value is not None
        and position_values
        and all(isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value)) for value in position_values)
        and math.isclose(math.fsum(float(value) for value in position_values), securities_value, rel_tol=1e-12, abs_tol=1e-9)
        and math.isclose(securities_value + cash_value, portfolio_value, rel_tol=1e-12, abs_tol=1e-9)
    )

    binding = analysis.snapshot_binding
    risk_projection = analysis.service_evidence.get("risk")
    risk_projection = risk_projection if isinstance(risk_projection, Mapping) else {}
    selected_run_id = str(projection.get("analysis_run_id", "")).strip()
    risk_snapshot = None
    if binding is not None:
        risk_snapshot = {
            "portfolio_id": getattr(binding, "portfolio_id", None),
            "snapshot_id": getattr(binding, "snapshot_id", None),
            "as_of": getattr(binding, "as_of", None),
            "candidate_id": analysis.candidate.candidate_id,
            "status": risk_projection.get("status", "unavailable"),
            "model_version": risk_projection.get("model_version"),
            "selected_estimator": risk_projection.get("selected_estimator"),
            "covariances": risk_projection.get("covariances"),
            "warnings": risk_projection.get("warnings", ()),
            "coverage": risk_projection.get("coverage"),
            "execution_allowed": risk_projection.get("execution_allowed", False),
        }

    decision_time = projection.get("analysis_date")
    distributions: dict[str, dict[str, object]] = {}
    if projection.get("proposal_handoff_allowed") is True and decision_time:
        try:
            distribution_rows = load_forecast_return_distributions(
                getattr(snapshot, "forecasts", pd.DataFrame()),
                horizon_days=horizon_days,
                decision_time=decision_time,
            )
        except (TypeError, ValueError, KeyError):
            distribution_rows = {}
        distributions = {}
        for instrument_id, distribution in distribution_rows.items():
            if instrument_id not in positions or not isinstance(distribution, Mapping):
                continue
            bound_distribution = dict(distribution)
            if not bound_distribution.get("analysis_run_id"):
                bound_distribution["analysis_run_id"] = selected_run_id
            distributions[instrument_id] = bound_distribution

    analysis_snapshot = {
        "portfolio_id": portfolio_meta.get("portfolio_id"),
        "snapshot_id": portfolio_meta.get("snapshot_id"),
        "as_of": portfolio_meta.get("as_of"),
        "analysis_run_id": selected_run_id or None,
        "candidate_id": analysis.candidate.candidate_id,
        "decision_time": decision_time,
        "status": "complete" if projection.get("proposal_handoff_allowed") is True else "unavailable",
        "policy_status": "available" if projection.get("proposal_handoff_allowed") is True else "unavailable",
        "distributions": distributions,
        "target_weights": analysis.candidate.targets,
        "cash_weight": analysis.candidate.cash_weight,
        "cash_return": None,
        "benchmark_return": None,
    }
    portfolio_snapshot = {
        **portfolio_meta,
        "sealed": projection.get("proposal_handoff_allowed") is True,
        "positions": positions,
        "securities_value": securities_value,
        "cash_value": cash_value,
        "total_value": portfolio_value,
        "value_components_reconciled": value_components_reconciled,
        "cash_weight": analysis.current_cash_weight,
    }
    return build_portfolio_forecast_snapshot(
        portfolio_snapshot,
        analysis_snapshot,
        risk_snapshot,
        horizon_days=horizon_days,
        output_currency=output_currency,
    )


def load_portfolio_calendar_projection(
    snapshot: object,
    analysis: PortfolioAnalysis,
    *,
    output_currency: str = "EUR",
) -> dict[str, object]:
    """Load saved calendar, corporate-action, bond-term and FX evidence."""

    binding = analysis.snapshot_binding
    decision_time = getattr(binding, "as_of", None) if binding is not None else None
    decision = normalise_event_decision_time(decision_time)
    if decision is None:
        return build_portfolio_calendar(
            None,
            decision_time=None,
            output_currency=output_currency,
        )

    holdings = getattr(snapshot, "holdings", None)
    if isinstance(holdings, pd.DataFrame) and binding is not None:
        try:
            holdings = select_holdings_view(holdings, str(getattr(binding, "holdings_view", "combined")))
        except (TypeError, ValueError):
            holdings = pd.DataFrame()
    if not isinstance(holdings, pd.DataFrame):
        holdings = pd.DataFrame()

    event_rows = load_calendar_events()
    instrument_column = "instrument_id" if "instrument_id" in holdings.columns else "etf_id" if "etf_id" in holdings.columns else None
    instruments = sorted(
        {
            str(value).strip()
            for value in holdings[instrument_column].tolist()
            if str(value).strip()
        }
    ) if instrument_column else []
    corporate_actions = []
    storage_path = storage_layout(ROOT).transactional_path
    if storage_path.is_file():
        with CorporateActionStore(ROOT) as store:
            for instrument_id in instruments:
                corporate_actions.extend(store.query(instrument_id))

    terms: dict[str, Mapping[str, object]] = {}
    if "asset_type" in holdings.columns:
        bond_ids = sorted(
            {
                str(row[instrument_column]).strip()
                for _, row in holdings.iterrows()
                if instrument_column
                and str(row.get("asset_type", "")).strip().casefold()
                in {"bond", "fixed_income", "fixed income", "government_bond", "corporate_bond"}
            }
        )
        cutoff = decision.isoformat()
        for instrument_id in bond_ids:
            terms[instrument_id] = load_fixed_income_terms_projection(
                instrument_id,
                storage_root=ROOT,
                effective_at=cutoff,
                decision_time=cutoff,
            )
    try:
        fx_rates = load_fx_rates()
    except (OSError, ValueError, TypeError, ImportError):
        fx_rates = pd.DataFrame()

    return build_portfolio_calendar(
        holdings,
        decision_time=decision.to_pydatetime(),
        output_currency=output_currency,
        event_rows=event_rows,
        corporate_actions=tuple(corporate_actions),
        fixed_income_terms=terms,
        fx_rates=fx_rates,
    )


def load_portfolio_holdings_projection(
    snapshot: object,
    analysis: PortfolioAnalysis,
    *,
    horizon_days: int,
    output_currency: str = "EUR",
    analysis_run_id: str | None = None,
    search: str = "",
    asset_type: str | None = None,
    sort_by: str = "instrument_id",
    descending: bool = False,
    column_preset: str = "full",
    storage_root: Path | None = None,
    artifact_directory: Path | None = None,
) -> dict[str, object]:
    """Load a holding view from one bound portfolio, performance and analysis run."""

    source = Path(storage_root or ROOT).resolve()
    artifact_root = Path(artifact_directory or LOG_DIR).resolve()
    binding = analysis.snapshot_binding
    unavailable = {
        "status": "unavailable",
        "reason": "portfolio_snapshot_binding_unavailable",
        "portfolio_snapshot": None,
        "performance_snapshot": None,
        "analysis_run_id": None,
        "analysis_date": None,
        "analysis_policy_id": None,
        "analysis_current": False,
        "horizon_days": horizon_days,
        "output_currency": str(output_currency or "").strip().upper(),
        "proposal_handoff_allowed": False,
        "proposal_handoff_reason": "portfolio_snapshot_binding_unavailable",
        "row_count": 0,
        "total_rows": 0,
        "rows": [],
        "analysis_runs": [],
        "execution_allowed": False,
    }
    if binding is None:
        return unavailable

    portfolio_snapshot = {
        "portfolio_id": getattr(binding, "portfolio_id", None),
        "snapshot_id": getattr(binding, "snapshot_id", None),
        "as_of": getattr(binding, "as_of", None),
        "source_checksum": getattr(binding, "source_checksum", None),
        "policy_id": getattr(snapshot, "policy_id", None),
    }
    holdings = getattr(snapshot, "holdings", None)
    holdings = select_holdings_view(holdings, str(getattr(binding, "holdings_view", "combined")))
    if isinstance(holdings, pd.DataFrame) and not holdings.empty and "asset_type" not in holdings.columns:
        identity_column = next((name for name in ("instrument_id", "etf_id") if name in holdings.columns), None)
        configured = getattr(getattr(snapshot, "config", None), "universe", None)
        configured_by_id = configured.by_id() if configured is not None and callable(getattr(configured, "by_id", None)) else {}
        if identity_column is not None:
            holdings = holdings.copy()
            holdings["asset_type"] = holdings[identity_column].map(
                lambda value: getattr(configured_by_id.get(str(value)), "instrument_type", None)
            )

    report = load_portfolio_valuation_history(storage_root=source)
    snapshots = report.get("snapshots")
    performance_snapshot: dict[str, object] | None = None
    as_of = _holdings_date(getattr(binding, "as_of", None))
    if isinstance(snapshots, pd.DataFrame) and not snapshots.empty and as_of and "date" in snapshots:
        dates = pd.to_datetime(snapshots["date"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
        selected = snapshots.loc[dates.eq(as_of)]
        if len(selected) == 1:
            performance_snapshot = selected.iloc[0].to_dict()
            performance_snapshot["date"] = as_of
            performance_snapshot["execution_allowed"] = False

    signals = tuple(getattr(snapshot, "signals", ()) or ())
    current_run_ids = {
        str(getattr(signal, "run_id", "")).strip()
        for signal in signals
        if str(getattr(signal, "run_id", "")).strip()
    }

    artifacts: list[dict[str, object]] = []
    try:
        paths = sorted(artifact_root.glob("decision_opportunity_*.json"))
    except OSError:
        paths = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != 1
            or payload.get("artifact_version") != "decision-opportunity-shadow-v1"
            or payload.get("execution_allowed") is not False
        ):
            continue
        run_id = str(payload.get("run_id", "")).strip()
        run_date = _holdings_date(payload.get("decision_time"))
        if run_id and run_date and as_of and run_date <= as_of:
            artifacts.append(dict(payload))
    analysis_runs = [
        {
            "run_id": str(item.get("run_id", "")),
            "decision_time": str(item.get("decision_time", "")),
            "status": str(item.get("status", "unavailable")),
        }
        for item in sorted(artifacts, key=lambda item: (str(item.get("decision_time", "")), str(item.get("run_id", ""))), reverse=True)
    ]

    chosen_run_id = str(analysis_run_id or "").strip()
    if not chosen_run_id and len(current_run_ids) == 1:
        chosen_run_id = next(iter(current_run_ids))
    if not chosen_run_id and analysis_runs:
        chosen_run_id = str(analysis_runs[0]["run_id"])
    signal_by_id = {
        str(getattr(signal, "etf_id", "")).strip(): signal
        for signal in signals
        if str(getattr(signal, "run_id", "")).strip() == chosen_run_id
        and str(getattr(signal, "etf_id", "")).strip()
    } if chosen_run_id else {}
    selected_artifacts = [item for item in artifacts if str(item.get("run_id", "")) == chosen_run_id]
    artifact = selected_artifacts[0] if len(selected_artifacts) == 1 else None
    analysis_date = _holdings_date(artifact.get("decision_time")) if artifact is not None else None
    config_hashes = artifact.get("config_hashes") if artifact is not None else None
    policy_id = (
        str(config_hashes.get("decision_opportunity_v1", "")).strip()
        if isinstance(config_hashes, Mapping)
        else ""
    )
    raw_results = artifact.get("results") if artifact is not None else None
    results = {
        str(item.get("instrument", "")).strip(): dict(item)
        for item in raw_results or ()
        if isinstance(item, Mapping) and str(item.get("instrument", "")).strip()
    } if isinstance(raw_results, list) else {}
    opportunity_policy_matches = bool(
        policy_id
        and policy_id != "unavailable"
        and results
        and all(str(item.get("config_hash", "")).strip() == policy_id for item in results.values())
    )
    selected_signals_current = bool(
        chosen_run_id
        and current_run_ids == {chosen_run_id}
        and signal_by_id
        and all(_holdings_date(getattr(signal, "signal_date", None)) == analysis_date for signal in signal_by_id.values())
    )
    gate_policy_checksums = {
        str(getattr(signal, "gate_policy_checksum", "")).strip()
        for signal in signal_by_id.values()
    }
    gate_policy_id = next(iter(gate_policy_checksums)) if len(gate_policy_checksums) == 1 else ""
    gate_policy_matches = bool(gate_policy_id and gate_policy_id != "unavailable")
    analysis_status = (
        "complete"
        if artifact is not None and artifact.get("status") == "complete" and opportunity_policy_matches and selected_signals_current
        else "partial"
        if artifact is not None and artifact.get("status") == "partial"
        else "unavailable"
    )
    table_rows: dict[str, dict[str, object]] = {}
    for instrument_id, opportunity in results.items():
        signal = signal_by_id.get(instrument_id)
        if signal is None:
            continue
        canonical_score = getattr(signal, "canonical_score", None)
        scores = {
            "evidence": getattr(canonical_score, "evidence_confidence_10", None),
            "quality": getattr(canonical_score, "attractiveness_10", None),
            "risk": getattr(canonical_score, "risk_implementation_10", None),
            "total": getattr(signal, "total_score", None),
        }
        table_rows[instrument_id] = {
            "instrument_id": instrument_id,
            "analysis_run_id": chosen_run_id,
            "scores": scores,
            "rank": opportunity.get("universe_rank"),
            "peer_rank": opportunity.get("peer_rank"),
            "action": getattr(signal, "action", None),
            "blockers": tuple(getattr(signal, "blocked_by", ()) or ()),
            "coverage": opportunity.get("coverage"),
        }

    distributions: dict[str, object] = {}
    decision_time = artifact.get("decision_time") if artifact is not None else None
    if selected_signals_current and decision_time:
        try:
            distribution_rows = load_forecast_return_distributions(
                getattr(snapshot, "forecasts", pd.DataFrame()),
                horizon_days=horizon_days,
                decision_time=decision_time,
            )
        except (TypeError, ValueError, KeyError):
            distribution_rows = {}
        distributions = {
            instrument_id: distribution
            for instrument_id, distribution in distribution_rows.items()
            if instrument_id in table_rows
        }

    analysis_snapshot = {
        "analysis_run_id": chosen_run_id or None,
        "run_id": str(artifact.get("run_id", "")) if artifact is not None else None,
        "decision_time": artifact.get("decision_time") if artifact is not None else None,
        "status": analysis_status,
        "policy_id": policy_id or None,
        "policy_ids": {
            "opportunity": policy_id or None,
            "gate": gate_policy_id or None,
        },
        "policy_status": "available" if opportunity_policy_matches and selected_signals_current and gate_policy_matches else "unavailable",
        "rows": table_rows,
        "distributions": distributions,
    }
    try:
        fx_rates = load_fx_rates()
    except (OSError, ValueError, TypeError, ImportError):
        fx_rates = pd.DataFrame()
    try:
        currency_projection = project_portfolio_currency(analysis, output_currency, fx_rates)
    except (TypeError, ValueError, ArithmeticError):
        currency_projection = None

    projection = build_portfolio_holdings_table(
        holdings if isinstance(holdings, pd.DataFrame) else None,
        portfolio_snapshot=portfolio_snapshot,
        performance_snapshot=performance_snapshot,
        analysis_snapshot=analysis_snapshot,
        horizon_days=horizon_days,
        output_currency=output_currency,
        currency_projection=currency_projection,
        search=search,
        asset_type=asset_type,
        sort_by=sort_by,
        descending=descending,
        column_preset=column_preset,
    )
    projection["analysis_runs"] = analysis_runs
    projection["selected_analysis_run_id"] = chosen_run_id or None
    if artifact is None:
        projection["analysis_reason"] = "selected_analysis_run_unavailable"
    elif not selected_signals_current:
        projection["analysis_reason"] = "analysis_run_does_not_match_saved_signal_snapshot"
    elif not opportunity_policy_matches or not gate_policy_matches:
        projection["analysis_reason"] = "analysis_policy_hash_mismatch_or_unavailable"
    else:
        projection["analysis_reason"] = None
    return projection


def _holdings_date(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("UTC")
    return parsed.date().isoformat()


def build_profiled_forecast_lab_workspace(
    config: object,
    forecasts: object,
    prices: object,
    *,
    profile_id: str = "auto",
) -> dict[str, object]:
    """Build Forecast Lab through the app facade with an explicit hardware profile."""

    from etf_cockpit.features.forecast_lab import build_forecast_lab_workspace

    return build_forecast_lab_workspace(
        config, forecasts, prices, profile_id=profile_id
    )


def build_resource_profile_diagnostics(
    root: Path | None = None,
    *,
    requested_profile: str = "auto",
    snapshot: HardwareSnapshot | None = None,
) -> dict[str, object]:
    """Expose local hardware limitations in the application diagnostics payload."""

    report = resource_profile_report(
        root, requested_profile=requested_profile, snapshot=snapshot
    )
    return {
        "status": report["selected_status"],
        "limitations": list(report["limitations"]),
        "resource_profile": report,
        "execution_allowed": False,
    }


def project_portfolio_currency(
    analysis: PortfolioAnalysis,
    target_currency: str,
    fx_rates: pd.DataFrame,
) -> CurrencyProjection:
    """Return the canonical informational currency projection for presentation."""
    return _project_portfolio_currency(analysis, target_currency, fx_rates)


def load_portfolio_exposure_projection(
    position_weights: Mapping[str, float],
    *,
    decision_time: str | datetime,
    analysis_date: str | date | datetime | None = None,
    portfolio_id: str | None = None,
    snapshot_id: str | None = None,
    position_metadata: Mapping[str, Mapping[str, object]] | None = None,
    holding_metadata: Mapping[str, Mapping[str, object]] | None = None,
    reporting_currency: str | None = None,
    holdings: pd.DataFrame | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    """Load the read-only exposure chart projection for a ledger-weight snapshot."""
    evidence = holdings if isinstance(holdings, pd.DataFrame) else load_direct_holdings(root=root)
    cube = build_portfolio_exposure_cube(
        evidence,
        position_weights,
        decision_time=decision_time,
        analysis_date=analysis_date,
        portfolio_id=portfolio_id,
        snapshot_id=snapshot_id,
        position_metadata=position_metadata,
        holding_metadata=holding_metadata,
        reporting_currency=reporting_currency,
    )
    return cube.to_projection()


def load_portfolio_risk_profile_projection(
    snapshot: object,
    analysis: object,
    *,
    profile_id: str = "medium",
    profile_version: object = None,
    version_history: Sequence[object] = (),
    profile_edits: Mapping[str, object] | None = None,
    reset_to_preset: bool = False,
) -> dict[str, object]:
    """Load the local, advisory profile projection for one bound candidate."""

    try:
        return build_risk_profile_workspace(
            snapshot,
            analysis,
            selected_profile_id=profile_id,
            selected_version=profile_version,
            version_history=version_history,
            profile_edits=profile_edits,
            reset_to_preset=reset_to_preset,
        )
    except (RiskProfileError, OSError, TypeError, ValueError) as exc:
        return unavailable_risk_profile_workspace(str(exc) or "risk_profile_projection_unavailable")


def _normalise_valuation_assumptions(value: object) -> dict[str, object]:
    """Accept only the bounded, explicit session scenario contract."""
    if not isinstance(value, Mapping) or set(value) != {"forecast_years", "discount_rate", "terminal_growth", "scenarios"}:
        raise ValueError("Explicit forecast years, discount, terminal growth and three scenarios are required")
    years = value["forecast_years"]
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 50:
        raise ValueError("Forecast years must be an integer from 1 to 50")

    def number(raw: object) -> float:
        if isinstance(raw, bool) or not isinstance(raw, Real) or not math.isfinite(raw):
            raise ValueError("Scenario inputs must be finite numbers")
        return float(raw)

    discount = number(value["discount_rate"])
    terminal = number(value["terminal_growth"])
    if not 0 < discount <= 1 or not -1 <= terminal < discount:
        raise ValueError("Discount or terminal growth is outside the allowed range")
    scenarios = value["scenarios"]
    if not isinstance(scenarios, Mapping) or set(scenarios) != {"bear", "base", "bull"}:
        raise ValueError("Exactly bear, base and bull scenarios are required")
    growths = []
    for name in ("bear", "base", "bull"):
        row = scenarios[name]
        if not isinstance(row, Mapping) or set(row) != {"growth"}:
            raise ValueError("Only explicit growth is allowed for each scenario")
        growths.append(number(row["growth"]))
    if not -0.5 <= growths[0] < growths[1] < growths[2] <= 1:
        raise ValueError("Growth must satisfy -50% <= bear < base < bull <= 100%")
    return {"forecast_years": years, "discount_rate": discount, "terminal_growth": terminal,
            "scenarios": {name: {"growth": growth} for name, growth in zip(("bear", "base", "bull"), growths, strict=True)}}


def _finite_valuation_result(value: object) -> bool:
    if isinstance(value, Mapping):
        return all(_finite_valuation_result(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite_valuation_result(item) for item in value)
    return not isinstance(value, Real) or math.isfinite(value)


def load_valuation_evidence(path: Path, *, instrument_id: str, decision_time: object, assumptions: object = None) -> dict[str, object]:
    """Validate raw scoped facts before the date-grained stock research producer.

    Exact UTC knowledge filtering precedes the producer's date adapter. A
    date-only availability is conservatively eligible at UTC end-of-day;
    malformed selected evidence blocks the entire panel, never just that row.
    """
    def unavailable(reason: str) -> dict[str, object]:
        return {"status": "unavailable", "message": reason, "execution_allowed": False}

    cutoff = normalise_event_decision_time(decision_time)
    if cutoff is None:
        return unavailable("Snapshot decision time is unavailable; point-in-time valuation cannot be established.")
    context = {}
    if assumptions is not None:
        try:
            assumptions = _normalise_valuation_assumptions(assumptions)
        except (ValueError, TypeError, OverflowError):
            return unavailable("Invalid explicit scenario assumptions; valuation unavailable.")
        context = {"kind": "local_user_scenario_assumption", "instrument_id": instrument_id,
                   "decision_time": cutoff.isoformat(), "session_preview_only": True,
                   "score_authority": False, "execution_allowed": False, "assumptions": assumptions}
    try:
        raw = pd.read_parquet(path)
        if raw.empty:
            return unavailable("Canonical local statement evidence is unavailable.")
        if raw.columns.duplicated().any() or "instrument_id" not in raw:
            return unavailable("Statement identity is malformed; valuation unavailable.")
        frame = raw.loc[raw["instrument_id"].map(lambda value: isinstance(value, str) and value == instrument_id)].copy()
        if frame.empty:
            return unavailable("No canonical local statements exist for this instrument.")
        required = {"canonical_metric", "value", "available_at", "source_id"}
        if not required.issubset(frame.columns):
            return unavailable("Required statement evidence fields are missing; valuation unavailable.")
        for alias in ("etf_id", "display_id"):
            if alias in frame and any(not pd.api.types.is_scalar(value) or (pd.notna(value) and value != instrument_id) for value in frame[alias]):
                return unavailable("Statement identity conflicts; valuation unavailable.")
        fields = (
            "instrument_id", "canonical_metric", "value", "available_at", "source_id", "concept", "unit",
            "start", "end", "instant", "filed", "form", "accession", "fiscal_year", "fiscal_period",
            "dimensions", "currency", "period_type", "mapping_status", "mapping_confidence",
            "manual_review_required", "restatement_kind",
        )
        frame = frame[[field for field in fields if field in frame]].copy()
        knowledge = []
        for row in frame.to_dict("records"):
            if any(not pd.api.types.is_scalar(value) for value in row.values()):
                return unavailable("Malformed statement row; valuation unavailable.")
            value = row["value"]
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                return unavailable("Invalid or nonfinite statement numeric input; valuation unavailable.")
            if any(not isinstance(row[field], str) or not row[field].strip() for field in ("canonical_metric", "source_id")):
                return unavailable("Statement metric or provenance is missing; valuation unavailable.")
            available = row["available_at"]
            known_at = normalise_event_decision_time(available)
            if known_at is None:
                return unavailable("Statement availability is unknown or malformed; valuation unavailable.")
            knowledge.append(known_at)
            for field in ("start", "end", "instant", "filed"):
                date_value = row.get(field)
                if date_value is not None and pd.notna(date_value):
                    if not isinstance(date_value, str) or pd.isna(pd.to_datetime(date_value, errors="coerce", utc=True)):
                        return unavailable("Malformed statement period or filing date; valuation unavailable.")
            if not any(isinstance(row.get(field), str) and row[field].strip() for field in ("end", "instant")):
                return unavailable("Statement period is missing; valuation unavailable.")
        frame = frame.loc[[known_at <= cutoff for known_at in knowledge]].copy()
        if frame.empty:
            return unavailable("No statement evidence was available at the snapshot decision time.")
        # Share counts are a sourced-input validity rule, not a valuation formula.
        # Check only selected, cutoff-eligible facts; future/foreign counts cannot
        # invalidate the current preview. The producer uses this exact metric name.
        share_counts = frame.loc[frame["canonical_metric"].eq("shares_outstanding"), "value"]
        if share_counts.le(0).any():
            return unavailable("Nonpositive sourced share count; valuation unavailable.")
        # All surviving rows have already passed exact knowledge filtering.
        # Adapt only the producer's internal availability representation, not
        # the persisted facts or the disclosed decision cutoff.
        precisions = {"date_only_utc_end_of_day" if len(str(value).strip()) == 10 else "timestamp" for value in frame["available_at"]}
        frame["available_at"] = [normalise_event_decision_time(value).date().isoformat() for value in frame["available_at"]]
        result = valuation_analysis(frame, instrument_id=instrument_id, as_known_at=cutoff.isoformat(), assumptions=assumptions)
        if not _finite_valuation_result(result):
            return unavailable("Nonfinite derived valuation evidence; valuation unavailable.")
        result["source_lineage"]["as_known_at"] = cutoff.isoformat()
        result["source_lineage"]["knowledge_precision"] = sorted(precisions)
        result["source_lineage"]["cutoff_policy"] = "Exact UTC filtering before date-grained canonical calculation; date-only knowledge uses UTC end-of-day."
        return result | {"status": "available", "assumption_context": context}
    except ArithmeticError:
        return unavailable("Arithmetic failure in canonical valuation; valuation unavailable.")
    except (OSError, ValueError, TypeError, ImportError, KeyError):
        return unavailable("Canonical statement store is unreadable or malformed; valuation unavailable.")


def load_etf_look_through(
    instrument_id: str,
    *,
    decision_time: object,
    holdings_frame: object = None,
    fundamentals_frame: object = None,
    identity_map: Mapping[str, str] | None = None,
    provider_metrics: Mapping[str, object] | None = None,
    max_holdings_age_days: int = 90,
) -> dict[str, object]:
    """Read local ETF holdings and constituent evidence for the pure analyzer."""
    from dataclasses import asdict

    from etf_cockpit.analysis.look_through import calculate_look_through
    from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
    from etf_cockpit.data.fundamentals import FUNDAMENTAL_CLEAN_PATH

    try:
        holdings = pd.read_parquet(FUND_HOLDINGS_PATH) if holdings_frame is None else holdings_frame
        if fundamentals_frame is None:
            try:
                fundamentals = pd.read_parquet(FUNDAMENTAL_CLEAN_PATH)
            except (FileNotFoundError, OSError, ValueError, ImportError):
                fundamentals = pd.DataFrame()
        else:
            fundamentals = fundamentals_frame
        summary = calculate_look_through(
            holdings,
            instrument_id=instrument_id,
            decision_time=decision_time,
            constituent_fundamentals=fundamentals,
            identity_map=identity_map,
            provider_metrics=provider_metrics,
            max_holdings_age_days=max_holdings_age_days,
        )
        return asdict(summary)
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        return {
            "instrument_id": instrument_id,
            "status": "unavailable",
            "message": "Local holdings look-through evidence is unavailable or malformed.",
            "execution_allowed": False,
        }


def load_etf_structure_projection(
    instrument_id: str,
    *,
    document_registry: object = None,
    report_records: object = None,
    supplemental_rows: object = None,
    holdings: object = None,
    decision_time: object = None,
    numeric_inputs: Mapping[str, object] | None = None,
    numeric_candidates: object = None,
) -> dict[str, object]:
    """Load the local ETF structural read model without provider access."""

    try:
        registry = read_document_registry() if document_registry is None else document_registry
        reports = read_etf_report_records() if report_records is None else report_records
        return project_etf_structure(
            instrument_id,
            document_registry=registry,
            report_records=reports,
            supplemental_rows=supplemental_rows,
            holdings=holdings,
            decision_time=decision_time,
            numeric_inputs=numeric_inputs,
            numeric_candidates=numeric_candidates,
        )
    except (OSError, TypeError, ValueError):
        return {
            "contract": "etf-structure-documents.v1",
            "instrument_id": str(instrument_id),
            "status": "unavailable",
            "fields": {},
            "documents": {family: {"status": "unknown", "execution_allowed": False} for family in ("factsheet", "prospectus", "holdings")},
            "versions": [],
            "flags": ["structure_evidence_invalid"],
            "evidence_confidence_cap": 0.0,
            "execution_allowed": False,
        }


def load_identity_projection(
    instrument_id: str,
    path: Path | None = None,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return one fail-closed, read-only identity lineage projection for presentation."""

    import pandas as pd

    master_root = Path(storage_root).resolve() if storage_root is not None else None
    if master_root is None and path is None:
        default_path = Path(IDENTITY_PATH).resolve()
        if len(default_path.parents) >= 3:
            master_root = default_path.parents[2]
    if master_root is not None:
        try:
            if identity_master_exists(master_root):
                with IdentityMasterStore(master_root) as master:
                    return master.projection(
                        instrument_id,
                        effective_at=effective_at,
                        decision_time=decision_time,
                    )
            if storage_root is not None and path is None:
                return {
                    "status": "unavailable",
                    "instrument_id": str(instrument_id),
                    "reason_code": "identity_master_evidence_unavailable",
                    "execution_allowed": False,
                }
        except KeyError:
            if storage_root is not None and path is None:
                return {
                    "status": "unavailable",
                    "instrument_id": str(instrument_id),
                    "reason_code": "identity_master_evidence_unavailable",
                    "execution_allowed": False,
                }
        except (IdentityMasterSchemaError, OSError, ValueError):
            return {
                "status": "unavailable",
                "instrument_id": str(instrument_id),
                "reason_code": "identity_master_evidence_invalid",
                "execution_allowed": False,
            }

    identity_path = Path(path or IDENTITY_PATH)
    try:
        frame = pd.read_parquet(identity_path)
    except (OSError, ValueError, ImportError):
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "identity_evidence_unavailable",
            "execution_allowed": False,
        }
    if "instrument_id" not in frame.columns:
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "identity_schema_unavailable",
            "execution_allowed": False,
        }
    matches = frame.loc[frame["instrument_id"].astype(str).eq(str(instrument_id))]
    if len(matches) != 1:
        return {
            "status": "quarantined" if len(matches) > 1 else "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "duplicate_identity_projection" if len(matches) > 1 else "identity_evidence_unavailable",
            "candidate_count": len(matches),
            "execution_allowed": False,
        }
    row = matches.iloc[0]
    fields = (
        "identity_confidence",
        "identity_status",
        "identity_decision_id",
        "identity_conflict_ids",
        "identity_resolution_state",
        "identity_effective_at",
        "identity_decision_time",
        "identity_objects",
        "identity_history",
        "warnings",
    )
    projection: dict[str, object] = {
        "status": "available",
        "instrument_id": str(instrument_id),
        "execution_allowed": False,
    }
    for field in fields:
        value = row.get(field)
        projection[field] = "unavailable" if value is None or bool(pd.isna(value)) else value
    return projection


def load_fixed_income_terms_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return read-only contractual terms/schedules or an explicit unavailable state."""

    from datetime import datetime

    from etf_cockpit.core.paths import ROOT

    root = Path(storage_root or ROOT).resolve()
    unavailable = {
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_terms_unavailable"],
        "capability_flags": {
            "terms_available": False,
            "contractual_schedule_available": False,
            "pricing_allowed": False,
            "screening_allowed": False,
            "proposal_allowed": False,
            "execution_allowed": False,
        },
        "pricing_allowed": False,
        "screening_allowed": False,
        "proposal_allowed": False,
        "execution_allowed": False,
    }
    try:
        if not fixed_income_terms_exists(root):
            return unavailable
        effective = (
            datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
            if effective_at
            else None
        )
        decision = (
            datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
            if decision_time
            else None
        )
        classification = (
            read_instrument_context(
                root,
                instrument_id,
                effective_at=effective,
                decision_time=decision,
            )
            if classification_store_exists(root)
            else None
        )
        with FixedIncomeTermsStore(root) as store:
            return store.projection(
                instrument_id,
                effective_at=effective,
                decision_time=decision,
                classification=classification,
            )
    except (
        ClassificationSchemaError,
        FixedIncomeTermsSchemaError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ):
        return unavailable | {"reason_codes": ["fixed_income_terms_invalid"]}


def load_fixed_income_market_data_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return read-only fixed-income market evidence for presentation."""

    from datetime import datetime
    from etf_cockpit.core.paths import ROOT

    root = Path(storage_root or ROOT).resolve()
    unavailable = {
        "contract": "fixed-income-market-data.v1",
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_market_data_unavailable"],
        "observations": [],
        "provider_coverage": {"status": "unavailable", "rows": []},
        "precise_liquidity_available": False,
        "execution_allowed": False,
    }
    try:
        if not fixed_income_market_data_exists(root):
            return unavailable
        effective = (
            datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
            if effective_at
            else None
        )
        decision = (
            datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
            if decision_time
            else None
        )
        with FixedIncomeMarketDataStore(root) as store:
            return store.resolve(
                instrument_id,
                effective_at=effective,
                decision_time=decision,
            )
    except (FixedIncomeMarketDataSchemaError, OSError, TypeError, ValueError):
        return unavailable


def calculate_fixed_income_analytics_projection(
    valuation: FixedIncomeValuationInput,
) -> dict[str, object]:
    """Calculate and serialize analytics behind the application boundary."""

    from dataclasses import asdict

    projection = _analytics_jsonable(
        asdict(calculate_fixed_income_analytics(valuation))
    )
    if not isinstance(projection, dict):
        raise FixedIncomeAnalyticsError("analytics projection is invalid")
    return projection


def calculate_fixed_income_risk_projection(
    risk_input: FixedIncomeRiskInput,
) -> dict[str, object]:
    """Calculate a serialisable non-executable fixed-income risk projection."""

    from dataclasses import asdict

    projection = _analytics_jsonable(asdict(calculate_fixed_income_risk(risk_input)))
    if not isinstance(projection, dict):
        raise FixedIncomeRiskError("risk projection is invalid")
    return projection


def load_fixed_income_risk_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Load verified local risk evidence for presentation only."""

    from datetime import datetime
    from etf_cockpit.core.paths import ROOT

    unavailable = {
        "contract": "fixed-income-risk.v1",
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_risk_unavailable"],
        "execution_allowed": False,
    }
    path = Path(storage_root or ROOT) / "data" / "analytics" / "fixed_income_risk.parquet"
    if not path.exists():
        return unavailable
    try:
        cutoff = datetime.fromisoformat(decision_time.replace("Z", "+00:00")) if decision_time else None
        rows = [
            row for row in read_fixed_income_risk(path)
            if row["instrument_id"] == str(instrument_id)
            and (cutoff is None or datetime.fromisoformat(str(row["decision_time"])) <= cutoff)
        ]
        if not rows:
            return unavailable
        result = max(rows, key=lambda row: (str(row["decision_time"]), str(row["calculated_at"])))["result"]
        return dict(result) if isinstance(result, dict) else unavailable
    except (FixedIncomeRiskError, OSError, TypeError, ValueError):
        return unavailable | {"reason_codes": ["fixed_income_risk_invalid"]}


def load_fixed_income_analytics_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Load the latest local analytics record, failing closed when unavailable."""

    from datetime import datetime

    from etf_cockpit.core.paths import ROOT

    unavailable = {
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_analytics_unavailable"],
        "execution_allowed": False,
    }
    path = Path(storage_root or ROOT) / "data" / "analytics" / "bond_analytics.parquet"
    if not path.exists():
        return unavailable
    try:
        cutoff = (
            datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
            if decision_time
            else None
        )
        matches = [
            row
            for row in read_bond_analytics(path)
            if row["instrument_id"] == str(instrument_id)
            and (
                cutoff is None
                or datetime.fromisoformat(str(row["decision_time"])) <= cutoff
            )
        ]
        if not matches:
            return unavailable
        latest = max(
            matches,
            key=lambda row: (
                str(row["decision_time"]),
                str(row["calculated_at"]),
                str(row["record_id"]),
            ),
        )
        result = latest["result"]
        return dict(result) if isinstance(result, dict) else unavailable
    except (FixedIncomeAnalyticsError, OSError, TypeError, ValueError):
        return unavailable | {"reason_codes": ["fixed_income_analytics_invalid"]}


def _analytics_jsonable(value: object) -> object:
    from datetime import date, datetime
    from decimal import Decimal
    from enum import Enum
    from collections.abc import Mapping

    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _analytics_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_analytics_jsonable(item) for item in value]
    return value


def load_classification_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
    min_leaf_confidence: float = 0.75,
) -> dict[str, object]:
    """Return fail-closed point-in-time classification for presentation."""

    root = Path(storage_root).resolve() if storage_root is not None else None
    if root is None:
        default_path = Path(IDENTITY_PATH).resolve()
        if len(default_path.parents) >= 3:
            root = default_path.parents[2]
    if root is None:
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "classification_storage_unavailable",
            "execution_allowed": False,
        }
    try:
        return read_classification_projection(
            root,
            instrument_id,
            effective_at=effective_at,
            decision_time=decision_time,
            min_leaf_confidence=min_leaf_confidence,
        )
    except (ClassificationSchemaError, OSError, ValueError):
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "classification_evidence_invalid",
            "execution_allowed": False,
        }


def load_peer_cohort_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return persisted peer lineage only; presentation never calculates statistics."""

    from etf_cockpit.core.paths import ROOT

    try:
        return read_peer_cohort_projection(
            Path(storage_root or ROOT).resolve(),
            instrument_id,
            decision_time=decision_time,
        )
    except (OSError, TypeError, ValueError):
        return {
            "contract": "peer-cohort.v1",
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "peer_cohort_evidence_invalid",
            "execution_allowed": False,
        }


def load_opportunity_assessment(
    instrument_id: str,
    *,
    decision_time: object = None,
    run_id: str | None = None,
    artifact_directory: Path | None = None,
) -> dict[str, object]:
    """Read the latest valid local opportunity result without recalculation."""

    instrument = str(instrument_id or "").strip()
    unavailable = {
        "status": "unavailable",
        "instrument": instrument,
        "reason_code": "opportunity_result_unavailable",
        "execution_allowed": False,
    }
    if not instrument:
        return unavailable | {"reason_code": "instrument_id_unavailable"}
    root = Path(artifact_directory or LOG_DIR)
    cutoff = None
    if decision_time is not None:
        try:
            cutoff = pd.Timestamp(decision_time)
            if cutoff.tzinfo is None:
                cutoff = cutoff.tz_localize("UTC")
            else:
                cutoff = cutoff.tz_convert("UTC")
            if len(str(decision_time).strip()) == 10:
                cutoff = cutoff + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        except (TypeError, ValueError, OverflowError):
            return unavailable | {"reason_code": "decision_time_invalid"}
    records: list[tuple[pd.Timestamp, str, dict[str, object]]] = []
    try:
        paths = sorted(root.glob("decision_opportunity_*.json"))
    except OSError:
        return unavailable
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != 1
            or payload.get("artifact_version") != "decision-opportunity-shadow-v1"
            or payload.get("execution_allowed") is not False
            or (run_id is not None and str(payload.get("run_id")) != run_id)
        ):
            continue
        try:
            timestamp = pd.Timestamp(payload.get("decision_time"))
            if timestamp.tzinfo is None:
                continue
            timestamp = timestamp.tz_convert("UTC")
        except (TypeError, ValueError, OverflowError):
            continue
        if cutoff is not None and timestamp > cutoff:
            continue
        hashes = payload.get("config_hashes")
        if not isinstance(hashes, Mapping):
            continue
        rows = payload.get("results")
        if not isinstance(rows, list):
            continue
        result = next(
            (
                dict(item)
                for item in rows
                if isinstance(item, Mapping)
                and str(item.get("instrument", "")) == instrument
                and item.get("execution_allowed") is False
            ),
            None,
        )
        if result is None:
            continue
        result.update(
            {
                "artifact_status": str(payload.get("status", "unavailable")),
                "run_id": str(payload.get("run_id", "")),
                "config_hashes": dict(hashes),
            }
        )
        records.append((timestamp, str(payload.get("run_id", "")), result))
    if not records:
        return unavailable
    records.sort(key=lambda item: (item[0], item[1]))
    return records[-1][2]


def load_stock_research_context(
    instrument_id: str,
    *,
    statements_path: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Load stock statements and their point-in-time classification/peer context.

    ``decision_time`` is the application's stable decision time; when given it overrides the
    classification record's own decision time so every panel on the page uses one cutoff.
    """
    requested_decision_time = str(decision_time or "").strip() or None
    classification_projection = load_classification_projection(instrument_id)
    classification_value = classification_projection.get("classification")
    classification = dict(classification_value) if isinstance(classification_value, Mapping) else {}
    classification_status = str(classification_projection.get("status", "unavailable"))
    effective_at = str(classification.get("effective_at") or "").strip() or None
    decision_time = requested_decision_time or str(classification.get("decision_time") or "").strip() or None
    peer_projection = load_peer_cohort_projection(instrument_id, decision_time=decision_time)
    peer_projection_status = str(peer_projection.get("status", "unavailable"))
    cohort = peer_projection.get("cohort")
    members = cohort.get("members") if isinstance(cohort, Mapping) else None
    peer_ids = {
        str(value)
        for value in members or ()
        if str(value).strip() and str(value) != str(instrument_id)
    } if peer_projection_status == "available" and classification_status == "available" else set()

    from etf_cockpit.data.stock_research import load_stock_research_frame

    facts = load_stock_research_frame(
        statements_path or STATEMENT_FACTS_PATH,
        as_known_at=decision_time,
    )
    if "instrument_id" in facts.columns:
        statements = facts[facts["instrument_id"].astype(str).eq(str(instrument_id))].reset_index(drop=True)
        peer_frame = facts[facts["instrument_id"].astype(str).isin(peer_ids)].reset_index(drop=True)
    else:
        statements = facts.iloc[0:0].copy()
        peer_frame = facts.iloc[0:0].copy()
    peer_frame.attrs["peer_context_status"] = peer_projection_status if peer_ids else "unavailable"
    sector = str(classification.get("sector") or "").strip() if classification_status == "available" else ""
    financial_labels = {sector.casefold()}
    for name in ("industry", "issuer_sector", "issuer_type", "business_model_tags", "strategy_labels"):
        value = classification.get(name, ())
        values = (value,) if isinstance(value, str) else value
        if isinstance(values, (tuple, list, set)):
            for item in values:
                label = str(item or "").strip().casefold()
                if label:
                    financial_labels.update({label, label.replace("-", "_")})
    financial_projection: dict[str, object] = {}
    if financial_labels & {"bank", "banks", "banking", "savings_bank", "savings banks", "deposit_taking", "insurance", "insurer", "financial", "financials", "financial_institution", "financial institution", "financial_services", "financial services"}:
        financial_projection = load_financial_institution_projection(
            instrument_id,
            decision_time=decision_time,
            effective_at=effective_at,
        )
    valuation_market_inputs = load_valuation_market_inputs(
        instrument_id,
        statements=statements,
        decision_time=decision_time,
    )
    peer_valuation_market_inputs = {
        peer_id: load_valuation_market_inputs(
            peer_id,
            statements=peer_frame.loc[peer_frame["instrument_id"].astype(str).eq(peer_id)].copy(),
            decision_time=decision_time,
        )
        for peer_id in sorted(peer_ids)
    }
    return {
        "instrument_id": str(instrument_id),
        "statements": statements,
        "classification": classification,
        "classification_status": classification_status,
        "sector": sector,
        "peer_context": dict(peer_projection),
        "peer_frame": peer_frame,
        "peer_context_status": peer_projection_status if peer_ids else "unavailable",
        "financial_projection": financial_projection,
        "valuation_market_inputs": valuation_market_inputs,
        "peer_valuation_market_inputs": peer_valuation_market_inputs,
        "effective_at": effective_at,
        "decision_time": decision_time,
        "execution_allowed": False,
    }


def load_valuation_market_inputs(
    instrument_id: str,
    *,
    statements: object,
    decision_time: object,
    assumptions: object = None,
    benchmark_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Load local valuation market evidence at the page's single decision time."""

    cutoff = normalise_event_decision_time(decision_time)
    base: dict[str, object] = {
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "decision_time": cutoff.isoformat() if cutoff is not None else None,
        "valuation_date": cutoff.date().isoformat() if cutoff is not None else None,
        "execution_allowed": False,
    }
    if cutoff is None:
        return base | {"reason": "Snapshot decision time is unavailable; market valuation cannot be established."}
    if not isinstance(statements, pd.DataFrame) or statements.empty:
        return base | {"reason": "Point-in-time statement evidence is unavailable."}
    frame = statements.copy()
    if "instrument_id" in frame:
        frame = frame.loc[frame["instrument_id"].astype(str).eq(str(instrument_id))].copy()
    if frame.empty or "canonical_metric" not in frame.columns:
        return base | {"reason": "Scoped statement facts are unavailable."}
    if "available_at" in frame:
        known_at = [normalise_event_decision_time(value) for value in frame["available_at"]]
        if any(value is None for value in known_at):
            return base | {"reason": "Statement vintage is malformed; market valuation cannot be established."}
        frame = frame.loc[[value <= cutoff for value in known_at]].copy()
        if frame.empty:
            return base | {"reason": "No statement filing vintage is known by the snapshot decision time."}
    currencies = sorted({str(value).strip().upper() for value in frame.get("currency", pd.Series(dtype="object")).dropna() if str(value).strip()})
    if len(currencies) != 1 or len(currencies[0]) != 3:
        return base | {"reason": "A single statement reporting currency is required for valuation."}
    reporting_currency = currencies[0]
    latest_by_metric = _valuation_latest_facts(frame)
    diluted_shares = latest_by_metric.get("diluted_shares_outstanding")
    if diluted_shares is None or diluted_shares <= 0:
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": None, "reason": "A positive sourced diluted share count is required; basic or weighted-average shares are not substituted."}
    if not PRICE_PARQUET.is_file():
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": diluted_shares, "reason": "Local dated market-price evidence is unavailable."}
    try:
        prices = load_prices(PRICE_PARQUET)
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": diluted_shares, "reason": "Local market-price evidence could not be read."}
    identity_column = next((column for column in ("instrument_id", "etf_id", "display_id") if column in prices.columns), None)
    if identity_column is None or not {"date", "close"}.issubset(prices.columns):
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": diluted_shares, "reason": "Local price evidence is missing identity, date or close fields."}
    price_rows = prices.loc[prices[identity_column].astype(str).eq(str(instrument_id))].copy()
    if price_rows.empty:
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": diluted_shares, "reason": "No local quote exists for this instrument."}
    price_dates = pd.to_datetime(price_rows["date"], errors="coerce", utc=True)
    if price_dates.isna().any():
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": diluted_shares, "reason": "Malformed price dates make the market quote unavailable."}
    # A date-only close on the decision date is unknown before end of that UTC day.
    eligible = price_dates.dt.date.le(cutoff.date())
    if cutoff.time().isoformat() != "23:59:59.999999" and cutoff.time().isoformat() != "23:59:59":
        eligible &= price_dates.dt.date.lt(cutoff.date())
    price_rows = price_rows.loc[eligible].copy()
    price_dates = price_dates.loc[eligible]
    if price_rows.empty:
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": diluted_shares, "reason": "No dated close is known by the snapshot decision time."}
    latest_price_date = price_dates.max()
    selected = price_rows.loc[price_dates.eq(latest_price_date)]
    close_values = pd.to_numeric(selected["close"], errors="coerce")
    if close_values.isna().any() or not close_values.map(math.isfinite).all() or (close_values <= 0).any() or close_values.nunique() != 1:
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": diluted_shares, "reason": "The latest dated close is invalid or conflicted."}
    if "currency" not in selected.columns:
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": diluted_shares, "reason": "The latest dated close has no recorded currency."}
    price_currencies = sorted({str(value).strip().upper() for value in selected["currency"].dropna() if str(value).strip()})
    if len(price_currencies) != 1 or len(price_currencies[0]) != 3:
        return base | {"reporting_currency": reporting_currency, "shares_outstanding": diluted_shares, "reason": "The latest dated close has missing or conflicting currency evidence."}
    price_currency = price_currencies[0]
    raw_price = float(close_values.iloc[0])
    conversion_timestamp = None
    conversion_rate = 1.0
    warnings: list[str] = []
    quote_date = latest_price_date.date()
    age = len(pd.bdate_range(pd.Timestamp(quote_date) + pd.offsets.BDay(1), pd.Timestamp(cutoff.date())))
    price_staleness = price_staleness_status(age)
    if price_staleness == "block":
        return base | {"reporting_currency": reporting_currency, "price_currency": price_currency, "price_date": quote_date.isoformat(), "price_timestamp": quote_date.isoformat(), "price_staleness": price_staleness, "shares_outstanding": diluted_shares, "reason": "Latest local quote is stale at the snapshot decision time."}
    if price_staleness == "warning":
        warnings.append("Latest local quote is more than three trading days old.")
    if price_currency != reporting_currency:
        if not FX_CLEAN_PATH.is_file():
            return base | {"reporting_currency": reporting_currency, "price_currency": price_currency, "price_date": quote_date.isoformat(), "price_timestamp": quote_date.isoformat(), "shares_outstanding": diluted_shares, "reason": "Currency conversion evidence is unavailable."}
        try:
            fx = load_fx_rates(FX_CLEAN_PATH)
        except (OSError, ValueError, TypeError, KeyError, ImportError):
            return base | {"reporting_currency": reporting_currency, "price_currency": price_currency, "shares_outstanding": diluted_shares, "reason": "Local currency-conversion evidence could not be read."}
        if not {"as_of_date", "pair", "rate"}.issubset(fx.columns):
            return base | {"reporting_currency": reporting_currency, "price_currency": price_currency, "shares_outstanding": diluted_shares, "reason": "Currency-conversion evidence is missing date, pair or rate."}
        fx_dates = pd.to_datetime(fx["as_of_date"], errors="coerce", utc=True)
        compact_pairs = fx["pair"].fillna("").astype(str).str.upper().str.replace(r"[^A-Z]", "", regex=True)
        direct_pair = price_currency + reporting_currency
        inverse_pair = reporting_currency + price_currency
        eligible_fx = fx_dates.notna() & fx_dates.dt.date.le(quote_date) & compact_pairs.isin((direct_pair, inverse_pair))
        matching = fx.loc[eligible_fx].copy()
        if matching.empty:
            return base | {"reporting_currency": reporting_currency, "price_currency": price_currency, "price_date": quote_date.isoformat(), "price_timestamp": quote_date.isoformat(), "shares_outstanding": diluted_shares, "reason": "No then-dated FX conversion is available by the quote date."}
        matching_dates = pd.to_datetime(matching["as_of_date"], errors="coerce", utc=True)
        newest_fx_date = matching_dates.max()
        same_date = matching.loc[matching_dates.eq(newest_fx_date)]
        pairs = same_date["pair"].fillna("").astype(str).str.upper().str.replace(r"[^A-Z]", "", regex=True)
        rates = pd.to_numeric(same_date["rate"], errors="coerce")
        if rates.isna().any() or not rates.map(math.isfinite).all() or (rates <= 0).any() or rates.nunique() != 1 or pairs.nunique() != 1:
            return base | {"reporting_currency": reporting_currency, "price_currency": price_currency, "shares_outstanding": diluted_shares, "reason": "The latest then-dated FX conversion is invalid or conflicted."}
        conversion_rate = float(rates.iloc[0])
        selected_pair = str(pairs.iloc[0])
        if selected_pair == inverse_pair:
            conversion_rate = 1.0 / conversion_rate
        conversion_timestamp = newest_fx_date.date().isoformat()
        fx_age = len(pd.bdate_range(pd.Timestamp(conversion_timestamp) + pd.offsets.BDay(1), pd.Timestamp(quote_date)))
        if price_staleness_status(fx_age) == "block":
            return base | {"reporting_currency": reporting_currency, "price_currency": price_currency, "price_date": quote_date.isoformat(), "currency_conversion_timestamp": conversion_timestamp, "shares_outstanding": diluted_shares, "reason": "Currency-conversion evidence is stale relative to the quote date."}
        if price_staleness_status(fx_age) == "warning":
            warnings.append("Currency-conversion date is more than three trading days before the quote date.")
    share_price = raw_price * conversion_rate
    market_cap = share_price * diluted_shares
    net_debt = latest_by_metric.get("net_debt")
    if net_debt is None:
        debt, cash = latest_by_metric.get("debt"), latest_by_metric.get("cash")
        if (
            debt is not None
            and cash is not None
            and latest_by_metric.get("debt_period_end") == latest_by_metric.get("cash_period_end")
            and _valuation_facts_share_basis(frame, (str(latest_by_metric.get("debt_metric", "debt")), "cash"), latest_by_metric.get("debt_period_end"))
        ):
            net_debt = debt - cash
    adjustment_period = latest_by_metric.get("net_debt_period_end") or latest_by_metric.get("debt_period_end")
    lease_liabilities = latest_by_metric.get("lease_liabilities")
    restricted_cash = latest_by_metric.get("restricted_cash")
    adjustment_status = "unavailable"
    adjustment_reason = "Lease liabilities and restricted cash must both be explicitly reported on a matching statement basis."
    other_adjustments = None
    if (
        lease_liabilities is not None
        and restricted_cash is not None
        and latest_by_metric.get("lease_liabilities_period_end") == adjustment_period
        and latest_by_metric.get("restricted_cash_period_end") == adjustment_period
        and _valuation_facts_share_basis(frame, (str(latest_by_metric.get("debt_metric", "debt")), "cash", "lease_liabilities", "restricted_cash"), adjustment_period)
    ):
        other_adjustments = lease_liabilities - restricted_cash
        adjustment_status = "available"
        adjustment_reason = "Lease liabilities are added and restricted cash is subtracted; other EV adjustments are not included unless separately sourced."
    rate_result: dict[str, object] = {"status": "unavailable", "reason": "A forecast horizon must be explicitly supplied to select a reference rate."}
    horizon = None
    if isinstance(assumptions, Mapping):
        try:
            horizon = float(assumptions.get("forecast_years"))
        except (TypeError, ValueError, OverflowError):
            horizon = None
    if horizon is not None and math.isfinite(horizon) and horizon > 0:
        try:
            rate_result = MacroWarehouse().risk_free_rate(
                root=ROOT,
                mappings=load_risk_free_proxy_mappings(),
                currency=reporting_currency,
                horizon_years=horizon,
                decision_time=cutoff.isoformat(),
            )
        except (OSError, TypeError, ValueError, KeyError):
            rate_result = {"status": "unavailable", "reason": "Then-known reference-rate evidence could not be read."}
    source_ids = sorted({str(value) for value in selected.get("source", pd.Series(dtype="object")).dropna() if str(value)})
    filing_rows = frame.copy()
    filing_vintage = [
        {
            name: str(row[name])
            for name in ("filed", "available_at", "period_end", "accession", "form", "source_id")
            if name in row and pd.notna(row[name]) and str(row[name]).strip()
        }
        for row in filing_rows.to_dict("records")
        if any(name in row and pd.notna(row[name]) and str(row[name]).strip() for name in ("filed", "accession", "source_id"))
    ]
    filing_vintage = [dict(items) for items in sorted({tuple(sorted(item.items())) for item in filing_vintage})]
    result = base | {
        "status": "available_with_warning" if warnings else "available",
        "share_price": share_price,
        "share_price_native": raw_price,
        "price_currency": price_currency,
        "price_date": quote_date.isoformat(),
        "price_timestamp": quote_date.isoformat(),
        "price_timestamp_precision": "date_only_close",
        "price_source_ids": source_ids,
        "price_staleness": price_staleness,
        "reporting_currency": reporting_currency,
        "shares_outstanding": diluted_shares,
        "share_count_basis": "diluted_shares_outstanding",
        "share_count_period_end": latest_by_metric.get("diluted_shares_outstanding_period_end"),
        "market_cap": market_cap,
        "net_debt": net_debt,
        "net_debt_period_end": latest_by_metric.get("net_debt_period_end") or latest_by_metric.get("debt_period_end"),
        "enterprise_value": None if net_debt is None or other_adjustments is None else market_cap + net_debt + other_adjustments,
        "other_enterprise_value_adjustments": other_adjustments,
        "enterprise_value_adjustments": {"status": adjustment_status, "items": {"lease_liabilities": lease_liabilities, "restricted_cash": restricted_cash}, "formula": "lease_liabilities - restricted_cash", "reason": adjustment_reason},
        "currency_conversion_rate": conversion_rate if price_currency != reporting_currency else None,
        "currency_conversion_timestamp": conversion_timestamp,
        "currency_conversion_source_ids": [] if price_currency == reporting_currency else sorted({str(value) for value in same_date.get("source", pd.Series(dtype="object")).dropna() if str(value)}),
        "risk_free_reference": rate_result,
        "filing_vintage": filing_vintage,
        "statement_periods": sorted({str(value) for value in filing_rows.get("period_end", pd.Series(dtype="object")).dropna() if str(value)}),
        "accounting_scopes": sorted({str(value) for value in frame.get("consolidation_scope", pd.Series(dtype="object")).dropna() if str(value)}),
        "warnings": warnings,
        "benchmark_context": dict(benchmark_context or {}),
        "execution_allowed": False,
    }
    result["currency"] = reporting_currency
    return result


def _valuation_latest_facts(frame: pd.DataFrame) -> dict[str, object]:
    ordered = frame.copy()
    for column in ("period_end", "filed", "fiscal_year", "source_id"):
        if column not in ordered:
            ordered[column] = ""
    ordered = ordered.sort_values(["period_end", "filed", "fiscal_year", "source_id"], kind="stable", na_position="last")
    aliases = {
        "diluted_shares_outstanding": {"diluted_shares_outstanding", "diluted_shares"},
        "net_debt": {"net_debt"},
        "debt": {"debt"},
        "cash": {"cash"},
        "lease_liabilities": {"lease_liabilities"},
        "restricted_cash": {"restricted_cash"},
    }
    result: dict[str, object] = {}
    metrics = ordered["canonical_metric"].astype(str).str.casefold()
    if metrics.eq("contractual_debt").any():
        aliases["debt"] = {"contractual_debt"}
    for output, names in aliases.items():
        rows = ordered.loc[metrics.isin(names)]
        if rows.empty:
            continue
        numeric = pd.to_numeric(rows["value"], errors="coerce").dropna()
        if numeric.empty:
            continue
        latest = rows.loc[numeric.index[-1]]
        result[output] = float(numeric.iloc[-1])
        result[f"{output}_period_end"] = latest.get("period_end")
    for metric in ("cash", "net_debt", "debt", "lease_liabilities", "restricted_cash"):
        rows = ordered.loc[metrics.isin(aliases.get(metric, {metric}))]
        if not rows.empty:
            result[f"{metric}_period_end"] = rows.iloc[-1].get("period_end")
    result["debt_metric"] = next(iter(aliases["debt"]))
    return result


def _valuation_facts_share_basis(frame: pd.DataFrame, metrics: tuple[str, ...], period_end: object) -> bool:
    if not {"period_end", "currency"}.issubset(frame.columns):
        return False
    selected = frame.loc[frame["canonical_metric"].astype(str).isin(metrics)]
    if period_end is not None:
        selected = selected.loc[selected["period_end"].astype(str).eq(str(period_end))]
    if selected.empty:
        return False
    if not set(metrics).issubset(set(selected["canonical_metric"].astype(str))):
        return False
    for column in ("period_end", "currency", "consolidation_scope", "accounting_scope"):
        if column in selected and selected[column].dropna().astype(str).nunique() > 1:
            return False
    return True


def load_financial_institution_projection(
    instrument_id: str,
    *,
    projection: FinancialInstitutionProjection | Mapping[str, object] | None = None,
    storage_root: Path | None = None,
    decision_time: str | None = None,
    effective_at: str | None = None,
    context: object | None = None,
    tactical_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Load a verified projection, or build one from local point-in-time evidence."""

    if projection is None:
        try:
            return _build_financial_projection_from_evidence(
                instrument_id,
                storage_root=storage_root,
                decision_time=decision_time,
                effective_at=effective_at,
                context=context,
                tactical_evidence=tactical_evidence,
            )
        except (FinancialAdapterError, OSError, TypeError, ValueError, KeyError):
            return unavailable_financial_projection(
                instrument_id, "financial_evidence_invalid"
            )
    try:
        payload = verify_financial_projection(projection)
        if payload.get("instrument_id") != str(instrument_id):
            raise FinancialAdapterError("financial projection identity mismatch")
        return payload
    except (FinancialAdapterError, TypeError, ValueError):
        return unavailable_financial_projection(
            instrument_id, "financial_evidence_invalid"
        )


def load_capital_allocation_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str,
    sector: str = "",
    market_inputs: Mapping[str, object] | None = None,
    corporate_actions: object = (),
    corporate_action_coverage: object | None = None,
    decision_time: str | None = None,
    storage_root: Path | None = None,
    financial_projection: object | None = None,
) -> dict[str, object]:
    """Adapt local capital-allocation evidence and delegate financial sectors."""

    resolved_sector = str(sector or "").strip()
    if not resolved_sector or resolved_sector.casefold() == "unclassified":
        classification = load_classification_projection(
            instrument_id,
            storage_root=storage_root,
            decision_time=decision_time,
        )
        context = classification.get("classification", {})
        route = classification.get("sector_adapter_route", {})
        if isinstance(context, Mapping) and isinstance(route, Mapping) and route.get("allowed") is True:
            resolved_sector = str(context.get("sector") or context.get("industry") or "")

    actions = tuple(corporate_actions) if isinstance(corporate_actions, (list, tuple)) else ()
    coverage = corporate_action_coverage if isinstance(corporate_action_coverage, CorporateActionCoverage) else None
    bank_projection = None
    if resolved_sector.casefold() in {"bank", "banks", "financial", "financials", "insurance", "insurer"}:
        bank_projection = load_financial_institution_projection(
            instrument_id,
            projection=financial_projection,
            storage_root=storage_root,
            decision_time=decision_time,
        )
    return capital_allocation_analysis(
        statements,
        instrument_id=instrument_id,
        sector=resolved_sector,
        market_inputs=market_inputs,
        corporate_actions=actions,
        corporate_action_coverage=coverage,
        as_known_at=decision_time,
        financial_projection=bank_projection,
    )


def _build_financial_projection_from_evidence(
    instrument_id: str,
    *,
    storage_root: Path | None,
    decision_time: str | None,
    effective_at: str | None,
    context: object | None,
    tactical_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Adapt #699's persisted statement/EC artifacts to the domain adapter."""
    from datetime import datetime, timezone
    from etf_cockpit.core.paths import ROOT

    root = Path(storage_root or ROOT).resolve()
    identity = _read_json_artifact(root, "identity.json", instrument_id=instrument_id) or {}
    cutoff = str(decision_time or identity.get("known_at") or "").strip()
    if not cutoff:
        return unavailable_financial_projection(instrument_id, "financial_decision_time_unavailable")
    decision = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    cutoff = decision.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    effective = str(effective_at or identity.get("effective_at") or cutoff).strip()
    requested_period = str(effective_at or identity.get("effective_at") or "").strip() or None
    if len(effective) == 10:
        effective = f"{effective}T00:00:00Z"

    if context is None:
        context = read_instrument_context(
            root,
            instrument_id,
            effective_at=effective,
            decision_time=cutoff,
        )
    if str(getattr(context, "sector", "") or "").casefold() != "financials":
        return unavailable_financial_projection(instrument_id, "financial_classification_unavailable")

    frame = _read_financial_statement_frame(root, instrument_id=instrument_id)
    rows = _financial_rows_for_instrument(frame, instrument_id, decision)
    facts = _financial_metric_facts(rows, context, cutoff, target_period=requested_period)
    if not facts:
        return unavailable_financial_projection(instrument_id, "financial_statement_evidence_unavailable")

    registry = AdapterRegistry([financial_adapter_definition()])
    result = build_financial_institution_projection(
        context,
        tuple(facts),
        registry=registry,
        decision_time=cutoff,
        shocks={},
    )
    ec_payload = _read_json_artifact(root, "ec_facts.json", instrument_id=instrument_id) or {}
    ec_revision = _select_ec_revision(ec_payload, instrument_id, decision)
    ec_facts = ec_revision.get("facts", {}) if isinstance(ec_revision, Mapping) else {}
    from etf_cockpit.analysis.sparebank import analyse_sparebank_ec
    route_evidence = {
        "facts": ec_facts,
        "instrument_id": instrument_id,
        "jurisdiction": getattr(context, "operating_country", None)
        or getattr(context, "regulatory_country", None)
        or getattr(context, "legal_domicile", None),
        "legal_form": getattr(context, "issuer_type", None) or ec_revision.get("legal_form"),
        "instrument_subtype": getattr(context, "instrument_subtype", None) or ec_revision.get("instrument_subtype"),
        "capital_class": getattr(context, "share_class_id", None) or ec_revision.get("capital_class"),
        "known_at": ec_revision.get("known_at") or next(
            (value.get("known_at") for value in ec_facts.values() if isinstance(value, Mapping) and value.get("known_at")),
            ec_payload.get("known_at"),
        ),
        "effective_at": ec_revision.get("effective_at") or next(
            (value.get("effective_at") for value in ec_facts.values() if isinstance(value, Mapping) and value.get("effective_at")),
            ec_payload.get("effective_at"),
        ),
        "source_url": ec_revision.get("source_url") or ec_revision.get("source") or ec_payload.get("source_url"),
        "source_id": ec_revision.get("source_id") or ec_payload.get("source_id"),
        "sha256": ec_revision.get("sha256") or ec_payload.get("sha256"),
        "filing_version": ec_revision.get("filing_version") or ec_payload.get("filing_version"),
        "revision_id": ec_revision.get("revision_id") or ec_payload.get("revision_id"),
    }
    valuation_assumptions = ec_revision.get("valuation_assumptions")
    valuation_assumptions = valuation_assumptions if isinstance(valuation_assumptions, Mapping) else None
    valuation_currency = str(
        (valuation_assumptions or {}).get("currency")
        or (valuation_assumptions or {}).get("output_currency")
        or ""
    ).strip().upper()
    price_path = root / "data" / "clean" / "prices.parquet"
    decision_price = None
    decision_price_projection: dict[str, object] = {
        "status": "unavailable",
        "reason_code": "decision_price_store_missing",
        "execution_allowed": False,
    }
    if price_path.is_file():
        try:
            from etf_cockpit.data.duckdb_store import load_prices

            prices = load_prices(price_path)
            if not {"instrument_id", "date", "close", "currency"}.issubset(prices.columns):
                decision_price_projection["reason_code"] = "decision_price_store_invalid"
            else:
                eligible = prices.loc[prices["instrument_id"].astype(str).eq(str(instrument_id))].copy()
                eligible["_price_date"] = pd.to_datetime(eligible["date"], errors="coerce", utc=True)
                eligible = eligible.loc[eligible["_price_date"].notna() & eligible["_price_date"].le(pd.Timestamp(decision))]
                if eligible.empty:
                    decision_price_projection["reason_code"] = "decision_price_unavailable_as_of_decision"
                else:
                    price_row = eligible.sort_values("_price_date", kind="stable").iloc[-1]
                    close = pd.to_numeric(pd.Series([price_row["close"]]), errors="coerce").iloc[0]
                    currency_value = price_row["currency"]
                    price_currency = "" if pd.isna(currency_value) else str(currency_value).strip().upper()
                    if pd.isna(close) or not math.isfinite(float(close)) or float(close) <= 0:
                        decision_price_projection["reason_code"] = "decision_price_invalid"
                    elif not valuation_currency or not price_currency:
                        decision_price_projection["reason_code"] = "decision_price_currency_unavailable"
                    elif price_currency != valuation_currency:
                        decision_price_projection.update(
                            reason_code="decision_price_currency_mismatch",
                            date=price_row["_price_date"].date().isoformat(),
                            currency=price_currency,
                            valuation_currency=valuation_currency,
                        )
                    else:
                        decision_price = float(close)
                        decision_price_projection = {
                            "status": "available",
                            "price": decision_price,
                            "date": price_row["_price_date"].date().isoformat(),
                            "currency": price_currency,
                            "valuation_currency": valuation_currency,
                            "execution_allowed": False,
                        }
        except Exception:
            decision_price_projection["reason_code"] = "decision_price_store_invalid"
    sparebank_analysis = analyse_sparebank_ec(
        route_evidence,
        decision_time=cutoff,
        price=decision_price,
        bank_metrics=result.metrics,
        bank_economics_evidence=(ec_revision.get("bank_economics_evidence") if isinstance(ec_revision, Mapping) else None),
        events=(ec_revision.get("events", ()) if isinstance(ec_revision, Mapping) else ()),
        valuation_assumptions=valuation_assumptions,
        tactical_evidence=tactical_evidence,
    )
    if sparebank_analysis.routing.applies or (isinstance(ec_facts, Mapping) and ec_facts):
        from dataclasses import asdict, replace
        identity_payload = dict(result.share_class_identity) if isinstance(result.share_class_identity, Mapping) else {}
        identity_payload["facts"] = {
            name: {
                "available": bool(value.get("available")) if isinstance(value, Mapping) else False,
                "value": value.get("value") if isinstance(value, Mapping) else None,
                "unit": value.get("unit") if isinstance(value, Mapping) else None,
                "period": value.get("period") if isinstance(value, Mapping) else None,
                "known_at": value.get("known_at") if isinstance(value, Mapping) else None,
                "source": value.get("source_url") if isinstance(value, Mapping) else None,
            }
            for name, value in ec_facts.items()
            if isinstance(ec_facts, Mapping)
        }
        sparebank_payload = asdict(sparebank_analysis)
        sparebank_payload["decision_price"] = decision_price_projection
        source_vintage_hash = _source_vintage_hash(route_evidence.get("sha256")) or "unavailable"
        sparebank_payload["source_vintage_hash"] = source_vintage_hash
        scorecard = sparebank_analysis.scorecard
        composite = getattr(scorecard, "composite_10", None)
        if isinstance(composite, Real) and not isinstance(composite, bool) and math.isfinite(float(composite)):
            try:
                from etf_cockpit.data.score_history import append_score_run

                append_score_run(
                    pd.DataFrame(
                        [
                            {
                                "instrument_id": str(instrument_id),
                                "final_combined_score_10": float(composite),
                                "price_as_of_date": decision_price_projection.get("date", ""),
                                "data_as_of_date": decision.date().isoformat(),
                                "formula_version": getattr(scorecard, "formula_version", "unavailable"),
                                "formula_checksum": getattr(scorecard, "formula_checksum", "unavailable"),
                                "source_vintage_hash": source_vintage_hash,
                            }
                        ]
                    ),
                    f"sparebank:{instrument_id}:{cutoff}",
                    cutoff,
                    root=root,
                )
                history_status = {"status": "written", "reason": None}
            except Exception:
                history_status = {"status": "not_written", "reason": "score_history_write_failed"}
        else:
            reason = decision_price_projection.get("reason_code")
            if not reason:
                reason = "scorecard_blocked" if getattr(scorecard, "status", None) == "BLOCKED" else "scorecard_composite_unavailable"
            history_status = {"status": "not_written", "reason": reason}
        sparebank_payload["history_status"] = history_status
        identity_payload["sparebank_analysis"] = sparebank_payload
        identity_payload["native_suite"] = sparebank_analysis.contract if sparebank_analysis.routing.applies else None
        identity_payload["claim_status"] = sparebank_analysis.claim_state.claim_status
        identity_payload["generic_valuation_status"] = sparebank_analysis.generic_valuation_status
        identity_payload["generic_valuation_reason"] = sparebank_analysis.generic_valuation_reason
        if sparebank_analysis.generic_valuation_status == "inapplicable":
            result = replace(
                result,
                limitations=tuple(sorted({*result.limitations, "generic_bank_valuation:inapplicable_sparebank_claim"})),
            )
        result = replace(result, share_class_identity=identity_payload)
        from etf_cockpit.analysis.financial_sector_adapters import _hash as _financial_hash
        payload = result.__dict__.copy()
        payload.pop("result_hash", None)
        result = replace(result, result_hash=_financial_hash(payload))
    return verify_financial_projection(result)


def _evidence_roots(root: Path, instrument_id: str = "") -> tuple[Path, ...]:
    canonical = root / "evidence" / "norway"
    roots: list[Path] = [root]
    if instrument_id:
        prefix = f"{str(instrument_id).strip().upper()}-"
        try:
            roots.extend(sorted((item for item in canonical.iterdir() if item.is_dir() and item.name.upper().startswith(prefix)), key=lambda item: item.name))
        except OSError:
            pass
    roots.extend((canonical, root / "evidence"))
    return tuple(dict.fromkeys(roots))


def _select_ec_facts(payload: Mapping[str, object], instrument_id: str, decision: object) -> Mapping[str, object]:
    """Select the identity-bound EC revision known at the decision cutoff."""

    selected = _select_ec_revision(payload, instrument_id, decision)
    facts = selected.get("facts") if isinstance(selected, Mapping) else None
    return facts if isinstance(facts, Mapping) else {}


def _select_ec_revision(payload: Mapping[str, object], instrument_id: str, decision: object) -> Mapping[str, object]:
    """Return the complete identity-bound EC revision envelope at the cutoff."""

    cutoff = pd.Timestamp(decision)
    revisions = payload.get("revisions")
    eligible: list[Mapping[str, object]] = []
    if isinstance(revisions, list):
        for revision in revisions:
            if not isinstance(revision, Mapping) or str(revision.get("instrument_id") or "") != str(instrument_id):
                continue
            known = pd.to_datetime(revision.get("known_at"), errors="coerce", utc=True)
            if pd.isna(known) or known > cutoff:
                continue
            facts = revision.get("facts")
            if isinstance(facts, Mapping):
                eligible.append(revision)
    if eligible:
        selected = max(eligible, key=lambda item: pd.Timestamp(item.get("known_at")))
        return selected
    # Backward-compatible read of a single pre-revision artifact, still bound
    # to the requested instrument and point-in-time cutoff.
    if str(payload.get("instrument_id") or instrument_id) != str(instrument_id):
        return {}
    known = pd.to_datetime(payload.get("known_at"), errors="coerce", utc=True)
    facts = payload.get("facts")
    return payload if isinstance(facts, Mapping) and not pd.isna(known) and known <= cutoff else {}


def _read_json_artifact(root: Path, name: str, *, instrument_id: str = "") -> dict[str, object] | None:
    import json

    candidates = tuple(item / name for item in _evidence_roots(root, instrument_id))
    for candidate in candidates:
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _read_financial_statement_frame(root: Path, *, instrument_id: str = "") -> pd.DataFrame:
    candidates = tuple(item / "statement_facts.parquet" for item in _evidence_roots(root, instrument_id)) + (
        root / "data" / "clean" / "statement_facts.parquet",
        root / "normalised_statements.parquet",
    )
    for candidate in candidates:
        try:
            if candidate.exists():
                frame = pd.read_parquet(candidate)
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    return frame
        except (OSError, ValueError, ImportError):
            continue
    return pd.DataFrame()


def _financial_rows_for_instrument(
    frame: pd.DataFrame, instrument_id: str, decision: object
) -> list[dict[str, object]]:
    if frame.empty or "instrument_id" not in frame.columns:
        return []
    scoped = frame.loc[frame["instrument_id"].astype(str).eq(str(instrument_id))]
    cutoff = pd.Timestamp(decision)
    rows: list[dict[str, object]] = []
    for row in scoped.to_dict("records"):
        known_raw = row.get("known_at") or row.get("available_at") or row.get("filed")
        effective_raw = row.get("effective_at") or row.get("end") or row.get("instant")
        known = pd.to_datetime(known_raw, errors="coerce", utc=True)
        effective = pd.to_datetime(effective_raw, errors="coerce", utc=True)
        if pd.isna(known) or known > cutoff or pd.isna(effective) or effective > cutoff:
            continue
        row["_known"] = known
        row["_effective"] = effective
        rows.append(row)
    return rows


def _row_period(row: Mapping[str, object]) -> pd.Timestamp | None:
    value = row.get("effective_at") or row.get("end") or row.get("instant") or row.get("period")
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _financial_metric_facts(
    rows: list[dict[str, object]], context: object, cutoff: str, *, target_period: str | None = None
) -> list[FinancialMetricEvidence]:
    from etf_cockpit.analysis.financial_sector_adapters import _METRICS, _REGULATORY

    model = "bank"
    candidates: dict[str, dict[str, object]] = {}
    aliases = {
        "liquidity_coverage_ratio": "liquidity_coverage_ratio",
        "lcr": "liquidity_coverage_ratio",
        "nsfr": "net_stable_funding_ratio",
        "net_stable_funding_ratio": "net_stable_funding_ratio",
        "cet1": "cet1_ratio",
        "cet1_ratio": "cet1_ratio",
        "total_capital": "total_capital_ratio",
        "total_capital_ratio": "total_capital_ratio",
        "leverage": "leverage_ratio",
        "leverage_ratio": "leverage_ratio",
        "net_interest_margin": "net_interest_margin",
        "npl_ratio": "npl_ratio",
        "stage_2_exposure": "stage_2_exposure",
        "stage_3_exposure": "stage_3_exposure",
        "cost_of_risk": "cost_of_risk",
        "dividend": "dividends",
        "dividends": "dividends",
        "retained_earnings": "retained_earnings",
        "net_fee_income": "net_fee_income",
        "fee_income": "net_fee_income",
        "other_operating_income": "other_operating_income",
        "other_income": "other_operating_income",
        "net_profit": "net_profit",
        "net_profit_attributable": "net_profit_attributable",
        "net_income_attributable": "net_profit_attributable",
        "profit_attributable": "net_profit_attributable",
        "opening_equity": "opening_equity",
        "closing_equity": "closing_equity",
        "equity": "closing_equity",
        "opening_tangible_equity": "opening_tangible_equity",
        "closing_tangible_equity": "closing_tangible_equity",
        "tangible_equity": "closing_tangible_equity",
        "interest_earning_assets": "interest_earning_assets",
        "average_interest_earning_assets": "interest_earning_assets",
        "opening_interest_earning_assets": "opening_interest_earning_assets",
        "closing_interest_earning_assets": "closing_interest_earning_assets",
        "total_assets": "total_assets",
        "opening_total_assets": "opening_total_assets",
        "closing_total_assets": "closing_total_assets",
        "gross_loans": "gross_loans",
        "opening_gross_loans": "opening_gross_loans",
        "closing_gross_loans": "closing_gross_loans",
        "impairment_losses": "impairment_losses",
        "loss_allowance": "loss_allowance",
        "shares_outstanding": "shares_outstanding",
        "payout": "payout_headroom",
        "payout_ratio": "payout_headroom",
        "tangible_book_value": "tangible_book_value",
        "price_to_book": "price_to_book",
        "price_to_tangible_book": "price_to_tangible_book",
    }
    derivation_inputs = {
        "loans_to_customers", "deposits_from_customers", "operating_expenses", "net_interest_income",
        "net_fee_income", "other_operating_income", "net_profit", "net_profit_attributable",
        "opening_equity", "closing_equity", "opening_tangible_equity", "closing_tangible_equity",
        "interest_earning_assets", "total_assets", "gross_loans", "impairment_losses", "loss_allowance",
        "opening_interest_earning_assets", "closing_interest_earning_assets", "opening_total_assets", "closing_total_assets",
        "opening_gross_loans", "closing_gross_loans",
        "shares_outstanding",
    }
    for row in rows:
        raw_metric = str(row.get("canonical_metric") or row.get("concept") or "").strip().casefold()
        metric = aliases.get(raw_metric, raw_metric)
        if metric not in _METRICS[model] and metric not in derivation_inputs:
            continue
        if target_period and not metric.startswith("opening_"):
            target = pd.Timestamp(target_period)
            row_period = _row_period(row)
            if row_period is not None and row_period.date() != target.date():
                # Retain a sole comparative so a mismatched-period formula is
                # explicitly unavailable; a requested-period row supersedes it.
                if metric not in candidates:
                    candidates[metric] = row
                continue
        previous = candidates.get(metric)
        if previous is not None and (row["_effective"], row["_known"]) <= (previous["_effective"], previous["_known"]):
            continue
        candidates[metric] = row

    def numeric(row: dict[str, object]) -> float | None:
        try:
            value = float(row.get("value"))
            return value if math.isfinite(value) else None
        except (TypeError, ValueError):
            return None

    def category(row: dict[str, object], metric: str) -> str:
        explicit = str(row.get("fact_category") or "").strip().casefold()
        source = f"{row.get('source_id', '')} {row.get('taxonomy', '')} {row.get('concept', '')}".casefold()
        if explicit in {"pillar3", "regulatory", "market", "issuer_apm", "calculated", "ifrs"}:
            return "pillar3" if explicit == "regulatory" else explicit
        if metric in _REGULATORY and any(token in source for token in ("pillar", "prudential", "regulatory", "eba")):
            return "pillar3"
        if "market" in source or "quote" in source:
            return "market"
        if row.get("is_custom") or "extension" in source:
            return "issuer_apm"
        return "ifrs"

    def fact(
        metric: str,
        value: float | None,
        row: dict[str, object] | None,
        *,
        fact_category: str = "calculated",
        definition: str = "",
        limitations: tuple[str, ...] = (),
        source_id_override: str | None = None,
        inputs: tuple[dict[str, object], ...] = (),
        calculated_period: str | None = None,
        calculated_unit: str | None = None,
    ) -> FinancialMetricEvidence:
        selected = row or {}
        lineage_rows = inputs or ((selected,) if row else ())
        known = max((item.get("_known") for item in lineage_rows if item.get("_known") is not None), default=selected.get("_known"))
        effective = calculated_period or selected.get("_effective")
        def aware_iso(value: object, fallback: str) -> str:
            if value is None:
                return fallback
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is None:
                stamp = stamp.tz_localize("UTC")
            return stamp.isoformat().replace("+00:00", "Z")
        known_at = aware_iso(known, cutoff)
        as_of = aware_iso(effective, cutoff)
        lineage_ids = tuple(sorted(str(item.get("source_id")) for item in lineage_rows if item.get("source_id")))
        source_id = str(source_id_override or selected.get("source_id") or f"unavailable:{metric}")
        if inputs and lineage_ids:
            source_id = f"{source_id}|inputs={','.join(lineage_ids)}"
        unit = str(calculated_unit or selected.get("unit") or "ratio")
        if value is None:
            unit = (
                "currency_per_share"
                if metric == "tangible_book_value"
                else "currency"
                if metric in {"dividends", "retained_earnings", "issuance_dilution", "residual_income_input"}
                else "ratio"
            )
        if metric in {"dividends", "retained_earnings", "issuance_dilution", "residual_income_input"} and unit.casefold() not in {"shares", "currency_per_share", "currency"}:
            unit = "currency"
        return FinancialMetricEvidence(
            metric=metric,
            value=value,
            unit="percent" if unit.casefold() in {"percent", "%"} else unit,
            period=str(calculated_period or selected.get("fiscal_year") or selected.get("end") or selected.get("instant") or "undated"),
            reporting_standard="IFRS" if fact_category == "ifrs" else fact_category.upper(),
            jurisdiction=str(getattr(context, "operating_country", None) or "NO"),
            business_model=model,
            source_id=source_id,
            source_authority=(
                SourceAuthority.OFFICIAL
                if fact_category in {"ifrs", "pillar3", "regulatory"}
                else SourceAuthority.MANUAL
                if fact_category == "calculated"
                else SourceAuthority.ISSUER
            ),
            as_of=as_of,
            known_at=known_at,
            direction=None,
            fact_category=fact_category,
            definition=definition,
            scope=str(selected.get("consolidation_scope") or (lineage_rows[0].get("consolidation_scope") if lineage_rows else None) or "consolidated"),
            coverage="reported" if row else ("derived" if value is not None else "unavailable"),
            source=";".join(str(item.get("source_url") or item.get("source_id") or "") for item in lineage_rows) or str(selected.get("source_url") or source_id),
            limitations=limitations,
        )

    facts: list[FinancialMetricEvidence] = []
    for metric in sorted(_METRICS[model]):
        row = candidates.get(metric)
        value = numeric(row) if row is not None else None
        category_name = category(row, metric) if row is not None else ("pillar3" if metric in _REGULATORY else "calculated")
        facts.append(fact(metric, value, row, fact_category=category_name))

    def compatible(input_names: tuple[str, ...], *, allow_opening: bool = False) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
        selected: list[dict[str, object]] = []
        for name in input_names:
            item = candidates.get(name)
            if item is None and allow_opening and name.startswith("opening_"):
                continue
            if item is None:
                return (), ("missing_input",)
            selected.append(item)
        if not selected:
            return (), ("missing_input",)
        reasons: set[str] = set()
        periods = {_row_period(item).date() for item in selected if _row_period(item) is not None and not (allow_opening and str(item.get("canonical_metric") or "").casefold().startswith("opening_"))}
        if len(periods) > 1:
            reasons.add("period_mismatch")
        currencies = {str(item.get("currency") or str(item.get("unit") or "").split("/", 1)[0]).upper() for item in selected if item.get("currency") or item.get("unit")}
        if len(currencies) > 1:
            reasons.add("currency_mismatch")
        scopes = {str(item.get("consolidation_scope") or "consolidated").casefold() for item in selected}
        if len(scopes) > 1:
            reasons.add("scope_mismatch")
        if target_period:
            target = pd.Timestamp(target_period).date()
            if any(_row_period(item) is not None and _row_period(item).date() != target and not (allow_opening and str(item.get("canonical_metric") or "").casefold().startswith("opening_")) for item in selected):
                reasons.add("period_mismatch")
        return tuple(selected), tuple(sorted(reasons))

    def emit(metric: str, result: float | None, inputs: tuple[dict[str, object], ...], reasons: tuple[str, ...], definition: str, *, unit: str = "ratio", period: str | None = None) -> None:
        facts[:] = [item for item in facts if item.metric != metric]
        limitations = reasons or (() if result is not None else ("missing_input",))
        inferred_period = _row_period(inputs[0]).date().isoformat() if inputs and _row_period(inputs[0]) is not None else cutoff
        facts.append(fact(metric, result, None, definition=definition, limitations=limitations, source_id_override=f"calculated:{metric}", inputs=inputs, calculated_period=period or target_period or inferred_period, calculated_unit=unit))

    selected, reasons = compatible(("loans_to_customers", "deposits_from_customers"))
    denom = selected[1].get("value") if len(selected) == 2 else None
    emit("loan_deposit_ratio", None if reasons or denom is None or float(denom) <= 0 else float(selected[0].get("value")) / float(denom), selected, reasons + (("invalid_denominator",) if denom is None or (denom is not None and float(denom) <= 0) else ()), "loans_to_customers / deposits_from_customers")

    selected, reasons = compatible(("operating_expenses", "net_interest_income", "net_fee_income", "other_operating_income"))
    income = sum(float(item.get("value")) for item in selected[1:]) if len(selected) == 4 else None
    emit("cost_income_ratio", None if reasons or income is None or income <= 0 else float(selected[0].get("value")) / income, selected, reasons + (("invalid_denominator",) if income is None or (income is not None and income <= 0) else ()), "operating_expenses / (net_interest_income + net_fee_income + other_operating_income)")

    selected, reasons = compatible(("net_profit_attributable", "opening_equity", "closing_equity"), allow_opening=True)
    opening = candidates.get("opening_equity")
    closing = candidates.get("closing_equity")
    roe_inputs = tuple(item for item in (candidates.get("net_profit_attributable"), opening, closing) if item is not None)
    average_equity = (float(opening.get("value")) + float(closing.get("value"))) / 2 if opening and closing else None
    emit("roe", None if reasons or average_equity is None or average_equity <= 0 else float(candidates["net_profit_attributable"].get("value")) / average_equity, roe_inputs, reasons + (("missing_opening_equity",) if opening is None else ()) + (("invalid_denominator",) if average_equity is None or (average_equity is not None and average_equity <= 0) else ()), "net_profit_attributable / average(opening_equity, closing_equity)")

    selected, reasons = compatible(("net_profit_attributable", "opening_tangible_equity", "closing_tangible_equity"), allow_opening=True)
    opening = candidates.get("opening_tangible_equity")
    closing = candidates.get("closing_tangible_equity")
    rote_inputs = tuple(item for item in (candidates.get("net_profit_attributable"), opening, closing) if item is not None)
    average_tangible = (float(opening.get("value")) + float(closing.get("value"))) / 2 if opening and closing else None
    emit("rote", None if reasons or average_tangible is None or average_tangible <= 0 else float(candidates["net_profit_attributable"].get("value")) / average_tangible, rote_inputs, reasons + (("missing_opening_tangible_equity",) if opening is None else ()) + (("invalid_denominator",) if average_tangible is None or (average_tangible is not None and average_tangible <= 0) else ()), "net_profit_attributable / average(opening_tangible_equity, closing_tangible_equity)")

    base = candidates.get("net_interest_income")
    assets_open = candidates.get("opening_interest_earning_assets")
    assets_close = candidates.get("closing_interest_earning_assets")
    if assets_open and assets_close:
        selected, reasons = compatible(("net_interest_income", "opening_interest_earning_assets", "closing_interest_earning_assets"), allow_opening=True)
        denominator = (float(assets_open.get("value")) + float(assets_close.get("value"))) / 2
        nim_definition = "net_interest_income / average(interest_earning_assets)"
    else:
        selected, reasons = compatible(("net_interest_income", "interest_earning_assets"))
        if len(selected) != 2:
            assets_open = candidates.get("opening_total_assets")
            assets_close = candidates.get("closing_total_assets")
            if assets_open and assets_close:
                selected, reasons = compatible(("net_interest_income", "opening_total_assets", "closing_total_assets"), allow_opening=True)
                denominator = (float(assets_open.get("value")) + float(assets_close.get("value"))) / 2
            else:
                selected, reasons = compatible(("net_interest_income", "total_assets"))
                denominator = float(selected[1].get("value")) if len(selected) == 2 else None
            nim_definition = "net_interest_income / average(total_assets) (disclosed proxy)"
        else:
            nim_definition = "net_interest_income / average(interest_earning_assets)"
            denominator = float(selected[1].get("value"))
    emit("net_interest_margin", None if reasons or base is None or denominator is None or denominator <= 0 else float(base.get("value")) / denominator, selected, reasons + (("invalid_denominator",) if denominator is None or denominator <= 0 else ()), nim_definition)

    loans_open = candidates.get("opening_gross_loans")
    loans_close = candidates.get("closing_gross_loans")
    if loans_open and loans_close:
        selected, reasons = compatible(("impairment_losses", "opening_gross_loans", "closing_gross_loans"), allow_opening=True)
        denominator = (float(loans_open.get("value")) + float(loans_close.get("value"))) / 2
    else:
        selected, reasons = compatible(("impairment_losses", "gross_loans"))
        denominator = float(selected[1].get("value")) if len(selected) == 2 else None
    emit("cost_of_risk", None if reasons or len(selected) < 2 or denominator is None or denominator <= 0 else float(selected[0].get("value")) / denominator, selected, reasons + (("invalid_denominator",) if denominator is None or denominator <= 0 else ()), "impairment_losses / average(gross_loans)")
    selected, reasons = compatible(("loss_allowance", "stage_3_exposure"))
    emit("coverage_ratio", None if reasons or len(selected) != 2 or float(selected[1].get("value")) <= 0 else float(selected[0].get("value")) / float(selected[1].get("value")), selected, reasons + (("invalid_denominator",) if len(selected) != 2 or float(selected[1].get("value")) <= 0 else ()), "loss_allowance / stage_3_exposure")
    selected, reasons = compatible(("dividends", "net_profit"))
    emit("payout_headroom", None if reasons or len(selected) != 2 or float(selected[1].get("value")) == 0 else float(selected[0].get("value")) / float(selected[1].get("value")), selected, reasons + (("invalid_denominator",) if len(selected) != 2 or float(selected[1].get("value")) == 0 else ()), "dividends / net_profit")
    return facts


def load_real_asset_projection(
    instrument_id: str,
    *,
    projection: RealAssetProjection | Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Verify optional in-memory real-asset evidence; never calculate in the UI."""

    if projection is None:
        return unavailable_real_asset_projection(instrument_id)
    try:
        payload = verify_real_asset_projection(projection)
        if payload.get("instrument_id") != str(instrument_id):
            raise RealAssetAdapterError("real-asset projection identity mismatch")
        return payload
    except (RealAssetAdapterError, TypeError, ValueError):
        return unavailable_real_asset_projection(instrument_id, "real_asset_evidence_invalid")


def load_cyclical_projection(
    instrument_id: str,
    *,
    projection: CyclicalProjection | Mapping[str, object] | None = None,
    expected_source_digest: str | None = None,
) -> dict[str, object]:
    """Verify optional in-memory cyclical evidence; never calculate in the UI."""

    if projection is None or expected_source_digest is None:
        return unavailable_cyclical_projection(instrument_id)
    try:
        payload = verify_cyclical_projection(
            projection,
            expected_source_digest=expected_source_digest,
        )
        if payload.get("instrument_id") != str(instrument_id):
            raise CyclicalAdapterError("cyclical projection identity mismatch")
        return payload
    except (CyclicalAdapterError, TypeError, ValueError):
        return unavailable_cyclical_projection(instrument_id, "cyclical_evidence_invalid")


def load_innovation_projection(
    instrument_id: str,
    *,
    projection: InnovationProjection | Mapping[str, object] | None = None,
    expected_source_digest: str | None = None,
) -> dict[str, object]:
    """Verify optional local innovation-sector evidence; never calculate in UI."""

    if projection is None or expected_source_digest is None:
        return unavailable_innovation_projection(instrument_id)
    try:
        payload = verify_innovation_projection(
            projection,
            expected_source_digest=expected_source_digest,
        )
        if payload.get("instrument_id") != str(instrument_id):
            raise InnovationAdapterError("innovation projection identity mismatch")
        return payload
    except (InnovationAdapterError, TypeError, ValueError):
        return unavailable_innovation_projection(instrument_id, "innovation_evidence_invalid")


def save_classification_overrides(
    storage_root: Path,
    overrides: tuple[ClassificationOverride, ...],
) -> dict[str, object]:
    """Persist reviewed local overrides through the application boundary."""

    try:
        with ClassificationStore(Path(storage_root).resolve()) as store:
            record_ids = store.append_overrides(overrides)
        return {
            "status": "saved",
            "record_ids": record_ids,
            "dependent_scores_invalidated": bool(record_ids),
            "execution_allowed": False,
        }
    except (ClassificationSchemaError, OSError, ValueError) as exc:
        return {
            "status": "rejected",
            "record_ids": (),
            "reason_code": "classification_override_rejected",
            "message": str(exc),
            "dependent_scores_invalidated": False,
            "execution_allowed": False,
        }


def load_paper_trade_rows(root: Path) -> tuple[dict[str, object], ...]:
    """Return safe, local paper-trade rows for presentation selectors."""

    from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError

    try:
        return PaperLedger(root).trade_rows()
    except (OSError, PaperLedgerError, ValueError):
        return ()


def load_canary_status(
    root: Path | None = None,
    *,
    account_id: str = "local-paper",
    config: object | None = None,
) -> dict[str, object]:
    """Expose the local paper-canary state and its permanently blocked live gate."""

    from etf_cockpit.trading.canary import CanaryConfig, CanaryController, CanaryError

    if config is not None and not isinstance(config, CanaryConfig):
        return {
            "state": "invalid",
            "stage": "disabled",
            "opted_in": False,
            "live_submission": "blocked",
            "live_unmet_dependencies": ["canary_config_invalid"],
            "execution_allowed": False,
        }
    try:
        return CanaryController(root or ROOT, account_id=account_id, config=config).status()
    except (CanaryError, OSError, TypeError, ValueError):
        return {
            "state": "invalid",
            "stage": "disabled",
            "opted_in": False,
            "live_submission": "blocked",
            "live_unmet_dependencies": ["canary_state_unavailable"],
            "execution_allowed": False,
        }


def load_paper_incidents(root: Path, *, account_id: str = "local-paper") -> dict[str, object]:
    """Expose the verified local incident journal to presentation selectors."""

    from etf_cockpit.trading.incidents import IncidentJournal, IncidentJournalError

    journal = IncidentJournal(root, account_id=account_id)
    try:
        projection = journal.snapshot()
        events = projection["events"]
        frozen = bool(projection["frozen"])
    except (OSError, IncidentJournalError, ValueError):
        return {
            "status": "invalid",
            "incidents": [],
            "postmortems": [],
            "reconciliations": [],
            "frozen": True,
            "reason_code": "incident_journal_invalid",
            "execution_allowed": False,
        }
    return {
        "status": "frozen" if frozen else "available",
        "incidents": [dict(event["payload"]) for event in events if event["event_type"] == "incident_recorded"],
        "postmortems": [dict(event["payload"]) for event in events if event["event_type"] == "postmortem_recorded"],
        "reconciliations": [dict(event["payload"]) for event in events if event["event_type"] == "reconciliation_recorded"],
        "frozen": frozen,
        "source_authority": "local_paper_incident_journal",
        "execution_allowed": False,
    }


def load_paper_timeline(
    root: Path,
    instrument_id: str,
    *,
    account_id: str = "local-paper",
) -> dict[str, object]:
    """Read one paper account's validated lifecycle history for presentation."""

    from etf_cockpit.portfolio.paper_trading import (
        PaperLedger,
        PaperLedgerError,
        PaperLedgerIntegrityError,
    )

    ledger = PaperLedger(root, account_id=account_id)
    if not ledger.path.exists():
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "rows": [],
            "reason_code": "paper_ledger_missing",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    try:
        rows = ledger.timeline_rows(instrument_id)
    except (OSError, PaperLedgerIntegrityError, PaperLedgerError, ValueError):
        return {
            "status": "invalid",
            "instrument_id": str(instrument_id),
            "rows": [],
            "reason_code": "paper_ledger_invalid",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    return {
        "status": "available",
        "instrument_id": str(instrument_id),
        "rows": list(rows),
        "source_authority": "local_paper_ledger",
        "message": "Recorded paper lifecycle history; this is not a historical account reconstruction.",
        "execution_allowed": False,
    }


def load_paper_tca_view(storage_root: Path | None = None, *, account_id: str = "local-paper") -> dict[str, object]:
    """Load ledger-backed fill attribution and persist completed-fill projections."""

    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError
    from etf_cockpit.trading.tca import (
        TCAAttributionStore,
        TCACalculator,
        calibrate_completed_fills,
    )

    root = Path(storage_root or ROOT).resolve()
    ledger = PaperLedger(root, account_id=account_id)
    if not ledger.path.exists():
        return {
            "status": "unavailable",
            "rows": [],
            "calibration": calibrate_completed_fills(()),
            "reason_code": "paper_ledger_missing",
            "message": "Paper ledger is missing; no fills or costs are inferred.",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    try:
        orders = {str(row.get("order_id")): row for row in ledger.orders()}
        fills = ledger.trade_rows()
        calculator = TCACalculator()
        cumulative_fills: dict[str, float] = {}
        records_list = []
        for fill in fills:
            order_id = str(fill.get("order_id"))
            order = orders.get(order_id)
            cumulative = cumulative_fills.get(order_id, 0.0) + float(fill.get("quantity", 0.0))
            cumulative_fills[order_id] = cumulative
            order_quantity = float((order or {}).get("quantity", 0.0))
            fill_is_completion = (
                order is not None
                and order.get("status") == "filled"
                and order_quantity > 0
                and cumulative + 1e-8 >= order_quantity
            )
            records_list.append(
                calculator.calculate(
                    fill,
                    order,
                    fill_is_completion=fill_is_completion,
                    account_id=account_id,
                )
            )
        records = tuple(records_list)
        store = TCAAttributionStore(ledger.path.parent / "tca_attributions")
        store.persist(records)
        stored_records = store.load()
    except (OSError, PaperLedgerError, ValueError, TypeError):
        return {
            "status": "invalid",
            "rows": [],
            "calibration": calibrate_completed_fills(()),
            "reason_code": "paper_tca_unavailable",
            "message": "Paper ledger or persisted TCA attribution is invalid; no costs are reported.",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    limitations = tuple(
        sorted({item for record in records for item in record.benchmark_limitations})
    )
    completed = sum(record.completed_order for record in records)
    return {
        "status": "available",
        "rows": [record.as_dict() for record in records],
        "calibration": calibrate_completed_fills(records),
        "coverage": {
            "fill_count": len(records),
            "order_linked_fill_count": sum(record.association_status == "order_linked" for record in records),
            "unexpected_fill_count": sum(record.association_status == "unexpected" for record in records),
            "completed_fill_count": completed,
            "decomposed_fill_count": sum(record.reconciliation_status == "reconciled" for record in records),
            "persisted_attribution_count": len(stored_records),
            "benchmark_limitations": list(limitations),
        },
        "reason_code": None if records else "no_fills_recorded",
        "message": (
            "Fill fees reconcile to the paper ledger. Delay, spread and impact require decision and arrival benchmarks; "
            "missing benchmarks remain unavailable."
        ),
        "source_authority": "local_paper_ledger",
        "execution_allowed": False,
    }


def _load_market_series_projection(
    prices: object,
    instrument_id: str,
    *,
    basis: str,
    local_currency: str,
    output_currency: str | None = None,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Build a fail-closed raw/adjusted/total-return chart projection."""

    import pandas as pd

    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.data.local_storage import storage_layout
    from etf_cockpit.data.market_adjustments import (
        CorporateActionCoverageStore,
        CorporateActionStore,
        FXObservationStore,
        apply_total_return_adjustments,
        derive_fx_cross,
    )

    if not isinstance(prices, pd.DataFrame) or prices.empty or basis not in {"raw", "adjusted", "total_return"}:
        return {"status": "unavailable", "reason_code": "market_series_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    identifier = "etf_id" if "etf_id" in prices.columns else "instrument_id" if "instrument_id" in prices.columns else None
    if identifier is None or "date" not in prices.columns:
        return {"status": "unavailable", "reason_code": "market_series_schema_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    scoped = prices.loc[prices[identifier].astype(str).eq(str(instrument_id))].copy()
    if scoped.empty:
        return {"status": "unavailable", "reason_code": "market_series_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    root = Path(storage_root or ROOT).resolve()
    actions = ()
    action_coverage = ()
    fx_observations = ()
    latest = pd.to_datetime(scoped["date"], errors="coerce", utc=True).max()
    cutoff = decision_time or (latest.isoformat() if pd.notna(latest) else None)
    if storage_layout(root).transactional_path.exists() and cutoff is not None and pd.notna(latest):
        with CorporateActionCoverageStore(root) as store:
            action_coverage = store.as_of(str(instrument_id), valid_at=latest.isoformat(), known_at=cutoff)
        with CorporateActionStore(root) as store:
            actions = store.as_of(str(instrument_id), known_at=cutoff)
        with FXObservationStore(root) as store:
            fx_observations = store.query()
    close_column = "close" if "close" in scoped.columns else None
    if close_column is None:
        if basis != "raw" and not action_coverage:
            return {"status": "unavailable", "reason_code": "corporate_action_coverage_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
        if basis == "adjusted" and action_coverage and "adjusted_close" in scoped.columns and (output_currency or local_currency).upper() == local_currency.upper():
            frame = scoped[["date", "adjusted_close"]].copy()
            frame["series_value"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
            frame = frame.dropna(subset=["series_value"])
            if not frame.empty:
                return {"status": "available", "basis": "provider_adjusted", "currency": local_currency.upper(), "frame": frame, "provenance": "provider_adjusted_close; explicit source coverage", "execution_allowed": False}
        return {"status": "unavailable", "reason_code": "raw_price_evidence_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    if basis != "raw" and not action_coverage:
        return {"status": "unavailable", "reason_code": "corporate_action_coverage_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    derived = apply_total_return_adjustments(scoped.rename(columns={close_column: "close"}), actions)
    if not derived.available:
        return {"status": derived.status, "reason_code": "corporate_action_discrepancy", "frame": derived.frame, "execution_allowed": False}
    frame = derived.frame.copy()
    target_currency = (output_currency or local_currency).upper()
    local = local_currency.upper()
    if target_currency != local:
        rates: list[float] = []
        for value in frame["date"]:
            rate = derive_fx_cross(fx_observations, local, target_currency, value, decision_time=cutoff)
            if not rate.available or rate.rate is None:
                return {"status": "unavailable", "reason_code": "required_fx_missing_stale_or_conflicted", "frame": pd.DataFrame(), "execution_allowed": False}
            rates.append(float(rate.rate))
        frame["fx_rate"] = rates
        frame["fx_return"] = frame["fx_rate"].pct_change()
        frame["output_total_return"] = (1.0 + frame["local_total_return"].fillna(0.0)) * (1.0 + frame["fx_return"].fillna(0.0)) - 1.0
        frame["output_total_return_index"] = 100.0 * (1.0 + frame["output_total_return"]).cumprod()
    if basis == "raw":
        frame["series_value"] = frame["raw_close"] * (frame["fx_rate"] if "fx_rate" in frame else 1.0)
    elif basis == "adjusted":
        frame["series_value"] = frame["adjusted_close"] * (frame["fx_rate"] if "fx_rate" in frame else 1.0)
    else:
        frame["series_value"] = frame["output_total_return_index"] if "output_total_return_index" in frame else frame["total_return_index"]
    return {
        "status": "available",
        "basis": basis,
        "currency": target_currency,
        "frame": frame,
        "provenance": "explicit corporate actions and dated point-in-time FX",
        "total_return_convention": derived.convention,
        "execution_allowed": False,
    }


def load_etf_economics_projection(
    snapshot: object,
    instrument_id: str,
    *,
    as_of: object = None,
    horizon_days: int = 252,
) -> dict[str, object]:
    """Load the economics panel through the application-facing read model."""

    from types import SimpleNamespace

    from etf_cockpit.app.selectors.instrument_detail import build_etf_economics_panel

    fund_evidence = getattr(snapshot, "etf_fund_total_return", None)
    benchmark_evidence = getattr(snapshot, "etf_benchmark_total_return", None)
    if isinstance(fund_evidence, dict) or isinstance(benchmark_evidence, dict):
        import pandas as pd

        records = getattr(snapshot, "etf_economics_records", ())
        decision_time = as_of if as_of is not None else getattr(
            getattr(snapshot, "data_report", None), "as_of_date", None
        )
        cutoff = None
        if decision_time is not None:
            cutoff = pd.Timestamp(decision_time)
            cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
            if len(str(decision_time).strip()) <= 10:
                cutoff += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        eligible_funds = [
            item
            for item in records
            if getattr(item, "scope", None) == "fund"
            and getattr(item, "instrument_id", None) == instrument_id
            and (
                cutoff is None
                or (pd.Timestamp(item.as_of) <= cutoff and pd.Timestamp(item.known_at) <= cutoff)
            )
        ]
        latest_fund = max(
            eligible_funds,
            key=lambda item: (item.as_of, item.known_at or ""),
            default=None,
        )
        if isinstance(fund_evidence, dict):
            fund_evidence = fund_evidence.get(instrument_id)
        if isinstance(benchmark_evidence, dict):
            benchmark_id = latest_fund.benchmark_id if latest_fund is not None else None
            benchmark_evidence = benchmark_evidence.get(benchmark_id)
        snapshot = SimpleNamespace(
            etf_economics_records=records,
            etf_fund_total_return=fund_evidence,
            etf_benchmark_total_return=benchmark_evidence,
            etf_closure_policy=getattr(snapshot, "etf_closure_policy", None),
            data_report=getattr(snapshot, "data_report", None),
        )

    return build_etf_economics_panel(
        snapshot, instrument_id, as_of=as_of, horizon_days=horizon_days
    )


def load_market_series_projection(
    prices: object,
    instrument_id: str,
    *,
    basis: str,
    local_currency: str,
    output_currency: str | None = None,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Build a controlled unavailable result for malformed or corrupt evidence."""

    import pandas as pd

    try:
        return _load_market_series_projection(
            prices,
            instrument_id,
            basis=basis,
            local_currency=local_currency,
            output_currency=output_currency,
            storage_root=storage_root,
            decision_time=decision_time,
        )
    except (ArithmeticError, OSError, TypeError, ValueError):
        return {
            "status": "unavailable",
            "reason_code": "market_adjustment_evidence_invalid",
            "frame": pd.DataFrame(),
            "execution_allowed": False,
        }


def load_bound_factor_risk_panel(snapshot: object, instrument_id: str) -> dict[str, object]:
    """Project canonical factor risk only from replayed snapshot input bindings."""
    import math as numeric_math
    from numbers import Real
    import pandas as pandas
    from etf_cockpit.application.benchmark_reference import adjusted_price_snapshot_binding, clip_to_decision_window
    from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry, ReferencePortfolioDefinition
    from etf_cockpit.portfolio.sandbox import holdings_checksum

    def source_knowledge(frame, effective_times, decision, *, price_rows=False):
        # Replay the no-trade builder's explicit per-row knowledge contract.
        authority_columns = tuple(column for column in ("known_at", "imported_at", "available_at") if column in frame)
        if not authority_columns:
            raise ValueError("explicit source knowledge is missing")
        columns = authority_columns + tuple(column for column in ("retrieved_at", "published_at") if price_rows and column in frame)
        times = []
        for (_, row), effective_time in zip(frame.iterrows(), effective_times):
            declared = {}
            for column in columns:
                value = row[column]
                if value is None or pandas.isna(value):
                    continue
                parsed = pandas.to_datetime(value, errors="coerce")
                if pandas.isna(parsed) or getattr(parsed, "tzinfo", None) is None:
                    raise ValueError("source knowledge must contain valid aware timestamps")
                declared[column] = pandas.Timestamp(parsed).tz_convert("UTC")
            if not any(column in declared for column in authority_columns):
                raise ValueError("each source row requires explicit knowledge")
            row_known = max(declared.values())
            if row_known < effective_time or row_known > decision:
                raise ValueError("source knowledge contradicts the effective time or decision cutoff")
            times.append(row_known)
        return max(times), {
            "status": "validated", "row_count": len(times), "fields": list(columns),
            "latest_known_at": max(times).isoformat(), "earliest_known_at": min(times).isoformat(),
        }

    empty = {
        "status": "unavailable", "instrument_id": instrument_id,
        "factor_exposures": [], "specific_risk": [], "instrument_contributions": [],
        "global_coverage": {}, "global_diagnostics": {}, "global_report_status": "unavailable",
        "coverage": {"status": "unavailable", "instrument_id": instrument_id},
        "coverage_scope": "selected_instrument", "historical_binding_status": "unavailable",
        "selected_instrument_status": "unverified", "warnings": [],
        "lookthrough_status": "unsupported", "retrospective_universe_replay": "unsupported",
        "execution_allowed": False,
    }
    try:
        prices = getattr(snapshot, "prices", None)
        features = getattr(snapshot, "features", None)
        holdings = getattr(snapshot, "holdings", None)
        if any(not isinstance(frame, pandas.DataFrame) or frame.empty or not frame.columns.is_unique for frame in (prices, features, holdings)):
            raise ValueError("complete unambiguous snapshot frames are required")
        binding = features.attrs.get("price_binding")
        if not isinstance(binding, Mapping) or not isinstance(binding.get("calculation_window"), Mapping):
            raise ValueError("full feature price binding is unavailable")
        window = binding["calculation_window"]
        replayed = adjusted_price_snapshot_binding(prices, calculation_window=window)
        if replayed is None or dict(binding) != replayed:
            raise ValueError("feature price binding does not match replayed adjusted prices")
        decision = pandas.Timestamp(window["decision_time"])
        as_of = pandas.Timestamp(getattr(getattr(snapshot, "data_report", None), "as_of_date", None))
        if pandas.isna(as_of) or decision.tzinfo is None or as_of.date().isoformat() != window["end_date"]:
            raise ValueError("snapshot cutoff does not match the bound calculation window")
        scoped_prices = clip_to_decision_window(prices, **window)
        scoped_features = clip_to_decision_window(features, **window)
        price_effective = pandas.to_datetime(scoped_prices["date"], errors="coerce", utc=True, format="mixed")
        _, price_knowledge = source_knowledge(scoped_prices, price_effective, decision, price_rows=True)
        if len(scoped_features) != len(features) or scoped_features.empty:
            raise ValueError("feature rows fall outside the bound decision window")
        for frame in (scoped_prices, scoped_features, holdings):
            if "etf_id" not in frame or any(not isinstance(value, str) or not value or value != value.strip() for value in frame["etf_id"]):
                raise ValueError("exact canonical source identifiers are required")
        if scoped_features.duplicated(["etf_id", "date"]).any():
            raise ValueError("feature identity and dates must be unambiguous")
        # A price checksum binds inputs, not supplied descriptor values. Replay
        # the canonical calculation before accepting those descriptors as bound.
        from etf_cockpit.features.feature_pipeline import compute_features
        replay_prices = scoped_prices.copy()
        if "volume" not in replay_prices:
            replay_prices["volume"] = float("nan")  # FeatureService's explicit missing-volume convention.
        replay_features = compute_features(replay_prices)
        descriptor_columns = ["etf_id", "date", "momentum_120d", "momentum_60d", "return_60d_log", "vol_60d_ann", "vol_120d_ann", "ewma_vol_ann"]
        if not set(descriptor_columns).issubset(scoped_features):
            raise ValueError("canonical factor descriptors are incomplete")
        supplied = scoped_features[descriptor_columns].copy()
        canonical = replay_features[descriptor_columns].copy()
        for frame in (supplied, canonical):
            frame["date"] = pandas.to_datetime(frame["date"], errors="coerce", utc=True, format="mixed")
        try:
            pandas.testing.assert_frame_equal(
                supplied.sort_values(["etf_id", "date"]).reset_index(drop=True),
                canonical.sort_values(["etf_id", "date"]).reset_index(drop=True),
                check_dtype=False, check_exact=True,
            )
        except AssertionError as exc:
            raise ValueError("supplied factor descriptors differ from canonical price replay") from exc
        required = ("current_weight", "market_value_eur", "as_of_date")
        if not set(required).issubset(holdings) or holdings["etf_id"].duplicated().any():
            raise ValueError("holdings allocation fields are incomplete")
        for column in required[:2]:
            if any(isinstance(value, bool) or not isinstance(value, Real) or not numeric_math.isfinite(value) or value < 0 for value in holdings[column]):
                raise ValueError("holdings allocation values are invalid")
        holding_dates = pandas.to_datetime(holdings["as_of_date"], errors="coerce", utc=True, format="mixed")
        if holding_dates.isna().any() or set(holding_dates.dt.date) != {as_of.date()}:
            raise ValueError("holdings are not effective at the snapshot cutoff")
        holdings_known, holdings_knowledge = source_knowledge(
            holdings, [pandas.Timestamp(as_of.date(), tz="UTC")] * len(holdings), decision
        )
        registry = getattr(snapshot, "benchmark_reference_registry", None)
        if not isinstance(registry, CanonicalBenchmarkRegistry):
            raise ValueError("canonical no-trade reference is unavailable")
        references = [item for item in registry.reference_portfolios if item.portfolio_id == "reference:no_trade"]
        checksum = holdings_checksum(holdings)
        if len(references) != 1 or not isinstance(references[0], ReferencePortfolioDefinition):
            raise ValueError("exactly one canonical no-trade reference is required")
        reference = references[0]
        known = pandas.Timestamp(reference.known_at)
        effective = pandas.Timestamp(reference.effective_at)
        if known != holdings_known:
            raise ValueError("no-trade reference knowledge differs from the source row maximum")
        if (reference.method != "no_trade" or tuple(reference.source_hashes) != (checksum,)
                or known.tzinfo is None or known > decision or effective != pandas.Timestamp(as_of.date(), tz="UTC")):
            raise ValueError("no-trade reference holdings provenance does not match the cutoff")
        held_ids = set(holdings["etf_id"])
        weights = dict(reference.current_weights or {})
        if set(weights) != held_ids | {f"cash:{reference.currency}"}:
            raise ValueError("no-trade reference does not prove the complete held universe")
        for row in holdings.itertuples():
            if weights[row.etf_id] != row.current_weight:
                raise ValueError("no-trade weights differ from bound holdings")
        universe = sorted(set(scoped_prices["etf_id"]) & set(scoped_features["etf_id"]))
        if not held_ids.issubset(universe):
            raise ValueError("held instruments lack bound price or feature evidence")
        # An absent position in the complete bound holdings set has zero
        # portfolio weight; its unknown market-value descriptor remains missing.
        allocation = pandas.DataFrame({"etf_id": universe}).merge(
            holdings[["etf_id", "current_weight", "market_value_eur"]], on="etf_id", how="left", validate="one_to_one"
        )
        allocation.loc[~allocation["etf_id"].isin(held_ids), "current_weight"] = 0.0

        report = build_factor_risk_report(
            scoped_prices.loc[scoped_prices["etf_id"].isin(universe)], allocation,
            scoped_features.loc[scoped_features["etf_id"].isin(universe), descriptor_columns], holdings=None,
        )
    except (ArithmeticError, AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        return empty | {"message": f"Factor-risk binding unavailable: {exc}."}
    selected = {}
    for key in ("factor_exposures", "specific_risk", "instrument_contributions"):
        frame = report.get(key)
        selected[key] = frame.loc[frame["instrument_id"].eq(instrument_id)].copy() if isinstance(frame, pandas.DataFrame) and "instrument_id" in frame else pandas.DataFrame()
    risk = selected["specific_risk"]
    covered = (report.get("status") in {"available", "partial"} and not risk.empty
               and "specific_vol_ann" in risk and pandas.to_numeric(risk["specific_vol_ann"], errors="coerce").map(numeric_math.isfinite).all())
    return empty | {
        "status": report.get("status") if covered else "unavailable",
        "historical_binding_status": "verified_snapshot",
        "selected_instrument_status": "available" if covered else "absent" if instrument_id not in universe else "insufficient_model_coverage",
        "coverage": {"status": "available" if covered else "unavailable", "instrument_id": instrument_id},
        **{key: frame.astype(object).where(pandas.notna(frame), None).to_dict("records") if covered else [] for key, frame in selected.items()},
        "global_report_status": report.get("status", "unavailable"),
        "global_coverage": report.get("coverage", {}), "global_diagnostics": report.get("diagnostics", {}),
        "global_coverage_scope": "estimation_universe", "global_diagnostics_scope": "estimation_universe",
        "warnings": report.get("warnings", []), "model_version": report.get("model_version", "unavailable"),
        "decision_time": window["decision_time"], "price_snapshot_checksum": replayed["price_snapshot_checksum"],
        "source_knowledge": {
            "prices": price_knowledge | {"checksum_scope": "price checksum binds values only; row knowledge validated separately"},
            "holdings": holdings_knowledge | {"holdings_checksum": checksum, "reference_content_hash": reference.content_hash},
        },
        "holdings_checksum": checksum, "universe_revision": getattr(snapshot, "universe_revision", ""),
        "message": "Factor risk from verified snapshot price/features and no-trade holdings bindings. Historical look-through and arbitrary retrospective universe replay are unsupported.",
    }


# Explicit presentation schema: future/private artifact fields are never projected.
_METRIC_HISTORY_DISPLAY_COLUMNS = (
    "run_id", "instrument_id", "component_group", "component_name", "source_id",
    "raw_metric_value", "normalised_score_10", "score_available", "na_reason",
    "source_dataset", "as_of_date", "freshness_status", "authority_label",
    "formula_version", "formula_checksum", "source_vintage_hash", "execution_allowed",
)


def load_score_metric_history_projection(instrument_id: str, *, frame=None) -> dict:
    """Read stored component snapshots without deriving scores or PIT authority."""
    import math
    from numbers import Real

    import pandas as pd

    from etf_cockpit.data.trust_artifacts import SCORE_METRIC_HISTORY_PATH

    def unavailable(reason: str) -> dict:
        return {"status": "unavailable", "reason_code": reason, "rows": [],
                "message": "Score-component metric history unavailable: " + reason + ".",
                "execution_allowed": False}

    if frame is None:
        try:
            frame = pd.read_parquet(SCORE_METRIC_HISTORY_PATH)
        except FileNotFoundError:
            return unavailable("missing_local_artifact")
        except Exception:
            return unavailable("unreadable_local_artifact")
    if (not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique
            or not set(_METRIC_HISTORY_DISPLAY_COLUMNS).issubset(frame.columns)):
        return unavailable("malformed_metric_history")
    rows = frame.loc[frame["instrument_id"].eq(instrument_id), list(_METRIC_HISTORY_DISPLAY_COLUMNS)]
    if rows.empty:
        return unavailable("no_instrument_metric_history")
    records = []
    for record in rows.to_dict("records"):
        for field, value in record.items():
            if not pd.api.types.is_scalar(value):
                return unavailable("malformed_metric_history")
            if pd.isna(value):
                record[field] = None
        for field in ("run_id", "instrument_id", "component_name"):
            if not isinstance(record[field], str) or not record[field].strip():
                return unavailable("malformed_metric_history")
        for field in ("raw_metric_value", "normalised_score_10"):
            value = record[field]
            if value is not None and (isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)):
                return unavailable("malformed_metric_history")
        record["execution_allowed"] = False
        records.append(record)
    return {"status": "available", "instrument_id": instrument_id, "rows": records,
            "message": "Persisted score-component snapshots across local runs. As-of dates and stored provenance do not establish knowledge-time availability or replay guarantees.",
            "execution_allowed": False}


def load_portfolio_goals_projection(
    snapshot: object,
    analysis: PortfolioAnalysis | None = None,
    *,
    action: Mapping[str, object] | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    """Load revisioned portfolio goals and snapshot-bound what-if evidence.

    The optional action is one of ``save_policy``, ``simulate``,
    ``acknowledge`` or ``snooze``. State uses the existing transactional user
    store; candidate analysis and alert evidence remain advisory and never
    write portfolio ledger entries.
    """

    binding = getattr(analysis, "snapshot_binding", None) if analysis is not None else None
    account_id = str(getattr(binding, "account_id", getattr(snapshot, "account_id", "default")) or "default")
    portfolio_id = str(getattr(binding, "portfolio_id", getattr(snapshot, "portfolio_id", "default")) or "default")
    storage_id = hashlib.sha256(f"{account_id}\0{portfolio_id}".encode("utf-8")).hexdigest()
    entity_type = PORTFOLIO_GOALS_SCHEMA
    command = dict(action) if isinstance(action, Mapping) else None
    command_type = str(command.get("type", "")) if command is not None else ""
    state: dict[str, object] = {
        "schema_version": PORTFOLIO_GOALS_SCHEMA,
        "policy_versions": [],
        "scenarios": [],
        "acknowledgement_history": [],
    }
    stored_revision = 0

    try:
        layout = storage_layout(root)
        database_exists = layout.transactional_path.is_file()
        if database_exists or command is not None:
            with TransactionalStore(root, read_only=command is None) as store:
                record = store.get(entity_type, storage_id)
                if record is not None:
                    if record.payload.get("schema_version") != PORTFOLIO_GOALS_SCHEMA:
                        return _portfolio_goals_unavailable("stored_portfolio_goals_schema_invalid")
                    state = dict(record.payload)
                    stored_revision = record.revision
                if command is not None:
                    if not isinstance(state.get("policy_versions"), list) or not isinstance(state.get("scenarios"), list) or not isinstance(state.get("acknowledgement_history"), list):
                        return _portfolio_goals_unavailable("stored_portfolio_goals_history_invalid")
                    versions = list(state["policy_versions"])
                    active_record = versions[-1] if versions else None
                    latest_policy = policy_from_record(active_record)
                    if versions and latest_policy is None:
                        return _portfolio_goals_unavailable("stored_portfolio_policy_invalid")
                    active_policy = _portfolio_goals_policy_as_of(versions, analysis)
                    policy_id = f"portfolio-goals:{storage_id}"
                    if active_policy is None:
                        active_policy = PortfolioPolicy(policy_id=policy_id, version=0)
                    evidence = _portfolio_goals_evidence(snapshot, analysis, active_policy, command_type)
                    current_hash = source_snapshot_hash(analysis) if analysis is not None else None
                    alerts, unavailable_alerts = build_alerts(
                        analysis,
                        active_policy,
                        snapshot=snapshot,
                        evidence=evidence,
                        snapshot_hash=current_hash,
                    ) if analysis is not None else ((), ({"kind": "all", "status": "unavailable", "reason": "analysis_unavailable"},))
                    acknowledgement_history = list(state["acknowledgement_history"])
                    scenarios = list(state["scenarios"])
                    saved_at = _portfolio_goals_action_time(command.get("at"))

                    if command_type == "save_policy":
                        raw_policy = command.get("policy")
                        next_policy = validate_portfolio_policy(
                            raw_policy,
                            policy_id=f"portfolio-goals:{storage_id}",
                            version=len(versions) + 1,
                        )
                        _validate_portfolio_goal_identifiers(next_policy, snapshot)
                        versions.append(policy_record(next_policy, saved_at=saved_at))
                    elif command_type == "simulate":
                        if analysis is None:
                            return _portfolio_goals_unavailable("what_if_analysis_unavailable")
                        scenario_policy = latest_policy or PortfolioPolicy(policy_id=policy_id, version=0)
                        scenario_evidence = _portfolio_goals_evidence(
                            snapshot, analysis, scenario_policy, command_type
                        )
                        forecast = None
                        try:
                            forecast = load_portfolio_forecast_aggregation(
                                snapshot,
                                analysis,
                                horizon_days=PRIMARY_MODEL_HORIZON_DAYS,
                            )
                        except (ArithmeticError, KeyError, TypeError, ValueError, AttributeError):
                            forecast = {"status": "unavailable", "reason": "canonical_portfolio_forecast_unavailable"}
                        scenario = build_what_if_scenario(
                            analysis,
                            snapshot,
                            scenario_policy,
                            evidence=scenario_evidence,
                            forecast=forecast,
                        )
                        scenario_value = what_if_record(scenario)
                        scenario_value["policy_binding"] = _portfolio_goals_policy_binding(scenario_policy)
                        scenario_value["saved_at"] = saved_at
                        scenarios.append(scenario_value)
                    elif command_type in {"acknowledge", "snooze"}:
                        if analysis is None or current_hash is None:
                            return _portfolio_goals_unavailable("alert_source_snapshot_unavailable")
                        requested_ids = command.get("alert_ids")
                        if not isinstance(requested_ids, Sequence) or isinstance(requested_ids, (str, bytes)):
                            return {"status": "invalid", "reason": "alert_ids_must_be_an_array", "execution_allowed": False}
                        current_alerts = {item.alert_id: item for item in alerts}
                        selected_ids = tuple(sorted({str(item).strip() for item in requested_ids if str(item).strip()}))
                        if not selected_ids or any(identifier not in current_alerts for identifier in selected_ids):
                            return {"status": "invalid", "reason": "alert_condition_not_active_for_selected_snapshot", "execution_allowed": False}
                        snoozed_until = None
                        if command_type == "snooze":
                            snoozed_until = _portfolio_goals_action_time(command.get("until"))
                            if datetime.fromisoformat(snoozed_until) <= datetime.fromisoformat(saved_at):
                                return {"status": "invalid", "reason": "snooze_until_must_follow_action_time", "execution_allowed": False}
                        for identifier in selected_ids:
                            acknowledgement_history.append({
                                "alert_id": identifier,
                                "source_snapshot_hash": current_hash,
                                "action": command_type,
                                "acted_at": saved_at,
                                "snoozed_until": snoozed_until,
                            })
                    else:
                        return {"status": "invalid", "reason": "unsupported_portfolio_goals_action", "execution_allowed": False}

                    state = {
                        "schema_version": PORTFOLIO_GOALS_SCHEMA,
                        "policy_versions": versions,
                        "scenarios": scenarios,
                        "acknowledgement_history": acknowledgement_history,
                    }
                    store.put(entity_type, storage_id, state, expected_revision=stored_revision)
    except ValueError as exc:
        return {"status": "invalid", "reason": str(exc), "execution_allowed": False}
    except StorageRevisionConflict as exc:
        return {"status": "conflict", "reason": str(exc), "execution_allowed": False}
    except (OSError, sqlite3.Error, StorageSchemaError) as exc:
        return _portfolio_goals_unavailable(f"local_portfolio_goals_store_unavailable:{type(exc).__name__}")

    versions = state.get("policy_versions", [])
    versions = versions if isinstance(versions, list) else []
    active_record = versions[-1] if versions else None
    latest_policy = policy_from_record(active_record)
    effective_policy = _portfolio_goals_policy_as_of(versions, analysis)
    policy_id = f"portfolio-goals:{storage_id}"
    editor_value = policy_editor_value(latest_policy)
    current_hash = source_snapshot_hash(analysis) if analysis is not None else None
    alert_policy = effective_policy or PortfolioPolicy(policy_id=policy_id, version=0)
    effective_policy_binding = _portfolio_goals_policy_binding(
        latest_policy or PortfolioPolicy(policy_id=policy_id, version=0)
    )
    evidence = _portfolio_goals_evidence(snapshot, analysis, alert_policy, command_type) if analysis is not None else {}
    if analysis is not None:
        alerts, unavailable_alerts = build_alerts(
            analysis,
            alert_policy,
            snapshot=snapshot,
            evidence=evidence,
            snapshot_hash=current_hash,
        )
    else:
        alerts, unavailable_alerts = (), ({"kind": "all", "status": "unavailable", "reason": "analysis_unavailable"},)
    actions = state.get("acknowledgement_history", [])
    actions = actions if isinstance(actions, list) else []
    decorated_alerts: list[dict[str, object]] = []
    for alert in alerts:
        history = [
            row for row in actions
            if isinstance(row, Mapping)
            and row.get("alert_id") == alert.alert_id
            and row.get("source_snapshot_hash") == current_hash
        ]
        snoozes = [row for row in history if row.get("action") == "snooze"]
        decorated_alerts.append({
            **alert_record(alert),
            "acknowledged": any(row.get("action") == "acknowledge" for row in history),
            "snoozed_until": snoozes[-1].get("snoozed_until") if snoozes else None,
        })
    scenario_history = state.get("scenarios", [])
    scenario_history = scenario_history if isinstance(scenario_history, list) else []
    latest_scenario = scenario_history[-1] if scenario_history else {
        "status": "unavailable", "reason": "no_what_if_scenario_has_been_run", "execution_allowed": False,
    }
    return {
        "status": "available" if latest_policy is not None or not versions else "unavailable",
        "reason": None if latest_policy is not None or not versions else "stored_portfolio_policy_invalid",
        "source_snapshot_hash": current_hash,
        "policy": None if latest_policy is None else policy_record(latest_policy),
        "policy_as_of": (
            {"status": "available", "version": effective_policy.version, "policy_id": effective_policy.policy_id}
            if effective_policy is not None
            else {"status": "unavailable", "reason": "no_policy_version_available_at_source_decision_time" if versions else "no_saved_policy"}
        ),
        "effective_policy_binding": effective_policy_binding,
        "policy_editor": editor_value,
        "policy_history": versions,
        "alerts": decorated_alerts,
        "unavailable_alerts": list(unavailable_alerts),
        "acknowledgement_history": actions,
        "scenario": latest_scenario,
        "scenarios": scenario_history,
        "audit_export": {
            "policy_versions": versions,
            "scenario_results": scenario_history,
            "alerts": decorated_alerts,
            "acknowledgements": actions,
        },
        "execution_allowed": False,
    }


def _portfolio_goals_evidence(
    snapshot: object,
    analysis: PortfolioAnalysis | None,
    policy: PortfolioPolicy,
    action_type: str,
) -> dict[str, object]:
    if analysis is None:
        return {}
    evidence: dict[str, object] = {}
    service_evidence = getattr(analysis, "service_evidence", {})
    service_evidence = service_evidence if isinstance(service_evidence, Mapping) else {}
    risk = service_evidence.get("risk")
    risk = risk if isinstance(risk, Mapping) else {}
    for metric in ("max_drawdown", "income_yield", "liquidity_eur", "forecast_deterioration"):
        value = risk.get(metric) if metric == "max_drawdown" else service_evidence.get(metric)
        if metric == "max_drawdown" and not isinstance(value, Mapping):
            portfolio_risk = risk.get("portfolio")
            if isinstance(portfolio_risk, Mapping) and metric in portfolio_risk:
                value = {
                    "status": risk.get("status", "unavailable"),
                    "value": portfolio_risk.get(metric),
                    "reason": risk.get("reason"),
                }
        evidence[metric] = value if isinstance(value, Mapping) else {
            "status": "unavailable",
            "value": None,
            "reason": f"canonical_{metric}_projection_unavailable",
        }
    needs_calendar = action_type == "simulate" or any((
        policy.event_within_days is not None,
        policy.maturity_within_days is not None,
        policy.maximum_maturity_days is not None,
    ))
    if needs_calendar:
        try:
            evidence["calendar"] = load_portfolio_calendar_projection(snapshot, analysis)
        except (OSError, KeyError, TypeError, ValueError, AttributeError):
            evidence["calendar"] = {"status": "unavailable", "reason": "point_in_time_calendar_unavailable", "events": None}
    return evidence


def _portfolio_goals_action_time(value: object) -> str:
    raw = datetime.now(timezone.utc) if value is None else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if raw.tzinfo is None:
        raise ValueError("portfolio goal action times must include a timezone")
    return raw.astimezone(timezone.utc).isoformat()


def _portfolio_goals_policy_as_of(versions: Sequence[object], analysis: object | None) -> PortfolioPolicy | None:
    binding = getattr(analysis, "snapshot_binding", None) if analysis is not None else None
    raw_cutoff = str(getattr(binding, "as_of", "") or "").strip()
    if not raw_cutoff:
        return None
    try:
        if len(raw_cutoff) == 10:
            cutoff = datetime.combine(date.fromisoformat(raw_cutoff), datetime.max.time(), tzinfo=timezone.utc)
        else:
            cutoff = datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                return None
            cutoff = cutoff.astimezone(timezone.utc)
    except ValueError:
        return None
    for record in reversed(versions):
        if not isinstance(record, Mapping):
            continue
        try:
            saved_at = datetime.fromisoformat(str(record.get("saved_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if saved_at.tzinfo is None or saved_at.astimezone(timezone.utc) > cutoff:
            continue
        policy = policy_from_record(record)
        if policy is not None:
            return policy
    return None


def _portfolio_goals_policy_binding(policy: PortfolioPolicy) -> dict[str, object]:
    record = policy_record(policy)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return {
        "policy_id": policy.policy_id,
        "version": policy.version,
        "policy_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }


def _validate_portfolio_goal_identifiers(policy: PortfolioPolicy, snapshot: object) -> None:
    config = getattr(snapshot, "config", None)
    universe = getattr(config, "universe", None)
    by_id = getattr(universe, "by_id", None)
    if not callable(by_id):
        raise ValueError("portfolio policy instrument universe is unavailable")
    valid_ids = {str(value) for value in by_id()}
    holdings = getattr(snapshot, "holdings", None)
    if isinstance(holdings, pd.DataFrame):
        column = "etf_id" if "etf_id" in holdings.columns else "instrument_id" if "instrument_id" in holdings.columns else None
        if column is not None:
            valid_ids.update(str(value).strip() for value in holdings[column].tolist() if str(value).strip())
    policy_ids = {key for key, _ in policy.target_weights} | {key for key, _, _ in policy.target_bands}
    unknown = sorted(policy_ids - valid_ids)
    if unknown:
        raise ValueError(f"unknown portfolio policy instrument ids: {', '.join(unknown)}")


def _portfolio_goals_unavailable(reason: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "reason": reason,
        "policy": {"status": "unavailable", "value": None, "reason": reason},
        "policy_history": [],
        "alerts": [],
        "unavailable_alerts": [{"kind": "all", "status": "unavailable", "reason": reason}],
        "acknowledgement_history": [],
        "scenario": {"status": "unavailable", "reason": reason, "execution_allowed": False},
        "execution_allowed": False,
    }
