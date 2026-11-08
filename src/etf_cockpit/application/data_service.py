"""Data ingestion and refresh orchestration with validated commits (application; ADR-0002)."""

from __future__ import annotations

import dataclasses
import re
import threading
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import CLEAN_DIR, FORECASTS_DIR, ROOT
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.core.timing import record_cache_event
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.core.values import years_before
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
    analyse_candidate_prices,
    fetch_candidate_prices,
    load_stored_candidate_prices,
    refresh_candidate_analysis,
    write_candidate_price_snapshot,
)
from etf_cockpit.data.price_quarantine import quarantine_invalid_ohlc as _quarantine_invalid_ohlc
from etf_cockpit.data.validation import (
    validate_holdings,
    validate_prices,
)
from etf_cockpit.data.provenance import sha256_dataframe
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


ADJ_CLOSE_RTOL = 1e-6
INCREMENTAL_OVERLAP_DAYS = 14
FX_OVERLAP_DAYS = 14


def _normalised_price_dates(frame: pd.DataFrame) -> pd.Series:
    if "date" not in frame.columns:
        return pd.Series(pd.NaT, index=frame.index, dtype=object)
    return pd.to_datetime(frame["date"], errors="coerce").dt.date


def _adjusted_price_basis_matches(stored: pd.DataFrame, fetched: pd.DataFrame) -> bool:
    if not {"date", "adjusted_close"}.issubset(stored.columns) or not {"date", "adjusted_close"}.issubset(fetched.columns):
        return False
    old = stored[["date", "adjusted_close"]].copy()
    new = fetched[["date", "adjusted_close"]].copy()
    old["date"] = _normalised_price_dates(old)
    new["date"] = _normalised_price_dates(new)
    shared = new.merge(old, on="date", how="inner", suffixes=("_fetched", "_stored"))
    if shared.empty:
        return False
    fetched_adjusted = pd.to_numeric(shared["adjusted_close_fetched"], errors="coerce")
    stored_adjusted = pd.to_numeric(shared["adjusted_close_stored"], errors="coerce")
    relative_difference = (fetched_adjusted / stored_adjusted - 1).abs()
    return bool((relative_difference <= ADJ_CLOSE_RTOL).fillna(False).all())


def _currency_basis_mismatch(stored: pd.DataFrame, fetched: pd.DataFrame) -> bool:
    if "currency" not in stored.columns or "currency" not in fetched.columns:
        return False
    stored_currencies = stored["currency"].dropna().astype(str).str.strip()
    if stored_currencies.nunique() > 1:
        return True
    if "date" not in stored.columns or "date" not in fetched.columns:
        return False
    old = stored[["date", "currency"]].copy()
    new = fetched[["date", "currency"]].copy()
    old["date"] = _normalised_price_dates(old)
    new["date"] = _normalised_price_dates(new)
    old = old.dropna(subset=["date"])
    new = new.dropna(subset=["date"])
    shared = new.merge(old, on="date", how="inner", suffixes=("_fetched", "_stored"))
    shared = shared.dropna(subset=["currency_fetched", "currency_stored"])
    fetched_labels = shared["currency_fetched"].astype(str).str.strip()
    stored_labels = shared["currency_stored"].astype(str).str.strip()
    return bool(fetched_labels.ne(stored_labels).any())


def _incremental_full_reason(stored: pd.DataFrame, fetched: pd.DataFrame) -> str | None:
    if _currency_basis_mismatch(stored, fetched):
        return "currency mismatch"
    if "date" not in stored.columns or "date" not in fetched.columns:
        return "no overlap"
    stored_dates = set(_normalised_price_dates(stored).dropna())
    fetched_dates = set(_normalised_price_dates(fetched).dropna())
    if not stored_dates.intersection(fetched_dates):
        return "no overlap"
    if "adjusted_close" not in stored.columns or "adjusted_close" not in fetched.columns:
        return "adjusted mismatch"
    if not _adjusted_price_basis_matches(stored, fetched):
        return "adjusted mismatch"
    return None


def _read_clean_price_store() -> pd.DataFrame:
    path = CLEAN_DIR / "prices.parquet"
    try:
        return pd.read_parquet(path) if path.is_file() else pd.DataFrame()
    except Exception:
        # An unreadable store cannot safely anchor a short-window merge.
        return pd.DataFrame()


