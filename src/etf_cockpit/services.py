from __future__ import annotations

from dataclasses import asdict, dataclass, field
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import date
import math
import json
from pathlib import Path

import pandas as pd

from etf_cockpit.backtest.engine import (
    BacktestDataUnavailableError,
    BacktestReport,
    backtest_input_checksum,
    quality_momentum_evidence_checksum,
    run_backtest,
)
from etf_cockpit.chatgpt_bridge.export_pack import export_review_pack
from etf_cockpit.chatgpt_bridge.import_audit import import_audit_json
from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAudit, ChatGPTAuditV2
from etf_cockpit.core.config import AppConfig, load_config
from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_bytes, atomic_write_group
from etf_cockpit.core.logging import append_jsonl, configure_logging
from etf_cockpit.core.paths import (
    BACKTESTS_DIR,
    ETF_BENCHMARK_TOTAL_RETURN_PATH,
    ETF_FUND_TOTAL_RETURN_PATH,
    FORECASTS_DIR,
    ensure_project_dirs,
)
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.core.timing import record_cache_event, timed_step
from etf_cockpit.core.types import DataQualityReport, ForecastResult, SignalResult
from etf_cockpit.core.workflow import PublicationScopeFactory, WorkflowTransitionError, publication_scope
from etf_cockpit.core.versioning import (
    current_settings_identity,
    current_settings_revision,
    ensure_run_manifest,
    settings_bound_run_id,
)
from etf_cockpit.data.duckdb_store import initialise_store, load_holdings, load_prices, write_features
from etf_cockpit.data.etf_economics import (
    ClosureProxyPolicy,
    EtfEconomicsObservation,
    TotalReturnEvidence,
    load_closure_proxy_policy,
    load_etf_economics_records,
    load_total_return_evidence,
)
from etf_cockpit.data.etf_structure import load_local_structural_evidence, structure_confidence_caps
from etf_cockpit.data.fx_data import commit_fx_import, fx_data_inventory, load_fx_rates, validate_fx_rates
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
from etf_cockpit.data.fundamentals import load_fundamental_evidence
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
from etf_cockpit.data.trade_candidate_analysis import fetch_candidate_prices, refresh_candidate_analysis
from etf_cockpit.data.validation import validate_holdings, validate_prices
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.data.universe_store import load_universe
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.forecast_scores import forecast_component_maps, forecast_return_distributions, load_latest_forecasts
from etf_cockpit.models.local_weights import LocalModelStatus
from etf_cockpit.models.registry import model_availability, model_diagnostics
from etf_cockpit.portfolio.risk import target_policy_issues
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
    ReferencePortfolioDefinition,
    VWCE_CANONICAL_ISIN,
    VWCE_CANONICAL_SHARE_CLASS,
    VwceAnchorEvidence,
    load_canonical_benchmark_registry,
    resolve_vwce_anchor,
)
from etf_cockpit.portfolio.sandbox import holdings_checksum
from etf_cockpit.signals.signal_pipeline import generate_signals
from etf_cockpit.signals.quality_momentum import FRAME_COLUMNS, QUALITY_MOMENTUM_VERSION


BENCHMARK_REFERENCE_REGISTRY_PATH: Path | None = None
_CANONICAL_REFERENCE_IDS = (
    "reference:equal_weight",
    "reference:maximum_diversification",
    "reference:no_trade",
)
# Holdings-derived portfolio totals are compared in EUR with a deliberately
# tight tolerance: one micro-euro absolute or one part per billion relative.
_NO_TRADE_TOTAL_REL_TOL = 1e-9
_NO_TRADE_TOTAL_ABS_TOL_EUR = 1e-6


def _holdings_imply_consistent_portfolio_total(
    weights: list[float], market_values: list[float],
) -> bool:
    """Require every positive-weight holding to imply one portfolio total."""

    implied_totals: list[float] = []
    for weight, market_value in zip(weights, market_values):
        if weight == 0.0:
            if market_value != 0.0:
                return False
            continue
        implied_total = market_value / weight
        if not math.isfinite(implied_total):
            return False
        implied_totals.append(implied_total)
    if not implied_totals:
        return True
    portfolio_total = implied_totals[0]
    if math.isclose(
        portfolio_total,
        0.0,
        rel_tol=0.0,
        abs_tol=_NO_TRADE_TOTAL_ABS_TOL_EUR,
    ):
        return False
    return all(
        math.isclose(
            implied_total,
            portfolio_total,
            rel_tol=_NO_TRADE_TOTAL_REL_TOL,
            abs_tol=_NO_TRADE_TOTAL_ABS_TOL_EUR,
        )
        for implied_total in implied_totals[1:]
    )


def _universe_cache_meta_path(path: Path) -> Path:
    return Path(f"{path}.meta.json")


def _current_universe_revision() -> str:
    try:
        return load_universe().revision
    except (OSError, ValueError, TypeError, KeyError):
        return ""


def _cache_matches_universe(path: Path, revision: str, settings_revision: str | None = None) -> bool:
    metadata_path = _universe_cache_meta_path(path)
    if not metadata_path.exists():
        return False
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    expected_settings = settings_revision or current_settings_revision()
    return (
        isinstance(payload, dict)
        and str(payload.get("universe_revision") or "") == revision
        and str(payload.get("settings_revision") or "") == expected_settings
    )


