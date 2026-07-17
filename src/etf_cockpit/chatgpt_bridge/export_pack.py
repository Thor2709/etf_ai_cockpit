from __future__ import annotations

import json
import hashlib
import zipfile
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from etf_cockpit.backtest.engine import BacktestReport
from etf_cockpit.chatgpt_bridge.prompts import CHATGPT_REVIEW_PROMPT
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import AUDIT_PACKETS_DIR, CONFIG_DIR, DERIVED_DIR, ROOT, STATEMENT_FACTS_PATH
from etf_cockpit.core.session_log import SESSION_LOG_PATH, copy_session_log_to
from etf_cockpit.core.types import DataQualityReport, SignalResult
from etf_cockpit.core.versioning import RUN_MANIFEST_DIR, VERSION_REGISTRY_PATH, write_version_registry
from etf_cockpit.data.fx_data import fx_data_inventory
from etf_cockpit.data.manual_notes import MANUAL_NEWS_CLEAN_PATH, load_manual_news, manual_news_markdown
from etf_cockpit.data.fundamentals import FUNDAMENTAL_CLEAN_PATH, FUNDAMENTAL_RAW_DIR, load_fundamental_evidence
from etf_cockpit.data.news_context import NEWS_RAW_DIR, load_news_items
from etf_cockpit.data.reference_data import reference_data_inventory
from etf_cockpit.data.trust_artifacts import (
    BENCHMARK_ATTRIBUTION_PATH,
    CORRELATION_CLUSTERS_PATH,
    ETF_DISCLOSURES_PATH,
    EVIDENCE_LEDGER_PATH,
    FEATURE_DRIVERS_PATH,
    FILINGS_STATEMENTS_PATH,
    IDENTITY_PATH,
    NEWS_CONTEXT_PATH,
    NEWS_TIMESTAMP_VALIDATION_PATH,
    PROVIDER_PROBE_PATH,
    SCORE_COMPONENTS_PATH,
    SCORE_HISTORY_PATH,
    SCORE_METRIC_HISTORY_PATH,
    SCORE_FORMULA_REGISTRY_PATH,
    SOURCE_CONFLICTS_PATH,
    write_score_formula_registry,
)
from etf_cockpit.data.parsed_disclosures import INDEX_METHODOLOGY_RECORDS_PATH, PRIIPS_KID_RECORDS_PATH
from etf_cockpit.data.fund_documents import FUND_DOCUMENTS_PATH
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
from etf_cockpit.data.health import build_data_health, export_data_health
from etf_cockpit.data.legal_terms import legal_terms_report
from etf_cockpit.data.bitemporal import BitemporalStore
from etf_cockpit.application.architecture import build_report as build_architecture_report
from etf_cockpit.governance.product_scope import (
    load_authority_matrix,
    load_feature_registry,
    load_gate_policy,
    load_glossary,
    load_product_governance,
    load_strategy_scope,
)
from etf_cockpit.portfolio.allocation import allocation_frame


# Backwards-compatible name for older scripts/tests; new exports default to data/audit_packets.
CHATGPT_EXPORTS_DIR = AUDIT_PACKETS_DIR
CANDLE_CONTEXT_PATH = DERIVED_DIR / "candle_context.parquet"
GOVERNANCE_CHECKSUMS_PATH = ROOT / "evidence" / "governance" / "policy_checksums.json"


# Canonical artefacts required in every external audit packet.  Paths are
# archive-relative and may be represented by an explicit unavailable marker
# when an optional local source is absent.  The records are deliberately
# declarative so the manifest remains auditable without importing UI state.
_COMPLETE_AUDIT_REQUIRED: tuple[tuple[str, str, bool], ...] = (
    ("evidence_export/provider_probe_results.csv", "provider", True),
    ("evidence_export/instrument_identity.csv", "identity", True),
    ("evidence_export/statement_facts.csv", "official_regulator", True),
    ("evidence_export/filings_statements.csv", "official_regulator", True),
    ("evidence_export/fund_documents.csv", "issuer_document", True),
    ("evidence_export/fund_holdings.csv", "issuer_document", True),
    ("evidence_export/etf_disclosures.csv", "issuer_document", True),
    ("evidence_export/priips_kid_records.csv", "issuer_document", True),
    ("evidence_export/index_methodology_records.csv", "issuer_document", True),
    ("evidence_export/news_context.csv", "context_only", True),
    ("evidence_export/news_timestamp_validation.csv", "context_only", True),
    ("evidence_export/source_conflicts.csv", "evidence", True),
    ("evidence_export/evidence_ledger.csv", "derived", True),
    ("evidence_export/score_components.csv", "derived", True),
    ("evidence_export/score_history.csv", "derived", True),
    ("evidence_export/score_metric_history.csv", "derived", True),
    ("evidence_export/score_formula_registry.json", "derived", False),
    ("evidence_export/version_registry.json", "derived", False),
    ("evidence_export/feature_drivers.csv", "derived", True),
    ("evidence_export/correlation_clusters.csv", "derived", True),
    ("evidence_export/benchmark_attribution.csv", "derived", True),
    ("evidence_export/edge_cost.csv", "derived", True),
    ("evidence_export/data_health.csv", "derived", True),
    ("evidence_export/bitemporal_vintage_manifest.json", "evidence", False),
    ("evidence_export/session.jsonl", "workflow", True),
    ("evidence_export/workflow.jsonl", "workflow", True),
    ("evidence_export/configs/data_providers_redacted.json", "configuration", False),
    ("evidence_export/configs/audit_manifest.yaml", "configuration", True),
    ("evidence_export/governance/legal_terms_registry.json", "governance", False),
    ("evidence_export/project_docs/issue_dossiers.json", "issue_dossier", True),
    ("evidence_export/checksum_manifest.json", "audit", False),
    ("checksum_manifest.json", "audit", False),
)

