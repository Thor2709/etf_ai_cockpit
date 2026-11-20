"""Weekly SEC evidence refresh (INT-06, INT-17, INT-18) and its point-in-time readers.

For each US stock the refresh reads companyfacts and submissions from SEC EDGAR and stores the
SEC-receipt earnings features and the Form 4 filings of the last 120 days (from their acceptance
time) in the bitemporal store. An 8-K with item 2.02 adds only the printed release time to the
earnings rows. For the target positions, the latest 10-K risk-factor and MD&A sections go to the
document chunk store (cache-first). A parsed 8-K and a stored Form 4 are never fetched again; a failed
8-K is retried on the next run and its release time then becomes a new earnings-row revision. Without
edgartools no filing document is downloaded. Every provider or target error becomes a reason in the
returned dict; the script holds the top-level guard, so the weekly job exit code is unchanged. Prices are passed empty: the stored prices carry no per-bar ``known_at``, so the filing
reaction stays unavailable and is not stored.
"""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
from datetime import date, datetime, timedelta, timezone
from importlib.util import find_spec
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError

import pandas as pd

from etf_cockpit.application.stock_service import universe_rows
from etf_cockpit.core.http_fetch import get_checked, same_host_https
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data import stock_fundamentals as sf
from etf_cockpit.data import stock_sources as src
from etf_cockpit.data.bitemporal import BitemporalStore
from etf_cockpit.data.document_chunks import CHUNK_STORE_NAME, index_document
from etf_cockpit.data.earnings_surprise import _US, DATASET_ID as EARNINGS_DATASET
from etf_cockpit.data.earnings_surprise import compute_earnings_events, record_earnings_events
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.data.sec_filing_documents import EightKFiling, fetch_8k, fetch_10k_section_chunks
from etf_cockpit.data.sec_ownership import (
    InsiderFiling,
    InsiderTransaction,
    ShadowFeature,
    _unavailable,
    insider_purchase_features,
    parse_ownership_xml,
)
from etf_cockpit.data.sec_pit_facts import acceptance_index

INSIDER_DATASET = "sec_insider_filings"
EIGHT_K_DATASET = "sec_8k_releases"
_FORM4_DAYS = 120
_MAX_BYTES = 50_000_000  # the same cap as the macro fetches
_PRICE_COLUMNS = ["instrument_id", "date", "adjusted_close", "known_at"]


def _sec_transport(url: str, headers: dict[str, str]) -> tuple[bytes, int, Any]:
    """One bounded same-host HTTPS GET for the SEC provider; 304 is a response, not an error."""

    try:
        payload, status, response_headers = get_checked(
            url, allowed=same_host_https(url), headers=headers, timeout=20.0, max_bytes=_MAX_BYTES
        )
    except HTTPError as exc:
        if exc.code == 304:
            return b"", 304, exc.headers
        raise
    if len(payload) > _MAX_BYTES:
        raise ValueError("response too large")
    return payload, status, response_headers


def _why(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:160]


