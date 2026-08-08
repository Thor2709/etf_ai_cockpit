from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import requests
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from etf_cockpit.audit.thesis_diary import ThesisDiaryStore, build_thesis_entry, sha256_value
from etf_cockpit.core.paths import CONFIG_DIR, DATA_DIR, REPORTS_DIR
from etf_cockpit.services import CockpitSnapshot


LOCAL_LLM_CONFIG_PATH = CONFIG_DIR / "local_llm.yaml"


class LocalLLMSettings(BaseModel):
    enabled: bool = True
    base_url: str = "http://localhost:1234/v1"
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = Field(default=60, gt=0, le=120)
    max_tokens: int = Field(default=700, ge=128, le=4000)


class LocalLLMStatus(BaseModel):
    status: Literal["disabled", "ok", "unavailable"]
    message: str
    base_url: str
    model: str | None = None


class LocalAuditCommentary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4000)
    blocked_trade_explanations: list[str] = Field(default_factory=list, max_length=20)
    contradictions: list[str] = Field(default_factory=list, max_length=20)
    external_review_questions: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)
    executable_authority: Literal[False] = False


def load_local_llm_settings(path: Path = LOCAL_LLM_CONFIG_PATH) -> LocalLLMSettings:
    if not path.exists():
        return LocalLLMSettings()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return LocalLLMSettings.model_validate(data)