def _load_local_structural_evidence():
    return load_local_structural_evidence(
        registry_reader=read_document_registry,
        report_reader=read_etf_report_records,
        factsheet_path=ETF_METADATA_CLEAN_PATH,
        holdings_path=FUND_HOLDINGS_PATH,
    )


def _load_structure_caps(instrument_ids: object, decision_time: object) -> dict[str, float]:
    """Load local structural evidence once at the signal service boundary."""

    ids = [str(item) for item in instrument_ids] if instrument_ids is not None else []
    try:
        evidence = _load_local_structural_evidence()
        return structure_confidence_caps(
            ids,
            document_registry=evidence.document_registry,
            report_records=evidence.report_records,
            supplemental_rows=evidence.supplemental_rows,
            holdings=evidence.holdings,
            decision_time=decision_time,
        )
    except Exception:
        return {item: 0.0 for item in ids}


def _cached_structure_columns_match(
    signal_log: pd.DataFrame,
    structural_caps: pd.Series,
    structural_hashes: pd.Series,
    structure_evidence: object,
    allowed_instrument_ids: object,
) -> bool:
    """Validate cached structural identity without replaying once per row."""

    decision_times = pd.to_datetime(signal_log["date"], errors="coerce")
    raw_instrument_ids = signal_log["etf_id"]
    instrument_ids = raw_instrument_ids.astype(str).str.strip()
    invalid_instrument_ids = raw_instrument_ids.isna() | instrument_ids.str.lower().isin(
        {"", "<na>", "nan", "none", "null"}
    )
    allowed_ids = {
        str(item).strip()
        for item in (allowed_instrument_ids or ())
        if str(item).strip()
    }
    if (
        decision_times.isna().any()
        or invalid_instrument_ids.any()
        or not allowed_ids
        or not instrument_ids.isin(allowed_ids).all()
    ):
        return False
    evidence_channels = (
        structure_evidence.document_registry,
        structure_evidence.report_records,
        structure_evidence.supplemental_rows,
        structure_evidence.holdings,
    )
    if all(isinstance(channel, pd.DataFrame) and channel.empty for channel in evidence_channels):
        return bool(structural_caps.eq(0.0).all() and structural_hashes.eq("unavailable").all())

    replay_rows = pd.DataFrame(
        {
            "decision_date": decision_times.dt.date,
            "instrument_id": instrument_ids,
            "stored_cap": structural_caps,
            "stored_hash": structural_hashes,
        }
    )
    for decision_date, rows in replay_rows.groupby("decision_date", sort=True):
        expected_caps = structure_confidence_caps(
            sorted(rows["instrument_id"].unique()),
            document_registry=structure_evidence.document_registry,
            report_records=structure_evidence.report_records,
            supplemental_rows=structure_evidence.supplemental_rows,
            holdings=structure_evidence.holdings,
            decision_time=decision_date,
        )
        for row in rows.itertuples(index=False):
            expected_cap = float(expected_caps.get(row.instrument_id, 0.0))
            expected_hash = str(
                expected_caps.provenance.get(row.instrument_id, {}).get(
                    "structure_provenance_hash", "unavailable"
                )
            ).strip()
            if float(row.stored_cap) != expected_cap or row.stored_hash != expected_hash:
                return False
    return True


def _write_universe_cache_metadata(path: Path, revision: str, settings_revision: str | None = None) -> None:
    metadata_path = _universe_cache_meta_path(path)
    payload = json.dumps(
        {
            "schema_version": 2,
            "universe_revision": revision,
            "settings_revision": settings_revision or current_settings_revision(),
        },
        sort_keys=True,
    ).encode("utf-8")
    atomic_write_bytes(metadata_path, payload, lambda candidate: json.loads(candidate.read_text(encoding="utf-8")))


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
    # Revision of the canonical universe used to build cached derived data.
    universe_revision: str = ""
    etf_economics_records: tuple[EtfEconomicsObservation, ...] = ()
    etf_fund_total_return: TotalReturnEvidence | None = None
    etf_benchmark_total_return: TotalReturnEvidence | None = None
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
        forecast_config = self.config if live_optional_models else _config_with_optional_models_disabled(self.config)
        forecast_service = ForecastService(forecast_config)
        universe_revision = _current_universe_revision()
        output = FORECASTS_DIR / f"forecast_results_yfinance_{effective_as_of:%Y%m%d}.csv"
        if use_cache and output.exists() and _cache_matches_universe(output, universe_revision, settings_revision):
            try:
                universe_forecast_frame = pd.read_csv(output)
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
            candidate_output = FORECASTS_DIR / f"yfinance_candidate_forecasts_{effective_as_of:%Y%m%d}.csv"
            if use_cache and candidate_output.exists() and _cache_matches_universe(candidate_output, universe_revision, settings_revision):
                try:
                    candidate_frame = pd.read_csv(candidate_output)
                except Exception:
                    record_cache_event("candidate_forecast", "invalidation", action_id="forecasts", detail="unreadable output")
                    candidate_frame = None
                if candidate_frame is not None:
                    record_cache_event("candidate_forecast", "hit", action_id="forecasts")
                    candidate_summary = _forecast_frame_status_summary(candidate_frame)
                    candidate_as_of = effective_as_of
                    candidate_mode = "reused from cache"
                else:
                    record_cache_event("candidate_forecast", "miss", action_id="forecasts")
                    candidate_data = fetch_candidate_prices(self.config, years=years)
                    candidate_ids = list(candidate_data.candidates["instrument_id"].astype(str))
                    candidate_output = FORECASTS_DIR / f"yfinance_candidate_forecasts_{candidate_data.effective_as_of:%Y%m%d}.csv"
                    candidate_forecasts = forecast_service.run_forecasts(
                        candidate_data.effective_as_of,
                        candidate_ids,
                        candidate_data.prices,
                        output_path=candidate_output,
                        horizons=horizons,
                        publish_guard=publish_guard,
                    )
                    candidate_summary = _forecast_status_summary(candidate_forecasts)
                    candidate_as_of = candidate_data.effective_as_of
                    candidate_mode = "refreshed"
            else:
                if use_cache and candidate_output.exists() and not _cache_matches_universe(candidate_output, universe_revision, settings_revision):
                    record_cache_event("candidate_forecast", "invalidation", action_id="forecasts", detail="universe revision changed or metadata missing")
                record_cache_event("candidate_forecast", "miss", action_id="forecasts")
                candidate_data = fetch_candidate_prices(self.config, years=years)
                candidate_ids = list(candidate_data.candidates["instrument_id"].astype(str))
                candidate_output = FORECASTS_DIR / f"yfinance_candidate_forecasts_{candidate_data.effective_as_of:%Y%m%d}.csv"
                if use_cache and candidate_output.exists() and _cache_matches_universe(candidate_output, universe_revision, settings_revision):
                    record_cache_event("candidate_forecast", "hit", action_id="forecasts")
                    candidate_summary = _forecast_frame_status_summary(pd.read_csv(candidate_output))
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


