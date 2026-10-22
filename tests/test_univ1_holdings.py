"""Offline UNIV1 contract tests; all holdings are explicitly synthetic."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import threading

import pytest
import yaml

from etf_cockpit.data.holdings_registry import ISSUERS, collect_daily, fetch_csv, load_funds
from etf_cockpit.data.holdings_snapshots import gap_report, import_historical, load_snapshots, write_snapshot
from etf_cockpit.data.ishares_holdings import COLUMNS, next_known_at, parse_ishares_csv
from etf_cockpit.data.market_calendar import ListingCalendarEvidence

FIXTURE = Path(__file__).parent / "fixtures" / "univ1_holdings" / "latest.csv"
PAGE = "https://www.ishares.com/uk/individual/en/products/251882/ishares-core-msci-world-ucits-etf"
URL = PAGE + "/latest-holdings.csv"
INSTRUMENT = "synthetic-fund"
RECEIPT = "2026-10-22T12:00:00+00:00"


@pytest.fixture
def listing():
    return ListingCalendarEvidence(
        listing_id="synthetic-listing", instrument_id=INSTRUMENT, mic="XLON", calendar_id="XLON",
        timezone="Europe/London", source_id="synthetic-calendar-evidence",
        source_checksum=hashlib.sha256(b"synthetic calendar binding").hexdigest(),
        valid_from=date(2020, 1, 1), known_at=datetime(2020, 1, 1, tzinfo=timezone.utc))


def options(listing):
    return dict(instrument_id=INSTRUMENT, source_url=URL, listing=listing)


def test_parser_asof_thousands_and_other_positions(listing):
    parsed = parse_ishares_csv(FIXTURE.read_bytes(), **options(listing),
                              isin_mapping={("SYN", "Synthetic exchange"): "IE00B4L5Y983"})
    assert parsed["as_of"] == "2026-10-20"
    assert len(parsed["holdings"]) == 1
    row = parsed["holdings"][0]
    assert row["market_value"] == 8344104027.0
    assert row["shares"] == 1234.0 and row["weight"] == .98
    assert row["isin"] == "IE00B4L5Y983" and row["isin_unavailable"] is False
    assert {r["asset_class"] for r in parsed["other_positions"]} == {
        "Cash", "Futures", "FX", "Money Market", "Cash Collateral and Margins"}
    assert parsed["other_positions"][0]["market_value"] == -100
    assert all(r["known_at"] == "2026-10-21T00:00:00+00:00"
               for r in parsed["holdings"] + parsed["other_positions"])
    assert parsed["execution_allowed"] is False
    unmapped = parse_ishares_csv(FIXTURE.read_bytes(), **options(listing),
                                isin_mapping={("SYN", "Different exchange"): "IE00B4L5Y983"})
    assert unmapped["holdings"][0]["isin_unavailable"] is True
    assert unmapped["holdings"][0]["isin"] is None


@pytest.mark.parametrize(("as_of", "expected"), [
    (date(2026, 10, 16), "2026-10-19T00:00:00+00:00"),
    (date(2026, 12, 24), "2026-12-29T00:00:00+00:00"),
])
def test_known_at_weekend_and_holiday(listing, as_of, expected):
    assert next_known_at(as_of, listing).isoformat() == expected


def test_idempotent_refetch_and_append_revision(tmp_path, listing):
    raw = FIXTURE.read_bytes()
    args = dict(**options(listing), fetched_at=RECEIPT)
    first = write_snapshot(tmp_path, raw, **args)
    before = {p: p.read_bytes() for p in (tmp_path / "data").rglob("*.json")}
    assert first["status"] == "created"
    assert first["snapshot"]["content_hash"] == hashlib.sha256(raw).hexdigest()
    assert first["snapshot"]["source_url"] == URL
    assert first["snapshot"]["fetched_at"] == RECEIPT
    assert write_snapshot(tmp_path, raw, **args)["status"] == "unchanged"
    revised = raw.replace(b"98.00", b"97.00")
    result = write_snapshot(tmp_path, revised, **dict(args, fetched_at="2026-10-23T12:00:00+00:00"))
    assert result["status"] == "revision" and result["snapshot"]["revision"] == 2
    assert all(p.read_bytes() == content for p, content in before.items())
    assert len(list((tmp_path / "data").rglob("*.json"))) == 2
    # Publication lag cannot backdate our own receipt or a corrected payload.
    assert load_snapshots(tmp_path, INSTRUMENT, decision_time="2026-10-21T12:00:00+00:00") == []
    assert load_snapshots(tmp_path, INSTRUMENT, decision_time=RECEIPT)[0]["revision"] == 1
    assert load_snapshots(tmp_path, INSTRUMENT, decision_time="2026-10-24T00:00:00+00:00")[0]["revision"] == 2


def test_concurrent_same_snapshot_is_idempotent(tmp_path, listing):
    def save(_):
        return write_snapshot(tmp_path, FIXTURE.read_bytes(), **options(listing), fetched_at=RECEIPT)["status"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        statuses = list(pool.map(save, range(3)))
    assert statuses.count("created") == 1 and statuses.count("unchanged") == 2


@pytest.mark.parametrize("media", ["text/html", "text/csv"])
def test_html_response_rejected(monkeypatch, listing, media):
    from etf_cockpit.data import holdings_registry as registry
    html = b"<!DOCTYPE html><html>Not holdings</html>"
    monkeypatch.setattr(registry, "get_checked", lambda *a, **k: (html, 200, {"Content-Type": media}))
    monkeypatch.setattr(registry, "_LAST_REQUEST", {})
    with pytest.raises(ValueError, match="non-CSV/HTML"):
        fetch_csv(URL, "Mozilla/5.0")
    with pytest.raises(ValueError, match="not an iShares"):
        parse_ishares_csv(html, **options(listing))


def test_import_historical_never_overwrites_collected(tmp_path, listing):
    raw = FIXTURE.read_bytes()
    write_snapshot(tmp_path, raw, **options(listing), fetched_at=RECEIPT)
    before = {p: p.read_bytes() for p in (tmp_path / "data").rglob("*.json")}
    imported = import_historical(tmp_path, FIXTURE, **options(listing), fetched_at=RECEIPT,
                                 known_at="2026-10-21T10:00:00+00:00", licence_ref="synthetic manual fixture")
    assert imported["snapshot"]["origin"] == "historical"
    assert imported["snapshot"]["holdings"][0]["known_at"] == "2026-10-21T10:00:00+00:00"
    assert all(p.read_bytes() == content for p, content in before.items())
    assert len(list((tmp_path / "data").rglob("*.json"))) == 2
    historical = load_snapshots(tmp_path, INSTRUMENT, decision_time="2026-10-21T10:00:00+00:00")
    assert len(historical) == 1 and historical[0]["origin"] == "historical"
    assert load_snapshots(tmp_path, INSTRUMENT, decision_time="2026-10-21T09:59:59+00:00") == []
    with pytest.raises(ValueError, match="timezone-aware"):
        import_historical(tmp_path, FIXTURE, **options(listing), fetched_at=RECEIPT,
                          known_at="2026-10-21", licence_ref="synthetic")
    with pytest.raises(ValueError, match="require proven"):
        import_historical(tmp_path, FIXTURE, **options(listing), fetched_at=RECEIPT,
                          known_at=None, licence_ref="synthetic")


def config_file(root, funds):
    directory = root / "configs"
    directory.mkdir(exist_ok=True)
    path = directory / "ishares_ucits_funds_v1.yaml"
    path.write_text(yaml.safe_dump(dict(schema_version=1, execution_allowed=False,
                                        user_agent="Mozilla/5.0", funds=funds)), encoding="utf-8")


def test_collect_daily_empty_noop(tmp_path):
    config_file(tmp_path, [])
    before = set(tmp_path.rglob("*"))
    def unexpected(*args):
        pytest.fail("empty registry contacted the network")
    assert collect_daily(tmp_path, fetcher=unexpected) == []
    assert set(tmp_path.rglob("*")) == before


def test_registry_other_issuers_inactive():
    assert ISSUERS["iShares"]["active"] is True
    for name in ("Xtrackers", "Vanguard", "Amundi", "SPDR"):
        assert ISSUERS[name]["active"] is False
        assert ISSUERS[name]["required_fields"]
        assert "url" not in str(ISSUERS[name]).lower()


def fund_config(listing):
    from dataclasses import asdict
    calendar = asdict(listing)
    calendar["valid_from"] = calendar["valid_from"].isoformat()
    calendar["known_at"] = calendar["known_at"].isoformat()
    calendar["conflict_ids"] = []
    return dict(ticker="SWDA", ISIN="IE00B4L5Y983", product_page_url=PAGE,
                slug="ishares-core-msci-world-ucits-etf", instrument_id=INSTRUMENT, calendar=calendar)


def test_configured_collection_and_duplicate_rejected(tmp_path, listing):
    fund = fund_config(listing)
    config_file(tmp_path, [fund])
    calls = []
    def fetch(url, ua):
        calls.append((url, ua, threading.current_thread().name))
        return FIXTURE.read_bytes()
    results = collect_daily(tmp_path, fetcher=fetch)
    assert results == [dict(ticker="SWDA", status="created", as_of="2026-10-20")]
    assert calls[0][:2] == (URL, "Mozilla/5.0")
    assert "ThreadPoolExecutor" in calls[0][2]
    config_file(tmp_path, [fund, fund])
    with pytest.raises(ValueError, match="duplicate product"):
        load_funds(tmp_path)


def test_missing_business_days(tmp_path, listing):
    write_snapshot(tmp_path, FIXTURE.read_bytes(), **options(listing), fetched_at=RECEIPT)
    assert gap_report(tmp_path, INSTRUMENT, start=date(2026, 10, 16), end=date(2026, 10, 21),
                      listing=listing, decision_time=RECEIPT) == ["2026-10-16", "2026-10-19", "2026-10-21"]


@pytest.mark.parametrize("mutation", [
    lambda raw: raw.replace(b"Market Currency", b"Unknown column"),
    lambda raw: raw.replace(b",Equity,", b",Unverified Bond,"),
    lambda raw: raw.replace(b'"1,234.00"', b'"-"'),
    lambda raw: raw.replace(b'"1,234.00"', b'"12,34.00"'),
    lambda raw: raw.replace(b'"20/Oct/2026"', b'"missing date"'),
])
def test_unverified_schema_and_missing_values_fail_closed(listing, mutation):
    with pytest.raises(ValueError):
        parse_ishares_csv(mutation(FIXTURE.read_bytes()), **options(listing))


def test_bond_shape_requires_explicit_configuration(listing):
    payload = FIXTURE.read_bytes().replace(b",Equity,", b",Fixed Income,")
    parsed = parse_ishares_csv(payload, **options(listing), bond_asset_classes=("Fixed Income",))
    assert parsed["holdings"][0]["asset_class"] == "Fixed Income"
    assert tuple(COLUMNS)[0] == "Ticker"


def test_historical_revision_requires_later_source_knowledge(tmp_path, listing):
    args = dict(**options(listing), fetched_at=RECEIPT, origin="historical",
                known_at="2026-10-21T10:00:00+00:00", licence_ref="synthetic manual provenance")
    write_snapshot(tmp_path, FIXTURE.read_bytes(), **args)
    revised = FIXTURE.read_bytes().replace(b"98.00", b"97.00")
    later_receipt = dict(args, fetched_at="2026-10-23T12:00:00+00:00")
    with pytest.raises(ValueError, match="source known_at must advance"):
        write_snapshot(tmp_path, revised, **later_receipt)
    result = write_snapshot(tmp_path, revised,
                            **dict(later_receipt, known_at="2026-10-22T10:00:00+00:00"))
    assert result["snapshot"]["revision"] == 2
    assert load_snapshots(tmp_path, INSTRUMENT, decision_time="2026-10-21T11:00:00+00:00")[0]["revision"] == 1
    assert load_snapshots(tmp_path, INSTRUMENT, decision_time="2026-10-22T11:00:00+00:00")[0]["revision"] == 2


def test_duplicate_security_rows_fail_closed(listing):
    raw = FIXTURE.read_bytes()
    duplicate = next(line for line in raw.splitlines() if line.startswith(b"SYN,"))
    with pytest.raises(ValueError, match="duplicate canonical holdings"):
        parse_ishares_csv(raw + duplicate + b"\n", **options(listing))


def test_politeness_spaces_starts_and_transport_shape(monkeypatch):
    from etf_cockpit.data import holdings_registry as registry
    now, starts = [10.0], []
    monkeypatch.setattr(registry, "_LAST_REQUEST", {})
    monkeypatch.setattr(registry.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(registry.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    def transport(url, **kwargs):
        starts.append(now[0])
        assert kwargs["max_redirects"] == 0 and not kwargs["allowed"](URL)
        assert kwargs["headers"]["User-Agent"] == "Mozilla/5.0"
        return FIXTURE.read_bytes(), 200, {"Content-Type": "text/plain; charset=utf-8"}
    monkeypatch.setattr(registry, "get_checked", transport)
    fetch_csv(URL, "Mozilla/5.0")
    fetch_csv(URL, "Mozilla/5.0")
    assert starts == [10.0, 11.0]
