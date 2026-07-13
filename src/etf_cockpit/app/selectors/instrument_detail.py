from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import pandas as pd

from etf_cockpit.data.fund_documents import build_document_inventory, read_document_registry
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
from etf_cockpit.data.fundamentals import FUNDAMENTAL_CLEAN_PATH, latest_fundamental_rows, load_fundamental_evidence
from etf_cockpit.data.news_context import NEWS_CLEAN_PATH, load_news_items, sort_news_items
from etf_cockpit.data.parsed_disclosures import read_index_methodology_records, read_priips_kid_records
from etf_cockpit.data.run_changes import compare_runs
from etf_cockpit.data.score_history import score_history_frame
from etf_cockpit.data.trust_artifacts import BENCHMARK_ATTRIBUTION_PATH, CORRELATION_CLUSTERS_PATH, FEATURE_DRIVERS_PATH
from etf_cockpit.core.paths import DERIVED_DIR
from etf_cockpit.services import CockpitSnapshot


@dataclass(frozen=True)
class InstrumentDetailViewModel:
    instrument_id: str
    display_name: str
    status: str
    identity: dict[str, Any]
    sections: dict[str, Any]


_SECTION_NAMES = (
    "identity",
    "price",
    "scores",
    "feature_drivers",
    "risk",
    "attribution",
    "fundamentals",
    "etf_disclosures",
    "etf_holdings",
    "news",
    "forecasts",
    "backtests",
    "paper_trades",
    "history",
    "journal",
    "run_changes",
)
SCOREBOARD_PATH = DERIVED_DIR / "scoreboard.parquet"
PAPER_TRADES_PATH = DERIVED_DIR / "paper_trades.parquet"


def _unavailable(message: str) -> dict[str, Any]:
    """Return a consistent, non-authoritative unavailable panel."""

    return {"status": "unavailable", "message": message, "execution_allowed": False}


def _safe_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_frame(frame: object) -> pd.DataFrame:
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _load_parquet(path: object) -> pd.DataFrame:
    try:
        candidate = path
        if candidate is None or not candidate.exists():  # type: ignore[union-attr]
            return pd.DataFrame()
        return pd.read_parquet(candidate)  # type: ignore[arg-type]
    except Exception:
        return pd.DataFrame()


def _instrument_rows(frame: object, instrument_id: str, *, columns: tuple[str, ...] = ("instrument_id", "etf_id")) -> pd.DataFrame:
    source = _safe_frame(frame)
    if source.empty:
        return source
    available = [column for column in columns if column in source.columns]
    if not available:
        return source.iloc[0:0]
    mask = pd.Series(False, index=source.index)
    for column in available:
        mask |= source[column].astype(str).eq(str(instrument_id))
    return source.loc[mask].copy()


