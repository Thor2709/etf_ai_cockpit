from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import Counter
from datetime import date
import json
from pathlib import Path

import pandas as pd

from etf_cockpit.backtest.engine import BacktestDataUnavailableError, BacktestReport, run_backtest
from etf_cockpit.chatgpt_bridge.export_pack import export_review_pack
from etf_cockpit.chatgpt_bridge.import_audit import import_audit_json
from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAudit, ChatGPTAuditV2
from etf_cockpit.core.config import AppConfig, load_config
from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_bytes, atomic_write_group
from etf_cockpit.core.logging import append_jsonl, configure_logging
from etf_cockpit.core.paths import BACKTESTS_DIR, FORECASTS_DIR, ensure_project_dirs
from etf_cockpit.core.timing import record_cache_event, timed_step
from etf_cockpit.core.types import DataQualityReport, ForecastResult, SignalResult
from etf_cockpit.core.versioning import ensure_run_manifest
from etf_cockpit.data.duckdb_store import initialise_store, load_holdings, load_prices, write_features
from etf_cockpit.data.fx_data import commit_fx_import, fx_data_inventory, load_fx_rates, validate_fx_rates
from etf_cockpit.data.import_pipeline import commit_price_import, rollback_latest_price_import as rollback_price_store
from etf_cockpit.data.manual_notes import commit_manual_news_import, load_manual_news, validate_manual_news
from etf_cockpit.data.providers import GenericHTTPProvider, ManualLocalFileProvider, ProviderResult
from etf_cockpit.data.reference_data import (
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
from etf_cockpit.signals.signal_pipeline import generate_signals


def _universe_cache_meta_path(path: Path) -> Path:
    return Path(f"{path}.meta.json")


def _current_universe_revision() -> str:
    try:
        return load_universe().revision
    except (OSError, ValueError, TypeError, KeyError):
        return ""


def _cache_matches_universe(path: Path, revision: str) -> bool:
    metadata_path = _universe_cache_meta_path(path)
    if not metadata_path.exists():
        return False
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(payload, dict) and str(payload.get("universe_revision") or "") == revision


def _write_universe_cache_metadata(path: Path, revision: str) -> None:
    metadata_path = _universe_cache_meta_path(path)
    payload = json.dumps({"schema_version": 1, "universe_revision": revision}, sort_keys=True).encode("utf-8")
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


class DataService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.last_operation_succeeded = True

    def update_prices(self, force_sample: bool = False) -> None:
        ensure_sample_files(self.config, force=force_sample)
        initialise_store(self.config, force_sample=force_sample)

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

    def api_update_status(self) -> str:
        section = self.config.data_providers.section("prices")
        if section.active_provider.lower() == "yfinance":
            return self.refresh_yfinance_data()
        result = GenericHTTPProvider(section).fetch_prices([], date.today(), date.today())
        return result.message

    def refresh_yfinance_data(self, *, years: int = 5, include_reference_data: bool = True) -> str:
        self.last_operation_succeeded = False
        end_date = date.today()
        start_date = end_date.replace(year=end_date.year - years)
        provider = YFinanceProvider.from_config(self.config)
        messages: list[str] = []

        result = provider.fetch_prices([], start_date, end_date)
        if not result.ok or result.data is None:
            return result.message
        report = validate_prices(result.data, as_of_date=end_date)
        block_issues = [issue.message for issue in report.issues if issue.severity == "block"]
        if block_issues:
            return "Yahoo Finance prices fetched but not committed because validation blocked them: " + "; ".join(block_issues)
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
                    messages.append(f"{dataset_type}: {reference_result.message}")
                    continue
                try:
                    reference_commit = commit_reference_import(
                        reference_result,
                        dataset_type,
                        known_etfs=context["known_etfs"],
                        isin_to_etf_id=context["isin_to_etf_id"],
                        ticker_to_etf_id=context["ticker_to_etf_id"],
                    )
                except Exception as exc:
                    messages.append(f"{dataset_type}: fetched but not committed because validation failed: {exc}")
                    continue
                warning_suffix = f" Warnings: {'; '.join(reference_commit.warnings)}" if reference_commit.warnings else ""
                messages.append(
                    (
                        f"{reference_result.message} Validated and committed {reference_commit.rows} {dataset_type} rows. "
                        f"Clean data: {reference_commit.clean_path}.{warning_suffix}"
                    )
                )
        self.last_operation_succeeded = True
        return "\n".join(messages)

    def run_yfinance_candidate_analysis(self, *, years: int = 5) -> str:
        result = refresh_candidate_analysis(self.config, years=years)
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
    ) -> str:
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
        if use_cache and output.exists() and _cache_matches_universe(output, universe_revision):
            try:
                universe_forecast_frame = pd.read_csv(output)
            except Exception:
                record_cache_event("forecast", "invalidation", action_id="forecasts", detail="unreadable output")
                universe_forecast_frame = None
            if universe_forecast_frame is not None:
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
            )
            universe_summary = _forecast_status_summary(universe_forecasts)
            universe_mode = "refreshed"
        if universe_mode == "refreshed" and output.exists():
            _write_universe_cache_metadata(output, universe_revision)
        messages = [
            (
                f"Configured ETF forecasts {universe_mode} "
                f"as of {effective_as_of}: {universe_summary}. Output: {output}."
            )
        ]
        if include_candidates:
            candidate_output = FORECASTS_DIR / f"yfinance_candidate_forecasts_{effective_as_of:%Y%m%d}.csv"
            if use_cache and candidate_output.exists() and _cache_matches_universe(candidate_output, universe_revision):
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
                    )
                    candidate_summary = _forecast_status_summary(candidate_forecasts)
                    candidate_as_of = candidate_data.effective_as_of
                    candidate_mode = "refreshed"
            else:
                if use_cache and candidate_output.exists() and not _cache_matches_universe(candidate_output, universe_revision):
                    record_cache_event("candidate_forecast", "invalidation", action_id="forecasts", detail="universe revision changed or metadata missing")
                record_cache_event("candidate_forecast", "miss", action_id="forecasts")
                candidate_data = fetch_candidate_prices(self.config, years=years)
                candidate_ids = list(candidate_data.candidates["instrument_id"].astype(str))
                candidate_output = FORECASTS_DIR / f"yfinance_candidate_forecasts_{candidate_data.effective_as_of:%Y%m%d}.csv"
                if use_cache and candidate_output.exists() and _cache_matches_universe(candidate_output, universe_revision):
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
                    )
                    candidate_summary = _forecast_status_summary(candidate_forecasts)
                    candidate_as_of = candidate_data.effective_as_of
                    candidate_mode = "refreshed"
            if candidate_mode == "refreshed" and candidate_output.exists():
                _write_universe_cache_metadata(candidate_output, universe_revision)
            messages.append(
                (
                    f"Candidate forecasts {candidate_mode} as of {candidate_as_of}: "
                    f"{candidate_summary}. Output: {candidate_output}."
                )
            )
        return "\n".join(messages)

    def import_local_file(self, path: Path, dataset_type: str = "prices", *, commit: bool = False) -> ProviderResult:
        result = ManualLocalFileProvider().import_file(path, dataset_type)
        if dataset_type == "prices" and result.ok and result.data is not None:
            report = validate_prices(result.data)
            if report.status == "Blocked":
                issues = "; ".join(issue.message for issue in report.issues if issue.severity == "block")
                return ProviderResult(result.provider_name, dataset_type, "error", f"Imported prices failed validation: {issues}", result.data, result.metadata)
            if commit:
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

    def rollback_latest_price_import(self) -> str:
        try:
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

    def compute_features(self, as_of_date: date | None = None, prices: pd.DataFrame | None = None) -> pd.DataFrame:
        frame = prices if prices is not None else load_prices()
        if as_of_date:
            frame = frame[pd.to_datetime(frame["date"]).dt.date <= as_of_date]
        benchmark = self.config.universe.enabled_ids[0] if self.config.universe.enabled_ids else None
        features = compute_features(frame, benchmark_etf_id=benchmark)
        write_features(features)
        ensure_run_manifest(
            f"features_{as_of_date.isoformat() if as_of_date else 'latest'}",
            ("schema:local-storage", "dataset:prices", "dataset:universe"),
        )
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
    ) -> list[ForecastResult]:
        price_frame = prices if prices is not None else load_prices()
        price_frame = price_frame.copy()
        price_frame["date"] = pd.to_datetime(price_frame["date"])
        price_frame = price_frame[pd.to_datetime(price_frame["date"]).dt.date <= as_of_date]
        horizons = horizons or self.config.models.forecast_horizons_trading_days
        pivot = price_frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
        benchmark_id = self.config.universe.enabled_ids[0] if self.config.universe.enabled_ids else None
        benchmark_returns = pivot[benchmark_id].pct_change(fill_method=None).dropna() if benchmark_id in pivot else None
        forecasts: list[ForecastResult] = []
        run_id = f"forecast_{as_of_date:%Y%m%d}"
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
        forecasts.extend(self._run_timesfm_forecasts(pivot, etf_ids, horizons, as_of_date, run_id))
        forecasts.extend(self._run_toto_forecasts(price_frame, etf_ids, horizons, as_of_date, run_id))
        self._write_forecasts(forecasts, as_of_date, output_path=output_path)
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

    def _write_forecasts(self, forecasts: list[ForecastResult], as_of_date: date, *, output_path: Path | None = None) -> None:
        output = output_path or FORECASTS_DIR / f"forecast_results_{as_of_date:%Y%m%d}.csv"
        payload = pd.DataFrame([_forecast_to_row(forecast) for forecast in forecasts]).to_csv(index=False).encode("utf-8")

        def validate(path: Path) -> None:
            _validate_csv(path)

        with timed_step("forecasts", "write_output"):
            atomic_write_bytes(output, payload, validate)


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

    def load_or_run_backtest(self, as_of_date: date | None = None) -> BacktestReport:
        cache_present = (BACKTESTS_DIR / "backtest_results.csv").exists() or (BACKTESTS_DIR / "equity_curves.csv").exists()
        with timed_step("backtest", "cache_read"):
            cached = self._load_cached_backtest(as_of_date)
        if cached is not None:
            record_cache_event("backtest", "hit", action_id="backtest")
            return cached
        if cache_present:
            record_cache_event("backtest", "invalidation", action_id="backtest", detail="unreadable or stale output")
        record_cache_event("backtest", "miss", action_id="backtest")
        return self.run_backtest()

    def run_backtest(self) -> BacktestReport:
        try:
            report = run_backtest(self.config, load_prices())
        except BacktestDataUnavailableError as exc:
            return _empty_backtest_report(str(exc))
        BACKTESTS_DIR.mkdir(parents=True, exist_ok=True)
        requests = (
            AtomicWriteRequest(BACKTESTS_DIR / "backtest_results.csv", report.results.to_csv(index=False).encode("utf-8"), lambda path: _validate_csv(path)),
            AtomicWriteRequest(BACKTESTS_DIR / "equity_curves.csv", report.equity_curves.to_csv().encode("utf-8"), lambda path: _validate_csv(path, index_col=0)),
            AtomicWriteRequest(BACKTESTS_DIR / "trade_log.csv", report.trade_log.to_csv(index=False).encode("utf-8"), lambda path: _validate_csv(path)),
            AtomicWriteRequest(BACKTESTS_DIR / "signal_log.csv", report.signal_log.to_csv(index=False).encode("utf-8"), lambda path: _validate_csv(path)),
            AtomicWriteRequest(
                BACKTESTS_DIR / "backtest_metadata.json",
                json.dumps(report.metadata, default=str, sort_keys=True, indent=2).encode("utf-8"),
                lambda path: json.loads(path.read_text(encoding="utf-8")),
            ),
        )
        with timed_step("backtest", "write_outputs"):
            atomic_write_group(requests)
        for output in (
            BACKTESTS_DIR / "backtest_results.csv",
            BACKTESTS_DIR / "equity_curves.csv",
            BACKTESTS_DIR / "signal_log.csv",
        ):
            _write_universe_cache_metadata(output, self.universe_revision)
        ensure_run_manifest(
            "backtest",
            (
                "schema:local-storage",
                "dataset:prices",
                "formula:score-engine-v3",
                "policy:portfolio-targets",
                "policy:risk-limits",
                "policy:costs",
                "model:baseline",
            ),
        )
        append_jsonl("model_runs.jsonl", "backtest_completed", {"ai_added_value": report.ai_added_value})
        return report

    def _load_cached_backtest(self, as_of_date: date | None = None) -> BacktestReport | None:
        results_path = BACKTESTS_DIR / "backtest_results.csv"
        equity_path = BACKTESTS_DIR / "equity_curves.csv"
        trade_path = BACKTESTS_DIR / "trade_log.csv"
        signal_path = BACKTESTS_DIR / "signal_log.csv"
        metadata_path = BACKTESTS_DIR / "backtest_metadata.json"
        if not results_path.exists() or not equity_path.exists():
            return None
        if not _cache_matches_universe(results_path, self.universe_revision) or not _cache_matches_universe(equity_path, self.universe_revision):
            return None
        try:
            results = pd.read_csv(results_path)
            if results.empty:
                return None
            if not self.REQUIRED_RESULT_COLUMNS.issubset(results.columns):
                return None
            if as_of_date is not None and "end_date" in results.columns:
                end_dates = pd.to_datetime(results["end_date"], errors="coerce").dt.date.dropna()
                if end_dates.empty or max(end_dates) != as_of_date:
                    return None
            equity_curves = pd.read_csv(equity_path, index_col=0, parse_dates=True)
            trade_log = pd.read_csv(trade_path) if trade_path.exists() else pd.DataFrame()
            signal_log = pd.read_csv(signal_path) if signal_path.exists() else pd.DataFrame()
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            if not isinstance(metadata, dict):
                metadata = {}
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
    ) -> Path:
        return export_review_pack(self.config, holdings, features, signals, backtest, as_of_date=as_of_date, data_report=data_report)

    def import_audit_json(self, path: Path) -> ChatGPTAudit | ChatGPTAuditV2:
        return import_audit_json(path, self.config)


def build_snapshot(force_sample: bool = False) -> CockpitSnapshot:
    with timed_step("snapshot", "build"):
        return _build_snapshot(force_sample=force_sample)


def _build_snapshot(force_sample: bool = False) -> CockpitSnapshot:
    configure_logging()
    ensure_project_dirs()
    config = load_config()
    universe_revision = _current_universe_revision()
    data_service = DataService(config)
    data_service.update_prices(force_sample=force_sample)
    current_ids = set(config.universe.enabled_ids)
    prices = data_service.load_prices()
    if not prices.empty and "etf_id" in prices:
        prices = prices[prices["etf_id"].astype(str).isin(current_ids)].copy()
    holdings = load_holdings()
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
        features = feature_service.compute_features(data_report.as_of_date, prices)
        latest = latest_features(features, data_report.as_of_date)
    status = model_availability(config)
    inventory = model_diagnostics(config)
    forecasts = load_latest_forecasts(universe_revision=universe_revision)
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
        )
    )
    backtest = _empty_backtest_report("Backtest skipped because no clean prices exist for the current two-tier universe yet.") if prices.empty else BacktestService(config, universe_revision=universe_revision).load_or_run_backtest(data_report.as_of_date)
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
