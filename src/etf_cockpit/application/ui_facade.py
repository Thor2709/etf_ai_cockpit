"""Presentation-facing compatibility facade for the first ISSUE-0071 wave.

Pages, components and selectors depend on this application boundary instead
of importing storage/provider implementations directly. The underlying
implementations remain compatible while later slices move them behind typed
ports and application commands.
"""

from collections.abc import Mapping
import math
from numbers import Real
from pathlib import Path

import pandas as pd

from etf_cockpit.analysis.parity_report import (
    analysis_parity_report_path,
)
from etf_cockpit.core.paths import LOG_DIR, STATEMENT_FACTS_PATH
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.event_calendar import load_calendar_events, normalise_event_decision_time
from etf_cockpit.data.capital_allocation import capital_allocation_analysis
from etf_cockpit.data.market_adjustments import CorporateActionCoverage
from etf_cockpit.data.duckdb_store import PRICE_PARQUET, load_prices
from etf_cockpit.data.fx_data import FX_CLEAN_PATH, load_fx_rates
from etf_cockpit.data.local_storage import StorageRevisionConflict, TransactionalStore, storage_layout
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
from etf_cockpit.application.selection_views import (
    load_portfolio_goals_projection,
    load_top_n_selection,
)
from etf_cockpit.application.market_views import (
    _load_market_series_projection,  # noqa: F401 - compatibility re-export (consumed through the facade)
    load_etf_economics_projection,
    load_etf_look_through,
    load_etf_structure_projection,
    load_market_series_projection,
)
from etf_cockpit.application.sector_views import (
    load_cyclical_projection,
    load_innovation_projection,
    load_real_asset_projection,
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
