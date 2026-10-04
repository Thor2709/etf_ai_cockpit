from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from io import BytesIO
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
    FORECASTS_DIR,
    ensure_project_dirs,
)
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.core.timing import record_cache_event, timed_step
from etf_cockpit.core.types import DataQualityReport, SignalResult, latest_signal
from etf_cockpit.core.workflow import PublicationScopeFactory, WorkflowTransitionError, publication_scope
from etf_cockpit.core.versioning import (
    current_settings_identity,
    current_settings_revision,
    ensure_run_manifest,
    settings_bound_run_id,
)
from etf_cockpit.data.duckdb_store import FEATURE_PARQUET, initialise_store, load_features, load_holdings, load_prices, write_features
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
from etf_cockpit.data.fx_data import commit_fx_import, fx_data_inventory, load_fx_rates, validate_fx_rates
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
from etf_cockpit.data.fundamentals import load_fundamental_evidence
from etf_cockpit.data.identity_master import (
    IdentityMasterStore,
)
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.import_pipeline import commit_price_import, rollback_latest_price_import as rollback_price_store
from etf_cockpit.data.manual_notes import commit_manual_news_import, load_manual_news, validate_manual_news
from etf_cockpit.data.parsed_disclosures import read_etf_report_records
from etf_cockpit.data.providers import GenericHTTPProvider, ManualLocalFileProvider, ProviderResult
from etf_cockpit.data.reference_data import (
    ETF_METADATA_CLEAN_PATH,
    commit_reference_import,
    normalise_reference_dataset_type,
    reference_data_inventory,
    validate_reference_dataset,
)
from etf_cockpit.data.sample_data import ensure_sample_files
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH
from etf_cockpit.data.trade_candidate_analysis import (
    fetch_candidate_prices,
    load_candidate_price_binding,
    refresh_candidate_analysis,
    write_candidate_price_snapshot,
)
from etf_cockpit.data.validation import validate_holdings, validate_prices
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.forecast_scores import (
    configured_forecast_request_identity,
    forecast_component_maps,
    forecast_return_distributions,
    load_latest_forecasts,
)
from etf_cockpit.models.calibration import load_forecast_history
from etf_cockpit.models.local_weights import LocalModelStatus
from etf_cockpit.models.registry import model_availability, model_diagnostics
from etf_cockpit.portfolio.risk import target_policy_issues
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
    _price_binding_matches,
    _price_snapshot_binding,
    _read_bound_cache_payload,
    _reference_binding,
    _reference_identity_hash,
    _reference_identity_matches,
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
    _config_with_optional_models_disabled,
    _forecast_frame_status_summary,
    _forecast_status_summary,
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


