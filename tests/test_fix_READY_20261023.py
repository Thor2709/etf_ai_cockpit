"""Data-readiness launch gate (PLAN-T4-20261023, D10): each check fails closed and the CLI exits non-zero unless all pass."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.application import data_readiness as gate
from etf_cockpit.data.replay_membership import ListingHistory
from tests._pit_listing import listed_since

ROOT = Path(__file__).resolve().parents[1]
DAYS = [day.date() for day in pd.bdate_range("2024-01-01", periods=40)]
START, END = DAYS[0], DAYS[-1]
STOCKS = ["STK1", "STK2", "STK3"]
ETFS = ["VWCE", "ETF1"]
GATES = json.dumps([{"gate_id": "valuation", "passed": True, "severity": "warning", "reason": "ok"}])


def _thresholds() -> gate.ReadinessThresholds:
    return replace(gate.load_thresholds(), min_scoreable_stocks=3, min_scoreable_etfs=2)


def _inputs() -> gate.ReadinessInputs:
    """A complete, passing store: every instrument priced, listed, scored with every weighted family and per-gate results."""

    ids = [*ETFS, *STOCKS]
    kind = {key: "ETF" for key in ETFS} | {key: "Stock" for key in STOCKS}
    prices = pd.DataFrame(
        [{"etf_id": key, "date": day, "currency": "USD" if key == "STK3" else "EUR", "source": "yfinance"} for key in ids for day in DAYS]
    )
    history = pd.DataFrame(
        [
            {
                "as_of_date": day.isoformat(), "instrument_id": key, "asset_type": kind[key], "final_combined_score_10": 6.0,
                "freshness_status": "ok", "pit_terms_unavailable": "", "missing_components": "", "gate_results": GATES,
                "provenance": "historical_backfill",
            }
            for key in ids for day in DAYS
        ]
    )
    eligibility = pd.DataFrame(
        [
            {"as_of_date": day.isoformat(), "instrument_id": key, "asset_type": kind[key], "eligible": True, "reasons": "", "membership_status": "listed"}
            for key in ids for day in DAYS
        ]
    )
    fx = pd.DataFrame(
        {"as_of_date": DAYS, "base_currency": "USD", "quote_currency": "EUR", "rate": 0.9, "source": "yfinance", "ingested_at": "2023-12-29T00:00:00+00:00"}
    )
    return gate.ReadinessInputs(history, eligibility, prices, fx, listed_since(ids))


def _evaluate(inputs: gate.ReadinessInputs, thresholds: gate.ReadinessThresholds | None = None) -> gate.ReadinessReport:
    return gate.evaluate_readiness(inputs, START, END, thresholds or _thresholds(), every=5)


def _failed(report: gate.ReadinessReport) -> set[str]:
    return {name for item in report.dates for name, result in item.checks.items() if not result.passed}


def test_membership_and_scoreable_counts_are_checked_per_date() -> None:
    inputs = _inputs()
    inputs.membership = listed_since(["VWCE", "ETF1", "STK1", "STK2"])  # STK3 has no listing history
    report = _evaluate(inputs)
    assert _failed(report) == {"pit_membership"} and "STK3" in report.dates[0].checks["pit_membership"].gaps["unverified"]
    inputs.membership = None  # an unavailable membership store is a FAIL, never assumed verified
    assert "pit_membership" in _failed(_evaluate(inputs))
    inputs = _inputs()
    assert not _evaluate(inputs, replace(_thresholds(), min_scoreable_stocks=4)).passed
    unscored = inputs.history["as_of_date"].eq(DAYS[5].isoformat()) & inputs.history["instrument_id"].eq("STK2")
    inputs.history.loc[unscored, "final_combined_score_10"] = None  # one date loses a scoreable stock
    report = _evaluate(inputs)
    assert [item.day for item in report.dates if not item.passed] == [DAYS[5].isoformat()]
    assert report.dates[1].checks["universe_counts"].counts["scoreable_stocks"] == 2


def test_family_completeness_counts_only_weighted_families_and_needs_90_percent() -> None:
    inputs = _inputs()
    inputs.history["pit_terms_unavailable"] = "timesfm|etf_exposure"  # headline weight 0: never blocks
    assert _evaluate(inputs).passed
    inputs.history.loc[inputs.history["instrument_id"].isin(["STK1", "STK2"]), "missing_components"] = "stock_value"  # weight > 0
    report = _evaluate(inputs)
    assert _failed(report) == {"family_completeness"}
    assert report.dates[0].checks["family_completeness"].counts["missing:stock_value"] == 2
    inputs.history["missing_components"] = ""
    inputs.history.loc[inputs.history["instrument_id"].eq("ETF1"), "freshness_status"] = "stale"  # not fresh also blocks
    assert _failed(_evaluate(inputs)) == {"family_completeness"}


def test_prices_and_fx_must_cover_admitted_instruments() -> None:
    inputs = _inputs()
    inputs.prices = inputs.prices.loc[~(inputs.prices["etf_id"].eq("STK1") & (inputs.prices["date"] > DAYS[10]))]
    report = _evaluate(inputs)
    assert "prices" in _failed(report) and "STK1" in report.dates[-1].checks["prices"].gaps["no_recent_price"]
    inputs = _inputs()
    inputs.prices = inputs.prices.loc[~(inputs.prices["etf_id"].eq("VWCE") & inputs.prices["date"].isin(DAYS[1:5]))]
    report = _evaluate(inputs)
    assert not report.interval["benchmark_sessions"].passed and not report.passed
    inputs = _inputs()
    inputs.fx = pd.DataFrame()  # the USD stock has no rate: FAIL, never 1.0
    report = _evaluate(inputs)
    assert _failed(report) == {"fx"} and any("USD_to_EUR" in label for label in report.dates[0].checks["fx"].gaps)
    inputs = _inputs()
    inputs.fx = inputs.fx.loc[inputs.fx["as_of_date"] > DAYS[20]]  # no quote on or before the early dates
    assert "fx" in _failed(_evaluate(inputs))


def test_complete_store_passes_and_missing_inputs_fail_closed(tmp_path: Path) -> None:
    report = _evaluate(_inputs())
    assert report.passed and len(report.dates) == 8 and not _failed(report) and report.execution_allowed is False
    inputs = _inputs()
    inputs.history = inputs.history.loc[inputs.history["as_of_date"].ne(DAYS[5].isoformat())]
    report = _evaluate(inputs)
    assert [item.day for item in report.dates if not item.passed] == [DAYS[5].isoformat()]
    assert not report.dates[1].checks["scored_run"].passed
    empty = gate.evaluate_readiness(gate.ReadinessInputs(unavailable={"prices": "boom"}), START, END, _thresholds())
    assert not empty.passed and not empty.dates and "boom" in empty.interval["decision_dates"].detail
    text = gate.CONFIG_PATH.read_text(encoding="utf-8")
    (tmp_path / "missing.yaml").write_text(text.replace("min_scoreable_etfs: 10\n", ""), encoding="utf-8")
    (tmp_path / "live.yaml").write_text(text.replace("execution_allowed: false", "execution_allowed: true"), encoding="utf-8")
    for name in ("missing.yaml", "live.yaml", "absent.yaml"):
        with pytest.raises(ValueError):
            gate.load_thresholds(tmp_path / name)
    configured = gate.load_thresholds()
    assert (configured.min_scoreable_stocks, configured.min_scoreable_etfs, configured.min_family_complete_share) == (200, 10, 0.90)
    assert (configured.min_price_coverage_share, configured.max_gate_wiring_failures) == (0.99, 0)


def test_per_gate_results_must_be_stored_for_every_scored_row() -> None:
    inputs = _inputs()
    inputs.history.loc[inputs.history["instrument_id"].eq("STK2"), "gate_results"] = "[]"
    report = _evaluate(inputs)
    assert _failed(report) == {"gate_results"} and report.dates[0].checks["gate_results"].gaps["gate_wiring"] == ("STK2",)
    inputs = _inputs()
    assert "gate_results" in _failed(_evaluate(replace(inputs, history=inputs.history.drop(columns=["gate_results"]))))


def test_cli_exits_non_zero_without_stores_and_writes_nothing(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "data_readiness.py"), "--root", str(tmp_path), "--start", "2024-01-01", "--end", "2024-02-23"],
        capture_output=True, text=True, timeout=300, cwd=ROOT, check=False,
    )
    assert result.returncode == 1, (result.stdout[-400:], result.stderr[-400:])
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["status"] == "FAIL" and summary["execution_allowed"] is False
    assert list(tmp_path.iterdir()) == []
    bad = subprocess.run([sys.executable, str(ROOT / "scripts" / "data_readiness.py"), "--root", str(tmp_path), "--start", "2024-02-23", "--end", "2024-01-01"],
                         capture_output=True, text=True, timeout=300, cwd=ROOT, check=False)
    assert bad.returncode == 2
