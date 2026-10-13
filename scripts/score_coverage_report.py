from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _coverage(score: object | None) -> float:
    score_coverage = getattr(score, "score_coverage", None)
    if score_coverage is not None:
        return float(score_coverage)
    canonical = getattr(score, "canonical_score", None)
    if canonical is not None:
        return float(canonical.coverage)
    return 0.0


def _asset_type(identity: object) -> str:
    extra = getattr(identity, "model_extra", None) or {}
    value = str(getattr(identity, "instrument_type", extra.get("instrument_type", getattr(identity, "asset_class", ""))) or "").strip().lower()
    if value in {"stock", "equity", "share", "common_stock"}:
        return "Stock"
    if value in {"certificate", "equity_certificate", "equity certificate", "egenkapitalbevis"}:
        return "Equity certificate"
    return "ETF"


def _first_failure(
    instrument_id: str,
    identity: object | None,
    price_count: int,
    valid_price_count: int,
    signal: object | None,
    score: object | None,
    process_error: str | None,
    identity_conflict: str | None,
    score_failure: str | None = None,
) -> str:
    if identity is None:
        return f"identity/routing: enabled instrument {instrument_id} has no configured identity"
    if identity_conflict:
        return f"identity/routing: {identity_conflict}"
    if price_count == 0:
        return f"obtain: no local price rows for {instrument_id} in data/clean/prices.parquet"
    if valid_price_count == 0:
        return f"obtain: {price_count} local rows for {instrument_id}, but none has a finite adjusted_close"
    if process_error:
        return f"process: {process_error}"
    if signal is None:
        return f"process: signal generation returned no result for {instrument_id} despite {valid_price_count} finite adjusted_close rows"
    if score is None:
        return f"score: score generation returned no result for {instrument_id}"
    if score_failure:
        return f"score: {score_failure}"
    if getattr(score, "final_label", "") == "scorecard_owned":
        return f"score: {getattr(score, 'one_line_reason', 'native scorecard owns this instrument')}"
    if getattr(score, "final_score_10", None) is not None:
        return "none"
    if getattr(score, "classification_dependency_status", "") != "current":
        warnings = ", ".join(str(item) for item in (getattr(score, "warnings", ()) or ())) or "none"
        return (
            "score: classification dependency status is "
            f"{getattr(score, 'classification_dependency_status', 'unavailable')}; warnings={warnings}"
        )
    components = getattr(score, "components", ()) or ()
    missing = next((item for item in components if not getattr(item, "score_eligible", False)), None)
    if missing is not None:
        return f"score: {getattr(missing, 'key', 'component')} is unavailable: {getattr(missing, 'why', 'no reason supplied')}"
    return f"show: no final score is available; {getattr(score, 'one_line_reason', 'no score reason supplied')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report score coverage for every enabled universe instrument.")
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="Temporary rcdata copy root")
    args = parser.parse_args()
    if not args.root:
        parser.error("set ETF_COCKPIT_ROOT or pass --root")
    root = Path(args.root).expanduser().resolve()
    if not (root / "configs" / "universe.yaml").is_file():
        parser.error(f"{root} does not contain configs/universe.yaml")
    os.environ["ETF_COCKPIT_ROOT"] = str(root)

    import pandas as pd

    from etf_cockpit.application.identity_views import load_identity_projection
    from etf_cockpit.application.financial_institution_views import load_financial_institution_projection
    from etf_cockpit.application.signal_service import SignalService
    from etf_cockpit.core.config import load_config
    from etf_cockpit.core.paths import CLEAN_DIR
    from etf_cockpit.data.duckdb_store import load_prices
    from etf_cockpit.data.score_history import score_history_frame
    from etf_cockpit.signals.simple_scores import build_simple_instrument_scores, simple_scoreboard_frame

    config = load_config(root / "configs")
    identities = config.universe.by_id()
    price_path = CLEAN_DIR / "prices.parquet"
    prices = load_prices() if price_path.exists() else pd.DataFrame()
    if not prices.empty and "date" in prices.columns:
        dates = pd.to_datetime(prices["date"], errors="coerce")
        as_of = dates.max().date() if dates.notna().any() else None
    else:
        as_of = None

    signals: list[object] = []
    process_error: str | None = None
    if as_of is not None:
        try:
            signals = list(SignalService(config).generate_signals(as_of_date=as_of))
        except Exception as exc:  # The report must still list every enabled ID.
            process_error = f"{type(exc).__name__}: {exc}"

    try:
        scores = build_simple_instrument_scores(
            config,
            signals,
            pd.DataFrame(),
            prices,
            universe_revision="coverage-report",
        )
    except Exception as exc:  # The report must retain per-instrument failure evidence.
        scores = []
        process_error = process_error or f"{type(exc).__name__}: {exc}"

    signal_by_id = {str(getattr(item, "etf_id", "")): item for item in signals}
    score_by_id = {str(getattr(item, "display_id", "")): item for item in scores}
    scoreboard = simple_scoreboard_frame(scores)
    scoreboard_by_id = (
        {str(row.get("instrument_id")): row for _, row in scoreboard.iterrows()}
        if not scoreboard.empty and "instrument_id" in scoreboard.columns
        else {}
    )
    history = score_history_frame(root=root)
    latest_history: dict[str, object] = {}
    if not history.empty and "instrument_id" in history.columns:
        ordered_history = history.sort_values("run_completed_at", kind="stable") if "run_completed_at" in history.columns else history
        latest_history = {
            str(row.get("instrument_id")): row
            for _, row in ordered_history.groupby("instrument_id", sort=False).tail(1).iterrows()
        }
    if prices.empty or "etf_id" not in prices.columns:
        price_groups: dict[str, pd.DataFrame] = {}
    else:
        price_groups = {str(key): group for key, group in prices.groupby("etf_id", sort=False)}

    native_scorecards: dict[str, dict[str, object]] = {}
    if as_of is not None:
        decision_time = f"{as_of.isoformat()}T23:59:59Z"
        for instrument_id in config.universe.enabled_ids:
            score = score_by_id.get(instrument_id)
            if score is None or getattr(score, "final_label", "") != "scorecard_owned":
                continue
            projection = load_financial_institution_projection(
                instrument_id,
                storage_root=root,
                decision_time=decision_time,
                effective_at=decision_time,
            )
            identity_payload = projection.get("share_class_identity")
            analysis = identity_payload.get("sparebank_analysis") if isinstance(identity_payload, dict) else None
            native_scorecards[instrument_id] = {
                "projection": projection,
                "analysis": analysis if isinstance(analysis, dict) else {},
            }

    print("instrument_id | asset_type | score | coverage | first_failing_step_and_reason")
    for instrument_id in config.universe.enabled_ids:
        identity = identities.get(instrument_id)
        group = price_groups.get(instrument_id, pd.DataFrame())
        price_count = len(group)
        if "adjusted_close" in group:
            valid_price_count = int(pd.to_numeric(group["adjusted_close"], errors="coerce").replace([float("inf"), float("-inf")], pd.NA).notna().sum())
        else:
            valid_price_count = 0
        projection = load_identity_projection(instrument_id, storage_root=root)
        conflict_ids = projection.get("identity_conflict_ids", ())
        if isinstance(conflict_ids, str):
            identity_conflict_ids = [value for value in conflict_ids.strip("[] ").replace("'", "").replace('"', "").split(",") if value and value != "unavailable"]
        elif isinstance(conflict_ids, (list, tuple, set)):
            identity_conflict_ids = [str(value) for value in conflict_ids if str(value).strip()]
        else:
            identity_conflict_ids = []
        conflict = None
        if identity_conflict_ids:
            conflict = f"identity conflict {', '.join(identity_conflict_ids)}"
        if identity is not None:
            identity_objects = projection.get("identity_objects", "")
            try:
                decoded_objects = json.loads(identity_objects) if isinstance(identity_objects, str) else identity_objects
            except (TypeError, ValueError):
                decoded_objects = ()
            if isinstance(decoded_objects, dict):
                decoded_objects = [decoded_objects]
            configured_type = _asset_type(identity)
            for item in decoded_objects if isinstance(decoded_objects, (list, tuple)) else ():
                fields = item.get("fields") if isinstance(item, dict) else None
                source_type = str(fields.get("asset_type") or "").strip().casefold() if isinstance(fields, dict) else ""
                source_type = "Equity certificate" if source_type in {"certificate", "equity_certificate", "equity certificate", "egenkapitalbevis"} else "Stock" if source_type in {"stock", "equity", "share", "common_stock"} else "ETF" if source_type == "etf" else source_type.title()
                if source_type and source_type != configured_type:
                    conflict = (
                        f"configured asset type {configured_type} conflicts with identity projection asset type {source_type}"
                    )
                    break
        score = score_by_id.get(instrument_id)
        coverage = None if score is not None and getattr(score, "final_label", "") == "scorecard_owned" else _coverage(score)
        score_value = getattr(score, "final_score_10", None) if score is not None else None
        native_failure = None
        native = native_scorecards.get(instrument_id)
        if native is not None:
            native_projection = native.get("projection", {})
            analysis = native.get("analysis", {})
            scorecard = analysis.get("scorecard", {}) if isinstance(analysis, dict) else {}
            if isinstance(scorecard, dict):
                native_score = scorecard.get("composite_10")
                if native_score is not None and not pd.isna(native_score):
                    score_value = float(native_score)
                native_coverage = scorecard.get("composite_coverage")
                if native_coverage is not None and not pd.isna(native_coverage):
                    coverage = float(native_coverage)
            if score_value is None:
                reason_code_value = native_projection.get("reason_code")
                reason_code = str(reason_code_value).strip() if reason_code_value else "scorecard_composite_unavailable"
                scorecard_reasons = scorecard.get("gate_reasons", ()) if isinstance(scorecard, dict) else ()
                missing_axes = scorecard.get("missing_axes", ()) if isinstance(scorecard, dict) else ()
                detail = ", ".join(str(value) for value in (*scorecard_reasons, *missing_axes) if str(value).strip())
                native_failure = f"Sparebank scorecard unavailable ({reason_code})" + (f"; {detail}" if detail else "")
        scoreboard_row = scoreboard_by_id.get(instrument_id, {})
        show_failure = None
        if score_value is not None:
            if "final_combined_score_10" not in scoreboard.columns:
                show_failure = (
                    "show: scoreboard output omits final_combined_score_10; "
                    "it publishes evidence_score_10 only"
                )
            elif pd.isna(scoreboard_row.get("final_combined_score_10")):
                show_failure = "show: final_combined_score_10 is null in the scoreboard output"
        native_history = latest_history.get(instrument_id) if score is not None and getattr(score, "final_label", "") == "scorecard_owned" else None
        if score_value is None and native_history is not None:
            score_value = native_history.get("final_combined_score_10")
            coverage_value = native_history.get("coverage", native_history.get("canonical_coverage", coverage))
            if coverage_value is not None and not pd.isna(coverage_value):
                coverage = float(coverage_value)
        score_text = "none" if score_value is None else f"{float(score_value):.3f}"
        coverage_text = "unavailable" if coverage is None else f"{coverage:.6f}"
        failure = (
            "none"
            if native_history is not None and score_value is not None
            else show_failure
            if show_failure is not None
            else _first_failure(
                instrument_id,
                identity,
                price_count,
                valid_price_count,
                signal_by_id.get(instrument_id),
                score,
                process_error,
                conflict,
                native_failure,
            )
        )
        print(f"{instrument_id} | {_asset_type(identity) if identity is not None else 'unknown'} | {score_text} | {coverage_text} | {failure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
