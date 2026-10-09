"""Data ingestion and refresh orchestration with validated commits (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from io import BytesIO
from pathlib import Path
import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import FORECASTS_DIR, ROOT
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.core.timing import record_cache_event
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.core.workflow import (
    PublicationScopeFactory,
    WorkflowTransitionError,
    publication_scope,
)
from etf_cockpit.core.versioning import current_settings_revision
from etf_cockpit.data.duckdb_store import (
    initialise_store,
    load_holdings,
    load_prices,
)
from etf_cockpit.data.fx_data import (
    commit_fx_import,
    fx_data_inventory,
    load_fx_rates,
    validate_fx_rates,
)
from etf_cockpit.data.import_pipeline import (
    commit_price_import,
    rollback_latest_price_import as rollback_price_store,
)
from etf_cockpit.data.manual_notes import (
    commit_manual_news_import,
    load_manual_news,
    validate_manual_news,
)
from etf_cockpit.data.providers import (
    GenericHTTPProvider,
    ManualLocalFileProvider,
    ProviderResult,
)
from etf_cockpit.data.reference_data import (
    commit_reference_import,
    normalise_reference_dataset_type,
    reference_data_inventory,
    validate_reference_dataset,
)
from etf_cockpit.data.sample_data import ensure_sample_files
from etf_cockpit.data.trade_candidate_analysis import (
    fetch_candidate_prices,
    refresh_candidate_analysis,
    write_candidate_price_snapshot,
)
from etf_cockpit.data.validation import (
    validate_holdings,
    validate_prices,
)
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.portfolio.risk import target_policy_issues
from etf_cockpit.application.derived_cache import (
    _cache_matches_universe,
    _calculation_window,
    _current_universe_revision,
    _forecast_request_identity,
    _price_snapshot_binding,
    _read_bound_cache_payload,
)
from etf_cockpit.application.reference_context import (
    _benchmark_reference_snapshot_inputs,
    _reference_context_from_inputs,
)
from etf_cockpit.application.forecast_service import (
    _config_with_optional_models_disabled,
    _forecast_frame_status_summary,
    _forecast_status_summary,
    ForecastService,
)


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
        result, quarantined = _quarantine_invalid_ohlc(result)
        report = validate_prices(result.data, as_of_date=end_date)
        # Vendor OHLC glitches are quarantined row by row above, and a short history is a per-instrument
        # signal gate the snapshot re-applies; neither should block committing every other instrument.
        commit_tolerated = {"insufficient_history"}
        block_issues = [
            f"{issue.etf_id}: {issue.message}" for issue in report.issues
            if issue.severity == "block" and issue.code not in commit_tolerated
        ]
        if block_issues:
            return "Yahoo Finance prices fetched but not committed because validation blocked them: " + "; ".join(block_issues)
        if quarantined is not None and not quarantined.empty:
            quarantine_path = ROOT / "data" / "quality" / f"price_quarantine_{end_date.isoformat()}.parquet"
            quarantine_path.parent.mkdir(parents=True, exist_ok=True)
            quarantined.to_parquet(quarantine_path, index=False)
            messages.append(f"Quarantined {len(quarantined)} invalid OHLC rows to {quarantine_path.name}.")
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


def _quarantine_invalid_ohlc(result):
    """Split vendor rows with impossible OHLC values off the import; return (clean result, quarantined rows)."""
    import dataclasses

    frame = result.data
    needed = {"open", "high", "low", "close"}
    if frame is None or not needed.issubset(frame.columns):
        return result, None
    bad = (
        (frame["open"] <= 0)
        | (frame["close"] <= 0)
        | (frame["high"] < frame["low"])
        | (frame["high"] < frame[["open", "close"]].max(axis=1))
        | (frame["low"] > frame[["open", "close"]].min(axis=1))
    )
    if not bad.any():
        return result, None
    quarantined = frame.loc[bad].copy()
    quarantined["quarantine_reason"] = "invalid_ohlc"
    return dataclasses.replace(result, data=frame.loc[~bad].reset_index(drop=True)), quarantined
