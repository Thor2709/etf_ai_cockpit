"""Nightly S&P 500 capture and census (forward paper path C2/C3). No network: ``fetch`` is injected."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data import sp500_capture
from etf_cockpit.data.sp500_capture import Sp500CaptureError, capture_sp500, constituents, select_instrument_bindings
from etf_cockpit.data.universe_membership import capture_log
from etf_cockpit.data.universe_store import UniverseRecord, save_universe

NOW = datetime(2026, 11, 20, 21, 31, tzinfo=timezone.utc)
SCOPE = "listing:sp500:all"
TICKERS = ["BRK.B", "ACN", *(f"F{index:03d}" for index in range(498))]


def _page(tickers=TICKERS, header=("Symbol", "Security", "GICS Sector", "CIK")) -> bytes:
    head = "".join(f"<th>{name}</th>" for name in header)
    body = "".join(f'<tr><td><a href="/x">{ticker}</a></td><td>{ticker} Inc.</td><td>Tech</td><td>{index + 1:010d}</td></tr>'
                   for index, ticker in enumerate(tickers))
    return f'<html><table class="wikitable" id="constituents"><tr>{head}</tr>{body}</table></html>'.encode()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("network is forbidden in capture tests")
    monkeypatch.setattr(sp500_capture, "get_checked", denied)


@pytest.fixture
def root(tmp_path):
    save_universe((
        UniverseRecord("BRK_B", "Berkshire", isin="US0846707026", ticker="BRK-B", currency="USD"),
        UniverseRecord("ACCENTURE", "Accenture", isin="IE00B4BNMY34", ticker="ACN", currency="USD"),
        UniverseRecord("F000_EU", "F000 Europe", isin="FR0010307819", ticker="F000", currency="EUR"),
    ), expected_revision="", root=tmp_path)
    return tmp_path


def _census(root) -> pd.DataFrame:
    return pd.read_parquet(root / sp500_capture.COVERAGE_RELATIVE_PATH)


def test_parser_reads_symbol_security_cik_table():
    rows = constituents(_page(["MMM", "AOS", "ABT", "BRK.B", "ZTS"]).decode())
    assert [row["ticker"] for row in rows] == ["MMM", "AOS", "ABT", "BRK.B", "ZTS"]
    assert rows[3] == {"ticker": "BRK.B", "name": "BRK.B Inc.", "cik": "0000000004"}
    with pytest.raises(ValueError, match="header"):
        constituents(_page(["MMM"], header=("Ticker", "Security", "CIK")).decode())


def test_binding_rule_is_exact_ticker_usd_unique_and_any_isin_country():
    def record(instrument_id, ticker, isin, currency="USD", status="verified"):
        return SimpleNamespace(instrument_id=instrument_id, ticker=ticker, isin=isin, isin_status=status,
                               asset_type="stock", currency=currency)
    members = {t: {"current": True, "open_from": "2026-11-20"} for t in ("ACN", "BRK.B", "DUP", "LR", "BA")}
    records = [record("ACCENTURE", "ACN", "IE00B4BNMY34"), record("BRK_B", "BRK-B", "US0846707026"),
               record("DUP_A", "DUP", "US0000000011"), record("DUP_B", "DUP", "US0000000029"),
               record("LEGRAND", "LR", "FR0010307819", currency="EUR"),
               record("BOEING", "BA", "US0970231058", status="needs_verification")]
    bindings, rejected = select_instrument_bindings(members, records, {t: {"cik": "1"} for t in members},
                                                    known_at="2026-11-20T21:31:00Z", revision="r1")
    assert [(b["ticker"], b["instrument_id"]) for b in bindings] == [("ACN", "ACCENTURE"), ("BRK.B", "BRK_B")]
    assert rejected == [{"ticker": "DUP", "reason": "ambiguous_universe_records"}]


def test_rerun_same_night_is_duplicate_without_extra_rows(root):
    first = capture_sp500(root, now=NOW, fetch=lambda _url: _page())
    assert (first.status, first.snapshot_date, first.members, first.bound, first.unbound, first.census_rows) == (
        "recorded", "2026-11-20", 500, 2, 498, 500)
    census = _census(root)
    assert list(census.columns) == sp500_capture.COVERAGE_COLUMNS
    bound = census.loc[census["binding_status"].eq("bound")]
    assert dict(zip(bound["source_ticker"], bound["instrument_id"])) == {"BRK.B": "BRK_B", "ACN": "ACCENTURE"}
    assert set(census["valid_from"]) == {"2026-11-20"} and set(census["valid_to"]) == {"2026-11-21"}
    assert set(census["member_known_at"]) == {first.known_at} and set(bound["identity_known_at"]) == {first.known_at}
    unbound = census.loc[census["binding_status"].eq("unbound")]
    assert unbound["identity_known_at"].isna().all() and set(unbound["reason"]) == {"no_verified_usd_stock"}
    ledger = capture_log(SCOPE, root=root)
    assert len(ledger) == 1 and int(ledger.iloc[0]["row_count"]) == 2

    def refetch(_url):
        raise AssertionError("a same-night rerun must not fetch")
    second = capture_sp500(root, now=NOW + timedelta(hours=1), fetch=refetch)
    assert (second.status, second.members, second.bound, second.census_rows) == ("duplicate", 500, 2, 0)
    assert len(_census(root)) == 500 and len(capture_log(SCOPE, root=root)) == 1


def test_next_night_capture_keeps_previous_census_rows(root):
    capture_sp500(root, now=NOW, fetch=lambda _url: _page())
    later = capture_sp500(root, now=NOW + timedelta(days=1), fetch=lambda _url: _page(TICKERS[:-1] + ["NEW"]))
    assert later.status == "recorded" and later.snapshot_date == "2026-11-21"
    census = _census(root)
    assert census.groupby("valid_from").size().to_dict() == {"2026-11-20": 500, "2026-11-21": 500}
    assert len(capture_log(SCOPE, root=root)) == 2


def test_capture_without_census_is_rebuilt_from_the_stored_payload(root):
    first = capture_sp500(root, now=NOW, fetch=lambda _url: _page())
    (root / sp500_capture.COVERAGE_RELATIVE_PATH).unlink()

    def refetch(_url):
        raise AssertionError("a rebuild must not fetch")
    rebuilt_at = NOW + timedelta(minutes=5)
    rebuilt = capture_sp500(root, now=rebuilt_at, fetch=refetch)
    assert (rebuilt.status, rebuilt.census_rows, rebuilt.bound) == ("duplicate", 500, 2)
    census = _census(root)
    assert set(census["member_known_at"]) == {first.known_at}
    bound = census.loc[census["binding_status"].eq("bound"), "identity_known_at"]
    assert set(pd.to_datetime(bound, utc=True)) == {pd.Timestamp(rebuilt_at)}
    assert len(capture_log(SCOPE, root=root)) == 1


@pytest.mark.parametrize("fetch", [
    pytest.param(lambda _url: (_ for _ in ()).throw(OSError("offline")), id="fetch"),
    pytest.param(lambda _url: _page(header=("Ticker", "Security", "CIK")), id="header"),
    pytest.param(lambda _url: _page(TICKERS[:10]), id="row-count"),
])
def test_fetch_parse_or_guard_failure_raises_and_writes_nothing(root, fetch):
    with pytest.raises(Sp500CaptureError):
        capture_sp500(root, now=NOW, fetch=fetch)
    assert capture_log(SCOPE, root=root).empty
    assert not (root / sp500_capture.COVERAGE_RELATIVE_PATH).exists()


def test_default_fetch_goes_only_through_get_checked(root, monkeypatch):
    calls = []

    def fake_get_checked(url, *, allowed, headers, timeout, max_bytes):
        calls.append((url, allowed))
        return _page(), 200, {}
    monkeypatch.setattr(sp500_capture, "get_checked", fake_get_checked)
    assert capture_sp500(root, now=NOW).status == "recorded"
    [(url, allowed)] = calls
    assert url == sp500_capture.WIKI_CONSTITUENTS
    assert allowed("https://en.wikipedia.org/wiki/Other") and not allowed("https://example.com/x")