def _headers(settings: LocalLLMSettings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    return headers


def check_local_llm_status(settings: LocalLLMSettings | None = None) -> LocalLLMStatus:
    settings = settings or load_local_llm_settings()
    if not settings.enabled:
        return LocalLLMStatus(status="disabled", message="Local LLM audit is disabled in configs/local_llm.yaml.", base_url=settings.base_url)
    try:
        response = requests.get(f"{settings.base_url.rstrip('/')}/models", headers=_headers(settings), timeout=settings.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("data", []) if isinstance(payload, dict) else []
        model_id = settings.model or (models[0].get("id") if models and isinstance(models[0], dict) else None)
        if not model_id:
            return LocalLLMStatus(status="unavailable", message="Local LLM endpoint is reachable but no model id was returned.", base_url=settings.base_url)
        return LocalLLMStatus(status="ok", message="Local LLM endpoint is reachable.", base_url=settings.base_url, model=model_id)
    except requests.exceptions.RequestException:
        return LocalLLMStatus(
            status="unavailable",
            message="Local LLM endpoint unavailable. Start the LM Studio local server or leave this optional workflow unused.",
            base_url=settings.base_url,
        )
    except Exception as exc:
        return LocalLLMStatus(status="unavailable", message=f"Local LLM status check failed: {type(exc).__name__}", base_url=settings.base_url)


def build_local_audit_context(snapshot: CockpitSnapshot) -> dict[str, Any]:
    signal_rows = []
    for signal in snapshot.signals:
        metrics = signal.supporting_metrics
        signal_rows.append(
            {
                "etf_id": signal.etf_id,
                "final_action": signal.supporting_metrics.get("final_action", signal.action),
                "blocked_by": signal.blocked_by,
                "reason_full": signal.supporting_metrics.get("reason_full", signal.reason_long),
                "edge_to_cost_ratio": signal.supporting_metrics.get("edge_to_cost_ratio"),
                "input_sources": ["cockpit_snapshot", f"signal:{signal.etf_id}"],
                "evidence_score": next((metrics.get(key) for key in ("evidence_score_10", "evidence_score", "canonical_attractiveness_10") if metrics.get(key) is not None), None),
                "evidence_quality": next((metrics.get(key) for key in ("evidence_quality_10", "evidence_quality", "canonical_evidence_confidence_10") if metrics.get(key) is not None), None),
                "risk_friction": metrics.get("risk_friction_10"),
                "final_advisory_label": metrics.get("final_label", signal.action),
                "model_allowed_in_score": {
                    key: value
                    for key, value in signal.supporting_metrics.items()
                    if key.endswith("_model_allowed_in_score")
                },
            }
        )
    if "strategy_name" in snapshot.backtest.results.columns:
        signal_strategy = snapshot.backtest.results[snapshot.backtest.results["strategy_name"] == "signal_strategy"]
    else:
        signal_strategy = snapshot.backtest.results.iloc[0:0]
    backtest_row = signal_strategy.iloc[0].to_dict() if not signal_strategy.empty else {}
    return {
        "as_of_date": snapshot.data_report.as_of_date.isoformat(),
        "data_status": snapshot.data_report.status,
        "trading_allowed": False,
        "validation_issues": [
            {"severity": issue.severity, "code": issue.code, "message": issue.message}
            for issue in snapshot.data_report.issues
        ],
        "model_status": snapshot.model_status,
        "signals": signal_rows,
        "backtest": {
            key: backtest_row.get(key)
            for key in (
                "strategy_name",
                "cagr",
                "sharpe",
                "max_drawdown",
                "turnover_annualised",
                "backtest_quality",
                "probabilistic_sharpe",
                "deflated_sharpe",
                "pbo_probability_backtest_overfitting",
                "parameter_sensitivity_status",
                "overfitting_warning",
                "worst_1d_return",
                "worst_5d_return",
                "worst_10d_return",
                "loss_cluster_max_days",
            )
        },
        "backtest_metadata": snapshot.backtest.metadata,
        "authority": "commentary_only_no_trade_execution",
    }


def parse_local_llm_response(content: str) -> LocalAuditCommentary:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Local LLM response did not contain a JSON object.")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Local LLM response was not valid JSON: {exc}") from exc
    try:
        return LocalAuditCommentary.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Local LLM response failed schema validation: {exc}") from exc


def build_local_audit_prompt(context: dict[str, Any]) -> str:
    """Build the deterministic prompt persisted with a local thesis."""

    return (
        "You are auditing a local ETF decision-support cockpit. "
        "Only explain deterministic outputs supplied in JSON. "
        "Do not calculate portfolio metrics, invent data, override risk gates, or recommend direct buy/sell execution. "
        "Return exactly one JSON object with fields: summary, blocked_trade_explanations, contradictions, "
        "external_review_questions, confidence, executable_authority. executable_authority must be false.\n\n"
        f"Audit context:\n{json.dumps(context, default=str, indent=2)}"
    )


def generate_local_audit_commentary(
    context: dict[str, Any],
    settings: LocalLLMSettings | None = None,
) -> tuple[LocalLLMStatus, LocalAuditCommentary | None]:
    settings = settings or load_local_llm_settings()
    status = check_local_llm_status(settings)
    if status.status != "ok" or not status.model:
        return status, None
    prompt = build_local_audit_prompt(context)
    body = {
        "model": status.model,
        "messages": [
            {"role": "system", "content": "You provide non-executable audit commentary only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": settings.max_tokens,
    }
    response = requests.post(
        f"{settings.base_url.rstrip('/')}/chat/completions",
        headers=_headers(settings),
        json=body,
        timeout=settings.timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return status, parse_local_llm_response(content)


def save_local_audit_commentary(
    commentary: LocalAuditCommentary,
    *,
    model: str | None,
    context: dict[str, Any] | None = None,
    directory: Path = REPORTS_DIR,
    diary_root: Path = DATA_DIR,
) -> Path:
    context = context or {"status": "unavailable", "authority": "commentary_only_no_trade_execution"}
    model_name = model or "unavailable"
    signals = context.get("signals")
    scoped_signals = signals if isinstance(signals, list) and signals else [{"etf_id": context.get("instrument_id", "unavailable"), "input_sources": ["cockpit_snapshot"]}]
    stored_entries = []
    for signal in scoped_signals:
        signal = signal if isinstance(signal, dict) else {}
        instrument_id = str(signal.get("etf_id") or context.get("instrument_id") or "unavailable")
        scoped_context = {**context, "signals": [signal], "instrument_id": instrument_id}
        prompt = build_local_audit_prompt(scoped_context)
        input_sources = sorted({str(source) for source in signal.get("input_sources", []) if str(source).strip()} | {"cockpit_snapshot", f"signal:{instrument_id}"})
        source_snapshot = {"source": "cockpit_snapshot", "input_sources": input_sources, "snapshot": scoped_context}
        retrieval_snapshot = {
            "method": "build_local_audit_context.v1",
            "context_hash": sha256_value(scoped_context),
            "fields": sorted(scoped_context),
        }
        metadata = scoped_context.get("backtest_metadata")
        forward_only = isinstance(metadata, dict) and metadata.get("forward_only") is True and metadata.get("llm_available_at_decision") is True
        entry = build_thesis_entry(
            prompt=prompt,
            model=model_name,
            instrument_id=instrument_id,
            input_sources=input_sources,
            source_snapshot=source_snapshot,
            retrieval_snapshot=retrieval_snapshot,
            evidence_snapshot=scoped_context,
            llm_output=commentary.model_dump(mode="json"),
            thesis_summary=commentary.summary,
            risk_summary="; ".join(commentary.blocked_trade_explanations) or "No additional risk summary supplied.",
            contradiction_summary="; ".join(commentary.contradictions) or "No contradictions supplied.",
            uncertainty=1.0 - commentary.confidence,
            evidence_score=signal.get("evidence_score"),
            evidence_quality=signal.get("evidence_quality"),
            risk_friction=signal.get("risk_friction"),
            final_advisory_label=str(signal.get("final_advisory_label") or "manual_review"),
            backtest_validity="forward_only" if forward_only else "unknown",
        )
        stored_entries.append(ThesisDiaryStore(diary_root).create(entry))
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"local_llm_audit_{timestamp}.json"
    payload = {
        "source": "local_lm_studio",
        "model": model_name,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "thesis_id": stored_entries[0].thesis_id if len(stored_entries) == 1 else None,
        "thesis_ids": [entry.thesis_id for entry in stored_entries],
        "thesis_checksums": {entry.thesis_id: entry.checksum for entry in stored_entries},
        "instrument_ids": [entry.instrument_id for entry in stored_entries],
        "executable_authority": False,
        "commentary": commentary.model_dump(),
        "thesis_records": [entry.model_dump(mode="json") for entry in stored_entries],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
