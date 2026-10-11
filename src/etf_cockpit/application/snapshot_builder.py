"""Cockpit snapshot type and in-memory snapshot assembly from data, features, signals and backtests (application; ADR-0002)."""

from __future__ import annotations

from datetime import datetime, timezone

from collections.abc import Mapping
from dataclasses import (
    dataclass,
    field,
    replace,
)
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable
import pandas as pd

if TYPE_CHECKING:
    from etf_cockpit.backtest.engine import BacktestReport
from etf_cockpit.core.config import (
    AppConfig,
    load_config,
)
from etf_cockpit.core.logging import configure_logging
from etf_cockpit.core.paths import FORECASTS_DIR, ensure_project_dirs
from etf_cockpit.core.session_log import log_event
from etf_cockpit.core.timing import timed_step
from etf_cockpit.core.types import (
    DataQualityReport,
    SignalResult,
)
from etf_cockpit.core.workflow import PublicationScopeFactory
from etf_cockpit.data.duckdb_store import load_holdings
from etf_cockpit.data.etf_economics import (
    ClosureProxyPolicy,
    EtfEconomicsObservation,
    TotalReturnEvidence,
)
from etf_cockpit.data.trade_candidate_analysis import load_candidate_price_binding, load_candidate_price_snapshot
from etf_cockpit.features.feature_pipeline import latest_features
from etf_cockpit.models.forecast_scores import (
    configured_forecast_request_identity,
    forecast_component_maps,
    forecast_return_distributions,
    load_latest_forecasts,
)
from etf_cockpit.models.local_weights import LocalModelStatus
from etf_cockpit.models.registry import (
    model_availability,
    model_diagnostics,
)
from etf_cockpit.portfolio.benchmark_reference_contract import (
    CanonicalBenchmarkRegistry,
    VwceAnchorEvidence,
)
from etf_cockpit.signals.signal_pipeline import generate_signals
from etf_cockpit.application.derived_cache import (
    _calculation_window,
    _current_universe_revision,
    _price_snapshot_binding,
)
from etf_cockpit.application.structural_evidence import _load_structure_caps
from etf_cockpit.application.reference_context import (
    _benchmark_reference_snapshot_inputs,
    _reference_context_from_inputs,
)
from etf_cockpit.application.economics_inputs import _etf_economics_snapshot_inputs
from etf_cockpit.application.feature_service import FeatureService
from etf_cockpit.application.data_service import DataService
from etf_cockpit.application.signal_service import _run_decision_shadow_guard

_STARTUP_WRITE_LOCK = threading.RLock()
_BACKTEST_LOCK = threading.Lock()  # module-level so snapshots stay deep-copyable


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
    backtest: BacktestReport | None
    model_status: dict[str, bool]
    model_inventory: list[LocalModelStatus]
    _backtest_loader: Callable[[], BacktestReport] | None = field(default=None, repr=False, compare=False)
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
    # When this live snapshot was built: facts fetched before it (e.g. ETF TER/holdings fetched after
    # the last price) are known to its views. Replays set an explicit decision time instead.
    facts_known_at: str | None = None
    benchmark_reference_portfolio_ids: tuple[str, ...] = ()
    vwce_anchor_evidence: VwceAnchorEvidence | None = None
    vwce_listing_id: str | None = None
    vwce_conversion_evidence: Mapping[str, object] | None = None

    def __getattribute__(self, name: str):
        # ``backtest`` is loaded lazily (startup speed); every reader still gets the report.
        if name == "backtest":
            return object.__getattribute__(self, "ensure_backtest")()
        return object.__getattribute__(self, name)

    def ensure_backtest(self) -> BacktestReport | None:
        """Load the persisted report or calculate it once when a consumer needs it."""

        get = object.__getattribute__
        if get(self, "backtest") is not None or get(self, "_backtest_loader") is None:
            return get(self, "backtest")
        with _STARTUP_WRITE_LOCK:
            with _BACKTEST_LOCK:
                if get(self, "backtest") is None and get(self, "_backtest_loader") is not None:
                    self.backtest = get(self, "_backtest_loader")()
                return get(self, "backtest")


