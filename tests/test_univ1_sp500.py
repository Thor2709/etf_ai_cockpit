"""UNIV1 offline acceptance evidence, exclusively synthetic source fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import zipfile

import pandas as pd
import pytest
import yaml

from etf_cockpit.data.sec_cik_history import map_cik
from etf_cockpit.data.sec_pit_facts import acceptance_index, fact_known_at, select_facts
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
    assert not (tmp_path / "output" / "data").exists()