def _fx_pair_series(frame: pd.DataFrame) -> pd.Series:
    if "pair" in frame.columns:
        return frame["pair"].fillna("").astype(str).str.strip().str.upper()
    if {"base_currency", "quote_currency"}.issubset(frame.columns):
        return (
            frame["base_currency"].fillna("").astype(str).str.strip().str.upper()
            + "/"
            + frame["quote_currency"].fillna("").astype(str).str.strip().str.upper()
        )
    return pd.Series("", index=frame.index, dtype=object)


def _fx_date_series(frame: pd.DataFrame) -> pd.Series:
    column = next((name for name in ("as_of_date", "date", "rate_date") if name in frame.columns), None)
    if column is None:
        return pd.Series(pd.NaT, index=frame.index, dtype=object)
    return pd.to_datetime(frame[column], errors="coerce").dt.date


def _read_clean_fx_store() -> pd.DataFrame:
    path = CLEAN_DIR / "fx.parquet"
    return pd.read_parquet(path) if path.is_file() else pd.DataFrame()


def _refresh_yfinance_fx(
    provider: YFinanceProvider,
    config: AppConfig,
    *,
    years: int,
    end_date: date,
    publish_guard: PublicationScopeFactory | None,
) -> list[str]:
    base_currency = str(config.targets.base_currency).strip().upper()
    currencies = sorted(
        {
            str(instrument.currency).strip().upper()
            for instrument in config.universe.etfs
            if str(instrument.currency or "").strip()
        }
        - {base_currency}
    )
    pairs = [f"{currency}/{base_currency}" for currency in currencies]
    if not pairs:
        return []

    try:
        stored = _read_clean_fx_store()
    except Exception:
        return ["FX not refreshed: " + ", ".join(pairs) + "."]
    stored_pairs = _fx_pair_series(stored)
    stored_dates = _fx_date_series(stored)
    fallback_start = years_before(end_date, years)
    pair_windows: dict[date, list[str]] = {}
    for pair in pairs:
        pair_dates = stored_dates.loc[stored_pairs.eq(pair)].dropna()
        start = max(pair_dates) - timedelta(days=FX_OVERLAP_DAYS) if not pair_dates.empty else fallback_start
        pair_windows.setdefault(start, []).append(pair)

    failed_pairs: set[str] = set()
    fetched_parts: list[pd.DataFrame] = []
    successful_template: ProviderResult | None = None
    for start, window_pairs in pair_windows.items():
        try:
            result = provider.fetch_fx(window_pairs, start, end_date)
        except WorkflowTransitionError:
            raise
        except Exception:
            failed_pairs.update(window_pairs)
            continue
        if not result.ok or result.data is None:
            failed_pairs.update(window_pairs)
            continue

        result_pairs = _fx_pair_series(result.data)
        reported_failures = set(re.findall(r"\b([A-Z]{3}/[A-Z]{3}):", str(result.message).upper()))
        for pair in window_pairs:
            pair_rows = result.data.loc[result_pairs.eq(pair)].copy()
            if pair in reported_failures or pair_rows.empty:
                failed_pairs.add(pair)
                continue
            try:
                validation = validate_fx_rates(
                    pair_rows,
                    source_name=result.metadata.source_name if result.metadata else result.provider_name,
                    provider_or_manual_source=result.provider_name,
                )
            except Exception:
                failed_pairs.add(pair)
                continue
            if not validation.ok:
                failed_pairs.add(pair)
                continue
            fetched_parts.append(pair_rows)
            if successful_template is None:
                successful_template = result

    if fetched_parts and successful_template is not None:
        fetched = pd.concat(fetched_parts, ignore_index=True, sort=False)
        fetched_pairs = _fx_pair_series(fetched)
        fetched_dates = _fx_date_series(fetched)
        parts: list[pd.DataFrame] = []
        if not stored.empty:
            for pair in sorted(set(stored_pairs)):
                old_rows = stored.loc[stored_pairs.eq(pair)].copy()
                if pair not in pairs or pair in failed_pairs:
                    parts.append(old_rows)
                    continue
                replacement_dates = set(fetched_dates.loc[fetched_pairs.eq(pair)].dropna())
                keep_old = ~stored_dates.loc[old_rows.index].isin(replacement_dates)
                parts.append(old_rows.loc[keep_old])
        parts.append(fetched)
        merged = pd.concat(parts, ignore_index=True, sort=False)
        fx_result = dataclasses.replace(
            successful_template,
            status="ok",
            message=f"Fetched and merged FX rates for {len(set(fetched_pairs))} pairs.",
            data=merged,
        )
        try:
            with publication_scope(publish_guard):
                commit_fx_import(fx_result)
        except WorkflowTransitionError:
            raise
        except Exception:
            failed_pairs.update(pairs)

    messages: list[str] = []
    if failed_pairs:
        messages.append("FX not refreshed: " + ", ".join(sorted(failed_pairs)) + ".")
    return messages


