"""Point-in-time tests for ISSUE-0186's SEC-receipt earnings features."""

from __future__ import annotations

import json
from pathlib import Path
import statistics

import pandas as pd
import pytest

from etf_cockpit.data.bitemporal import BitemporalStore
from etf_cockpit.data.earnings_surprise import (
    compute_earnings_events,
    earnings_information_features,
    record_earnings_events,
)
from etf_cockpit.features.feature_store import LocalFeatureStore
from etf_cockpit.features.panel import PITPanelInputs, build_pit_panel

FIXTURES = Path(__file__).parent / "fixtures" / "univ1_sp500"
_PRICE_COLUMNS = ["instrument_id", "date", "known_at", "adjusted_close", "is_adjusted", "currency"]
# Quarter revenue, 2019Q1 .. 2022Q2; the last quarter is filed after every decision.
_REVENUE = [100 + 5 * i + (i * i % 7) * 3 for i in range(14)]
_REVENUE[12] += 40


def _case():
    """Synthetic US issuer: 13 original quarters, an 8-K 2.02 before the 2022Q1 10-Q, a late 2022Q2."""
    rows = []
    filings = [("8-K-2022-Q1", "2022-04-28", "2022-04-28T20:05:00Z", "8-K", "2.02,9.01")]

    def filing(accn, filed, form):
        filings.append((accn, filed, filed + "T14:00:00Z", form, ""))

    def fact(accn, filed, start, end, value):
        rows.append({"start": start, "end": end, "val": value, "accn": accn, "filed": filed})

    for year in range(2019, 2023):
        base = (year - 2019) * 4
        quarters = [("Q1", "01-01", "03-31", f"{year}-05-05"), ("Q2", "04-01", "06-30", f"{year}-08-05"),
                    ("Q3", "07-01", "09-30", f"{year}-11-05")]
        for index, (name, start, end, filed) in enumerate(quarters):
            if base + index >= len(_REVENUE):
                continue
            accn = f"10Q-{year}-{name}"
            filing(accn, filed, "10-Q")
            fact(accn, filed, f"{year}-{start}", f"{year}-{end}", _REVENUE[base + index])
            if name == "Q3":
                fact(accn, filed, f"{year}-01-01", f"{year}-09-30", sum(_REVENUE[base:base + 3]))
        if base + 3 < len(_REVENUE):
            filing(f"10K-{year}", f"{year + 1}-02-25", "10-K")
            fact(f"10K-{year}", f"{year + 1}-02-25", f"{year}-01-01", f"{year}-12-31", sum(_REVENUE[base:base + 4]))
    # 2022Q1 was restated in the 2022Q2 10-Q; the SUE must keep the original value.
    rows.append({"start": "2021-01-01", "end": "2021-03-31", "val": _REVENUE[8] + 1000,
                 "accn": "10Q-2022-Q2", "filed": "2022-08-05"})
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
    submissions = {"filings": {"recent": {
        "accessionNumber": [item[0] for item in filings], "filingDate": [item[1] for item in filings],
        "acceptanceDateTime": [item[2] for item in filings], "form": [item[3] for item in filings],
        "items": [item[4] for item in filings],
    }}}
    return facts, submissions


def _prices():
    days = ["2022-04-26", "2022-04-27", "2022-04-28", "2022-04-29", "2022-05-02", "2022-05-03", "2022-05-04"]
    stock = [100.0, 100.0, 100.0, 104.0, 110.0, 111.0, 112.0]
    bench = [200.0, 200.0, 200.0, 201.0, 202.0, 203.0, 204.0]

    def frame(instrument, closes):
        return pd.DataFrame([[instrument, day, day + "T15:30:00Z", close, True, "EUR"]
                             for day, close in zip(days, closes)], columns=_PRICE_COLUMNS)

    return frame("ZZA", stock), frame("VWCE", bench)


def test_panel_sees_sec_receipt_features_only_when_available_and_never_a_late_quarter(tmp_path):
    facts, submissions = _case()
    prices, benchmark = _prices()
    result = compute_earnings_events("ZZA", facts, submissions, prices, benchmark, country="US")
    assert result["status"] == "available"
    with BitemporalStore(tmp_path / "bitemporal") as store:
        record_earnings_events(store, "ZZA", result["events"], run_id="run-1")
        record_earnings_events(store, "ZZA", result["events"], run_id="run-2")  # idempotent
        feature_store = LocalFeatureStore(tmp_path)
        features = earnings_information_features(store, feature_store, "ZZA")
    assert features["pit_grade"].eq("observed").all()
    decisions = {  # close of t, close of t+1, open after t+1, after the 10-Q, after only a late quarter existed
        "close_t": "2022-04-29T15:30:00Z", "close_t1": "2022-05-02T15:30:00Z",
        "open_after": "2022-05-03T07:00:00Z", "after_10q": "2022-05-06T15:30:00Z", "june": "2022-06-15T15:30:00Z",
    }
    membership = pd.DataFrame([{
        "instrument_id": "ZZA", "snapshot_date": stamp[:10], "snapshot_complete": True, "valid_from": "2020-01-01",
        "valid_to": None, "known_at": "2022-01-01T00:00:00Z", "pit_grade": "observed", "source": "fixture",
    } for stamp in decisions.values()])
    panel = build_pit_panel(
        list(decisions.values()), membership, ["sue_revenue", "filing_reaction_3s"], horizons=(1,),
        inputs=PITPanelInputs(feature_store, features, prices, benchmark),
    ).set_index("decision_time")
    row = {name: panel.loc[pd.Timestamp(stamp).isoformat()] for name, stamp in decisions.items()}
    # Reaction: close of t-1 (04-28) to close of t+1 (05-02), relative to VWCE.
    reaction = 110 / 100 - 1 - (202 / 200 - 1)
    # SUE: original (earliest-filed) values, up to eight prior seasonal differences, sample std.
    def sue(i):
        return (_REVENUE[i] - _REVENUE[i - 4]) / statistics.stdev([_REVENUE[j] - _REVENUE[j - 4] for j in range(max(4, i - 8), i)])

    for name in ("close_t", "close_t1"):  # the 2022Q1 event is not visible yet; 2021Q4 is
        assert row[name]["sue_revenue"] == pytest.approx(sue(11))
        assert pd.isna(row[name]["filing_reaction_3s"])
    assert row["open_after"]["filing_reaction_3s"] == pytest.approx(reaction)
    assert pd.isna(row["open_after"]["sue_revenue"])  # the 2022Q1 figure is in the 10-Q, filed 05-05
    for name in ("after_10q", "june"):  # the 2022Q2 quarter, filed in August, never shows
        assert row[name]["sue_revenue"] == pytest.approx(sue(12))
        assert row[name]["filing_reaction_3s"] == pytest.approx(reaction)
    assert row["june"]["earnings_information_available_at"] == "2022-05-05T14:00:00+00:00"


