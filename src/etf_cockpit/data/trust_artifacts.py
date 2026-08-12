from __future__ import annotations

import hashlib
from dataclasses import asdict
from io import BytesIO
import json
import math
from numbers import Integral
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from etf_cockpit.core.atomic_io import (
    AtomicWriteRequest,
    atomic_write_bytes,
    atomic_write_group,
    wait_for_atomic_group,
)
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import CLEAN_DIR, DERIVED_DIR, RAW_DIR, ROOT
from etf_cockpit.core.session_log import log_event
from etf_cockpit.core.versioning import build_run_manifest, build_version_registry, ensure_run_manifest, write_version_registry
from etf_cockpit.data.trade_candidate_analysis import latest_candidate_input
from etf_cockpit.data.contracts import SourceAuthority, redact_text
from etf_cockpit.data.instrument_identity import IdentityClaim, resolve_identity
from etf_cockpit.data.evidence_ledger import EvidenceSource, ledger_entry_for_component
from etf_cockpit.data.provider_registry import PROBE_SCHEMA_VERSION, ProviderRegistry
from etf_cockpit.data.yfinance_provider import yfinance_symbol_map_from_config
from etf_cockpit.data.fund_documents import (
    FUND_DOCUMENTS_PATH,
    FundDocument,
    build_document_inventory,
    canonical_document_type,
    read_document_registry,
    unavailable_document,
)
from etf_cockpit.data.parsed_disclosures import (
    ETF_REPORT_CONFLICTS_PATH,
    ETF_REPORT_RECORDS_PATH,
    INDEX_METHODOLOGY_RECORDS_PATH,
    KID_COLUMNS,
    METHODOLOGY_COLUMNS,
    PRIIPS_KID_RECORDS_PATH,
    REPORT_COLUMNS,
    REPORT_CONFLICT_COLUMNS,
)
from etf_cockpit.data.score_history import project_classification_score_frame
from etf_cockpit.signals.feature_drivers import build_feature_drivers
from etf_cockpit.signals.canonical_scoring import load_score_policy
from etf_cockpit.features.crowding import build_correlation_clusters
from etf_cockpit.features.cash_comparison import (
    cash_comparison_from_projection,
    validate_cash_comparison_result,
)

PROVIDER_PROBE_PATH = CLEAN_DIR / "provider_probe_results.parquet"
IDENTITY_PATH = CLEAN_DIR / "instrument_identity.parquet"
SOURCE_CONFLICTS_PATH = CLEAN_DIR / "source_conflicts.parquet"
EVIDENCE_LEDGER_PATH = DERIVED_DIR / "evidence_ledger.parquet"
SCORE_COMPONENTS_PATH = DERIVED_DIR / "score_components.parquet"
SCORE_HISTORY_PATH = DERIVED_DIR / "score_history.parquet"
SCORE_METRIC_HISTORY_PATH = DERIVED_DIR / "score_metric_history.parquet"
SCORE_FORMULA_REGISTRY_PATH = DERIVED_DIR / "score_formula_registry.json"
FEATURE_DRIVERS_PATH = DERIVED_DIR / "feature_drivers.parquet"
CORRELATION_CLUSTERS_PATH = DERIVED_DIR / "correlation_clusters.parquet"
BENCHMARK_ATTRIBUTION_PATH = DERIVED_DIR / "benchmark_attribution.parquet"
FILINGS_STATEMENTS_PATH = CLEAN_DIR / "filings_statements.parquet"
ETF_DISCLOSURES_PATH = CLEAN_DIR / "etf_disclosures.parquet"
NEWS_CONTEXT_PATH = CLEAN_DIR / "news_context.parquet"
NEWS_TIMESTAMP_VALIDATION_PATH = CLEAN_DIR / "news_timestamp_validation.parquet"

SOURCE_AUTHORITY = {
    "official_regulator": 100,
    "official_filing": 95,
    "issuer_document": 85,
    "exchange": 75,
    "vendor_verified": 65,
    "vendor_unofficial": 45,
    "manual_context": 25,
    "model_advisory": 0,
    "unknown": 0,
}

PROVIDER_COLUMNS = [
    "schema_version",
    "provider_id",
    "dataset_type",
    "status",
    "authority",
    "authority_rank",
    "configured",
    "entitlement",
    "rate_limit_note",
    "last_success_at",
    "error_fingerprint",
    "score_eligible",
    "message",
    "provider_name",
    "active_provider",
    "enabled",
    "source_authority",
    "requires_api_key",
    "has_api_key",
    "base_url_configured",
    "capabilities",
    "last_probe_at",
    "executable_authority",
]

IDENTITY_COLUMNS = [
    "instrument_id",
    "display_name",
    "analysis_tier",
    "data_policy",
    "instrument_type",
    "asset_class",
    "isin",
    "isin_status",
    "yahoo_symbol",
    "provider_symbol",
    "source_group",
    "exchange",
    "currency",
    "region",
    "sector",
    "theme",
    "source",
    "identity_confidence",
    "warnings",
    "provider_symbol_map",
    "mic",
    "share_class",
    "listing",
    "issuer",
    "cik",
    "identity_source_id",
    "identity_status",
    "identity_decision_id",
    "identity_conflict_ids",
    "identity_resolution_state",
    "identity_effective_at",
    "identity_decision_time",
    "identity_objects",
    "identity_history",
    "executable_authority",
]

CONFLICT_COLUMNS = [
    "conflict_id",
    "instrument_id",
    "field_name",
    "source_a",
    "source_b",
    "value_a",
    "value_b",
    "authority_a",
    "authority_b",
    "canonical_value",
    "resolution_status",
    "requires_manual_review",
    "reason",
    "selected_source_id",
    "period",
    "unit",
    "currency",
    "as_of",
    "valid_from",
    "valid_to",
    "restatement_ids",
    "reason_code",
    "conflict_state",
    "policy_id",
    "policy_sha256",
    "decision_id",
    "review_decision_id",
    "candidate_count",
    "execution_allowed",
    "detected_at",
]

EVIDENCE_COLUMNS = [
    "evidence_id",
    "run_id",
    "instrument_id",
    "component",
    "source_id",
    "source_dataset",
    "source_name",
    "source_authority",
    "authority_rank",
    "as_of_date",
    "freshness_status",
    "conflict_status",
    "conflict_id",
    "confidence",
    "evidence_quality",
    "provider_id",
    "calculation_method",
    "score_eligible",
    "executable_authority",
    "evidence_value",
    "reason",
    "created_at",
]

SCORE_COMPONENT_COLUMNS = [
    "run_id",
    "instrument_id",
    "component",
    "source_id",
    "raw_metric",
    "normalised_score_10",
    "status",
    "authority",
    "source_dataset",
    "as_of_date",
    "freshness_status",
    "conflict_status",
    "conflict_id",
    "source_authority",
    "authority_rank",
    "evidence_quality",
    "confidence",
    "calculation_method",
    "score_eligible",
    "driver_text",
    "canonical_score_role",
    "canonical_contribution_raw",
    "peer_group",
    "uncertainty",
    "formula_version",
    "formula_checksum",
    "source_vintage_hash",
    "executable_authority",
]

SCORE_HISTORY_COLUMNS = [
    "run_id",
    "run_started_at",
    "run_completed_at",
    "instrument_id",
    "display_name",
    "yahoo_ticker",
    "asset_type",
    "analysis_tier",
    "source_group",
    "data_as_of_date",
    "price_as_of_date",
    "evidence_score_10",
    "evidence_quality_10",
    "risk_friction_10",
    "final_combined_score_10",
    "rank",
    "score_rank",
    "warnings",
    "freshness_status",
    "model_available",
    "model_availability",
    "forecast_status",
    "news_inventory",
    "backtest_trust",
    "portfolio_risk",
    "gross_expected_edge_bps",
    "estimated_total_cost_bps",
    "net_expected_edge_bps",
    "edge_to_cost_ratio",
    "cost_stress_scenario",
    "friction_status",
    "friction_reason",
    "gross_expected_return",
    "q10_expected_return",
    "q50_expected_return",
    "q90_expected_return",
    "expected_return_horizon_days",
    "net_q10_expected_return",
    "net_expected_return",
    "net_q90_expected_return",
    "expected_return_order_value_eur",
    "expected_return_cost_bps",
    "expected_return_cost_eur",
    "expected_return_cost_ratio",
    "expected_return_distribution_version",
    "expected_return_source_dataset",
    "final_label",
    "final_action",
    "reason_short",
    "reason_full",
    "blocked_by",
    "source_snapshot_hash",
    "score_schema_version",
    "canonical_attractiveness_10",
    "canonical_expected_return_10",
    "canonical_risk_implementation_10",
    "canonical_evidence_confidence_10",
    "canonical_coverage",
    "formula_version",
    "formula_checksum",
    "source_vintage_hash",
    "classification_version_id",
    "classification_invalidation_hash",
    "classification_dependency_status",
    "version_registry_signature",
    "dependency_graph_hash",
    "snapshot_hash",
    "execution_allowed",
]

SCORE_METRIC_HISTORY_COLUMNS = [
    "run_id",
    "instrument_id",
    "component_group",
    "component_name",
    "source_id",
    "raw_metric_value",
    "normalised_score_10",
    "score_available",
    "na_reason",
    "source_dataset",
    "as_of_date",
    "freshness_status",
    "authority_label",
    "formula_version",
    "formula_checksum",
    "source_vintage_hash",
    "execution_allowed",
]

FEATURE_DRIVER_COLUMNS = [
    "instrument",
    "instrument_id",
    "component",
    "source_id",
    "raw_metric",
    "normalised_score",
    "direction",
    "authority",
    "driver_text",
    "source_dataset",
    "as_of_date",
    "freshness_status",
    "classification",
    "authority_classification",
    "freshness_classification",
    "flags",
    "execution_allowed",
]

