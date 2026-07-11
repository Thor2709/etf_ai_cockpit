from __future__ import annotations

import json
import hashlib
import zipfile
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from etf_cockpit.backtest.engine import BacktestReport
from etf_cockpit.chatgpt_bridge.prompts import CHATGPT_REVIEW_PROMPT
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import AUDIT_PACKETS_DIR, CONFIG_DIR, DERIVED_DIR, ROOT
from etf_cockpit.core.session_log import SESSION_LOG_PATH, copy_session_log_to
from etf_cockpit.core.types import DataQualityReport, SignalResult
from etf_cockpit.data.fx_data import fx_data_inventory
from etf_cockpit.data.manual_notes import MANUAL_NEWS_CLEAN_PATH, load_manual_news, manual_news_markdown
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
    SOURCE_CONFLICTS_PATH,
)
from etf_cockpit.portfolio.allocation import allocation_frame


# Backwards-compatible name for older scripts/tests; new exports default to data/audit_packets.
CHATGPT_EXPORTS_DIR = AUDIT_PACKETS_DIR
CANDLE_CONTEXT_PATH = DERIVED_DIR / "candle_context.parquet"

SIGNAL_TABLE_COLUMNS = [
    "etf_id",
    "name",
    "action",
    "confidence",
    "total_score",
    "final_action",
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
        rows.append(
            {
                "etf_id": signal.etf_id,
                "name": names.get(signal.etf_id, signal.etf_id),
                "action": signal.action,
                "confidence": signal.confidence,
                "total_score": signal.total_score,
                "final_action": signal.supporting_metrics.get("final_action", signal.action),
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
        "holdings": allocation[
            ["etf_id", "name", "current_weight", "target_weight", "drift", "role", "region", "sector", "currency"]
        ].to_dict(orient="records"),
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
    (export_dir / "06_recent_news_events.md").write_text(manual_news_markdown(manual_news), encoding="utf-8")
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
        "trading_allowed": data_report.trading_allowed if data_report else None,
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
                "final_action": signal.action,
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
    required = [
        {
            "path": "evidence_export/session.jsonl",
            "allow_unavailable": True,
            "unavailable_marker": "evidence_export/session_log_unavailable.txt",
        },
        {"path": "evidence_export/trust_critical_manifest.json", "allow_unavailable": False},
        {"path": "evidence_export/configs/data_providers_redacted.json", "allow_unavailable": False},
        {
            "path": "evidence_export/project_docs/open.md",
            "allow_unavailable": True,
            "unavailable_marker": "evidence_export/project_docs/open_unavailable.txt",
        },
        {
            "path": "evidence_export/candle_context.csv",
            "allow_unavailable": True,
            "unavailable_marker": "evidence_export/candle_context_unavailable.txt",
        },
        {
            "path": "evidence_export/source_conflicts.csv",
            "allow_unavailable": True,
            "unavailable_marker": "evidence_export/source_conflicts_unavailable.txt",
        },
        {"path": "01_portfolio_summary.json", "allow_unavailable": False},
    ]
    checksums: dict[str, str] = {}
    for path in export_dir.rglob("*"):
        if path.is_file() and path.name != "audit_manifest.json":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            checksums[str(path.relative_to(export_dir)).replace("\\", "/")] = digest
    (export_dir / "audit_manifest.json").write_text(
        json.dumps({"schema_version": 1, "required": required, "checksums": checksums, "derived": derived_manifest, "evidence": evidence_manifest}, indent=2, sort_keys=True),
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

    for source_path in (
        PROVIDER_PROBE_PATH,
        IDENTITY_PATH,
        SOURCE_CONFLICTS_PATH,
        EVIDENCE_LEDGER_PATH,
        SCORE_COMPONENTS_PATH,
        SCORE_HISTORY_PATH,
        SCORE_METRIC_HISTORY_PATH,
        FEATURE_DRIVERS_PATH,
        CORRELATION_CLUSTERS_PATH,
        BENCHMARK_ATTRIBUTION_PATH,
        FILINGS_STATEMENTS_PATH,
        ETF_DISCLOSURES_PATH,
        NEWS_CONTEXT_PATH,
        NEWS_TIMESTAMP_VALIDATION_PATH,
    ):
        _copy_evidence_file(source_path, evidence_root, manifest)
    _copy_evidence_file(CANDLE_CONTEXT_PATH, evidence_root, manifest)

    session_destination = evidence_root / "session.jsonl"
    if copy_session_log_to(session_destination):
        _include_file(session_destination, "session.jsonl", manifest)
    else:
        marker = evidence_root / "session_log_unavailable.txt"
        marker.write_text(f"Current session log unavailable at {SESSION_LOG_PATH}\n", encoding="utf-8")
        _include_file(marker, "session_log_unavailable.txt", manifest)

    config_root = evidence_root / "configs"
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "data_providers_redacted.json").write_text(
        json.dumps(config.data_providers.redacted(), indent=2, default=str),
        encoding="utf-8",
    )
    for filename in ("universe.yaml", "portfolio_targets.yaml", "risk_limits.yaml", "costs.yaml", "model_settings.yaml", "ui_settings.yaml"):
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
            marker.write_text(f"{source} is unavailable. Missing project documentation was not invented.\n", encoding="utf-8")
            _include_file(marker, f"project_docs/{marker.name}", manifest)
            manifest["missing"].append(str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source))

    (evidence_root / "trust_critical_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    _include_file(evidence_root / "trust_critical_manifest.json", "trust_critical_manifest.json", manifest)
    return manifest


def _copy_evidence_file(source_path: Path, evidence_root: Path, manifest: dict[str, object]) -> None:
    if not source_path.exists():
        marker = evidence_root / f"{source_path.stem}_unavailable.txt"
        marker.write_text(f"{source_path} is unavailable. Missing optional evidence was not invented.\n", encoding="utf-8")
        _include_file(marker, marker.name, manifest)
        manifest.setdefault("missing", []).append(str(source_path))
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
            marker = evidence_root / f"{source_path.stem}_export_failed.txt"
            marker.write_text(f"Could not export {source_path}: {exc}\n", encoding="utf-8")
            _include_file(marker, marker.name, manifest)
            return
    target = evidence_root / source_path.name
    target.write_bytes(source_path.read_bytes())
    _include_file(target, target.name, manifest)


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