def build_snapshot(
    force_sample: bool = False,
    *,
    publish_guard: PublicationScopeFactory | None = None,
) -> CockpitSnapshot:
    with _STARTUP_WRITE_LOCK:
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
    candidate_prices = load_candidate_price_snapshot()
    if not candidate_prices.empty and {"etf_id", "date"}.issubset(candidate_prices.columns):
        existing_ids = set(prices.get("etf_id", pd.Series(dtype=str)).astype(str))
        candidate_ids = current_ids - existing_ids
        candidate_prices = candidate_prices.loc[candidate_prices["etf_id"].astype(str).isin(candidate_ids)].copy()
        if not candidate_prices.empty:
            prices = pd.concat([prices, candidate_prices], ignore_index=True, sort=False)
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
    if forecasts.empty:
        forecasts = _load_legacy_forecasts(
            data_report.as_of_date,
            allowed_ids=current_ids.intersection(set(prices.get("etf_id", pd.Series(dtype=str)).astype(str))),
        )
    structure_caps = _load_structure_caps(config.universe.enabled_ids, data_report.as_of_date)
    signals = (
        []
        if latest.empty
        else _clean_signal_narratives(
            generate_signals(
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
                preserve_snapshot_narrative_warning=True,
            )
        )
    )
    _run_decision_shadow_guard(
        config,
        signals,
        decision_time=data_report.as_of_date,
        latest_features=latest,
        price_history=features,
    )
    def load_backtest() -> BacktestReport:
        from etf_cockpit.application.backtest_service import _empty_backtest_report, BacktestService

        if prices.empty:
            return _empty_backtest_report(
                "Backtest skipped because no clean prices exist for the current two-tier universe yet."
            )
        return BacktestService(
            config,
            universe_revision=universe_revision,
            reference_context=reference_context,
        ).load_or_run_backtest(data_report.as_of_date, publish_guard=publish_guard)
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
        backtest=None,
        model_status=status,
        model_inventory=inventory,
        _backtest_loader=load_backtest,
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
        facts_known_at=datetime.now(timezone.utc).isoformat(),
        benchmark_reference_portfolio_ids=benchmark_reference["reference_ids"],  # type: ignore[arg-type]
        vwce_anchor_evidence=benchmark_reference["anchor"],  # type: ignore[arg-type]
        vwce_listing_id=benchmark_reference["listing_id"],  # type: ignore[arg-type]
        vwce_conversion_evidence=None,
    )


def _load_legacy_forecasts(as_of_date: object, *, allowed_ids: set[str]) -> pd.DataFrame:
    """Read an unbound pre-sidecar forecast cache with an explicit legacy label.

    Legacy rows are limited to instruments with local price history and forecast
    dates at or before the snapshot cutoff. A present but mismatched sidecar is
    never bypassed.
    """

    if not allowed_ids:
        return pd.DataFrame()
    files = sorted(
        FORECASTS_DIR.glob("forecast_results_*.csv"),
        key=lambda item: (
            item.stem.rsplit("_", 1)[-1] if item.stem.rsplit("_", 1)[-1].isdigit() else "",
            item.stat().st_mtime,
        ),
        reverse=True,
    )
    if not files or Path(f"{files[0]}.meta.json").exists():
        return pd.DataFrame()
    path = files[0]
    try:
        frame = pd.read_csv(path)
    except (OSError, ValueError, UnicodeError) as exc:
        log_event(
            event_type="data_read_failed",
            severity="warning",
            component="forecast_cache",
            operation="read_legacy_forecasts",
            file_paths=path,
            exception_type=type(exc).__name__,
            exception_message_redacted=str(exc),
        )
        return pd.DataFrame()
    required = {"etf_id", "forecast_date", "horizon_days", "expected_return", "model_name", "status"}
    if not required.issubset(frame.columns):
        frame.attrs["unavailable_reason"] = "legacy_forecast_schema_incompatible"
        return pd.DataFrame()
    dates = pd.to_datetime(frame["forecast_date"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    cutoff = pd.to_datetime(as_of_date, errors="coerce")
    if pd.isna(cutoff):
        frame.attrs["unavailable_reason"] = "snapshot_forecast_cutoff_unavailable"
        return pd.DataFrame()
    valid = dates.notna() & (dates <= cutoff.normalize()) & frame["etf_id"].astype(str).isin(allowed_ids)
    frame = frame.loc[valid].copy()
    if frame.empty:
        return frame
    frame["source_file"] = str(path)
    frame["cache_status"] = "legacy_cache"
    frame.attrs["cache_compatibility"] = "legacy_cache"
    return frame


def _clean_signal_narratives(signals: list[SignalResult]) -> list[SignalResult]:
    """Keep nonfinite score placeholders out of presentation text with an explicit cause."""

    cleaned: list[SignalResult] = []
    nonfinite = re.compile(r"\bnan\b", re.IGNORECASE)
    for signal in signals:
        short = str(signal.reason_short or "")
        long = str(signal.reason_long or "")
        if not any(nonfinite.search(value) or "n/ad" in value.casefold() for value in (short, long)):
            cleaned.append(signal)
            continue
        reason = "Score explanation unavailable because one or more component values are nonfinite; see component status and reason fields."
        warnings = list(signal.warnings)
        warnings.append("nonfinite_score_narrative_suppressed")
        cleaned.append(replace(signal, reason_short=reason, reason_long=reason, warnings=list(dict.fromkeys(warnings))))
    return cleaned