CORRELATION_CLUSTER_COLUMNS = [
    "instrument_id",
    "cluster_id",
    "cluster_label",
    "benchmark_id",
    "correlation_to_benchmark",
    "average_peer_correlation",
    "crowding_warning",
    "calculation_window_days",
    "as_of_date",
    "sector",
    "theme",
    "theme_warning",
    "sample_size",
    "pair_sample_size",
    "ranking_weight",
    "cluster_weight",
    "cluster_risk_contribution",
    "ranking_coverage",
    "top_ranked_concentration",
    "top_ranked_theme_concentration",
    "top_ranked_theme_warning",
    "source_dataset",
    "status",
    "execution_allowed",
]

BENCHMARK_ATTRIBUTION_COLUMNS = [
    "instrument_id",
    "instrument_currency",
    "benchmark_id",
    "benchmark_period_days",
    "benchmark_return",
    "instrument_period_return",
    "benchmark_beta",
    "benchmark_correlation",
    "alpha_proxy",
    "alpha_t_stat",
    "sector_theme_warning",
    "source_dataset",
    "as_of_date",
    "sector_return",
    "sector_relative_return",
    "sector_beta",
    "sector_correlation",
    "sector_alpha_proxy",
    "sector_attribution_status",
    "attribution_sample_size",
    "attribution_source_dataset",
    "theme_return",
    "theme_relative_return",
    "theme_beta",
    "theme_correlation",
    "theme_alpha_proxy",
    "theme_attribution_status",
    "theme_sample_size",
    "gross_expected_edge_bps",
    "estimated_total_cost_bps",
    "net_expected_edge_bps",
    "edge_to_cost_ratio",
    "cost_stress_scenario",
    "friction_status",
    "friction_reason",
    "cash_instrument_return",
    "cash_return",
    "excess_over_cash",
    "cash_currency",
    "cash_unit",
    "cash_dataset_kind",
    "cash_start_date",
    "cash_end_date",
    "cash_horizon_years",
    "cash_rate",
    "cash_vintage",
    "cash_comparison_status",
    "cash_comparison_reason",
    "cash_source_id",
    "cash_source_authority",
    "cash_source_checksum",
    "cash_source_terms",
    "cash_methodology",
    "cash_mapping_methodology",
    "cash_day_count",
    "cash_compounding",
    "cash_reinvestment",
    "cash_effective_at",
    "cash_published_at",
    "cash_available_at",
    "cash_curve_id",
    "cash_curve_version",
    "cash_curve_revision",
    "cash_curve_type",
    "cash_extrapolation_allowed",
    "cash_fallback",
    "cash_fallback_from",
    "cash_interpolation",
    "cash_freshness",
    "cash_freshness_status",
    "cash_decision_time",
    "cash_knowledge_cutoff",
    "inflation_context",
    "status",
    "execution_allowed",
]


def refresh_static_trust_artifacts(config: AppConfig) -> dict[str, Path]:
    paths = {
        "provider_probe_results": write_provider_probe_results(config),
        "instrument_identity": write_instrument_identity(config),
        "score_formula_registry": write_score_formula_registry(),
        "version_registry": write_version_registry(),
    }
    identity = _safe_read_parquet(IDENTITY_PATH, IDENTITY_COLUMNS)
    paths["source_conflicts"] = write_source_conflicts(identity)
    paths.update(write_optional_source_inventories(config, identity))
    _ensure_empty_if_missing(EVIDENCE_LEDGER_PATH, EVIDENCE_COLUMNS)
    _ensure_empty_if_missing(SCORE_COMPONENTS_PATH, SCORE_COMPONENT_COLUMNS)
    _ensure_empty_if_missing(SCORE_HISTORY_PATH, SCORE_HISTORY_COLUMNS)
    _ensure_empty_if_missing(SCORE_METRIC_HISTORY_PATH, SCORE_METRIC_HISTORY_COLUMNS)
    _ensure_empty_if_missing(FEATURE_DRIVERS_PATH, FEATURE_DRIVER_COLUMNS)
    _ensure_empty_if_missing(CORRELATION_CLUSTERS_PATH, CORRELATION_CLUSTER_COLUMNS)
    _ensure_empty_if_missing(BENCHMARK_ATTRIBUTION_PATH, BENCHMARK_ATTRIBUTION_COLUMNS)
    _ensure_empty_if_missing(PRIIPS_KID_RECORDS_PATH, KID_COLUMNS)
    _ensure_empty_if_missing(INDEX_METHODOLOGY_RECORDS_PATH, METHODOLOGY_COLUMNS)
    _ensure_empty_if_missing(ETF_REPORT_RECORDS_PATH, REPORT_COLUMNS)
    _ensure_empty_if_missing(ETF_REPORT_CONFLICTS_PATH, REPORT_CONFLICT_COLUMNS)
    log_event(
        event_type="trust_artifacts",
        severity="info",
        component="trust_artifacts",
        operation="refresh_static_trust_artifacts",
        status="success",
        file_paths=[str(path) for path in paths.values()],
    )
    return paths


def write_score_formula_registry() -> Path:
    policies = {asset_type: load_score_policy(asset_type).as_dict() for asset_type in ("ETF", "STOCK")}
    unsigned = {
        "schema_version": 1,
        "formula_version": "score-engine-v3.0.0",
        "policies": policies,
        "execution_allowed": False,
        "immutable_after_run": True,
    }
    signature = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    payload = {
        **unsigned,
        "signature_algorithm": "sha256-content-address",
        "registry_signature": signature,
    }
    atomic_write_bytes(
        SCORE_FORMULA_REGISTRY_PATH,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        lambda path: json.loads(path.read_text(encoding="utf-8")),
    )
    return SCORE_FORMULA_REGISTRY_PATH


def write_trust_artifacts_for_scores(
    config: AppConfig,
    scores: Iterable[Any],
    scoreboard: pd.DataFrame,
    prices: pd.DataFrame | None = None,
) -> dict[str, Path]:
    scores = list(scores)
    ranked_instruments = [str(getattr(score, "display_id", "")) for score in scores[:10]]
    now = _utc_now()
    run_id = f"score_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    manifest_dependencies = (
        "schema:local-storage",
        "formula:score-engine-v3",
        "feature:feature-registry",
        "policy:gate-policy",
        "dataset:universe",
        "policy:portfolio-targets",
        "policy:risk-limits",
        "policy:costs",
        "policy:model-settings",
        "policy:strategy-scope",
        "model:baseline",
    )
    refresh_static_trust_artifacts(config)
    run_manifest = build_run_manifest(run_id, manifest_dependencies)
    paths = {
        "evidence_ledger": write_evidence_ledger(scores, run_id=run_id, created_at=now),
        "score_components": write_score_components(scores, run_id=run_id, created_at=now),
        "score_history": append_score_history(
            scores,
            run_id=run_id,
            created_at=now,
            version_registry_signature=str(run_manifest["registry_signature"]),
            dependency_graph_hash=str(run_manifest["dependency_graph_hash"]),
        ),
        "score_metric_history": append_score_metric_history(scores, run_id=run_id, created_at=now),
        "feature_drivers": write_feature_drivers(scores),
        "correlation_clusters": write_correlation_clusters(
            prices,
            _configured_metadata(config),
            ranked_instruments=ranked_instruments,
            weights={instrument_id: 1.0 for instrument_id in ranked_instruments},
        ),
        "benchmark_attribution": write_benchmark_attribution(scoreboard),
    }
    paths["version_registry"] = write_version_registry()
    paths["run_manifest"] = ensure_run_manifest(
        run_id,
        manifest_dependencies,
    )
    log_event(
        event_type="trust_artifacts",
        severity="info",
        component="trust_artifacts",
        operation="write_trust_artifacts_for_scores",
        status="success",
        row_counts={name: _safe_row_count(path) for name, path in paths.items()},
        file_paths=[str(path) for path in paths.values()],
    )
    return paths


def write_provider_probe_results(config: AppConfig) -> Path:
    now = _utc_now()
    registry = ProviderRegistry(config.data_providers)
    capabilities = registry.probe_all()
    # Publish one atomic frame containing both canonical capability fields and
    # legacy aliases.  Existing consumers can continue reading their aliases
    # without dropping the versioned registry contract.
    rows: list[dict[str, Any]] = []
    for item in capabilities:
        section, dataset_type = _provider_section_for(config, item.provider_id)
        active = (section.active_provider or "none").strip().lower()
        legacy_authority = _legacy_provider_authority(item.authority)
        canonical = item.to_dict()
        rows.append(
            {
                **canonical,
                "schema_version": PROBE_SCHEMA_VERSION,
                "provider_id": canonical["provider_id"],
                "dataset_type": canonical["dataset_type"],
                "provider_name": canonical["provider_id"],
                "active_provider": redact_text(active),
                "enabled": item.configured,
                "source_authority": legacy_authority,
                "requires_api_key": _provider_requires_api_key(item.provider_id, active),
                "has_api_key": bool(section.api_key),
                "base_url_configured": bool(section.base_url),
                "capabilities": canonical["dataset_type"],
                "last_probe_at": now,
                "executable_authority": False,
            }
        )
    frame = pd.DataFrame(rows, columns=PROVIDER_COLUMNS)
    frame.attrs["schema_version"] = PROBE_SCHEMA_VERSION
    return _write_dual(frame, PROVIDER_PROBE_PATH)