def test_an_entry_close_known_after_its_session_close_is_missing_not_replaced_by_an_earlier_close():
    facts, submissions = _case()
    prices, benchmark = _prices()
    prices.loc[prices["date"].eq("2022-04-28"), "known_at"] = "2022-04-29T07:00:00Z"  # after the XETR close of 04-28
    events = compute_earnings_events("ZZA", facts, submissions, prices, benchmark, country="US")["events"]

    reaction = {e["quarter_end"]: e["features"]["filing_reaction_3s"] for e in events}["2022-03-31"]
    assert reaction == {"status": "unavailable", "reason": "ZZA:entry_close_missing"}


@pytest.mark.parametrize("country, status, reason", [
    ("US", "available", "fewer_than_6_seasonal_differences"),
    ("Germany", "unavailable", "non_us_issuer"),
])
def test_unavailable_for_short_history_and_non_us_issuer(country, status, reason):
    facts = json.loads((FIXTURES / "CIK9000000001.json").read_text(encoding="utf-8"))
    submissions = json.loads((FIXTURES / "submissions_9000000001.json").read_text(encoding="utf-8"))
    prices, benchmark = _prices()
    result = compute_earnings_events("ZZA", facts, submissions, prices, benchmark, country=country)
    assert result["status"] == status
    if status == "available":
        sue = result["events"][0]["features"]["sue_revenue"]
        assert (sue["status"], sue["reason"], sue.get("value")) == ("unavailable", reason, None)
    else:
        assert result["reason"] == reason and result["events"] == []


def test_announcement_time_comes_only_from_the_matching_8k_release_and_stays_unavailable_otherwise(tmp_path):
    from datetime import datetime, timezone
    from etf_cockpit.data.sec_filing_documents import EightKFiling

    facts, submissions = _case()
    prices, benchmark = _prices()
    receipt = datetime(2022, 4, 28, 20, 5, tzinfo=timezone.utc)
    printed = "2022-04-28T19:55:00+00:00"

    def release(announced, accepted=receipt, accession="8-K-2022-Q1"):
        return EightKFiling(accession, "8-K", "0000777001", "2022-04-28", accepted, ("2.02", "9.01"), (),
                            announced, "explicit_in_release", "ab" * 32)

    def announcements(eight_ks):
        events = compute_earnings_events("ZZA", facts, submissions, prices, benchmark, country="US", eight_ks=eight_ks)["events"]
        return {e["quarter_end"]: e["public_announcement_time"] for e in events}

    assert announcements([release(printed)])["2022-03-31"] == printed
    assert set(announcements([release(printed)]).values()) == {printed, "unavailable"}  # only the 8-K quarter
    assert set(announcements([]).values()) == {"unavailable"}
    assert set(announcements([release(printed, accepted=receipt.replace(minute=6))]).values()) == {"unavailable"}  # other filing
    assert set(announcements([release(printed, accession="8-K-OTHER")]).values()) == {"unavailable"}  # same second, other filing
    assert set(announcements([release("unavailable")]).values()) == {"unavailable"}

    events = compute_earnings_events("ZZA", facts, submissions, prices, benchmark, country="US", eight_ks=[release(printed)])["events"]
    with BitemporalStore(tmp_path / "bitemporal") as store:
        record_earnings_events(store, "ZZA", events, run_id="run-1")
        values = [o.value for o in store.observations("earnings_information", entity_id="ZZA")]
    stored = {v["event_key"]: v["public_announcement_time"] for v in values}
    assert stored["2022-03-31"] == printed and all(v["event_definition"] == "sec_receipt" for v in values)
    assert all(v["sec_receipt_time"] != v["public_announcement_time"] for v in values)
    old_events = [{k: v for k, v in e.items() if k != "public_announcement_time"} for e in events]  # stored before INT-18
    with BitemporalStore(tmp_path / "old") as store:
        record_earnings_events(store, "ZZA", old_events, run_id="run-2")
        assert {o.value["public_announcement_time"] for o in store.observations("earnings_information", entity_id="ZZA")} == {"unavailable"}