SIGNAL_TABLE_COLUMNS = [
    "etf_id",
    "name",
    "research_state",
    "portfolio_review_state",
    "analysis_status",
    "research_promotion_allowed",
    "portfolio_review_allowed",
    "execution_allowed",
    "legacy_action",
    "migration_version",
    "gate_policy_version",
    "gate_policy_checksum",
    "schema_version",
    "confidence",
    "total_score",
    "canonical_attractiveness_10",
    "canonical_expected_return_10",
    "canonical_risk_implementation_10",
    "canonical_evidence_confidence_10",
    "canonical_coverage",
    "formula_version",
    "formula_checksum",
    "source_vintage_hash",
    "reason_full",
    "score_1w",
    "score_1m",
    "score_3m",
    "score_6m",
    "score_9m",
    "blocked_by",
    "reason_short",
    "expected_edge_bps",
    "estimated_cost_bps",
    "edge_to_cost_ratio",
    "cost_low_bps",
    "cost_base_bps",
    "cost_high_bps",
    "edge_to_cost_low",
    "edge_to_cost_base",
    "edge_to_cost_high",
    "cost_stress_warning",
    "cost_stress_assumptions",
    "min_trade_value_eur",
]


def _signal_rows(signals: Iterable[SignalResult], config: AppConfig) -> list[dict[str, object]]:
    names = {etf.id: etf.name for etf in config.universe.etfs}
    rows = []
    for signal in signals:
        authority = signal.to_v2_dict()
        canonical = signal.canonical_score
        rows.append(
            {
                "etf_id": signal.etf_id,
                "name": names.get(signal.etf_id, signal.etf_id),
                **authority,
                "confidence": signal.confidence,
                "total_score": signal.total_score,
                "canonical_attractiveness_10": canonical.attractiveness_10 if canonical else None,
                "canonical_expected_return_10": canonical.expected_return_10 if canonical else None,
                "canonical_risk_implementation_10": canonical.risk_implementation_10 if canonical else None,
                "canonical_evidence_confidence_10": canonical.evidence_confidence_10 if canonical else None,
                "canonical_coverage": canonical.coverage if canonical else 0.0,
                "formula_version": canonical.formula_version if canonical else "unavailable",
                "formula_checksum": canonical.formula_checksum if canonical else "unavailable",
                "source_vintage_hash": canonical.source_vintage_hash if canonical else "unavailable",
                "reason_full": signal.supporting_metrics.get("reason_full", signal.reason_long),
                "score_1w": signal.components.momentum,
                "score_1m": signal.components.trend,
                "score_3m": signal.total_score,
                "score_6m": 0.5 * signal.components.momentum + 0.5 * signal.components.trend,
                "score_9m": signal.components.baseline_ml,
                "blocked_by": "|".join(signal.blocked_by),
                "reason_short": signal.reason_short,
                "expected_edge_bps": signal.supporting_metrics.get("expected_edge_bps"),
                "estimated_cost_bps": signal.supporting_metrics.get("estimated_cost_bps"),
                "edge_to_cost_ratio": signal.supporting_metrics.get("edge_to_cost_ratio"),
                "cost_low_bps": signal.supporting_metrics.get("cost_low_bps"),
                "cost_base_bps": signal.supporting_metrics.get("cost_base_bps"),
                "cost_high_bps": signal.supporting_metrics.get("cost_high_bps"),
                "edge_to_cost_low": signal.supporting_metrics.get("edge_to_cost_low"),
                "edge_to_cost_base": signal.supporting_metrics.get("edge_to_cost_base"),
                "edge_to_cost_high": signal.supporting_metrics.get("edge_to_cost_high"),
                "cost_stress_warning": signal.supporting_metrics.get("cost_stress_warning"),
                "cost_stress_assumptions": signal.supporting_metrics.get("cost_stress_assumptions"),
                "min_trade_value_eur": signal.supporting_metrics.get("min_trade_value_eur"),
            }
        )
    return rows