def write_instrument_identity(config: AppConfig) -> Path:
    symbol_map = yfinance_symbol_map_from_config(config)
    rows: list[dict[str, Any]] = []
    for etf in config.universe.etfs:
        yahoo_symbol = symbol_map.get(etf.id) or etf.provider_symbol or etf.ticker
        extras = getattr(etf, "__pydantic_extra__", {}) or {}
        source_id = f"config:universe:{etf.id}"
        claims = [
            IdentityClaim(etf.id, "name", etf.name, "universe", SourceAuthority.MANUAL, source_id),
            IdentityClaim(etf.id, "ticker", etf.ticker, "universe", SourceAuthority.MANUAL, source_id),
            IdentityClaim(etf.id, "isin", etf.isin or "", "universe", SourceAuthority.MANUAL, source_id),
            IdentityClaim(etf.id, "exchange", etf.exchange or "", "universe", SourceAuthority.MANUAL, source_id),
            IdentityClaim(etf.id, "currency", etf.currency or "", "universe", SourceAuthority.MANUAL, source_id),
            IdentityClaim(etf.id, "asset_type", _instrument_type(etf.asset_class), "universe", SourceAuthority.MANUAL, source_id),
            IdentityClaim(etf.id, "provider_symbol", yahoo_symbol or "", "yfinance", SourceAuthority.VENDOR, f"yfinance:identity:{etf.id}"),
        ]
        for field in ("mic", "share_class", "listing", "issuer", "cik"):
            extra_value = extras.get(field)
            if extra_value:
                claims.append(IdentityClaim(etf.id, field, str(extra_value), "issuer", SourceAuthority.ISSUER, f"issuer:identity:{etf.id}"))
        resolution = resolve_identity(claims)
        identity = resolution.identity
        warnings = list(identity.warnings)
        if not yahoo_symbol:
            warnings.append("missing_yfinance_symbol")
        rows.append(
            {
                "instrument_id": etf.id,
                "display_name": etf.name,
                "analysis_tier": str(extras.get("analysis_tier") or "primary"),
                "data_policy": str(extras.get("data_policy") or "yfinance_now_multi_provider_later"),
                "instrument_type": str(extras.get("instrument_type") or _instrument_type(etf.asset_class)),
                "asset_class": etf.asset_class,
                "isin": identity.isin or "",
                "isin_status": identity.isin_status,
                "yahoo_symbol": identity.provider_symbols.get("yfinance", yahoo_symbol),
                "provider_symbol": etf.provider_symbol or identity.provider_symbols.get("yfinance", yahoo_symbol),
                "source_group": "Primary tier",
                "exchange": identity.exchange or "",
                "currency": identity.currency or "",
                "region": etf.region or "",
                "sector": etf.sector or "",
                "theme": etf.theme or "",
                "source": "configs/universe.yaml",
                "identity_confidence": identity.confidence,
                "warnings": "|".join(dict.fromkeys(warnings)),
                "provider_symbol_map": json.dumps(dict(identity.provider_symbols), sort_keys=True),
                "mic": identity.mic or "",
                "share_class": identity.share_class or "",
                "listing": identity.listing or "",
                "issuer": identity.issuer or "",
                "cik": identity.cik or "",
                "identity_source_id": source_id,
                "identity_status": "manual_review" if resolution.requires_manual_review else "resolved",
                "identity_decision_id": resolution.decision_id,
                "identity_conflict_ids": json.dumps([item.conflict_id for item in resolution.conflicts], sort_keys=True),
                "identity_resolution_state": resolution.resolution_state,
                "identity_effective_at": resolution.effective_at or "latest",
                "identity_decision_time": resolution.decision_time or "latest",
                "identity_objects": json.dumps([asdict(item) for item in resolution.objects], sort_keys=True),
                "identity_history": json.dumps([asdict(item) for item in resolution.history], sort_keys=True),
                "executable_authority": False,
            }
        )
    rows.extend(_candidate_identity_rows(config))
    frame = pd.DataFrame(rows, columns=IDENTITY_COLUMNS)
    return _write_dual(frame, IDENTITY_PATH)


def write_source_conflicts(identity: pd.DataFrame | Any) -> Path:
    rows: list[dict[str, Any]] = []
    now = _utc_now()
    if not isinstance(identity, pd.DataFrame):
        for conflict in getattr(identity, "conflicts", ()) or ():
            source_ids = tuple(getattr(conflict, "source_ids", ()) or ())
            rows.append(
                {
                    "conflict_id": str(getattr(conflict, "conflict_id", "") or ""),
                    "instrument_id": str(getattr(conflict, "instrument_id", "") or ""),
                    "field_name": str(getattr(conflict, "field", "") or ""),
                    "source_a": redact_text(source_ids[0] if source_ids else "unknown"),
                    "source_b": redact_text(source_ids[1] if len(source_ids) > 1 else "unknown"),
                    "value_a": redact_text(getattr(conflict, "values", (None,))[0] if getattr(conflict, "values", ()) else ""),
                    "value_b": redact_text(getattr(conflict, "values", (None,))[1] if len(getattr(conflict, "values", ())) > 1 else ""),
                    "authority_a": "unknown",
                    "authority_b": "unknown",
                    "canonical_value": redact_text(getattr(conflict, "canonical_value", getattr(conflict, "selected_value", ""))),
                    "resolution_status": str(getattr(conflict, "resolution_status", "manual_review")),
                    "requires_manual_review": bool(getattr(conflict, "requires_manual_review", True)),
                    "reason": redact_text(getattr(conflict, "reason", "Conflict retained for manual review.")),
                    "selected_source_id": redact_text(getattr(conflict, "canonical_source_id", getattr(conflict, "selected_source_id", ""))),
                    "period": str(getattr(conflict, "period", "unavailable")),
                    "unit": str(getattr(conflict, "unit", "unavailable")),
                    "currency": str(getattr(conflict, "currency", "unavailable")),
                    "as_of": str(getattr(conflict, "as_of", "unavailable")),
                    "valid_from": str(getattr(conflict, "valid_from", "unavailable")),
                    "valid_to": str(getattr(conflict, "valid_to", "open")),
                    "restatement_ids": json.dumps(list(getattr(conflict, "restatement_ids", ()) or ()), sort_keys=True),
                    "reason_code": str(getattr(conflict, "reason_code", "identity_value_conflict")),
                    "conflict_state": str(getattr(conflict, "state", "quarantine")),
                    "policy_id": str(getattr(conflict, "policy_id", "unavailable")),
                    "policy_sha256": str(getattr(conflict, "policy_sha256", "unavailable")),
                    "decision_id": str(getattr(conflict, "decision_id", "unavailable")),
                    "review_decision_id": str(getattr(conflict, "review_decision_id", "")),
                    "candidate_count": int(
                        getattr(conflict, "candidate_count", 0)
                        or len(getattr(conflict, "source_ids", ()) or ())
                    ),
                    "execution_allowed": False,
                    "detected_at": now,
                }
            )
        return _write_dual(pd.DataFrame(rows, columns=CONFLICT_COLUMNS), SOURCE_CONFLICTS_PATH)
    for field_name in ("isin", "yahoo_symbol", "listing"):
        if identity.empty or field_name not in identity.columns:
            continue
        duplicates = identity[identity[field_name].astype(str).str.strip() != ""].copy()
        if duplicates.empty:
            continue
        duplicate_values = duplicates[duplicates.duplicated(field_name, keep=False)]
        for value, group in duplicate_values.groupby(field_name):
            ids = sorted(group["instrument_id"].astype(str))
            if len(ids) < 2:
                continue
            rows.append(
                {
                    "conflict_id": hashlib.sha256(f"{field_name}:{value}:{ids}".encode()).hexdigest()[:16],
                    "instrument_id": "|".join(ids),
                    "field_name": field_name,
                    "source_a": redact_text(group.iloc[0].get("source") or "unknown"),
                    "source_b": redact_text(group.iloc[1].get("source") or "unknown"),
                    "value_a": redact_text(value),
                    "value_b": redact_text(value),
                    "authority_a": "manual_context",
                    "authority_b": "manual_context",
                    "canonical_value": str(value),
                    "resolution_status": "duplicate_identity_requires_manual_review",
                    "requires_manual_review": True,
                    "reason": f"Duplicate canonical {field_name} value {value!r} is mapped to multiple instruments; identity merge is forbidden without manual review.",
                    "selected_source_id": "",
                    "period": "unavailable",
                    "unit": "unavailable",
                    "currency": "unavailable",
                    "as_of": "unavailable",
                    "valid_from": "unavailable",
                    "valid_to": "open",
                    "restatement_ids": "[]",
                    "reason_code": "duplicate_identity",
                    "conflict_state": "quarantine",
                    "policy_id": "identity-deduplication.v1",
                    "policy_sha256": "unavailable",
                    "decision_id": hashlib.sha256(f"duplicate:{field_name}:{value}:{ids}".encode()).hexdigest(),
                    "review_decision_id": "",
                    "candidate_count": len(ids),
                    "execution_allowed": False,
                    "detected_at": now,
                }
            )
    frame = pd.DataFrame(rows, columns=CONFLICT_COLUMNS)
    return _write_dual(frame, SOURCE_CONFLICTS_PATH)


def _component_source_id(component: Any) -> str:
    return str(getattr(component, "source_id", "") or "").strip()


def _source_dataset(source_id: str) -> str:
    return source_id.split(":", 1)[0] if source_id else "unavailable"


def _source_authority(source_id: str, component_authority: str) -> str:
    if not source_id:
        return "unknown"
    dataset = _source_dataset(source_id)
    dataset_authority = {
        "sec_edgar": "official_regulator",
        "esef": "official_filing",
        "issuer_document": "issuer_document",
        "priips_kid": "issuer_document",
        "index_methodology": "issuer_document",
        "etf_disclosures": "issuer_document",
        "yfinance": "vendor_unofficial",
        "rss": "manual_context",
        "manual": "manual_context",
        "model": "model_advisory",
    }
    if dataset in dataset_authority:
        return dataset_authority[dataset]
    return "vendor_unofficial" if component_authority in {"medium", "low"} else "unknown"


def _source_authority_enum(label: str) -> SourceAuthority:
    return {
        "official_regulator": SourceAuthority.OFFICIAL,
        "official_filing": SourceAuthority.OFFICIAL,
        "issuer_document": SourceAuthority.ISSUER,
        "vendor_verified": SourceAuthority.VENDOR,
        "vendor_unofficial": SourceAuthority.VENDOR,
        "manual_context": SourceAuthority.COMMUNITY,
        "model_advisory": SourceAuthority.MODEL,
    }.get(label, SourceAuthority.MANUAL)