class FeatureService:
    def __init__(self, config: AppConfig):
        self.config = config

    def compute_features(
        self,
        as_of_date: date | None = None,
        prices: pd.DataFrame | None = None,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> pd.DataFrame:
        settings_identity = current_settings_identity()
        frame = prices if prices is not None else load_prices()
        if as_of_date:
            frame = frame[pd.to_datetime(frame["date"]).dt.date <= as_of_date]
        benchmark = self.config.universe.enabled_ids[0] if self.config.universe.enabled_ids else None
        features = compute_features(frame, benchmark_etf_id=benchmark)
        run_id = settings_bound_run_id(
            f"features_{as_of_date.isoformat() if as_of_date else 'latest'}",
            settings_identity=settings_identity,
        )
        with publication_scope(publish_guard):
            ensure_run_manifest(
                run_id,
                ("schema:local-storage", "dataset:prices", "dataset:universe"),
                settings_identity=settings_identity,
            )
        with publication_scope(publish_guard):
            write_features(features)
        return features


class ForecastService:
    def __init__(self, config: AppConfig):
        self.config = config

    def run_forecasts(
        self,
        as_of_date: date,
        etf_ids: list[str],
        prices: pd.DataFrame | None = None,
        *,
        output_path: Path | None = None,
        horizons: list[int] | None = None,
        progress_callback: Callable[[str, int, int], None] | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> list[ForecastResult]:
        settings_identity = current_settings_identity()
        price_frame = prices if prices is not None else load_prices()
        price_frame = price_frame.copy()
        price_frame["date"] = pd.to_datetime(price_frame["date"])
        price_frame = price_frame[pd.to_datetime(price_frame["date"]).dt.date <= as_of_date]
        horizons = horizons or self.config.models.forecast_horizons_trading_days
        pivot = price_frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
        benchmark_id = self.config.universe.enabled_ids[0] if self.config.universe.enabled_ids else None
        benchmark_returns = pivot[benchmark_id].pct_change(fill_method=None).dropna() if benchmark_id in pivot else None
        forecasts: list[ForecastResult] = []
        run_id = settings_bound_run_id(
            f"forecast_{as_of_date:%Y%m%d}",
            settings_identity=settings_identity,
        )
        if progress_callback is not None:
            progress_callback("Running baseline forecasts", 1, 4)
        for etf_id in etf_ids:
            if etf_id not in pivot:
                continue
            series = pivot[etf_id].dropna()
            forecasts.extend(
                baseline_forecast(
                    etf_id,
                    series,
                    horizons,
                    as_of_date,
                    run_id=run_id,
                    benchmark_returns=benchmark_returns,
                )
            )
        if progress_callback is not None:
            progress_callback("Checking cached TimesFM forecasts", 2, 4)
        forecasts.extend(self._run_timesfm_forecasts(pivot, etf_ids, horizons, as_of_date, run_id))
        if progress_callback is not None:
            progress_callback("Checking cached Toto forecasts", 3, 4)
        forecasts.extend(self._run_toto_forecasts(price_frame, etf_ids, horizons, as_of_date, run_id))
        with publication_scope(publish_guard):
            ensure_run_manifest(
                run_id,
                (
                    "schema:local-storage",
                    "dataset:prices",
                    "policy:model-settings",
                    "formula:score-engine-v3",
                    "model:baseline",
                    "model:timesfm",
                    "model:toto",
                ),
                settings_identity=settings_identity,
            )
        if progress_callback is not None:
            progress_callback("Writing forecast outputs", 3, 4)
        self._write_forecasts(
            forecasts,
            as_of_date,
            output_path=output_path,
            settings_revision=str(settings_identity["settings_revision"]),
            publish_guard=publish_guard,
        )
        return forecasts

    def _run_timesfm_forecasts(
        self,
        pivot: pd.DataFrame,
        etf_ids: list[str],
        horizons: list[int],
        as_of_date: date,
        run_id: str,
    ) -> list[ForecastResult]:
        from etf_cockpit.models.timesfm_adapter import TimesFMAdapter

        adapter = TimesFMAdapter(self.config.models.runtime("timesfm"))
        forecasts: list[ForecastResult] = []
        try:
            for etf_id in etf_ids:
                if etf_id not in pivot:
                    continue
                forecasts.extend(
                    adapter.forecast_series(
                        pivot[etf_id].dropna(),
                        horizons,
                        etf_id=etf_id,
                        forecast_date=as_of_date,
                        run_id=run_id,
                    )
                )
        finally:
            adapter.unload_model()
        return forecasts

    def _run_toto_forecasts(
        self,
        price_frame: pd.DataFrame,
        etf_ids: list[str],
        horizons: list[int],
        as_of_date: date,
        run_id: str,
    ) -> list[ForecastResult]:
        from etf_cockpit.models.toto_adapter import TotoAdapter

        adapter = TotoAdapter(self.config.models.runtime("toto"))
        forecasts: list[ForecastResult] = []
        try:
            for etf_id in etf_ids:
                forecasts.extend(
                    adapter.forecast_etf(
                        etf_id,
                        as_of_date,
                        horizons,
                        prices=price_frame[["date", "etf_id", "adjusted_close"]],
                        run_id=run_id,
                    )
                )
        finally:
            adapter.unload_model()
        return forecasts

    def _write_forecasts(
        self,
        forecasts: list[ForecastResult],
        as_of_date: date,
        *,
        output_path: Path | None = None,
        settings_revision: str | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> None:
        output = output_path or FORECASTS_DIR / f"forecast_results_{as_of_date:%Y%m%d}.csv"
        payload = pd.DataFrame([_forecast_to_row(forecast) for forecast in forecasts]).to_csv(index=False).encode("utf-8")

        def validate(path: Path) -> None:
            _validate_csv(path)

        with timed_step("forecasts", "write_output"):
            with publication_scope(publish_guard):
                atomic_write_bytes(output, payload, validate)
        with publication_scope(publish_guard):
            _write_universe_cache_metadata(
                output,
                _current_universe_revision(),
                settings_revision or current_settings_revision(),
            )


class SignalService:
    def __init__(self, config: AppConfig):
        self.config = config

    def generate_signals(self, as_of_date: date | None = None, features: pd.DataFrame | None = None) -> list[SignalResult]:
        prices = load_prices()
        prices["date"] = pd.to_datetime(prices["date"]).dt.date
        effective_date = as_of_date or max(prices["date"])
        feature_frame = features if features is not None else FeatureService(self.config).compute_features(effective_date, prices)
        latest = latest_features(feature_frame, effective_date)
        holdings = load_holdings()
        report = DataService(self.config).validate_prices(prices, as_of_date=effective_date, holdings=holdings)
        status = model_availability(self.config)
        forecasts = load_latest_forecasts(universe_revision=_current_universe_revision())
        structure_caps = _load_structure_caps(self.config.universe.enabled_ids, effective_date)
        return generate_signals(
            self.config,
            latest,
            holdings,
            report,
            as_of_date=effective_date,
            toto_available=status["toto"],
            timesfm_available=status["timesfm"],
            forecast_scores=forecast_component_maps(forecasts),
            forecast_distributions=forecast_return_distributions(forecasts),
            structure_confidence_caps=structure_caps,
        )


def _forecast_to_row(forecast: ForecastResult) -> dict[str, object]:
    data = asdict(forecast)
    data["forecast_date"] = forecast.forecast_date.isoformat()
    return data


def _validate_csv(path: Path, *, index_col: int | None = None) -> None:
    # Empty trade/signal/forecast frames are valid unavailable artefacts.
    if path.stat().st_size:
        pd.read_csv(path, index_col=index_col)


def _forecast_status_summary(forecasts: list[ForecastResult]) -> str:
    if not forecasts:
        return "no rows"
    counts = Counter((forecast.model_name, forecast.status) for forecast in forecasts)
    return ", ".join(f"{model} {status} {count}" for (model, status), count in sorted(counts.items()))


def _forecast_frame_status_summary(frame: pd.DataFrame) -> str:
    if frame.empty or not {"model_name", "status"}.issubset(frame.columns):
        return "no rows"
    counts = frame.groupby(["model_name", "status"], dropna=False).size()
    return ", ".join(f"{model} {status} {count}" for (model, status), count in counts.sort_index().items())


def _config_with_optional_models_disabled(config: AppConfig) -> AppConfig:
    quick_config = config.model_copy(deep=True)
    for model_name in ("timesfm", "toto"):
        model_config = dict(quick_config.models.models.get(model_name, {}))
        model_config.update(
            {
                "enabled": False,
                "mode": "disabled",
            }
        )
        quick_config.models.models[model_name] = model_config
    return quick_config


class BacktestService:
    REQUIRED_RESULT_COLUMNS = {
        "return_hit_rate",
        "average_win_return",
        "average_loss_return",
        "payoff_ratio",
        "expected_value_per_period",
        "payoff_asymmetry_warning",
    }

    def __init__(self, config: AppConfig, *, universe_revision: str | None = None):
        self.config = config
        self.universe_revision = _current_universe_revision() if universe_revision is None else universe_revision

    def load_or_run_backtest(
        self,
        as_of_date: date | None = None,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> BacktestReport:
        cache_present = (BACKTESTS_DIR / "backtest_results.csv").exists() or (BACKTESTS_DIR / "equity_curves.csv").exists()
        with timed_step("backtest", "cache_read"):
            cached = self._load_cached_backtest(as_of_date)
        if cached is not None:
            record_cache_event("backtest", "hit", action_id="backtest")
            return cached
        if cache_present:
            record_cache_event("backtest", "invalidation", action_id="backtest", detail="unreadable or stale output")
        record_cache_event("backtest", "miss", action_id="backtest")
        return self.run_backtest(publish_guard=publish_guard)

    def run_backtest(self, *, publish_guard: PublicationScopeFactory | None = None) -> BacktestReport:
        settings_identity = current_settings_identity()
        prices = load_prices()
        fundamentals = load_fundamental_evidence()
        try:
            structure_evidence = _load_local_structural_evidence()
        except Exception:
            structure_evidence = None
        try:
            report = run_backtest(
                self.config,
                prices,
                fundamentals=fundamentals,
                structure_document_registry=(structure_evidence.document_registry if structure_evidence else None),
                structure_report_records=(structure_evidence.report_records if structure_evidence else None),
                structure_supplemental_rows=(structure_evidence.supplemental_rows if structure_evidence else None),
                structure_holdings=(structure_evidence.holdings if structure_evidence else None),
            )
        except BacktestDataUnavailableError as exc:
            return _empty_backtest_report(str(exc))
        run_id = settings_bound_run_id("backtest", settings_identity=settings_identity)
        with publication_scope(publish_guard):
            ensure_run_manifest(
                run_id,
                (
                    "schema:local-storage",
                    "dataset:prices",
                    "formula:score-engine-v3",
                    "policy:portfolio-targets",
                    "policy:risk-limits",
                    "policy:costs",
                    "model:baseline",
                ),
                settings_identity=settings_identity,
            )
        with publication_scope(publish_guard):
            BACKTESTS_DIR.mkdir(parents=True, exist_ok=True)
        requests = (
            AtomicWriteRequest(BACKTESTS_DIR / "backtest_results.csv", report.results.to_csv(index=False).encode("utf-8"), lambda path: _validate_csv(path)),
            AtomicWriteRequest(BACKTESTS_DIR / "equity_curves.csv", report.equity_curves.to_csv().encode("utf-8"), lambda path: _validate_csv(path, index_col=0)),
            AtomicWriteRequest(BACKTESTS_DIR / "trade_log.csv", report.trade_log.to_csv(index=False).encode("utf-8"), lambda path: _validate_csv(path)),
            AtomicWriteRequest(BACKTESTS_DIR / "signal_log.csv", report.signal_log.to_csv(index=False).encode("utf-8"), lambda path: _validate_csv(path)),
            AtomicWriteRequest(BACKTESTS_DIR / "quality_momentum_evidence.csv", report.quality_momentum_evidence.to_csv(index=False).encode("utf-8"), lambda path: _validate_csv(path)),
            AtomicWriteRequest(
                BACKTESTS_DIR / "backtest_metadata.json",
                json.dumps(report.metadata, default=str, sort_keys=True, indent=2).encode("utf-8"),
                lambda path: json.loads(path.read_text(encoding="utf-8")),
            ),
        )
        with timed_step("backtest", "write_outputs"):
            with publication_scope(publish_guard):
                atomic_write_group(requests)
        for output in (
            BACKTESTS_DIR / "backtest_results.csv",
            BACKTESTS_DIR / "equity_curves.csv",
            BACKTESTS_DIR / "signal_log.csv",
            BACKTESTS_DIR / "quality_momentum_evidence.csv",
        ):
            with publication_scope(publish_guard):
                _write_universe_cache_metadata(
                    output,
                    self.universe_revision,
                    str(settings_identity["settings_revision"]),
                )
        with publication_scope(publish_guard):
            append_jsonl("model_runs.jsonl", "backtest_completed", {"ai_added_value": report.ai_added_value})
        return report

    def _load_cached_backtest(self, as_of_date: date | None = None) -> BacktestReport | None:
        settings_revision = current_settings_revision()
        results_path = BACKTESTS_DIR / "backtest_results.csv"
        equity_path = BACKTESTS_DIR / "equity_curves.csv"
        trade_path = BACKTESTS_DIR / "trade_log.csv"
        signal_path = BACKTESTS_DIR / "signal_log.csv"
        metadata_path = BACKTESTS_DIR / "backtest_metadata.json"
        quality_evidence_path = BACKTESTS_DIR / "quality_momentum_evidence.csv"
        if not results_path.exists() or not equity_path.exists():
            return None
        if not _cache_matches_universe(
            results_path,
            self.universe_revision,
            settings_revision,
        ) or not _cache_matches_universe(
            equity_path,
            self.universe_revision,
            settings_revision,
        ):
            return None
        try:
            results = pd.read_csv(results_path)
            if results.empty:
                return None
            if not self.REQUIRED_RESULT_COLUMNS.issubset(results.columns):
                return None
            if "quality_momentum" not in set(results.get("strategy_name", ())):
                return None
            if as_of_date is not None and "end_date" in results.columns:
                end_dates = pd.to_datetime(results["end_date"], errors="coerce").dt.date.dropna()
                if end_dates.empty or max(end_dates) != as_of_date:
                    return None
            equity_curves = pd.read_csv(equity_path, index_col=0, parse_dates=True)
            trade_log = pd.read_csv(trade_path) if trade_path.exists() else pd.DataFrame()
            if not signal_path.exists():
                return None
            signal_log = pd.read_csv(signal_path)
            required_signal_columns = {
                "date",
                "etf_id",
                "structural_confidence_cap",
                "structural_provenance_hash",
            }
            if signal_log.empty or not required_signal_columns.issubset(signal_log.columns):
                return None
            structural_caps = pd.to_numeric(
                signal_log["structural_confidence_cap"], errors="coerce"
            )
            if structural_caps.isna().any() or not structural_caps.between(0.0, 1.0).all():
                return None
            structural_hashes = signal_log["structural_provenance_hash"].astype(str).str.strip()
            if structural_hashes.eq("").any() or structural_hashes.str.casefold().isin({"nan", "none"}).any():
                return None
            quality_momentum_evidence = pd.read_csv(quality_evidence_path) if quality_evidence_path.exists() else pd.DataFrame()
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            if not isinstance(metadata, dict):
                metadata = {}
            if metadata.get("quality_momentum_strategy_version") != QUALITY_MOMENTUM_VERSION:
                return None
            structure_evidence = _load_local_structural_evidence()
            if not _cached_structure_columns_match(
                signal_log,
                structural_caps,
                structural_hashes,
                structure_evidence,
                self.config.universe.enabled_ids,
            ):
                return None
            if metadata.get("input_checksum") != backtest_input_checksum(
                self.config,
                load_prices(),
                load_fundamental_evidence(),
                structure_document_registry=(structure_evidence.document_registry if structure_evidence else None),
                structure_report_records=(structure_evidence.report_records if structure_evidence else None),
                structure_supplemental_rows=(structure_evidence.supplemental_rows if structure_evidence else None),
                structure_holdings=(structure_evidence.holdings if structure_evidence else None),
            ):
                return None
            if not quality_evidence_path.exists():
                return None
            if set(FRAME_COLUMNS) - set(quality_momentum_evidence.columns):
                return None
            quality_momentum_evidence = quality_momentum_evidence.reindex(columns=FRAME_COLUMNS)
            if metadata.get("quality_momentum_evidence_checksum") != quality_momentum_evidence_checksum(
                quality_evidence_path.read_bytes()
            ):
                return None
            ai_added_value = False
            if {"strategy_name", "calmar"}.issubset(results.columns):
                momentum = results.loc[results["strategy_name"] == "momentum_only", "calmar"]
                signal = results.loc[results["strategy_name"] == "signal_strategy", "calmar"]
                if not momentum.empty and not signal.empty:
                    ai_added_value = bool(float(signal.iloc[0]) > float(momentum.iloc[0]) * 1.03)
            quality_values = results["backtest_quality"].dropna().astype(str) if "backtest_quality" in results else pd.Series(dtype=str)
            return BacktestReport(
                results=results,
                equity_curves=equity_curves,
                trade_log=trade_log,
                signal_log=signal_log,
                ai_added_value=ai_added_value,
                quality_label=quality_values.iloc[0] if not quality_values.empty else "low",
                quality_notes=[
                    "Loaded from cached local backtest output matching the current data date.",
                    "Use the Backtests page or diagnostics scripts to regenerate full backtest files after changing assumptions.",
                ],
                metadata=metadata,
                quality_momentum_evidence=quality_momentum_evidence,
            )
        except Exception:
            return None


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


def _benchmark_reference_snapshot_inputs(
    config: AppConfig,
    as_of: object,
    holdings: pd.DataFrame | None = None,
) -> dict[str, object]:
    unavailable: dict[str, object] = {
        "registry": CanonicalBenchmarkRegistry(),
        "instrument": None,
        "currency": None,
        "horizon_years": None,
        "start_date": None,
        "end_date": None,
        "decision_time": None,
        "reference_ids": (),
        "anchor": None,
        "listing_id": None,
    }
    try:
        registry = load_canonical_benchmark_registry(BENCHMARK_REFERENCE_REGISTRY_PATH)
        if any(item.portfolio_id == "reference:no_trade" for item in registry.reference_portfolios):
            registry = CanonicalBenchmarkRegistry(
                benchmarks=registry.benchmarks,
                cash_proxies=registry.cash_proxies,
                peer_sets=registry.peer_sets,
                reference_portfolios=tuple(
                    item
                    for item in registry.reference_portfolios
                    if item.portfolio_id != "reference:no_trade"
                ),
                vwce_anchors=registry.vwce_anchors,
            )
        unavailable["reference_ids"] = _CANONICAL_REFERENCE_IDS
        as_of_timestamp = pd.Timestamp(as_of)
        if pd.isna(as_of_timestamp):
            return unavailable
        end_date = as_of_timestamp.date()
        start_date = (as_of_timestamp - pd.DateOffset(years=1)).date()
        base_currency = config.targets.base_currency.strip().upper()
        decision_time = (
            pd.Timestamp(end_date, tz="UTC")
            + pd.Timedelta(hours=23, minutes=59, seconds=59)
        ).isoformat()
        no_trade = _current_portfolio_reference(
            config,
            holdings,
            as_of_date=end_date,
            start_date=start_date,
            decision_time=decision_time,
            currency=base_currency,
        )
        if no_trade is not None:
            registry = CanonicalBenchmarkRegistry(
                benchmarks=registry.benchmarks,
                cash_proxies=registry.cash_proxies,
                peer_sets=registry.peer_sets,
                reference_portfolios=(
                    registry.reference_portfolios + (no_trade,)
                ),
                vwce_anchors=registry.vwce_anchors,
            )
        configured = [
            item for item in config.universe.etfs
            if item.id == "VWCE" and item.isin == VWCE_CANONICAL_ISIN
        ]
        effective_cutoff = pd.Timestamp(start_date, tz="UTC")
        knowledge_cutoff = pd.Timestamp(decision_time)
        anchors = [
            item for item in registry.vwce_anchors
            if item.canonical_isin == VWCE_CANONICAL_ISIN
            and item.canonical_share_class_id == VWCE_CANONICAL_SHARE_CLASS
            and pd.Timestamp(item.effective_at) <= effective_cutoff
            and pd.Timestamp(item.known_at) <= knowledge_cutoff
        ]
        if len(configured) != 1 or not anchors:
            return {**unavailable, "registry": registry}
        vwce = configured[0]
        latest_effective = max(pd.Timestamp(item.effective_at) for item in anchors)
        anchors = [item for item in anchors if pd.Timestamp(item.effective_at) == latest_effective]
        latest_known = max(pd.Timestamp(item.known_at) for item in anchors)
        anchors = [item for item in anchors if pd.Timestamp(item.known_at) == latest_known]
        if len(anchors) != 1:
            return {**unavailable, "registry": registry}
        anchor = anchors[0]
        ticker = vwce.ticker.split(".", maxsplit=1)[0].upper()
        listing_ids = sorted({
            item.listing_id for item in anchor.listing_observations
            if item.ticker == ticker and item.currency == base_currency
        })
        if not listing_ids or start_date >= end_date:
            return {**unavailable, "registry": registry}
        resolutions = {
            listing_id: resolve_vwce_anchor(
                anchor,
                listing_id=listing_id,
                effective_date=start_date.isoformat(),
                decision_time=knowledge_cutoff.isoformat(),
                currency=base_currency,
                horizon_years=1.0,
            )
            for listing_id in listing_ids
        }
        available_listing_ids = [
            listing_id for listing_id, resolution in resolutions.items()
            if resolution.status == "available"
        ]
        if len(available_listing_ids) == 1:
            listing_id = available_listing_ids[0]
        elif len(available_listing_ids) > 1 or len(listing_ids) != 1:
            return {**unavailable, "registry": registry}
        else:
            listing_id = listing_ids[0]
        instrument = {
            "asset_class": vwce.asset_class,
            "country_region": vwce.region or "",
            "sector": vwce.sector or "",
            "currency": vwce.currency,
        }
        return {
            "registry": registry,
            "instrument": instrument,
            "currency": base_currency,
            "horizon_years": 1.0,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "decision_time": knowledge_cutoff.isoformat(),
            "reference_ids": _CANONICAL_REFERENCE_IDS,
            "anchor": anchor,
            "listing_id": listing_id,
        }
    except (BenchmarkReferenceError, OSError, TypeError, ValueError, AttributeError):
        return unavailable


def _current_portfolio_reference(
    config: AppConfig,
    holdings: pd.DataFrame | None,
    *,
    as_of_date: date,
    start_date: date,
    decision_time: str,
    currency: str,
) -> ReferencePortfolioDefinition | None:
    """Build a point-in-time no-trade reference from exact holdings evidence."""

    if not isinstance(holdings, pd.DataFrame) or holdings.empty:
        return None
    instrument_column = "etf_id" if "etf_id" in holdings.columns else "instrument_id"
    required = {instrument_column, "current_weight", "market_value_eur", "as_of_date"}
    if not required.issubset(holdings.columns):
        return None
    try:
        dates = pd.to_datetime(holdings["as_of_date"], errors="coerce")
        if dates.isna().any() or set(dates.dt.date) != {as_of_date}:
            return None
        ids = [str(value).strip() for value in holdings[instrument_column].tolist()]
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            return None
        configured_ids = set(config.universe.configured_enabled_ids)
        if any(value not in configured_ids for value in ids):
            return None
        raw_weights = holdings["current_weight"].tolist()
        if any(isinstance(value, bool) for value in raw_weights):
            return None
        weights = pd.to_numeric(holdings["current_weight"], errors="coerce").tolist()
        if any(
            not math.isfinite(float(value))
            or float(value) < 0
            or float(value) > 1
            for value in weights
        ):
            return None
        raw_market_values = holdings["market_value_eur"].tolist()
        if any(isinstance(value, bool) for value in raw_market_values):
            return None
        market_values = pd.to_numeric(holdings["market_value_eur"], errors="coerce").tolist()
        if any(
            not math.isfinite(float(value))
            or float(value) < 0
            for value in market_values
        ):
            return None
        total = math.fsum(float(value) for value in weights)
        if not math.isfinite(total) or total > 1.0:
            return None
        if not _holdings_imply_consistent_portfolio_total(
            [float(value) for value in weights],
            [float(value) for value in market_values],
        ):
            return None
        knowledge_columns = tuple(
            column
            for column in ("known_at", "imported_at", "available_at")
            if column in holdings.columns
        )
        if not knowledge_columns:
            return None
        effective_time = pd.Timestamp(as_of_date, tz="UTC")
        cutoff_time = pd.Timestamp(decision_time)
        source_knowledge_times: list[pd.Timestamp] = []
        for _, row in holdings.iterrows():
            row_knowledge_times: list[pd.Timestamp] = []
            for column in knowledge_columns:
                raw_value = row[column]
                if raw_value is None or pd.isna(raw_value):
                    continue
                parsed = pd.to_datetime(raw_value, errors="coerce")
                if pd.isna(parsed) or getattr(parsed, "tzinfo", None) is None:
                    return None
                parsed_utc = pd.to_datetime(parsed, errors="coerce", utc=True)
                if pd.isna(parsed_utc):
                    return None
                row_knowledge_times.append(pd.Timestamp(parsed_utc))
            if not row_knowledge_times:
                return None
            row_knowledge_time = max(row_knowledge_times)
            if row_knowledge_time < effective_time or row_knowledge_time > cutoff_time:
                return None
            source_knowledge_times.append(row_knowledge_time)
        cash_id = f"cash:{currency}"
        if cash_id in ids:
            return None
        current_weights = {
            instrument_id: float(weight)
            for instrument_id, weight in sorted(zip(ids, weights), key=lambda item: item[0])
        }
        current_weights[cash_id] = float(1.0 - total)
        source_hash = holdings_checksum(holdings)
        source_knowledge_time = max(source_knowledge_times).isoformat()
        return ReferencePortfolioDefinition(
            portfolio_id="reference:no_trade",
            version="1.0.0",
            method="no_trade",
            constituent_instrument_ids=tuple(current_weights),
            methodology="Hold the exact current positions and implied base-currency cash with zero proposed turnover.",
            effective_at=f"{as_of_date.isoformat()}T00:00:00+00:00",
            known_at=source_knowledge_time,
            current_weights=current_weights,
            currency=currency,
            minimum_horizon_years=0.1,
            maximum_horizon_years=50.0,
            start_date=start_date.isoformat(),
            end_date=as_of_date.isoformat(),
            source_hashes=(source_hash,),
        )
    except (ArithmeticError, TypeError, ValueError, KeyError):
        return None


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
    feature_service = FeatureService(config)
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
    forecasts = load_latest_forecasts(universe_revision=universe_revision)
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
    backtest = (
        _empty_backtest_report("Backtest skipped because no clean prices exist for the current two-tier universe yet.")
        if prices.empty
        else BacktestService(config, universe_revision=universe_revision).load_or_run_backtest(
            data_report.as_of_date,
            publish_guard=publish_guard,
        )
    )
    etf_economics_records = load_etf_economics_records()
    etf_fund_total_return = load_total_return_evidence(ETF_FUND_TOTAL_RETURN_PATH)
    etf_benchmark_total_return = load_total_return_evidence(ETF_BENCHMARK_TOTAL_RETURN_PATH)
    etf_closure_policy = load_closure_proxy_policy()
    benchmark_reference = _benchmark_reference_snapshot_inputs(
        config,
        data_report.as_of_date,
        holdings_source,
    )
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


def _empty_backtest_report(note: str) -> BacktestReport:
    columns = [
        "strategy_name",
        "cagr",
        "volatility",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
        "turnover",
        "cost_drag",
        "n_walk_forward_periods",
        "trade_count",
        "return_hit_rate",
        "average_win_return",
        "average_loss_return",
        "payoff_ratio",
        "expected_value_per_period",
        "payoff_asymmetry_warning",
        "average_trade_eur",
        "turnover_annualised",
        "worst_12m_return",
        "backtest_quality",
        "train_periods",
        "validation_periods",
        "test_periods",
        "median_holding_period_days",
        "probabilistic_sharpe",
        "deflated_sharpe",
        "pbo_probability_backtest_overfitting",
        "parameter_sensitivity_status",
        "worst_1d_return",
        "worst_5d_return",
        "worst_10d_return",
        "worst_drawdown_start",
        "worst_drawdown_end",
        "loss_cluster_max_days",
        "largest_negative_period_return",
        "overfitting_warning",
        "data_quality_status",
        "benchmark_strategy",
    ]
    return BacktestReport(
        results=pd.DataFrame(columns=columns),
        equity_curves=pd.DataFrame(),
        trade_log=pd.DataFrame(),
        signal_log=pd.DataFrame(),
        ai_added_value=False,
        quality_label="not_available",
        quality_notes=[note],
        metadata={
            "data_status": "unavailable",
            "not_enough_data_policy": "fail_closed",
            "forward_fill_used": False,
            "same_bar_execution_avoided": True,
        },
    )
