"""Offline synthetic SEC cover evidence and complete-window identity rules."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_cockpit.data.sec_cover_identity import acceptance_utc, identity_spans, parse_cover, select_bindings

FIXTURES = Path(__file__).parent / "fixtures" / "sec_cover"


def cover(cik="9000000001", *, accepted="2019-12-20T14:30:00", ticker="ZZA"):
    payload = (FIXTURES / f"{cik}-19-000001.txt").read_bytes()
    payload = payload.replace(b"<ACCEPTANCE-DATETIME>20191220143000", b"<ACCEPTANCE-DATETIME>" + accepted[:19].replace(
        "-", "").replace(":", "").replace("T", "").encode())
    if cik == "9000000001":
        payload = payload.replace(b">ZZA<", f">{ticker}<".encode())
    # The helper's accepted argument supplies header wall time; submissions is UTC.
    submitted = acceptance_utc(accepted.removesuffix("Z")).replace("+00:00", "Z")
    return parse_cover(payload, cik=cik, accession=f"{cik}-19-000001", form="10-K", acceptance=submitted,
                       source=f"https://www.sec.gov/synthetic/{cik}")


def interval(ticker="ZZA", start="2020-01-01", end=None):
    return {"ticker": ticker, "valid_from": start, "valid_to": end}


def record(ticker="ZZA"):
    return SimpleNamespace(asset_type="stock", isin_status="verified", isin="US5949181045", ticker=ticker,
                           instrument_id=f"synthetic-{ticker}")


def select(rows, windows=None, records=None, **kwargs):
    return select_bindings(rows, windows or [interval()], records or [record()], revision="fixture", **kwargs)


def test_cover_filed_later_than_interval_start_leaves_window_unbound():
    ciks, instruments, rejected = select([cover(accepted="2020-02-01T12:00:00Z")])
    assert not ciks and not instruments
    assert rejected[0]["reason"] == "no_cover_identity_for_window"


def test_cover_before_start_binds_at_acceptance_et_to_utc():
    ciks, instruments, rejected = select([cover()])
    assert rejected == []
    assert ciks[0]["known_at"] == instruments[0]["known_at"] == "2019-12-20T19:30:00+00:00"
    assert ciks[0]["valid_from"] == "2019-12-21"
    assert "provider symbol ZZA" in instruments[0]["source"]
    assert "9000000001-19-000001" in instruments[0]["source"]
    assert acceptance_utc("2020-07-01T14:30:00Z") == "2020-07-01T14:30:00+00:00"
    assert acceptance_utc("20200701143000") == "2020-07-01T18:30:00+00:00"


def test_acceptance_on_start_day_cannot_backdate_midnight():
    assert select([cover(accepted="2020-01-01T09:00:00Z")])[2]


def test_recycled_ticker_second_cik_rejected_even_after_closed_window():
    first = cover()
    other = {**cover("9000000002", accepted="2021-01-01T12:00:00Z"), "tickers": ["ZZA"]}
    ciks, instruments, rejected = select([first, other], [interval(end="2020-07-01")])
    assert not ciks and not instruments
    assert rejected[0]["reason"] == "recycled_ticker"
    changed = cover(accepted="2020-05-01T12:00:00Z", ticker="ZZD")
    assert select([first, changed, other])[2][0]["reason"] == "recycled_ticker"


def test_overlapping_cik_claims_are_ambiguous():
    other = {**cover("9000000002"), "tickers": ["ZZA"]}
    assert select([cover(), other])[2][0]["reason"] == "ambiguous_cover_identity"


def test_ticker_change_closes_binding_and_repeated_cover_keeps_first_knowledge():
    first = cover()
    same = cover(accepted="2020-03-01T12:00:00Z")
    changed = cover(accepted="2020-07-01T12:00:00Z", ticker="ZZD")
    spans = identity_spans([changed, same, first])
    old = next(row for row in spans if row["ticker"] == "ZZA")
    assert old["known_at"] == first["known_at"] and old["until"] == "2020-07-01T16:00:00+00:00"
    assert select([first, same, changed])[2][0]["reason"] == "no_cover_identity_for_window"
    ciks, instruments, rejected = select([first, same, changed], [interval(end="2020-07-01")])
    assert not rejected and ciks[0]["valid_to"] == "2020-07-01" and instruments


def test_multiclass_cover_binds_each_provider_symbol_separately():
    ciks, instruments, rejected = select([cover("9000000002")], [interval("ZZB"), interval("ZZC")],
                                         [record("ZZB"), record("ZZC")])
    assert not rejected
    assert {b["ticker"] for b in ciks} == {b["ticker"] for b in instruments} == {"ZZB", "ZZC"}


def test_changed_ticker_set_closes_even_a_retained_class():
    first = cover("9000000002")
    changed = {**first, "known_at": "2020-03-01T12:00:00+00:00", "tickers": ["ZZB"]}
    spans = [r for r in identity_spans([first, changed]) if r["ticker"] == "ZZB"]
    assert len(spans) == 2
    assert spans[0]["until"] == changed["known_at"] == spans[1]["known_at"]
    assert select([first, changed], [interval("ZZB")], [record("ZZB")])[2]


@pytest.mark.parametrize("mutation", [
    lambda p: p.replace(b"9000000001</ix", b"9000000002</ix"),
    lambda p: p.replace(b">ZZA<", b">N/A<"),
    lambda p: p.replace(b"dei:TradingSymbol", b"dei:OtherField"),
    lambda p: p.replace(b"20191220143000", b"20191320143000"),
])
def test_missing_unparseable_or_conflicting_cover_fails_closed(mutation):
    with pytest.raises(ValueError):
        parse_cover(mutation((FIXTURES / "9000000001-19-000001.txt").read_bytes()), cik="9000000001",
                    accession="9000000001-19-000001", form="10-K", acceptance="2019-12-20T19:30:00Z", source="fixture")


def test_unreadable_filing_breaks_continuity_and_failed_scan_binds_nothing():
    first = cover()
    missing = {**first, "known_at": "2020-02-01T12:00:00+00:00", "tickers": []}
    assert select([first, missing])[2]
    assert select([first], failed_ciks={first["cik"]})[2][0]["reason"] == "incomplete_cover_scan"
    assert select([first], incomplete_tickers={"ZZA"})[2][0]["reason"] == "incomplete_cover_scan"


def test_repeated_competing_claim_after_start_is_recycled_ticker():
    first = cover()
    other = {**cover("9000000002"), "tickers": ["ZZA"]}
    repeated = {**other, "known_at": "2020-02-01T12:00:00+00:00"}
    closed = {**other, "known_at": "2020-03-01T12:00:00+00:00", "tickers": ["ZZD"]}
    assert select([first, other, repeated, closed])[2][0]["reason"] == "recycled_ticker"


def test_reentry_reuses_one_cik_span_without_duplicate_bindings():
    ciks, instruments, rejected = select([cover()], [interval(end="2020-07-01"), interval(start="2020-09-01")])
    assert not rejected and len(ciks) == 1 and len(instruments) == 2


@pytest.mark.parametrize("stamp", ["2020-11-01T01:30:00", "2020-03-08T02:30:00", "2020-01-01"])
def test_uncertain_acceptance_is_rejected(stamp):
    with pytest.raises(ValueError):
        acceptance_utc(stamp)


@pytest.mark.parametrize("header,submitted,expected", [
    ("20191220143000", "2019-12-20T19:30:00.000Z", "2019-12-20T19:30:00+00:00"),
    ("20170802163128", "2017-08-02T20:31:28.000Z", "2017-08-02T20:31:28+00:00"),
])
def test_header_eastern_and_submissions_utc_describe_same_instant(header, submitted, expected):
    payload = (FIXTURES / "9000000001-19-000001.txt").read_bytes().replace(b"20191220143000", header.encode())
    row = parse_cover(payload, cik="9000000001", accession="9000000001-19-000001", form="10-K",
                      acceptance=submitted, source="fixture")
    assert row["known_at"] == expected
    assert row["tickers"] == ["ZZA"]


def test_genuinely_conflicting_acceptance_still_fails_closed():
    with pytest.raises(ValueError, match="conflicting acceptanceDateTime"):
        parse_cover((FIXTURES / "9000000001-19-000001.txt").read_bytes(), cik="9000000001",
                    accession="9000000001-19-000001", form="10-K", acceptance="2019-12-20T20:30:00Z", source="fixture")


def test_headerless_cover_uses_submissions_utc_without_second_shift():
    payload = (FIXTURES / "9000000001-19-000001.txt").read_bytes().replace(b"<ACCEPTANCE-DATETIME>20191220143000", b"")
    row = parse_cover(payload, cik="9000000001", accession="9000000001-19-000001", form="10-K",
                      acceptance="2019-12-20T19:30:00.000Z", source="fixture")
    assert row["known_at"] == "2019-12-20T19:30:00+00:00"


@pytest.mark.parametrize("fixture,form,tickers", [
    ("9000000001-R1.htm", "10-K", ["ZZA"]),
    ("9000000002-R1.htm", "20-F/A", ["ZZB", "ZZC"]),
    ("inline-cover.htm", "10-Q/A", ["ZZA"]),
])
def test_small_rendered_and_inline_cover_fixtures(fixture, form, tickers):
    cik = "9000000002" if fixture.startswith("9000000002") else "9000000001"
    row = parse_cover((FIXTURES / fixture).read_bytes(), cik=cik, accession=f"{cik}-19-000001",
                      form=form, acceptance="2019-12-20T19:30:00.000Z", source="fixture")
    assert row["tickers"] == tickers
    assert row["known_at"] == "2019-12-20T19:30:00+00:00"


def test_rendered_labels_alone_cannot_supply_dei_evidence():
    payload = (FIXTURES / "9000000001-R1.htm").read_bytes().replace(b"defref_dei_", b"untrusted_")
    with pytest.raises(ValueError, match="cover evidence"):
        parse_cover(payload, cik="9000000001", accession="9000000001-19-000001", form="10-K",
                    acceptance="2019-12-20T19:30:00Z", source="fixture")