def _component_score_eligible(component: Any) -> bool:
    typed_eligible = getattr(component, "score_eligible", None)
    if isinstance(typed_eligible, bool):
        return typed_eligible
    source_id = _component_source_id(component)
    source_dataset = _source_dataset(source_id).lower()
    status = str(getattr(component, "status", "") or "").strip().lower()
    return (
        getattr(component, "score_10", None) is not None
        and bool(source_id)
        and status == "ok"
        and source_dataset not in {"model", "community", "news", "rss", "candle"}
        and not getattr(component, "conflict_id", None)
        and str(getattr(component, "freshness_status", "") or "").strip().lower() not in {"stale", "stale_block", "unavailable", "missing", "missing_or_pending", "not_checked"}
    )


def write_evidence_ledger(scores: Iterable[Any], *, run_id: str, created_at: str) -> Path:
    rows: list[dict[str, Any]] = []
    for score in scores:
        instrument_id = str(getattr(score, "display_id", ""))
        latest_date = str(getattr(score, "latest_date", "") or "")
        for component in getattr(score, "components", []) or []:
            source_id = _component_source_id(component)
            source_authority = str(getattr(component, "source_authority", "") or "") or _source_authority(source_id, str(getattr(component, "authority", "medium") or "medium"))
            source_freshness = str(getattr(component, "freshness_status", "") or "").strip().lower() or _freshness_from_date(str(getattr(component, "as_of_date", "") or latest_date))
            source_obj = EvidenceSource(
                dataset=_source_dataset(source_id),
                source_id=redact_text(source_id),
                authority=_source_authority_enum(source_authority),
                as_of_date=str(getattr(component, "as_of_date", "") or latest_date) or None,
                freshness_status=source_freshness,
                confidence=getattr(component, "confidence", None),
                quality=getattr(component, "evidence_quality", None),
                provider_id=_source_dataset(source_id) or None,
                conflict_id=getattr(component, "conflict_id", None),
            )
            typed_entry = ledger_entry_for_component(
                instrument_id,
                str(getattr(component, "key", "")),
                getattr(component, "score_10", None),
                source_obj,
                conflict_id=getattr(component, "conflict_id", None),
            )
            eligible = typed_entry.score_eligible and _component_score_eligible(component)
            rows.append(
                {
                    "evidence_id": hashlib.sha256(f"{run_id}:{instrument_id}:{getattr(component, 'key', '')}".encode()).hexdigest()[:20],
                    "run_id": run_id,
                    "instrument_id": instrument_id,
                    "component": getattr(component, "key", ""),
                    "source_id": redact_text(source_id),
                    "source_dataset": _source_dataset(source_id),
                    "source_name": redact_text(source_id) or "unavailable",
                    "source_authority": source_authority,
                    "authority_rank": SOURCE_AUTHORITY.get(source_authority, 0),
                    "as_of_date": source_obj.as_of_date,
                    "freshness_status": source_freshness,
                    "conflict_status": getattr(component, "conflict_id", None) or ("not_checked" if latest_date == "pending refresh" else "no_known_conflict"),
                    "conflict_id": getattr(component, "conflict_id", None),
                    "confidence": getattr(component, "confidence", None),
                    "evidence_quality": getattr(component, "evidence_quality", None),
                    "provider_id": source_obj.provider_id,
                    "calculation_method": redact_text(getattr(component, "explanation", "")),
                    "score_eligible": eligible,
                    "executable_authority": False,
                    "evidence_value": getattr(component, "score_10", None),
                    "reason": redact_text(typed_entry.reason if not eligible else getattr(component, "why", "")),
                    "created_at": created_at,
                }
            )
    return _write_dual(pd.DataFrame(rows, columns=EVIDENCE_COLUMNS), EVIDENCE_LEDGER_PATH)


def write_score_components(scores: Iterable[Any], *, run_id: str, created_at: str) -> Path:
    rows: list[dict[str, Any]] = []
    for score in scores:
        canonical_rows = {
            str(row.get("key")): row
            for row in (getattr(getattr(score, "canonical_score", None), "components", ()) or ())
            if isinstance(row, dict)
        }
        canonical = getattr(score, "canonical_score", None)
        for component in getattr(score, "components", []) or []:
            score_value = getattr(component, "score_10", None)
            source_id = _component_source_id(component)
            source_authority = str(getattr(component, "source_authority", "") or "") or _source_authority(source_id, str(getattr(component, "authority", "medium") or "medium"))
            source_freshness = str(getattr(component, "freshness_status", "") or "").strip().lower() or _freshness_from_date(str(getattr(score, "latest_date", "")))
            rows.append(
                {
                    "run_id": run_id,
                    "instrument_id": getattr(score, "display_id", ""),
                    "component": getattr(component, "key", ""),
                    "source_id": redact_text(source_id),
                    "raw_metric": getattr(component, "raw_score", None),
                    "normalised_score_10": score_value,
                    "status": getattr(component, "status", ""),
                    "authority": getattr(component, "authority", ""),
                    "source_dataset": _source_dataset(source_id),
                    "as_of_date": getattr(component, "as_of_date", None) or getattr(score, "latest_date", ""),
                    "freshness_status": source_freshness,
                    "conflict_status": getattr(component, "conflict_id", None) or ("not_checked" if getattr(score, "latest_date", "") == "pending refresh" else "no_known_conflict"),
                    "conflict_id": getattr(component, "conflict_id", None),
                    "source_authority": source_authority,
                    "authority_rank": SOURCE_AUTHORITY.get(source_authority, 0),
                    "evidence_quality": getattr(component, "evidence_quality", None),
                    "confidence": getattr(component, "confidence", None),
                    "calculation_method": redact_text(getattr(component, "explanation", "")),
                    "score_eligible": _component_score_eligible(component),
                    "driver_text": redact_text(getattr(component, "why", "")),
                    "canonical_score_role": canonical_rows.get(str(getattr(component, "key", "")), {}).get("score_role"),
                    "canonical_contribution_raw": canonical_rows.get(str(getattr(component, "key", "")), {}).get("contribution_raw"),
                    "peer_group": canonical_rows.get(str(getattr(component, "key", "")), {}).get("peer_group"),
                    "uncertainty": canonical_rows.get(str(getattr(component, "key", "")), {}).get("uncertainty"),
                    "formula_version": getattr(canonical, "formula_version", "unavailable"),
                    "formula_checksum": getattr(canonical, "formula_checksum", "unavailable"),
                    "source_vintage_hash": getattr(canonical, "source_vintage_hash", "unavailable"),
                    "executable_authority": False,
                }
            )
    return _write_dual(pd.DataFrame(rows, columns=SCORE_COMPONENT_COLUMNS), SCORE_COMPONENTS_PATH)


