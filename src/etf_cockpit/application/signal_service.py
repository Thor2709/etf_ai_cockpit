"""Signal generation orchestration and the decision shadow-run guard (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import (
    Mapping,
    Sequence,
)
from datetime import date
import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.logging import append_jsonl
from etf_cockpit.core.types import (
    SignalResult,
    latest_signal,
)
from etf_cockpit.core.versioning import current_settings_revision
from etf_cockpit.data.duckdb_store import (
    FEATURE_PARQUET,
    load_features,
    load_holdings,
    load_prices,
)
from etf_cockpit.features.feature_pipeline import latest_features
from etf_cockpit.models.forecast_scores import (
    configured_forecast_request_identity,
    forecast_component_maps,
    forecast_return_distributions,
    load_latest_forecasts,
)
from etf_cockpit.models.calibration import load_forecast_history
from etf_cockpit.models.registry import model_availability
from etf_cockpit.signals.signal_pipeline import generate_signals
from etf_cockpit.application.derived_cache import (
    _calculation_window,
    _current_universe_revision,
    _price_binding_matches,
    _price_snapshot_binding,
    _reference_identity_matches,
)
from etf_cockpit.application.structural_evidence import _load_structure_caps
from etf_cockpit.application.reference_context import (
    _benchmark_reference_snapshot_inputs,
    _reference_context_from_inputs,
)
from etf_cockpit.application.feature_service import FeatureService
from etf_cockpit.application.data_service import DataService


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
            if features.attrs.get("relative_strength_anchor") is None:
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
        price_freshness: dict[str, str] = {}
        report_issues = getattr(report, "issues", None)
        report_available = isinstance(report_issues, (list, tuple))
        for issue in report_issues if report_available else ():
            if issue.etf_id == "ALL":
                continue
            if issue.code == "stale_data":
                price_freshness[issue.etf_id] = "stale"
            elif issue.code == "stale_data_warning" and price_freshness.get(issue.etf_id) != "stale":
                price_freshness[issue.etf_id] = "warning"
        if "etf_id" in latest.columns:
            latest = latest.copy()
            known_ids = latest["etf_id"].dropna().astype(str).unique()
            for instrument_id in known_ids:
                price_freshness.setdefault(instrument_id, "ok" if report_available else "unknown")
            latest["price_freshness"] = latest["etf_id"].astype(str).map(price_freshness).fillna("unknown")
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