def refresh_sec_evidence(
    config: Any,
    *,
    root: Path | None = None,
    only_ids: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
    provider: SecEdgarProvider | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Store new SEC evidence for every US stock target; returns counts and a reason per target with a gap."""

    root = Path(root or ROOT)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cfg = sf.load_stock_config(root)
    targets = sf.targets_from_universe(universe_rows(config), excluded_sectors=(cfg.get("scope", {}) or {}).get("excluded_sectors", []))
    if only_ids:
        targets = [t for t in targets if t.instrument_id in only_ids]
    report: dict[str, Any] = {"earnings_rows": 0, "insider_rows": 0, "ten_k_chunks": 0, "reasons": {}}
    if provider is None:
        try:
            provider = SecEdgarProvider(src.sec_user_agent(cfg, os.environ) or "", cache_dir=root / "data" / "raw" / "sec_edgar",
                                        transport=_sec_transport, rate_limit_seconds=0.1)
        except ValueError:
            report["reasons"] = {t.instrument_id: "no valid SEC User-Agent configured (set ETF_COCKPIT_SEC_EDGAR_USER_AGENT)" for t in targets}
            return report
    snapshots = sf.read_snapshots(root)
    positions = set(getattr(getattr(config, "targets", None), "positions", None) or {})
    run_id = f"sec_evidence:{now.isoformat()}"
    with BitemporalStore(root) as ledger:
        for target in targets:
            snap = sf.latest_snapshot(target.instrument_id, snapshots, now) or {}
            try:
                reasons = _refresh_target(provider, ledger, root, target, snap, target.instrument_id in positions, run_id, report, now)
            except Exception as exc:  # one target never stops the weekly job
                reasons = [f"unexpected: {_why(exc)}"]
            if reasons:
                report["reasons"][target.instrument_id] = "; ".join(reasons)
            if progress:
                progress(f"SEC evidence {target.instrument_id}: {report['reasons'].get(target.instrument_id, 'ok')}")
    return report


def _refresh_target(
    provider: SecEdgarProvider, ledger: BitemporalStore, root: Path, target: Any, snap: dict[str, Any], in_positions: bool,
    run_id: str, report: dict[str, Any], now: datetime,
) -> list[str]:
    iid = target.instrument_id
    country = snap.get("country")
    if str(country or "").strip().upper() not in _US:
        return ["non_us_issuer"]
    cik = target.cik or snap.get("cik")
    if not cik:
        return ["no SEC CIK resolved"]
    try:
        facts = json.loads(provider.fetch_companyfacts(cik).path.read_bytes())
        submissions = json.loads(provider.fetch_submissions(cik).path.read_bytes())
    except Exception as exc:
        return [f"SEC companyfacts/submissions unavailable: {_why(exc)}"]
    acceptances = acceptance_index(submissions)
    filings = _filing_rows(submissions)
    parser = find_spec("edgar") is not None  # the document fetches have no use without it: never download them
    reasons = [] if parser else ["SEC filing documents skipped: edgartools is not installed (optional `sec` extra)"]
    if parser:
        reasons += _store_form4(provider, ledger, iid, cik, filings, acceptances, run_id, report, now)
    parsed = {item.stable_id: item.value for item in ledger.observations(EIGHT_K_DATASET, entity_id=iid)}
    for row in filings:
        accession = row["accession"]
        if not parser or row["form"] != "8-K" or "2.02" not in row["items"].split(",") or accession in parsed:
            continue
        if not (acceptances.get(accession) or {}).get("accepted"):
            continue
        try:
            parsed[accession] = _record_8k(ledger, iid, accession, fetch_8k(provider, cik, accession), run_id)
        except Exception as exc:  # retried on the next run: only a parsed 8-K is stored
            reasons.append(f"8-K {accession}: {_why(exc)}")
    eight_ks = [_eight_k(value) for value in parsed.values()]
    empty = pd.DataFrame(columns=_PRICE_COLUMNS)
    result = compute_earnings_events(iid, facts, submissions, empty, empty, country=country, eight_ks=eight_ks)
    if result["status"] != "available":
        reasons.append(str(result["reason"]))
    before = len(ledger.observations(EARNINGS_DATASET, entity_id=iid))
    record_earnings_events(ledger, iid, result["events"], run_id=run_id, revised_at=now)
    report["earnings_rows"] += len(ledger.observations(EARNINGS_DATASET, entity_id=iid)) - before
    ten_ks = [row for row in filings if row["form"] == "10-K"]
    latest = max(ten_ks, key=lambda row: row["filingDate"])["accession"] if ten_ks else None
    if parser and in_positions and latest:
        try:
            chunks = fetch_10k_section_chunks(provider, cik, latest)
            report["ten_k_chunks"] += index_document(root / "data" / CHUNK_STORE_NAME, chunks)
        except Exception as exc:
            reasons.append(f"10-K {latest}: {_why(exc)}")
    return reasons


def _record_8k(ledger: BitemporalStore, instrument_id: str, accession: str, filing: EightKFiling, run_id: str) -> dict[str, Any]:
    """Store one parsed 8-K under its submissions accession (tables are not kept), available from its SEC receipt."""

    value = json.loads(json.dumps(dataclasses.asdict(dataclasses.replace(filing, tables=())), default=lambda item: item.isoformat()))
    ledger.record_observation(
        dataset_id=EIGHT_K_DATASET, entity_id=instrument_id, stable_id=accession, value=value,
        source_id="sec_8k", source_checksum=filing.source_sha256, revision=1, valid_from=filing.sec_receipt_time,
        published_at=filing.sec_receipt_time, observed_at=filing.sec_receipt_time, available_at=filing.sec_receipt_time,
        run_id=run_id, availability_confidence="exact",
    )
    return value


def _eight_k(value: dict[str, Any]) -> EightKFiling:
    return EightKFiling(**{**value, "sec_receipt_time": datetime.fromisoformat(value["sec_receipt_time"]), "items": tuple(value["items"]), "tables": ()})


def _filing_rows(submissions: dict[str, Any]) -> list[dict[str, str]]:
    """The recent submissions table as rows; a missing optional column reads as empty text."""

    table = submissions.get("filings", {}).get("recent", {})
    accessions = table.get("accessionNumber", [])
    columns = {name: table.get(name) or [""] * len(accessions) for name in ("form", "filingDate", "items", "primaryDocument")}
    return [{"accession": accession, **{name: str(values[i] or "") for name, values in columns.items()}} for i, accession in enumerate(accessions)]


def _store_form4(
    provider: SecEdgarProvider, ledger: BitemporalStore, iid: str, cik: str, filings: list[dict[str, str]],
    acceptances: dict, run_id: str, report: dict[str, Any], now: datetime,
) -> list[str]:
    """Fetch, parse and store each Form 4 filed in the last 120 days that is not stored yet."""

    reasons: list[str] = []
    stored = {item.stable_id for item in ledger.observations(INSIDER_DATASET, entity_id=iid)}
    since = (now - timedelta(days=_FORM4_DAYS)).date().isoformat()
    for row in filings:
        accession = row["accession"]
        if row["form"] not in ("4", "4/A") or accession in stored or row["filingDate"] < since:
            continue
        accepted = (acceptances.get(accession) or {}).get("accepted")
        if not accepted:
            reasons.append(f"Form 4 {accession}: no acceptance time")
            continue
        name = re.sub(r"^xslF345X\d\d/", "", row["primaryDocument"])
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{name}"
        try:
            xml = provider.fetch_filing_document(url).path.read_bytes()
            filing = parse_ownership_xml(xml, accession=accession, known_at=datetime.fromisoformat(accepted))
        except Exception as exc:
            reasons.append(f"Form 4 {accession}: {_why(exc)}")
            continue
        record_insider_filing(ledger, iid, filing, run_id=run_id)
        report["insider_rows"] += 1
    return reasons


def record_insider_filing(ledger: BitemporalStore, instrument_id: str, filing: InsiderFiling, *, run_id: str) -> None:
    """Store one parsed Form 4, available from its SEC acceptance time."""

    value = json.loads(json.dumps(dataclasses.asdict(filing), default=lambda item: item.isoformat()))
    ledger.record_observation(
        dataset_id=INSIDER_DATASET, entity_id=instrument_id, stable_id=filing.accession, value=value,
        source_id="sec_form4", source_checksum=filing.source_sha256, revision=1, valid_from=filing.known_at,
        published_at=filing.known_at, observed_at=filing.known_at, available_at=filing.known_at, run_id=run_id,
        availability_confidence="exact",
    )


def _insider_filing(value: dict[str, Any]) -> InsiderFiling:
    transactions = tuple(
        InsiderTransaction(**{**row, "transaction_date": date.fromisoformat(row["transaction_date"]) if row["transaction_date"] else None})
        for row in value["transactions"]
    )
    return InsiderFiling(**{**value, "known_at": datetime.fromisoformat(value["known_at"]),
                            "insider_ciks": tuple(value["insider_ciks"]), "transactions": transactions})


def insider_features(root: Path | None, instrument_id: str, cik: str | None, decision_time: datetime) -> dict[str, ShadowFeature]:
    """Insider purchase features from the stored Form 4 filings known at ``decision_time``."""

    names = ("insider_net_open_market_shares", "insider_cluster_buyers")
    if not cik:
        return {name: _unavailable(name, "no SEC CIK for this stock") for name in names}
    try:
        with BitemporalStore(Path(root or ROOT)) as ledger:
            rows = ledger.observations(INSIDER_DATASET, entity_id=instrument_id, available_at_lte=decision_time)
        filings = [_insider_filing(row.value) for row in rows if row.status == "active"]
        return insider_purchase_features(filings, issuer_cik=cik, decision_time=decision_time)
    except Exception as exc:
        return {name: _unavailable(name, f"SEC insider evidence unavailable: {_why(exc)}") for name in names}


def sue_revenue_feature(root: Path | None, instrument_id: str, decision_time: datetime) -> tuple[float | None, str, str | None]:
    """(value, detail, reason) of the latest stored revenue SUE known at ``decision_time``."""

    try:
        with BitemporalStore(Path(root or ROOT)) as ledger:
            rows = ledger.observations(EARNINGS_DATASET, entity_id=instrument_id, available_at_lte=decision_time)
    except Exception as exc:
        return None, "—", f"SEC evidence store unavailable: {_why(exc)}"
    known = [row for row in rows if row.status == "active" and row.value.get("feature") == "sue_revenue"]
    if not known:
        return None, "—", "no revenue surprise known by the decision time (weekly SEC refresh, US stocks only)"
    row = max(known, key=lambda item: (item.valid_from, item.revision))  # the latest quarter, not the latest revision
    return float(row.value["value"]), f"SEC receipt {row.valid_from[:10]} · known {row.available_at[:10]} · SEC EDGAR", None
