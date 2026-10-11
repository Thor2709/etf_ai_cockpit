"""Presentation-facing compatibility facade for the first ISSUE-0071 wave.

Pages, components and selectors depend on this application boundary instead
of importing storage/provider implementations directly. The underlying
implementations remain compatible while later slices move them behind typed
ports and application commands.
"""

from etf_cockpit.core.paths import STATEMENT_FACTS_PATH
from etf_cockpit.data.event_calendar import load_calendar_events, normalise_event_decision_time
from etf_cockpit.data.local_storage import StorageRevisionConflict, TransactionalStore
from etf_cockpit.data.macro_warehouse import MacroWarehouse
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
from etf_cockpit.data.classification import (
    ClassificationOverride,
)


from etf_cockpit.data.manual_notes import (
    MANUAL_NEWS_CLEAN_PATH,
    load_manual_news,
    manual_news_markdown,
    save_manual_note_credibility_review,
)
from etf_cockpit.data.news_context import _headline_direction as headline_direction, sort_news_items
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
from etf_cockpit.analysis.screening import (
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
    load_financial_institution_projection,
)
from etf_cockpit.application.fixed_income_views import (
    calculate_fixed_income_analytics_projection,
    load_fixed_income_analytics_projection,
    load_fixed_income_market_data_projection,
    load_fixed_income_risk_projection,
    load_fixed_income_screener,
    load_fixed_income_terms_projection,
)
from etf_cockpit.application.factor_risk_views import load_bound_factor_risk_panel
from etf_cockpit.application.portfolio_views import (
    load_portfolio_calendar_projection,
    load_portfolio_forecast_aggregation,
    load_portfolio_holdings_projection,
    load_portfolio_maturity_ladder_projection,
    load_portfolio_performance_series,
    load_portfolio_risk_profile_projection,
)
from etf_cockpit.application.decision_views import (
    build_screen_rows,
    load_opportunity_assessment,
    load_score_metric_history_projection,
)
from etf_cockpit.application.diagnostics_views import (
    load_analysis_parity_report,
)
from etf_cockpit.application.selection_views import (
    load_portfolio_goals_projection,
    load_top_n_selection,
)
from etf_cockpit.application.market_views import (
    load_etf_structure_projection,
    load_market_series_projection,
)
from etf_cockpit.application.sector_views import (
    load_cyclical_projection,
    load_innovation_projection,
    load_real_asset_projection,
)
from etf_cockpit.application.valuation_views import (
    load_capital_allocation_analysis,
    load_stock_research_context,
    load_valuation_evidence,
    load_valuation_market_inputs,
)


# The presentation-facing surface: own read models plus the re-exports that
# pages, components, selectors, scripts and tests consume (refactor P2.1).
__all__ = [
    "add_record",
    "allocation_frame",
    "analyse_portfolio_candidate",
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
    "build_rebalance_report",
    "build_robust_risk_report",
    "build_screen_rows",
    "build_simple_instrument_scores",
    "build_stock_research_report",
    "build_universe_manifest",
    "build_version_registry",
    "bulk_cache_health",
    "calculate_fixed_income_analytics_projection",
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
    "forecast_score_details",
    "format_model_inventory_line",
    "ForwardEvidenceDiary",
    "ForwardEvidenceIntegrityError",
    "ForwardEvidenceObservation",
    "ForwardInputManifest",
    "FUND_HOLDINGS_PATH",
    "FUNDAMENTAL_CLEAN_PATH",
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
    "load_candidate_price_binding",
    "load_capital_allocation_analysis",
    "load_classification_projection",
    "load_cyclical_projection",
    "load_etf_structure_projection",
    "load_financial_institution_projection",
    "load_fixed_income_analytics_projection",
    "load_fixed_income_market_data_projection",
    "load_fixed_income_risk_projection",
    "load_fixed_income_screener",
    "load_fixed_income_terms_projection",
    "load_fundamental_evidence",
    "load_identity_projection",
    "load_innovation_projection",
    "load_latest_forecasts",
    "load_local_structural_evidence",
    "load_manual_news",
    "load_market_series_projection",
    "load_news_items",
    "load_opportunity_assessment",
    "load_optional_research_import",
    "load_paper_tca_view",
    "load_paper_timeline",
    "load_paper_trade_rows",
    "load_peer_cohort_projection",
    "load_portfolio_calendar_projection",
    "load_portfolio_candidate",
    "load_portfolio_forecast_aggregation",
    "load_portfolio_goals_projection",
    "load_portfolio_holdings_projection",
    "load_portfolio_maturity_ladder_projection",
    "load_portfolio_performance_series",
    "load_portfolio_risk_profile_projection",
    "load_real_asset_projection",
    "load_reference_dataset",
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
    "PRIIPS_KID_RECORDS_PATH",
    "PRIMARY_MODEL_HORIZON_DAYS",
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
    "headline_direction",
    "sort_news_items",
    "SOURCE_CONFLICTS_PATH",
    "source_policy_rows",
    "STATEMENT_FACTS_PATH",
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
    "write_coverage_audit",
]