def _audit_portfolio_holdings(
    config: AppConfig,
    allocation: pd.DataFrame,
    holdings: pd.DataFrame | None = None,
) -> list[dict[str, object]]:
    """Include every enabled instrument in the audit allocation export.

    Targets intentionally cover only instruments with approved target weights.
    The audit packet is configuration-complete, so enabled instruments without
    a target or current holding are represented by explicit zero weights rather
    than being silently omitted.
    """

    columns = ["etf_id", "name", "current_weight", "target_weight", "drift", "role", "region", "sector", "currency"]
    by_id = {
        str(row["etf_id"]): row
        for _, row in allocation.iterrows()
        if row.get("etf_id") is not None
    }
    universe = config.universe.by_id()
    holding_by_id: dict[str, pd.Series] = {}
    if isinstance(holdings, pd.DataFrame) and not holdings.empty and "etf_id" in holdings.columns:
        for _, holding in holdings.iterrows():
            etf_id = str(holding.get("etf_id") or "").strip()
            if etf_id:
                holding_by_id[etf_id] = holding
    rows: list[dict[str, object]] = []
    for etf_id in config.universe.configured_enabled_ids:
        row = by_id.get(str(etf_id))
        if row is not None:
            rows.append({column: row.get(column) for column in columns})
            continue
        etf = universe.get(str(etf_id))
        holding = holding_by_id.get(str(etf_id))
        raw_current_weight = holding.get("current_weight") if holding is not None else None
        parsed_current_weight = pd.to_numeric(raw_current_weight, errors="coerce")
        current_weight = float(parsed_current_weight) if pd.notna(parsed_current_weight) else 0.0
        rows.append(
            {
                "etf_id": str(etf_id),
                "name": etf.name if etf else str(etf_id),
                "current_weight": current_weight,
                "target_weight": 0.0,
                "drift": current_weight,
                "role": etf.role if etf else "unknown",
                "region": etf.region if etf else None,
                "sector": etf.sector if etf else None,
                "currency": etf.currency if etf else config.targets.base_currency,
            }
        )
    return rows


