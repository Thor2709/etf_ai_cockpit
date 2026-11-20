"""Nightly S&P 500 constituents capture and index-coverage census (forward paper path, SDD C2/C3).

One capture per scope per UTC day. The page is fetched only through ``core.http_fetch.get_checked``;
bound members go to the membership ledger and every member gets one census row for [D, D+1).
Census rows are appended and never deleted. ``execution_allowed`` stays false.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file
from etf_cockpit.core.http_fetch import get_checked, same_host_https
from etf_cockpit.data.sec_cik_history import cik_text
from etf_cockpit.data.universe_membership import capture_log, load_raw_payload, record_listing_capture
from etf_cockpit.data.universe_store import load_universe

WIKI_CONSTITUENTS = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SCOPE = "listing:sp500:all"
SOURCE = "wikipedia:sp500_constituents"
COVERAGE_RELATIVE_PATH = Path("data/derived/universe_membership/index_coverage.parquet")
# Same columns and order as scripts/ingest_sp500.py COVERAGE_COLUMNS.
COVERAGE_COLUMNS = ["scope", "source_ticker", "instrument_id", "valid_from", "valid_to", "member_known_at",
                    "identity_known_at", "binding_status", "reason"]
MIN_ROWS, MAX_ROWS = 480, 520
MAX_BYTES = 8 * 1024**2
USER_AGENT = "etf-ai-cockpit-sp500-capture/1.0 (local research tool)"


class Sp500CaptureError(RuntimeError):
    """The page could not be fetched, parsed, guarded or captured."""


@dataclass(frozen=True)
class Sp500Capture:
    status: str  # "recorded" | "duplicate"
    snapshot_date: str
    known_at: str
    members: int
    bound: int
    unbound: int
    census_rows: int


def sec_ticker(ticker: str) -> str:
    """SEC and Yahoo write share-class separators with '-' where S&P data uses '.'."""
    return ticker.replace(".", "-")


def select_instrument_bindings(members: dict, records: list, ciks: dict, *, known_at: str, revision: str) -> tuple[list, list]:
    """Bind open-interval members to exactly one verified USD-quoted stock record with the exact ticker (any ISIN country)."""
    by_ticker = {}
    for item in records:
        if item.asset_type == "stock" and item.isin_status == "verified" and item.currency == "USD" and item.ticker:
            by_ticker.setdefault(item.ticker, []).append(item)
    bindings, rejected = [], []
    for ticker, info in sorted(members.items()):
        if not info["current"] or ticker not in ciks:
            continue
        matches = by_ticker.get(sec_ticker(ticker), [])
        if len(matches) == 1:
            record_ = matches[0]
            bindings.append({"ticker": ticker, "valid_from": info["open_from"], "valid_to": None,
                             "instrument_id": record_.instrument_id, "known_at": known_at,
                             "source": f"universe_store revision {revision}: {record_.instrument_id} ISIN {record_.isin} "
                                       "verified, USD quote, exact ticker (share-class '.'->'-' only)"})
        elif matches:
            rejected.append({"ticker": ticker, "reason": "ambiguous_universe_records"})
    return bindings, rejected


def constituents(text: str) -> list[dict]:
    table = text[text.find('id="constituents"'):]
    table = table[:table.find("</table>")]
    rows = []
    for row in re.findall(r"<tr.*?</tr>", table, re.S):
        rows.append([html_lib.unescape(re.sub(r"<[^>]+>", "", cell)).strip()
                     for cell in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)])
    if not rows or rows[0][:2] != ["Symbol", "Security"] or "CIK" not in rows[0]:
        raise ValueError("unexpected Wikipedia constituents header")
    index = rows[0].index("CIK")
    return [{"ticker": r[0], "name": r[1], "cik": cik_text(r[index])} for r in rows[1:] if len(r) > index]


def _fetch(url: str) -> bytes:
    payload, status, _headers = get_checked(url, allowed=same_host_https(url), headers={"User-Agent": USER_AGENT},
                                            timeout=60, max_bytes=MAX_BYTES)
    if status != 200 or len(payload) > MAX_BYTES:
        raise ValueError(f"constituents page status {status}, {len(payload)} bytes")
    return payload


def _census_rows(payload: bytes, root: Path, day: str, member_known_at: str, identity_known_at: str) -> list[dict]:
    page = constituents(payload.decode("utf-8"))
    tickers = [row["ticker"] for row in page]
    if not MIN_ROWS <= len(page) <= MAX_ROWS or len(set(tickers)) != len(tickers):
        raise ValueError(f"constituents guard: {len(page)} rows, {len(set(tickers))} distinct tickers")
    store = load_universe(root)
    if store.integrity_errors:
        raise ValueError("universe store has integrity errors; no instrument bindings")
    bindings, rejected = select_instrument_bindings(
        {t: {"current": True, "open_from": day} for t in tickers}, list(store.records), {t: {} for t in tickers},
        known_at=member_known_at, revision=str(store.revision))
    bound = {b["ticker"]: b["instrument_id"] for b in bindings}
    reasons = {r["ticker"]: r["reason"] for r in rejected}
    valid_to = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    return [{"scope": SCOPE, "source_ticker": t, "instrument_id": bound.get(t), "valid_from": day, "valid_to": valid_to,
             "member_known_at": member_known_at, "identity_known_at": identity_known_at if t in bound else None,
             "binding_status": "bound" if t in bound else "unbound",
             "reason": None if t in bound else reasons.get(t, "no_verified_usd_stock")} for t in tickers]


def _result(status: str, day: str, known_at: str, rows: pd.DataFrame | list[dict], written: int) -> Sp500Capture:
    frame = pd.DataFrame(rows, columns=COVERAGE_COLUMNS)
    bound = int(frame["binding_status"].eq("bound").sum())
    return Sp500Capture(status, day, known_at, len(frame), bound, len(frame) - bound, written)


def capture_sp500(root: Path, *, now: datetime, fetch=None) -> Sp500Capture:
    """Capture tonight's constituents into the ledger and append its census; skip when the day's census exists.

    Raises ``Sp500CaptureError`` on a fetch, parse, guard or capture failure; nothing is written in that case.
    """
    root = Path(root)
    stamp = now.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    day = stamp[:10]
    path = root / COVERAGE_RELATIVE_PATH
    try:
        old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=COVERAGE_COLUMNS)
        if list(old.columns) != COVERAGE_COLUMNS:
            raise ValueError("existing index coverage schema mismatch")
        today = old.loc[old["scope"].eq(SCOPE) & old["valid_from"].eq(day)]
        if not today.empty:  # capture kept: first of day
            return _result("duplicate", day, str(today["member_known_at"].iloc[0]), today, 0)
        ledger = capture_log(SCOPE, root=root)
        ledger = ledger.loc[ledger["snapshot_date"].eq(day) & ledger["source_kind"].eq("self")]
        if not ledger.empty:  # census rebuilt from stored capture
            status, known_at = "duplicate", str(ledger["known_at"].iloc[0])
            rows = _census_rows(load_raw_payload(str(ledger["checksum"].iloc[0]), root=root), root, day, known_at, stamp)
        else:
            payload = (fetch or _fetch)(WIKI_CONSTITUENTS)
            rows = _census_rows(payload, root, day, stamp, stamp)
            status, known_at = record_listing_capture(
                [{"instrument_id": row["instrument_id"]} for row in rows if row["instrument_id"] is not None],
                SOURCE, SCOPE, stamp, root=root, raw_payload=payload, snapshot_date=day).status, stamp
        incoming = pd.DataFrame(rows, columns=COVERAGE_COLUMNS)
        combined = incoming if old.empty else pd.concat([old, incoming], ignore_index=True)
        atomic_write_bytes(path, parquet_payload(combined), validate_parquet_file)
    except Exception as exc:
        raise Sp500CaptureError(f"capture failed: {type(exc).__name__}: {exc}") from exc
    return _result(status, day, known_at, rows, len(rows))