def _merge_incremental_price_result(
    provider: YFinanceProvider,
    window_result: ProviderResult,
    *,
    stored: pd.DataFrame,
    expected_ids: tuple[str, ...] | None,
    window_start: date,
    start_date: date,
    end_date: date,
) -> tuple[ProviderResult, tuple[str, ...]]:
    carried = _carry_forward_failed_instruments(window_result, expected_ids=expected_ids)
    partial_missing = tuple(getattr(carried, "missing_ids", ()))
    if partial_missing and carried.data is not None:
        carried = dataclasses.replace(carried, status="ok")
    if not carried.ok or carried.data is None:
        return carried, partial_missing

    window_data = window_result.data.copy() if window_result.data is not None else pd.DataFrame()
    if "etf_id" not in window_data.columns:
        return carried, partial_missing
    window_data["date"] = _normalised_price_dates(window_data)
    stored_data = stored.copy()
    if "date" in stored_data.columns:
        stored_data["date"] = _normalised_price_dates(stored_data)
    window_ids = set(window_data["etf_id"].astype(str))
    not_returned_ids = tuple(sorted(set(expected_ids or ()) - window_ids))

    carried_data = carried.data.copy()
    if "etf_id" in carried_data.columns:
        preserved = carried_data[~carried_data["etf_id"].astype(str).isin(window_ids)].copy()
    else:
        preserved = carried_data.iloc[0:0].copy()
    # Keep the original stored rows for every instrument omitted by the window fetch.
    preserved_ids = set(preserved["etf_id"].astype(str)) if "etf_id" in preserved.columns else set()
    if "etf_id" in stored_data.columns:
        missing_from_carry = stored_data[
            ~stored_data["etf_id"].astype(str).isin(window_ids | preserved_ids)
        ]
        if not missing_from_carry.empty:
            preserved = pd.concat([preserved, missing_from_carry], ignore_index=True)

    incremental_ids: list[str] = []
    full_ids: list[str] = []
    full_reason_counts = {"no overlap": 0, "adjusted mismatch": 0, "currency mismatch": 0}
    for instrument_id in sorted(window_ids):
        old_rows = (
            stored_data[stored_data["etf_id"].astype(str).eq(instrument_id)].copy()
            if "etf_id" in stored_data.columns
            else stored_data.iloc[0:0].copy()
        )
        new_rows = window_data[window_data["etf_id"].astype(str).eq(instrument_id)].copy()
        full_reason = _incremental_full_reason(old_rows, new_rows)
        if full_reason is None:
            incremental_ids.append(instrument_id)
        else:
            full_ids.append(instrument_id)
            full_reason_counts[full_reason] += 1

    full_data = pd.DataFrame()
    failed_full_ids: set[str] = set()
    if full_ids:
        try:
            full_result = provider.fetch_prices(full_ids, start_date, end_date)
        except WorkflowTransitionError:
            raise
        except Exception:
            failed_full_ids.update(full_ids)
        else:
            if full_result.data is not None and "etf_id" in full_result.data.columns:
                full_data = full_result.data.copy()
                full_data["date"] = _normalised_price_dates(full_data)
                full_data = full_data[full_data["etf_id"].astype(str).isin(full_ids)]
            else:
                full_data = pd.DataFrame(columns=window_data.columns)
            if not full_result.ok:
                failed_full_ids = set(_FAILED_SYMBOL.findall(str(full_result.message))) & set(full_ids)
                if not failed_full_ids:
                    failed_full_ids = set(full_ids)
                full_data = full_data[~full_data["etf_id"].astype(str).isin(failed_full_ids)]

    parts = [preserved] if not preserved.empty else []
    for instrument_id in sorted(window_ids):
        old_rows = (
            stored_data[stored_data["etf_id"].astype(str).eq(instrument_id)].copy()
            if "etf_id" in stored_data.columns
            else stored_data.iloc[0:0].copy()
        )
        new_rows = window_data[window_data["etf_id"].astype(str).eq(instrument_id)].copy()
        if instrument_id in incremental_ids:
            old_dates = _normalised_price_dates(old_rows)
            new_dates = set(_normalised_price_dates(new_rows).dropna())
            keep_old = old_dates.isna() | old_dates.lt(window_start) | (
                old_dates.ge(window_start) & ~old_dates.isin(new_dates)
            )
            old_rows = old_rows.loc[keep_old]
            parts.extend((old_rows, new_rows))
            continue

        refreshed_rows = full_data[full_data["etf_id"].astype(str).eq(instrument_id)] if "etf_id" in full_data.columns else full_data
        # A failed full refetch must not mix its window rows with the stored adjustment basis.
        parts.append(refreshed_rows if not refreshed_rows.empty else old_rows)

    merged = pd.concat(parts, ignore_index=True) if parts else window_data.iloc[0:0].copy()
    if "date" in merged.columns:
        merged_dates = _normalised_price_dates(merged)
        in_span = merged_dates.isna() | merged_dates.ge(start_date)
        merged = merged.loc[in_span].copy()
        merged["date"] = merged_dates.loc[in_span]
    if {"etf_id", "date"}.issubset(merged.columns):
        merged = merged.sort_values(["etf_id", "date"], kind="mergesort", na_position="last").reset_index(drop=True)

    summary = (
        f"Incremental refresh: {len(incremental_ids)} incremental instruments, "
        f"{len(full_ids)} full refetches, {len(not_returned_ids)} not returned. "
        f"Full refetch reasons: {full_reason_counts['no overlap']} no overlap, "
        f"{full_reason_counts['adjusted mismatch']} adjusted mismatch, "
        f"{full_reason_counts['currency mismatch']} currency mismatch."
    )
    if "etf_id" in full_data.columns:
        failed_full_ids.update(set(full_ids) - set(full_data["etf_id"].astype(str)))
    else:
        failed_full_ids.update(full_ids)
    if failed_full_ids:
        summary += " Full refetch unavailable for: " + ", ".join(sorted(failed_full_ids)) + "."
    stored_ids = set(stored_data["etf_id"].astype(str)) if "etf_id" in stored_data.columns else set()
    missing_after_full = tuple(sorted(set(partial_missing) | (failed_full_ids - stored_ids)))
    metadata = dataclasses.replace(carried.metadata, checksum=sha256_dataframe(merged)) if carried.metadata else None
    message = f"{carried.message} {summary}"
    if missing_after_full:
        result = PartialProviderResult(
            carried.provider_name,
            carried.dataset_type,
            "ok",
            message,
            merged,
            metadata,
            missing_ids=missing_after_full,
        )
    else:
        result = dataclasses.replace(carried, status="ok", message=message, data=merged, metadata=metadata)
    return result, missing_after_full


