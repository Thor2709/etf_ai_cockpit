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

from etf_cockpit.analysis.parity_report import (
    analysis_parity_report_path,
)
from etf_cockpit.core.paths import LOG_DIR, STATEMENT_FACTS_PATH
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.etf_structure import project_etf_structure
from etf_cockpit.data.event_calendar import load_calendar_events, normalise_event_decision_time
from etf_cockpit.data.capital_allocation import capital_allocation_analysis
from etf_cockpit.data.market_adjustments import CorporateActionCoverage
from etf_cockpit.data.duckdb_store import PRICE_PARQUET, load_prices
from etf_cockpit.data.fx_data import FX_CLEAN_PATH, load_fx_rates
from etf_cockpit.data.local_storage import StorageRevisionConflict, StorageSchemaError, TransactionalStore, storage_layout
from etf_cockpit.data.macro_warehouse import MacroWarehouse, load_risk_free_proxy_mappings
from etf_cockpit.data.provenance import price_staleness_status
from etf_cockpit.data.stock_research import valuation_analysis
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.parsed_disclosures import read_etf_report_records
from etf_cockpit.features.cash_comparison import (
    cash_comparison_from_projection,  # noqa: F401
    cash_comparison_to_projection,  # noqa: F401
)

from etf_cockpit.analysis.etf_tax_context import (
    ETFContextAssumptions,  # noqa: F401
    NetReturnScenario,  # noqa: F401
    build_currency_context,  # noqa: F401
    calculate_core_quality_tax_bias,  # noqa: F401
    calculate_net_return_scenario,  # noqa: F401
    load_tax_hedge_assumptions,  # noqa: F401
)
from etf_cockpit.application.portfolio_valuation import load_portfolio_valuation_history  # noqa: F401
from etf_cockpit.portfolio.performance_series import (
    performance_series_frame,  # noqa: F401
)
from etf_cockpit.portfolio.top_n_selection import (
    SelectionCandidate,
    SelectionPolicyError,
    build_selection_run,
    load_selection_policy,
    persist_selection_run,
)
from etf_cockpit.portfolio.selection_slices import materialise_selection_slices

from etf_cockpit.chatgpt_bridge.audit_packet import extract_and_validate_audit_archive
from etf_cockpit.data.backup_restore import (
    commit_restore,
    create_backup,
    create_encrypted_backup,
    run_disaster_recovery_drill,
    validate_encrypted_restore,
    validate_restore,
)
from etf_cockpit.data.bitemporal import bitemporal_history_summary
from etf_cockpit.data.bulk_cache import (
    ContentAddressedCache,
    bulk_cache_health,
)
from etf_cockpit.data.decision_journal import (
    DecisionJournal,
    JournalEntry,
    JournalIntegrityError,
)
from etf_cockpit.data.forward_evidence_diary import (
    ForwardEvidenceDiary,
    ForwardEvidenceIntegrityError,
    ForwardEvidenceObservation,
    ForwardInputManifest,
)
from etf_cockpit.data.event_calendar import (
    EVENT_CLEAN_PATH,
    events_available_as_of,
)
from etf_cockpit.data.etf_economics import calculate_etf_economics
from etf_cockpit.data.export_tables import export_table
from etf_cockpit.data.fund_documents import import_etf_document
from etf_cockpit.data.fund_holdings import (
    FUND_HOLDINGS_PATH,
    import_etf_holdings_with_document,
    normalise_holdings,
)
from etf_cockpit.data.fundamentals import (
    FUNDAMENTAL_CLEAN_PATH,
    assess_fundamental_row,
    latest_fundamental_rows,
    load_fundamental_evidence,
    sort_fundamental_evidence,
)
from etf_cockpit.data.fx_data import fx_data_inventory
from etf_cockpit.application.market_clock import (
    build_market_clock_diagnostics,
    operational_calendar_record_is_canonical,
)
from etf_cockpit.data.health import (
    DataHealthReport,
    DataHealthRow,
    DataHealthStatus,
    build_data_health,
    export_data_health,
    filter_data_health_rows,
)
from etf_cockpit.data.import_export import (
    ImportPreview,
    ImportService,
    validate_import,
)
from etf_cockpit.data.legal_terms import (
    legal_terms_report,
    legal_terms_rows,
)
from etf_cockpit.data.catalogue import (
    DataCatalogue,
    DataCatalogueError,
)
from etf_cockpit.data.macro_warehouse import MacroWarehouseError
from etf_cockpit.data.anomaly_ledger import AnomalyLedger
from etf_cockpit.data.stock_research import (
    CONSENSUS_IMPORT_PATH,
    GUIDANCE_IMPORT_PATH,
    build_stock_research_report,
    load_optional_research_import,
)
from etf_cockpit.backtest.event_engine import event_engine_status
from etf_cockpit.governance.release_certification import release_certification_report
from etf_cockpit.governance.supply_chain_intake import supply_chain_intake_report
from etf_cockpit.data.fixed_income_terms import (
    fixed_income_terms_exists,
)
from etf_cockpit.analysis.fixed_income_screener import (
    load_fixed_income_screener_config,
)
from etf_cockpit.data.classification import (
    ClassificationOverride,
)
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


