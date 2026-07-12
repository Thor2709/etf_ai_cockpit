from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from math import isfinite

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.logging import append_jsonl
from etf_cockpit.core.scheduler import current_run_id
from etf_cockpit.core.types import DataQualityReport, SignalResult
from etf_cockpit.governance.gate_policy import resolve_authority
from etf_cockpit.portfolio.allocation import allocation_frame
from etf_cockpit.portfolio.costs import estimated_cost_bps
from etf_cockpit.portfolio.holdings import portfolio_value
from etf_cockpit.portfolio.rebalancing import proposed_new_weight, suggested_trade_value
from etf_cockpit.signals.actions import advisory_action, apply_gate_result, preliminary_action
from etf_cockpit.signals.explanations import explain_signal
from etf_cockpit.signals.gates import evaluate_risk_gates
from etf_cockpit.signals.scoring import component_scores, row_components
from etf_cockpit.signals.research_states import GateResult, research_state_for_legacy_action


def generate_signals(
    config: AppConfig,
    latest_features: pd.DataFrame,
    holdings: pd.DataFrame,
    data_report: DataQualityReport,
    *,
    as_of_date: date | None = None,
    run_id: str | None = None,
    toto_available: bool = False,
    timesfm_available: bool = False,
    forecast_scores: dict[str, dict[str, float]] | None = None,
) -> list[SignalResult]:
    run_id = run_id or current_run_id("signals")
    signal_date = as_of_date or data_report.as_of_date
    allocation = allocation_frame(config, holdings)
    scored = component_scores(
        latest_features,
        allocation,
        config,
        toto_available=toto_available,
        timesfm_available=timesfm_available,
        forecast_scores=forecast_scores,
    )
    scored = scored.merge(allocation[["etf_id", "drift", "role", "name"]], on="etf_id", how="left")
    scored["cost_bps"] = scored["etf_id"].map(lambda etf_id: estimated_cost_bps(config, str(etf_id)))
    scored["expected_edge_60d"] = (
        0.50 * scored["momentum_60d"].fillna(0)
        + 0.25 * scored["momentum_120d"].fillna(0)
        + 0.25 * scored["relative_strength_60d"].fillna(0)
    ).clip(-0.30, 0.30)

    total_value = portfolio_value(holdings)
    cash_weight = max(0.0, 1.0 - float(holdings["current_weight"].sum()))
    signals: list[SignalResult] = []
    for _, row in scored.sort_values("total_score", ascending=False).iterrows():
        current_weight = float(row.get("current_weight") or 0.0)
        target_weight = float(row.get("target_weight") or 0.0)
        hard_band = float(row.get("hard_band") or 0.05)
        candidate = preliminary_action(
            config,
            total_score=float(row["total_score"]),
            confidence=float(row["confidence"]),
            current_weight=current_weight,
            drift=float(row.get("drift") or 0.0),
            hard_band=hard_band,
            trend_200=float(row.get("trend_200") or 0.0),
        )
        forecast_vol = float(row.get("ewma_vol_ann") or 0.0)
        projected_weight = proposed_new_weight(
            current_weight,
            target_weight,
            candidate,
            config.risks.portfolio_limits.max_trade_fraction_of_portfolio,
            forecast_vol=forecast_vol if forecast_vol > 0 else None,
        )
        blocked_by, warnings = evaluate_risk_gates(
            config,
            row,
            data_report,
            candidate_action=candidate,
            projected_weight=projected_weight,
            cash_weight=cash_weight,
            model_disagreement=0.0,
        )
        preliminary_trade_value = suggested_trade_value(total_value, current_weight, projected_weight)
        if candidate in {"buy", "add", "trim", "sell"} and preliminary_trade_value is not None:
            if abs(preliminary_trade_value) < config.risks.portfolio_limits.min_trade_value_eur:
                blocked_by = sorted(set([*blocked_by, "minimum_trade_size"]))
        final_internal_action = apply_gate_result(candidate, blocked_by)
        if final_internal_action != candidate:
            projected_weight = None
        trade_value = suggested_trade_value(total_value, current_weight, projected_weight)
        final_action = advisory_action(final_internal_action)
        if final_action == "no_trade" and not blocked_by:
            if abs(float(row.get("drift") or 0.0)) <= hard_band:
                blocked_by = ["inside_deadband"]
            else:
                blocked_by = ["no_trade_conservative"]
        reason_short, reason_long = explain_signal(row, final_action, blocked_by)
        status = "blocked" if blocked_by else ("warning" if warnings else "ok")
        expected_edge = float(row.get("expected_edge_60d") or 0.0)
        estimated_cost = float(row.get("cost_bps") or 0.0)
        expected_edge_bps = expected_edge * 10_000
        edge_to_cost_ratio = abs(expected_edge_bps) / estimated_cost if estimated_cost else None
        drift_percent = float(row.get("drift") or 0.0)
        drift_eur = drift_percent * total_value
        cost_stress = _cost_stress_metrics(
            config,
            etf_id=str(row["etf_id"]),
            expected_edge_bps=expected_edge_bps,
            base_cost_bps=estimated_cost,
            trade_value_eur=trade_value,
        )
        signal = SignalResult(
            run_id=run_id,
            signal_date=signal_date,
            etf_id=str(row["etf_id"]),
            action=final_action,
            confidence=round(float(row["confidence"]), 4),
            total_score=round(float(row["total_score"]), 4),
            components=row_components(row),
            blocked_by=blocked_by,
            warnings=warnings,
            reason_short=reason_short,
            reason_long=reason_long,
            horizon_primary="1-3 months",
            supporting_metrics={
                "raw_signal_score": float(row["total_score"]),
                "short_term_alert_score": float(row.get("momentum_20d") or 0.0),
                "medium_term_signal_score": float(
                    0.50 * float(row.get("momentum_60d") or 0.0)
                    + 0.50 * float(row.get("momentum_120d") or 0.0)
                ),
                "rebalance_signal": float(row.get("score_rebalance") or 0.0),
                "risk_signal": float(row.get("score_risk") or 0.0),
                "toto_score": float(row.get("score_toto") or 0.0),
                "timesfm_score": float(row.get("score_timesfm") or 0.0),
                "baseline_score": float(row.get("score_baseline_ml") or 0.0),
                "momentum_60d": float(row.get("momentum_60d") or 0.0),
                "momentum_120d": float(row.get("momentum_120d") or 0.0),
                "trend_200": float(row.get("trend_200") or 0.0),
                "vol_60d_ann": float(row.get("vol_60d_ann") or 0.0),
                "drawdown_current": float(row.get("drawdown_current") or 0.0),
                "current_weight": current_weight,
                "target_weight": target_weight,
                "drift_eur": drift_eur,
                "drift_percent": drift_percent,
                "expected_edge_bps": expected_edge_bps,
                "estimated_cost_bps": estimated_cost,
                "edge_to_cost_ratio": edge_to_cost_ratio,
                **cost_stress,
                "min_edge_to_cost_ratio": config.risks.portfolio_limits.min_edge_to_cost_ratio,
                "trade_value_eur": trade_value,
                "min_trade_value_eur": config.risks.portfolio_limits.min_trade_value_eur,
                "blocked_by": "|".join(blocked_by),
                "final_action": final_action,
                "reason_full": reason_long,
                "cost_bps": estimated_cost,
            },
            suggested_trade_value_eur=round(trade_value, 2) if trade_value is not None else None,
            suggested_new_weight=round(projected_weight, 4) if projected_weight is not None else None,
            status=status,
            model_versions_used={
                "baseline": "momentum_shrunk_v1",
                "timesfm": "unavailable" if not timesfm_available else "timesfm_2_5_optional",
                "toto": "unavailable" if not toto_available else "toto_2_0_optional",
            },
            timestamp=datetime.now(timezone.utc),
        )
        signals.append(_attach_authority(signal, data_report))

    append_jsonl("signal_log.jsonl", "signals_generated", {"signals": [_signal_to_json(signal) for signal in signals]}, run_id=run_id)
    return signals


