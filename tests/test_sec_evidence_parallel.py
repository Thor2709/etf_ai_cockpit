"""The weekly SEC evidence refresh fetches several targets at once and records them in target order."""

from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.application import sec_evidence_refresh as ser
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.data.stock_fundamentals import SNAPSHOT_COLUMNS, store_paths
from tests.test_earnings_surprise import _case
from tests.test_sec_evidence_refresh import AGENT, NOW, _shift

CIKS = {"T0": 777001, "T1": 777002, "T2": 777003, "T3": 777004, "T4": 777005, "T5": 777005}  # T5: a second share class


def _documents() -> dict[str, bytes]:
    documents = {}
    for cik in set(CIKS.values()):
        facts, submissions = (_shift(item) for item in _case())
        facts["cik"] = submissions["cik"] = cik
        submissions["filings"]["recent"]["primaryDocument"] = [""] * len(submissions["filings"]["recent"]["accessionNumber"])
        documents[f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"] = json.dumps(facts).encode()
        documents[f"https://data.sec.gov/submissions/CIK{cik:010d}.json"] = json.dumps(submissions).encode()
    return documents


class SlowSec:
    """Serves fixed bytes after a delay; records each request's start and end and how many ran at once."""

    def __init__(self, documents: dict[str, bytes], delay: float):
        self.documents, self.delay, self.lock = documents, delay, threading.Lock()
        self.starts: list[float] = []
        self.spans: list[tuple[str, float, float]] = []
        self.running = self.most = 0

    def __call__(self, url: str, _headers: dict[str, str]):
        with self.lock:
            start = time.monotonic()
            self.starts.append(start)
            self.running += 1
            self.most = max(self.most, self.running)
        time.sleep(self.delay)
        with self.lock:
            self.running -= 1
            self.spans.append((url, start, time.monotonic()))
        return (self.documents[url], 200, {}) if url in self.documents else (b"", 404, {})


def _setup(tmp_path: Path) -> SimpleNamespace:
    rows = [{"instrument_id": iid, "known_at": "2026-10-01T00:00:00+00:00", "source": "yfinance", "status": "ok",
             "country": "United States", "cik": f"{cik:010d}"} for iid, cik in CIKS.items()]
    path = store_paths(tmp_path)["snapshots"]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS).to_parquet(path)
    return SimpleNamespace(
        universe=SimpleNamespace(etfs=[{"id": iid, "name": iid, "instrument_type": "stock", "provider_symbol": iid, "enabled": True} for iid in CIKS]),
        targets=SimpleNamespace(positions={}),
    )


def test_targets_are_fetched_at_once_but_recorded_and_reported_in_target_order(tmp_path: Path, monkeypatch) -> None:
    config = _setup(tmp_path)
    fake = SlowSec(_documents(), delay=0.05)
    provider = SecEdgarProvider(AGENT, cache_dir=tmp_path / "sec_cache", transport=fake, rate_limit_seconds=0)
    monkeypatch.setattr(ser, "find_spec", lambda _name: None)
    real_index = ser.acceptance_index

    def broken_for_t1(submissions):
        if submissions["cik"] == CIKS["T1"]:
            raise RuntimeError("bad submissions table")
        return real_index(submissions)

    monkeypatch.setattr(ser, "acceptance_index", broken_for_t1)
    messages: list[str] = []
    report = ser.refresh_sec_evidence(config, root=tmp_path, provider=provider, now=NOW, progress=messages.append)

    assert fake.most > 1  # several targets are in flight at once
    assert [message.split(":")[0] for message in messages] == [f"SEC evidence {iid}" for iid in CIKS]
    assert report["reasons"]["T1"] == "unexpected: RuntimeError: bad submissions table"  # one target never stops the others
    assert all("unexpected" not in report["reasons"].get(iid, "") for iid in CIKS if iid != "T1")
    assert report["earnings_rows"] > 0
    shared = sorted((start, end) for url, start, end in fake.spans if "0000777005" in url)
    assert all(later[0] >= earlier[1] for earlier, later in zip(shared, shared[1:]))  # one CIK is never fetched twice at once


def test_edgartools_parses_never_overlap_across_workers(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone

    from etf_cockpit.data import sec_filing_documents as sfd
    from etf_cockpit.data import sec_ownership as so

    fake = SlowSec({}, delay=0.05)

    def parser():  # a fake edgartools: each parse is one slow "request" that records how many ran at once
        fake("parse", {})
        raise so.SecOwnershipUnavailable("fake parser")

    monkeypatch.setattr(sfd, "_edgar", parser)
    monkeypatch.setattr(so, "_edgar", parser)
    when = datetime(2026, 7, 30, tzinfo=timezone.utc)
    parses = [lambda: sfd.parse_8k(b"", known_at=when), lambda: sfd.parse_10k_section_chunks(b"", known_at=when),
              lambda: so.parse_ownership_xml(b"", accession="0000777001-26-000001", known_at=when)] * 2

    def run(parse) -> None:
        with suppress(so.SecOwnershipUnavailable):
            parse()

    with ThreadPoolExecutor(ser._WORKERS) as pool:
        list(pool.map(run, parses))
    assert len(fake.spans) == len(parses) and fake.most == 1


def test_all_sec_requests_share_one_limit_of_at_most_8_per_second(tmp_path: Path, monkeypatch) -> None:
    config = _setup(tmp_path)
    fake = SlowSec(_documents(), delay=0.01)
    monkeypatch.setenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT", AGENT)
    monkeypatch.setattr(ser, "get_checked", lambda url, **kwargs: fake(url, kwargs["headers"]))
    monkeypatch.setattr(ser, "find_spec", lambda _name: None)
    ser.refresh_sec_evidence(config, root=tmp_path, now=NOW)

    starts = sorted(fake.starts)
    assert len(starts) == 2 * len(CIKS)
    assert all(later - earlier >= 1.0 for earlier, later in zip(starts, starts[8:]))  # never 9 requests within one second