from etf_cockpit.data.manual_notes import (
    MANUAL_NEWS_CLEAN_PATH,
    load_manual_news,
    manual_news_markdown,
    save_manual_note_credibility_review,
)
from etf_cockpit.data.news_context import sort_news_items
from etf_cockpit.data.oam_adapters import (
    FILING_COVERAGE_PATH,
    MANUAL_FILING_QUEUE_PATH,
    OAM_DISCOVERY_PATH,
)
from etf_cockpit.data.parsed_disclosures import (
    EtfReportImportRequest,
    EtfReportReviewRequest,
    import_etf_report,
    persist_index_methodology_with_document,
    persist_priips_kid_with_document,
    read_index_methodology_records,
    read_priips_kid_records,
    review_etf_report,
)
from etf_cockpit.data.etf_structure import load_local_structural_evidence
from etf_cockpit.data.privacy import (
    delete_private_data,
    redact_private_fields,
)
from etf_cockpit.data.reference_data import (
    ETF_METADATA_CLEAN_PATH,
    reference_data_inventory,
)
from etf_cockpit.data.run_changes import (
    REQUIRED_CHANGE_DIMENSIONS,
    UPSTREAM_CHANGE_DIMENSIONS,
    compare_runs,
    select_comparison_runs,
)
from etf_cockpit.application.run_change_context import upstream_run_context  # noqa: F401
from etf_cockpit.data.score_history import score_history_frame
from etf_cockpit.data.source_policy import source_policy_rows
from etf_cockpit.data.statement_normalisation import load_statement_evidence
from etf_cockpit.data.trust_artifacts import (
    BENCHMARK_ATTRIBUTION_PATH,
    CORRELATION_CLUSTERS_PATH,
    ETF_DISCLOSURES_PATH,
    ETF_REPORT_CONFLICTS_PATH,
    ETF_REPORT_RECORDS_PATH,
    EVIDENCE_LEDGER_PATH,
    FEATURE_DRIVERS_PATH,
    FILINGS_STATEMENTS_PATH,
    INDEX_METHODOLOGY_RECORDS_PATH,
    NEWS_CONTEXT_PATH,
    NEWS_TIMESTAMP_VALIDATION_PATH,
    PRIIPS_KID_RECORDS_PATH,
    PROVIDER_PROBE_PATH,
    ProviderRegistry,
    SCORE_COMPONENTS_PATH,
    SCORE_HISTORY_PATH,
    SCORE_METRIC_HISTORY_PATH,
    SOURCE_CONFLICTS_PATH,
    build_document_inventory,
    load_score_history_summary,
)
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH
from etf_cockpit.data.universe_store import (
    InvestabilityPolicyProfile,
    add_record,
    disable_record,
    edit_record,
    import_legacy_universe,
    remove_record,
    save_universe,
    universe_payload_revision,
    validate_universe,
)
from etf_cockpit.data.universe_import import (
    UniverseRecord,
    build_universe_manifest,
    create_import_resume_state,
    dry_run_universe_import,
    is_valid_isin,
    resume_universe_import,
    save_universe_manifest,
)
from etf_cockpit.application.contracts import (
    ApiStatus,
    CancelWorkflowCommand,
    PageRequest,
    SubmitWorkflowCommand,
)
from etf_cockpit.application.screening import (
    ScreenFilter,
    ScreenSort,
    run_screen,
)
from etf_cockpit.application.screening_data import query_for_snapshot
from etf_cockpit.data.screen_store import (
    export_screen_csv,
    load_screen,
    save_screen,
)
from etf_cockpit.core.versioning import (
    build_version_registry,
    compatibility_summary,
)
from etf_cockpit.core.resource_profiles import (
    ResourcePolicy,
    estimate_workflow_resources,
    generated_cache_cleanup,
)
from etf_cockpit.core.resource_profiles import resource_profile_report
from etf_cockpit.models.forecast_scores import (
    CANONICAL_DISTRIBUTION_HORIZONS_DAYS,  # noqa: F401
    PRIMARY_MODEL_HORIZON_DAYS,  # noqa: F401
    forecast_return_distributions as load_forecast_return_distributions,
)  # noqa: F401
from etf_cockpit.models.model_zoo import model_zoo_frame
from etf_cockpit.models.coverage_audit import (
    build_coverage_audit,
    coverage_summary_lines,
    write_coverage_audit,
)
from etf_cockpit.models.local_weights import format_model_inventory_line
from etf_cockpit.portfolio.allocation import (
    allocation_frame,
    exposure_summary,
)
from etf_cockpit.portfolio.costs import cost_capacity_status
from etf_cockpit.portfolio.factor_risk import build_factor_risk_report
from etf_cockpit.portfolio.attribution import build_performance_attribution
from etf_cockpit.portfolio.rebalancing import (
    RebalanceConstraints,
    RebalanceReport,
    build_rebalance_report,
)
from etf_cockpit.portfolio.robust_risk import build_robust_risk_report
from etf_cockpit.portfolio.risk_analytics import (
    drawdown_contribution,
    exposure_limit_report,
    return_correlation_matrix,
    underlying_holdings_exposure,
)
from etf_cockpit.application.portfolio_sandbox import (
    PortfolioCandidate,
    PortfolioSandboxPersistenceError,
    analyse_portfolio_candidate,
    build_portfolio_candidate,
    candidate_id,
    draft_portfolio_candidate,
    load_portfolio_candidate,
    portfolio_snapshot_binding,
    rebalance_inapplicable_instruments,
    save_portfolio_candidate,
)
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
from etf_cockpit.application.overlap import (
    build_direct_overlap_view,
    direct_overlap_payload,
)
from etf_cockpit.signals.simple_scores import (
    NEWS_CLEAN_PATH,
    SCORE_LEGEND,
    SimpleInstrumentScore,
    SimpleScoreComponent,
    build_simple_instrument_scores,
    configured_forecast_request_identity,
    decision_from_score,
    filter_forecasts_for_universe,
    forecast_score_details,
    group_simple_scores,
    load_candidate_price_binding,
    load_latest_forecasts,
    load_news_items,
    load_reference_dataset,
    load_simple_scoreboard,
    load_universe,
    raw_to_score_10,
)
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
from etf_cockpit.application.paper_views import (
    load_canary_status,
    load_paper_incidents,
    load_paper_tca_view,
    load_paper_timeline,
    load_paper_trade_rows,
)
from etf_cockpit.application.identity_views import (
    load_classification_projection,
    load_identity_projection,
    load_peer_cohort_projection,
    save_classification_overrides,
)
from etf_cockpit.application.financial_institution_views import (
    _select_ec_revision,  # noqa: F401 - consumed through the facade by Sparebank tests
    load_financial_institution_projection,
)
from etf_cockpit.application.fixed_income_views import (
    _fixed_income_saved_risk_inputs,  # noqa: F401 - compatibility re-export (consumed through the facade)
    _fixed_income_saved_valuation_inputs,  # noqa: F401 - compatibility re-export (consumed through the facade)
    _persist_fixed_income_screener_snapshot,  # noqa: F401 - compatibility re-export (consumed through the facade)
    calculate_fixed_income_analytics_projection,
    calculate_fixed_income_risk_projection,
    load_fixed_income_analytics_projection,
    load_fixed_income_market_data_projection,
    load_fixed_income_risk_projection,
    load_fixed_income_screener,
    load_fixed_income_terms_projection,
)
from etf_cockpit.application.factor_risk_views import load_bound_factor_risk_panel
from etf_cockpit.application.portfolio_views import (
    load_portfolio_calendar_projection,
    load_portfolio_exposure_projection,
    load_portfolio_forecast_aggregation,
    load_portfolio_holdings_projection,
    load_portfolio_maturity_ladder_projection,
    load_portfolio_performance_series,
    load_portfolio_risk_profile_projection,
    project_portfolio_currency,
)
from etf_cockpit.application.decision_views import (
    build_screen_rows,
    load_opportunity_assessment,
    load_score_metric_history_projection,
    route_decision_rank_rows,
)
from etf_cockpit.application.diagnostics_views import (
    build_profiled_forecast_lab_workspace,
    build_resource_profile_diagnostics,
    load_analysis_parity_report,
)


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