def append_score_history(
    scores: Iterable[Any],
    *,
    run_id: str,
    created_at: str,
    version_registry_signature: str = "unavailable",
    dependency_graph_hash: str = "unavailable",
) -> Path:
    scores = list(scores)
    if version_registry_signature == "unavailable":
        version_registry_signature = str(build_version_registry().get("registry_signature", "unavailable"))
    ranked_ids = {
        str(getattr(score, "display_id", "")): rank
        for rank, score in enumerate(
            sorted(
                scores,
                key=_score_sort_key,
            ),
            start=1,
        )
    }
    rows: list[dict[str, Any]] = []
    for score in scores:
        warnings = "|".join(str(item).strip() for item in (getattr(score, "warnings", []) or []) if str(item).strip()) or "unavailable"
        rank = getattr(score, "rank", None)
        score_rank = getattr(score, "score_rank", None)
        if rank is None:
            rank = ranked_ids.get(str(getattr(score, "display_id", "")))
        if score_rank is None:
            score_rank = rank
        rows.append(
            {
                "run_id": run_id,
                "run_started_at": created_at,
                "run_completed_at": created_at,
                "instrument_id": getattr(score, "display_id", ""),
                "display_name": getattr(score, "name", ""),
                "yahoo_ticker": getattr(score, "yahoo_symbol", ""),
                "asset_type": getattr(score, "asset_type", ""),
                "analysis_tier": getattr(score, "analysis_tier", ""),
                "source_group": getattr(score, "source_group", ""),
                "data_as_of_date": getattr(score, "latest_date", ""),
                "price_as_of_date": getattr(score, "latest_date", ""),
                "evidence_score_10": getattr(score, "evidence_score_10", None),
                "evidence_quality_10": getattr(score, "evidence_quality_10", None),
                "risk_friction_10": getattr(score, "risk_friction_10", None),
                "final_combined_score_10": getattr(score, "final_score_10", None),
                "rank": rank,
                "score_rank": score_rank,
                "warnings": warnings,
                "freshness_status": _score_freshness(score),
                "model_available": _model_available(score),
                "model_availability": _model_availability(score),
                "forecast_status": _forecast_status(score),
                "news_inventory": getattr(score, "news_inventory", None) if getattr(score, "news_inventory", None) is not None else "unavailable",
                "backtest_trust": getattr(score, "backtest_trust_label", None) or "unavailable",
                "portfolio_risk": getattr(score, "portfolio_fit_label", None) or "unavailable",
                "gross_expected_edge_bps": getattr(score, "gross_expected_edge_bps", None),
                "estimated_total_cost_bps": getattr(score, "estimated_total_cost_bps", None),
                "net_expected_edge_bps": getattr(score, "net_expected_edge_bps", None),
                "edge_to_cost_ratio": getattr(score, "edge_to_cost_ratio", None),
                "cost_stress_scenario": getattr(score, "cost_stress_scenario", "unavailable"),
                "friction_status": getattr(score, "friction_status", "unavailable"),
                "friction_reason": getattr(score, "friction_reason", "Friction-adjusted edge unavailable."),
                "gross_expected_return": getattr(score, "gross_expected_return", None),
                "q10_expected_return": getattr(score, "q10_expected_return", None),
                "q50_expected_return": getattr(score, "q50_expected_return", None),
                "q90_expected_return": getattr(score, "q90_expected_return", None),
                "expected_return_horizon_days": getattr(score, "expected_return_horizon_days", None),
                "net_q10_expected_return": getattr(score, "net_q10_expected_return", None),
                "net_expected_return": getattr(score, "net_expected_return", None),
                "net_q90_expected_return": getattr(score, "net_q90_expected_return", None),
                "expected_return_order_value_eur": getattr(score, "expected_return_order_value_eur", None),
                "expected_return_cost_bps": getattr(score, "expected_return_cost_bps", None),
                "expected_return_cost_eur": getattr(score, "expected_return_cost_eur", None),
                "expected_return_cost_ratio": getattr(score, "expected_return_cost_ratio", None),
                "expected_return_distribution_version": getattr(
                    score,
                    "expected_return_distribution_version",
                    "expected-return-distribution.v1",
                ),
                "expected_return_source_dataset": getattr(
                    score,
                    "expected_return_source_dataset",
                    "forecast_return_distribution",
                ),
                "final_label": getattr(score, "final_label", ""),
                "final_action": getattr(score, "final_action", ""),
                "reason_short": getattr(score, "one_line_reason", ""),
                "reason_full": getattr(score, "one_line_reason", ""),
                "blocked_by": "|".join(getattr(score, "warnings", []) or []),
                "source_snapshot_hash": _score_snapshot_hash(score),
                "score_schema_version": "simple_scores_v3_groups",
                "canonical_attractiveness_10": getattr(getattr(score, "canonical_score", None), "attractiveness_10", None),
                "canonical_expected_return_10": getattr(getattr(score, "canonical_score", None), "expected_return_10", None),
                "canonical_risk_implementation_10": getattr(getattr(score, "canonical_score", None), "risk_implementation_10", None),
                "canonical_evidence_confidence_10": getattr(getattr(score, "canonical_score", None), "evidence_confidence_10", None),
                "canonical_coverage": getattr(getattr(score, "canonical_score", None), "coverage", 0.0),
                "formula_version": getattr(getattr(score, "canonical_score", None), "formula_version", "unavailable"),
                "formula_checksum": getattr(getattr(score, "canonical_score", None), "formula_checksum", "unavailable"),
                "source_vintage_hash": getattr(getattr(score, "canonical_score", None), "source_vintage_hash", "unavailable"),
                "classification_version_id": getattr(score, "classification_version_id", "unavailable"),
                "classification_invalidation_hash": getattr(score, "classification_invalidation_hash", "unavailable"),
                "classification_dependency_status": getattr(score, "classification_dependency_status", "legacy_unbound"),
                "version_registry_signature": version_registry_signature,
                "dependency_graph_hash": dependency_graph_hash,
                "snapshot_hash": "",
                "execution_allowed": False,
            }
        )
    new_frame = pd.DataFrame(rows, columns=SCORE_HISTORY_COLUMNS)
    snapshot_hash = _run_snapshot_hash(new_frame)
    new_frame["snapshot_hash"] = snapshot_hash
    return _append_parquet(
        SCORE_HISTORY_PATH,
        new_frame,
        SCORE_HISTORY_COLUMNS,
        id_columns=["run_id", "instrument_id"],
        snapshot_hash_column="snapshot_hash",
        run_id=run_id,
    )


def append_score_metric_history(scores: Iterable[Any], *, run_id: str, created_at: str) -> Path:
    rows: list[dict[str, Any]] = []
    for score in scores:
        for component in getattr(score, "components", []) or []:
            score_value = getattr(component, "score_10", None)
            source_id = _component_source_id(component)
            rows.append(
                {
                    "run_id": run_id,
                    "instrument_id": getattr(score, "display_id", ""),
                    "component_group": getattr(component, "score_role", "evidence"),
                    "component_name": getattr(component, "key", ""),
                    "source_id": source_id,
                    "raw_metric_value": getattr(component, "raw_score", None),
                    "normalised_score_10": score_value,
                    "score_available": score_value is not None,
                    "na_reason": "" if score_value is not None else getattr(component, "why", "score unavailable"),
                    "source_dataset": _source_dataset(source_id),
                    "as_of_date": getattr(score, "latest_date", ""),
                    "freshness_status": _freshness_from_date(str(getattr(score, "latest_date", ""))),
                    "authority_label": getattr(component, "authority", ""),
                    "formula_version": getattr(getattr(score, "canonical_score", None), "formula_version", "unavailable"),
                    "formula_checksum": getattr(getattr(score, "canonical_score", None), "formula_checksum", "unavailable"),
                    "source_vintage_hash": getattr(getattr(score, "canonical_score", None), "source_vintage_hash", "unavailable"),
                    "execution_allowed": False,
                }
            )
    new_frame = pd.DataFrame(rows, columns=SCORE_METRIC_HISTORY_COLUMNS)
    return _append_parquet(SCORE_METRIC_HISTORY_PATH, new_frame, SCORE_METRIC_HISTORY_COLUMNS, id_columns=["run_id", "instrument_id", "component_name"])


def write_feature_drivers(scores: Iterable[Any]) -> Path:
    frame = build_feature_drivers(scores)
    return _write_dual(frame.reindex(columns=FEATURE_DRIVER_COLUMNS), FEATURE_DRIVERS_PATH)


