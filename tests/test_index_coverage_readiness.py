"""Synthetic index cohorts test omitted members independently of admitted scores."""

from dataclasses import replace

import pandas as pd
import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.data.replay_membership import ListingHistory, OBSERVED_TRADING_STATUS
from etf_cockpit.portfolio import paper_bots_readiness as gate
from tests.test_fix_READY_20261023 import DAYS, END, START, _inputs, _thresholds


def _coverage_inputs(covered=18):
    inputs = _inputs()
    rows = []
    for index in range(20):
        rows.append({
            "scope": "listing:sp500:all", "source_ticker": f"SRC{index}",
            "instrument_id": f"MEMBER{index}" if index < 19 or covered == 20 else None,
            "valid_from": "2020-01-01", "valid_to": None,
            "member_known_at": "2020-01-01T00:00:00+00:00",
            "identity_known_at": "2020-01-01T00:00:00+00:00" if index < 19 or covered == 20 else None,
            "binding_status": "bound" if index < 19 or covered == 20 else "unbound",
            "reason": "synthetic fixture",
        })
    inputs.index_coverage = pd.DataFrame(rows)
    extra = pd.DataFrame([
        {"etf_id": f"MEMBER{index}", "date": day, "close": 100.0, "adjusted_close": 100.0,
         "currency": "EUR", "source": "yfinance"}
        for index in range(covered) for day in DAYS
    ])
    inputs.prices = pd.concat([inputs.prices, extra], ignore_index=True)
    return inputs


def _check(inputs, day=START, thresholds=None):
    report = gate.evaluate_readiness(inputs, day, day, thresholds or _thresholds(), every=1)
    assert len(report.dates) == 1
    return report.dates[0].checks["index_coverage"]


def test_coverage_below_threshold_fails_with_omitted_member_counts():
    inputs = _coverage_inputs(18)
    result = _check(inputs)
    assert not result.passed
    assert result.counts == {"members": 20, "covered": 18, "unbound": 1, "no_price": 1, "identity_unavailable": 0}
    assert "90.0%" in result.detail and "95.0%" in result.detail
    report = gate.evaluate_readiness(inputs, START, END, _thresholds())
    assert report.summary()["failed_by_check"]["index_coverage"] == len(report.dates)
    assert "members=20, covered=18, unbound=1, no_price=1" in report.format_text()


@pytest.mark.parametrize("covered", [19, 20])
def test_coverage_at_or_above_threshold_passes(covered):
    inputs = _coverage_inputs(covered)
    result = _check(inputs)
    assert result.passed and result.counts["covered"] == covered and result.counts["members"] == 20
    assert result.counts["no_price"] == 0
    report = gate.evaluate_readiness(inputs, START, END, _thresholds())
    assert report.passed and "index_coverage: ok - members=20" in report.format_text()


def test_missing_sidecar_with_index_scope_fails_as_unavailable():
    inputs = _inputs()
    record = {**inputs.membership.revisions[0], "scope": "listing:sp500:all"}
    inputs.membership = replace(inputs.membership, revisions=(*inputs.membership.revisions, record))
    result = _check(inputs)
    assert not result.passed and result.detail == "unavailable: index coverage sidecar is missing"
    inputs.index_coverage = pd.DataFrame(columns=["scope", "source_ticker", "instrument_id", "valid_from", "valid_to",
                                                  "member_known_at", "identity_known_at", "binding_status", "reason"])
    result = _check(inputs)
    assert not result.passed and "omits listing index scopes" in result.detail


def test_coverage_half_open_membership_and_both_knowledge_gates():
    inputs = _coverage_inputs(20)
    rows = inputs.index_coverage
    rows.loc[0, "valid_to"] = START.isoformat()  # exit session excluded
    rows.loc[1, "valid_from"] = DAYS[1].isoformat()  # future member excluded
    rows.loc[2, "member_known_at"] = f"{DAYS[1]}T00:00:00+00:00"  # unknown member excluded
    rows.loc[3, "identity_known_at"] = f"{DAYS[1]}T00:00:00+00:00"  # member counts; identity not usable
    rows.loc[4, "identity_known_at"] = None
    inputs.prices = inputs.prices.loc[~(inputs.prices["etf_id"].eq("MEMBER5") & inputs.prices["date"].eq(START))]
    result = _check(inputs)
    assert not result.passed
    assert result.counts == {"members": 17, "covered": 14, "unbound": 0, "no_price": 1, "identity_unavailable": 2}
    # Identity timestamps are inclusive at the decision close.
    rows.loc[3, "identity_known_at"] = f"{START}T23:59:59+00:00"
    assert _check(inputs).counts["covered"] == 15


