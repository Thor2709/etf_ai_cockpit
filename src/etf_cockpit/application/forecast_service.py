"""Forecast orchestration: baseline and optional-model forecasts, benchmark post-processing and bound forecast artefacts (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import (
    asdict,
    replace,
)
from collections import Counter
import importlib.util
import json
import math
from datetime import date
from pathlib import Path
import pandas as pd
import yaml

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import CONFIG_DIR, FORECASTS_DIR
from etf_cockpit.core.timing import timed_step
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.core.versioning import (
    current_settings_identity,
    current_settings_revision,
    ensure_run_manifest,
    settings_bound_run_id,
)
from etf_cockpit.data.duckdb_store import load_prices
from etf_cockpit.features.forecast_lab import build_forecast_lab_workspace as _build_forecast_lab_workspace
from etf_cockpit.features.returns import daily_log_returns
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.calibration import adjusted_log_return_target, load_forecast_history, target_matches_evaluation, horizon_calibration_scores
from etf_cockpit.models.forecast_scores import configured_forecast_request_identity as configured_forecast_request_identity, forecast_request_identity
from etf_cockpit.models.model_promotion import (
    OPTIONAL_MODELS,
    PRETRAINING_CUTOFFS,
    PRETRAINING_SOURCES,
    checkpoint_provenance,
    COUNTING,
    NOT_PROVEN,
    ModelPromotion,
    evaluate_model_promotions,
    positive_probability_status,
    matured_probability_frame,
    promotion_frame,
)
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry
from etf_cockpit.portfolio.benchmark_reference import (
    CanonicalReferenceContext,
    clip_to_decision_window,
    unavailable_reference_projection,
)
from etf_cockpit.application.derived_cache import (
    _calculation_window,
    _current_universe_revision,
    _price_snapshot_binding,
    _write_bound_cache_group,
)


def _live_optional_models_from_config(config: AppConfig) -> bool:
    return any(
        config.models.runtime(name).enabled and config.models.runtime(name).mode == "live"
        for name in ("timesfm", "timesfm3", "toto")
    )


class ForecastService:
    def __init__(self, config: AppConfig, *, reference_context: CanonicalReferenceContext | None = None):
        self.config = config
        self.reference_context = reference_context or CanonicalReferenceContext(
            CanonicalBenchmarkRegistry(),
            None,
            unavailable_reference_projection(),
        )

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
        reference_context: CanonicalReferenceContext | None = None,
        cache_request_identity: Mapping[str, object] | None = None,
        live_optional_models: bool | None = None,
        promotions: Mapping[str, ModelPromotion] | None = None,
        promotion_prices: pd.DataFrame | None = None,
    ) -> list[ForecastResult]:
        settings_identity = current_settings_identity()
        price_frame = prices if prices is not None else load_prices()
        price_frame = price_frame.copy()
        price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce", utc=True, format="mixed")
        # Promotion evidence is graded on the full stored history, not the shorter forecast calculation window.
        evidence_prices = price_frame
        context = reference_context if reference_context is not None else self.reference_context
        calculation_window = _calculation_window(context, as_of_date, price_frame)
        if calculation_window is None:
            raise ValueError("canonical forecast calculation window is unavailable")
        price_frame = clip_to_decision_window(price_frame, **calculation_window)
        price_binding = _price_snapshot_binding(price_frame, calculation_window=calculation_window)
        if price_binding is None:
            raise ValueError("adjusted-price snapshot identity is unavailable")
        horizons = horizons or self.config.models.forecast_horizons_trading_days
        resolved_live_optional_models = (
            _live_optional_models_from_config(self.config)
            if live_optional_models is None
            else live_optional_models
        )
        derived_request_identity = forecast_request_identity(
            self.config,
            horizons,
            live_optional_models=resolved_live_optional_models,
        )
        if cache_request_identity is not None and dict(cache_request_identity) != derived_request_identity:
            raise ValueError("forecast cache request identity does not match the calculation request")
        pivot = price_frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
        # Preserve row presence separately from the union pivot's holiday NaNs.
        pivot.attrs["timesfm_price_rows"] = {
            etf_id: group.sort_values("date")
            for etf_id, group in price_frame.groupby("etf_id", sort=False)
        }
        benchmark_id = context.benchmark_data_id if context is not None else None
        benchmark_returns = daily_log_returns(pivot[benchmark_id]).dropna() if benchmark_id in pivot else None
        forecasts: list[ForecastResult] = []
        run_id = settings_bound_run_id(
            f"forecast_{as_of_date:%Y%m%d}",
            settings_identity=settings_identity,
        )
        if progress_callback is not None:
            progress_callback("Running baseline forecasts", 1, 4)
        # Per-family durations are the Forecast Lab's measured resource use.
        with timed_step("forecasts", "model:baseline", run_id=run_id):
            for etf_id in etf_ids:
                series = pivot[etf_id].dropna() if etf_id in pivot else pd.Series(dtype=float)
                baseline_rows = baseline_forecast(
                    etf_id,
                    series,
                    horizons,
                    as_of_date,
                    run_id=run_id,
                    benchmark_returns=benchmark_returns,
                )
                if not baseline_rows:
                    baseline_rows = [
                        ForecastResult(
                            run_id=run_id,
                            model_name="baseline",
                            model_version="momentum_shrunk_v1",
                            etf_id=etf_id,
                            forecast_date=as_of_date,
                            horizon_days=horizon,
                            expected_return=None,
                            expected_excess_return=None,
                            status="unavailable",
                            model_allowed_in_score=False,
                            reason_unavailable="insufficient_adjusted_price_history",
                        )
                        for horizon in horizons
                    ]
                forecasts.extend(baseline_rows)
        if progress_callback is not None:
            progress_callback("Checking cached TimesFM forecasts", 2, 4)
        with timed_step("forecasts", "model:timesfm", run_id=run_id):
            forecasts.extend(_stamp_adjusted_log_return_target(self._run_timesfm_forecasts(pivot, etf_ids, horizons, as_of_date, run_id)))
        if "timesfm3" in self.config.models.models:
            with timed_step("forecasts", "model:timesfm3", run_id=run_id):
                forecasts.extend(_stamp_adjusted_log_return_target(
                    self._run_timesfm_forecasts(pivot, etf_ids, horizons, as_of_date, run_id, model_name="timesfm3")
                ))
        if progress_callback is not None:
            progress_callback("Checking cached Toto forecasts", 3, 4)
        with timed_step("forecasts", "model:toto", run_id=run_id):
            forecasts.extend(_stamp_adjusted_log_return_target(self._run_toto_forecasts(price_frame, etf_ids, horizons, as_of_date, run_id)))
        forecasts = self._evidence_gated_forecasts(forecasts, as_of_date, evidence_prices)
        forecasts = _postprocess_forecast_benchmark_fields(
            forecasts,
            benchmark_returns,
            self._probability_statuses(forecasts, as_of_date, evidence_prices),
        )
        if self.config.models.promotion.enabled:
            if promotions is None:
                # Candidate runs pass the configured universe's prices so every run in a workflow shares one decision.
                promotions = self.evaluate_promotions(as_of_date, promotion_prices if promotion_prices is not None else evidence_prices)
            forecasts = [_apply_promotion(row, promotions, self.config.models.shadow_optional_models) for row in forecasts]
        else:
            forecasts = [_apply_promotion(row, {}, self.config.models.shadow_optional_models) for row in forecasts]
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
            reference_identity=context.identity,
            price_binding=price_binding,
            cache_request_identity=derived_request_identity,
            live_optional_models=resolved_live_optional_models,
            publish_guard=publish_guard,
            promotions=promotions,
        )
        return forecasts

    def _probability_statuses(
        self,
        forecasts: list[ForecastResult],
        as_of_date: date,
        prices: pd.DataFrame,
        history: pd.DataFrame | None = None,
    ) -> dict[tuple[str, str, str | None, int], str]:
        """Admission of each producer's P(up) on matured history known at ``as_of_date`` (never the current run)."""

        stored = load_forecast_history() if history is None else history
        statuses: dict[tuple[str, str, str | None, int], str] = {}
        for forecast in forecasts:
            scope = _probability_scope(forecast)
            if scope not in statuses:  # pooled evidence is per (model, version, target, horizon), not per ETF
                statuses[scope] = positive_probability_status(
                    stored, prices, forecast.model_name, as_of_date,
                    model_version=forecast.model_version, target_id=forecast.target_id, horizon_days=forecast.horizon_days,
                )
        return statuses

    def _evidence_gated_forecasts(self, forecasts, as_of_date, prices, history=None):
        stored = load_forecast_history() if history is None else history
        sufficient: dict[tuple[str, str, str | None, int], bool] = {}
        output = []
        for forecast in forecasts:
            forecast = _identity_gated_forecast(forecast, self.config.models.models)
            if forecast.status == "ok":
                scope = _probability_scope(forecast)
                if scope not in sufficient:
                    evidence = matured_probability_frame(
                        stored, prices, forecast.model_name, as_of_date,
                        model_version=forecast.model_version, target_id=forecast.target_id, horizon_days=forecast.horizon_days,
                    )
                    metrics = horizon_calibration_scores(evidence)
                    sufficient[scope] = not metrics.empty and bool(metrics["status"].eq("ok").all())
                if not sufficient[scope]:
                    forecast = _unavailable_forecast(forecast, "Insufficient finite per-horizon calibration metrics or effective dates.")
            output.append(forecast)
        return output

    def evaluate_promotions(
        self,
        as_of_date: date,
        prices: pd.DataFrame,
        history: pd.DataFrame | None = None,
    ) -> dict[str, ModelPromotion]:
        """Decide which optional models count, from stored forecasts and prices known at ``as_of_date``."""

        stored = load_forecast_history() if history is None else history
        return evaluate_model_promotions(stored, prices, as_of_date, self.config.models.promotion)

    def _run_timesfm_forecasts(
        self,
        pivot: pd.DataFrame,
        etf_ids: list[str],
        horizons: list[int],
        as_of_date: date,
        run_id: str,
        *,
        model_name: str = "timesfm",
    ) -> list[ForecastResult]:
        from etf_cockpit.models.timesfm_adapter import TimesFMAdapter
        from etf_cockpit.models.timesfm3_adapter import TimesFM3Adapter

        adapter_class = TimesFM3Adapter if model_name == "timesfm3" else TimesFMAdapter
        adapter = adapter_class(self.config.models.runtime(model_name))
        forecasts: list[ForecastResult] = []
        try:
            for etf_id in etf_ids:
                try:
                    series = _timesfm_price_series(pivot, etf_id, as_of_date)
                except ValueError as exc:
                    forecasts.extend(adapter._status_results(
                        horizons, etf_id=etf_id, forecast_date=as_of_date,
                        run_id=run_id, status="unavailable", message=str(exc),
                    ))
                    continue
                forecasts.extend(
                    adapter.forecast_series(
                        series,
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
        try:
            return adapter.forecast_universe(
                etf_ids, as_of_date, horizons,
                prices=price_frame[["date", "etf_id", "adjusted_close"]], run_id=run_id,
            )
        finally:
            adapter.unload_model()

    def _write_forecasts(
        self,
        forecasts: list[ForecastResult],
        as_of_date: date,
        *,
        output_path: Path | None = None,
        settings_revision: str | None = None,
        reference_identity: Mapping[str, object] | None = None,
        price_binding: Mapping[str, object] | None = None,
        cache_request_identity: Mapping[str, object] | None = None,
        live_optional_models: bool | None = None,
        publish_guard: PublicationScopeFactory | None = None,
        promotions: Mapping[str, ModelPromotion] | None = None,
    ) -> None:
        output = output_path or FORECASTS_DIR / f"forecast_results_{as_of_date:%Y%m%d}.csv"
        if cache_request_identity is None:
            cache_request_identity = forecast_request_identity(
                self.config,
                sorted({forecast.horizon_days for forecast in forecasts}) or None,
                live_optional_models=(
                    _live_optional_models_from_config(self.config)
                    if live_optional_models is None
                    else live_optional_models
                ),
            )
        else:
            requested_horizons = cache_request_identity.get("requested_horizons")
            requested_mode = cache_request_identity.get("live_optional_models")
            if not isinstance(requested_horizons, list) or type(requested_mode) is not bool:
                raise ValueError("forecast cache request identity is malformed")
            validated_identity = forecast_request_identity(
                self.config,
                requested_horizons,
                live_optional_models=requested_mode,
            )
            output_horizons = {forecast.horizon_days for forecast in forecasts}
            if dict(cache_request_identity) != validated_identity or not output_horizons.issubset(requested_horizons):
                raise ValueError("forecast cache request identity does not match forecast output")
        payload = pd.DataFrame([_forecast_to_row(forecast, promotions, self.config.models.models) for forecast in forecasts]).to_csv(index=False).encode("utf-8")

        def validate(path: Path) -> None:
            _validate_csv(path)

        with timed_step("forecasts", "write_output"):
            with publication_scope(publish_guard):
                _write_bound_cache_group(
                    output,
                    payload,
                    validate,
                    _current_universe_revision(),
                    settings_revision or current_settings_revision(),
                    reference_identity,
                    price_binding,
                    cache_request_identity,
                )


def _unavailable_forecast(forecast: ForecastResult, reason: str) -> ForecastResult:
    # The producer's P(up) stays stored as a heuristic (never a user-facing probability) so a diagnostic
    # row can still mature into probability-calibration evidence.
    positive = forecast.prob_positive_return
    heuristic = forecast.heuristic_probability_positive
    if heuristic is None and positive is not None and math.isfinite(positive) and 0.0 <= positive <= 1.0:
        heuristic = positive
    return replace(forecast, status="unavailable", reason_unavailable=reason, error_message=reason,
                   model_allowed_in_score=False, prob_positive_return=None, prob_beat_benchmark=None,
                   heuristic_probability_positive=heuristic, probability_calibration_status="unavailable")


def _stamp_adjusted_log_return_target(forecasts: list[ForecastResult]) -> list[ForecastResult]:
    """Adapter forecasts are adjusted-close log returns of their horizon; name that registered target."""

    return [
        forecast if forecast.target_id is not None
        else replace(forecast, target_id=adjusted_log_return_target(forecast.horizon_days).target_id)
        for forecast in forecasts
    ]


def _identity_gated_forecast(forecast: ForecastResult, model_settings=None) -> ForecastResult:
    if forecast.status != "ok":
        return forecast  # keep the producer's own, more specific unavailable reason
    if not target_matches_evaluation(forecast.target_id, forecast.horizon_days):
        return _unavailable_forecast(forecast, "Missing, unregistered or mismatched target identity.")
    if forecast.model_name in OPTIONAL_MODELS:
        revision = str(_checkpoint_evidence(forecast.model_name, model_settings)["checkpoint_sha"])
        if len(revision) != 40 or any(char not in "0123456789abcdefABCDEF" for char in revision):
            return _unavailable_forecast(forecast, "Missing or unverifiable immutable checkpoint identity.")
    return forecast


def _probability_scope(forecast: ForecastResult) -> tuple[str, str, str | None, int]:
    return (forecast.model_name, forecast.model_version, forecast.target_id, forecast.horizon_days)


def _forecast_to_row(
    forecast: ForecastResult,
    promotions: Mapping[str, ModelPromotion] | None = None,
    model_settings: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if forecast.model_name == "baseline":
        forecast = _apply_promotion(forecast, {}, False)
    forecast = _identity_gated_forecast(forecast, model_settings)
    data = asdict(forecast)
    data["forecast_date"] = forecast.forecast_date.isoformat()
    promotion = _promotion_for_row(forecast, promotions or {})
    if forecast.promotion_status in {COUNTING, NOT_PROVEN} and promotion is not None:
        data.update(_promotion_evidence(forecast, promotion, model_settings))
    elif forecast.promotion_status == "shadow_only":
        data.update(_pretraining_evidence(forecast.model_name, forecast.forecast_date, model_settings))
        data["promotion_state"] = "shadow_only"
        data["execution_allowed"] = False
    return data



_CHECKPOINT_REVISION_KEYS = ("revision", "hf_revision", "model_sha", "checkpoint_sha")
# Metadata that identifies the checkpoint; paths, devices and timeouts are runtime choices, not identity.
_CHECKPOINT_CONFIG_KEYS = ("backend", "hf_repo_id", "model_size", "context_length", "use_quantiles", "decode_block_size")


def _declared_model_settings() -> Mapping[str, object]:
    """``models`` of configs/model_settings.yaml (metadata only; weights are never opened)."""

    try:
        loaded = yaml.safe_load((CONFIG_DIR / "model_settings.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    models = loaded.get("models") if isinstance(loaded, Mapping) else None
    return models if isinstance(models, Mapping) else {}


def _checkpoint_evidence(model_name: str, model_settings: Mapping[str, object] | None = None) -> dict[str, object]:
    """Checkpoint SHA, config, licence and cutoff scope of this model alone (a cutoff is never shared).

    The revision and identifying config come from the model's entry in model_settings.yaml; an absent
    source stays ``unknown`` (SHA) or empty (config), never copied from another checkpoint.
    """

    settings = model_settings if model_settings is not None else _declared_model_settings()
    entry = settings.get(model_name)
    entry = entry if isinstance(entry, Mapping) else {}
    revision = next((str(entry[key]).strip() for key in _CHECKPOINT_REVISION_KEYS if str(entry.get(key) or "").strip()), None)
    config = {key: entry[key] for key in _CHECKPOINT_CONFIG_KEYS if entry.get(key) is not None}
    row = checkpoint_provenance(model_name, model_sha=revision, config=config).as_row()
    return {
        "checkpoint_sha": row["checkpoint_sha"],
        "checkpoint_config": json.dumps(row["checkpoint_config"], sort_keys=True),
        "checkpoint_licence": row["checkpoint_licence"],
        "cutoff_scope": row["cutoff_scope"],
    }


def _pretraining_evidence(
    model_name: str, forecast_date: date, model_settings: Mapping[str, object] | None = None
) -> dict[str, object]:
    cutoff = PRETRAINING_CUTOFFS.get(model_name)
    possibly_leaked = cutoff is None or forecast_date <= cutoff
    return {
        **_checkpoint_evidence(model_name, model_settings),
        "pretraining_cutoff": cutoff.isoformat() if cutoff is not None else "unknown",
        "pretraining_sources": PRETRAINING_SOURCES.get(model_name, "unknown"),
        "contamination_status": "possibly_leaked" if possibly_leaked else "after_declared_cutoff",
        "promotion_evidence_allowed": False,
        "evaluation_scope": "diagnostic_only; existing governance approval required",
    }


def _promotion_evidence(
    forecast: ForecastResult, promotion: ModelPromotion, model_settings: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Leakage flags: every optional origin must follow its first verified local run and known cutoff."""

    window_open = (
        forecast.status == "ok"
        and forecast.model_version == promotion.model_version
        and forecast.horizon_days == promotion.evidence_horizon_days
        and promotion.evidence_window_open(forecast.forecast_date)
    )
    declared = promotion.pretraining_cutoff != "unknown"
    return {
        **_checkpoint_evidence(forecast.model_name, model_settings),
        "pretraining_cutoff": promotion.pretraining_cutoff,
        "pretraining_sources": PRETRAINING_SOURCES.get(forecast.model_name, "unknown"),
        "contamination_status": (
            ("after_declared_cutoff" if declared else "after_first_local_run") if window_open else "possibly_leaked"
        ),
        "promotion_evidence_allowed": window_open,
        "evaluation_scope": "matured out-of-sample evidence against the baseline",
        "promotion_state": forecast.promotion_status,
        "promotion_reason": promotion.reason,
        "execution_allowed": False,
    }


def _promotion_for_row(row: ForecastResult, promotions: Mapping[str, ModelPromotion]) -> ModelPromotion | None:
    """Select only this row's version; older versions keep their own evidence."""
    decision = promotions.get(row.model_name)
    if decision is not None and decision.model_version != row.model_version:
        for candidate in decision.version_evidence:
            if candidate["model_version"] == row.model_version:
                return ModelPromotion(**candidate)
    return decision


def _apply_promotion(
    row: ForecastResult,
    promotions: Mapping[str, ModelPromotion],
    shadow_flag: bool,
) -> ForecastResult:
    """Let an optional model's successful rows count only while its promotion decision says so."""

    if row.model_name == "baseline":
        return replace(row, model_allowed_in_score=row.status == "ok" and row.expected_return is not None)
    promotion = _promotion_for_row(row, promotions)
    if row.status != "ok" or promotion is None:
        return _shadow_forecast(row) if shadow_flag else replace(row, model_allowed_in_score=False, promotion_status=NOT_PROVEN)
    counting = (
        promotion.counting
        and promotion.model_name == row.model_name
        and promotion.model_version == row.model_version
        and row.horizon_days == promotion.evidence_horizon_days
    )
    matched = row.model_version == promotion.model_version and row.horizon_days == promotion.evidence_horizon_days
    return replace(
        row,
        model_allowed_in_score=counting,
        promotion_status=COUNTING if counting else NOT_PROVEN,
        oos_mase=promotion.model_mase if matched else None,
        oos_directional_accuracy=promotion.model_directional if matched else None,
        calibration_status=(promotion.calibration_status if promotion.calibration_status in {"good", "mixed", "weak", "limited"} else "limited") if matched else "limited",
        calibration_horizon_days=promotion.evidence_horizon_days if matched else None,
    )


def _shadow_forecast(row: ForecastResult) -> ForecastResult:
    if row.model_name == "baseline":
        return row
    return replace(row, model_allowed_in_score=False, promotion_status="shadow_only")


def build_forecast_lab_workspace(
    config: AppConfig,
    forecasts: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    forecast_history: pd.DataFrame | None = None,
    **kwargs: object,
) -> dict[str, object]:
    """Forecast Lab report with TimesFM3 availability and each optional model's promotion state.

    ``forecast_history`` is every stored forecast row (promotion needs matured runs, not only the latest);
    it defaults to ``forecasts``.
    """
    # Artefact availability (stored ok forecasts up to the as-of) is built by the report for every optional
    # model; the installed runtime is a separate fact and is reported next to it, never merged into it.
    kwargs.setdefault("runtime_installed", optional_runtime_installed())
    report = _build_forecast_lab_workspace(config, forecasts, prices, **kwargs)
    history = forecasts if forecast_history is None else pd.concat([forecast_history, forecasts], ignore_index=True)
    as_of = _promotion_as_of(kwargs.get("as_of_date"), prices, history)
    if config.models.promotion.enabled:
        promotions = evaluate_model_promotions(history, prices, as_of, config.models.promotion)
    else:
        promotions = {
            model: ModelPromotion(model, NOT_PROVEN, "Automatic promotion is disabled in model settings.")
            for model in OPTIONAL_MODELS
        }
    report["promotion"] = promotion_frame(promotions)
    return _stamp_promotion_states(report, promotions, history)


_OPTIONAL_RUNTIME_PACKAGES = {"timesfm": "timesfm", "timesfm3": "timesfm", "toto": "toto2"}


def optional_runtime_installed() -> dict[str, bool]:
    """Whether each optional model's python runtime package is importable (weights are not checked here)."""

    return {model: importlib.util.find_spec(package) is not None for model, package in _OPTIONAL_RUNTIME_PACKAGES.items()}


def forecast_lab_inputs(latest: pd.DataFrame, history: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Every stored forecast, so matured outcomes and walk-forward folds are not limited to the latest run.

    Forecasts whose instrument has no stored price (for example a delisted ETF) are kept: the Forecast Lab lists them
    as excluded (``missing_price_series``) and counts them in the completeness denominator instead of hiding them.
    A repeated forecast keeps its newest row. ``prices`` is accepted for call compatibility.
    """

    parts = [frame for frame in (history, latest) if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not parts:
        return latest
    combined = pd.concat(parts, ignore_index=True)
    key = ["model_name", "etf_id", "forecast_date", "horizon_days"]
    if not {*key, "status"}.issubset(combined.columns):
        return latest
    stamp = pd.to_datetime(combined["forecast_date"], errors="coerce", utc=True, format="mixed").dt.normalize()
    combined = combined.assign(_day=stamp).drop_duplicates(["model_name", "etf_id", "_day", "horizon_days"], keep="last").drop(columns="_day")
    return combined.reset_index(drop=True)


def _promotion_as_of(requested: object, prices: pd.DataFrame, history: pd.DataFrame) -> date:
    """Evidence cutoff: an explicit replay date, else the latest known price session."""

    if requested is not None:
        parsed = pd.to_datetime(requested, errors="coerce")
        if pd.notna(parsed):
            return parsed.date()
    for frame, column in ((prices, "date"), (history, "forecast_date")):
        if isinstance(frame, pd.DataFrame) and column in frame.columns:
            latest = pd.to_datetime(frame[column], errors="coerce", utc=True, format="mixed").max()
            if pd.notna(latest):
                return latest.date()
    return date.today()


def _stamp_promotion_states(
    report: dict[str, object],
    promotions: Mapping[str, ModelPromotion],
    history: pd.DataFrame | None = None,
) -> dict[str, object]:
    """Replace the diagnostic placeholder state in the report tables with promotion decisions.

    The model table shows today's decision. A run keeps the state stored with its own rows at run time,
    never today's decision: a later promotion cannot relabel a historical run.
    """

    models, runs = report.get("models"), report.get("runs")
    if isinstance(models, pd.DataFrame) and not models.empty:
        models = models.copy()
        models["promotion_state"] = [
            promotions[name].state if name in promotions else ("reference" if name == "baseline" else "not_proven")
            for name in models["model_name"].astype(str)
        ]
        report["models"] = models
    if isinstance(runs, pd.DataFrame) and not runs.empty:
        runs = runs.copy()
        recorded = _recorded_run_states(history)
        runs["promotion_state"] = [
            _run_promotion_text(str(members), promotions, recorded.get(str(run_id), {}))
            for members, run_id in zip(runs["models"], runs["run_id"])
        ]
        report["runs"] = runs
    return report


def _recorded_run_states(history: pd.DataFrame | None) -> dict[str, dict[str, str]]:
    """Promotion state each stored row carried when its run wrote it, per run and model."""

    if not isinstance(history, pd.DataFrame) or not {"model_name", "promotion_state"}.issubset(history.columns):
        return {}
    run_ids = history["run_id"].astype(str) if "run_id" in history.columns else pd.Series("local-cache", index=history.index)
    states: dict[str, dict[str, str]] = {}
    for run_id, model, state in zip(run_ids, history["model_name"].astype(str), history["promotion_state"]):
        if isinstance(state, str) and state.strip() and state.strip().lower() != "nan":
            states.setdefault(run_id, {})[model] = state.strip()
    return states


def _run_promotion_text(members: str, promotions: Mapping[str, ModelPromotion], recorded: Mapping[str, str] | None = None) -> str:
    recorded = recorded or {}
    parts = []
    for name in (item.strip() for item in members.split(",")):
        if name not in promotions:
            continue
        state = recorded.get(name)
        parts.append(
            f"{name}: not recorded at run time"
            if state is None
            else f"{name}: {'counting' if state == COUNTING else 'not yet proven'}"
        )
    return "; ".join(parts) or "reference"


def _timesfm_price_series(pivot: pd.DataFrame, etf_id: str, as_of_date: date) -> pd.Series:
    """Keep own-session gaps, exclude certified closures; never infer a holiday from NaN."""
    from datetime import datetime, time, timezone
    import json
    from etf_cockpit.core.paths import CONFIG_DIR
    from etf_cockpit.data.market_calendar import MarketCalendarService

    rows = pivot.attrs.get("timesfm_price_rows", {}).get(etf_id)
    if rows is None:
        series = pivot[etf_id].copy() if etf_id in pivot else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    else:
        series = rows.set_index("date")["adjusted_close"].copy()
    series = series.loc[pd.to_datetime(series.index).date <= as_of_date].sort_index()
    if series.empty:
        return series
    series.index = pd.DatetimeIndex(series.index).normalize()
    if series.index.has_duplicates:
        raise ValueError("TimesFM session grid unavailable: duplicate instrument session dates.")
    cutoff = datetime.combine(as_of_date, time.max, timezone.utc)
    identity = None
    if rows is not None and "calendar_identity" in rows:
        candidates = rows.loc[pd.to_datetime(rows["date"]).dt.date <= as_of_date, "calendar_identity"].dropna()
        if not candidates.empty:
            identity = candidates.iloc[-1]
            if isinstance(identity, str):
                try:
                    identity = json.loads(identity)
                except ValueError:
                    identity = None
    if isinstance(identity, Mapping):
        try:
            calendar = MarketCalendarService.from_correction_ledger(CONFIG_DIR / "market_calendar_corrections.yaml")
            listing = calendar.listing_from_identity_projection(identity)
            if listing.instrument_id != etf_id:
                raise ValueError("calendar identity does not match forecast instrument")
            if listing.valid_from > series.index.min().date() or (
                listing.valid_to is not None and listing.valid_to <= series.index.max().date()
            ):
                raise ValueError("calendar identity does not cover the historical context")
            days = pd.date_range(series.index.min().normalize(), series.index.max().normalize(), freq="D")
            sessions = days[[calendar.is_business_day(listing, day.date(), knowledge_cutoff=cutoff) for day in days]]
            # An observed price is evidence of a session even if the calendar disagrees;
            # certified sessions without a row become NaN gaps; NaN rows on certified
            # closures are not sessions and are dropped.
            grid = sessions.union(series.index)
            restored = series.reindex(grid)
            return restored.loc[restored.notna() | restored.index.isin(sessions)]
        except ValueError as exc:
            raise ValueError(f"TimesFM session calendar unavailable: {exc}") from exc
    # Without certified calendar evidence the instrument's own observed dates are its
    # session grid and absent dates are non-sessions (never invented). Without a calendar a NaN row cannot be told apart from a holiday row, so it is dropped.
    return series.dropna()


def _demote_unadmitted_probabilities(
    forecast: ForecastResult, probability_status: Mapping[tuple[str, str, str | None, int], str] | None
) -> ForecastResult:
    """Keep a producer's P(up) as ``prob_positive_return`` only when its admission is ``calibrated``.

    Otherwise the value becomes a heuristic score (never a user-facing probability) and ``prob_*`` is
    None. ``prob_beat_benchmark`` has no matured benchmark-outcome admission, so it is never calibrated here.
    """

    admitted = forecast.status == "ok" and target_matches_evaluation(forecast.target_id, forecast.horizon_days) and (probability_status or {}).get(_probability_scope(forecast)) == "calibrated"
    positive = forecast.prob_positive_return
    heuristic = forecast.heuristic_probability_positive
    if heuristic is None and positive is not None and math.isfinite(positive) and 0.0 <= positive <= 1.0:
        heuristic = positive
    beat = forecast.heuristic_probability_beat_benchmark
    if beat is None and forecast.prob_beat_benchmark is not None and math.isfinite(forecast.prob_beat_benchmark):
        beat = forecast.prob_beat_benchmark
    return replace(
        forecast,
        prob_positive_return=positive if admitted else None,
        prob_beat_benchmark=None,
        heuristic_probability_positive=None if admitted else heuristic,
        heuristic_probability_beat_benchmark=beat,
        probability_calibration_status="calibrated" if admitted else "unavailable",
    )


def _postprocess_forecast_benchmark_fields(
    forecasts: list[ForecastResult],
    benchmark_returns: pd.Series | None,
    probability_status: Mapping[tuple[str, str, str | None, int], str] | None = None,
) -> list[ForecastResult]:
    """Derive relative fields uniformly using horizon log-return sigma from every producer.

    Probabilities from any producer stay heuristic unless ``probability_status`` admits the model.
    """

    forecasts = [_demote_unadmitted_probabilities(forecast, probability_status) for forecast in forecasts]
    if benchmark_returns is None or benchmark_returns.empty:
        return [
            replace(forecast, expected_excess_return=None, prob_beat_benchmark=None, heuristic_probability_beat_benchmark=None)
            for forecast in forecasts
        ]
    benchmark_daily = float(benchmark_returns.tail(180).mean() * 0.35)
    output: list[ForecastResult] = []
    for forecast in forecasts:
        if forecast.expected_return is None or not math.isfinite(forecast.expected_return) or not math.isfinite(benchmark_daily):
            output.append(replace(forecast, expected_excess_return=None, prob_beat_benchmark=None, heuristic_probability_beat_benchmark=None))
            continue
        excess = float(forecast.expected_return - benchmark_daily * forecast.horizon_days)
        try:
            volatility = float(forecast.forecast_vol)
        except (TypeError, ValueError):
            volatility = None
        if volatility is None or not math.isfinite(volatility) or volatility <= 0:
            output.append(
                replace(
                    forecast,
                    expected_excess_return=excess,
                    prob_beat_benchmark=None,
                    heuristic_probability_beat_benchmark=None,
                    reason_unavailable=(
                        f"{forecast.reason_unavailable}; forecast_vol_unavailable_for_benchmark_probability"
                        if forecast.reason_unavailable
                        else "forecast_vol_unavailable_for_benchmark_probability"
                    ),
                )
            )
            continue
        output.append(
            replace(
                forecast,
                expected_excess_return=excess,
                # A logistic of excess/vol is a heuristic score, not a calibrated probability.
                prob_beat_benchmark=None,
                heuristic_probability_beat_benchmark=(
                    1 / (1 + math.exp(-excess / volatility)) if excess >= 0
                    else math.exp(excess / volatility) / (1 + math.exp(excess / volatility))
                ),
            )
        )
    return output


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
    for model_name in ("timesfm", "timesfm3", "toto"):
        if model_name not in quick_config.models.models:
            continue
        model_config = dict(quick_config.models.models.get(model_name, {}))
        model_config.update(
            {
                "enabled": False,
                "mode": "disabled",
            }
        )
        quick_config.models.models[model_name] = model_config
    return quick_config