def export_review_pack(
    config: AppConfig,
    holdings: pd.DataFrame,
    features: pd.DataFrame,
    signals: list[SignalResult],
    backtest: BacktestReport,
    *,
    as_of_date: date,
    data_report: DataQualityReport | None = None,
) -> Path:
    export_dir = CHATGPT_EXPORTS_DIR / f"audit_packet_{as_of_date:%Y-%m-%d}"
    export_dir.mkdir(parents=True, exist_ok=True)
    allocation = allocation_frame(config, holdings)
    portfolio_summary = {
        "as_of_date": as_of_date.isoformat(),
        "base_currency": config.targets.base_currency,
        "portfolio_value": float(holdings["market_value_eur"].sum()),
        "cash_weight": max(0.0, 1.0 - float(holdings["current_weight"].sum())),
        "holdings": _audit_portfolio_holdings(config, allocation, holdings),
        "risk_limits": config.risks.portfolio_limits.model_dump(),
    }
    (export_dir / "00_prompt.md").write_text(CHATGPT_REVIEW_PROMPT, encoding="utf-8")
    (export_dir / "01_portfolio_summary.json").write_text(json.dumps(portfolio_summary, indent=2, default=str), encoding="utf-8")
    signal_table = pd.DataFrame(_signal_rows(signals, config), columns=SIGNAL_TABLE_COLUMNS)
    signal_table.to_csv(export_dir / "02_signal_table.csv", index=False)
    latest_features = features.sort_values("date").groupby("etf_id").tail(1)
    metric_columns = [
        "etf_id",
        "date",
        "momentum_20d",
        "momentum_60d",
        "momentum_120d",
        "momentum_180d",
        "trend_100",
        "trend_200",
        "vol_20d_ann",
        "vol_60d_ann",
        "drawdown_current",
        "drawdown_120d_max",
        "relative_strength_60d",
        "liquidity_score",
    ]
    latest_features[[col for col in metric_columns if col in latest_features.columns]].to_csv(
        export_dir / "03_etf_detail_metrics.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "model_name": model,
                "model_version": version,
                "etf_id": signal.etf_id,
                "horizon_days": 60,
                "expected_return": signal.supporting_metrics.get("momentum_60d"),
                "expected_excess_return": signal.supporting_metrics.get("momentum_60d"),
                "q10_return": None,
                "q50_return": signal.supporting_metrics.get("momentum_60d"),
                "q90_return": None,
                "forecast_vol": signal.supporting_metrics.get("vol_60d_ann"),
                "prob_positive_return": None,
                "prob_beat_benchmark": None,
                "status": "ok" if version != "unavailable" else "unavailable",
            }
            for signal in signals
            for model, version in signal.model_versions_used.items()
        ]
    ).to_csv(export_dir / "04_model_forecasts.csv", index=False)
    if "strategy_name" in backtest.results.columns:
        main_strategy = backtest.results[backtest.results["strategy_name"] == "signal_strategy"].to_dict(orient="records")
        benchmark_rows = backtest.results[backtest.results["strategy_name"] != "signal_strategy"].to_dict(orient="records")
    else:
        main_strategy = []
        benchmark_rows = []
    summary = {
        "main_strategy": main_strategy,
        "benchmarks": benchmark_rows,
        "ai_added_value": backtest.ai_added_value,
        "warning_flags": ["AI informational only until validated on real out-of-sample data"],
        "last_walk_forward_periods": [],
    }
    (export_dir / "05_backtest_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    manual_news = load_manual_news(MANUAL_NEWS_CLEAN_PATH)
    news_markdown = manual_news_markdown(manual_news)
    canonical_news = load_news_items(NEWS_CONTEXT_PATH)
    if not canonical_news.empty:
        news_markdown += "\n## Canonical point-in-time news/context\n\n"
        news_markdown += "News is context-only (`executable_authority=false`) and unavailable rows are not backtest inputs.\n\n"
        for _, row in canonical_news.tail(20).iterrows():
            news_markdown += (
                f"- {row.get('instrument_id', 'unavailable')} | {row.get('published_at', 'unavailable')} | "
                f"provider={row.get('provider_name', 'unavailable')} | source_url={row.get('source_url', 'unavailable')} | "
                f"status={row.get('timestamp_status', 'unavailable')} | executable_authority=false\n"
            )
    fundamentals = load_fundamental_evidence(FUNDAMENTAL_CLEAN_PATH)
    if not fundamentals.empty:
        news_markdown += "\n## Fundamental evidence inventory\n\n"
        for _, row in fundamentals.tail(20).iterrows():
            news_markdown += (
                f"- {row.get('instrument_id', 'unavailable')} | as_of={row.get('as_of_date', 'unavailable')} | "
                f"eligibility={row.get('eligibility', 'not_score_eligible')} | source={row.get('source', 'unavailable')} | "
                f"missing={row.get('missing_fields', 'none') or 'none'} | executable_authority=false\n"
            )
    (export_dir / "06_recent_news_events.md").write_text(news_markdown, encoding="utf-8")
    (export_dir / "07_questions_for_chatgpt.md").write_text(
        "- Which app signals are too weak after costs?\n- Which risks should downgrade buy/add/trim actions?\n- Are AI forecasts adding value versus simple baselines?\n",
        encoding="utf-8",
    )
    (export_dir / "08_response_schema.json").write_text((CONFIG_DIR / "chatgpt_schema.json").read_text(encoding="utf-8"), encoding="utf-8")
    (export_dir / "09_readme.md").write_text(
        "This audit packet is for manual external review only. It must not be treated as trading authority.\n",
        encoding="utf-8",
    )
    validation_report = {
        "as_of_date": as_of_date.isoformat(),
        "trading_allowed": False,
        "status": data_report.status if data_report else "unknown",
        "issues": [asdict(issue) for issue in data_report.issues] if data_report else [],
        "dataset_metadata": [asdict(meta) for meta in data_report.dataset_metadata] if data_report else [],
    }
    (export_dir / "10_validation_report.json").write_text(json.dumps(validation_report, indent=2, default=str), encoding="utf-8")
    risk_gate_report = {
        "as_of_date": as_of_date.isoformat(),
        "signals": [
            {
                "etf_id": signal.etf_id,
                **signal.to_v2_dict(),
                "blocked_by": signal.blocked_by,
                "warnings": signal.warnings,
                "reason_full": signal.supporting_metrics.get("reason_full", signal.reason_long),
            }
            for signal in signals
        ],
    }
    (export_dir / "11_risk_gate_report.json").write_text(json.dumps(risk_gate_report, indent=2, default=str), encoding="utf-8")
    reference_inventory = reference_data_inventory()
    (export_dir / "12_reference_data_inventory.json").write_text(json.dumps(reference_inventory, indent=2, default=str), encoding="utf-8")
    fx_inventory = fx_data_inventory()
    (export_dir / "13_fx_inventory.json").write_text(json.dumps(fx_inventory, indent=2, default=str), encoding="utf-8")
    derived_manifest = _export_derived_evidence(export_dir)
    evidence_manifest = _export_trust_critical_evidence(export_dir, config)
    edge_cost_path = export_dir / "evidence_export" / "edge_cost.csv"
    edge_cost_path.parent.mkdir(parents=True, exist_ok=True)
    edge_columns = [
        column
        for column in (
            "etf_id", "expected_edge_bps", "estimated_cost_bps", "edge_to_cost_ratio",
            "cost_low_bps", "cost_base_bps", "cost_high_bps", "edge_to_cost_low",
            "edge_to_cost_base", "edge_to_cost_high", "cost_stress_warning",
            "cost_stress_assumptions", "execution_allowed",
        )
        if column in signal_table.columns
    ]
    signal_table[edge_columns].to_csv(edge_cost_path, index=False)
    _include_file(edge_cost_path, "edge_cost.csv", evidence_manifest)
    vintage_manifest_path = export_dir / "evidence_export" / "bitemporal_vintage_manifest.json"
    _write_bitemporal_manifest(vintage_manifest_path)
    _include_file(vintage_manifest_path, "bitemporal_vintage_manifest.json", evidence_manifest)
    trust_manifest_path = export_dir / "evidence_export" / "trust_critical_manifest.json"
    trust_manifest_path.write_text(json.dumps(evidence_manifest, indent=2, default=str), encoding="utf-8")
    _include_file(trust_manifest_path, "trust_critical_manifest.json", evidence_manifest)
    combined = [
        "# Combined External Audit Packet",
        "",
        (export_dir / "00_prompt.md").read_text(encoding="utf-8"),
        "",
        "## Portfolio Summary",
        "```json",
        (export_dir / "01_portfolio_summary.json").read_text(encoding="utf-8"),
        "```",
        "",
        "## Signal Table",
        "```csv",
        signal_table.to_csv(index=False),
        "```",
        "",
        "## Recent Manual Thesis/News Notes",
        "",
        (export_dir / "06_recent_news_events.md").read_text(encoding="utf-8"),
        "",
        "## Reference Data Inventory",
        "```json",
        (export_dir / "12_reference_data_inventory.json").read_text(encoding="utf-8"),
        "```",
        "",
        "## FX Inventory",
        "```json",
        (export_dir / "13_fx_inventory.json").read_text(encoding="utf-8"),
        "```",
        "",
        "## Derived Evidence Manifest",
        "```json",
        json.dumps(derived_manifest, indent=2),
        "```",
        "",
        "## Trust-Critical Evidence Manifest",
        "```json",
        json.dumps(evidence_manifest, indent=2),
        "```",
    ]
    (export_dir / "combined_review_packet.md").write_text("\n".join(combined), encoding="utf-8")
    _write_audit_manifest(export_dir, derived_manifest, evidence_manifest)
    zip_path = export_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in export_dir.rglob("*"):
            if file.is_file():
                archive.write(file, arcname=file.relative_to(export_dir))
    return zip_path


def _write_audit_manifest(export_dir: Path, derived_manifest: dict[str, object], evidence_manifest: dict[str, object]) -> None:
    governance_path = export_dir / "evidence_export" / "governance" / "policy_checksums.json"
    governance_path.parent.mkdir(parents=True, exist_ok=True)
    governance_payload: dict[str, object] = {}
    diagnostic_mode = False
    try:
        governance_payload = json.loads(GOVERNANCE_CHECKSUMS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        diagnostic_mode = True

    policy_loaders = {
        "authority_matrix": load_authority_matrix,
        "product_governance": load_product_governance,
        "feature_registry": load_feature_registry,
        "strategy_scope": load_strategy_scope,
        "gate_policy": load_gate_policy,
        "glossary": load_glossary,
    }
    policy_checksums: dict[str, str] = {}
    for policy_name, loader in policy_loaders.items():
        result = loader()
        diagnostic_mode = diagnostic_mode or result.diagnostic_mode or result.policy is None
        if result.checksum != "unavailable":
            policy_checksums[policy_name] = result.checksum
    manifest_records = governance_payload.get("policies")
    if isinstance(manifest_records, dict):
        for policy_name, record in manifest_records.items():
            if isinstance(record, dict) and isinstance(record.get("sha256"), str):
                policy_checksums.setdefault(policy_name, record["sha256"])
    if len(policy_checksums) != 6:
        diagnostic_mode = True
    governance_payload.setdefault("schema_version", "1.0")
    governance_payload["diagnostic_mode"] = diagnostic_mode
    governance_payload["diagnostic_marker"] = "governance_diagnostic" if diagnostic_mode else "governance_valid"
    governance_payload["policy_checksums"] = policy_checksums
    governance_path.write_text(json.dumps(governance_payload, indent=2, sort_keys=True), encoding="utf-8")

    # Keep the older core packet entries while extending it with the complete
    # canonical set.  A path may only be unavailable when a marker was
    # explicitly written, so no optional source is silently omitted.
    required_specs = [
        *[(path, authority, allow) for path, authority, allow in _COMPLETE_AUDIT_REQUIRED],
        ("evidence_export/trust_critical_manifest.json", "evidence", False),
        ("evidence_export/governance/policy_checksums.json", "governance", False),
        ("evidence_export/governance/presentation-boundary-report.json", "architecture", False),
        ("01_portfolio_summary.json", "user_record", False),
        ("evidence_export/candle_context.csv", "derived", True),
        ("evidence_export/project_docs/open.md", "issue_dossier", True),
        ("evidence_export/source_conflicts.csv", "evidence", True),
    ]
    deduped_specs = list(dict.fromkeys(required_specs))

    required: list[dict[str, object]] = []
    # Unavailable markers must exist before either checksum manifest is
    # generated. Their payloads are then covered by both manifests.
    for path, authority, allow_unavailable in deduped_specs:
        record: dict[str, object] = {
            "path": path,
            "schema_version": 1,
            "source_authority": authority,
            "allow_unavailable": bool(allow_unavailable),
        }
        candidate = export_dir / Path(path)
        if candidate.is_file():
            pass
        elif allow_unavailable:
            if path.endswith("/session.jsonl"):
                marker_name = "session_log_unavailable.txt"
            elif path == "evidence_export/candle_context.csv":
                # Preserve the established audit-packet marker name used by
                # downstream readers while keeping the manifest explicit.
                marker_name = "candle_context_unavailable.txt"
            else:
                marker_name = f"{Path(path).stem}_{hashlib.sha256(path.encode()).hexdigest()[:10]}_unavailable.txt"
            marker = f"{Path(path).with_name(marker_name)}".replace("\\", "/")
            marker_path = export_dir / marker
            if not marker_path.is_file():
                marker_path = _write_unavailable_marker(marker_path, candidate, evidence_manifest)
            record["unavailable_marker"] = marker_path.relative_to(export_dir).as_posix()
            record["unavailable_reason"] = "source_not_available"
        required.append(record)

    # The checksum manifests intentionally exclude themselves and each other;
    # this avoids an impossible recursive self-hash while making the exclusion
    # explicit and machine-checkable.  The audit manifest below covers both
    # checksum-manifest files by their ordinary archive-relative hashes.
    _write_checksum_manifests(export_dir)
    checksums = _collect_checksums(export_dir)
    for checksum_path in ("checksum_manifest.json", "evidence_export/checksum_manifest.json"):
        checksum_file = export_dir / checksum_path
        if checksum_file.is_file():
            checksums[checksum_path] = _sha256_file(checksum_file)
    for item in required:
        item_path = str(item["path"])
        if item_path in checksums:
            item["sha256"] = checksums[item_path]
        elif item.get("unavailable_marker"):
            marker = str(item["unavailable_marker"])
            item["sha256"] = checksums.get(marker, "")
        else:
            item["sha256"] = ""
    (export_dir / "audit_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "complete-audit-v1",
                "required": required,
                "checksums": checksums,
                "derived": derived_manifest,
                "evidence": evidence_manifest,
                "governance": {
                    "schema_version": str(governance_payload.get("schema_version", "1.0")),
                    "diagnostic_mode": diagnostic_mode,
                    "diagnostic_marker": governance_payload["diagnostic_marker"],
                    "policy_checksums": policy_checksums,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _export_derived_evidence(export_dir: Path) -> dict[str, object]:
    manifest: dict[str, object] = {"included": [], "missing": []}
    scoreboard_path = DERIVED_DIR / "scoreboard.parquet"
    if scoreboard_path.exists():
        try:
            scoreboard = pd.read_parquet(scoreboard_path)
            scoreboard.to_csv(export_dir / "14_scoreboard.csv", index=False)
            scoreboard.to_json(export_dir / "14_scoreboard.json", orient="records", indent=2)
            evidence_dir = export_dir / "instrument_evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            for _, row in scoreboard.iterrows():
                instrument_id = _safe_file_stem(str(row.get("instrument_id") or row.get("symbol") or "instrument"))
                (evidence_dir / f"{instrument_id}.json").write_text(json.dumps(row.to_dict(), indent=2, default=str), encoding="utf-8")
            manifest["included"].append("14_scoreboard.csv")
            manifest["included"].append("14_scoreboard.json")
            manifest["included"].append("instrument_evidence/*.json")
        except Exception as exc:
            manifest["missing"].append(f"scoreboard export failed: {exc}")
    else:
        manifest["missing"].append("scoreboard.parquet")

    for source_name, export_name in (
        ("model_calibration.csv", "15_model_calibration.csv"),
        ("market_regime.json", "16_market_regime.json"),
        ("strategy_templates.csv", "17_strategy_templates.csv"),
    ):
        source = DERIVED_DIR / source_name
        if source.exists():
            (export_dir / export_name).write_bytes(source.read_bytes())
            manifest["included"].append(export_name)
        else:
            manifest["missing"].append(source_name)
    (export_dir / "18_derived_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["included"].append("18_derived_manifest.json")
    return manifest


def _export_trust_critical_evidence(export_dir: Path, config: AppConfig) -> dict[str, object]:
    evidence_root = export_dir / "evidence_export"
    evidence_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"included": [], "missing": [], "checksums": {}}
    if not SCORE_FORMULA_REGISTRY_PATH.exists():
        write_score_formula_registry()
    if not VERSION_REGISTRY_PATH.exists():
        write_version_registry()

    for source_path in (
        PROVIDER_PROBE_PATH,
        IDENTITY_PATH,
        SOURCE_CONFLICTS_PATH,
        EVIDENCE_LEDGER_PATH,
        SCORE_COMPONENTS_PATH,
        SCORE_HISTORY_PATH,
        SCORE_METRIC_HISTORY_PATH,
        SCORE_FORMULA_REGISTRY_PATH,
        VERSION_REGISTRY_PATH,
        FEATURE_DRIVERS_PATH,
        CORRELATION_CLUSTERS_PATH,
        BENCHMARK_ATTRIBUTION_PATH,
        FILINGS_STATEMENTS_PATH,
        STATEMENT_FACTS_PATH,
        FUND_DOCUMENTS_PATH,
        FUND_HOLDINGS_PATH,
        ETF_DISCLOSURES_PATH,
        PRIIPS_KID_RECORDS_PATH,
        INDEX_METHODOLOGY_RECORDS_PATH,
        NEWS_CONTEXT_PATH,
        NEWS_CONTEXT_PATH.with_suffix(".csv"),
        NEWS_CONTEXT_PATH.with_name(NEWS_CONTEXT_PATH.stem + "_audit.json"),
        NEWS_TIMESTAMP_VALIDATION_PATH,
        FUNDAMENTAL_CLEAN_PATH,
        FUNDAMENTAL_CLEAN_PATH.with_suffix(".csv"),
        FUNDAMENTAL_CLEAN_PATH.with_name(FUNDAMENTAL_CLEAN_PATH.stem + "_audit.json"),
    ):
        _copy_evidence_file(source_path, evidence_root, manifest)
    _copy_evidence_file(CANDLE_CONTEXT_PATH, evidence_root, manifest)
    _copy_evidence_tree(RUN_MANIFEST_DIR, evidence_root / "run_manifests", manifest)
    _copy_evidence_tree(FUNDAMENTAL_RAW_DIR, evidence_root / "raw_fundamentals", manifest)
    _copy_evidence_tree(NEWS_RAW_DIR, evidence_root / "raw_news_context", manifest)

    architecture_path = evidence_root / "governance" / "presentation-boundary-report.json"
    architecture_path.parent.mkdir(parents=True, exist_ok=True)
    architecture_path.write_text(json.dumps(build_architecture_report(ROOT), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _include_file(architecture_path, "governance/presentation-boundary-report.json", manifest)
    legal_terms_path = evidence_root / "governance" / "legal_terms_registry.json"
    legal_terms_path.write_text(json.dumps(legal_terms_report(ROOT), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _include_file(legal_terms_path, "governance/legal_terms_registry.json", manifest)

    session_destination = evidence_root / "session.jsonl"
    if copy_session_log_to(session_destination):
        _include_file(session_destination, "session.jsonl", manifest)
    else:
        marker = evidence_root / "session_log_unavailable.txt"
        _write_unavailable_marker(marker, SESSION_LOG_PATH, manifest, reason="session_log_unavailable")

    config_root = evidence_root / "configs"
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "data_providers_redacted.json").write_text(
        json.dumps(config.data_providers.redacted(), indent=2, default=str),
        encoding="utf-8",
    )
    for filename in ("universe.yaml", "portfolio_targets.yaml", "risk_limits.yaml", "costs.yaml", "model_settings.yaml", "ui_settings.yaml", "score_engine_v3.yaml", "audit_manifest.yaml", "legal_terms_registry.yaml"):
        source = CONFIG_DIR / filename
        if source.exists():
            target = config_root / filename
            target.write_text(_redact_config_text(source.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
            _include_file(target, f"configs/{filename}", manifest)
        else:
            manifest["missing"].append(f"configs/{filename}")
    _include_file(config_root / "data_providers_redacted.json", "configs/data_providers_redacted.json", manifest)

    docs_root = evidence_root / "project_docs"
    docs_root.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "plan.md", ROOT / "ISSUES.md", ROOT / "issues" / "open.md", ROOT / "issues" / "closed.md"):
        if source.exists():
            target = docs_root / source.name
            target.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            _include_file(target, f"project_docs/{source.name}", manifest)
        else:
            marker = docs_root / f"{source.stem}_unavailable.txt"
            _write_unavailable_marker(marker, source, manifest, reason="project_document_unavailable")

    _export_issue_dossiers(docs_root, manifest)
    _export_health_evidence(export_dir, config, manifest)
    _copy_optional_output(ROOT / "logs" / "workflow.jsonl", evidence_root, "workflow.jsonl", manifest)

    (evidence_root / "trust_critical_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    _include_file(evidence_root / "trust_critical_manifest.json", "trust_critical_manifest.json", manifest)
    return manifest


def _copy_optional_output(source: Path, evidence_root: Path, arcname: str, manifest: dict[str, object]) -> None:
    """Copy one optional local output while recording a machine-readable gap."""

    target = evidence_root / arcname
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.exists() and source.is_file():
        target.write_bytes(source.read_bytes())
        _include_file(target, arcname, manifest)
        return
    marker = target.with_name(f"{target.stem}_unavailable.txt")
    _write_unavailable_marker(marker, source, manifest)


def _write_unavailable_marker(marker: Path, source: Path, manifest: dict[str, object], *, reason: str | None = None) -> Path:
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "status": "unavailable",
        "path": str(source),
        "reason": reason or "source_not_available",
        "source_authority": "unknown",
        "executable_authority": False,
    }
    marker.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence_root = next((parent for parent in marker.parents if parent.name == "evidence_export"), None)
    archive_root = evidence_root.parent if evidence_root is not None else marker.parents[1]
    _include_file(marker, marker.relative_to(archive_root).as_posix(), manifest)
    manifest.setdefault("missing", []).append(str(source))
    return marker


def _export_issue_dossiers(docs_root: Path, manifest: dict[str, object]) -> None:
    """Persist issue files and a deterministic inventory for external review."""

    issues_root = ROOT / "issues"
    records: list[dict[str, object]] = []
    if issues_root.exists():
        for source in sorted(path for path in issues_root.rglob("*") if path.is_file()):
            relative = source.relative_to(issues_root).as_posix()
            target = docs_root / "issues" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            arcname = target.relative_to(docs_root.parent).as_posix()
            _include_file(target, arcname, manifest)
            records.append({"path": arcname, "sha256": _sha256_file(target), "source": relative})
    inventory = docs_root / "issue_dossiers.json"
    inventory.write_text(
        json.dumps({"schema_version": 1, "status": "available" if records else "unavailable", "dossiers": records, "executable_authority": False}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _include_file(inventory, "project_docs/issue_dossiers.json", manifest)
    if not records:
        manifest.setdefault("missing", []).append(str(issues_root))


def _write_bitemporal_manifest(destination: Path) -> None:
    try:
        with BitemporalStore(ROOT) as store:
            observations = store.observations(None)
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "observation_count": len(observations),
            "observations": [
                {
                    "observation_id": row.observation_id,
                    "dataset_id": row.dataset_id,
                    "entity_id": row.entity_id,
                    "stable_id": row.stable_id,
                    "run_id": row.run_id,
                    "revision": row.revision,
                    "valid_from": row.valid_from,
                    "valid_to": row.valid_to,
                    "published_at": row.published_at,
                    "available_at": row.available_at,
                    "observed_at": row.observed_at,
                    "revised_at": row.revised_at,
                    "source_id": row.source_id,
                    "source_checksum": row.source_checksum,
                    "timezone_confidence": row.timezone_confidence,
                    "availability_confidence": row.availability_confidence,
                    "status": row.status,
                }
                for row in observations
            ],
        }
    except Exception as exc:
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "observation_count": 0,
            "status": "unavailable",
            "error_type": type(exc).__name__,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _collect_checksums(export_dir: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for path in export_dir.rglob("*"):
        if path.is_file() and path.name not in {"audit_manifest.json", "checksum_manifest.json"}:
            checksums[str(path.relative_to(export_dir)).replace("\\", "/")] = _sha256_file(path)
    return checksums


def _write_checksum_manifests(export_dir: Path) -> None:
    """Write deterministic root and evidence copies without recursive self-hashes."""

    payload = {
        "schema_version": 1,
        "contract": "complete-audit-v1",
        "self_hash_excluded": True,
        "execution_allowed": False,
        "checksums": _collect_checksums(export_dir),
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    root_manifest = export_dir / "checksum_manifest.json"
    evidence_manifest = export_dir / "evidence_export" / "checksum_manifest.json"
    evidence_manifest.parent.mkdir(parents=True, exist_ok=True)
    root_manifest.write_text(encoded, encoding="utf-8")
    evidence_manifest.write_text(encoded, encoding="utf-8")


def _export_health_evidence(export_dir: Path, config: AppConfig, manifest: dict[str, object]) -> None:
    target = export_dir / "evidence_export" / "data_health.csv"
    try:
        report = build_data_health(config, ROOT)
        export_data_health(report, target)
        _include_file(target, "data_health.csv", manifest)
    except Exception as exc:
        _write_unavailable_marker(target.with_name("data_health_unavailable.txt"), target, manifest, reason=f"health_export_failed:{type(exc).__name__}")


def _copy_evidence_file(source_path: Path, evidence_root: Path, manifest: dict[str, object]) -> None:
    if source_path.suffix.lower() == ".parquet" and not source_path.exists():
        csv_mirror = source_path.with_suffix(".csv")
        if csv_mirror.exists():
            target = evidence_root / csv_mirror.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(csv_mirror.read_bytes())
            _include_file(target, target.name, manifest)
            return
    if not source_path.exists():
        relative = source_path.as_posix()
        try:
            relative = source_path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            pass
        digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:10]
        marker = evidence_root / f"{source_path.stem}_{digest}_unavailable.txt"
        _write_unavailable_marker(marker, source_path, manifest)
        return
    if source_path.suffix == ".parquet":
        try:
            frame = pd.read_parquet(source_path)
            csv_target = evidence_root / f"{source_path.stem}.csv"
            json_target = evidence_root / f"{source_path.stem}.json"
            frame.to_csv(csv_target, index=False)
            frame.to_json(json_target, orient="records", indent=2)
            _include_file(csv_target, csv_target.name, manifest)
            _include_file(json_target, json_target.name, manifest)
            return
        except Exception as exc:
            csv_mirror = source_path.with_suffix(".csv")
            if csv_mirror.exists():
                target = evidence_root / csv_mirror.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(csv_mirror.read_bytes())
                _include_file(target, target.name, manifest)
                return
            relative = source_path.as_posix()
            try:
                relative = source_path.resolve().relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                pass
            digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:10]
            marker = evidence_root / f"{source_path.stem}_{digest}_export_failed.txt"
            _write_unavailable_marker(marker, source_path, manifest, reason=f"export_failed:{type(exc).__name__}")
            return
    target = evidence_root / source_path.name
    target.write_bytes(source_path.read_bytes())
    _include_file(target, target.name, manifest)


def _copy_evidence_tree(source_root: Path, destination_root: Path, manifest: dict[str, object]) -> None:
    """Copy immutable raw generations into the audit packet when present."""

    if not source_root.exists():
        marker = destination_root.parent / f"{destination_root.name}_unavailable.txt"
        _write_unavailable_marker(marker, source_root, manifest)
        return
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative = source.relative_to(source_root)
        target = destination_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        _include_file(target, target.relative_to(destination_root.parent).as_posix(), manifest)


def _include_file(path: Path, arcname: str, manifest: dict[str, object]) -> None:
    manifest.setdefault("included", []).append(str(arcname))
    manifest.setdefault("checksums", {})[str(arcname)] = _sha256_file(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return ""


def _redact_config_text(text: str) -> str:
    redacted_lines = []
    for line in text.splitlines():
        if "api_key:" in line.lower() or "token:" in line.lower() or "secret:" in line.lower() or "password:" in line.lower():
            prefix = line.split(":", 1)[0]
            redacted_lines.append(f"{prefix}: \"***redacted***\"")
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines) + "\n"


def _safe_file_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return cleaned or "instrument"


def _safe_optional_frame(path: Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()
    except Exception:
        return pd.DataFrame()