def test_coverage_runs_even_without_scored_or_admitted_members():
    inputs = _coverage_inputs(18)
    inputs.history = pd.DataFrame()
    inputs.eligibility = pd.DataFrame()
    result = _check(inputs)
    assert not result.passed and result.counts["members"] == 20


@pytest.mark.parametrize("column,value", [
    ("member_known_at", "2020-01-01T00:00:00"), ("identity_known_at", "bad"),
    ("binding_status", "unknown"), ("valid_to", "2019-01-01"),
])
def test_malformed_coverage_fails_closed(column, value):
    inputs = _coverage_inputs(20)
    inputs.index_coverage.loc[0, column] = value
    result = _check(inputs)
    assert not result.passed and result.detail.startswith("unavailable:")


def test_coverage_overlap_fails_closed():
    inputs = _coverage_inputs(20)
    inputs.index_coverage = pd.concat([inputs.index_coverage, inputs.index_coverage.iloc[:1]])
    assert not _check(inputs).passed


def test_load_inputs_reads_sidecar_without_writes(tmp_path):
    path = tmp_path / gate.INDEX_COVERAGE_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    expected = _coverage_inputs(20).index_coverage
    expected.to_parquet(path)
    before = sorted(str(path) for path in tmp_path.rglob("*"))
    actual = gate.load_inputs(tmp_path)
    pd.testing.assert_frame_equal(actual.index_coverage, expected)
    assert sorted(str(path) for path in tmp_path.rglob("*")) == before


def test_index_coverage_default_and_configured_threshold(tmp_path):
    assert gate.load_thresholds().min_index_member_coverage == 0.95
    config = gate.CONFIG_PATH.read_text(encoding="utf-8")
    path = tmp_path / "thresholds.yaml"
    path.write_text(config.replace("min_index_member_coverage: 0.95\n", ""), encoding="utf-8")
    assert gate.load_thresholds(path).min_index_member_coverage == 0.95
    path.write_text(config.replace("min_index_member_coverage: 0.95", "min_index_member_coverage: 0.90"), encoding="utf-8")
    assert _check(_coverage_inputs(18), thresholds=gate.load_thresholds(path)).passed


def test_readiness_accepts_observed_status_only_for_canonical_etfs():
    inputs = _inputs()
    # Only VWCE is a canonical ETF; STK1's score-row label cannot fabricate its kind.
    prices = pd.DataFrame([
        {"etf_id": key, "date": START, "close": 100.0, "volume": 1000, "source": "yfinance",
         "available_at": f"{START}T20:00:00+00:00"} for key in ("VWCE", "STK1")
    ])
    retained = tuple(row for row in inputs.membership.revisions if row["instrument_id"] not in {"VWCE", "STK1"})
    inputs.membership = ListingHistory(retained).with_observed_trading(prices, load_config())
    inputs.eligibility.loc[inputs.eligibility["instrument_id"].eq("VWCE"), "membership_status"] = OBSERVED_TRADING_STATUS
    result = gate.evaluate_readiness(inputs, START, START, _thresholds()).dates[0].checks["pit_membership"]
    assert not result.passed and result.gaps["unverified"] == ("STK1",)
    inputs.membership = replace(inputs.membership, revisions=(*retained, *[
        row for row in _inputs().membership.revisions if row["instrument_id"] == "STK1"
    ]))
    assert gate.evaluate_readiness(inputs, START, START, _thresholds()).dates[0].checks["pit_membership"].passed
    inputs.eligibility.loc[inputs.eligibility["instrument_id"].eq("STK1"), "membership_status"] = OBSERVED_TRADING_STATUS
    assert not gate.evaluate_readiness(inputs, START, START, _thresholds()).dates[0].checks["pit_membership"].passed
    inputs.eligibility.loc[inputs.eligibility["instrument_id"].isin(["VWCE", "STK1"]), "membership_status"] = "listed"
    result = gate.evaluate_readiness(inputs, START, START, _thresholds()).dates[0].checks["pit_membership"]
    assert not result.passed and result.gaps["unverified"] == ("VWCE",)


def test_etf_universe_caveat_is_in_readiness_report():
    report = gate.evaluate_readiness(_inputs(), START, START, _thresholds())
    assert any("current listings; closed ETFs are absent" in caveat for caveat in report.caveats)
