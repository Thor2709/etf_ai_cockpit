"""Pure-logic tests for the S&P live acquisition layer (no network)."""
from types import SimpleNamespace
import time

import pytest

from etf_cockpit.data.sp500_history import build_intervals
from scripts import acquire_sp500 as acq


def event(date, action, ticker, name=None):
    return {"date": date, "action": action, "ticker": ticker, "name": name or ticker}


def test_reverse_baseline_round_trips_through_build_intervals_with_conservative_announcements():
    events = [event("2020-03-01", "add", "ZZC"), event("2020-03-01", "remove", "ZZB"), event("2021-01-05", "remove", "ZZA")]
    baseline, issues = acq.reverse_baseline({"ZZC"}, events, "2019-12-31")
    assert baseline == ["ZZA", "ZZB"] and issues == []
    intervals = build_intervals({"date": "2019-12-31", "known_at": "2019-12-31", "tickers": baseline}, events,
                                acq.conservative_announcements(events), source="wikipedia")
    removed = [row for row in intervals if row["ticker"] == "ZZA" and row["valid_to"]]
    # Knowledge is the END of the effective day: never earlier than the change itself.
    assert removed[0]["known_at"] == "2021-01-05T23:59:59.999999+00:00"
    # A change that cannot be undone is reported, not silently absorbed.
    assert acq.reverse_baseline({"ZZC"}, [event("2020-03-01", "add", "ZZQ")], "2019-12-31")[1]


def record(instrument_id, ticker, isin, status="verified", kind="stock"):
    return SimpleNamespace(instrument_id=instrument_id, ticker=ticker, isin=isin, isin_status=status, asset_type=kind)


def test_instrument_bindings_come_only_from_verified_us_stock_records_with_exact_ticker():
    members = {t: {"current": True, "open_from": "2010-02-16"} for t in ("BRK.B", "LR", "BA", "XXX")}
    ciks = {t: {"cik": "0000000001"} for t in members}
    records = [record("BRK_B", "BRK-B", "US0846707026"), record("LEGRAND", "LR", "FR0010307819"),
               record("BOEING", "BA", "US0970231058", status="needs_verification"), record("MSFT", "MSFT", "US5949181045")]
    bindings, rejected = acq.select_instrument_bindings(members, records, ciks, known_at="2026-10-22T00:00:00+00:00", revision="r1")
    assert [(b["ticker"], b["instrument_id"]) for b in bindings] == [("BRK.B", "BRK_B")]
    assert bindings[0]["valid_to"] is None and bindings[0]["source"] and rejected == []


def test_name_key_requires_exact_normalised_equality():
    assert acq.name_key("Anheuser-Busch Companies, Inc. (BUD)") == acq.name_key("ANHEUSER BUSCH COMPANIES")
    assert acq.name_key("Alcoa") != acq.name_key("Alcoa Arconic")


def test_resume_accepts_only_checksum_matching_files(tmp_path):
    target, meta = tmp_path / "a.json", tmp_path / "meta"
    acq.record(target, meta, b"{}", url="u")
    assert acq.recorded(target, meta)["sha256"] == acq.sha256(b"{}")
    target.write_bytes(b"[]")
    assert acq.recorded(target, meta) is None


def test_limiter_spaces_calls_across_threads():
    limiter = acq.Limiter(20.0)
    from concurrent.futures import ThreadPoolExecutor
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: limiter.wait(), range(6)))
    # Six calls need five full 50 ms gaps however the threads interleave.
    assert time.monotonic() - started >= 0.24


def test_windows_and_members_table_keep_removed_names():
    snaps = [{"date": "2020-01-01", "tickers": ["A", "B"]}, {"date": "2020-06-01", "tickers": ["A", "C"]}]
    assert acq.windows(snaps) == {"A": [["2020-01-01", None]], "B": [["2020-01-01", "2020-06-01"]], "C": [["2020-06-01", None]]}
    history = {"snapshots": snaps, "wiki_events": [event("2020-06-01", "remove", "B", "Bee Corp")],
               "current": [{"ticker": "A", "name": "Alpha", "cik": "0000000001"}]}
    table = acq.members_table(history)
    assert table["B"]["current"] is False and table["B"]["name"] == "Bee Corp"
    assert table["A"]["current"] is True and table["A"]["open_from"] == "2020-01-01"
