from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from io import BytesIO
import math
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
from etf_cockpit.chatgpt_bridge.export_pack import export_review_pack
from etf_cockpit.chatgpt_bridge.import_audit import import_audit_json
from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAudit, ChatGPTAuditV2
from etf_cockpit.core.config import AppConfig, load_config
from etf_cockpit.core.atomic_io import (
    AtomicWriteRequest,
    atomic_write_bytes,
    atomic_write_group,
    read_atomic_group,
)
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
from etf_cockpit.data.duckdb_store import FEATURE_PARQUET, initialise_store, load_features, load_holdings, load_prices, write_features
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
from etf_cockpit.data.trade_candidate_analysis import (
    fetch_candidate_prices,
    load_candidate_price_binding,
    refresh_candidate_analysis,
    write_candidate_price_snapshot,
)
from etf_cockpit.data.validation import validate_holdings, validate_prices
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.data.universe_store import load_universe
from etf_cockpit.features.cash_comparison import adjusted_endpoint_available_at
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.forecast_scores import (
    configured_forecast_request_identity,
    forecast_component_maps,
    forecast_request_identity,
    forecast_return_distributions,
    load_latest_forecasts,
)
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
    validate_execution_disabled,
)
from etf_cockpit.application.benchmark_reference import (
    CanonicalReferenceContext,
    adjusted_price_snapshot_binding,
    clip_to_decision_window,
    resolve_canonical_reference,
    unavailable_reference_projection,
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


def _cache_matches_universe(
    path: Path,
    revision: str,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> bool:
    metadata_path = _universe_cache_meta_path(path)
    if not path.is_file() or not metadata_path.is_file():
        return False
    try:
        payload_bytes, metadata_bytes = read_atomic_group((path, metadata_path))
        payload = json.loads(metadata_bytes.decode("utf-8"))
    except (OSError, ValueError, TypeError, RecursionError):
        return False
    expected_settings = settings_revision or current_settings_revision()
    matches = (
        isinstance(payload, dict)
        and str(payload.get("universe_revision") or "") == revision
        and str(payload.get("settings_revision") or "") == expected_settings
    )
    if not matches or reference_identity is None:
        if not matches:
            return False
        checksum = payload.get("payload_sha256") if isinstance(payload, dict) else None
        return (
            (checksum is None or checksum == hashlib.sha256(payload_bytes).hexdigest())
            and (price_binding is None or _price_binding_matches(payload, price_binding))
            and (
                forecast_request_identity is None
                or _forecast_request_matches(payload, forecast_request_identity)
            )
        )
    if payload.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest():
        return False
    if price_binding is not None and not _price_binding_matches(payload, price_binding):
        return False
    if forecast_request_identity is not None and not _forecast_request_matches(payload, forecast_request_identity):
        return False
    return _reference_identity_matches(
        payload.get("reference_identity"),
        payload.get("reference_identity_hash"),
        reference_identity,
    )


def _read_bound_cache_payload(
    path: Path,
    revision: str,
    settings_revision: str,
    reference_identity: Mapping[str, object],
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> bytes | None:
    metadata_path = _universe_cache_meta_path(path)
    try:
        payload_bytes, metadata_bytes = read_atomic_group((path, metadata_path))
        payload = json.loads(metadata_bytes.decode("utf-8"))
    except (OSError, TypeError, ValueError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("universe_revision") or "") != revision:
        return None
    if str(payload.get("settings_revision") or "") != settings_revision:
        return None
    if not _reference_identity_matches(
        payload.get("reference_identity"),
        payload.get("reference_identity_hash"),
        reference_identity,
    ):
        return None
    if price_binding is not None and not _price_binding_matches(payload, price_binding):
        return None
    if forecast_request_identity is not None and not _forecast_request_matches(payload, forecast_request_identity):
        return None
    if payload.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest():
        return None
    return payload_bytes


def _load_local_structural_evidence():
    return load_local_structural_evidence(
        registry_reader=read_document_registry,
        report_reader=read_etf_report_records,
        factsheet_path=ETF_METADATA_CLEAN_PATH,
        holdings_path=FUND_HOLDINGS_PATH,
    )


def _run_backtest_compatibly(config: AppConfig, prices: pd.DataFrame, **kwargs: object) -> BacktestReport:
    """Keep the service seam compatible with older focused test runners.

    Signature filtering is explicit compatibility, not exception handling:
    TypeError raised by the runner itself must remain visible to the caller.
    """

    parameters = inspect.signature(run_backtest).parameters
    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    supported = kwargs if accepts_kwargs else {key: value for key, value in kwargs.items() if key in parameters}
    return run_backtest(config, prices, **supported)


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


def _write_universe_cache_metadata(
    path: Path,
    revision: str,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> None:
    metadata_path = _universe_cache_meta_path(path)
    payload_sha256 = (
        hashlib.sha256(path.read_bytes()).hexdigest()
        if reference_identity is not None and path.is_file()
        else None
    )
    payload = json.dumps(
        {
            "schema_version": 2,
            "universe_revision": revision,
            "settings_revision": settings_revision or current_settings_revision(),
            **({"payload_sha256": payload_sha256} if payload_sha256 is not None else {}),
            **(
                {
                    "reference_identity": dict(reference_identity),
                    "reference_identity_hash": _reference_identity_hash(reference_identity),
                }
                if reference_identity is not None
                else {}
            ),
            **(dict(price_binding) if price_binding is not None else {}),
            **(
                {
                    "forecast_request_identity": dict(forecast_request_identity),
                    "forecast_request_identity_hash": _reference_identity_hash(forecast_request_identity),
                }
                if forecast_request_identity is not None
                else {}
            ),
        },
        sort_keys=True,
    ).encode("utf-8")
    atomic_write_bytes(metadata_path, payload, lambda candidate: json.loads(candidate.read_text(encoding="utf-8")))


def _write_bound_cache_metadata(
    path: Path,
    revision: str,
    settings_revision: str,
    reference_identity: Mapping[str, object] | None,
    price_binding: Mapping[str, object] | None = None,
) -> None:
    """Write reference-bound metadata, retaining the old test seam."""

    if reference_identity is None:
        _write_universe_cache_metadata(path, revision, settings_revision, price_binding=price_binding)
        return
    try:
        _write_universe_cache_metadata(path, revision, settings_revision, reference_identity, price_binding)
    except TypeError as exc:
        # A narrow compatibility path for callers monkeypatching the former
        # three-argument helper; production always uses the bound form above.
        if "positional" not in str(exc) and "argument" not in str(exc):
            raise
        _write_universe_cache_metadata(path, revision, settings_revision, price_binding=price_binding)


def _bound_cache_metadata_payload(
    revision: str,
    settings_revision: str,
    reference_identity: Mapping[str, object] | None,
    payload: bytes,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> bytes:
    record: dict[str, object] = {
        "schema_version": 3,
        "universe_revision": revision,
        "settings_revision": settings_revision,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }
    if reference_identity is not None:
        record["reference_identity"] = dict(reference_identity)
        record["reference_identity_hash"] = _reference_identity_hash(reference_identity)
    if price_binding is not None:
        record.update(dict(price_binding))
    if forecast_request_identity is not None:
        record["forecast_request_identity"] = dict(forecast_request_identity)
        record["forecast_request_identity_hash"] = _reference_identity_hash(forecast_request_identity)
    return json.dumps(record, sort_keys=True).encode("utf-8")


def _write_bound_cache_group(
    path: Path,
    payload: bytes,
    validator: Callable[[Path], None],
    revision: str,
    settings_revision: str,
    reference_identity: Mapping[str, object] | None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> None:
    metadata_path = _universe_cache_meta_path(path)
    metadata_payload = _bound_cache_metadata_payload(
        revision,
        settings_revision,
        reference_identity,
        payload,
        price_binding,
        forecast_request_identity,
    )
    atomic_write_group(
        (
            AtomicWriteRequest(path, payload, validator),
            AtomicWriteRequest(
                metadata_path,
                metadata_payload,
                lambda candidate: json.loads(candidate.read_text(encoding="utf-8")),
            ),
        )
    )


def _reference_identity_hash(identity: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _canonical_json_value(identity),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_json_value(value: object) -> object:
    """Return JSON-safe canonical data without coercing primitive types."""

    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("canonical mappings require string keys")
        return {key: _canonical_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        return value
    raise TypeError("canonical JSON contains an unsupported primitive")


def _calculation_window(
    context: CanonicalReferenceContext,
    as_of_date: date,
    prices: pd.DataFrame,
) -> dict[str, str] | None:
    """Return the exact canonical window, with a deterministic local fallback."""

    try:
        requested_as_of = pd.Timestamp(as_of_date).date()
    except (TypeError, ValueError):
        return None
    resolution = getattr(context, "resolution", None)
    if resolution is not None:
        declaration = resolution.declaration
        try:
            end_date = date.fromisoformat(declaration.end_date)
        except (TypeError, ValueError):
            return None
        if requested_as_of > end_date:
            return None
        if requested_as_of < end_date:
            return {
                "start_date": declaration.start_date,
                "end_date": requested_as_of.isoformat(),
                "decision_time": f"{requested_as_of.isoformat()}T23:59:59+00:00",
            }
        return {
            "start_date": declaration.start_date,
            "end_date": declaration.end_date,
            "decision_time": declaration.decision_time,
        }

    if not isinstance(prices, pd.DataFrame) or "date" not in prices.columns:
        start_date = requested_as_of
    else:
        dates = pd.to_datetime(prices["date"], errors="coerce", utc=True)
        valid = dates.dropna()
        start_date = valid.min().date() if not valid.empty else requested_as_of
    return {
        "start_date": start_date.isoformat(),
        "end_date": requested_as_of.isoformat(),
        "decision_time": f"{requested_as_of.isoformat()}T23:59:59+00:00",
    }


def _price_snapshot_binding(
    prices: pd.DataFrame,
    *,
    calculation_window: Mapping[str, str],
) -> dict[str, object] | None:
    """Build the adjusted-price identity used by derived-cache sidecars."""

    return adjusted_price_snapshot_binding(prices, calculation_window=calculation_window)


def _price_binding_matches(metadata: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    checksum = expected.get("price_snapshot_checksum")
    revision = expected.get("price_snapshot_revision")
    cutoff = expected.get("effective_cutoff")
    window = expected.get("calculation_window")
    valid = (
        isinstance(checksum, str)
        and len(checksum) == 64
        and all(character in "0123456789abcdef" for character in checksum)
        and revision == checksum
        and isinstance(cutoff, str)
        and bool(cutoff)
        and isinstance(window, Mapping)
        and window.get("decision_time") == cutoff
        and all(isinstance(window.get(key), str) and window.get(key) for key in ("start_date", "end_date"))
    )
    return valid and all(metadata.get(key) == value for key, value in expected.items())


def _forecast_request_identity(
    config: AppConfig,
    horizons: list[int] | None,
    *,
    live_optional_models: bool,
) -> dict[str, object]:
    return forecast_request_identity(
        config,
        horizons,
        live_optional_models=live_optional_models,
    )


def _live_optional_models_from_config(config: AppConfig) -> bool:
    return any(
        config.models.runtime(name).enabled and config.models.runtime(name).mode == "live"
        for name in ("timesfm", "toto")
    )


def _forecast_request_matches(metadata: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    return _reference_identity_matches(
        metadata.get("forecast_request_identity"),
        metadata.get("forecast_request_identity_hash"),
        expected,
    )


def _reference_binding(reference_context: CanonicalReferenceContext) -> dict[str, object]:
    """Build the one cache binding from the freshly resolved context."""

    projection = reference_context.projection
    identity = reference_context.identity
    identity_hash = _reference_identity_hash(identity)
    strategy = (
        "canonical_price_series"
        if projection.get("status") == "available" and reference_context.benchmark_data_id
        else "unavailable"
    )
    strategy_identity = {
        "strategy": strategy,
        "benchmark_data_id": reference_context.benchmark_data_id,
        "reference_identity_hash": identity_hash,
    }
    return {
        "benchmark_reference": projection,
        "benchmark_reference_hash": _reference_identity_hash(projection),
        "benchmark_strategy": strategy,
        "benchmark_strategy_hash": _reference_identity_hash(strategy_identity),
        "benchmark_strategy_identity": strategy_identity,
        "reference_identity": identity,
        "reference_identity_hash": identity_hash,
    }


def _cached_backtest_binding_matches(
    metadata: Mapping[str, object],
    reference_context: CanonicalReferenceContext,
) -> bool:
    """Require cached benchmark metadata to match canonical context exactly."""

    try:
        validate_execution_disabled(metadata)
        expected = _reference_binding(reference_context)
        return all(
            metadata.get(field) == value
            for field, value in expected.items()
        ) and all(
            _reference_identity_hash(metadata[field]) == expected[hash_field]
            for field, hash_field in (
                ("benchmark_reference", "benchmark_reference_hash"),
                ("benchmark_strategy_identity", "benchmark_strategy_hash"),
                ("reference_identity", "reference_identity_hash"),
            )
        )
    except (BenchmarkReferenceError, TypeError, ValueError, KeyError, RecursionError):
        return False


def _reference_identity_matches(
    stored: object,
    claimed_hash: object,
    expected: Mapping[str, object],
) -> bool:
    if not isinstance(stored, Mapping):
        return False
    try:
        expected_hash = _reference_identity_hash(expected)
        return (
            str(claimed_hash or "") == expected_hash
            and _reference_identity_hash(stored) == expected_hash
        )
    except (TypeError, ValueError, RecursionError):
        return False


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


class FeatureService:
    def __init__(self, config: AppConfig, *, reference_context: CanonicalReferenceContext | None = None):
        self.config = config
        self.reference_context = reference_context or CanonicalReferenceContext(
            CanonicalBenchmarkRegistry(),
            None,
            unavailable_reference_projection(),
        )

    def compute_features(
        self,
        as_of_date: date | None = None,
        prices: pd.DataFrame | None = None,
        *,
        publish_guard: PublicationScopeFactory | None = None,
        reference_context: CanonicalReferenceContext | None = None,
    ) -> pd.DataFrame:
        settings_identity = current_settings_identity()
        frame = (prices if prices is not None else load_prices()).copy()
        if "volume" not in frame.columns:
            frame["volume"] = float("nan")
        context = reference_context if reference_context is not None else self.reference_context
        effective_as_of = as_of_date
        if effective_as_of is None:
            if "date" not in frame.columns:
                raise ValueError("canonical feature calculation window is unavailable")
            valid_dates = pd.to_datetime(frame["date"], errors="coerce", utc=True).dropna()
            if valid_dates.empty:
                raise ValueError("canonical feature calculation window is unavailable")
            effective_as_of = valid_dates.max().date()
        calculation_window = _calculation_window(context, effective_as_of, frame)
        if calculation_window is None:
            raise ValueError("canonical feature calculation window is unavailable")
        frame = clip_to_decision_window(frame, **calculation_window)
        price_binding = _price_snapshot_binding(frame, calculation_window=calculation_window)
        if price_binding is None:
            raise ValueError("adjusted-price snapshot identity is unavailable")
        benchmark = context.benchmark_data_id if context is not None else None
        available_ids = set(frame["etf_id"].astype(str)) if "etf_id" in frame.columns else set()
        if benchmark is None or benchmark not in available_ids:
            benchmark = None
        features = compute_features(frame, benchmark_etf_id=benchmark)
        if benchmark is None:
            for column in ("relative_strength_60d", "relative_strength_120d"):
                if column in features.columns:
                    features[column] = float("nan")
        features.attrs["benchmark_reference"] = (
            unavailable_reference_projection()
            if context is None
            else context.projection
        )
        features.attrs["reference_identity"] = context.identity
        features.attrs["reference_identity_hash"] = _reference_identity_hash(context.identity)
        features.attrs["price_binding"] = dict(price_binding)
        run_id = settings_bound_run_id(
            f"features_{effective_as_of.isoformat()}",
            settings_identity=settings_identity,
        )
        with publication_scope(publish_guard):
            ensure_run_manifest(
                run_id,
                ("schema:local-storage", "dataset:prices", "dataset:universe"),
                settings_identity=settings_identity,
            )
        with publication_scope(publish_guard):
            write_features(
                features,
                cache_metadata={
                    "universe_revision": _current_universe_revision(),
                    "settings_revision": str(settings_identity["settings_revision"]),
                    "reference_identity": context.identity,
                    **price_binding,
                },
            )
        return features


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
    ) -> list[ForecastResult]:
        settings_identity = current_settings_identity()
        price_frame = prices if prices is not None else load_prices()
        price_frame = price_frame.copy()
        price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce", utc=True, format="mixed")
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
        benchmark_id = context.benchmark_data_id if context is not None else None
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
        forecasts = _postprocess_forecast_benchmark_fields(forecasts, benchmark_returns)
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
        reference_identity: Mapping[str, object] | None = None,
        price_binding: Mapping[str, object] | None = None,
        cache_request_identity: Mapping[str, object] | None = None,
        live_optional_models: bool | None = None,
        publish_guard: PublicationScopeFactory | None = None,
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
        payload = pd.DataFrame([_forecast_to_row(forecast) for forecast in forecasts]).to_csv(index=False).encode("utf-8")

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


def _sanitize_unavailable_relative_features(features: pd.DataFrame) -> None:
    """Drop relative fields from an in-memory frame without canonical evidence."""

    for column in ("relative_strength_60d", "relative_strength_120d"):
        if column in features.columns:
            features[column] = float("nan")


def _forecast_to_row(forecast: ForecastResult) -> dict[str, object]:
    data = asdict(forecast)
    data["forecast_date"] = forecast.forecast_date.isoformat()
    return data


def _postprocess_forecast_benchmark_fields(
    forecasts: list[ForecastResult],
    benchmark_returns: pd.Series | None,
) -> list[ForecastResult]:
    """Derive relative forecast fields uniformly after every model adapter."""

    if benchmark_returns is None or benchmark_returns.empty:
        return [
            replace(forecast, expected_excess_return=None, prob_beat_benchmark=None)
            for forecast in forecasts
        ]
    benchmark_daily = float(benchmark_returns.tail(180).mean() * 0.35)
    output: list[ForecastResult] = []
    for forecast in forecasts:
        if forecast.expected_return is None:
            output.append(replace(forecast, expected_excess_return=None, prob_beat_benchmark=None))
            continue
        excess = float(forecast.expected_return - benchmark_daily * forecast.horizon_days)
        volatility = max(float(forecast.forecast_vol or 0.0), 1e-6)
        output.append(
            replace(
                forecast,
                expected_excess_return=excess,
                prob_beat_benchmark=float(1 / (1 + math.exp(-excess / volatility))),
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


def _decode_negative_contribution_periods(value: object) -> list[dict[str, object]] | None:
    if type(value) is not str:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded, list):
        return None
    records: list[dict[str, object]] = []
    for record in decoded:
        if not isinstance(record, dict) or set(record) != {"date", "return"}:
            return None
        raw_date = record["date"]
        raw_return = record["return"]
        if type(raw_date) is not str or type(raw_return) not in {int, float}:
            return None
        try:
            contribution_date = date.fromisoformat(raw_date)
            contribution_return = float(raw_return)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(contribution_return) or contribution_return >= 0:
            return None
        records.append({"date": contribution_date, "return": contribution_return})
    return records


def _cached_tail_diagnostics_are_valid(results: pd.DataFrame) -> bool:
    exact_methods = {
        "diagnostic_method": "historical_tail_diagnostics.v2",
        "negative_return_concentration_method": (
            "five worst observed loss sessions divided by total observed loss magnitude"
        ),
        "performance_concentration_method": (
            "best/worst up-to-five observed sessions divided by same-sign gross log contribution"
        ),
        "high_volatility_loss_method": (
            "loss-session alignment with 20-session realized volatility at or above its 75th percentile"
        ),
        "regime_stress_loss_method": "loss-session alignment with explicitly labelled stress regimes",
    }
    for column, expected in exact_methods.items():
        if not results[column].map(lambda value: type(value) is str and value == expected).all():
            return False
    for column in (
        "diagnostic_status",
        "negative_return_concentration_status",
        "performance_concentration_status",
        "positive_performance_concentration_status",
        "negative_performance_concentration_status",
        "high_volatility_loss_status",
        "regime_stress_loss_status",
    ):
        if not results[column].map(
            lambda value: type(value) is str and value in {"available", "unavailable"}
        ).all():
            return False
    if not results["execution_allowed"].map(
        lambda value: type(value) is bool and value is False
    ).all():
        return False
    numeric_columns = (
        "gross_log_return",
        "worst_1d_return",
        "worst_5d_return",
        "worst_10d_return",
        "worst_drawdown_duration_days",
        "worst_drawdown_duration_sessions",
        "observed_session_count",
        "loss_cluster_max_days",
        "largest_negative_period_return",
        "negative_return_concentration_share",
        "performance_concentration_share",
        "positive_performance_concentration_share",
        "negative_performance_concentration_share",
    )
    for column in numeric_columns:
        if not results[column].map(lambda value: pd.isna(value) or type(value) is not bool).all():
            return False
        values = pd.to_numeric(results[column], errors="coerce")
        if (results[column].notna() & values.isna()).any():
            return False
        if not values.dropna().map(math.isfinite).all():
            return False
    for column in (
        "worst_drawdown_duration_days",
        "worst_drawdown_duration_sessions",
        "observed_session_count",
        "loss_cluster_max_days",
    ):
        values = pd.to_numeric(results[column], errors="coerce").dropna()
        if (values < 0).any() or (values % 1 != 0).any():
            return False
    for column in (
        "negative_return_concentration_share",
        "performance_concentration_share",
        "positive_performance_concentration_share",
        "negative_performance_concentration_share",
    ):
        values = pd.to_numeric(results[column], errors="coerce").dropna()
        if not values.between(0.0, 1.0).all():
            return False
    for column in ("worst_drawdown_start", "worst_drawdown_end", "largest_negative_period_date"):
        values = results[column]
        if not values.map(lambda value: pd.isna(value) or type(value) is str).all():
            return False
        if (values.notna() & pd.to_datetime(values, errors="coerce", format="%Y-%m-%d").isna()).any():
            return False
    for column in (
        "few_days_explain_most_performance",
        "positive_performance_few_sessions_explain_most",
        "negative_performance_few_sessions_explain_most",
        "losses_during_high_volatility",
        "losses_during_regime_stress",
    ):
        if not results[column].map(lambda value: pd.isna(value) or type(value) is bool).all():
            return False
    if not results["performance_concentration_basis"].map(
        lambda value: type(value) is str
        and value in {"positive_gross_log_return", "negative_gross_log_return", "flat_gross_log_return", "unavailable"}
    ).all():
        return False
    observed = pd.to_numeric(results["observed_session_count"], errors="coerce")
    available = results["diagnostic_status"].eq("available")
    if (available & observed.lt(2)).any() or (~available & observed.ne(0)).any():
        return False
    for column in ("worst_1d_return", "worst_drawdown_start", "worst_drawdown_end"):
        if available.ne(results[column].notna()).any():
            return False
    loss_cluster = pd.to_numeric(results["loss_cluster_max_days"], errors="coerce")
    if loss_cluster.gt(observed).any():
        return False
    largest_negative = pd.to_numeric(results["largest_negative_period_return"], errors="coerce")
    largest_negative_date = results["largest_negative_period_date"]
    if largest_negative.notna().ne(largest_negative_date.notna()).any():
        return False
    if largest_negative.dropna().ge(0).any():
        return False
    for column in ("worst_1d_return", "worst_5d_return", "worst_10d_return"):
        if pd.to_numeric(results[column], errors="coerce").dropna().le(-1.0).any():
            return False
    for status_column, value_column in (
        ("negative_return_concentration_status", "negative_return_concentration_share"),
        ("performance_concentration_status", "performance_concentration_share"),
        ("positive_performance_concentration_status", "positive_performance_concentration_share"),
        ("negative_performance_concentration_status", "negative_performance_concentration_share"),
    ):
        status_available = results[status_column].eq("available")
        values_present = pd.to_numeric(results[value_column], errors="coerce").notna()
        if status_available.ne(values_present).any():
            return False
    conditional_stress_fields = {
        "high_volatility_loss_status": (
            "losses_during_high_volatility",
            "high_volatility_threshold",
            "high_volatility_loss_sessions",
            "loss_sessions_observed",
        ),
        "regime_stress_loss_status": (
            "losses_during_regime_stress",
            "regime_stress_loss_sessions",
            "regime_stress_sessions_observed",
        ),
    }
    for status_column, dependent_columns in conditional_stress_fields.items():
        status_available = results[status_column].eq("available")
        if status_available.any() and any(column not in results for column in dependent_columns):
            return False
        for column in dependent_columns:
            if column in results and (status_available & results[column].isna()).any():
                return False
            if column in results and column not in {
                "losses_during_high_volatility",
                "losses_during_regime_stress",
            }:
                values = pd.to_numeric(results[column], errors="coerce")
                if (results[column].notna() & values.isna()).any():
                    return False
                if not values.dropna().map(math.isfinite).all():
                    return False
    decoded_contributions = results["largest_negative_contribution_periods"].map(
        _decode_negative_contribution_periods
    )
    if decoded_contributions.isna().any():
        return False
    results["largest_negative_contribution_periods"] = decoded_contributions
    return True


class BacktestService:
    REQUIRED_RESULT_COLUMNS = {
        "return_hit_rate",
        "average_win_return",
        "average_loss_return",
        "payoff_ratio",
        "expected_value_per_period",
        "payoff_asymmetry_warning",
        "gross_log_return",
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
        except Exception:
            structure_evidence = None
        try:
            report = _run_backtest_compatibly(
                self.config,
                prices,
                fundamentals=fundamentals,
                structure_document_registry=(structure_evidence.document_registry if structure_evidence else None),
                structure_report_records=(structure_evidence.report_records if structure_evidence else None),
                structure_supplemental_rows=(structure_evidence.supplemental_rows if structure_evidence else None),
                structure_holdings=(structure_evidence.holdings if structure_evidence else None),
                benchmark_data_id=reference_context.benchmark_data_id,
                benchmark_reference=reference_context.projection,
                reference_identity=reference_context.identity,
                benchmark_registry=reference_context.registry,
            )
            # Bind every runner result to the freshly resolved readback context
            # before publication, including older local runner seams.
            reference_binding = _reference_binding(reference_context)
            report.metadata.update(reference_binding)
            report.results["benchmark_strategy"] = reference_binding["benchmark_strategy"]
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
        persisted_results = report.results.copy()
        if "largest_negative_contribution_periods" in persisted_results:
            persisted_results["largest_negative_contribution_periods"] = persisted_results[
                "largest_negative_contribution_periods"
            ].map(lambda value: json.dumps(value, default=str, separators=(",", ":")))
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
        requests.append(
            AtomicWriteRequest(
                BACKTESTS_DIR / "backtest_metadata.json",
                json.dumps(report.metadata, default=str, sort_keys=True, indent=2).encode("utf-8"),
                lambda path: json.loads(path.read_text(encoding="utf-8")),
            )
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
        )
        sidecar_paths = tuple(_universe_cache_meta_path(path) for path in payload_paths)
        snapshot_paths = payload_paths + sidecar_paths + (metadata_path,)
        if any(not path.is_file() for path in snapshot_paths):
            return None
        try:
            structure_evidence = _load_local_structural_evidence()
        except Exception:
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
            results = pd.read_csv(BytesIO(payload_bytes[results_path]))
            if results.empty:
                return None
            if not self.REQUIRED_RESULT_COLUMNS.issubset(results.columns):
                return None
            if not _cached_tail_diagnostics_are_valid(results):
                return None
            if "quality_momentum" not in set(results.get("strategy_name", ())):
                return None
            if as_of_date is not None and "end_date" in results.columns:
                end_dates = pd.to_datetime(results["end_date"], errors="coerce").dt.date.dropna()
                if end_dates.empty or max(end_dates) != as_of_date:
                    return None
            equity_curves = pd.read_csv(BytesIO(payload_bytes[equity_path]), index_col=0, parse_dates=True)
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
            metadata = json.loads(snapshot[metadata_path].decode("utf-8"))
            if not isinstance(metadata, dict) or not _cached_backtest_binding_matches(
                metadata, reference_context
            ):
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
                load_fundamental_evidence(),
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
        decision_time = adjusted_endpoint_available_at(end_date)
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


def _reference_context_from_inputs(
    inputs: Mapping[str, object],
    *,
    purpose: str,
    analysis_id: str,
) -> CanonicalReferenceContext:
    registry = inputs.get("registry")
    if not isinstance(registry, CanonicalBenchmarkRegistry):
        registry = CanonicalBenchmarkRegistry()
    instrument_value = inputs.get("instrument")
    currency_value = inputs.get("currency")
    horizon_value = inputs.get("horizon_years")
    start_value = inputs.get("start_date")
    end_value = inputs.get("end_date")
    decision_value = inputs.get("decision_time")
    reference_ids_value = inputs.get("reference_ids", ())
    reference_ids: tuple[str, ...] = (
        tuple(reference_ids_value)
        if isinstance(reference_ids_value, Sequence)
        and not isinstance(reference_ids_value, (str, bytes))
        and all(isinstance(item, str) for item in reference_ids_value)
        else ()
    )
    return resolve_canonical_reference(
        registry,
        analysis_id=analysis_id,
        purpose=purpose,
        instrument_id="VWCE",
        instrument=instrument_value if isinstance(instrument_value, Mapping) else None,
        currency=currency_value if isinstance(currency_value, str) else None,
        horizon_years=horizon_value if isinstance(horizon_value, (int, float)) else None,
        start_date=start_value if isinstance(start_value, str) else None,
        end_date=end_value if isinstance(end_value, str) else None,
        decision_time=decision_value if isinstance(decision_value, str) else None,
        reference_portfolio_ids=reference_ids,
    )


def _backtest_calculation_context(
    config: AppConfig,
    base_context: CanonicalReferenceContext,
    prices: pd.DataFrame,
) -> CanonicalReferenceContext:
    """Resolve benchmark evidence against the complete backtest panel window."""

    resolution = base_context.resolution
    if resolution is None or not isinstance(prices, pd.DataFrame) or prices.empty:
        return base_context
    if not isinstance(base_context.instrument, Mapping):
        return CanonicalReferenceContext(
            base_context.registry,
            None,
            blocker="backtest_reference_inputs_unavailable",
        )
    required = {"date", "etf_id", "adjusted_close"}
    if not required.issubset(prices.columns):
        return base_context
    try:
        frame = prices.loc[:, ["date", "etf_id", "adjusted_close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
        columns = [item for item in config.universe.enabled_ids if item in set(frame["etf_id"].astype(str))]
        pivot = frame[frame["etf_id"].astype(str).isin(columns)].pivot(
            index="date", columns="etf_id", values="adjusted_close"
        ).sort_index()
        pivot = pivot.reindex(columns=columns)
        pivot = pivot.loc[pivot.notna().all(axis=1)]
        if pivot.empty:
            return base_context
        cutoff_date = pd.Timestamp(resolution.declaration.decision_time).date()
        pivot = pivot.loc[pivot.index.date <= cutoff_date]
        if pivot.empty:
            return base_context
        start = pivot.index.min().date()
        end = pivot.index.max().date()
        if start >= end:
            return base_context
        horizon_years = max(0.1, (end - start).days / 365.25)
        base_cutoff = pd.Timestamp(resolution.declaration.decision_time)
        # The original decision-time cutoff is authoritative.  Extending it to
        # cover a complete backtest panel would make later evidence visible.
        decision_time = base_cutoff.isoformat()
        return resolve_canonical_reference(
            base_context.registry,
            analysis_id=f"backtest:{start.isoformat()}:{end.isoformat()}",
            purpose=resolution.declaration.purpose,
            instrument_id=resolution.declaration.instrument_id,
            instrument=base_context.instrument,
            currency=resolution.declaration.currency,
            horizon_years=horizon_years,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            decision_time=decision_time,
            reference_portfolio_ids=resolution.declaration.reference_portfolio_ids,
        )
    except (BenchmarkReferenceError, OSError, TypeError, ValueError, KeyError, AttributeError):
        return CanonicalReferenceContext(base_context.registry, None, blocker="backtest_reference_resolution_unavailable")


def _backtest_prices_for_reference(
    prices: pd.DataFrame,
    reference_context: CanonicalReferenceContext,
) -> pd.DataFrame | None:
    """Replay the exact price snapshot consumed by the backtest checksum."""

    identity = reference_context.identity
    analysis = identity.get("analysis")
    if analysis is None and identity.get("status") == "unavailable":
        return prices
    if not isinstance(analysis, Mapping):
        return None
    clipped = clip_to_decision_window(
        prices,
        start_date=analysis.get("start_date"),
        end_date=analysis.get("end_date"),
        decision_time=analysis.get("decision_time"),
    )
    return None if clipped.empty else clipped


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
    etf_economics_records = load_etf_economics_records()
    etf_fund_total_return = load_total_return_evidence(ETF_FUND_TOTAL_RETURN_PATH)
    etf_benchmark_total_return = load_total_return_evidence(ETF_BENCHMARK_TOTAL_RETURN_PATH)
    etf_closure_policy = load_closure_proxy_policy()
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