def load_top_n_selection(
    *,
    candidates: Sequence[SelectionCandidate] | None = None,
    mode: str = "cross_asset",
    decision_time: str | None = None,
    top_n: int | None = None,
    seed: int | None = None,
    portfolio_snapshot: Mapping[str, object] | None = None,
    reference_anchor: object | None = None,
    portfolio_policy: object | None = None,
    risk_profile: object | None = None,
    snapshot: object | None = None,
    storage_root: Path | None = None,
) -> dict[str, object]:
    """Build from saved, point-in-time evidence and persist an immutable run."""

    root = Path(storage_root or ROOT).resolve()
    try:
        policy = load_selection_policy()
    except SelectionPolicyError as exc:
        return {
            "contract": "selection-run.v1",
            "status": "unavailable",
            "mode": "unavailable",
            "reason": str(exc),
            "selected_ids": [],
            "candidate_table": [],
            "exclusion_funnel": [],
            "policy": None,
            "persistence_status": "not_attempted",
            "execution_allowed": False,
        }

    if not decision_time:
        return {
            "contract": "selection-run.v1",
            "status": "unavailable",
            "mode": "unavailable",
            "reason": "selection_decision_time_unavailable",
            "selected_ids": [],
            "candidate_table": [],
            "exclusion_funnel": [],
            "policy": policy.to_record(),
            "persistence_status": "not_attempted",
            "execution_allowed": False,
        }

    if candidates is None:
        from dataclasses import fields

        from etf_cockpit.analysis.decision.contracts import OpportunityResult
        from etf_cockpit.application.bulk_run import BulkAnalysisService
        from etf_cockpit.portfolio.benchmark_reference_contract import resolve_vwce_anchor
        from etf_cockpit.portfolio.goals_constraints import policy_from_record
        from etf_cockpit.portfolio.risk_profiles import (
            VWCEAnchorSnapshot,
            RiskProfileVersion,
            load_risk_profile_presets,
            risk_profile_preset_version,
            risk_profile_version_from_record,
        )

        try:
            cutoff = pd.Timestamp(decision_time)
        except (TypeError, ValueError, OverflowError):
            return {
                "contract": "selection-run.v1",
                "status": "unavailable",
                "mode": "unavailable",
                "reason": "selection_decision_time_invalid",
                "selected_ids": [],
                "candidate_table": [],
                "exclusion_funnel": [],
                "policy": policy.to_record(),
                "persistence_status": "not_attempted",
                "execution_allowed": False,
            }
        if cutoff.tzinfo is None:
            return {
                "contract": "selection-run.v1",
                "status": "unavailable",
                "mode": "unavailable",
                "reason": "selection_decision_time_invalid",
                "selected_ids": [],
                "candidate_table": [],
                "exclusion_funnel": [],
                "policy": policy.to_record(),
                "persistence_status": "not_attempted",
                "execution_allowed": False,
            }
        cutoff = cutoff.tz_convert("UTC")

        def _known_by_cutoff(value: object) -> bool:
            try:
                timestamp = pd.Timestamp(value)
                return bool(timestamp.tzinfo is not None and timestamp.tz_convert("UTC") <= cutoff)
            except (TypeError, ValueError, OverflowError):
                return False

        def _record_time(value: Mapping[str, object]) -> object | None:
            return next(
                (value.get(name) for name in ("decision_time", "as_of", "known_at") if value.get(name)),
                None,
            )

        bulk_outputs: dict[str, tuple[Mapping[str, object], str, str]] = {}
        instrument_ids: set[str] = set()
        try:
            bulk_service = BulkAnalysisService(root)
            workflows = bulk_service.scheduler.list_workflows(limit=200)
            for workflow in workflows:
                if workflow.workflow_type != BulkAnalysisService.workflow_type:
                    continue
                if not _known_by_cutoff(workflow.created_at):
                    continue
                bulk_run = bulk_service.get_run(workflow.workflow_id)
                jobs = bulk_service.scheduler.list_jobs(workflow.workflow_id)
                finished_by_id = {
                    str(job.inputs.get("instrument_id")): str(job.finished_at)
                    for job in jobs
                    if isinstance(job.inputs, Mapping)
                    and job.inputs.get("instrument_id")
                    and job.finished_at
                    and _known_by_cutoff(job.finished_at)
                }
                for instrument_id, output in bulk_run.results.items():
                    clean_id = str(instrument_id).strip()
                    if not clean_id:
                        continue
                    instrument_ids.add(clean_id)
                    if not isinstance(output, Mapping):
                        continue
                    known_at = _record_time(output) or finished_by_id.get(clean_id)
                    if known_at is None or not _known_by_cutoff(known_at):
                        continue
                    bulk_outputs.setdefault(
                        clean_id,
                        (dict(output), str(known_at), str(bulk_run.hashes.get(clean_id, ""))),
                    )
        except (AttributeError, KeyError, OSError, sqlite3.Error, TypeError, ValueError):
            bulk_outputs = {}

        universe = getattr(getattr(snapshot, "config", None), "universe", None)
        by_id = getattr(universe, "by_id", None)
        if callable(by_id):
            try:
                instrument_ids.update(str(value).strip() for value in by_id() if str(value).strip())
            except (TypeError, ValueError):
                pass

        try:
            fixed_screen = load_fixed_income_screener(
                storage_root=root,
                decision_time=decision_time,
            )
        except (OSError, TypeError, ValueError):
            fixed_screen = {"status": "unavailable", "rows": [], "decision_time": decision_time}
        fixed_rows_raw = fixed_screen.get("rows", ())
        fixed_rows = {
            str(row.get("instrument_id", "")).strip(): dict(row)
            for row in fixed_rows_raw
            if isinstance(row, Mapping) and str(row.get("instrument_id", "")).strip()
        } if isinstance(fixed_rows_raw, Sequence) else {}
        instrument_ids.update(fixed_rows)

        artifact_directory = LOG_DIR
        try:
            artifact_directory = root / LOG_DIR.relative_to(ROOT)
        except ValueError:
            pass
        opportunity_fields = {item.name for item in fields(OpportunityResult)}
        tuple_fields = {"domain_scores", "positive_drivers", "negative_drivers", "benchmark_rankers"}
        candidates_list: list[SelectionCandidate] = []
        for instrument_id in sorted(instrument_ids):
            try:
                saved_opportunity = load_opportunity_assessment(
                    instrument_id,
                    decision_time=decision_time,
                    artifact_directory=artifact_directory,
                )
                opportunity_values = {
                    key: value for key, value in saved_opportunity.items()
                    if key in opportunity_fields
                }
                for field_name in tuple_fields:
                    if isinstance(opportunity_values.get(field_name), list):
                        opportunity_values[field_name] = tuple(opportunity_values[field_name])
                opportunity = OpportunityResult(**opportunity_values)
            except (KeyError, TypeError, ValueError):
                continue

            output_entry = bulk_outputs.get(instrument_id)
            output = output_entry[0] if output_entry is not None else {}
            metric_values: dict[str, object] = {}
            pending = [output]
            while pending:
                current = pending.pop()
                if not isinstance(current, Mapping):
                    continue
                for key in ("net_expected_return", "downside_risk", "marginal_impact", "liquidity", "cost", "evidence"):
                    if key not in metric_values and current.get(key) is not None:
                        metric_values[key] = current[key]
                pending.extend(value for value in current.values() if isinstance(value, Mapping))

            fixed_row = fixed_rows.get(instrument_id, {})
            if metric_values.get("net_expected_return") is None and fixed_row.get("net_total_return") is not None:
                metric_values["net_expected_return"] = fixed_row["net_total_return"]
            if metric_values.get("downside_risk") is None and fixed_row.get("loss_probability") is not None:
                metric_values["downside_risk"] = fixed_row["loss_probability"]
            if metric_values.get("evidence") is None:
                metric_values["evidence"] = opportunity.confidence

            country = None
            sector = None
            try:
                classification = load_classification_projection(
                    instrument_id,
                    storage_root=root,
                    effective_at=decision_time,
                    decision_time=decision_time,
                )
                classification_value = classification.get("classification")
                if isinstance(classification_value, Mapping):
                    country = classification_value.get("country")
                    sector = classification_value.get("sector")
            except (OSError, TypeError, ValueError):
                pass
            country = country or fixed_row.get("country")
            sector = sector or fixed_row.get("issuer_sector")
            common_times = [opportunity.decision_time]
            if output_entry is not None:
                common_times.append(output_entry[1])
            if fixed_row and fixed_screen.get("decision_time"):
                common_times.append(str(fixed_screen["decision_time"]))
            source_hashes = [("opportunity_universe", opportunity.universe_hash),
                             ("opportunity_policy", opportunity.config_hash),
                             ("opportunity_vintage", opportunity.source_vintage_hash)]
            if output_entry is not None and output_entry[2]:
                source_hashes.append(("bulk_run", output_entry[2]))
            if fixed_row and fixed_screen.get("analysis_snapshot_id"):
                source_hashes.append(("fixed_income_screener", str(fixed_screen["analysis_snapshot_id"])))
            candidates_list.append(
                SelectionCandidate(
                    opportunity=opportunity,
                    common_metrics_as_of=max(
                        pd.Timestamp(value).tz_convert("UTC") for value in common_times
                    ).isoformat(),
                    country=None if country is None else str(country),
                    sector=None if sector is None else str(sector),
                    net_expected_return=metric_values.get("net_expected_return"),
                    downside_risk=metric_values.get("downside_risk"),
                    marginal_impact=metric_values.get("marginal_impact"),
                    liquidity=metric_values.get("liquidity"),
                    cost=metric_values.get("cost"),
                    evidence=metric_values.get("evidence"),
                    source_hashes=tuple(source_hashes),
                )
            )
        candidates = tuple(candidates_list)
        if not candidates:
            return {
                "contract": "selection-run.v1",
                "status": "unavailable",
                "mode": mode if mode in {"asset_specific", "cross_asset"} else "unavailable",
                "reason": "frozen_opportunity_candidates_unavailable",
                "decision_time": decision_time,
                "top_n": policy.top_n if top_n is None else top_n,
                "seed": seed,
                "policy": policy.to_record(),
                "candidate_table": [],
                "selected_ids": [],
                "exclusion_funnel": [],
                "source_snapshot_hashes": {},
                "portfolio_reference": None,
                "persistence_status": "not_attempted",
                "execution_allowed": False,
            }

        if portfolio_snapshot is None and snapshot is not None:
            candidate_snapshot = getattr(snapshot, "portfolio_snapshot", None)
            if isinstance(candidate_snapshot, Mapping):
                portfolio_snapshot = dict(candidate_snapshot)
            else:
                binding = getattr(snapshot, "candidate_price_binding", None)
                binding = binding if isinstance(binding, Mapping) else {}
                portfolio_id = getattr(snapshot, "portfolio_id", None)
                snapshot_id = getattr(snapshot, "snapshot_id", binding.get("snapshot_id"))
                as_of = getattr(snapshot, "as_of", binding.get("as_of"))
                if portfolio_id and snapshot_id and as_of:
                    holdings = getattr(snapshot, "holdings", None)
                    portfolio_snapshot = {
                        "portfolio_id": str(portfolio_id),
                        "snapshot_id": str(snapshot_id),
                        "as_of": str(as_of),
                        "holdings": holdings.to_dict(orient="records") if isinstance(holdings, pd.DataFrame) else [],
                    }

        if reference_anchor is None and portfolio_snapshot is None and snapshot is not None:
            supplied_anchor = getattr(snapshot, "vwce_anchor_snapshot", None)
            if isinstance(supplied_anchor, VWCEAnchorSnapshot):
                reference_anchor = supplied_anchor
            else:
                evidence = getattr(snapshot, "vwce_anchor_evidence", None)
                listing_id = getattr(snapshot, "vwce_listing_id", None)
                currency = getattr(snapshot, "benchmark_reference_currency", None)
                horizon = getattr(snapshot, "benchmark_reference_horizon_years", None)
                effective_date = getattr(snapshot, "benchmark_reference_end_date", None)
                if evidence is not None and listing_id and currency and horizon and effective_date:
                    try:
                        resolved = resolve_vwce_anchor(
                            evidence,
                            listing_id=str(listing_id),
                            effective_date=str(effective_date),
                            decision_time=decision_time,
                            currency=str(currency),
                            horizon_years=float(horizon),
                            conversion_evidence=getattr(snapshot, "vwce_conversion_evidence", None),
                        )
                        reference_anchor = VWCEAnchorSnapshot(
                            status="available" if resolved.status == "available" else "unavailable",
                            reason=resolved.reason,
                            canonical_share_class_id=resolved.canonical_share_class_id,
                            listing_id=resolved.listing_id,
                            effective_date=resolved.effective_date,
                            knowledge_cutoff=resolved.decision_time,
                            output_currency=resolved.output_currency,
                            horizon_years=resolved.horizon_years,
                            anchor_digest=resolved.anchor_digest,
                            resolution_digest=resolved.replay_digest,
                            risk_envelope_status="unavailable",
                            risk_metrics=(),
                        )
                    except (TypeError, ValueError):
                        reference_anchor = None

        if portfolio_policy is None and snapshot is not None:
            try:
                goals = load_portfolio_goals_projection(snapshot, root=root)
                versions = goals.get("policy_history", ())
                if isinstance(versions, Sequence) and not isinstance(versions, (str, bytes)):
                    usable_versions = [
                        item for item in versions
                        if isinstance(item, Mapping)
                        and item.get("saved_at")
                        and _known_by_cutoff(item.get("saved_at"))
                    ]
                    if usable_versions:
                        portfolio_policy = policy_from_record(usable_versions[-1])
            except (OSError, TypeError, ValueError):
                portfolio_policy = None

        if risk_profile is None:
            supplied_profile = getattr(snapshot, "risk_profile", None) if snapshot is not None else None
            if isinstance(supplied_profile, RiskProfileVersion):
                risk_profile = supplied_profile
            elif isinstance(supplied_profile, Mapping):
                try:
                    risk_profile = risk_profile_version_from_record(supplied_profile)
                except (TypeError, ValueError):
                    risk_profile = None
            if risk_profile is None:
                try:
                    presets = load_risk_profile_presets()
                    default_profile = next(item for item in presets if item.profile_id == "medium")
                    risk_profile = risk_profile_preset_version(default_profile)
                except (StopIteration, OSError, TypeError, ValueError):
                    risk_profile = None

    try:
        run = build_selection_run(
            candidates,
            decision_time=decision_time,
            mode=mode,  # type: ignore[arg-type]
            policy=policy,
            top_n=top_n,
            seed=seed,
            portfolio_snapshot=portfolio_snapshot,
            reference_anchor=reference_anchor,
            portfolio_policy=portfolio_policy,  # type: ignore[arg-type]
            risk_profile=risk_profile,  # type: ignore[arg-type]
        )
        with TransactionalStore(root) as store:
            stored = persist_selection_run(store, run)
    except (OSError, StorageSchemaError, sqlite3.DatabaseError, TypeError, ValueError) as exc:
        return {
            "contract": "selection-run.v1",
            "status": "unavailable",
            "mode": "unavailable",
            "reason": "selection_run_unavailable:" + str(exc),
            "selected_ids": [],
            "candidate_table": [],
            "exclusion_funnel": [],
            "policy": policy.to_record(),
            "persistence_status": "failed",
            "execution_allowed": False,
        }
    return {
        **run.to_record(),
        "slices": materialise_selection_slices(run),
        "persistence_status": "persisted",
        "persistence_revision": stored.revision,
    }


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
    if decision_time is not None:
        decision_cutoff = pd.to_datetime(decision_time, errors="coerce", utc=True)
        if pd.isna(decision_cutoff):
            return {"status": "unavailable", "reason_code": "decision_time_invalid", "frame": pd.DataFrame(), "execution_allowed": False}
        observation_times = pd.to_datetime(scoped["date"], errors="coerce", utc=True)
        scoped = scoped.loc[observation_times.notna() & (observation_times < decision_cutoff)].copy()
        if "known_at" in scoped:
            known_times = pd.to_datetime(scoped["known_at"], errors="coerce", utc=True)
            scoped = scoped.loc[known_times.notna() & (known_times < decision_cutoff)].copy()
        if scoped.empty:
            return {"status": "unavailable", "reason_code": "market_series_outside_decision_window", "frame": pd.DataFrame(), "execution_allowed": False}
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
        frame["fx_return"] = frame["fx_rate"].pct_change(fill_method=None)
        local_returns = frame["local_total_return"].copy()
        fx_returns = frame["fx_return"].copy()
        if local_returns.iloc[1:].isna().any() or fx_returns.iloc[1:].isna().any():
            return {"status": "unavailable", "reason_code": "required_total_return_input_missing", "frame": pd.DataFrame(), "execution_allowed": False}
        if not local_returns.empty:
            # The first row has no prior observation; only this base-period return is defined as zero.
            local_returns.iloc[0] = 0.0
            fx_returns.iloc[0] = 0.0
        frame["output_total_return"] = (1.0 + local_returns) * (1.0 + fx_returns) - 1.0
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

    from etf_cockpit.application.etf_economics_view import build_etf_economics_panel

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