class DataService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.last_operation_succeeded = True

    def update_prices(
        self,
        force_sample: bool = False,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> None:
        ensure_sample_files(self.config, force=force_sample, publish_guard=publish_guard)
        initialise_store(self.config, force_sample=force_sample, publish_guard=publish_guard)

    def load_prices(self, etf_ids: list[str] | None = None, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        prices = load_prices()
        if etf_ids:
            prices = prices[prices["etf_id"].isin(etf_ids)]
        prices["date"] = pd.to_datetime(prices["date"]).dt.date
        if start:
            prices = prices[prices["date"] >= start]
        if end:
            prices = prices[prices["date"] <= end]
        return prices

    def validate_prices(
        self,
        prices: pd.DataFrame | None = None,
        as_of_date: date | None = None,
        holdings: pd.DataFrame | None = None,
    ) -> DataQualityReport:
        report = validate_prices(prices if prices is not None else self.load_prices(), as_of_date=as_of_date)
        holdings_report = (
            validate_holdings(self.config, holdings, as_of_date=report.as_of_date, fx_rates=load_fx_rates())
            if holdings is not None
            else None
        )
        policy_issues = target_policy_issues(self.config)
        extra_issues = [*(holdings_report.issues if holdings_report else []), *policy_issues]
        extra_metadata = holdings_report.dataset_metadata if holdings_report else []
        if not extra_issues and not extra_metadata:
            return report
        return DataQualityReport(
            as_of_date=report.as_of_date,
            issues=[*report.issues, *extra_issues],
            dataset_metadata=[*report.dataset_metadata, *extra_metadata],
        )

    def dry_run_update(self) -> str:
        report = self.validate_prices(holdings=load_holdings())
        manual_notes = load_manual_news()
        meta_lines = [
            f"{meta.source_type}: {meta.staleness_status}, as_of={meta.as_of_date}, checksum={meta.checksum[:12]}"
            for meta in report.dataset_metadata
        ]
        if not manual_notes.empty:
            latest_note_date = pd.to_datetime(manual_notes["as_of_date"], errors="coerce").max()
            latest_note_label = latest_note_date.date().isoformat() if pd.notna(latest_note_date) else "unknown"
            manual_validation = validate_manual_news(manual_notes)
            checksum = manual_validation.metadata.checksum if manual_validation.metadata else "unknown"
            meta_lines.append(f"manual_news: dated_only, as_of={latest_note_label}, checksum={checksum[:12]}")
        for reference in reference_data_inventory():
            if not reference["present"]:
                continue
            meta_lines.append(
                (
                    f"{reference['dataset_type']}: {reference['staleness_status']}, "
                    f"as_of={reference['as_of_date']}, checksum={str(reference['checksum'])[:12]}"
                )
            )
        fx_inventory = fx_data_inventory()
        if fx_inventory["present"]:
            meta_lines.append(
                (
                    f"fx: {fx_inventory['staleness_status']}, as_of={fx_inventory['as_of_date']}, "
                    f"pairs={','.join(fx_inventory['pairs'])}, checksum={str(fx_inventory['checksum'])[:12]}"
                )
            )
        issue_lines = [f"{issue.severity.upper()} {issue.code}: {issue.message}" for issue in report.issues]
        return "\n".join(
            [
                "Dry run completed. Current local data was validated; no files were replaced.",
                f"Analysis hard block: {not report.analysis_allowed}",
                *(meta_lines or ["No dataset metadata available."]),
                *(issue_lines or ["No validation issues found."]),
            ]
        )

    def api_update_status(self, *, publish_guard: PublicationScopeFactory | None = None) -> str:
        section = self.config.data_providers.section("prices")
        if section.active_provider.lower() == "yfinance":
            return self.refresh_yfinance_data(publish_guard=publish_guard)
        result = GenericHTTPProvider(section).fetch_prices([], date.today(), date.today())
        self.last_operation_succeeded = result.ok
        return redact_text(str(result.message))

    def refresh_yfinance_data(
        self,
        *,
        years: int = 5,
        include_reference_data: bool = True,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        self.last_operation_succeeded = False
        end_date = date.today()
        start_date = end_date.replace(year=end_date.year - years)
        provider = YFinanceProvider.from_config(self.config)
        messages: list[str] = []

        result = provider.fetch_prices([], start_date, end_date)
        if not result.ok or result.data is None:
            return redact_text(str(result.message))
        report = validate_prices(result.data, as_of_date=end_date)
        block_issues = [issue.message for issue in report.issues if issue.severity == "block"]
        if block_issues:
            return "Yahoo Finance prices fetched but not committed because validation blocked them: " + "; ".join(block_issues)
        with publication_scope(publish_guard):
            commit_result = commit_price_import(result)
        messages.append(
            (
                f"{result.message} Validated and committed {commit_result.rows} price rows. "
                f"Clean prices: {commit_result.clean_path}. Previous snapshot: {commit_result.previous_snapshot_path or 'none'}."
            )
        )

        if include_reference_data:
            context = self._reference_context()
            for dataset_type, reference_result in (
                ("etf_metadata", provider.fetch_etf_metadata([])),
                ("etf_holdings", provider.fetch_etf_holdings([])),
            ):
                if not reference_result.ok or reference_result.data is None:
                    messages.append(f"{dataset_type}: {redact_text(str(reference_result.message))}")
                    continue
                try:
                    with publication_scope(publish_guard):
                        reference_commit = commit_reference_import(
                            reference_result,
                            dataset_type,
                            known_etfs=context["known_etfs"],
                            isin_to_etf_id=context["isin_to_etf_id"],
                            ticker_to_etf_id=context["ticker_to_etf_id"],
                        )
                except WorkflowTransitionError:
                    raise
                except Exception as exc:
                    messages.append(
                        f"{dataset_type}: fetched but not committed because validation failed ({type(exc).__name__})."
                    )
                    continue
                warning_suffix = f" Warnings: {'; '.join(reference_commit.warnings)}" if reference_commit.warnings else ""
                messages.append(
                    (
                        f"{redact_text(str(reference_result.message))} Validated and committed {reference_commit.rows} {dataset_type} rows. "
                        f"Clean data: {reference_commit.clean_path}.{warning_suffix}"
                    )
                )
        self.last_operation_succeeded = True
        return "\n".join(messages)

    def run_yfinance_candidate_analysis(
        self,
        *,
        years: int = 5,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        result = refresh_candidate_analysis(self.config, years=years, publish_guard=publish_guard)
        return (
            f"YFinance candidate algorithms refreshed for {result.rows} instruments as of {result.effective_as_of}. "
            f"Report: {result.csv_path}."
        )

    def run_yfinance_forecasts(
        self,
        *,
        years: int = 5,
        include_candidates: bool = True,
        horizons: list[int] | None = None,
        use_cache: bool = True,
        live_optional_models: bool = True,
        progress_callback: Callable[[str, int, int], None] | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        self.last_operation_succeeded = False
        settings_revision = current_settings_revision()
        prices = load_prices()
        if prices.empty:
            return "No clean yfinance prices are available. Refresh yfinance data first."
        prices = prices.copy()
        prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
        effective_as_of = prices["date"].max().date()
        reference_inputs = _benchmark_reference_snapshot_inputs(
            self.config,
            effective_as_of,
            load_holdings(),
        )
        reference_context = _reference_context_from_inputs(
            reference_inputs,
            purpose="comparison",
            analysis_id=f"forecast:{effective_as_of.isoformat()}",
        )
        calculation_window = _calculation_window(reference_context, effective_as_of, prices)
        if calculation_window is None:
            return "Forecast calculation skipped because the canonical calculation window is unavailable."
        price_binding = _price_snapshot_binding(prices, calculation_window=calculation_window)
        if price_binding is None:
            return "Forecast calculation skipped because the adjusted-price snapshot identity is unavailable."
        try:
            request_identity = _forecast_request_identity(
                self.config,
                horizons,
                live_optional_models=live_optional_models,
            )
        except ValueError as exc:
            return f"Forecast calculation skipped because the request identity is invalid: {exc}."
        forecast_config = self.config if live_optional_models else _config_with_optional_models_disabled(self.config)
        forecast_service = ForecastService(forecast_config, reference_context=reference_context)
        universe_revision = _current_universe_revision()
        output = FORECASTS_DIR / f"forecast_results_yfinance_{effective_as_of:%Y%m%d}.csv"
        if use_cache and output.exists() and _cache_matches_universe(
            output, universe_revision, settings_revision, reference_context.identity, price_binding, request_identity
        ):
            try:
                cached_payload = _read_bound_cache_payload(
                    output,
                    universe_revision,
                    settings_revision,
                    reference_context.identity,
                    price_binding,
                    request_identity,
                )
                if cached_payload is None:
                    raise ValueError("forecast cache pair changed during read")
                universe_forecast_frame = pd.read_csv(BytesIO(cached_payload))
            except Exception:
                record_cache_event("forecast", "invalidation", action_id="forecasts", detail="unreadable output")
                universe_forecast_frame = None
            if universe_forecast_frame is not None:
                if progress_callback is not None:
                    progress_callback("Running baseline forecasts", 1, 4)
                    progress_callback("Checking cached TimesFM forecasts", 2, 4)
                    progress_callback("Checking cached Toto forecasts", 3, 4)
                record_cache_event("forecast", "hit", action_id="forecasts")
                universe_summary = _forecast_frame_status_summary(universe_forecast_frame)
                universe_mode = "reused from cache"
            else:
                record_cache_event("forecast", "miss", action_id="forecasts")
                universe_forecasts = forecast_service.run_forecasts(
                    effective_as_of,
                    self.config.universe.enabled_ids,
                    prices,
                    output_path=output,
                    horizons=horizons,
                    progress_callback=progress_callback,
                    publish_guard=publish_guard,
                    cache_request_identity=request_identity,
                    live_optional_models=live_optional_models,
                )
                universe_summary = _forecast_status_summary(universe_forecasts)
                universe_mode = "refreshed"
        else:
            if use_cache and output.exists():
                record_cache_event("forecast", "invalidation", action_id="forecasts", detail="universe revision changed or metadata missing")
            record_cache_event("forecast", "miss", action_id="forecasts")
            universe_forecasts = forecast_service.run_forecasts(
                effective_as_of,
                self.config.universe.enabled_ids,
                prices,
                output_path=output,
                horizons=horizons,
                progress_callback=progress_callback,
                publish_guard=publish_guard,
                cache_request_identity=request_identity,
                live_optional_models=live_optional_models,
            )
            universe_summary = _forecast_status_summary(universe_forecasts)
            universe_mode = "refreshed"
        messages = [
            (
                f"Configured ETF forecasts {universe_mode} "
                f"as of {effective_as_of}: {universe_summary}. Output: {output}."
            )
        ]
        if include_candidates:
            candidate_data = fetch_candidate_prices(self.config, years=years)
            candidate_ids = list(candidate_data.candidates["instrument_id"].astype(str))
            candidate_output = FORECASTS_DIR / f"yfinance_candidate_forecasts_{candidate_data.effective_as_of:%Y%m%d}.csv"
            candidate_window = _calculation_window(
                reference_context, candidate_data.effective_as_of, candidate_data.prices
            )
            candidate_binding = (
                None
                if candidate_window is None
                else _price_snapshot_binding(candidate_data.prices, calculation_window=candidate_window)
            )
            if candidate_binding is None:
                messages.append(
                    "Candidate forecasts unavailable because the adjusted-price snapshot identity is unavailable; "
                    "no disk cache was accepted or published."
                )
                self.last_operation_succeeded = True
                return "\n".join(messages)
            write_candidate_price_snapshot(
                candidate_data.prices,
                candidate_binding,
                publish_guard=publish_guard,
            )
            if use_cache and candidate_output.exists() and _cache_matches_universe(
                candidate_output,
                universe_revision,
                settings_revision,
                reference_context.identity,
                candidate_binding,
                request_identity,
            ):
                try:
                    cached_payload = _read_bound_cache_payload(
                        candidate_output,
                        universe_revision,
                        settings_revision,
                        reference_context.identity,
                        candidate_binding,
                        request_identity,
                    )
                    if cached_payload is None:
                        raise ValueError("candidate forecast cache pair changed during read")
                    candidate_frame = pd.read_csv(BytesIO(cached_payload))
                except Exception:
                    record_cache_event("candidate_forecast", "invalidation", action_id="forecasts", detail="unreadable output")
                    candidate_frame = None
                if candidate_frame is not None:
                    record_cache_event("candidate_forecast", "hit", action_id="forecasts")
                    candidate_summary = _forecast_frame_status_summary(candidate_frame)
                    candidate_as_of = candidate_data.effective_as_of
                    candidate_mode = "reused from cache"
                else:
                    candidate_forecasts = forecast_service.run_forecasts(
                        candidate_data.effective_as_of,
                        candidate_ids,
                        candidate_data.prices,
                        output_path=candidate_output,
                        horizons=horizons,
                        publish_guard=publish_guard,
                        cache_request_identity=request_identity,
                        live_optional_models=live_optional_models,
                    )
                    candidate_summary = _forecast_status_summary(candidate_forecasts)
                    candidate_as_of = candidate_data.effective_as_of
                    candidate_mode = "refreshed"
            else:
                if use_cache and candidate_output.exists() and not _cache_matches_universe(
                    candidate_output,
                    universe_revision,
                    settings_revision,
                    reference_context.identity,
                    candidate_binding,
                    request_identity,
                ):
                    record_cache_event("candidate_forecast", "invalidation", action_id="forecasts", detail="universe revision changed or metadata missing")
                record_cache_event("candidate_forecast", "miss", action_id="forecasts")
                candidate_forecasts = forecast_service.run_forecasts(
                    candidate_data.effective_as_of,
                    candidate_ids,
                    candidate_data.prices,
                    output_path=candidate_output,
                    horizons=horizons,
                    publish_guard=publish_guard,
                    cache_request_identity=request_identity,
                    live_optional_models=live_optional_models,
                )
                candidate_summary = _forecast_status_summary(candidate_forecasts)
                candidate_as_of = candidate_data.effective_as_of
                candidate_mode = "refreshed"
            messages.append(
                (
                    f"Candidate forecasts {candidate_mode} as of {candidate_as_of}: "
                    f"{candidate_summary}. Output: {candidate_output}."
                )
            )
        self.last_operation_succeeded = True
        return "\n".join(messages)

    def import_local_file(
        self,
        path: Path,
        dataset_type: str = "prices",
        *,
        commit: bool = False,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> ProviderResult:
        result = ManualLocalFileProvider().import_file(path, dataset_type)
        if dataset_type == "prices" and result.ok and result.data is not None:
            report = validate_prices(result.data)
            if report.status == "Blocked":
                issues = "; ".join(issue.message for issue in report.issues if issue.severity == "block")
                return ProviderResult(result.provider_name, dataset_type, "error", f"Imported prices failed validation: {issues}", result.data, result.metadata)
            if commit:
                with publication_scope(publish_guard):
                    commit_result = commit_price_import(result)
                return ProviderResult(
                    result.provider_name,
                    dataset_type,
                    "ok",
                    (
                        f"{result.message} Validated and committed {commit_result.rows} rows. "
                        f"Raw copy: {commit_result.raw_path}. Clean prices: {commit_result.clean_path}. "
                        f"Previous snapshot: {commit_result.previous_snapshot_path or 'none'}."
                    ),
                    result.data,
                    result.metadata,
                )
        if dataset_type == "manual_news" and result.ok and result.data is not None:
            known_etfs = self.config.universe.enabled_ids
            validation = validate_manual_news(
                result.data,
                source_name=result.metadata.source_name if result.metadata else path.name,
                provider_or_manual_source=str(path),
                known_etfs=known_etfs,
            )
            if not validation.ok:
                return ProviderResult(
                    result.provider_name,
                    dataset_type,
                    "error",
                    f"Imported manual notes failed validation: {'; '.join(validation.errors)}",
                    result.data,
                    result.metadata,
                )
            if commit:
                with publication_scope(publish_guard):
                    commit_result = commit_manual_news_import(result, known_etfs=known_etfs)
                warning_suffix = f" Warnings: {'; '.join(commit_result.warnings)}" if commit_result.warnings else ""
                return ProviderResult(
                    result.provider_name,
                    dataset_type,
                    "ok",
                    (
                        f"{result.message} Validated and committed {commit_result.rows} manual notes. "
                        f"Raw copy: {commit_result.raw_path}. Clean notes: {commit_result.clean_path}. "
                        f"Previous snapshot: {commit_result.previous_snapshot_path or 'none'}. "
                        "Executable authority forced to false."
                        f"{warning_suffix}"
                    ),
                    validation.frame,
                    commit_result.metadata,
                )
            return ProviderResult(
                result.provider_name,
                dataset_type,
                "ok",
                f"{result.message} Manual notes validated. Executable authority will be forced to false on commit.",
                validation.frame,
                validation.metadata,
            )
        if dataset_type in {"etf_metadata", "etf_factsheet", "etf_factsheets", "etf_holdings"} and result.ok and result.data is not None:
            resolved_type = normalise_reference_dataset_type(dataset_type)
            context = self._reference_context()
            validation = validate_reference_dataset(
                result.data,
                resolved_type,
                known_etfs=context["known_etfs"],
                isin_to_etf_id=context["isin_to_etf_id"],
                ticker_to_etf_id=context["ticker_to_etf_id"],
                source_name=result.metadata.source_name if result.metadata else path.name,
                provider_or_manual_source=str(path),
            )
            if not validation.ok:
                return ProviderResult(
                    result.provider_name,
                    resolved_type,
                    "error",
                    f"Imported {resolved_type} failed validation: {'; '.join(validation.errors)}",
                    result.data,
                    result.metadata,
                )
            if commit:
                with publication_scope(publish_guard):
                    commit_result = commit_reference_import(
                        result,
                        resolved_type,
                        known_etfs=context["known_etfs"],
                        isin_to_etf_id=context["isin_to_etf_id"],
                        ticker_to_etf_id=context["ticker_to_etf_id"],
                    )
                warning_suffix = f" Warnings: {'; '.join(commit_result.warnings)}" if commit_result.warnings else ""
                return ProviderResult(
                    result.provider_name,
                    resolved_type,
                    "ok",
                    (
                        f"{result.message} Validated and committed {commit_result.rows} {resolved_type} rows. "
                        f"Raw copy: {commit_result.raw_path}. Clean data: {commit_result.clean_path}. "
                        f"Previous snapshot: {commit_result.previous_snapshot_path or 'none'}. "
                        f"Staleness: {commit_result.metadata.staleness_status}."
                        f"{warning_suffix}"
                    ),
                    validation.frame,
                    commit_result.metadata,
                )
            return ProviderResult(
                result.provider_name,
                resolved_type,
                "ok",
                f"{result.message} {resolved_type} validated. Staleness: {validation.metadata.staleness_status if validation.metadata else 'unknown'}.",
                validation.frame,
                validation.metadata,
            )
        if dataset_type == "fx" and result.ok and result.data is not None:
            validation = validate_fx_rates(
                result.data,
                source_name=result.metadata.source_name if result.metadata else path.name,
                provider_or_manual_source=str(path),
            )
            if not validation.ok:
                return ProviderResult(
                    result.provider_name,
                    dataset_type,
                    "error",
                    f"Imported FX rates failed validation: {'; '.join(validation.errors)}",
                    result.data,
                    result.metadata,
                )
            if commit:
                with publication_scope(publish_guard):
                    commit_result = commit_fx_import(result)
                warning_suffix = f" Warnings: {'; '.join(commit_result.warnings)}" if commit_result.warnings else ""
                return ProviderResult(
                    result.provider_name,
                    dataset_type,
                    "ok",
                    (
                        f"{result.message} Validated and committed {commit_result.rows} FX rows. "
                        f"Raw copy: {commit_result.raw_path}. Clean FX: {commit_result.clean_path}. "
                        f"Previous snapshot: {commit_result.previous_snapshot_path or 'none'}. "
                        f"Staleness: {commit_result.metadata.staleness_status}."
                        f"{warning_suffix}"
                    ),
                    validation.frame,
                    commit_result.metadata,
                )
            return ProviderResult(
                result.provider_name,
                dataset_type,
                "ok",
                f"{result.message} FX rates validated. Staleness: {validation.metadata.staleness_status if validation.metadata else 'unknown'}.",
                validation.frame,
                validation.metadata,
            )
        return result

    def _reference_context(self) -> dict[str, object]:
        etfs = self.config.universe.etfs
        return {
            "known_etfs": [etf.id for etf in etfs],
            "isin_to_etf_id": {etf.isin: etf.id for etf in etfs if etf.isin},
            "ticker_to_etf_id": {etf.ticker: etf.id for etf in etfs if etf.ticker},
        }

    def rollback_latest_price_import(
        self,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        try:
            try:
                rollback = rollback_price_store(publish_guard=publish_guard)
            except TypeError as exc:
                if "publish_guard" not in str(exc):
                    raise
                rollback = rollback_price_store()
        except FileNotFoundError as exc:
            return str(exc)

        restored = pd.read_parquet(rollback.compatibility_path)
        report = validate_prices(restored)
        if report.status == "Blocked":
            issues = "; ".join(issue.message for issue in report.issues if issue.severity == "block")
            return f"Rollback restored a snapshot, but validation is blocked: {issues}"
        return (
            f"Rolled back prices to {rollback.restored_snapshot_path}. "
            f"Rows: {rollback.rows}. Current replaced copy: {rollback.current_snapshot_path or 'none'}."
        )


class SignalService:
    def __init__(self, config: AppConfig):
        self.config = config

    def generate_signals(self, as_of_date: date | None = None, features: pd.DataFrame | None = None) -> list[SignalResult]:
        prices = load_prices()
        prices["date"] = pd.to_datetime(prices["date"]).dt.date
        effective_date = as_of_date or max(prices["date"])
        holdings = load_holdings()
        benchmark_reference = _benchmark_reference_snapshot_inputs(
            self.config,
            effective_date,
            holdings,
        )
        reference_context = _reference_context_from_inputs(
            benchmark_reference,
            purpose="comparison",
            analysis_id=f"signals:{pd.Timestamp(effective_date).date().isoformat()}",
        )
        calculation_window = _calculation_window(reference_context, effective_date, prices)
        price_binding = (
            None
            if calculation_window is None
            else _price_snapshot_binding(prices, calculation_window=calculation_window)
        )
        universe_revision = _current_universe_revision()
        settings_revision = current_settings_revision()
        request_identity = configured_forecast_request_identity(self.config)
        cached_features = (
            load_features(
                FEATURE_PARQUET,
                universe_revision=universe_revision,
                settings_revision=settings_revision,
                reference_identity=reference_context.identity,
                price_binding=price_binding,
            )
            if price_binding is not None
            else pd.DataFrame()
        )
        supplied_matches = (
            features is not None
            and price_binding is not None
            and _reference_identity_matches(
                features.attrs.get("reference_identity"),
                features.attrs.get("reference_identity_hash"),
                reference_context.identity,
            )
            and isinstance(features.attrs.get("price_binding"), Mapping)
            and _price_binding_matches(features.attrs["price_binding"], price_binding)
        )
        if supplied_matches and features is not None:
            feature_frame = features.copy()
            if reference_context.benchmark_data_id is None:
                _sanitize_unavailable_relative_features(feature_frame)
        elif not cached_features.empty:
            feature_frame = cached_features
        else:
            feature_frame = FeatureService(self.config, reference_context=reference_context).compute_features(
                effective_date,
                prices,
                reference_context=reference_context,
            )
        latest = latest_features(feature_frame, effective_date)
        report = DataService(self.config).validate_prices(prices, as_of_date=effective_date, holdings=holdings)
        status = model_availability(self.config)
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
        structure_caps = _load_structure_caps(self.config.universe.enabled_ids, effective_date)
        signals = generate_signals(
            self.config,
            latest,
            holdings,
            report,
            as_of_date=effective_date,
            toto_available=status["toto"],
            timesfm_available=status["timesfm"],
            forecast_scores=forecast_component_maps(forecasts),
            forecast_distributions=forecast_return_distributions(forecasts, decision_time=effective_date),
            structure_confidence_caps=structure_caps,
            historical_forecasts=load_forecast_history(),
            calibration_prices=prices,
            decision_time=pd.Timestamp(effective_date, tz="UTC"),
        )
        _run_decision_shadow_guard(
            self.config,
            signals,
            decision_time=effective_date,
            latest_features=latest,
            price_history=feature_frame,
        )
        return signals


def _run_decision_shadow_guard(
    config: AppConfig,
    signals: Sequence[SignalResult],
    *,
    decision_time: date,
    latest_features: pd.DataFrame | None = None,
    price_history: pd.DataFrame | None = None,
) -> None:
    """Publish decision v1 beside v3 without allowing shadow errors to escape."""

    newest_signal = latest_signal(signals)
    run_id = newest_signal.run_id if newest_signal is not None else None
    try:
        liquidity_reports = {}
        if price_history is not None:
            from etf_cockpit.features.etf_economics import calculate_etf_liquidity

            for instrument in config.universe.enabled_ids:
                try:
                    liquidity_reports[instrument] = calculate_etf_liquidity(
                        config, price_history, instrument, as_of=decision_time
                    )
                except Exception:
                    liquidity_reports[instrument] = None
        from etf_cockpit.analysis.decision.shadow_run import run_decision_shadow

        run_decision_shadow(
            config,
            signals,
            decision_time=decision_time,
            latest_features=latest_features,
            liquidity_reports=liquidity_reports,
        )
    except Exception as exc:
        try:
            append_jsonl(
                "decision_opportunity_shadow_failures.jsonl",
                "decision_opportunity_shadow_failed",
                {"reason_code": f"SHADOW_RUN_FAILED:{type(exc).__name__}"},
                run_id=run_id,
            )
        except Exception:
            pass


def _sanitize_unavailable_relative_features(features: pd.DataFrame) -> None:
    """Drop relative fields from an in-memory frame without canonical evidence."""

    for column in ("relative_strength_60d", "relative_strength_120d"):
        if column in features.columns:
            features[column] = float("nan")


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
