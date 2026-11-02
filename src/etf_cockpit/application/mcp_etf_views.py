"""Application facades for MCP ETF holdings, structure and disclosure tools.

Open defaults: holdings pages contain 25 rows; look-through uses a 90-day
holdings age limit and 0.80 minimum aggregate coverage from the canonical view.
Manual holdings imports are known only from their local receipt time.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from etf_cockpit.application.etf_economics_view import build_etf_economics_panel
from etf_cockpit.application.market_views import load_etf_look_through, load_etf_structure_projection
from etf_cockpit.application.overlap import build_direct_overlap_view, direct_overlap_payload
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.fund_documents import import_etf_document, read_document_registry
from etf_cockpit.data.fund_holdings import holdings_splits
from etf_cockpit.data.holdings_registry import listing_evidence
from etf_cockpit.data.holdings_snapshots import gap_report, import_historical, load_snapshots
from etf_cockpit.data.parsed_disclosures import (
    EtfReportImportRequest,
    ReportSourceAuthority,
    import_etf_report,
    read_etf_report_records,
)


def etf_holdings_view(instrument_id: str, as_of: date, *, top_n: int = 25, include_gaps: bool = False) -> dict[str, object]:
    decision_time = datetime.combine(as_of, datetime.max.time(), tzinfo=timezone.utc)
    snapshots = load_snapshots(Path(ROOT), instrument_id, decision_time=decision_time)
    selected = [item for item in snapshots if item.get("as_of") == as_of.isoformat()]
    if not selected:
        return {"instrument_id": instrument_id, "status": "unavailable", "unavailable_reason": "No holdings snapshot is available for the requested date.", "holdings": [], "splits": None, "gaps": None}
    record = max(selected, key=lambda item: int(item.get("revision", 0)))
    rows = record.get("holdings")
    if not isinstance(rows, list):
        return {"instrument_id": instrument_id, "status": "unavailable", "unavailable_reason": "The retained holdings snapshot has no usable holdings rows.", "holdings": [], "splits": None, "gaps": None}
    frame = pd.DataFrame(rows)
    splits = holdings_splits(frame)
    holdings = sorted(
        rows,
        key=lambda item: (
            float(item["weight"])
            if isinstance(item.get("weight"), (int, float)) and not isinstance(item.get("weight"), bool)
            else float("-inf")
        ),
        reverse=True,
    )[:top_n]
    gaps: list[str] | None = None
    if include_gaps:
        listing = listing_evidence(Path(ROOT), instrument_id)
        start = min((date.fromisoformat(str(item["as_of"])) for item in snapshots), default=as_of)
        gaps = gap_report(Path(ROOT), instrument_id, start=start, end=as_of, listing=listing, decision_time=decision_time)
    return {"instrument_id": instrument_id, "status": "available", "as_of": as_of.isoformat(), "holdings": holdings, "splits": splits, "gaps": gaps, "snapshot_revision": record.get("revision")}


def etf_look_through_view(instrument_id: str, decision_time: datetime) -> dict[str, object]:
    return load_etf_look_through(instrument_id, decision_time=decision_time, analysis_date=decision_time.date(), require_canonical_identity=True)


def portfolio_look_through_view(snapshot: object, decision_time: datetime) -> dict[str, object]:
    from etf_cockpit.application.portfolio_views import load_portfolio_exposure_projection

    frame = getattr(snapshot, "holdings", None)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {"status": "unavailable", "reason_code": "portfolio_holdings_unavailable", "exposures": [], "execution_allowed": False}
    weights: dict[str, float] = {}
    for _, row in frame.iterrows():
        instrument = str(row.get("etf_id", row.get("instrument_id", ""))).strip()
        raw = row.get("current_weight")
        if not instrument or isinstance(raw, bool):
            continue
        try:
            weight = float(raw)
        except (TypeError, ValueError):
            continue
        if pd.notna(weight) and weight >= 0 and weight <= 1:
            weights[instrument] = weights.get(instrument, 0.0) + weight
    if not weights:
        return {"status": "unavailable", "reason_code": "portfolio_weights_unavailable", "exposures": [], "execution_allowed": False}
    return load_portfolio_exposure_projection(
        weights,
        decision_time=decision_time,
        analysis_date=decision_time.date(),
        root=Path(ROOT),
    )


def etf_overlap_view(snapshot: object, instrument_ids: list[str], *, weights: dict[str, float] | None = None, include_portfolio: bool = False) -> dict[str, object]:
    report = build_direct_overlap_view(
        snapshot,
        instrument_ids,
        target_weights=weights,
        focus_instrument_id=instrument_ids[0] if len(instrument_ids) == 1 else None,
    )
    payload = direct_overlap_payload(report)
    if not include_portfolio:
        payload.pop("concentrations", None)
    return payload


def etf_economics_view(snapshot: object, instrument_id: str, *, horizon_days: int = 252) -> dict[str, Any]:
    return build_etf_economics_panel(snapshot, instrument_id, horizon_days=horizon_days)


def etf_disclosures_view(instrument_id: str) -> dict[str, object]:
    documents = read_document_registry()
    reports = read_etf_report_records()
    docs = documents.loc[documents["instrument_id"].astype(str).eq(instrument_id)] if "instrument_id" in documents else documents.iloc[:0]
    rows = reports.loc[reports["instrument_id"].astype(str).eq(instrument_id)] if "instrument_id" in reports else reports.iloc[:0]
    return {
        "instrument_id": instrument_id,
        "documents": docs.head(100).to_dict("records"),
        "parsed_fields": rows.head(100).to_dict("records"),
        "conflicts": rows.loc[rows.get("verification_status", pd.Series(index=rows.index, dtype=object)).astype(str).eq("conflict")].head(100).to_dict("records"),
        "status": "available" if not docs.empty or not rows.empty else "unavailable",
        "unavailable_reason": None if not docs.empty or not rows.empty else "No disclosure records are available for this instrument.",
    }


def preview_disclosure_import(kind: str, path: Path, instrument_id: str, as_of: date, sha256: str | None) -> dict[str, object]:
    candidate = Path(path)
    if not candidate.is_file():
        raise ValueError("local disclosure path is not a file")
    import hashlib

    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if sha256 and digest.casefold() != sha256.casefold():
        raise ValueError("source checksum does not match sha256")
    if kind not in {"document", "holdings", "report"}:
        raise ValueError("kind must be document, holdings, or report")
    details: dict[str, object] = {"kind": kind, "path_name": candidate.name, "instrument_id": instrument_id, "as_of": as_of.isoformat(), "sha256": digest, "bytes": candidate.stat().st_size}
    if kind == "holdings":
        listing = listing_evidence(Path(ROOT), instrument_id)
        # Use the canonical parser as a no-write validation pass.
        from etf_cockpit.data.ishares_holdings import parse_ishares_csv

        parsed = parse_ishares_csv(candidate.read_bytes(), instrument_id=instrument_id, source_url=candidate.resolve().as_uri(), listing=listing)
        details.update({"rows": len(parsed["holdings"]), "as_of": parsed["as_of"], "known_at": parsed["known_at"]})
    return details


def commit_disclosure_import(kind: str, path: Path, instrument_id: str, as_of: date, sha256: str | None) -> dict[str, object]:
    preview = preview_disclosure_import(kind, path, instrument_id, as_of, sha256)
    candidate = Path(path)
    if kind == "document":
        result = import_etf_document(
            candidate,
            instrument_id=instrument_id,
            document_type="factsheet",
            authority="local_user_import",
            document_date=as_of,
            expected_sha256=str(preview["sha256"]),
        )
    elif kind == "holdings":
        listing = listing_evidence(Path(ROOT), instrument_id)
        result = import_historical(
            Path(ROOT), candidate, known_at=datetime.now(timezone.utc), licence_ref="local-user-import",
            instrument_id=instrument_id, source_url=candidate.resolve().as_uri(), fetched_at=datetime.now(timezone.utc),
            listing=listing,
        )
    else:
        request = EtfReportImportRequest(
            instrument_id=instrument_id,
            document_kind="annual_report",
            source_authority=ReportSourceAuthority.LOCAL_USER_IMPORT,
            source_path=candidate,
            expected_document_date=as_of,
            expected_sha256=str(preview["sha256"]),
        )
        result = import_etf_report(request)
    return {"kind": kind, "instrument_id": instrument_id, "result": result, "execution_allowed": False}


__all__ = [
    "commit_disclosure_import", "etf_disclosures_view", "etf_economics_view", "etf_holdings_view",
    "etf_look_through_view", "etf_overlap_view", "preview_disclosure_import",
]
