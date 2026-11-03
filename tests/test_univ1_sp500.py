"""UNIV1 offline acceptance evidence, exclusively synthetic source fixtures."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import zipfile

import pandas as pd
import pytest
import yaml

from etf_cockpit.data.sec_cik_history import map_cik
from etf_cockpit.data.sec_pit_facts import acceptance_index, fact_known_at, select_facts
from etf_cockpit.data.stock_fundamentals import PERIOD_COLUMNS, _write, append_period_rows, store_paths
from etf_cockpit.data.sp500_history import (
    build_intervals, cross_validate, intervals_from_fja, parse_fja_csv, parse_wikipedia_changes,
)
from etf_cockpit.data.universe_membership import membership_frame
from scripts import ingest_sp500
from scripts.ingest_sp500 import ingest, main

FIXTURES = Path(__file__).parent / "fixtures" / "univ1_sp500"
SPECS = {
    "us-gaap:Revenues": {"unit": "USD", "kind": "duration"},
    "dei:EntityCommonStockSharesOutstanding": {"unit": "shares", "kind": "instant"},
}


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def announcements():
    return [{"date": "2020-07-01", "ticker": ticker, "action": action,
             "known_at": "2020-06-25", "source": "synthetic announcement fixture"}
            for action, ticker in (("add", "ZZC"), ("remove", "ZZB"))]


def histories():
    snapshots = parse_fja_csv((FIXTURES / "history.csv").read_text(), date_column="date", tickers_column="tickers")
    events = parse_wikipedia_changes((FIXTURES / "changes.html").read_text(), table_id="synthetic-changes")
    baseline = {**snapshots[0], "known_at": "2019-12-31", "names": {"ZZB": "Synthetic Former Issuer"}}
    left = intervals_from_fja(snapshots, announcements(), baseline_known_at=baseline["known_at"])
    right = build_intervals(baseline, events, announcements(), source="wikipedia")
    return snapshots, events, baseline, left, right


def test_interval_building_both_sources_keeps_delisted_name():
    _, _, _, left, right = histories()
    for rows in (left, right):
        removed = [row for row in rows if row["ticker"] == "ZZB"]
        assert len(removed) == 2
        assert removed[0]["valid_to"] is None
        assert removed[0]["known_at"] == "2019-12-31T23:59:59.999999+00:00"
        assert removed[1]["valid_to"] == "2020-07-01"
        assert removed[1]["known_at"] == "2020-06-25T23:59:59.999999+00:00"
        assert any(row["ticker"] == "ZZC" and row["valid_from"] == "2020-07-01" for row in rows)
    assert cross_validate(left, right) == []


def test_disagreement_reported_instead_of_silent_merge():
    _, _, _, left, right = histories()
    different = deepcopy(right)
    different[-1]["valid_from"] = "2020-07-02"
    disagreements = cross_validate(left, different)
    assert {row["only_in"] for row in disagreements} == {"fja05680", "wikipedia"}
    assert len(disagreements) == 2


def test_missing_announcement_never_uses_effective_date_as_known_at():
    snapshots, _, _, _, _ = histories()
    with pytest.raises(ValueError, match="announcement"):
        intervals_from_fja(snapshots, [], baseline_known_at="2019-12-31")


def test_conservative_change_without_announcement_is_known_at_effective_date_start():
    snapshots, _, _, _, _ = histories()
    provenance = []
    rows = intervals_from_fja(snapshots, [], baseline_known_at="2019-12-31",
                              announcement_policy="effective_date_conservative", provenance=provenance)
    changes = [row for row in rows if row["valid_from"] == "2020-07-01" or row["valid_to"]]
    assert len(changes) == len(provenance) == 2
    assert {row["known_at"] for row in changes} == {"2020-07-01T00:00:00+00:00"}
    assert all(datetime.fromisoformat(row["known_at"]) >= datetime.fromisoformat("2020-07-01T00:00:00+00:00")
               for row in changes)
    assert {row["provenance"] for row in provenance} == {
        "known_at=effective_date (conservative, no announcement evidence)"}
    assert all(row["announcement_source"] is None for row in provenance)


@pytest.mark.parametrize("stamp,expected,sourced", [
    ("2020-06-25", "2020-06-25T23:59:59.999999+00:00", True),
    ("2020-07-01T00:00:00Z", "2020-07-01T00:00:00+00:00", False),
    ("2020-07-01T12:00:00Z", "2020-07-01T00:00:00+00:00", False),
    ("2020-07-02", "2020-07-01T00:00:00+00:00", False),
])
def test_conservative_policy_only_earlier_sourced_announcement_wins(stamp, expected, sourced):
    snapshots, _, _, _, _ = histories()
    evidence = [{**row, "known_at": stamp} for row in announcements()]
    provenance = []
    rows = intervals_from_fja(snapshots, evidence, baseline_known_at="2019-12-31",
                              announcement_policy="effective_date_conservative", provenance=provenance)
    assert {row["known_at"] for row in rows if row["valid_from"] == "2020-07-01" or row["valid_to"]} == {expected}
    assert all(bool(row["announcement_source"]) == sourced for row in provenance)
    if sourced:
        # The exit is already announced when a later baseline is observed.
        # Baseline membership itself must never become known before observation.
        baseline = {"date": "2020-06-30", "known_at": "2020-06-30T00:00:00+00:00", "tickers": ["ZZA", "ZZB"]}
        _, events, _, _, _ = histories()
        observed = build_intervals(baseline, events, evidence, source="fja05680",
                                   announcement_policy="effective_date_conservative")
        assert [row for row in observed if row["ticker"] == "ZZB"] == [{
            "ticker": "ZZB", "valid_from": "2020-06-30", "valid_to": "2020-07-01", "source": "fja05680",
            "known_at": "2020-06-30T00:00:00+00:00", "name": "Synthetic Former Issuer"}]
        with pytest.raises(ValueError, match="exit revision"):
            build_intervals(baseline, events, evidence, source="fja05680")
    with pytest.raises(ValueError, match="evidence source"):
        intervals_from_fja(snapshots, [{**evidence[0], "source": ""}], baseline_known_at="2019-12-31",
                           announcement_policy="effective_date_conservative")
    with pytest.raises(ValueError, match="announcement_policy"):
        intervals_from_fja(snapshots, [], baseline_known_at="2019-12-31", announcement_policy="guess")


@pytest.mark.parametrize("bad", ["unrecognised", "date,wrong\n2020-01-01,ZZA\n"])
def test_unverified_csv_shape_fails_closed(bad):
    with pytest.raises(ValueError, match="header"):
        parse_fja_csv(bad, date_column="date", tickers_column="tickers")


def test_live_wikipedia_shape_with_refs_column_and_pipe_artefact_parses():
    events = parse_wikipedia_changes((FIXTURES / "changes_live_shape.html").read_text(), table_id="changes")
    assert [(row["date"], row["action"], row["ticker"]) for row in events] == [
        ("2020-03-03", "add", "ZZD"), ("2020-07-01", "add", "ZZC"), ("2020-07-01", "remove", "ZZB")]
    bad = (FIXTURES / "changes_live_shape.html").read_text().replace("Refs</th>", "Sources</th>")
    with pytest.raises(ValueError, match="header"):
        parse_wikipedia_changes(bad, table_id="changes")


def test_unverified_wikipedia_shape_fails_closed():
    with pytest.raises(ValueError, match="header"):
        parse_wikipedia_changes((FIXTURES / "changes.html").read_text().replace("Removed", "Deleted"),
                                table_id="synthetic-changes")


def facts(as_of, payload=None, submissions=None, **kwargs):
    return select_facts(payload or load("CIK9000000001.json"), as_of, specs=SPECS,
                        submissions=submissions or load("submissions_9000000001.json"),
                        historical_pages=[load("CIK9000000001-submissions-001.json")], **kwargs)


def revenue(rows, fp):
    return next(row for row in rows if row["tag"] == "us-gaap:Revenues" and row["fp"] == fp)


def test_asof_original_before_restatement_and_restated_after_no_future_facts():
    before = facts("2021-03-01T12:00:00Z")
    after = facts("2021-06-01T12:00:00Z")
    assert revenue(before, "FY")["val"] == 100
    assert revenue(after, "FY")["val"] == 110
    assert revenue(before, "Q4")["val"] == 30
    assert revenue(after, "Q4")["val"] == 40
    assert all(row["filed"] <= "2021-03-01" for row in before)
    assert all(row["known_at"] <= "2021-03-01T12:00:00+00:00" for row in before)
    assert not any(row["fp"] == "FY" for row in facts("2021-02-19T22:32:00Z"))
    # Removing or changing frame must have no effect on point-in-time selection.
    changed = load("CIK9000000001.json")
    for row in changed["facts"]["us-gaap"]["Revenues"]["units"]["USD"]:
        row["frame"] = "synthetic-irrelevant-frame"
    assert facts("2021-06-01T12:00:00Z", payload=changed) == after
    shares = next(row for row in before if row["tag"].startswith("dei:"))
    assert shares["val"] == 20 and shares["known_at"] == "2021-02-20T05:00:00+00:00"


def test_acceptance_after_1730_et_next_day_known_at_and_dst():
    index = acceptance_index(load("submissions_9000000001.json"))
    original = load("CIK9000000001.json")["facts"]["us-gaap"]["Revenues"]["units"]["USD"][1]
    assert fact_known_at(original, index) == "2021-02-20T05:00:00+00:00"
    row = {**original, "filed": "2021-07-02", "accn": "synthetic-summer"}
    accepted = {row["accn"]: {"filed": row["filed"], "accepted": "2021-07-02T21:30:01+00:00"}}
    assert fact_known_at(row, accepted) == "2021-07-03T04:00:00+00:00"
    accepted[row["accn"]]["accepted"] = "2021-07-02T21:30:00+00:00"
    assert fact_known_at(row, accepted) == "2021-07-02T21:30:00+00:00"


def test_date_only_filed_conservative_and_strict_acceptance_mode():
    payload = load("CIK9000000001.json")
    row = payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"][1]
    assert fact_known_at(row, {}) == "2021-02-20T04:59:59.999999+00:00"
    with pytest.raises(ValueError, match="acceptanceDateTime unavailable"):
        fact_known_at(row, {}, require_acceptance=True)


@pytest.mark.parametrize("mutation,match", [
    ("unit", "unit mismatch"), ("duration", "duration mismatch"),
    ("missing_filed", "provable"), ("ambiguous", "conflicting"),
])
def test_invalid_fact_evidence_fails_closed(mutation, match):
    payload = load("CIK9000000001.json")
    units = payload["facts"]["us-gaap"]["Revenues"]["units"]
    if mutation == "unit":
        units["EUR"] = units.pop("USD")
    elif mutation == "duration":
        units["USD"][1]["start"] = "2020-11-01"
    elif mutation == "missing_filed":
        del units["USD"][1]["filed"]
    else:
        units["USD"].append({**units["USD"][1], "val": 999})
    with pytest.raises(ValueError, match=match):
        facts("2021-03-01T12:00:00Z", payload=payload)


def test_live_shape_quarter_and_ytd_share_end_and_fp_without_conflict():
    payload = load("CIK9000000001.json")
    units = payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    # A 10-Q reports the 3-month and the year-to-date value under the same end/fp.
    units += [{"start": "2020-07-01", "end": "2020-09-30", "val": 25, "accn": "synthetic-nine-a", "filed": "2020-11-02", "fp": "Q3", "fy": 2020}]
    rows = [row for row in facts("2021-03-01T12:00:00Z", payload=payload, derive_q4=False)
            if row["tag"] == "us-gaap:Revenues" and row["fp"] == "Q3"]
    assert sorted((row["start"], row["val"]) for row in rows) == [("2020-01-01", 70), ("2020-07-01", 25)]


def test_skip_policy_counts_unprovable_facts_but_default_still_raises():
    payload = load("CIK9000000001.json")
    # Live 8-K/prospectus facts carry no fp; a zero share count is also unusable.
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        {"start": "2020-01-01", "end": "2020-12-31", "val": 1, "accn": "synthetic-8k", "filed": "2021-02-25", "fp": None})
    payload["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"].append(
        {"end": "2021-02-10", "val": 0, "accn": "synthetic-zero", "filed": "2021-02-25", "fp": "FY", "fy": 2020})
    with pytest.raises(ValueError, match="unsupported fact fp"):
        facts("2021-03-01T12:00:00Z", payload=payload)
    skipped = {}
    rows = facts("2021-03-01T12:00:00Z", payload=payload, skipped=skipped)
    assert skipped == {"nonpositive_shares": 1, "unsupported_fp": 1}
    assert revenue(rows, "FY")["val"] == 100


def test_q4_needs_both_legs_and_matching_start():
    payload = load("CIK9000000001.json")
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"].pop(0)
    assert not any(row["fp"] == "Q4" for row in facts("2021-03-01T12:00:00Z", payload=payload))
    payload = load("CIK9000000001.json")
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["start"] = "2020-01-02"
    assert not any(row["fp"] == "Q4" for row in facts("2021-03-01T12:00:00Z", payload=payload))


def test_unmapped_delisted_ticker_stays_unmapped_and_current_not_backdated():
    kwargs = {"company_tickers": load("company_tickers.json"),
              "submissions": [load("submissions_9000000002.json")], "observed_at": "2022-01-01"}
    unknown = map_cik("ZZB", "2020-01-01", "2020-07-01", **kwargs)
    assert unknown["status"] == "unmapped" and unknown["cik"] is None
    current_in_past = map_cik("ZZC", "2020-07-01", None, **kwargs)
    assert current_in_past["status"] == "unmapped"
    # An exact name + a fully bounded historical window can identify the issuer.
    former = map_cik("ZZB", "2020-01-01", "2020-06-30", security_name="Synthetic Former Issuer", **kwargs)
    assert former["cik"] == "9000000002"
    assert former["known_at"] == "2022-01-01T23:59:59.999999+00:00"


def test_conflicting_dated_ciks_remain_unmapped():
    binding = {"ticker": "ZZB", "valid_from": "2020-01-01", "valid_to": "2020-07-01",
               "cik": "9000000002", "known_at": "2019-12-31", "source": "synthetic binding"}
    result = map_cik("ZZB", "2020-01-01", "2020-07-01", company_tickers={}, submissions=[],
                     observed_at="2022-01-01", bindings=[binding, {**binding, "cik": "9000000001"}])
    assert result["status"] == "unmapped" and result["reason"] == "ambiguous_cik"


def ingest_config(tmp_path):
    config = yaml.safe_load((FIXTURES.parents[2] / "configs" / "sp500_universe_v1.yaml").read_text())
    companyfacts, submissions = tmp_path / "companyfacts.zip", tmp_path / "submissions.zip"
    with zipfile.ZipFile(companyfacts, "w") as archive:
        for cik in ("9000000001", "9000000002"):
            archive.writestr(f"CIK{cik}.json", (FIXTURES / f"CIK{cik}.json").read_bytes())
    with zipfile.ZipFile(submissions, "w") as archive:
        for cik in ("9000000001", "9000000002"):
            archive.writestr(f"CIK{cik}.json", (FIXTURES / f"submissions_{cik}.json").read_bytes())
        archive.writestr("CIK9000000001-submissions-001.json", (FIXTURES / "CIK9000000001-submissions-001.json").read_bytes())
    config.update(history_csv=str(FIXTURES / "history.csv"), wikipedia_html=str(FIXTURES / "changes.html"),
                  company_tickers=str(FIXTURES / "company_tickers.json"), companyfacts=str(companyfacts),
                  submissions=str(submissions), as_of="2021-06-01T12:00:00Z", identity_observed_at="2022-01-01",
                  baseline_known_at="2019-12-31", baseline_names={"ZZB": "Synthetic Former Issuer"},
                  baseline_source="synthetic baseline observation",
                  wikipedia_baseline={"date": "2020-01-01", "known_at": "2019-12-31",
                                      "source": "synthetic independent Wikipedia baseline",
                                      "tickers": ["ZZA", "ZZB"], "names": {"ZZB": "Synthetic Former Issuer"}},
                  csv_shape={"date_column": "date", "tickers_column": "tickers"}, wikipedia_table_id="synthetic-changes",
                  announcements=announcements(), licence_ref="synthetic fixture; no real membership data")
    for ticker, cik, instrument_id, start, end in (
        ("ZZA", "9000000001", "synthetic-instrument-a", "2020-01-01", None),
        ("ZZB", "9000000002", "synthetic-instrument-b", "2020-01-01", "2020-07-01"),
        ("ZZC", "9000000002", "synthetic-instrument-b", "2020-07-01", None),
    ):
        common = {"ticker": ticker, "valid_from": start, "valid_to": end,
                  "known_at": "2019-12-01", "source": "synthetic identity fixture"}
        config["cik_bindings"].append({**common, "cik": cik})
        config["instrument_bindings"].append({**common, "instrument_id": instrument_id})
    return config


def membership_rows(root):
    with sqlite3.connect(root / "data" / "derived" / "universe_membership" / "membership.sqlite") as connection:
        return connection.execute("SELECT scope,instrument_id,valid_from,valid_to,known_at,snapshot_date,complete "
                                  "FROM licensed_history ORDER BY instrument_id,valid_from,known_at").fetchall()


def test_history_start_uses_latest_dated_fja_snapshot_and_omits_earlier_changes(tmp_path):
    config = ingest_config(tmp_path)
    history = tmp_path / "history.csv"
    history.write_text('date,tickers\n2019-01-01,"ZZQ"\n2020-01-01,"ZZA,ZZB"\n2020-07-01,"ZZA,ZZC"\n')
    config.update(history_csv=str(history), history_start="2020-02-01", baseline_known_at="2026-11-02",
                  announcement_policy="effective_date_conservative", announcements=[], cross_validation="report")
    root = tmp_path / "output"
    report = ingest(config, root=root, workers=1)
    assert report["status"] == "complete", report
    baseline = report["history_baseline"]
    assert baseline["snapshot_date"] == "2020-01-01"
    assert baseline["known_at"] == "2020-01-01T00:00:00+00:00"
    rows = membership_rows(root)
    assert min(row[2] for row in rows) == "2020-02-01"
    assert {row[4] for row in rows if row[2] == "2020-02-01" and row[3] is None} == {
        "2020-01-01T00:00:00.000000Z"}
    assert {(row["date"], row["ticker"]) for row in report["membership_provenance"]} == {
        ("2020-07-01", "ZZB"), ("2020-07-01", "ZZC")}
    # A former member remains in the ledger, including its open and closed revisions.
    former = [row for row in rows if row[1] == "synthetic-instrument-b" and row[2] == "2020-02-01"]
    assert [row[3] for row in former] == [None, "2020-07-01"]
    with pytest.raises(ValueError, match="no fja snapshot"):
        ingest({**config, "history_start": "2018-01-01"}, root=tmp_path / "bad", workers=1)


def test_parallel_ingestion_equals_serial_and_resume(tmp_path):
    config = ingest_config(tmp_path)
    serial, parallel = tmp_path / "serial", tmp_path / "parallel"
    a = ingest(config, root=serial, workers=1)
    b = ingest(config, root=parallel, workers=2)
    assert a["status"] == "complete", a
    assert b == a
    path = Path("data/clean/stock_fundamentals.parquet")
    first = pd.read_parquet(serial / path)
    pd.testing.assert_frame_equal(first, pd.read_parquet(parallel / path))
    memberships = membership_rows(serial)
    assert membership_rows(parallel) == memberships
    assert any(row[3] == "2020-07-01" for row in memberships)
    rows = first[(first.instrument_id == "synthetic-instrument-a") & (first.period_type == "FY")]
    assert rows.revenue.tolist() == [100, 110]
    assert first[first.period_type == "SHARES"].shares_outstanding.tolist() == [20, 30]
    assert ingest(config, root=serial, workers=1) == a
    pd.testing.assert_frame_equal(first, pd.read_parquet(serial / path))
    assert membership_rows(serial) == memberships


def _fundamental_fact(known_at, revenue, *, instrument_id="synthetic-instrument-a"):
    row = {column: None for column in PERIOD_COLUMNS}
    row.update(instrument_id=instrument_id, period_end="2020-12-31", period_type="FY", fiscal_year=2020,
               currency="USD", source="sec", source_ref="synthetic filing", known_at=known_at,
               available_at=known_at, revenue=revenue)
    return row


def test_batch_fundamentals_match_legacy_vintage_rows_with_restatements_and_suppression():
    instrument_id = "synthetic-instrument-a"
    existing = pd.DataFrame([
        _fundamental_fact("2019-01-01T00:00:00+00:00", 90),
        _fundamental_fact("2020-01-01T00:00:00+00:00", 100),
        _fundamental_fact("2022-01-01T00:00:00+00:00", 110),
    ], columns=PERIOD_COLUMNS)
    rows = [
        _fundamental_fact("2021-01-01T00:00:00+00:00", 100),  # suppressed before later restatement
        _fundamental_fact("2022-01-01T00:00:00+00:00", 110),  # existing digest
        _fundamental_fact("2023-01-01T00:00:00+00:00", 110),  # suppressed after restatement
        _fundamental_fact("2024-01-01T00:00:00+00:00", 115),
        _fundamental_fact("2025-01-01T00:00:00+00:00", 115),  # suppressed unchanged vintage
    ]
    legacy = existing.copy()
    digests = {ingest_sp500._fingerprint(row) for row in existing.to_dict("records")}
    identities = {}

    def identity(row):
        return tuple(str(row.get(key)) for key in ("period_end", "period_type", "source", "known_at"))

    for row in existing.to_dict("records"):
        identities.setdefault(identity(row), set()).add(ingest_sp500._fingerprint(row))
    for raw in sorted(rows, key=lambda item: (item["known_at"], item["period_end"], item["period_type"], item["source"])):
        row = {**raw, "instrument_id": instrument_id}
        digest = ingest_sp500._fingerprint(row)
        if digest in digests:
            continue
        if identity(row) in identities and digest not in identities[identity(row)]:
            raise AssertionError("fixture unexpectedly conflicts with stored vintage")
        visible = legacy[legacy["known_at"].astype(str) <= raw["known_at"]]
        candidate, added = append_period_rows(visible, instrument_id, [raw])
        if added:
            digests.add(digest)
            legacy = pd.concat([legacy, candidate.tail(added)], ignore_index=True)

    additions = ingest_sp500._pending_facts(existing, instrument_id, rows)
    batched = pd.concat([existing, pd.DataFrame(additions, columns=PERIOD_COLUMNS)], ignore_index=True)
    sort_columns = ["instrument_id", "known_at", "period_end", "period_type", "source"]
    pd.testing.assert_frame_equal(
        legacy[PERIOD_COLUMNS].sort_values(sort_columns, kind="mergesort").reset_index(drop=True),
        batched[PERIOD_COLUMNS].sort_values(sort_columns, kind="mergesort").reset_index(drop=True),
    )


def test_partial_fundamentals_store_resumes_to_clean_store(tmp_path):
    config = ingest_config(tmp_path)
    clean_root, partial_root = tmp_path / "clean", tmp_path / "partial"
    clean_report = ingest(config, root=clean_root, workers=1)
    assert clean_report["status"] == "complete", clean_report
    path = Path("data/clean/stock_fundamentals.parquet")
    clean = pd.read_parquet(clean_root / path)
    first_instrument = clean.iloc[0]["instrument_id"]
    _write(store_paths(partial_root)["periods"], clean[clean["instrument_id"] == first_instrument])

    resumed = ingest(config, root=partial_root, workers=2)
    assert resumed["status"] == "complete", resumed
    actual = pd.read_parquet(partial_root / path)
    pd.testing.assert_frame_equal(clean, actual)


def test_changed_fundamental_at_existing_known_at_still_raises():
    existing = pd.DataFrame([_fundamental_fact("2020-01-01T00:00:00+00:00", 100)], columns=PERIOD_COLUMNS)
    changed = _fundamental_fact("2020-01-01T00:00:00+00:00", 101)
    with pytest.raises(ValueError, match="changed fundamentals at existing known_at"):
        ingest_sp500._pending_facts(existing, "synthetic-instrument-a", [changed])


def test_ingestion_persists_membership_through_store(tmp_path):
    config = ingest_config(tmp_path)
    root = tmp_path / "output"
    report = ingest(config, root=root, workers=1)
    assert report["status"] == "complete", report
    assert config["scope"] == "listing:sp500:all"
    assert {row[0] for row in membership_rows(root)} == {"listing:sp500:all"}
    before = membership_frame("listing:sp500:all", "2020-06-01T12:00:00Z", root=root)
    assert set(before.instrument_id) == {"synthetic-instrument-a", "synthetic-instrument-b"}
    assert before.valid_to.isna().all()
    after = membership_frame("listing:sp500:all", config["as_of"], root=root)
    removed = after[(after.instrument_id == "synthetic-instrument-b") & (after.valid_from == "2020-01-01")]
    assert removed.valid_to.tolist() == ["2020-07-01"]
    assert len(after) == 3
    assert membership_frame("listing:stoxx600:all", config["as_of"], root=root).empty


@pytest.mark.parametrize("fail_on", [1, 2])
def test_membership_failure_leaves_no_issuer_fundamentals(tmp_path, monkeypatch, fail_on):
    config = ingest_config(tmp_path)
    # Keep one issuer so a later revision can fail after a real membership write.
    config["cik_bindings"] = [row for row in config["cik_bindings"] if row["ticker"] != "ZZA"]
    root = tmp_path / "output"
    original = ingest_sp500.import_licensed_history
    calls = 0

    def fail_membership(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_on:
            raise OSError("synthetic membership write failure")
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ingest_sp500, "import_licensed_history", fail_membership)
        report = ingest(config, root=root, workers=1)
    assert calls == fail_on
    assert report["status"] == "partial"
    assert len(report["issuers"]) == 1
    assert report["issuers"][0]["status"] == "failed"
    assert "synthetic membership write failure" in report["issuers"][0]["reason"]
    assert not (root / "data/clean/stock_fundamentals.parquet").exists()
    # Resume must tolerate the membership revision committed before the failure.
    resumed = ingest(config, root=root, workers=1)
    assert resumed["issuers"][0]["status"] == "ingested", resumed
    assert (root / "data/clean/stock_fundamentals.parquet").exists()


def test_disagreement_blocks_all_store_writes(tmp_path):
    config = ingest_config(tmp_path)
    changed = tmp_path / "different.html"
    changed.write_text((FIXTURES / "changes.html").read_text().replace("July 1, 2020", "July 2, 2020"))
    config["wikipedia_html"] = str(changed)
    config["announcements"] += [{**row, "date": "2020-07-02"} for row in announcements()]
    root = tmp_path / "blocked"
    report = ingest(config, root=root, workers=1)
    assert report["status"] == "blocked" and report["disagreements"]
    assert not (root / "data").exists()


def test_report_mode_publishes_fja_history_and_lists_disagreements_but_default_blocks(tmp_path):
    config = ingest_config(tmp_path)
    changed = tmp_path / "different.html"
    changed.write_text((FIXTURES / "changes.html").read_text().replace("July 1, 2020", "June 30, 2020"))
    config["wikipedia_html"] = str(changed)
    config["announcements"] += [{**row, "date": "2020-06-30"} for row in announcements()]
    assert ingest(config, root=tmp_path / "blocked", workers=1)["status"] == "blocked"
    config.update(cross_validation="report", wikipedia_baseline={})
    root = tmp_path / "report"
    report = ingest(config, root=root, workers=1)
    assert report["status"] == "complete" and report["cross_validation"] == "report"
    assert {(row["only_in"], row["date"]) for row in report["disagreements"]} == {
        ("fja05680", "2020-07-01"), ("wikipedia", "2020-06-30")}
    assert report["wikipedia_events_after_history"] == []
    assert any(row[3] == "2020-07-01" for row in membership_rows(root))
    config["cross_validation"] = "silent"
    with pytest.raises(ValueError, match="cross_validation"):
        ingest(config, root=tmp_path / "bad", workers=1)


def test_report_mode_extends_history_with_wikipedia_changes_after_last_snapshot(tmp_path):
    config = ingest_config(tmp_path)
    later = tmp_path / "later.html"
    later.write_text((FIXTURES / "changes.html").read_text().replace(
        "</table>", "<tr><td>August 3, 2020</td><td>ZZE</td><td>Synthetic Later Issuer</td><td>ZZC</td>"
        "<td>Synthetic Renamed Issuer</td><td>later</td></tr></table>"))
    config.update(wikipedia_html=str(later), cross_validation="report", wikipedia_baseline={},
                  announcements=announcements() + [{**row, "date": "2020-08-03", "known_at": "2020-08-03", "ticker": "ZZE" if row["action"] == "add" else "ZZC"}
                                                   for row in announcements()])
    root = tmp_path / "extended"
    report = ingest(config, root=root, workers=1)
    assert {(row["action"], row["ticker"]) for row in report["wikipedia_events_after_history"]} == {("add", "ZZE"), ("remove", "ZZC")}
    assert report["disagreements"] == []
    assert any(row[2] == "2020-07-01" and row[3] == "2020-08-03" for row in membership_rows(root))
    assert any(item["ticker"] == "ZZE" for item in report["unmapped"])
    assert {row["source"] for row in report["membership_provenance"] if row["date"] == "2020-08-03"} == {"wikipedia"}


def test_ingest_skip_policy_reports_skipped_facts_and_rejects_unknown_policy(tmp_path):
    config = ingest_config(tmp_path)
    payload = json.loads((FIXTURES / "CIK9000000001.json").read_text())
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        {"start": "2020-01-01", "end": "2020-12-31", "val": 1, "accn": "synthetic-8k", "filed": "2021-02-25", "fp": None})
    path = Path(config["companyfacts"])
    path.unlink()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("CIK9000000001.json", json.dumps(payload))
        archive.writestr("CIK9000000002.json", (FIXTURES / "CIK9000000002.json").read_bytes())
    assert ingest(config, root=tmp_path / "strict", workers=1)["status"] == "partial"
    config["invalid_fact_policy"] = "skip"
    report = ingest(config, root=tmp_path / "skip", workers=1)
    assert report["status"] == "complete", report
    assert [item["skipped_facts"] for item in report["issuers"] if item["cik"] == "9000000001"] == [{"unsupported_fp": 1}]
    config["invalid_fact_policy"] = "maybe"
    assert ingest(config, root=tmp_path / "bad", workers=1)["status"] == "partial"


def test_cli_report_unmapped_and_missing_issuer_fail_closed(tmp_path):
    config = ingest_config(tmp_path)
    config["cik_bindings"] = []
    cfg, report = tmp_path / "run.yaml", tmp_path / "report.json"
    cfg.write_text(yaml.safe_dump(config))
    assert main(["--config", str(cfg), "--root", str(tmp_path / "output"), "--workers", "1", "--report", str(report)]) == 1
    result = json.loads(report.read_text())
    assert result["execution_allowed"] is False
    assert result["unmapped"] and result["status"] == "partial"
    coverage = pd.read_parquet(tmp_path / "output/data/derived/universe_membership/index_coverage.parquet")
    assert len(coverage) == 3 and set(coverage.binding_status) == {"unbound"}
    assert not (tmp_path / "output/data/derived/universe_membership/membership.sqlite").exists()


def test_cover_config_coverage_exact_columns_bound_and_unbound_scope_replacement(tmp_path):
    config = ingest_config(tmp_path)
    config["identity_policy"] = "sec_cover_v1"
    config["cik_bindings"] = [r for r in config["cik_bindings"] if r["ticker"] != "ZZB"]
    config["identity_unbound"] = [{"ticker": "ZZB", "valid_from": "2020-01-01", "reason": "no_cover_identity_for_window"}]
    root = tmp_path / "output"
    report = ingest(config, root=root, workers=1)
    path = root / "data/derived/universe_membership/index_coverage.parquet"
    frame = pd.read_parquet(path)
    assert list(frame.columns) == ["scope", "source_ticker", "instrument_id", "valid_from", "valid_to", "member_known_at",
                                   "identity_known_at", "binding_status", "reason"]
    assert len(frame) == 3 and set(frame.binding_status) == {"bound", "unbound"}
    missing = frame.loc[frame.source_ticker == "ZZB"].iloc[0]
    assert pd.isna(missing.instrument_id) and missing.valid_to == "2020-07-01"
    assert missing.reason == "no_cover_identity_for_window" and pd.isna(missing.identity_known_at)
    assert report["coverage"]["by_reason"]["no_cover_identity_for_window"] == {"intervals": 1, "member_days": 182}
    assert all("2022" not in r[4] for r in membership_rows(root))
    other = {**config, "scope": "listing:synthetic:all"}
    ingest(other, root=root, workers=1)
    ingest(config, root=root, workers=1)
    updated = pd.read_parquet(path)
    assert len(updated) == 6 and set(updated.scope) == {config["scope"], other["scope"]}
    pd.testing.assert_frame_equal(frame, updated.loc[updated.scope == config["scope"]].reset_index(drop=True))


def test_closed_interval_and_reentry_keep_entry_exit_revisions(tmp_path):
    config = ingest_config(tmp_path)
    history = tmp_path / "reentry.csv"
    history.write_text('date,tickers\n2020-01-01,"ZZA,ZZB"\n2020-07-01,"ZZA,ZZC"\n'
                       '2020-08-01,"ZZC"\n2020-09-01,"ZZA,ZZC"\n')
    config.update(history_csv=str(history), cross_validation="report", identity_policy="sec_cover_v1",
                  announcement_policy="effective_date_conservative", announcements=[])
    root = tmp_path / "output"
    report = ingest(config, root=root, workers=1)
    assert report["status"] == "complete", report
    rows = [r for r in membership_rows(root) if r[1] == "synthetic-instrument-a"]
    assert [(r[2], r[3]) for r in rows] == [("2020-01-01", None), ("2020-01-01", "2020-08-01"), ("2020-09-01", None)]
    assert rows[0][4] != rows[1][4] != rows[2][4]
    frame = pd.read_parquet(root / "data/derived/universe_membership/index_coverage.parquet")
    assert len(frame.loc[frame.source_ticker == "ZZA"]) == 2


def test_distinct_filing_vintages_one_period_kept_even_when_value_unchanged(tmp_path):
    config = ingest_config(tmp_path)
    payload = json.loads((FIXTURES / "CIK9000000001.json").read_text())
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"][-1]["val"] = 100
    archive = tmp_path / "unchanged.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("CIK9000000001.json", json.dumps(payload))
        out.writestr("CIK9000000002.json", (FIXTURES / "CIK9000000002.json").read_bytes())
    config.update(companyfacts=str(archive), identity_policy="sec_cover_v1")
    root = tmp_path / "output"
    report = ingest(config, root=root, workers=1)
    assert report["status"] == "complete", report
    frame = pd.read_parquet(root / "data/clean/stock_fundamentals.parquet")
    vintages = frame.loc[(frame.instrument_id == "synthetic-instrument-a") & (frame.period_type == "FY")]
    assert vintages.revenue.tolist() == [100, 100]
    assert vintages.known_at.nunique() == 2 and vintages.source_ref.nunique() == 2
    assert vintages.known_at.str.startswith("2021").all()
    before = frame.copy()
    assert ingest(config, root=root, workers=1)["status"] == "complete"
    pd.testing.assert_frame_equal(before, pd.read_parquet(root / "data/clean/stock_fundamentals.parquet"))


def test_reingest_earlier_identity_knowledge_still_rejected_by_ledger(tmp_path):
    config = ingest_config(tmp_path)
    later = deepcopy(config)
    for binding in later["cik_bindings"] + later["instrument_bindings"]:
        binding["known_at"] = "2021-04-01T00:00:00Z"
    root = tmp_path / "output"
    assert ingest(later, root=root, workers=1)["status"] == "complete"
    checkpoint = membership_rows(root)
    report = ingest(config, root=root, workers=1)
    assert report["status"] == "partial"
    assert all(r["status"] == "failed" and "changed/backdated membership knowledge" in r["reason"] for r in report["issuers"])
    assert membership_rows(root) == checkpoint


def test_today_only_identity_stays_invisible_historically(tmp_path):
    config = ingest_config(tmp_path)
    for row in config["cik_bindings"] + config["instrument_bindings"]:
        row["known_at"] = "2021-05-15T12:00:00Z"
    root = tmp_path / "output"
    assert ingest(config, root=root, workers=1)["status"] == "complete"
    assert membership_frame(config["scope"], "2021-05-01T00:00:00Z", root=root).empty
    frame = pd.read_parquet(root / "data/clean/stock_fundamentals.parquet")
    assert set(frame.known_at) == {"2021-05-15T12:00:00+00:00"}


def test_cover_mode_late_or_invalid_evidence_is_unbound(tmp_path):
    config = ingest_config(tmp_path)
    config["identity_policy"] = "sec_cover_v1"
    config["cik_bindings"][0]["known_at"] = "2020-02-01T12:00:00Z"
    config["instrument_bindings"][1].pop("known_at")
    report = ingest(config, root=tmp_path / "output", workers=1)
    assert {r["reason"] for r in report["unmapped"]} == {"cover_evidence_after_window_start", "invalid_identity_evidence"}