def _feature_driver_panel(instrument_id: str) -> dict[str, Any]:
    try:
        frame = pd.read_parquet(FEATURE_DRIVERS_PATH) if FEATURE_DRIVERS_PATH.exists() else pd.DataFrame()
    except Exception:
        frame = pd.DataFrame()
    frame = _normalise_feature_driver_frame(frame)
    if frame.empty or "instrument_id" not in frame.columns:
        return {"status": "unavailable", "rows": [], "message": "Feature drivers unavailable; no local component history is registered.", "execution_allowed": False}
    scoped = frame[frame["instrument_id"].astype(str).eq(str(instrument_id))].copy()
    if scoped.empty:
        return {"status": "unavailable", "rows": [], "message": "Feature drivers unavailable for this instrument.", "execution_allowed": False}
    scoped["_score_sort"] = pd.to_numeric(scoped.get("normalised_score"), errors="coerce")
    rows = scoped.drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    positive = scoped.loc[scoped["direction"].astype(str).eq("positive")].sort_values(["_score_sort", "component"], ascending=[False, True], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    negative = scoped.loc[scoped["direction"].astype(str).eq("negative")].sort_values(["_score_sort", "component"], ascending=[True, True], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    missing = scoped.loc[scoped["direction"].astype(str).eq("missing")].sort_values(["component"], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    low_authority = scoped.loc[scoped["flags"].astype(str).str.contains("low_authority", na=False)].sort_values(["component"], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    stale_or_partial = scoped.loc[scoped["flags"].astype(str).str.contains("stale|partial", na=False, regex=True)].sort_values(["component"], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    return {
        "status": "available",
        "rows": rows,
        "top_positive": positive[:3],
        "top_negative": negative[:3],
        "missing_or_na": missing,
        "low_authority": low_authority,
        "stale_or_partial": stale_or_partial,
        "execution_allowed": False,
    }


def _normalise_feature_driver_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Add modern feature-driver columns when reading a legacy local store."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    if "instrument_id" not in result.columns and "instrument" in result.columns:
        result["instrument_id"] = result["instrument"]
    if "instrument" not in result.columns and "instrument_id" in result.columns:
        result["instrument"] = result["instrument_id"]
    if "normalised_score" not in result.columns:
        result["normalised_score"] = result.get("normalised_score_10")
    if "raw_metric" not in result.columns:
        result["raw_metric"] = result.get("raw_metric_value")
    for column, default in (
        ("component", "unknown"),
        ("source_id", "unavailable"),
        ("authority", "unknown"),
        ("driver_text", "Feature driver unavailable; informational only."),
        ("source_dataset", "unavailable"),
        ("as_of_date", "unavailable"),
        ("freshness_status", "unknown"),
        ("classification", "unclassified"),
        ("authority_classification", "unknown"),
        ("freshness_classification", "unknown"),
        ("flags", "none"),
        ("execution_allowed", False),
    ):
        if column not in result.columns:
            result[column] = default
    if "direction" not in result.columns:
        score = pd.to_numeric(result["normalised_score"], errors="coerce")
        result["direction"] = score.map(lambda value: "missing" if pd.isna(value) else "positive" if value >= 6 else "negative" if value <= 4 else "mixed")
    result["flags"] = result["flags"].fillna("none").astype(str)
    derived_flags = result["flags"].eq("none")
    result.loc[derived_flags & result["direction"].astype(str).eq("missing"), "flags"] = "missing"
    result.loc[derived_flags & result["authority_classification"].astype(str).str.contains("low", case=False, na=False), "flags"] = "low_authority"
    result.loc[derived_flags & result["freshness_classification"].astype(str).str.contains("stale|partial", case=False, na=False, regex=True), "flags"] = "stale"
    return result


def _fundamentals_panel(instrument_id: str, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    try:
        source = frame if isinstance(frame, pd.DataFrame) else load_fundamental_evidence(FUNDAMENTAL_CLEAN_PATH)
    except Exception:
        return _unavailable("Fundamental evidence unavailable; the optional local store is missing or corrupt.") | {"score_eligible": False}
    if source.empty or "instrument_id" not in source.columns:
        return _unavailable("Fundamental evidence unavailable; no complete local five-section record is registered.") | {"score_eligible": False}
    try:
        scoped = latest_fundamental_rows(source[source["instrument_id"].astype(str).eq(str(instrument_id))])
    except Exception:
        return _unavailable("Fundamental evidence unavailable; the optional local store is malformed.") | {"score_eligible": False}
    if scoped.empty:
        return _unavailable("Fundamental evidence unavailable for this instrument.") | {"score_eligible": False}
    row = scoped.iloc[-1]
    return {
        "status": "available" if bool(row.get("score_eligible", False)) else "manual_review",
        "eligibility": row.get("eligibility", "not_score_eligible"),
        "score_eligible": bool(row.get("score_eligible", False)),
        "source": row.get("source", row.get("source_authority", "unavailable")),
        "source_authority": row.get("source_authority", "unavailable"),
        "as_of": row.get("as_of_date", "unavailable"),
        "missing_fields": str(row.get("missing_fields", "")),
        "warnings": str(row.get("warnings", "")),
        "limitations": str(row.get("limitations", "unavailable")),
        "sector_relative_status": row.get("sector_relative_status", "unavailable"),
        "sector_relative_value": row.get("sector_relative_value", "unavailable"),
        "sector_relative_peer": row.get("sector_relative_peer", "unavailable"),
        "sector_relative_benchmark": row.get("sector_relative_benchmark", "unavailable"),
        "sector_relative_delta": row.get("sector_relative_delta", "unavailable"),
        "sector_relative_limitation": row.get("sector_relative_limitation", "No sector-relative comparison evidence supplied."),
        "executable_authority": False,
        "execution_allowed": False,
    }


def _news_panel(instrument_id: str, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    try:
        source = frame if isinstance(frame, pd.DataFrame) else load_news_items(NEWS_CLEAN_PATH)
    except Exception:
        return _unavailable("News unavailable; the optional local store is missing or corrupt.") | {"items": [], "context_only": True, "executable_authority": False}
    if source.empty or "instrument_id" not in source.columns:
        return _unavailable("News unavailable; no timestamp-validated local items are registered.") | {"items": [], "context_only": True, "executable_authority": False}
    try:
        scoped = sort_news_items(source[source["instrument_id"].astype(str).eq(str(instrument_id))])
    except Exception:
        return _unavailable("News unavailable; the optional local store is malformed.") | {"items": [], "context_only": True, "executable_authority": False}
    if scoped.empty:
        return _unavailable("News unavailable for this instrument.") | {"items": [], "context_only": True, "executable_authority": False}
    items = [_news_item_record(row) for row in scoped.tail(20).to_dict("records")]
    return {"status": "available", "message": "News is context-only and cannot change deterministic scores.", "items": items, "context_only": True, "executable_authority": False, "execution_allowed": False}


def _news_item_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise every row to the provenance fields rendered by Instrument Detail."""

    item = dict(row)
    item.update(
        {
            "source_url": item.get("source_url") or item.get("url") or "unavailable",
            "published_at": item.get("published_at") or "unavailable",
            "ingested_at": item.get("ingested_at") or "unavailable",
            "provider_name": item.get("provider_name") or item.get("provider") or "unavailable",
            "credibility": item.get("credibility") or "unverified",
            "instrument_mapping_method": item.get("instrument_mapping_method") or "unavailable",
            "available_at_decision_time": bool(item.get("available_at_decision_time", False)),
            "timestamp_status": item.get("timestamp_status") or item.get("timestamp_confidence") or "unavailable",
            "context_only": True,
            "executable_authority": False,
        }
    )
    return item


def _etf_disclosure_panel(
    instrument_id: str,
    *,
    document_registry: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
    kid_records: pd.DataFrame | None = None,
    methodology_records: pd.DataFrame | None = None,
) -> dict[str, Any]:
    try:
        registry = document_registry.copy() if isinstance(document_registry, pd.DataFrame) else read_document_registry()
    except Exception:
        registry = pd.DataFrame()
    registry_manual_review = False
    registry_message = ""
    if not registry.empty:
        registry_id_column = next((column for column in ("instrument_id", "etf_id") if column in registry.columns), None)
        if registry_id_column is None:
            registry_manual_review = True
            registry_message = "ETF disclosure registry is missing a canonical instrument_id or etf_id column; manual review is required."
            inventory = pd.DataFrame()
        else:
            registry = registry[registry[registry_id_column].astype(str).eq(str(instrument_id))].copy()
    if not registry_manual_review and registry.empty:
        try:
            inventory = build_document_inventory([instrument_id])
        except Exception:
            inventory = pd.DataFrame()
    elif not registry_manual_review:
        inventory = registry
    document_rows = []
    for row in inventory.to_dict("records"):
        document_rows.append(
            {
                "document_type": str(row.get("document_type", "")),
                "coverage_status": str(row.get("coverage_status", "unavailable")),
                "document_date": row.get("document_date") or "unavailable",
                "source": row.get("source_url") or row.get("authority") or "unavailable",
                "checksum": row.get("checksum") or row.get("sha256") or "unavailable",
                "source_id": row.get("source_id") or "unavailable",
            }
        )

    if holdings is None:
        try:
            holdings = pd.read_parquet(FUND_HOLDINGS_PATH) if FUND_HOLDINGS_PATH.exists() else pd.DataFrame()
        except Exception:
            holdings = pd.DataFrame()
    holdings_frame = holdings.copy() if isinstance(holdings, pd.DataFrame) else pd.DataFrame()
    holdings_manual_review = False
    holdings_message = ""
    if not holdings_frame.empty:
        id_column = "instrument_id" if "instrument_id" in holdings_frame.columns else "etf_id" if "etf_id" in holdings_frame.columns else None
        if id_column:
            holdings_frame = holdings_frame[holdings_frame[id_column].astype(str).eq(str(instrument_id))]
        else:
            holdings_manual_review = True
            holdings_message = "ETF holdings are missing a canonical instrument_id or etf_id column; manual review is required."
            holdings_frame = pd.DataFrame()
    if holdings_frame.empty:
        holdings_summary: dict[str, Any] = {
            "status": "manual_review" if holdings_manual_review else "unavailable",
            "message": holdings_message or "No normalised holdings are available.",
            "manual_review": holdings_manual_review,
            "rows": [],
        }
    else:
        sort_column = "as_of" if "as_of" in holdings_frame.columns else "as_of_date" if "as_of_date" in holdings_frame.columns else None
        if sort_column:
            holdings_frame = holdings_frame.sort_values(sort_column, kind="stable")
        row = holdings_frame.iloc[-1]
        holdings_summary = {
            "status": "available",
            "as_of": row.get("as_of") or row.get("as_of_date") or "unavailable",
            "completeness": row.get("completeness", "unavailable"),
            "freshness": row.get("freshness", "unavailable"),
            "confidence": row.get("confidence", "unavailable"),
            "source": row.get("source", "unavailable"),
            "authority": row.get("authority", "unavailable"),
            "score_eligible": row.get("score_eligible", False),
            "manual_review": False,
            "rows": holdings_frame.to_dict("records"),
        }
    try:
        kid_frame = kid_records.copy() if isinstance(kid_records, pd.DataFrame) else read_priips_kid_records()
    except Exception:
        kid_frame = pd.DataFrame()
    try:
        methodology_frame = methodology_records.copy() if isinstance(methodology_records, pd.DataFrame) else read_index_methodology_records()
    except Exception:
        methodology_frame = pd.DataFrame()
    kid = _parsed_kid_panel(kid_frame, instrument_id)
    methodology = _parsed_methodology_panel(methodology_frame, instrument_id)
    has_registered_document = any(row["coverage_status"] in {"available", "imported", "mapped"} for row in document_rows)
    return {
        "status": "manual_review" if registry_manual_review else "available" if has_registered_document or kid["status"] == "available" or methodology["status"] == "available" else "unavailable",
        "message": registry_message or "ETF disclosure evidence is shown from canonical instrument-linked local records.",
        "manual_review": registry_manual_review or holdings_manual_review,
        "document_inventory": document_rows,
        "holdings": holdings_summary,
        "exposure": {
            "status": holdings_summary.get("status", "unavailable"),
            "rows": holdings_summary.get("rows", []),
            "message": holdings_summary.get("message", "ETF holdings/exposure unavailable."),
        },
        "kid": kid,
        "methodology": methodology,
        "execution_allowed": False,
    }


def _parsed_kid_panel(frame: pd.DataFrame, instrument_id: str) -> dict[str, Any]:
    return _parsed_panel(frame, instrument_id, "kid", ("product", "isin", "manufacturer", "sri", "cost_fields", "holding_period_years", "scenarios", "document_date", "extraction_confidence"))


def _parsed_methodology_panel(frame: pd.DataFrame, instrument_id: str) -> dict[str, Any]:
    return _parsed_panel(frame, instrument_id, "methodology", ("provider", "index_series", "version", "document_date", "eligibility_rules", "weighting_rules", "review_frequency", "caps", "confidence"))


def _parsed_panel(frame: pd.DataFrame, instrument_id: str, kind: str, fields: tuple[str, ...]) -> dict[str, Any]:
    if frame.empty or "instrument_id" not in frame.columns:
        return {"status": "unavailable", "manual_review": True, "message": f"Parsed {kind} evidence unavailable; manual review required."}
    scoped = frame[frame["instrument_id"].astype(str).eq(str(instrument_id))]
    if scoped.empty:
        return {"status": "unavailable", "manual_review": True, "message": f"Parsed {kind} evidence unavailable; manual review required."}
    row = scoped.sort_values("imported_at", kind="stable").iloc[-1] if "imported_at" in scoped.columns else scoped.iloc[-1]
    payload: dict[str, Any] = {field: row.get(field) for field in fields}
    payload.update({field: row.get(field) for field in ("source_pages", "warnings") if field in row.index})
    for field in ("source_pages", "warnings", "cost_fields", "scenarios", "eligibility_rules", "weighting_rules", "caps"):
        value = payload.get(field)
        if isinstance(value, str):
            try:
                import json
                payload[field] = json.loads(value)
            except (TypeError, ValueError):
                payload[field] = [value] if field != "cost_fields" else {"raw": value}
    payload.update(
        {
            "status": "available" if bool(row.get("success")) and not bool(row.get("manual_review")) and str(row.get("freshness_status", "ok")) not in {"stale_block", "missing_or_pending", "unknown"} else "manual_review",
            "source_id": row.get("source_id", "unavailable"),
            "source_sha256": row.get("source_sha256", "unavailable"),
            "parser_version": row.get("parser_version", "unavailable"),
            "manual_review": bool(row.get("manual_review", True)),
            "score_eligible": bool(row.get("score_eligible", False)),
            "source_authority": row.get("source_authority", "issuer_document"),
            "freshness_status": row.get("freshness_status", "unknown"),
        }
    )
    return payload


def build_etf_disclosure_panel(model: InstrumentDetailViewModel) -> dict[str, Any]:
    """Return the reusable ETF disclosure model shown on Instrument Detail."""
    value = model.sections.get("etf_disclosures")
    return value if isinstance(value, dict) else {"status": "unavailable", "document_inventory": [], "holdings": {"status": "unavailable"}, "kid": {"status": "unavailable"}, "methodology": {"status": "unavailable"}}


def _friction_panel(instrument_id: str) -> dict[str, Any]:
    fields = ("gross_expected_edge_bps", "estimated_total_cost_bps", "net_expected_edge_bps", "edge_to_cost_ratio")
    empty = {field: None for field in fields}
    empty.update({"cost_stress_scenario": "unavailable", "status": "unavailable", "execution_allowed": False})
    if not SCOREBOARD_PATH.exists():
        return empty
    try:
        frame = pd.read_parquet(SCOREBOARD_PATH)
    except Exception:
        return empty
    id_column = next((column for column in ("display_id", "instrument_id", "etf_id") if column in frame.columns), None)
    if id_column is None:
        return empty
    rows = frame[frame[id_column].astype(str).eq(str(instrument_id))]
    if rows.empty:
        return empty
    row = rows.iloc[-1]
    def _finite(value: object) -> float | None:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    result = {field: _finite(row.get(field)) if field in row.index else None for field in fields}
    scenario = row.get("cost_stress_scenario")
    try:
        scenario_is_non_finite = isinstance(scenario, (int, float)) and not math.isfinite(float(scenario))
    except (TypeError, ValueError):
        scenario_is_non_finite = False
    if scenario_is_non_finite or pd.isna(scenario):
        scenario_text = "unavailable"
    else:
        scenario_text = str(scenario).strip() or "unavailable"
    result.update(
        {
            "cost_stress_scenario": scenario_text,
            "status": "available" if any(result[field] is not None for field in fields) else "unavailable",
            "execution_allowed": False,
        }
    )
    return result


def _price_panel(snapshot: CockpitSnapshot, instrument_id: str) -> dict[str, Any]:
    rows = _instrument_rows(getattr(snapshot, "prices", None), instrument_id)
    if rows.empty:
        return _unavailable("Price history unavailable for this instrument.") | {"rows": [], "history": []}
    date_column = "date" if "date" in rows.columns else "as_of_date" if "as_of_date" in rows.columns else None
    if date_column is not None:
        rows["_date_sort"] = pd.to_datetime(rows[date_column], errors="coerce")
        rows = rows.sort_values("_date_sort", kind="stable").drop(columns=["_date_sort"])
    latest = rows.iloc[-1]
    price = latest.get("adjusted_close")
    if _safe_float(price) is None:
        price = latest.get("close")
    latest_date = latest.get(date_column) if date_column else None
    latest_text = "unavailable" if latest_date is None or pd.isna(latest_date) else str(latest_date)
    freshness = "unknown"
    if latest_text != "unavailable":
        freshness = "fresh"
        try:
            reference = pd.to_datetime(getattr(getattr(snapshot, "data_report", None), "as_of_date", None), errors="coerce")
            observed = pd.to_datetime(latest_date, errors="coerce")
            if pd.notna(reference) and pd.notna(observed) and (reference - observed).days > 5:
                freshness = "stale"
        except Exception:
            freshness = "unknown"
    records = rows.tail(500).where(pd.notna(rows.tail(500)), None).to_dict("records")
    return {
        "status": "available",
        "rows": len(rows),
        "history": records,
        "latest_price": _safe_float(price),
        "latest_date": latest_text,
        "as_of": latest_text,
        "freshness": freshness,
        "source": latest.get("source", "unavailable"),
        "currency": latest.get("currency", "unavailable"),
        "execution_allowed": False,
    }


def _scoreboard_row(instrument_id: str) -> dict[str, Any]:
    frame = _load_parquet(SCOREBOARD_PATH)
    rows = _instrument_rows(frame, instrument_id, columns=("instrument_id", "display_id", "etf_id"))
    return rows.iloc[-1].to_dict() if not rows.empty else {}


def _score_panel(signal: Any, scoreboard: Mapping[str, Any], derived: Mapping[str, Any], friction: Mapping[str, Any]) -> dict[str, Any]:
    if signal is None and not scoreboard:
        return _unavailable("Score evidence unavailable for this instrument.") | {"crowding": derived["crowding"], "friction": friction}
    gates: list[str] = [str(value) for value in (getattr(signal, "blocked_by", ()) or ())]
    decision = getattr(signal, "authority_decision", None)
    for gate in getattr(decision, "gates", ()) or ():
        if not bool(getattr(gate, "passed", True)) and str(getattr(gate, "gate_id", "")) not in gates:
            gates.append(str(getattr(gate, "gate_id", "")))
    evidence_score = next((_safe_float(scoreboard.get(key)) for key in ("evidence_score_10", "evidence_score", "final_combined_score_10") if _safe_float(scoreboard.get(key)) is not None), None)
    quality = next((_safe_float(scoreboard.get(key)) for key in ("evidence_quality_10", "evidence_quality") if _safe_float(scoreboard.get(key)) is not None), None)
    label = str(scoreboard.get("final_label") or scoreboard.get("final_action") or getattr(signal, "research_state", "manual_review"))
    reason = str(scoreboard.get("one_line_reason") or scoreboard.get("reason") or getattr(signal, "reason_long", "Score reason unavailable."))
    return {
        "status": "available",
        "evidence_score": evidence_score,
        "evidence_quality": quality,
        "signal_score": _safe_float(getattr(signal, "total_score", None)),
        "final_label": label,
        "final_reason": reason,
        "reason": reason,
        "blocked_gates": gates,
        "warnings": list(getattr(signal, "warnings", ()) or ()),
        "freshness": scoreboard.get("freshness_status", "unavailable"),
        "crowding": derived["crowding"],
        "friction": friction,
        "execution_allowed": False,
    }


def _risk_panel(features: object, friction: Mapping[str, Any], crowding: Mapping[str, Any]) -> dict[str, Any]:
    rows = _safe_frame(features)
    if rows.empty:
        return _unavailable("Risk and feature evidence unavailable for this instrument.") | {"crowding": crowding, "cost": friction}
    row = rows.iloc[-1]
    values = {str(key): _safe_float(row.get(key)) for key in row.index}
    momentum = {key: values.get(key) for key in ("momentum_20d", "momentum_60d", "momentum_120d", "momentum_180d")}
    trend = {key: values.get(key) for key in ("trend_100", "trend_200", "trend_slope")}
    relative = {key: values.get(key) for key in ("relative_strength_60d", "relative_strength_120d")}
    volatility = {key: values.get(key) for key in ("vol_20d_ann", "vol_60d_ann", "vol_120d_ann", "ewma_vol_ann")}
    drawdown = {key: values.get(key) for key in ("drawdown_current", "drawdown_60d_max", "drawdown_120d_max")}
    liquidity = {"liquidity_score": values.get("liquidity_score")}
    return {
        "status": "available",
        "as_of": str(row.get("date", "unavailable")),
        "momentum": momentum,
        "momentum_60d": momentum["momentum_60d"],
        "trend": trend,
        "trend_200": trend["trend_200"],
        "relative_strength": relative,
        "relative_strength_60d": relative["relative_strength_60d"],
        "volatility": volatility,
        "drawdown": drawdown,
        "liquidity": liquidity,
        "cost": friction,
        "crowding": crowding,
        "execution_allowed": False,
    }


def _attribution_panel(derived: Mapping[str, Any], scoreboard: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(derived.get("attribution", {}))
    aliases = {
        "alpha": ("alpha", "alpha_proxy"),
        "beta": ("beta", "benchmark_beta"),
        "correlation": ("correlation", "benchmark_correlation"),
    }
    for target, names in aliases.items():
        value[target] = next(
            (
                _safe_float(scoreboard.get(name))
                for name in names
                if _safe_float(scoreboard.get(name)) is not None
            ),
            next((_safe_float(value.get(name)) for name in names if _safe_float(value.get(name)) is not None), None),
        )
    value.setdefault("status", "available" if any(value.get(key) is not None for key in ("alpha", "beta", "correlation")) else "unavailable")
    value["execution_allowed"] = False
    return value


def _forecast_panel(snapshot: CockpitSnapshot, instrument_id: str) -> dict[str, Any]:
    rows = _instrument_rows(getattr(snapshot, "forecasts", None), instrument_id)
    if rows.empty:
        return _unavailable("Forecast evidence unavailable; no valid local forecast rows are registered.") | {"rows": []}
    return {"status": "available", "rows": rows.where(pd.notna(rows), None).to_dict("records"), "execution_allowed": False}


def _backtest_panel(snapshot: CockpitSnapshot, instrument_id: str, scoreboard: Mapping[str, Any]) -> dict[str, Any]:
    report = getattr(snapshot, "backtest", None)
    signal_log = _instrument_rows(getattr(report, "signal_log", None), instrument_id)
    trade_log = _instrument_rows(getattr(report, "trade_log", None), instrument_id)
    quality = scoreboard.get("backtest_trust_label") or scoreboard.get("backtest_validity")
    if signal_log.empty and trade_log.empty and quality is None:
        return _unavailable("Backtest trust unavailable for this instrument.") | {"signal_rows": [], "trade_rows": []}
    return {"status": "available", "trust": quality or "available", "signal_rows": signal_log.to_dict("records"), "trade_rows": trade_log.to_dict("records"), "execution_allowed": False}


def _paper_trade_panel(instrument_id: str, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    source = frame if isinstance(frame, pd.DataFrame) else _load_parquet(PAPER_TRADES_PATH)
    rows = _instrument_rows(source, instrument_id)
    if rows.empty:
        return _unavailable("Paper-trade history unavailable; no local paper-trade records are registered.") | {"rows": []}
    return {"status": "available", "rows": rows.to_dict("records"), "execution_allowed": False}


def _history_panel(instrument_id: str, history: pd.DataFrame | None = None) -> dict[str, Any]:
    try:
        source = history if isinstance(history, pd.DataFrame) else score_history_frame()
    except Exception:
        source = pd.DataFrame()
    rows = _instrument_rows(source, instrument_id)
    if rows.empty:
        return _unavailable("Score history unavailable; a second local score run is required.") | {"rows": []}
    return {"status": "available", "rows": rows.to_dict("records"), "execution_allowed": False}


def _run_changes_panel(instrument_id: str, history: pd.DataFrame | None = None) -> dict[str, Any]:
    try:
        source = history if isinstance(history, pd.DataFrame) else score_history_frame()
        if not isinstance(source, pd.DataFrame) or source.empty or "run_id" not in source.columns:
            raise ValueError("no score history")
        runs = list(dict.fromkeys(source["run_id"].astype(str).tolist()))
        current = runs[-1]
        previous = runs[-2] if len(runs) > 1 else None
        report = compare_runs(source, current, previous)
        changes = [change.__dict__ for change in report.changes if change.instrument_id == instrument_id]
        return {"status": "available", "current_run_id": current, "previous_run_id": previous, "changes": changes, "execution_allowed": False}
    except Exception:
        return _unavailable("What changed since the last run is unavailable until comparable score history exists.") | {"changes": []}


def _journal_panel(instrument_id: str, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    rows = _instrument_rows(frame, instrument_id) if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if rows.empty:
        return _unavailable("Decision journal entries unavailable for this instrument.") | {"entries": []}
    return {"status": "available", "entries": rows.to_dict("records"), "execution_allowed": False}


def build_instrument_detail(
    snapshot: CockpitSnapshot,
    instrument_id: str,
    *,
    document_registry: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
    kid_records: pd.DataFrame | None = None,
    methodology_records: pd.DataFrame | None = None,
    fundamentals: pd.DataFrame | None = None,
    news: pd.DataFrame | None = None,
    score_history: pd.DataFrame | None = None,
    paper_trades: pd.DataFrame | None = None,
    journal: pd.DataFrame | None = None,
) -> InstrumentDetailViewModel:
    identity = next((item for item in snapshot.config.universe.etfs if item.id == instrument_id), None)
    if identity is None:
        return InstrumentDetailViewModel(instrument_id, instrument_id, "unavailable", {"instrument_id": instrument_id}, {name: "unavailable" for name in _SECTION_NAMES})
    signal = next((item for item in getattr(snapshot, "signals", ()) if item.etf_id == instrument_id), None)
    features = _instrument_rows(getattr(snapshot, "latest_features", None), instrument_id)
    if features.empty:
        all_features = _instrument_rows(getattr(snapshot, "features", None), instrument_id)
        if not all_features.empty and "date" in all_features.columns:
            features = all_features.sort_values("date", kind="stable").tail(1)
    derived = _derived_evidence_panel(instrument_id)
    friction = _friction_panel(instrument_id)
    scoreboard = _scoreboard_row(instrument_id)
    group = str(getattr(identity, "source_group", "") or ("Sparebanken" if str(identity.instrument_type).casefold() in {"equity_certificate", "certificate"} else identity.analysis_tier or "unavailable"))
    identity_panel = {
        "status": "available",
        "instrument_id": instrument_id,
        "name": identity.name,
        "ticker": identity.ticker,
        "isin": identity.isin or "needs_verification",
        "asset_type": identity.instrument_type or identity.asset_class,
        "asset_class": identity.asset_class,
        "group": group,
        "exchange": identity.exchange or "unavailable",
        "currency": identity.currency or "unavailable",
        "region": identity.region or "unavailable",
        "sector": identity.sector or "unavailable",
        "theme": identity.theme or "unavailable",
        "source_id": f"config:universe:{instrument_id}",
        "execution_allowed": False,
    }
    disclosure = _etf_disclosure_panel(instrument_id, document_registry=document_registry, holdings=holdings, kid_records=kid_records, methodology_records=methodology_records)
    return InstrumentDetailViewModel(
        instrument_id,
        identity.name,
        "ready",
        identity_panel,
        {
            "identity": identity_panel,
            "price": _price_panel(snapshot, instrument_id),
            "scores": _score_panel(signal, scoreboard, derived, friction),
            "feature_drivers": _feature_driver_panel(instrument_id),
            "risk": _risk_panel(features, friction, derived["crowding"]),
            "attribution": _attribution_panel(derived, scoreboard),
            "fundamentals": _fundamentals_panel(instrument_id, fundamentals),
            "etf_disclosures": disclosure,
            "etf_holdings": disclosure.get("exposure", _unavailable("ETF holdings/exposure unavailable.")),
            "news": _news_panel(instrument_id, news),
            "forecasts": _forecast_panel(snapshot, instrument_id),
            "backtests": _backtest_panel(snapshot, instrument_id, scoreboard),
            "paper_trades": _paper_trade_panel(instrument_id, paper_trades),
            "history": _history_panel(instrument_id, score_history),
            "journal": _journal_panel(instrument_id, journal),
            "run_changes": _run_changes_panel(instrument_id, score_history),
        },
    )


def _derived_evidence_panel(instrument_id: str) -> dict[str, dict[str, Any]]:
    """Load persisted crowding/attribution evidence without recalculating UI authority."""

    crowding: dict[str, Any] = {"status": "unavailable", "message": "Correlation cluster evidence is unavailable.", "execution_allowed": False}
    attribution: dict[str, Any] = {"status": "unavailable", "message": "Benchmark attribution evidence is unavailable.", "sector_attribution_status": "N/A", "execution_allowed": False}
    try:
        if CORRELATION_CLUSTERS_PATH.exists():
            frame = pd.read_parquet(CORRELATION_CLUSTERS_PATH)
            if "instrument_id" in frame.columns:
                rows = frame[frame["instrument_id"].astype(str).eq(str(instrument_id))]
                if not rows.empty:
                    crowding = {**rows.iloc[-1].to_dict(), "status": str(rows.iloc[-1].get("status", "available")), "execution_allowed": False}
    except Exception:
        pass
    try:
        if BENCHMARK_ATTRIBUTION_PATH.exists():
            frame = pd.read_parquet(BENCHMARK_ATTRIBUTION_PATH)
            if "instrument_id" in frame.columns:
                rows = frame[frame["instrument_id"].astype(str).eq(str(instrument_id))]
                if not rows.empty:
                    attribution = {**rows.iloc[-1].to_dict(), "status": str(rows.iloc[-1].get("status", "available")), "execution_allowed": False}
    except Exception:
        pass
    return {"crowding": crowding, "attribution": attribution}
