"""PR-3b: the weekly SEC evidence refresh (INT-06, INT-17, INT-18) with a fake SEC transport."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
from types import SimpleNamespace
from urllib.error import HTTPError

import pandas as pd
import pytest

from etf_cockpit.application import sec_evidence_refresh as ser
from etf_cockpit.data.bitemporal import BitemporalStore
from etf_cockpit.data.earnings_surprise import DATASET_ID
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.data.stock_fundamentals import SNAPSHOT_COLUMNS, store_paths
from tests.test_earnings_surprise import _REVENUE, _case

AGENT = "ETF AI Cockpit tests research@company.org"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000777001.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0000777001.json"


def _shift(value):
    """The `_case()` issuer moved four years later, so its last quarter is reported in 2026."""
    if isinstance(value, dict):
        return {key: _shift(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_shift(item) for item in value]
    return re.sub(r"20(19|2[0-3])", lambda m: str(int(m[0]) + 4), value) if isinstance(value, str) else value


def _sec_documents(filings: tuple[tuple[str, str, str, str, str, str], ...] = ()) -> dict[str, bytes]:
    """companyfacts and submissions; ``filings`` adds (accession, form, filed, accepted, items, primary document) rows."""
    facts, submissions = (_shift(item) for item in _case())
    facts["cik"] = submissions["cik"] = 777001
    recent = submissions["filings"]["recent"]
    recent["primaryDocument"] = [""] * len(recent["accessionNumber"])
    for row in filings:
        for column, value in zip(("accessionNumber", "form", "filingDate", "acceptanceDateTime", "items", "primaryDocument"), row):
            recent[column].append(value)
    return {FACTS_URL: json.dumps(facts).encode(), SUBMISSIONS_URL: json.dumps(submissions).encode()}


class FakeSec:
    """Serves fixed bytes per URL and records every request; an unknown URL is a 404, never a real request."""

    def __init__(self, documents: dict[str, bytes]):
        self.documents, self.calls = documents, []

    def __call__(self, url: str, _headers: dict[str, str]):
        self.calls.append(url)
        return (self.documents[url], 200, {}) if url in self.documents else (b"", 404, {})


def _setup(tmp_path: Path, documents: dict[str, bytes]) -> tuple[SimpleNamespace, FakeSec, SecEdgarProvider]:
    snapshots = pd.DataFrame([
        {"instrument_id": "ZZA", "known_at": "2026-10-01T00:00:00+00:00", "source": "yfinance", "status": "ok", "country": "United States", "cik": "0000777001"},
        {"instrument_id": "SAP", "known_at": "2026-10-01T00:00:00+00:00", "source": "yfinance", "status": "ok", "country": "Germany"},
    ], columns=SNAPSHOT_COLUMNS)
    path = store_paths(tmp_path)["snapshots"]
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshots.to_parquet(path)
    config = SimpleNamespace(
        universe=SimpleNamespace(etfs=[
            {"id": "ZZA", "name": "ZZA Corp", "instrument_type": "stock", "provider_symbol": "ZZA", "enabled": True},
            {"id": "SAP", "name": "SAP SE", "instrument_type": "stock", "provider_symbol": "SAP.DE", "enabled": True},
        ]),
        targets=SimpleNamespace(positions={"ZZA": object()}),
    )
    fake = FakeSec(documents)
    return config, fake, SecEdgarProvider(AGENT, cache_dir=tmp_path / "sec_cache", transport=fake, rate_limit_seconds=0)


def _sue(i: int) -> float:
    return (_REVENUE[i] - _REVENUE[i - 4]) / statistics.stdev([_REVENUE[j] - _REVENUE[j - 4] for j in range(max(4, i - 8), i)])


def test_int06_weekly_refresh_stores_sec_receipt_earnings_rows_once_and_skips_non_us_issuers(tmp_path: Path) -> None:
    config, fake, provider = _setup(tmp_path, _sec_documents())
    first = ser.refresh_sec_evidence(config, root=tmp_path, provider=provider, now=NOW)
    assert first["earnings_rows"] > 0
    assert first["reasons"]["SAP"] == "non_us_issuer"
    assert all("SAP" not in url for url in fake.calls)
    with BitemporalStore(tmp_path) as store:
        rows = store.observations(DATASET_ID, entity_id="ZZA")
    assert rows and all(row.available_at >= row.value["sec_receipt_time"] for row in rows)

    calls = len(fake.calls)
    again = ser.refresh_sec_evidence(config, root=tmp_path, provider=provider, now=NOW)
    assert again["earnings_rows"] == 0
    assert set(fake.calls[calls:]) <= {FACTS_URL, SUBMISSIONS_URL}

    before_10q = datetime(2026, 5, 1, tzinfo=timezone.utc)  # the 2026Q1 figure is filed in the 10-Q of 05-05
    value, _detail, reason = ser.sue_revenue_feature(tmp_path, "ZZA", before_10q)
    assert value == pytest.approx(_sue(11)) and reason is None
    assert ser.sue_revenue_feature(tmp_path, "ZZA", datetime(2026, 6, 15, tzinfo=timezone.utc))[0] == pytest.approx(_sue(12))
    assert ser.sue_revenue_feature(tmp_path, "ZZA", NOW)[0] == pytest.approx(_sue(13))  # 2026Q2, filed 08-05
    value, detail, reason = ser.sue_revenue_feature(tmp_path, "ZZA", datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert (value, detail) == (None, "—") and reason


ACC_F4 = "0000777001-26-000001"
F4_URL = "https://www.sec.gov/Archives/edgar/data/777001/000077700126000001/form4.xml"


def test_int17_new_form4_filings_are_stored_at_acceptance_and_never_fetched_twice(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("edgar")
    documents = _sec_documents((
        (ACC_F4, "4", "2026-08-13", "2026-08-13T12:00:00.000Z", "", "xslF345X05/form4.xml"),
        ("0000777001-26-000002", "4", "2026-01-02", "2026-01-02T12:00:00.000Z", "", "old.xml"),  # older than 120 days
        ("0000777001-26-000003", "4", "2026-09-01", "", "", "noacceptance.xml"),  # no acceptance time: fail closed
    ))
    xml = (FIXTURES / "sec_ownership" / "form4_mixed.xml").read_bytes()
    documents[F4_URL] = xml.replace(b"<issuerCik>0000012345</issuerCik>", b"<issuerCik>0000777001</issuerCik>")
    config, fake, provider = _setup(tmp_path, documents)

    with monkeypatch.context() as patch:  # without the parser no Form 4 is downloaded only to be dropped
        patch.setattr(ser, "find_spec", lambda _name: None)
        missing = ser.refresh_sec_evidence(config, root=tmp_path, provider=provider, now=NOW)
    assert missing["insider_rows"] == 0 and F4_URL not in fake.calls and "edgartools" in missing["reasons"]["ZZA"]

    first = ser.refresh_sec_evidence(config, root=tmp_path, provider=provider, now=NOW)
    assert first["insider_rows"] == 1 and fake.calls.count(F4_URL) == 1
    assert not any(name in url for url in fake.calls for name in ("old.xml", "noacceptance.xml"))
    assert "0000777001-26-000003" in first["reasons"]["ZZA"]
    with BitemporalStore(tmp_path) as store:
        (row,) = store.observations(ser.INSIDER_DATASET, entity_id="ZZA")
    accepted = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
    assert datetime.fromisoformat(row.available_at) == datetime.fromisoformat(row.value["known_at"]) == accepted
    assert row.availability_confidence == "exact"

    again = ser.refresh_sec_evidence(config, root=tmp_path, provider=provider, now=NOW)
    assert again["insider_rows"] == 0 and fake.calls.count(F4_URL) == 1

    name = "insider_net_open_market_shares"
    assert ser.insider_features(tmp_path, "ZZA", "0000777001", NOW)[name].value == 1300.0
    early = ser.insider_features(tmp_path, "ZZA", "0000777001", datetime(2026, 8, 13, 11, tzinfo=timezone.utc))[name]
    assert (early.value, early.reason) == (None, "no_insider_filing_known_by_decision_time")


ACC_8K, ACC_10K = "0000777001-26-000010", "0000777001-26-000004"
EIGHT_K_URL = f"https://www.sec.gov/Archives/edgar/data/777001/{ACC_8K}.txt"
TEN_K_URL = f"https://www.sec.gov/Archives/edgar/data/777001/{ACC_10K}.txt"


def _filing_documents() -> dict[str, bytes]:
    documents = _sec_documents((
        (ACC_8K, "8-K", "2026-07-30", "2026-07-30T20:15:00.000Z", "2.02,9.01", "ex991.htm"),  # the 2026Q2 release
        (ACC_10K, "10-K", "2026-02-27", "2026-02-27T21:30:00.000Z", "", "form10k.htm"),
    ))
    directory = FIXTURES / "sec_filing_documents"
    documents[EIGHT_K_URL] = (directory / "8k_earnings.txt").read_bytes()
    documents[TEN_K_URL] = (directory / "10k_sections.txt").read_bytes()
    return documents


def test_int18_8k_release_time_reaches_the_earnings_rows_and_the_latest_10k_of_a_position_is_searchable(tmp_path: Path) -> None:
    import sqlite3

    from etf_cockpit.application.research_evidence import search_document_chunks
    from etf_cockpit.data.document_chunks import CHUNK_STORE_NAME

    pytest.importorskip("edgar")
    config, fake, provider = _setup(tmp_path / "unheld", _filing_documents())
    config.targets.positions = {}
    ser.refresh_sec_evidence(config, root=tmp_path / "unheld", provider=provider, now=NOW)
    assert EIGHT_K_URL in fake.calls and TEN_K_URL not in fake.calls  # 10-K scope: target positions only

    config, fake, provider = _setup(tmp_path, _filing_documents())
    first = ser.refresh_sec_evidence(config, root=tmp_path, provider=provider, now=NOW)
    assert first["ten_k_chunks"] == 2
    with BitemporalStore(tmp_path) as store:
        stored = {(o.value["event_key"], o.value["feature"]): o.value for o in store.observations(DATASET_ID, entity_id="ZZA")}
    assert stored[("2026-06-30", "sue_revenue")]["public_announcement_time"] == "2026-07-30T20:05:00+00:00"
    assert stored[("2026-06-30", "sue_revenue")]["sec_receipt_time"] == "2026-07-30T20:15:00+00:00"

    hits = search_document_chunks(tmp_path, "competition larger vendors", as_of="2026-03-01T00:00:00Z")["hits"]
    assert hits and hits[0]["source_id"].endswith(":risk_factors")
    assert search_document_chunks(tmp_path, "competition", as_of="2026-02-27T21:00:00Z")["hits"] == []  # before acceptance

    def chunk_count() -> int:
        with sqlite3.connect(tmp_path / "data" / CHUNK_STORE_NAME) as connection:
            return connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    count, calls = chunk_count(), len(fake.calls)
    again = ser.refresh_sec_evidence(config, root=tmp_path, provider=provider, now=NOW)
    assert (again["earnings_rows"], again["ten_k_chunks"], chunk_count()) == (0, 0, count)
    assert set(fake.calls[calls:]) <= {FACTS_URL, SUBMISSIONS_URL}  # stored 8-K and 10-K: no new fetch


def test_without_a_user_agent_every_target_has_the_reason_and_no_request_is_made(tmp_path: Path, monkeypatch) -> None:
    config, _fake, _provider = _setup(tmp_path, {})
    monkeypatch.delenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT", raising=False)
    monkeypatch.setattr(ser, "get_checked", lambda *_a, **_k: pytest.fail("no request without a User-Agent"))
    result = ser.refresh_sec_evidence(config, root=tmp_path, now=NOW)
    assert set(result["reasons"]) == {"ZZA", "SAP"} and "User-Agent" in result["reasons"]["ZZA"]


def test_transport_maps_304_to_a_response_and_refuses_a_body_above_50_mb(monkeypatch) -> None:
    seen = {}

    def not_modified(url, **kwargs):
        seen.update(kwargs)
        raise HTTPError(url, 304, "Not Modified", {"ETag": "abc"}, None)

    monkeypatch.setattr(ser, "get_checked", not_modified)
    payload, status, headers = ser._sec_transport(FACTS_URL, {"User-Agent": AGENT})
    assert (payload, status, dict(headers)) == (b"", 304, {"ETag": "abc"})
    assert seen["max_bytes"] == 50_000_000 and seen["allowed"](FACTS_URL) and not seen["allowed"]("https://example.org/x")

    monkeypatch.setattr(ser, "get_checked", lambda url, **kwargs: (b"x" * (kwargs["max_bytes"] + 1), 200, {}))
    with pytest.raises(ValueError, match="response too large"):
        ser._sec_transport(FACTS_URL, {})
    monkeypatch.setattr(ser, "get_checked", lambda url, **kwargs: (_ for _ in ()).throw(HTTPError(url, 403, "Forbidden", {}, None)))
    with pytest.raises(HTTPError):
        ser._sec_transport(FACTS_URL, {})


def test_weekly_fundamentals_script_runs_the_sec_evidence_refresh_after_the_fundamentals(monkeypatch) -> None:
    import sys

    from etf_cockpit.application import stock_service
    from etf_cockpit.core import config as config_module
    from scripts import refresh_stock_fundamentals as script

    order = []
    monkeypatch.setattr(sys, "argv", ["refresh_stock_fundamentals.py", "--ids", "ZZA"])
    monkeypatch.setattr(config_module, "load_config", lambda: "cfg")
    monkeypatch.setattr(stock_service, "refresh_universe_stock_fundamentals",
                        lambda *a, **k: order.append(("fundamentals", a, k["only_ids"])) or SimpleNamespace(rows_added=0, failures={}))
    monkeypatch.setattr(ser, "refresh_sec_evidence",
                        lambda *a, **k: order.append(("sec", a, k["only_ids"])) or {"earnings_rows": 0, "insider_rows": 0, "ten_k_chunks": 0, "reasons": {}})
    assert script.main() == 0
    assert order == [("fundamentals", ("cfg",), {"ZZA"}), ("sec", ("cfg",), {"ZZA"})]