def _signal_to_json(signal: SignalResult) -> dict[str, object]:
    # Operational signal traces use the v2 authority seam.  The legacy
    # ``action``/``final_action`` values remain available on the in-memory
    # object for compatibility callers but are not published here.
    data = signal.to_v2_dict()
    data.update(
        {
            "run_id": signal.run_id,
            "signal_date": signal.signal_date.isoformat(),
            "etf_id": signal.etf_id,
            "confidence": signal.confidence,
            "total_score": signal.total_score,
            "blocked_by": signal.blocked_by,
            "warnings": signal.warnings,
            "reason_short": signal.reason_short,
            "reason_long": signal.reason_long,
            "timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
        }
    )
    return data


def _attach_authority(signal: SignalResult, data_report: DataQualityReport) -> SignalResult:
    """Resolve and attach the typed gate decision before release serialisation.

    Signal generation does not have a portfolio-review snapshot, so that
    dimension remains explicitly not applicable. Missing evidence is recorded
    as a failed gate rather than being treated as a pass.
    """

    etf_issues = [issue for issue in data_report.issues if issue.etf_id in {signal.etf_id, "ALL"}]
    blocked_codes = set(signal.blocked_by)
    warning_codes = set(signal.warnings)
    has_dataset_evidence = any(
        bool(metadata.checksum and metadata.provider_or_manual_source)
        for metadata in data_report.dataset_metadata
    )
    risk_blocks = {
        "portfolio_validation_block",
        "expected_drawdown_gate",
        "cash_minimum_breached",
        "model_disagreement",
        "edge_below_cost_threshold",
    }
    gates = [
        GateResult(
            gate_id="identity",
            passed=bool(signal.etf_id.strip()),
            message="ETF identity is present" if signal.etf_id.strip() else "ETF identity is missing",
        ),
        GateResult(
            gate_id="data_quality",
            passed=not any(issue.severity == "block" for issue in etf_issues),
            message="No blocking data-quality issue" if not any(issue.severity == "block" for issue in etf_issues) else "Blocking data-quality issue",
        ),
        GateResult(
            gate_id="evidence",
            passed=has_dataset_evidence,
            message="Dated provider evidence is available" if has_dataset_evidence else "Dated provider evidence is unavailable",
        ),
        GateResult(
            gate_id="model_validity",
            passed=isfinite(float(signal.total_score)) and signal.model_versions_used.get("baseline") not in {None, "unavailable"},
            message="Baseline score and model version are present",
        ),
        GateResult(
            gate_id="risk",
            passed=not bool(blocked_codes & risk_blocks),
            message="No blocking risk gate" if not blocked_codes & risk_blocks else "Risk gate blocked",
        ),
        GateResult(
            gate_id="valuation",
            passed=False,
            message="Valuation context is unavailable to signal generation",
        ),
        GateResult(
            gate_id="signal",
            passed=not warning_codes,
            message="No signal warnings" if not warning_codes else "Signal warnings remain visible",
        ),
        GateResult(
            gate_id="portfolio_fit",
            passed="portfolio_validation_block" not in blocked_codes,
            message="Portfolio constraints are available" if "portfolio_validation_block" not in blocked_codes else "Portfolio validation blocked",
        ),
        GateResult(
            gate_id="cost",
            passed="edge_below_cost_threshold" not in blocked_codes,
            message="Edge clears configured cost threshold" if "edge_below_cost_threshold" not in blocked_codes else "Edge is below configured cost threshold",
        ),
    ]
    decision = resolve_authority(research_state_for_legacy_action(signal.action), gates, None)
    return replace(signal, authority_decision=decision)