# The presentation-facing surface: own read models plus the re-exports that
# pages, components, selectors, scripts and tests consume (refactor P2.1).
__all__ = [
    "add_record",
    "allocation_frame",
    "analyse_portfolio_candidate",
    "analysis_parity_report_path",
    "AnomalyLedger",
    "ApiStatus",
    "assess_fundamental_row",
    "BENCHMARK_ATTRIBUTION_PATH",
    "bitemporal_history_summary",
    "build_coverage_audit",
    "build_currency_context",
    "build_data_health",
    "build_direct_overlap_view",
    "build_document_inventory",
    "build_factor_risk_report",
    "build_market_clock_diagnostics",
    "build_performance_attribution",
    "build_portfolio_candidate",
    "build_profiled_forecast_lab_workspace",
    "build_rebalance_report",
    "build_resource_profile_diagnostics",
    "build_robust_risk_report",
    "build_screen_rows",
    "build_simple_instrument_scores",
    "build_stock_research_report",
    "build_universe_manifest",
    "build_version_registry",
    "bulk_cache_health",
    "calculate_etf_economics",
    "calculate_fixed_income_analytics_projection",
    "calculate_fixed_income_risk_projection",
    "calculate_net_return_scenario",
    "CancelWorkflowCommand",
    "candidate_id",
    "CANONICAL_DISTRIBUTION_HORIZONS_DAYS",
    "cash_comparison_from_projection",
    "cash_comparison_to_projection",
    "ClassificationOverride",
    "commit_restore",
    "compare_runs",
    "compatibility_summary",
    "configured_forecast_request_identity",
    "CONSENSUS_IMPORT_PATH",
    "ContentAddressedCache",
    "CORRELATION_CLUSTERS_PATH",
    "cost_capacity_status",
    "coverage_summary_lines",
    "create_backup",
    "create_encrypted_backup",
    "create_import_resume_state",
    "DataCatalogue",
    "DataCatalogueError",
    "DataHealthReport",
    "DataHealthRow",
    "DataHealthStatus",
    "decision_from_score",
    "DecisionJournal",
    "delete_private_data",
    "direct_overlap_payload",
    "disable_record",
    "draft_portfolio_candidate",
    "drawdown_contribution",
    "dry_run_universe_import",
    "edit_record",
    "estimate_workflow_resources",
    "ETF_DISCLOSURES_PATH",
    "ETF_METADATA_CLEAN_PATH",
    "ETF_REPORT_CONFLICTS_PATH",
    "ETF_REPORT_RECORDS_PATH",
    "ETFContextAssumptions",
    "EtfReportImportRequest",
    "EtfReportReviewRequest",
    "EVENT_CLEAN_PATH",
    "event_engine_status",
    "events_available_as_of",
    "EVIDENCE_LEDGER_PATH",
    "export_data_health",
    "export_screen_csv",
    "export_table",
    "exposure_limit_report",
    "exposure_summary",
    "extract_and_validate_audit_archive",
    "FEATURE_DRIVERS_PATH",
    "FILING_COVERAGE_PATH",
    "FILINGS_STATEMENTS_PATH",
    "filter_data_health_rows",
    "filter_forecasts_for_universe",
    "fixed_income_terms_exists",
    "forecast_score_details",
    "format_model_inventory_line",
    "ForwardEvidenceDiary",
    "ForwardEvidenceIntegrityError",
    "ForwardEvidenceObservation",
    "ForwardInputManifest",
    "FUND_HOLDINGS_PATH",
    "FUNDAMENTAL_CLEAN_PATH",
    "FX_CLEAN_PATH",
    "fx_data_inventory",
    "generated_cache_cleanup",
    "group_simple_scores",
    "GUIDANCE_IMPORT_PATH",
    "IDENTITY_PATH",
    "import_etf_document",
    "import_etf_holdings_with_document",
    "import_etf_report",
    "import_legacy_universe",
    "ImportPreview",
    "ImportService",
    "INDEX_METHODOLOGY_RECORDS_PATH",
    "InvestabilityPolicyProfile",
    "is_valid_isin",
    "JournalEntry",
    "JournalIntegrityError",
    "latest_fundamental_rows",
    "legal_terms_report",
    "legal_terms_rows",
    "load_analysis_parity_report",
    "load_bound_factor_risk_panel",
    "load_calendar_events",
    "load_canary_status",
    "load_candidate_price_binding",
    "load_capital_allocation_analysis",
    "load_classification_projection",
    "load_cyclical_projection",
    "load_etf_economics_projection",
    "load_etf_look_through",
    "load_etf_structure_projection",
    "load_financial_institution_projection",
    "load_fixed_income_analytics_projection",
    "load_fixed_income_market_data_projection",
    "load_fixed_income_risk_projection",
    "load_fixed_income_screener",
    "load_fixed_income_screener_config",
    "load_fixed_income_terms_projection",
    "load_forecast_return_distributions",
    "load_fundamental_evidence",
    "load_fx_rates",
    "load_identity_projection",
    "load_innovation_projection",
    "load_latest_forecasts",
    "load_local_structural_evidence",
    "load_manual_news",
    "load_market_series_projection",
    "load_news_items",
    "load_opportunity_assessment",
    "load_optional_research_import",
    "load_paper_incidents",
    "load_paper_tca_view",
    "load_paper_timeline",
    "load_paper_trade_rows",
    "load_peer_cohort_projection",
    "load_portfolio_calendar_projection",
    "load_portfolio_candidate",
    "load_portfolio_exposure_projection",
    "load_portfolio_forecast_aggregation",
    "load_portfolio_goals_projection",
    "load_portfolio_holdings_projection",
    "load_portfolio_maturity_ladder_projection",
    "load_portfolio_performance_series",
    "load_portfolio_risk_profile_projection",
    "load_portfolio_valuation_history",
    "load_prices",
    "load_real_asset_projection",
    "load_reference_dataset",
    "load_risk_free_proxy_mappings",
    "load_score_history_summary",
    "load_score_metric_history_projection",
    "load_screen",
    "load_simple_scoreboard",
    "load_statement_evidence",
    "load_stock_research_context",
    "load_tax_hedge_assumptions",
    "load_top_n_selection",
    "load_universe",
    "load_valuation_evidence",
    "load_valuation_market_inputs",
    "LOG_DIR",
    "MacroWarehouse",
    "MacroWarehouseError",
    "MANUAL_FILING_QUEUE_PATH",
    "MANUAL_NEWS_CLEAN_PATH",
    "manual_news_markdown",
    "model_zoo_frame",
    "NEWS_CLEAN_PATH",
    "NEWS_CONTEXT_PATH",
    "NEWS_TIMESTAMP_VALIDATION_PATH",
    "normalise_bound_claim",
    "normalise_event_decision_time",
    "normalise_holdings",
    "OAM_DISCOVERY_PATH",
    "operational_calendar_record_is_canonical",
    "PageRequest",
    "performance_series_frame",
    "persist_index_methodology_with_document",
    "persist_priips_kid_with_document",
    "portfolio_snapshot_binding",
    "PortfolioAnalysis",
    "PortfolioCandidate",
    "PortfolioSandboxPersistenceError",
    "PRICE_PARQUET",
    "PRIIPS_KID_RECORDS_PATH",
    "PRIMARY_MODEL_HORIZON_DAYS",
    "project_portfolio_currency",
    "PROVIDER_PROBE_PATH",
    "ProviderRegistry",
    "query_for_snapshot",
    "raw_to_score_10",
    "read_document_registry",
    "read_etf_report_records",
    "read_index_methodology_records",
    "read_priips_kid_records",
    "rebalance_inapplicable_instruments",
    "RebalanceConstraints",
    "RebalanceReport",
    "redact_private_fields",
    "reference_data_inventory",
    "release_certification_report",
    "remove_record",
    "REQUIRED_CHANGE_DIMENSIONS",
    "resource_profile_report",
    "ResourcePolicy",
    "resume_universe_import",
    "return_correlation_matrix",
    "review_etf_report",
    "ROOT",
    "route_decision_rank_rows",
    "run_disaster_recovery_drill",
    "run_screen",
    "save_classification_overrides",
    "save_manual_note_credibility_review",
    "save_portfolio_candidate",
    "save_screen",
    "save_universe",
    "save_universe_manifest",
    "SCORE_COMPONENTS_PATH",
    "score_history_frame",
    "SCORE_HISTORY_PATH",
    "SCORE_LEGEND",
    "SCORE_METRIC_HISTORY_PATH",
    "ScreenFilter",
    "ScreenSort",
    "select_comparison_runs",
    "select_holdings_view",
    "SimpleInstrumentScore",
    "SimpleScoreComponent",
    "sort_fundamental_evidence",
    "sort_news_items",
    "SOURCE_CONFLICTS_PATH",
    "source_policy_rows",
    "STATEMENT_FACTS_PATH",
    "storage_layout",
    "StorageRevisionConflict",
    "SubmitWorkflowCommand",
    "supply_chain_intake_report",
    "TransactionalStore",
    "underlying_holdings_exposure",
    "universe_payload_revision",
    "UniverseRecord",
    "UPSTREAM_CHANGE_DIMENSIONS",
    "upstream_run_context",
    "validate_encrypted_restore",
    "validate_import",
    "validate_restore",
    "validate_universe",
    "valuation_analysis",
    "write_coverage_audit",
]
