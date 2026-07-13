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


_SECTION_NAMES = ("identity", "price", "scores", "feature_drivers", "risk", "attribution", "fundamentals", "etf_disclosures", "news", "forecasts", "backtests", "history", "journal", "run_changes")
SCOREBOARD_PATH = DERIVED_DIR / "scoreboard.parquet"


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
    source = frame if isinstance(frame, pd.DataFrame) else load_fundamental_evidence(FUNDAMENTAL_CLEAN_PATH)
    if source.empty or "instrument_id" not in source.columns:
        return {"status": "unavailable", "message": "Fundamental evidence unavailable; no complete local five-section record is registered.", "score_eligible": False}
    scoped = latest_fundamental_rows(source[source["instrument_id"].astype(str).eq(str(instrument_id))])
    if scoped.empty:
        return {"status": "unavailable", "message": "Fundamental evidence unavailable for this instrument.", "score_eligible": False}
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
    }


def _news_panel(instrument_id: str, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    source = frame if isinstance(frame, pd.DataFrame) else load_news_items(NEWS_CLEAN_PATH)
    if source.empty or "instrument_id" not in source.columns:
        return {"status": "unavailable", "message": "News unavailable; no timestamp-validated local items are registered.", "items": [], "context_only": True, "executable_authority": False}
    scoped = sort_news_items(source[source["instrument_id"].astype(str).eq(str(instrument_id))])
    if scoped.empty:
        return {"status": "unavailable", "message": "News unavailable for this instrument.", "items": [], "context_only": True, "executable_authority": False}
    items = [_news_item_record(row) for row in scoped.tail(20).to_dict("records")]
    return {"status": "available", "message": "News is context-only and cannot change deterministic scores.", "items": items, "context_only": True, "executable_authority": False}


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
    registry = document_registry.copy() if isinstance(document_registry, pd.DataFrame) else read_document_registry()
    if not registry.empty and "instrument_id" in registry.columns:
        registry = registry[registry["instrument_id"].astype(str).eq(str(instrument_id))].copy()
    if registry.empty:
        inventory = build_document_inventory([instrument_id])
    else:
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
    if not holdings_frame.empty:
        id_column = "instrument_id" if "instrument_id" in holdings_frame.columns else "etf_id" if "etf_id" in holdings_frame.columns else None
        if id_column:
            holdings_frame = holdings_frame[holdings_frame[id_column].astype(str).eq(str(instrument_id))]
    if holdings_frame.empty:
        holdings_summary: dict[str, Any] = {"status": "unavailable", "message": "No normalised holdings are available."}
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
        }
    kid_frame = kid_records.copy() if isinstance(kid_records, pd.DataFrame) else read_priips_kid_records()
    methodology_frame = methodology_records.copy() if isinstance(methodology_records, pd.DataFrame) else read_index_methodology_records()
    kid = _parsed_kid_panel(kid_frame, instrument_id)
    methodology = _parsed_methodology_panel(methodology_frame, instrument_id)
    has_registered_document = any(row["coverage_status"] in {"available", "imported", "mapped"} for row in document_rows)
    return {
        "status": "available" if has_registered_document or kid["status"] == "available" or methodology["status"] == "available" else "unavailable",
        "document_inventory": document_rows,
        "holdings": holdings_summary,
        "kid": kid,
        "methodology": methodology,
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
) -> InstrumentDetailViewModel:
    identity = next((item for item in snapshot.config.universe.etfs if item.id == instrument_id), None)
    if identity is None:
        return InstrumentDetailViewModel(instrument_id, instrument_id, "unavailable", {"instrument_id": instrument_id}, {name: "unavailable" for name in _SECTION_NAMES})
    signal = next((item for item in snapshot.signals if item.etf_id == instrument_id), None)
    price_rows = snapshot.prices[snapshot.prices.get("etf_id", "") == instrument_id] if not snapshot.prices.empty and "etf_id" in snapshot.prices.columns else snapshot.prices.iloc[0:0]
    derived = _derived_evidence_panel(instrument_id)
    friction = _friction_panel(instrument_id)
    return InstrumentDetailViewModel(
        instrument_id,
        identity.name,
        "ready",
        {"name": identity.name, "ticker": identity.ticker, "isin": identity.isin or "needs_verification", "asset_type": identity.asset_class, "exchange": identity.exchange},
        {
            "identity": "ready",
            "price": {"rows": len(price_rows), "as_of": str(price_rows["date"].max()) if not price_rows.empty and "date" in price_rows.columns else "unavailable"},
            "scores": {"status": "ready" if signal is not None else "unavailable", "crowding": derived["crowding"], "friction": friction, "execution_allowed": False},
            "feature_drivers": _feature_driver_panel(instrument_id),
            "risk": {"status": "ready" if signal is not None else "unavailable", "crowding": derived["crowding"], "friction": friction, "execution_allowed": False},
            "attribution": {**derived["attribution"], "execution_allowed": False},
            "fundamentals": _fundamentals_panel(instrument_id, fundamentals),
            "etf_disclosures": _etf_disclosure_panel(instrument_id, document_registry=document_registry, holdings=holdings, kid_records=kid_records, methodology_records=methodology_records),
            "news": _news_panel(instrument_id, news),
            "forecasts": "available from valid forecast rows",
            "backtests": "available from local backtest report",
            "history": "available from local score history",
            "journal": "unavailable until a local note exists",
            "run_changes": "available from local run history",
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
