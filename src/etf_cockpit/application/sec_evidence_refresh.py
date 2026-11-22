"""Weekly SEC evidence refresh (INT-06, INT-17, INT-18) and its point-in-time readers.

For each US stock the refresh reads companyfacts and submissions from SEC EDGAR and stores the
SEC-receipt earnings features and the Form 4 filings of the last 120 days (from their acceptance
time) in the bitemporal store. An 8-K with item 2.02 adds only the printed release time to the
earnings rows. For the target positions, the latest 10-K risk-factor and MD&A sections go to the
document chunk store (cache-first). A parsed 8-K and a stored Form 4 are never fetched again; a failed
8-K filed in the last 120 days is retried on the next run and its release time then becomes a new
earnings-row revision; an older 8-K is never fetched, so its earnings rows keep the release time unavailable. Without
edgartools no filing document is downloaded. Every provider or target error becomes a reason in the
returned dict; the script holds the top-level guard, so the weekly job exit code is unchanged. Prices are passed empty: the stored prices carry no per-bar ``known_at``, so the filing
reaction stays unavailable and is not stored. Eight workers fetch and parse targets at once under the
provider's one shared rate limit; the main thread alone reads and writes the ledger, in target order,
so the stored rows and the report are those of a serial run.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
import dataclasses
from datetime import date, datetime, timedelta, timezone
from importlib.util import find_spec
import json
import os
from pathlib import Path
import re
import threading
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
from etf_cockpit.data.sec_filing_documents import _edgar as _documents_parser
from etf_cockpit.data.sec_ownership import (
    InsiderFiling,
    InsiderTransaction,
    ShadowFeature,
    _edgar as _ownership_parser,
    _unavailable,
    insider_purchase_features,
    parse_ownership_xml,
)
from etf_cockpit.data.sec_pit_facts import acceptance_index

INSIDER_DATASET = "sec_insider_filings"
EIGHT_K_DATASET = "sec_8k_releases"
_FORM4_DAYS = 120
_EIGHT_K_DAYS = 120  # only an item-2.02 8-K filed in this window is fetched
_MAX_BYTES = 50_000_000  # the same cap as the macro fetches
_PRICE_COLUMNS = ["instrument_id", "date", "adjusted_close", "known_at"]
_WORKERS = 8  # targets fetched at once; every SEC request still passes the provider's one shared limiter
_AHEAD = 16  # targets fetched ahead of the in-order recording: bounds memory while one target is slow


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


def sec_provider(root: Path | None = None, *, reuse_companyfacts: bool = False) -> SecEdgarProvider:
    """The weekly job's SEC provider; ValueError without a valid SEC User-Agent."""

    root = Path(root or ROOT)
    return SecEdgarProvider(src.sec_user_agent(sf.load_stock_config(root), os.environ) or "", cache_dir=root / "data" / "raw" / "sec_edgar",
                            transport=_sec_transport, rate_limit_seconds=0.13,  # under 8 requests/s with margin
                            reuse_companyfacts=reuse_companyfacts)


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
            provider = sec_provider(root)
        except ValueError:
            report["reasons"] = {t.instrument_id: "no valid SEC User-Agent configured (set ETF_COCKPIT_SEC_EDGAR_USER_AGENT)" for t in targets}
            return report
    snapshots = sf.read_snapshots(root)
    positions = set(getattr(getattr(config, "targets", None), "positions", None) or {})
    run_id = f"sec_evidence:{now.isoformat()}"
    with suppress(Exception):  # import the parsers once, here, so workers never import edgartools at once; a failure
        if find_spec("edgar") is not None:  # is then reported per filing by the workers, as before
            _documents_parser()
            _ownership_parser()
    cik_locks: dict[str, threading.Lock] = {}
    ahead: deque = deque()
    with BitemporalStore(root) as ledger, ThreadPoolExecutor(_WORKERS) as pool:

        def start(target: Any) -> None:  # main thread: the ledger is read here, never in a worker
            iid = target.instrument_id
            snap = sf.latest_snapshot(iid, snapshots, now) or {}
            known: tuple[set[str], dict[str, Any]] = (set(), {})
            try:
                known = _known_filings(ledger, iid)
                job = pool.submit(_fetch_target, provider, target, snap, iid in positions, known, now, cik_locks)
            except Exception as exc:
                job = Future()
                job.set_exception(exc)
            ahead.append((target, snap, known, job))

        def finish() -> None:  # main thread, in target order: every ledger write and progress message
            target, snap, known, job = ahead.popleft()
            try:
                reasons = _record_target(ledger, root, target.instrument_id, snap, job.result(), known[1], run_id, report, now)
            except Exception as exc:  # one target never stops the weekly job
                reasons = [f"unexpected: {_why(exc)}"]
            if reasons:
                report["reasons"][target.instrument_id] = "; ".join(reasons)
            if progress:
                progress(f"SEC evidence {target.instrument_id}: {report['reasons'].get(target.instrument_id, 'ok')}")

        for target in targets:
            start(target)
            if len(ahead) >= _AHEAD:
                finish()
        while ahead:
            finish()
    return report


@dataclasses.dataclass
class _Fetched:
    """One target's SEC documents, fetched and parsed in a worker; nothing here is stored yet."""

    facts_path: Path  # parsed in the main thread: a few large companyfacts never wait in memory
    submissions: dict[str, Any]
    reasons: list[str]
    form4: list[InsiderFiling | str] = dataclasses.field(default_factory=list)  # filing order: a filing or its reason
    eight_ks: list[tuple[str, EightKFiling | Exception]] = dataclasses.field(default_factory=list)
    ten_k: tuple[str, list | Exception] | None = None