class DataService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.last_operation_succeeded = True
        self.last_operation_status = "available"
        self.last_operation_reason = ""

    def update_prices(
        self,
        force_sample: bool = False,
        *,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> None:
        ensure_sample_files(
            self.config, force=force_sample, allow_synthetic=self.config.data.allow_synthetic_sample_data,
            publish_guard=publish_guard,
        )
        initialise_store(self.config, force_sample=force_sample, publish_guard=publish_guard)
        prices = load_prices(config=self.config)
        self.last_operation_succeeded = not prices.empty
        self.last_operation_status = "available" if self.last_operation_succeeded else "unavailable"
        self.last_operation_reason = str(prices.attrs.get("reason", "")) if prices.empty else ""

    def load_prices(self, etf_ids: list[str] | None = None, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        prices = load_prices(config=self.config)
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
        report = validate_prices(prices if prices is not None else self.load_prices(), as_of_date=as_of_date, config=self.config)
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
        prices = self.load_prices()
        if prices.empty and prices.attrs.get("status") == "unavailable":
            return f"unavailable: {prices.attrs['reason']}"
        report = self.validate_prices(holdings=load_holdings(config=self.config))
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
        incremental: bool = False,
        include_fundamentals: bool = True,
        include_fx: bool = False,
    ) -> str:
        self.last_operation_succeeded = False
        end_date = date.today()
        start_date = years_before(end_date, years)
        provider = YFinanceProvider.from_config(self.config)
        messages: list[str] = []
        incremental_window_start: date | None = None
        if incremental:
            stored_snapshot = _read_clean_price_store()
            if not stored_snapshot.empty and "date" in stored_snapshot.columns:
                valid_dates = _normalised_price_dates(stored_snapshot).dropna()
                if not valid_dates.empty:
                    latest_stored_date = max(valid_dates)
                    incremental_window_start = max(
                        start_date,
                        latest_stored_date - timedelta(days=INCREMENTAL_OVERLAP_DAYS),
                    )
        result = provider.fetch_prices([], incremental_window_start or start_date, end_date)
        symbol_map = getattr(provider, "_symbol_map", None)
        expected_ids = tuple(symbol_map([])) if callable(symbol_map) else None
        # Merge-with-stored and commit are one critical section: two concurrent partial refreshes
        # must not both start from the same stored snapshot and overwrite each other's rows.
        with _PRICE_REFRESH_LOCK:
            if incremental_window_start is not None:
                stored = _read_clean_price_store()
                if stored.empty:
                    result = provider.fetch_prices([], start_date, end_date)
                    incremental_window_start = None
                else:
                    result, partial_missing = _merge_incremental_price_result(
                        provider,
                        result,
                        stored=stored,
                        expected_ids=expected_ids,
                        window_start=incremental_window_start,
                        start_date=start_date,
                        end_date=end_date,
                    )
            if incremental_window_start is None:
                result = _carry_forward_failed_instruments(result, expected_ids=expected_ids)
                partial_missing = tuple(getattr(result, "missing_ids", ()))
                if partial_missing and result.data is not None:
                    result = dataclasses.replace(result, status="ok")  # fresh + stored rows are real data; success stays False
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
                quarantine_path = _unused_quarantine_path(ROOT / "data" / "quality", end_date)
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
        if partial_missing:
            messages.insert(0, "PARTIAL refresh, not ok: no price data for " + ", ".join(sorted(partial_missing)) + ".")

        if include_fx:
            messages.extend(
                _refresh_yfinance_fx(
                    provider,
                    self.config,
                    years=years,
                    end_date=end_date,
                    publish_guard=publish_guard,
                )
            )

        if include_reference_data:
            from etf_cockpit.data.etf_e1_fetch import fetch_etf_e1_reference_data

            context = self._reference_context()
            reference_results, source_messages = fetch_etf_e1_reference_data(
                self.config, provider, checkpoint=lambda: _cancellation_checkpoint(publish_guard)
            )
            messages.extend(redact_text(message) for message in source_messages)
            for dataset_type, reference_result in reference_results:
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
        if include_fundamentals:
            messages.append(_refresh_stock_fundamentals(self.config, publish_guard))
        else:
            messages.append("Stock fundamentals skipped (weekly job).")
        from etf_cockpit.data.holdings_registry import collect_daily

        try:
            for status in collect_daily(ROOT, publish_guard=publish_guard):
                messages.append("iShares holdings: " + ", ".join(f"{key}={value}" for key, value in status.items()))
        except WorkflowTransitionError:
            raise
        except Exception as exc:
            messages.append(f"iShares holdings unavailable ({type(exc).__name__}).")
        self.last_operation_succeeded = True
        return "\n".join(messages)

    def run_stored_candidate_analysis(
        self,
        *,
        years: int = 5,
        identifiers: Sequence[str] | None = None,
        root: Path = ROOT,
    ) -> dict[str, object]:
        """Run the canonical price analysis from verified local evidence without fetching."""

        data = load_stored_candidate_prices(root=root, years=years, identifiers=identifiers)
        report = analyse_candidate_prices(data.candidates, data.prices)
        return {
            "rows": report.astype(object).where(pd.notna(report), None).to_dict(orient="records"),
            "effective_as_of": data.effective_as_of.isoformat(),
            "source_message": data.source_message,
        }

    def run_yfinance_candidate_analysis(
        self,
        *,
        years: int = 5,
        identifiers: Sequence[str] | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        result = refresh_candidate_analysis(
            self.config, years=years, identifiers=identifiers, publish_guard=publish_guard,
        )
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
        prices = load_prices(config=self.config)
        if not prices.empty:
            # Bind to the enabled universe, exactly like the snapshot and score consumers do.
            prices = prices[prices["etf_id"].astype(str).isin(set(self.config.universe.enabled_ids))]
        if prices.empty:
            return "No clean yfinance prices are available. Refresh yfinance data first."
        prices = prices.copy()
        prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
        effective_as_of = prices["date"].max().date()
        reference_inputs = _benchmark_reference_snapshot_inputs(
            self.config,
            effective_as_of,
            load_holdings(config=self.config),
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
                    promotion_prices=prices,
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
                promotion_prices=prices,
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
            try:
                candidate_data = fetch_candidate_prices(self.config, years=years)
            except RuntimeError as exc:
                # Candidate forecasts are optional extras; the configured forecasts above stand.
                messages.append(f"Candidate forecasts skipped: {redact_text(str(exc))[:300]}")
                self.last_operation_succeeded = True
                return "\n".join(messages)
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
                        promotion_prices=prices,
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
                    promotion_prices=prices,
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


_PRICE_REFRESH_LOCK = threading.Lock()
_FAILED_SYMBOL = re.compile(r"(?:^|[;.]\s*)([^\s/;:]+)/[^\s:;]+: ")


@dataclasses.dataclass(frozen=True)
class PartialProviderResult(ProviderResult):
    """A refresh in which configured instruments have neither fresh nor stored prices: never ok."""

    missing_ids: tuple[str, ...] = ()


def _unused_quarantine_path(directory: Path, day: date) -> Path:
    """A same-day quarantine never overwrites an earlier one."""

    path = directory / f"price_quarantine_{day.isoformat()}.parquet"
    counter = 1
    while path.exists():
        counter += 1
        path = directory / f"price_quarantine_{day.isoformat()}_{counter}.parquet"
    return path


def _carry_forward_failed_instruments(
    result: ProviderResult,
    *,
    clean_path: Path | None = None,
    expected_ids: tuple[str, ...] | None = None,
) -> ProviderResult:
    """One instrument the provider could not return must not block every other refresh.

    The price store is replaced on commit, so the instruments missing from a partial fetch keep
    their stored history unchanged (they turn stale and the staleness gate reports them) instead
    of being dropped. Nothing is filled or estimated. A configured instrument with neither fresh
    nor stored prices makes the result a `PartialProviderResult` (status unavailable), never ok."""

    if result.ok or result.data is None or result.data.empty:
        return result
    path = clean_path or CLEAN_DIR / "prices.parquet"
    fetched = set(result.data["etf_id"].astype(str))
    stored = pd.read_parquet(path) if path.is_file() else pd.DataFrame(columns=["etf_id"])
    stored_ids = set(stored["etf_id"].astype(str))
    kept = stored[~stored["etf_id"].astype(str).isin(fetched)]
    data = pd.concat([result.data, kept], ignore_index=True) if not kept.empty else result.data
    kept_ids = sorted(set(kept["etf_id"].astype(str)))
    wanted = set(expected_ids) if expected_ids is not None else set(_FAILED_SYMBOL.findall(str(result.message)))
    missing = tuple(sorted(wanted - fetched - stored_ids))
    message = (
        f"Downloaded fresh prices for {len(fetched)} instruments. Not refreshed, stored history kept: "
        + (", ".join(kept_ids) if kept_ids else "none (no stored history)")
        + ". Provider detail: "
        + str(result.message).replace("Partial refresh rejected; no incomplete Yahoo Finance price set was committed. ", "")
    )
    metadata = dataclasses.replace(result.metadata, checksum=sha256_dataframe(data)) if result.metadata else None
    if missing:
        return PartialProviderResult(
            result.provider_name,
            result.dataset_type,
            "unavailable",
            message + " No data at all for: " + ", ".join(missing) + ".",
            data,
            metadata,
            missing_ids=missing,
        )
    return ProviderResult(result.provider_name, result.dataset_type, "ok", message, data, metadata)


def _refresh_stock_fundamentals(config: AppConfig, publish_guard: PublicationScopeFactory | None) -> str:
    """Normal-stock fundamentals ride along with the price refresh; a failure never blocks prices."""

    from etf_cockpit.application.stock_service import refresh_universe_stock_fundamentals

    try:
        with publication_scope(publish_guard):
            report = refresh_universe_stock_fundamentals(config)
    except WorkflowTransitionError:
        raise  # a user cancellation must reach the workflow, never become a soft message
    except Exception as exc:  # read-only, best-effort source; the reason is shown, prices stand
        return f"Stock fundamentals not refreshed: {type(exc).__name__}: {redact_text(str(exc))[:200]}"
    missing = f" Without data: {', '.join(sorted(report.failures))}." if report.failures else ""
    return f"Stock fundamentals refreshed: {report.rows_added} new rows.{missing}"


def _cancellation_checkpoint(publish_guard: PublicationScopeFactory | None) -> None:
    """Raise the workflow's cancellation error between long network steps (no-op otherwise)."""

    with publication_scope(publish_guard):
        pass