def write_correlation_clusters(
    prices: pd.DataFrame | None,
    metadata: dict[str, object] | None = None,
    *,
    window: int = 120,
    ranked_instruments: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> Path:
    report = build_correlation_clusters(
        prices if isinstance(prices, pd.DataFrame) else pd.DataFrame(),
        metadata or {},
        window=window,
        ranked_instruments=ranked_instruments,
        weights=weights,
    )
    rows = [
        {
            "instrument_id": row.instrument_id,
            "cluster_id": row.cluster_id,
            "cluster_label": row.cluster_label,
            "benchmark_id": "",
            "correlation_to_benchmark": None,
            "average_peer_correlation": row.average_peer_correlation,
            "crowding_warning": row.crowding_warning,
            "calculation_window_days": report.window,
            "as_of_date": row.as_of,
            "sector": row.sector,
            "theme": row.theme,
            "theme_warning": row.theme_warning,
            "sample_size": row.sample_size,
            "pair_sample_size": row.pair_sample_size,
            "ranking_weight": row.ranking_weight,
            "cluster_weight": row.cluster_weight,
            "cluster_risk_contribution": row.cluster_risk_contribution,
            "ranking_coverage": row.ranking_coverage,
            "top_ranked_concentration": row.top_ranked_concentration,
            "top_ranked_theme_concentration": row.top_ranked_theme_concentration,
            "top_ranked_theme_warning": row.top_ranked_theme_warning,
            "source_dataset": row.source_dataset,
            "status": report.status,
            "execution_allowed": False,
        }
        for row in report.rows
    ]
    return _write_dual(pd.DataFrame(rows, columns=CORRELATION_CLUSTER_COLUMNS), CORRELATION_CLUSTERS_PATH)


def write_benchmark_attribution(scoreboard: pd.DataFrame) -> Path:
    if scoreboard.empty:
        return _write_dual(pd.DataFrame(columns=BENCHMARK_ATTRIBUTION_COLUMNS), BENCHMARK_ATTRIBUTION_PATH)
    rows = []
    for _, row in scoreboard.iterrows():
        raw_cash = cash_comparison_from_projection(row.to_dict())
        expected_currency = row.get("instrument_currency")
        if expected_currency is None or pd.isna(expected_currency):
            expected_currency = None
        if raw_cash.get("status") == "available" and expected_currency is None:
            raw_cash = {
                "status": "unavailable",
                "reason": "instrument currency is unavailable for cash comparison",
                "execution_allowed": False,
            }
        cash = validate_cash_comparison_result(
            raw_cash,
            expected_currency=expected_currency,
        ).as_dict()
        rows.append(
            {
                "instrument_id": row.get("instrument_id"),
                "instrument_currency": row.get("instrument_currency"),
                "benchmark_id": row.get("benchmark_id"),
                "benchmark_period_days": row.get("benchmark_period_days"),
                "benchmark_return": row.get("benchmark_return"),
                "instrument_period_return": row.get("instrument_period_return"),
                "benchmark_beta": row.get("benchmark_beta"),
                "benchmark_correlation": row.get("benchmark_correlation"),
                "alpha_proxy": row.get("alpha_proxy"),
                "alpha_t_stat": row.get("alpha_t_stat"),
                "sector_theme_warning": row.get("sector_theme_warning"),
                "sector_return": row.get("sector_return"),
                "sector_relative_return": row.get("sector_relative_return"),
                "sector_beta": row.get("sector_beta"),
                "sector_correlation": row.get("sector_correlation"),
                "sector_alpha_proxy": row.get("sector_alpha_proxy"),
                "sector_attribution_status": row.get("sector_attribution_status", "N/A"),
                "attribution_sample_size": row.get("attribution_sample_size"),
                "attribution_source_dataset": row.get("attribution_source_dataset", "adjusted_price_returns"),
                "theme_return": row.get("theme_return"),
                "theme_relative_return": row.get("theme_relative_return"),
                "theme_beta": row.get("theme_beta"),
                "theme_correlation": row.get("theme_correlation"),
                "theme_alpha_proxy": row.get("theme_alpha_proxy"),
                "theme_attribution_status": row.get("theme_attribution_status", "N/A"),
                "theme_sample_size": row.get("theme_sample_size"),
                "gross_expected_edge_bps": row.get("gross_expected_edge_bps"),
                "estimated_total_cost_bps": row.get("estimated_total_cost_bps"),
                "net_expected_edge_bps": row.get("net_expected_edge_bps"),
                "edge_to_cost_ratio": row.get("edge_to_cost_ratio"),
                "cost_stress_scenario": row.get("cost_stress_scenario"),
                "friction_status": row.get("friction_status", "unavailable"),
                "friction_reason": row.get("friction_reason", "Friction-adjusted edge unavailable."),
                "cash_instrument_return": cash.get("instrument_return"),
                "cash_return": cash.get("cash_return"),
                "excess_over_cash": cash.get("excess_over_cash"),
                "cash_currency": cash.get("currency"),
                "cash_unit": cash.get("unit"),
                "cash_dataset_kind": cash.get("dataset_kind"),
                "cash_start_date": cash.get("start_date"),
                "cash_end_date": cash.get("end_date"),
                "cash_horizon_years": cash.get("horizon_years"),
                "cash_rate": cash.get("rate"),
                "cash_vintage": cash.get("vintage"),
                "cash_comparison_status": cash["status"],
                "cash_comparison_reason": cash.get("reason"),
                "cash_source_id": cash.get("source_id"),
                "cash_source_authority": cash.get("source_authority"),
                "cash_source_checksum": cash.get("source_checksum"),
                "cash_source_terms": cash.get("source_terms"),
                "cash_methodology": cash.get("methodology"),
                "cash_mapping_methodology": cash.get("mapping_methodology"),
                "cash_day_count": cash.get("day_count"),
                "cash_compounding": cash.get("compounding"),
                "cash_reinvestment": cash.get("reinvestment"),
                "cash_effective_at": cash.get("effective_at"),
                "cash_published_at": cash.get("published_at"),
                "cash_available_at": cash.get("available_at"),
                "cash_curve_id": cash.get("curve_id"),
                "cash_curve_version": cash.get("curve_version"),
                "cash_curve_revision": cash.get("curve_revision"),
                "cash_curve_type": cash.get("curve_type"),
                "cash_extrapolation_allowed": cash.get("extrapolation_allowed"),
                "cash_fallback": cash.get("fallback"),
                "cash_fallback_from": cash.get("fallback_from"),
                "cash_interpolation": cash.get("interpolation"),
                "cash_freshness": cash.get("freshness"),
                "cash_freshness_status": cash.get("freshness_status"),
                "cash_decision_time": cash.get("decision_time"),
                "cash_knowledge_cutoff": cash.get("knowledge_cutoff"),
                "inflation_context": cash.get("inflation_context"),
                "source_dataset": "derived_scoreboard",
                "as_of_date": row.get("latest_price_date"),
                "status": row.get("analysis_status", "unavailable"),
                "execution_allowed": False,
            }
        )
    revision_values = [row.get("cash_curve_revision") for row in rows]
    frame = pd.DataFrame(rows, columns=BENCHMARK_ATTRIBUTION_COLUMNS)
    frame["cash_curve_revision"] = _strict_nullable_revision_array(
        revision_values
    )
    return _write_dual(frame, BENCHMARK_ATTRIBUTION_PATH)


def _strict_nullable_revision_array(values: list[object]) -> pd.arrays.IntegerArray:
    normalised: list[int | None] = []
    for value in values:
        if value is None or pd.isna(value):
            normalised.append(None)
            continue
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise ValueError("cash_curve_revision must be a nullable integer")
        normalised.append(int(value))
    return pd.array(normalised, dtype="Int64")


def _configured_metadata(config: AppConfig | None) -> dict[str, object]:
    if config is None:
        return {}
    return {
        etf.id: {"sector": etf.sector, "theme": etf.theme}
        for etf in config.universe.etfs
        if etf.id in config.universe.enabled_ids
    }


def write_optional_source_inventories(config: AppConfig, identity: pd.DataFrame) -> dict[str, Path]:
    return {
        # Keep imported SEC statement rows when the normal trust refresh runs.
        # The refresh discovers local filing documents, but it is not allowed
        # to replace evidence imported through another official provider.
        "filings_statements": _append_parquet(
            FILINGS_STATEMENTS_PATH,
            _local_document_inventory("filings", RAW_DIR / "filings", identity),
            [],
            id_columns=["document_id", "checksum"],
        ),
        "etf_disclosures": _write_dual(
            _etf_disclosure_inventory(identity, configured_etf_ids=[etf.id for etf in config.universe.etfs if etf.instrument_type == "etf"]),
            ETF_DISCLOSURES_PATH,
        ),
        "priips_kid_records": PRIIPS_KID_RECORDS_PATH,
        "index_methodology_records": INDEX_METHODOLOGY_RECORDS_PATH,
        "news_context": _write_dual(_news_context_inventory(identity), NEWS_CONTEXT_PATH),
        "news_timestamp_validation": _write_dual(_news_timestamp_validation(), NEWS_TIMESTAMP_VALIDATION_PATH),
    }


def load_score_history_summary() -> dict[str, list[dict[str, Any]]]:
    history = project_classification_score_frame(
        _safe_read_parquet(SCORE_HISTORY_PATH, SCORE_HISTORY_COLUMNS),
        root=ROOT,
    )
    if history.empty:
        return {}
    if "run_completed_at" in history.columns:
        history = history.sort_values("run_completed_at")
    result: dict[str, list[dict[str, Any]]] = {}
    for instrument_id, group in history.groupby("instrument_id"):
        result[str(instrument_id)] = group.tail(20).to_dict(orient="records")
    return result


def _candidate_identity_rows(config: AppConfig) -> list[dict[str, Any]]:
    try:
        path = latest_candidate_input()
        candidates = pd.read_csv(path)
    except Exception:
        return []
    primary_isins = {str(etf.isin).strip() for etf in config.universe.etfs if etf.isin}
    primary_symbols = {str(etf.provider_symbol or etf.ticker).strip() for etf in config.universe.etfs}
    rows: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        instrument_id = str(row.get("instrument_id") or "").strip()
        symbol = str(row.get("yahoo_symbol") or "").strip()
        isin = str(row.get("isin") or "").strip()
        isin_status = _isin_status(isin)
        if not instrument_id or symbol in primary_symbols or (isin_status == "verified" and isin in primary_isins):
            continue
        warnings: list[str] = []
        if isin_status == "missing":
            warnings.append("missing_isin")
        if isin_status == "needs_verification":
            warnings.append("isin_needs_verification")
        analysis_tier = str(row.get("analysis_tier") or "secondary")
        candidate_object = {
            "object_type": "instrument",
            "object_id": instrument_id,
            "parent_object_id": None,
            "relationship": None,
            "fields": {"ticker": symbol, "isin": isin},
            "source_ids": [f"candidate:{instrument_id}"],
        }
        candidate_decision_id = hashlib.sha256(
            json.dumps(
                {
                    "schema_version": 1,
                    "object": candidate_object,
                    "decision_time": "unavailable",
                    "resolution_state": "manual_review",
                    "execution_allowed": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        rows.append(
            {
                "instrument_id": instrument_id,
                "display_name": str(row.get("name") or instrument_id),
                "analysis_tier": analysis_tier,
                "data_policy": str(row.get("data_policy") or "yfinance_only"),
                "instrument_type": str(row.get("instrument_type") or "stock"),
                "asset_class": str(row.get("asset_type") or row.get("instrument_type") or ""),
                "isin": isin,
                "isin_status": isin_status,
                "yahoo_symbol": symbol,
                "provider_symbol": symbol,
                "source_group": _source_group_for_analysis_tier(analysis_tier),
                "exchange": str(row.get("exchange") or ""),
                "currency": str(row.get("currency") or ""),
                "region": str(row.get("region") or ""),
                "sector": str(row.get("sector") or ""),
                "theme": str(row.get("theme") or ""),
                "source": str(path),
                "identity_confidence": "medium" if isin_status == "verified" and symbol else "manual_review",
                "warnings": "|".join(warnings),
                "provider_symbol_map": json.dumps({"yfinance": symbol}, sort_keys=True),
                "identity_source_id": f"candidate:{instrument_id}",
                "identity_status": "manual_review",
                "identity_decision_id": candidate_decision_id,
                "identity_conflict_ids": "[]",
                "identity_resolution_state": "manual_review",
                "identity_effective_at": "unavailable",
                "identity_decision_time": "unavailable",
                "identity_objects": json.dumps([candidate_object], sort_keys=True),
                "identity_history": "[]",
                "executable_authority": False,
            }
        )
    return rows


def _optional_free_provider_rows(now: str) -> list[dict[str, Any]]:
    specs = [
        ("sec_edgar", "filings", "official_regulator", "Optional no-key SEC EDGAR provider. Disabled until explicitly requested or mapped."),
        ("fred", "macro", "official_regulator", "Optional FRED macro context provider. Disabled by default."),
        ("stooq", "prices", "vendor_unofficial", "Optional Stooq fallback price provider. Disabled by default."),
        ("rss", "news", "manual_context", "Optional RSS news/context provider. Context only and disabled by default."),
        ("esef_local", "filings", "official_filing", "Manual local ESEF/iXBRL importer. Awaiting local files."),
        ("etf_disclosure_local", "etf_disclosures", "issuer_document", "Manual ETF disclosure importer. Awaiting local files."),
        ("priips_kid_local", "priips_kid", "issuer_document", "Manual PRIIPs KID parser. Awaiting local files."),
        ("index_methodology_local", "index_methodology", "issuer_document", "Manual index methodology importer. Awaiting local files."),
    ]
    return [
        {
            "provider_id": f"{name}:{dataset_type}",
            "provider_name": name,
            "dataset_type": dataset_type,
            "active_provider": "disabled",
            "enabled": False,
            "status": "unavailable",
            "message": message,
            "source_authority": authority,
            "authority_rank": SOURCE_AUTHORITY.get(authority, 0),
            "requires_api_key": False,
            "has_api_key": False,
            "base_url_configured": False,
            "capabilities": json.dumps({"available_now": False, "context_only": dataset_type in {"news", "macro"}}),
            "last_probe_at": now,
            "executable_authority": False,
        }
        for name, dataset_type, authority, message in specs
    ]


def _capabilities_for_dataset(dataset_type: str, active_provider: str) -> str:
    active = active_provider == "yfinance"
    capabilities = {
        "fetch_prices": active and dataset_type == "prices",
        "fetch_fx": active and dataset_type == "fx",
        "fetch_etf_metadata": active and dataset_type == "etf_metadata",
        "fetch_etf_holdings": active and dataset_type == "etf_holdings",
        "score_eligible": active,
    }
    return json.dumps(capabilities, sort_keys=True)


def _etf_disclosure_inventory(identity: pd.DataFrame, configured_etf_ids: Iterable[str] | None = None) -> pd.DataFrame:
    if configured_etf_ids is not None:
        instrument_ids = {str(value).strip() for value in configured_etf_ids if str(value).strip()}
    elif not identity.empty and "instrument_id" in identity.columns:
        scoped_identity = identity
        if "instrument_type" in identity.columns:
            instrument_types = identity["instrument_type"].astype(str).str.lower().str.strip()
            scoped_identity = identity[instrument_types.isin({"etf", "fund", ""})]
        instrument_ids = set(scoped_identity["instrument_id"].astype(str))
    else:
        instrument_ids = set()

    canonical = _canonical_etf_disclosure_inventory(instrument_ids)
    if canonical is not None:
        return canonical

    roots = [
        ("factsheet", RAW_DIR / "etf_factsheets"),
        ("holdings", RAW_DIR / "etf_holdings"),
        ("priips_kid", RAW_DIR / "priips_kids"),
        ("prospectus_or_report", RAW_DIR / "etf_reports"),
        ("index_methodology", RAW_DIR / "index_methodology"),
    ]
    documents: list[FundDocument] = []
    for doc_type, root in roots:
        for row in _document_rows(root, document_type=doc_type, instrument_ids=instrument_ids):
            documents.append(
                FundDocument(
                    instrument_id=str(row.get("instrument_id", "")),
                    document_type=canonical_document_type(str(row.get("document_type", doc_type))),
                    path=str(row.get("path", "")),
                    source_url="",
                    authority=str(row.get("source_authority", "issuer_document")),
                    sha256=str(row.get("checksum", "")) or None,
                    document_date=str(row.get("as_of_date", "")) or None,
                    coverage_status="available" if row.get("instrument_id") else "unavailable",
                    warnings=("unmapped_manual_review",) if not row.get("instrument_id") else (),
                    source_id="funddoc:" + str(row.get("document_id", "")),
                    schema_version=1,
                    ingested_at=str(row.get("ingested_at", "")),
                )
            )
    inventory = build_document_inventory(sorted(instrument_ids), documents)
    if inventory.empty:
        return pd.DataFrame(columns=[
            "document_id", "source_id", "instrument_id", "document_type", "document_kind", "path", "source_url",
            "source_authority", "as_of_date", "ingested_at", "checksum", "coverage_status", "extraction_status", "executable_authority",
        ])
    inventory = inventory.rename(columns={"authority": "source_authority", "document_date": "as_of_date"})
    inventory["document_id"] = inventory["source_id"]
    inventory["executable_authority"] = False
    inventory["checksum"] = inventory["sha256"].fillna("")
    columns = [
        "document_id",
        "source_id",
        "instrument_id",
        "document_type",
        "document_kind",
        "path",
        "source_url",
        "source_authority",
        "as_of_date",
        "ingested_at",
        "checksum",
        "coverage_status",
        "extraction_status",
        "executable_authority",
    ]
    return inventory[columns]


def _canonical_etf_disclosure_inventory(instrument_ids: set[str]) -> pd.DataFrame | None:
    """Project the canonical fund-document registry into the trust artifact.

    A present registry is authoritative for its registered provenance. Missing
    instrument/type combinations are added explicitly, while an absent or
    unreadable registry returns ``None`` so older raw-directory discovery stays
    compatible.
    """
    registry = read_document_registry(path=FUND_DOCUMENTS_PATH)
    if registry.empty:
        return None
    rows: list[dict[str, Any]] = []
    for instrument_id in sorted(instrument_ids):
        for document_type in ("factsheet", "kid", "prospectus_report", "holdings", "methodology"):
            matches = registry.loc[
                registry.get("instrument_id", pd.Series(dtype=str)).astype(str).eq(instrument_id)
                & registry.get("document_type", pd.Series(dtype=str)).astype(str).map(_canonical_document_type_or_empty).eq(document_type)
            ]
            if matches.empty:
                missing = asdict(unavailable_document(instrument_id, document_type, "document_not_available"))
                missing["coverage_status"] = "missing"
                rows.append(_disclosure_row(missing))
                continue
            for _, raw in matches.iterrows():
                row = raw.to_dict()
                row["document_type"] = document_type
                rows.append(_disclosure_row(row))
    return pd.DataFrame(rows, columns=[
        "document_id", "source_id", "instrument_id", "document_type", "document_kind", "path", "source_url",
        "source_authority", "as_of_date", "ingested_at", "checksum", "coverage_status", "extraction_status", "executable_authority",
    ])


def _canonical_document_type_or_empty(value: object) -> str:
    try:
        return canonical_document_type(str(value))
    except ValueError:
        return ""


def _disclosure_row(raw: dict[str, Any]) -> dict[str, Any]:
    source_id = _clean_text(raw.get("source_id") or raw.get("document_id"))
    checksum = _clean_text(raw.get("checksum") or raw.get("sha256"))
    coverage_status = _clean_text(raw.get("coverage_status"))
    extraction_status = _clean_text(raw.get("extraction_status"))
    if extraction_status and extraction_status != "complete":
        coverage_status = "unavailable"
    elif coverage_status in {"", "unavailable"}:
        coverage_status = "available" if checksum or _clean_text(raw.get("path")) else "missing"
    as_of_date = raw.get("as_of_date") if raw.get("as_of_date") is not None else raw.get("document_date")
    if hasattr(as_of_date, "date"):
        as_of_date = as_of_date.date().isoformat()
    elif pd.isna(as_of_date):
        as_of_date = ""
    else:
        as_of_date = _clean_text(as_of_date)
    return {
        "document_id": source_id,
        "source_id": source_id,
        "instrument_id": _clean_text(raw.get("instrument_id")),
        "document_type": _canonical_document_type_or_empty(raw.get("document_type")),
        "document_kind": _clean_text(raw.get("document_kind")),
        "path": _clean_text(raw.get("path")),
        "source_url": _clean_text(raw.get("source_url")),
        "source_authority": _clean_text(raw.get("source_authority") or raw.get("authority")) or "unknown",
        "as_of_date": as_of_date,
        "ingested_at": _clean_text(raw.get("ingested_at")),
        "checksum": checksum,
        "coverage_status": coverage_status,
        "extraction_status": extraction_status,
        "executable_authority": False,
    }


def _clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return ""
    return str(value).strip()


def _local_document_inventory(dataset: str, root: Path, identity: pd.DataFrame) -> pd.DataFrame:
    rows = _document_rows(root, document_type=dataset, instrument_ids=set(identity["instrument_id"].astype(str)) if not identity.empty else set())
    columns = [
        "document_id",
        "instrument_id",
        "document_type",
        "path",
        "source_authority",
        "as_of_date",
        "ingested_at",
        "checksum",
        "coverage_status",
        "executable_authority",
    ]
    return pd.DataFrame(rows, columns=columns)


def _document_rows(root: Path, *, document_type: str, instrument_ids: set[str]) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        stem_upper = path.stem.upper()
        mapped_ids = [instrument_id for instrument_id in instrument_ids if instrument_id.upper() in stem_upper]
        instrument_id = mapped_ids[0] if mapped_ids else ""
        rows.append(
            {
                "document_id": hashlib.sha256(str(path).encode()).hexdigest()[:16],
                "instrument_id": instrument_id,
                "document_type": document_type,
                "path": str(path),
                "source_authority": "issuer_document" if document_type != "filings" else "official_filing",
                "as_of_date": "",
                "ingested_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
                "checksum": _file_sha256(path),
                "coverage_status": "mapped" if instrument_id else "unmapped_manual_review",
                "executable_authority": False,
            }
        )
    return rows


def _provider_section_for(config: AppConfig, provider_id: str) -> tuple[Any, str]:
    direct = config.data_providers.providers.get(provider_id)
    if direct is not None and (direct.active_provider or "none").strip().lower() not in {"", "none"}:
        return direct, provider_id
    for dataset_type, section in config.data_providers.providers.items():
        if (section.active_provider or "none").strip().lower() == provider_id:
            return section, dataset_type
    return direct or config.data_providers.section(provider_id), provider_id


def _provider_requires_api_key(provider_id: str, active_provider: str) -> bool:
    keyless = {
        "",
        "none",
        "yfinance",
        "sec_edgar",
        "filings_xbrl_org",
        "stooq",
        "rss",
        "manual_local",
        "manual_local_file",
        "issuer_document",
        "index_provider",
    }
    return provider_id == "fred" or active_provider not in keyless


def _legacy_provider_authority(authority: SourceAuthority) -> str:
    return {
        SourceAuthority.OFFICIAL: "official_regulator",
        SourceAuthority.ISSUER: "issuer_document",
        SourceAuthority.VENDOR: "vendor_unofficial",
        SourceAuthority.COMMUNITY: "manual_context",
        SourceAuthority.MANUAL: "manual_context",
        SourceAuthority.MODEL: "model_advisory",
    }[authority]


def _news_context_inventory(identity: pd.DataFrame) -> pd.DataFrame:
    # Canonical Task 16 clean rows outrank legacy raw-directory discovery.  A
    # trust refresh must never erase imported, timestamp-validated news.
    canonical = _safe_read_parquet(NEWS_CONTEXT_PATH, [])
    if not canonical.empty and "news_id" in canonical.columns:
        frame = canonical.copy()
        for column, default in (
            ("headline", ""),
            ("source_url", ""),
            ("provider_name", ""),
            ("published_at", ""),
            ("ingested_at", ""),
            ("credibility", "unverified"),
            ("instrument_mapping_method", ""),
            ("timestamp_confidence", "unknown"),
            ("timestamp_status", "unknown"),
            ("backtest_eligible", False),
            ("available_at_decision_time", False),
            ("source_authority", "unknown"),
            ("context_only", True),
            ("executable_authority", False),
            ("raw_path", ""),
            ("item_checksum", ""),
            ("path", ""),
        ):
            if column not in frame.columns:
                frame[column] = default
        if "raw_path" not in canonical.columns and "path" in canonical.columns:
            frame["raw_path"] = canonical["path"]
        if "path" not in canonical.columns and "raw_path" in canonical.columns:
            frame["path"] = canonical["raw_path"]
        frame["context_only"] = True
        frame["executable_authority"] = False
        return frame.reset_index(drop=True)
    root = RAW_DIR / "manual_news"
    rows: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rows.append(
                    {
                        "news_id": hashlib.sha256(str(path).encode()).hexdigest()[:16],
                        "instrument_id": "",
                        "source_url": "",
                        "provider_name": "manual_file",
                        "published_at": "",
                        "ingested_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
                        "timestamp_confidence": "manual_review",
                        "available_at_decision_time": False,
                        "source_authority": "manual_context",
                        "context_only": True,
                        "executable_authority": False,
                        "path": str(path),
                        "checksum": _file_sha256(path),
                    }
                )
    columns = [
        "news_id",
        "instrument_id",
        "source_url",
        "provider_name",
        "published_at",
        "ingested_at",
        "timestamp_confidence",
        "available_at_decision_time",
        "source_authority",
        "context_only",
        "executable_authority",
        "path",
        "checksum",
    ]
    return pd.DataFrame(rows, columns=columns)


def _news_timestamp_validation() -> pd.DataFrame:
    news = _safe_read_parquet(NEWS_CONTEXT_PATH, [])
    rows: list[dict[str, Any]] = []
    if not news.empty:
        for _, row in news.iterrows():
            published = str(row.get("published_at") or "")
            source_status = str(row.get("timestamp_status") or "").strip().lower()
            confidence = source_status if source_status else ("valid" if published else "missing_published_at")
            eligible = confidence in {"valid", "valid_context"} and bool(row.get("available_at_decision_time"))
            rows.append(
                {
                    "news_id": row.get("news_id"),
                    "timestamp_status": confidence,
                    "backtest_eligible": eligible,
                    "reason": "News without published_at or available_at_decision_time is context-only and excluded from backtests.",
                    "available_at_decision_time": bool(row.get("available_at_decision_time", False)),
                    "instrument_mapping_method": row.get("instrument_mapping_method", ""),
                }
            )
    return pd.DataFrame(rows, columns=["news_id", "timestamp_status", "backtest_eligible", "reason", "available_at_decision_time", "instrument_mapping_method"])


def _append_parquet(
    path: Path,
    new_frame: pd.DataFrame,
    columns: list[str],
    *,
    id_columns: list[str],
    snapshot_hash_column: str | None = None,
    run_id: str | None = None,
) -> Path:
    existing = _safe_read_parquet(path, columns)
    if snapshot_hash_column and "run_id" in existing.columns:
        run_ids = (
            {str(run_id)}
            if run_id is not None
            else set(new_frame["run_id"].astype(str))
            if "run_id" in new_frame.columns
            else set()
        )
        if run_ids:
            existing = existing.loc[~existing["run_id"].astype(str).isin(run_ids)].copy()
    if existing.empty:
        combined = new_frame.copy()
    elif new_frame.empty:
        combined = existing.copy()
    else:
        combined = pd.concat([existing, new_frame], ignore_index=True)
    if not combined.empty:
        combined = combined.drop_duplicates(subset=[col for col in id_columns if col in combined.columns], keep="last")
    return _write_dual(combined, path)


def _run_snapshot_hash(frame: pd.DataFrame) -> str:
    """Hash a complete run snapshot, independent of row ordering."""

    canonical = frame.drop(columns=["snapshot_hash"], errors="ignore").copy()
    sort_columns = [column for column in ("run_id", "instrument_id") if column in canonical.columns]
    if sort_columns:
        canonical = canonical.sort_values(sort_columns, kind="stable")
    canonical = canonical.reindex(sorted(canonical.columns), axis=1)
    payload = canonical.to_json(orient="records", date_format="iso", default_handler=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _score_sort_key(score: Any) -> tuple[bool, float, str]:
    value = _safe_float(getattr(score, "final_score_10", None))
    return (value is None, -(value or 0.0), str(getattr(score, "display_id", "")))


def _write_dual(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = path.with_suffix(".csv")
    parquet_output = BytesIO()
    frame.to_parquet(parquet_output, index=False)
    payloads = {
        path: parquet_output.getvalue(),
        csv_path: frame.to_csv(index=False).encode("utf-8"),
    }
    atomic_write_group(
        AtomicWriteRequest(
            destination,
            payload,
            _parquet_validation if destination.suffix == ".parquet" else _csv_validation,
        )
        for destination, payload in payloads.items()
    )
    return path


def _parquet_validation(path: Path) -> None:
    pd.read_parquet(path)


def _csv_validation(path: Path) -> None:
    pd.read_csv(path, low_memory=False)


def _ensure_empty_if_missing(path: Path, columns: list[str]) -> None:
    if path.exists():
        return
    _write_dual(pd.DataFrame(columns=columns), path)


def _safe_read_parquet(path: Path, columns: list[str]) -> pd.DataFrame:
    try:
        if path.exists():
            wait_for_atomic_group(path)
            return pd.read_parquet(path)
    except Exception as exc:
        log_event(
            event_type="data_error",
            severity="error",
            component="trust_artifacts",
            operation="read_parquet",
            status="unavailable",
            file_paths=[str(path)],
            user_message=f"Evidence store unavailable: {path.name} ({type(exc).__name__}).",
        )
    return pd.DataFrame(columns=columns)


def _safe_row_count(path: Path) -> int:
    try:
        return int(pd.read_parquet(path).shape[0])
    except Exception:
        return 0


def _score_snapshot_hash(score: Any) -> str:
    payload = {
        "instrument_id": getattr(score, "display_id", ""),
        "score": getattr(score, "final_score_10", None),
        "components": [
            [getattr(component, "key", ""), getattr(component, "score_10", None), getattr(component, "status", "")]
            for component in getattr(score, "components", []) or []
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _score_freshness(score: Any) -> str:
    statuses = [
        str(getattr(component, "freshness_status", "") or "")
        for component in getattr(score, "components", []) or []
        if str(getattr(component, "freshness_status", "") or "")
    ]
    if any(status in {"stale", "stale_block"} for status in statuses):
        return "stale"
    if any(status in {"partial", "warning", "unknown", "missing_or_pending"} for status in statuses):
        return "partial"
    return statuses[0] if statuses else _freshness_from_date(str(getattr(score, "latest_date", "")))


def _model_available(score: Any) -> bool | None:
    versions = getattr(score, "model_versions_used", None)
    if isinstance(versions, dict) and versions:
        return any(_real_model_value(value) for value in versions.values())
    components = getattr(score, "components", []) or []
    if any(
        str(getattr(component, "key", "") or "").casefold() in {"baseline", "timesfm", "toto"}
        and getattr(component, "score_10", None) is not None
        for component in components
    ):
        return True
    # Human-readable labels are not model evidence.  In particular the
    # configured/candidate placeholder "Model evidence pending" must remain
    # unavailable until a real model row or version is present.
    return False


def _model_availability(score: Any) -> str:
    versions = getattr(score, "model_versions_used", None)
    if isinstance(versions, dict) and versions:
        real_versions = {
            name: str(version).strip()
            for name, version in versions.items()
            if _real_model_value(version)
        }
        if real_versions:
            return "|".join(f"{name}={version}" for name, version in sorted(real_versions.items()))
    components = getattr(score, "components", []) or []
    model_rows = [
        str(getattr(component, "key", "") or "").strip()
        for component in components
        if str(getattr(component, "key", "") or "").casefold() in {"baseline", "timesfm", "toto"}
        and getattr(component, "score_10", None) is not None
    ]
    if model_rows:
        return "|".join(f"{key}=available" for key in sorted(model_rows))
    return "unavailable"


def _real_model_value(value: object) -> bool:
    if value is None:
        return False
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().casefold() not in {"", "none", "null", "nan", "unavailable", "pending", "pending refresh", "false"}


def _forecast_status(score: Any) -> str:
    components = [
        component
        for component in (getattr(score, "components", []) or [])
        if str(getattr(component, "key", "") or "").casefold() in {"baseline", "timesfm", "toto"}
    ]
    if not components:
        return "unavailable"
    valid = sum(getattr(component, "score_10", None) is not None for component in components)
    if valid == len(components):
        return "available"
    if valid:
        return "partial"
    return "unavailable"


def _freshness_from_date(value: str) -> str:
    if not value or value == "pending refresh":
        return "missing_or_pending"
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return "unknown"
        now = pd.Timestamp.utcnow().tz_localize(None).normalize()
        age_days = (now - parsed.tz_localize(None).normalize()).days
        if age_days <= 3:
            return "ok"
        if age_days <= 10:
            return "warning"
        return "stale_block"
    except Exception:
        return "unknown"


def _instrument_type(asset_class: str) -> str:
    return "etf" if str(asset_class).lower() in {"bond", "equity", "commodity"} else str(asset_class or "instrument")


def _source_group_for_analysis_tier(analysis_tier: str) -> str:
    tier = str(analysis_tier or "").strip().lower()
    if tier == "sparebanken":
        return "Sparebanken"
    if tier == "primary":
        return "Primary tier"
    return "Secondary tier"


def _isin_status(isin: Any) -> str:
    value = str(isin or "").strip()
    if not value:
        return "missing"
    if value.lower() == "needs_verification":
        return "needs_verification"
    return "verified"


def _file_sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return ""


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