def _known_filings(ledger: BitemporalStore, iid: str) -> tuple[set[str], dict[str, Any]]:
    """The stored Form 4 accessions and parsed 8-Ks of one target."""

    return ({item.stable_id for item in ledger.observations(INSIDER_DATASET, entity_id=iid)},
            {item.stable_id: item.value for item in ledger.observations(EIGHT_K_DATASET, entity_id=iid)})


def _fetch_target(
    provider: SecEdgarProvider, target: Any, snap: dict[str, Any], in_positions: bool,
    known: tuple[set[str], dict[str, Any]], now: datetime, cik_locks: dict[str, threading.Lock],
) -> _Fetched | list[str]:
    """Worker: every SEC request and parse of one target, without the ledger; a list is the target's only reasons."""

    if str(snap.get("country") or "").strip().upper() not in _US:
        return ["non_us_issuer"]
    cik = target.cik or snap.get("cik")
    if not cik:
        return ["no SEC CIK resolved"]
    with cik_locks.setdefault(str(cik).lstrip("0"), threading.Lock()):  # share classes never fetch one CIK at once
        try:
            facts_path = provider.fetch_companyfacts(cik).path
            submissions = json.loads(provider.fetch_submissions(cik).path.read_bytes())
        except Exception as exc:
            return [f"SEC companyfacts/submissions unavailable: {_why(exc)}"]
        acceptances = acceptance_index(submissions)
        filings = _filing_rows(submissions)
        if find_spec("edgar") is None:  # the document fetches have no use without it: never download them
            return _Fetched(facts_path, submissions, ["SEC filing documents skipped: edgartools is not installed (optional `sec` extra)"])
        fetched = _Fetched(facts_path, submissions, [], _fetch_form4(provider, cik, filings, acceptances, known[0], now))
        since = (now - timedelta(days=_EIGHT_K_DAYS)).date().isoformat()
        for row in filings:
            accession = row["accession"]
            if row["form"] != "8-K" or "2.02" not in row["items"].split(",") or accession in known[1] or row["filingDate"] < since:
                continue
            if not (acceptances.get(accession) or {}).get("accepted"):
                continue
            try:
                fetched.eight_ks.append((accession, fetch_8k(provider, cik, accession, tables=False)))  # the ledger keeps no tables
            except Exception as exc:  # retried on the next run: only a parsed 8-K is stored
                fetched.eight_ks.append((accession, exc))
        ten_ks = [row for row in filings if row["form"] == "10-K"]
        latest = max(ten_ks, key=lambda row: row["filingDate"])["accession"] if ten_ks else None
        if in_positions and latest:
            try:
                fetched.ten_k = (latest, fetch_10k_section_chunks(provider, cik, latest))
            except Exception as exc:
                fetched.ten_k = (latest, exc)
        return fetched


def _record_target(
    ledger: BitemporalStore, root: Path, iid: str, snap: dict[str, Any], fetched: _Fetched | list[str],
    parsed: dict[str, Any], run_id: str, report: dict[str, Any], now: datetime,
) -> list[str]:
    """Main thread: store one fetched target in the serial order; returns its reasons."""

    if isinstance(fetched, list):
        return fetched
    try:
        facts = json.loads(fetched.facts_path.read_bytes())
    except Exception as exc:
        return [f"SEC companyfacts/submissions unavailable: {_why(exc)}"]
    reasons = list(fetched.reasons)
    for item in fetched.form4:
        if isinstance(item, str):
            reasons.append(item)
            continue
        record_insider_filing(ledger, iid, item, run_id=run_id)
        report["insider_rows"] += 1
    for accession, item in fetched.eight_ks:
        try:
            if isinstance(item, Exception):
                raise item
            parsed[accession] = _record_8k(ledger, iid, accession, item, run_id)
        except Exception as exc:  # retried on the next run: only a parsed 8-K is stored
            reasons.append(f"8-K {accession}: {_why(exc)}")
    eight_ks = [_eight_k(value) for value in parsed.values()]
    empty = pd.DataFrame(columns=_PRICE_COLUMNS)
    result = compute_earnings_events(iid, facts, fetched.submissions, empty, empty, country=snap.get("country"), eight_ks=eight_ks)
    if result["status"] != "available":
        reasons.append(str(result["reason"]))
    before = len(ledger.observations(EARNINGS_DATASET, entity_id=iid))
    record_earnings_events(ledger, iid, result["events"], run_id=run_id, revised_at=now)
    report["earnings_rows"] += len(ledger.observations(EARNINGS_DATASET, entity_id=iid)) - before
    if fetched.ten_k is not None:
        latest, chunks = fetched.ten_k
        try:
            if isinstance(chunks, Exception):
                raise chunks
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


def _fetch_form4(
    provider: SecEdgarProvider, cik: str, filings: list[dict[str, str]], acceptances: dict, stored: set[str], now: datetime,
) -> list[InsiderFiling | str]:
    """Fetch and parse each Form 4 filed in the last 120 days that is not stored yet; a str is why one is missing."""

    out: list[InsiderFiling | str] = []
    since = (now - timedelta(days=_FORM4_DAYS)).date().isoformat()
    for row in filings:
        accession = row["accession"]
        if row["form"] not in ("4", "4/A") or accession in stored or row["filingDate"] < since:
            continue
        accepted = (acceptances.get(accession) or {}).get("accepted")
        if not accepted:
            out.append(f"Form 4 {accession}: no acceptance time")
            continue
        name = re.sub(r"^xslF345X\d\d/", "", row["primaryDocument"])
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{name}"
        try:
            xml = provider.fetch_filing_document(url).path.read_bytes()
            out.append(parse_ownership_xml(xml, accession=accession, known_at=datetime.fromisoformat(accepted)))
        except Exception as exc:
            out.append(f"Form 4 {accession}: {_why(exc)}")
    return out


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
