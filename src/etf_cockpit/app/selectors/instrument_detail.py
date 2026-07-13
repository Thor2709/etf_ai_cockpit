from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from etf_cockpit.data.fund_documents import build_document_inventory, read_document_registry
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
from etf_cockpit.data.parsed_disclosures import read_index_methodology_records, read_priips_kid_records
from etf_cockpit.services import CockpitSnapshot


@dataclass(frozen=True)
class InstrumentDetailViewModel:
    instrument_id: str
    display_name: str
    status: str
    identity: dict[str, Any]
    sections: dict[str, Any]


_SECTION_NAMES = ("identity", "price", "scores", "risk", "attribution", "fundamentals", "etf_disclosures", "news", "forecasts", "backtests", "history", "journal", "run_changes")


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


def build_instrument_detail(
    snapshot: CockpitSnapshot,
    instrument_id: str,
    *,
    document_registry: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
    kid_records: pd.DataFrame | None = None,
    methodology_records: pd.DataFrame | None = None,
) -> InstrumentDetailViewModel:
    identity = next((item for item in snapshot.config.universe.etfs if item.id == instrument_id), None)
    if identity is None:
        return InstrumentDetailViewModel(instrument_id, instrument_id, "unavailable", {"instrument_id": instrument_id}, {name: "unavailable" for name in _SECTION_NAMES})
    signal = next((item for item in snapshot.signals if item.etf_id == instrument_id), None)
    price_rows = snapshot.prices[snapshot.prices.get("etf_id", "") == instrument_id] if not snapshot.prices.empty and "etf_id" in snapshot.prices.columns else snapshot.prices.iloc[0:0]
    return InstrumentDetailViewModel(
        instrument_id,
        identity.name,
        "ready",
        {"name": identity.name, "ticker": identity.ticker, "isin": identity.isin or "needs_verification", "asset_type": identity.asset_class, "exchange": identity.exchange},
        {
            "identity": "ready",
            "price": {"rows": len(price_rows), "as_of": str(price_rows["date"].max()) if not price_rows.empty and "date" in price_rows.columns else "unavailable"},
            "scores": "ready" if signal is not None else "unavailable",
            "risk": "ready" if signal is not None else "unavailable",
            "attribution": "available from evidence ledger where present",
            "fundamentals": "unavailable unless sourced",
            "etf_disclosures": _etf_disclosure_panel(instrument_id, document_registry=document_registry, holdings=holdings, kid_records=kid_records, methodology_records=methodology_records),
            "news": "unavailable unless timestamp-validated",
            "forecasts": "available from valid forecast rows",
            "backtests": "available from local backtest report",
            "history": "available from local score history",
            "journal": "unavailable until a local note exists",
            "run_changes": "available from local run history",
        },
    )