def _cost_stress_metrics(
    config: AppConfig,
    *,
    etf_id: str,
    expected_edge_bps: float,
    base_cost_bps: float,
    trade_value_eur: float | None,
) -> dict[str, object]:
    commission_bps = 0.0
    if trade_value_eur is not None and abs(trade_value_eur) > 0:
        commission_bps = config.costs.cost_model.default_commission_eur / abs(trade_value_eur) * 10_000.0
    low_cost = max(0.0, base_cost_bps * 0.75 + commission_bps)
    base_cost = max(0.0, base_cost_bps + commission_bps)
    high_cost = max(0.0, base_cost_bps * 1.75 + commission_bps * 1.25)
    min_ratio = config.risks.portfolio_limits.min_edge_to_cost_ratio
    low_ratio = _edge_to_cost(expected_edge_bps, low_cost)
    base_ratio = _edge_to_cost(expected_edge_bps, base_cost)
    high_ratio = _edge_to_cost(expected_edge_bps, high_cost)
    if high_ratio is not None and high_ratio >= min_ratio:
        warning = "edge_survives_high_cost_stress"
    elif base_ratio is not None and base_ratio >= min_ratio:
        warning = "edge_fails_high_cost_stress"
    elif base_ratio is not None:
        warning = "edge_fails_base_cost"
    else:
        warning = "insufficient_edge_or_cost"
    return {
        "cost_low_bps": round(low_cost, 4),
        "cost_base_bps": round(base_cost, 4),
        "cost_high_bps": round(high_cost, 4),
        "edge_to_cost_low": None if low_ratio is None else round(low_ratio, 4),
        "edge_to_cost_base": None if base_ratio is None else round(base_ratio, 4),
        "edge_to_cost_high": None if high_ratio is None else round(high_ratio, 4),
        "cost_stress_warning": warning,
        "cost_stress_assumptions": (
            f"Low/base/high scenarios use 0.75x/1.00x/1.75x configured spread+slippage+FX for {etf_id}; "
            "commission is converted to bps only when a trade value exists."
        ),
    }


def _edge_to_cost(expected_edge_bps: float, cost_bps: float) -> float | None:
    if cost_bps <= 0:
        return None
    return abs(expected_edge_bps) / cost_bps
