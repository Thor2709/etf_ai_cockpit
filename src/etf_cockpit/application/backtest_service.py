"""Backtest orchestration, operational-evidence binding and bound backtest artefacts (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import (
    Callable,
    Mapping,
)
from datetime import date
from io import BytesIO
import json
import hashlib
import inspect
from pathlib import Path
import pandas as pd

from etf_cockpit.backtest.engine import (
    BacktestDataUnavailableError,
    BacktestReport,
    backtest_input_checksum,
    quality_momentum_evidence_checksum,
    run_backtest,
)
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.atomic_io import (
    AtomicWriteRequest,
    atomic_write_group,
    read_atomic_group,
)
from etf_cockpit.core.logging import append_jsonl
from etf_cockpit.core.paths import (
    BACKTESTS_DIR,
    CONFIG_DIR,
)
from etf_cockpit.core.timing import (
    record_cache_event,
    timed_step,
)
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.core.versioning import (
    current_settings_identity,
    current_settings_revision,
    ensure_run_manifest,
    settings_bound_run_id,
)
from etf_cockpit.data.duckdb_store import load_prices
from etf_cockpit.data.fundamentals import load_fundamental_evidence
from etf_cockpit.data.identity_master import (
    IdentityMasterSchemaError,
    IdentityMasterStore,
    identity_master_content_digest,
)
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry
from etf_cockpit.portfolio.benchmark_reference import CanonicalReferenceContext
from etf_cockpit.signals.quality_momentum import (
    FRAME_COLUMNS,
    QUALITY_MOMENTUM_VERSION,
)
from etf_cockpit.application.derived_cache import (
    _bound_cache_metadata_payload,
    _cached_backtest_binding_matches,
    _cached_structure_columns_match,
    _cached_tail_diagnostics_are_valid,
    _current_universe_revision,
    _decode_nullable_integer_diagnostic,
    _encode_nullable_integer_diagnostic,
    _NULLABLE_INTEGER_DIAGNOSTIC_FIELDS,
    _reference_binding,
    _reference_identity_matches,
    _universe_cache_meta_path,
)
from etf_cockpit.application.structural_evidence import _load_local_structural_evidence
from etf_cockpit.application.reference_context import (
    _backtest_calculation_context,
    _backtest_prices_for_reference,
)
from etf_cockpit.application.forecast_service import _validate_csv


def _run_backtest_compatibly(config: AppConfig, prices: pd.DataFrame, **kwargs: object) -> BacktestReport:
    """Keep the service seam compatible with older focused test runners.

    Signature filtering is explicit compatibility, not exception handling:
    TypeError raised by the runner itself must remain visible to the caller.
    """

    parameters = inspect.signature(run_backtest).parameters
    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    supported = kwargs if accepts_kwargs else {key: value for key, value in kwargs.items() if key in parameters}
    return run_backtest(config, prices, **supported)


def _backtest_runner_kwargs(
    reference_context: CanonicalReferenceContext,
    fundamentals: pd.DataFrame,
    *,
    structure_document_registry: object,
    structure_report_records: object,
    structure_supplemental_rows: object,
    structure_holdings: object,
    calendar_identity_resolver: Callable[[str, object], Mapping[str, object] | None] | None,
) -> dict[str, object]:
    return {
        "fundamentals": fundamentals,
        "structure_document_registry": structure_document_registry,
        "structure_report_records": structure_report_records,
        "structure_supplemental_rows": structure_supplemental_rows,
        "structure_holdings": structure_holdings,
        "benchmark_data_id": reference_context.benchmark_data_id,
        "benchmark_reference": reference_context.projection,
        "reference_identity": reference_context.identity,
        "benchmark_registry": reference_context.registry,
        "calendar_identity_resolver": calendar_identity_resolver,
    }


def _normalise_operational_evidence_rows(rows: object) -> list[dict[str, object]] | None:
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        return None
    normalised: list[dict[str, object]] = []
    for row in rows:
        if any(type(key) is not str for key in row):
            return None
        normalised.append(
            {
                key: value.isoformat() if type(value) is date else value
                for key, value in row.items()
            }
        )
    return normalised


OPERATIONAL_EVIDENCE_INPUT_BINDING_VERSION = "operational-evidence-inputs.v2"


def _operational_evidence_input_binding(config: AppConfig) -> str | None:
    """Fingerprint every non-price input of persisted operational evidence.

    Prices, settings and reference context are bound by the existing cache
    checks.  Returns None when an input cannot be read, so no cache matches.
    """

    def digest(path: Path) -> str | None:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    try:
        identity_path = Path(IDENTITY_PATH).resolve()
        identity_store: str | None = None
        if len(identity_path.parents) >= 3:
            # Bind the logical identity records the backtest resolver reads, not
            # the raw bytes of the shared transactional store: unrelated writes
            # (classification, fixed income, ledgers) must not invalidate the
            # cache and force a full backtest recompute.
            identity_store = identity_master_content_digest(identity_path.parents[2])
        payload = {
            "version": OPERATIONAL_EVIDENCE_INPUT_BINDING_VERSION,
            "calendar_corrections": digest(CONFIG_DIR / "market_calendar_corrections.yaml"),
            "identity_store": identity_store,
            "cost_model": config.costs.cost_model.model_dump(mode="json"),
        }
    except OSError:
        return None
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _open_backtest_calendar_identity_resolver() -> tuple[
    IdentityMasterStore | None,
    Callable[[str, object], Mapping[str, object] | None] | None,
]:
    """Open one read-only logical identity view for the complete backtest run."""

    def unavailable_projection(instrument_id: str, reason: str) -> Mapping[str, object]:
        return {
            "status": "unavailable",
            "instrument_id": instrument_id,
            "reason": reason,
            "execution_allowed": False,
        }

    def unavailable(instrument_id: str, _signal_timestamp: object) -> Mapping[str, object]:
        return unavailable_projection(instrument_id, "canonical_identity_store_unreadable")

    identity_path = Path(IDENTITY_PATH).resolve()
    if len(identity_path.parents) < 3:
        return None, None
    root = identity_path.parents[2]
    try:
        if not storage_layout(root).transactional_path.is_file():
            return None, None
        store = IdentityMasterStore(root, read_only=True)
    except (IdentityMasterSchemaError, OSError, ValueError):
        return None, unavailable
    cache: dict[tuple[str, str], Mapping[str, object] | None] = {}

    def resolve(instrument_id: str, signal_timestamp: object) -> Mapping[str, object] | None:
        try:
            timestamp = pd.Timestamp(signal_timestamp)
            if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
                return unavailable_projection(
                    instrument_id, "canonical_identity_point_in_time_unavailable"
                )
            timestamp = timestamp.tz_convert("UTC")
            point_in_time = timestamp.isoformat()
            key = (instrument_id, point_in_time)
            if key not in cache:
                cache[key] = store.projection(
                    instrument_id,
                    effective_at=point_in_time,
                    decision_time=point_in_time,
                )
            return cache[key]
        except (IdentityMasterSchemaError, KeyError, TypeError, ValueError, OverflowError):
            return unavailable(instrument_id, signal_timestamp)

    return store, resolve


class BacktestService:
    REQUIRED_RESULT_COLUMNS = {
        "return_hit_rate",
        "average_win_return",
        "average_loss_return",
        "payoff_ratio",
        "expected_value_per_period",
        "payoff_asymmetry_warning",
        "gross_log_return",
        "max_drawdown",
        "diagnostic_method",
        "diagnostic_status",
        "execution_allowed",
        "worst_1d_return",
        "worst_5d_return",
        "worst_10d_return",
        "worst_drawdown_start",
        "worst_drawdown_end",
        "worst_drawdown_duration_days",
        "worst_drawdown_duration_sessions",
        "observed_session_count",
        "loss_cluster_max_days",
        "largest_negative_period_return",
        "largest_negative_period_date",
        "largest_negative_contribution_periods",
        "negative_return_concentration_share",
        "negative_return_concentration_status",
        "negative_return_concentration_reason",
        "negative_return_concentration_method",
        "few_days_explain_most_performance",
        "performance_concentration_basis",
        "performance_concentration_method",
        "performance_concentration_status",
        "performance_concentration_share",
        "positive_performance_concentration_share",
        "positive_performance_concentration_status",
        "positive_performance_few_sessions_explain_most",
        "negative_performance_concentration_share",
        "negative_performance_concentration_status",
        "negative_performance_few_sessions_explain_most",
        "losses_during_high_volatility",
        "high_volatility_loss_status",
        "high_volatility_loss_reason",
        "high_volatility_loss_method",
        "losses_during_regime_stress",
        "regime_stress_loss_status",
        "regime_stress_loss_reason",
        "regime_stress_loss_method",
    }

    def __init__(
        self,
        config: AppConfig,
        *,
        universe_revision: str | None = None,
        reference_context: CanonicalReferenceContext | None = None,
    ):
        self.config = config
        self.universe_revision = _current_universe_revision() if universe_revision is None else universe_revision
        self.reference_context = reference_context or CanonicalReferenceContext(
            CanonicalBenchmarkRegistry(), None, blocker="reference_resolution_unavailable"
        )

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
        reference_context = _backtest_calculation_context(self.config, self.reference_context, prices)
        fundamentals = load_fundamental_evidence()
        try:
            structure_evidence = _load_local_structural_evidence()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return _empty_backtest_report(f"Structural evidence unavailable ({type(exc).__name__}): {exc}; backtest was not run.")
        operational_input_binding = _operational_evidence_input_binding(self.config)
        identity_store, calendar_identity_resolver = _open_backtest_calendar_identity_resolver()
        try:
            runner_kwargs = _backtest_runner_kwargs(
                reference_context,
                fundamentals,
                structure_document_registry=(structure_evidence.document_registry if structure_evidence else None),
                structure_report_records=(structure_evidence.report_records if structure_evidence else None),
                structure_supplemental_rows=(structure_evidence.supplemental_rows if structure_evidence else None),
                structure_holdings=(structure_evidence.holdings if structure_evidence else None),
                calendar_identity_resolver=calendar_identity_resolver,
            )
            report = _run_backtest_compatibly(
                self.config,
                prices,
                **runner_kwargs,
            )
            # Bind every runner result to the freshly resolved readback context
            # before publication, including older local runner seams.
            reference_binding = _reference_binding(reference_context)
            report.metadata.update(reference_binding)
            report.metadata["operational_evidence_input_binding"] = operational_input_binding
            report.results["benchmark_strategy"] = reference_binding["benchmark_strategy"]
        except BacktestDataUnavailableError as exc:
            return _empty_backtest_report(str(exc))
        finally:
            if identity_store is not None:
                identity_store.close()
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
        persisted_results = report.results.copy()
        for diagnostic_field in _NULLABLE_INTEGER_DIAGNOSTIC_FIELDS & set(persisted_results):
            persisted_results[diagnostic_field] = persisted_results[diagnostic_field].map(
                _encode_nullable_integer_diagnostic
            )
        if "largest_negative_contribution_periods" in persisted_results:
            persisted_results["largest_negative_contribution_periods"] = persisted_results[
                "largest_negative_contribution_periods"
            ].map(lambda value: json.dumps(value, default=str, separators=(",", ":")))
        metadata_payload = json.dumps(
            report.metadata, default=str, sort_keys=True, indent=2
        ).encode("utf-8")
        payloads = {
            BACKTESTS_DIR / "backtest_results.csv": (
                persisted_results.to_csv(index=False).encode("utf-8"),
                lambda path: _validate_csv(path),
            ),
            BACKTESTS_DIR / "equity_curves.csv": (
                report.equity_curves.to_csv().encode("utf-8"),
                lambda path: _validate_csv(path, index_col=0),
            ),
            BACKTESTS_DIR / "trade_log.csv": (
                report.trade_log.to_csv(index=False).encode("utf-8"),
                lambda path: _validate_csv(path),
            ),
            BACKTESTS_DIR / "signal_log.csv": (
                report.signal_log.to_csv(index=False).encode("utf-8"),
                lambda path: _validate_csv(path),
            ),
            BACKTESTS_DIR / "quality_momentum_evidence.csv": (
                report.quality_momentum_evidence.to_csv(index=False).encode("utf-8"),
                lambda path: _validate_csv(path),
            ),
            BACKTESTS_DIR / "backtest_metadata.json": (
                metadata_payload,
                lambda path: json.loads(path.read_text(encoding="utf-8")),
            ),
        }
        settings_revision = str(settings_identity["settings_revision"])
        requests = [
            AtomicWriteRequest(path, payload, validator)
            for path, (payload, validator) in payloads.items()
        ]
        requests.extend(
            AtomicWriteRequest(
                _universe_cache_meta_path(path),
                _bound_cache_metadata_payload(
                    self.universe_revision,
                    settings_revision,
                    reference_context.identity,
                    payload,
                ),
                lambda path: json.loads(path.read_text(encoding="utf-8")),
            )
            for path, (payload, _validator) in payloads.items()
        )
        with timed_step("backtest", "write_outputs"):
            with publication_scope(publish_guard):
                atomic_write_group(requests)
        with publication_scope(publish_guard):
            append_jsonl("model_runs.jsonl", "backtest_completed", {"ai_added_value": report.ai_added_value})
        return report

    def _load_cached_backtest(self, as_of_date: date | None = None) -> BacktestReport | None:
        settings_revision = current_settings_revision()
        prices = load_prices()
        reference_context = _backtest_calculation_context(self.config, self.reference_context, prices)
        checksum_prices = _backtest_prices_for_reference(prices, reference_context)
        if checksum_prices is None:
            return None
        results_path = BACKTESTS_DIR / "backtest_results.csv"
        equity_path = BACKTESTS_DIR / "equity_curves.csv"
        trade_path = BACKTESTS_DIR / "trade_log.csv"
        signal_path = BACKTESTS_DIR / "signal_log.csv"
        metadata_path = BACKTESTS_DIR / "backtest_metadata.json"
        quality_evidence_path = BACKTESTS_DIR / "quality_momentum_evidence.csv"
        payload_paths = (
            results_path,
            equity_path,
            trade_path,
            signal_path,
            quality_evidence_path,
            metadata_path,
        )
        sidecar_paths = tuple(_universe_cache_meta_path(path) for path in payload_paths)
        snapshot_paths = payload_paths + sidecar_paths
        if any(not path.is_file() for path in snapshot_paths):
            return None
        try:
            structure_evidence = _load_local_structural_evidence()
        except (OSError, ValueError, TypeError, KeyError):
            return None
        try:
            snapshot = dict(zip(snapshot_paths, read_atomic_group(snapshot_paths), strict=True))
            payload_bytes = {path: snapshot[path] for path in payload_paths}
            for path, sidecar_path in zip(payload_paths, sidecar_paths, strict=True):
                sidecar = json.loads(snapshot[sidecar_path].decode("utf-8"))
                if (
                    not isinstance(sidecar, dict)
                    or str(sidecar.get("universe_revision") or "") != self.universe_revision
                    or str(sidecar.get("settings_revision") or "") != settings_revision
                    or sidecar.get("payload_sha256") != hashlib.sha256(payload_bytes[path]).hexdigest()
                    or not _reference_identity_matches(
                        sidecar.get("reference_identity"),
                        sidecar.get("reference_identity_hash"),
                        reference_context.identity,
                    )
                ):
                    return None
            results = pd.read_csv(
                BytesIO(payload_bytes[results_path]),
                converters={
                    field: _decode_nullable_integer_diagnostic
                    for field in _NULLABLE_INTEGER_DIAGNOSTIC_FIELDS
                },
            )
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
            equity_curves = pd.read_csv(BytesIO(payload_bytes[equity_path]), index_col=0, parse_dates=True)
            if not _cached_tail_diagnostics_are_valid(results, equity_curves):
                return None
            trade_log = pd.read_csv(BytesIO(payload_bytes[trade_path]))
            signal_log = pd.read_csv(BytesIO(payload_bytes[signal_path]))
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
            quality_momentum_evidence = pd.read_csv(BytesIO(payload_bytes[quality_evidence_path]))
            metadata = json.loads(payload_bytes[metadata_path].decode("utf-8"))
            if not isinstance(metadata, dict):
                return None
            fundamentals = load_fundamental_evidence()
            # Operational evidence is bound to every non-price input it reads
            # (calendar corrections, identity store, cost model).  A changed
            # input invalidates the cache; re-deriving a full backtest to
            # validate a cache read would defeat the cache.
            input_binding = metadata.get("operational_evidence_input_binding")
            if (
                type(input_binding) is not str
                or input_binding != _operational_evidence_input_binding(self.config)
                or _normalise_operational_evidence_rows(metadata.get("operational_evidence_rows")) is None
            ):
                return None
            if not _cached_backtest_binding_matches(metadata, reference_context):
                return None
            expected_benchmark_strategy = metadata["benchmark_strategy"]
            if (
                "benchmark_strategy" not in results.columns
                or not results["benchmark_strategy"].map(
                    lambda value: type(value) is str and value == expected_benchmark_strategy
                ).all()
            ):
                return None
            if metadata.get("quality_momentum_strategy_version") != QUALITY_MOMENTUM_VERSION:
                return None
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
                checksum_prices,
                fundamentals,
                structure_document_registry=(structure_evidence.document_registry if structure_evidence else None),
                structure_report_records=(structure_evidence.report_records if structure_evidence else None),
                structure_supplemental_rows=(structure_evidence.supplemental_rows if structure_evidence else None),
                structure_holdings=(structure_evidence.holdings if structure_evidence else None),
            ):
                return None
            if set(FRAME_COLUMNS) - set(quality_momentum_evidence.columns):
                return None
            quality_momentum_evidence = quality_momentum_evidence.reindex(columns=FRAME_COLUMNS)
            if metadata.get("quality_momentum_evidence_checksum") != quality_momentum_evidence_checksum(
                payload_bytes[quality_evidence_path]
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
        except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError):
            return None


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
