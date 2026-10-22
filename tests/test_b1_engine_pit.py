"""Lane B: dated solvency metrics and explicit point-in-time ETF holdings."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics as sm, stock_universe
from etf_cockpit.analysis.decision import gates
from etf_cockpit.application import score_backfill
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data.esef_provider import parse_reported_shares
from etf_cockpit.signals import simple_scores as scores
from tests.test_b1_blockers import _facts
from tests.test_score_backfill import _config, _series
from tests.test_stock_evidence import _evidence, _period

DAY = date(2025, 9, 30)
CUTOFF = datetime(2025, 9, 30, 23, 59, 59, tzinfo=timezone.utc)


def _holdings(etf_id: str, *, vintage="2025-09-29", known="2025-09-30T08:00:00Z", weight=0.01):
    return pd.DataFrame({"etf_id": etf_id, "weight": [weight] * 100, "as_of_date": vintage, "known_at": known})


def _pit_run(monkeypatch, *, missing: str | None = None):
    config = _config()
    # Use normal-stock identities: banks have a separate valuation route.
    stocks = ["SU", "LR", "PRY", "NEX"]
    etf = "VWCE"
    selected = [*stocks, etf]
    config.universe.etfs = [item for item in config.universe.etfs if item.id in selected]
    for item in config.universe.etfs:
        item.exchange = "XETRA"
        if item.id in stocks:
            item.sector = "Technology"  # synthetic generic companies, same peer cohort
    sessions = list(xcals.get_calendar("XETR").sessions_in_range("2022-01-03", str(DAY)))
    frames = []
    for seed, instrument in enumerate(selected):
        frame = _series(instrument, sessions, seed, volume=100_000.0)
        rng = np.random.default_rng(seed)
        # A positive, low-volatility path supplies an actual candidate signal.
        level = 50 * np.exp(np.cumsum(rng.normal(0.001, 0.002, len(frame))))
        for column, factor in (("open", 1), ("close", 1), ("adjusted_close", 1), ("high", 1.004), ("low", 0.996)):
            frame[column] = level * factor
        if missing == "prices" and instrument == stocks[0]:
            frame = frame.tail(120)
        frames.append(frame)
    prices = pd.concat(frames, ignore_index=True)
    share = parse_reported_shares(_facts("2023-03-30"), source_ref="synthetic filing")[0]
    filed = sm.Period(
        date.fromisoformat(share["period_end"]), "SHARES", datetime.fromisoformat(share["known_at"]), "EUR",
        share["source"], {"shares_outstanding": share["shares_outstanding"]},
        available_at=datetime.fromisoformat(share["available_at"]),
    )
    periods = {}
    for index, instrument in enumerate(stocks):
        annual = []
        for year in (2021, 2022, 2023, 2024):
            period = _period(year, minority_interest=0.0)
            # Solvency is debt/equity only; absent D&A must not require a peer-scored leverage ratio.
            values = {key: value * 100 for key, value in period.values.items() if key not in {"shares_outstanding", "da"}}
            if index:
                for key in ("net_income_parent", "ebit", "cfo"):
                    values[key] *= 0.5
            if instrument == stocks[0] and missing in {"debt", "equity"}:
                values.pop("ib_debt" if missing == "debt" else "equity_parent")
            annual.append(replace(period, values=values, field_sources={}))
        periods[instrument] = annual + ([] if missing == "shares" and instrument == stocks[0] else [filed])
    monkeypatch.setattr(store, "read_fundamentals", lambda _root: pd.DataFrame(columns=store.PERIOD_COLUMNS))
    monkeypatch.setattr(store, "read_snapshots", lambda _root: pd.DataFrame(columns=store.SNAPSHOT_COLUMNS))
    monkeypatch.setattr(store, "read_fx", lambda _root: pd.DataFrame(columns=store.FX_COLUMNS))
    monkeypatch.setattr(store, "periods_for", lambda iid, _frame, _chain: periods.get(iid, []))
    monkeypatch.setattr(stock_universe, "load_user_peers", lambda _root: {})
    monkeypatch.setattr(scores, "get_universe_evidence", stock_universe.build_universe_evidence)
    holdings = None if missing == "holdings" else _holdings(etf)
    original_build = scores.build_universe_simple_scores
    original_rank = score_backfill.rank_and_finalize_scores
    observed = {}

    def build(*args, **kwargs):
        # Lane C owns passing the holdings source in production. Exercise that fixed contract here.
        kwargs["as_of_sources"] = replace(kwargs["as_of_sources"], etf_holdings=holdings)
        return original_build(*args, **kwargs)

    def rank(*args, **kwargs):
        ranked = original_rank(*args, **kwargs)
        observed.update({item.display_id: item for item in ranked})
        return ranked

    monkeypatch.setattr(score_backfill, "build_universe_simple_scores", build)
    monkeypatch.setattr(score_backfill, "rank_and_finalize_scores", rank)
    run, eligibility = score_backfill.score_as_of(config, prices, DAY, fx_rates=pd.DataFrame())
    return run, eligibility, observed, stocks[0], etf


def test_complete_pit_stock_and_etf_are_promoted(monkeypatch):
    run, _, observed, stock, etf = _pit_run(monkeypatch)
    assert run is not None and len(run) == 5
    score = observed[stock]
    failures = [(gate.gate_id, gate.message) for gate in score.authority_decision.gates if not gate.passed]
    assert score.research_promotion_allowed is True, (stock, score.final_label, score.warnings, failures)
    assert score.analysis_status == "complete"
    row = run.set_index("instrument_id").loc[stock]
    assert bool(row["research_promotion_allowed"]) and row["analysis_status"] == "complete"
    # ETF: the PIT holdings now satisfy the exposure/identity/cost critical gates. As-of mode withholds stored
    # forecasts (no known-at), so ETF canonical coverage stays below minimum_coverage 0.50 by design; the gate is
    # not relaxed and the remaining blocker is named.
    etf_score = observed[etf]
    gates = {gate.gate_id: gate.status for gate in etf_score.canonical_score.critical_gates}
    assert gates == {"identity": "PASS", "cost": "PASS", "exposure": "PASS"}
    assert etf_score.canonical_score.unavailable_reason == "insufficient_coverage"
    assert etf_score.research_promotion_allowed is False


@pytest.mark.parametrize("missing,gate", [("shares", "owner_claim"), ("debt", "solvency_liquidity"),
                                         ("equity", "solvency_liquidity"), ("holdings", "exposure"),
                                         ("prices", "insufficient_history")])
def test_removing_one_input_blocks_with_the_named_gate(monkeypatch, missing, gate):
    run, eligibility, observed, stock, etf = _pit_run(monkeypatch, missing=missing)
    instrument = etf if missing == "holdings" else stock
    if missing == "prices":
        row = eligibility.set_index("instrument_id").loc[instrument]
        assert not bool(row["eligible"]) and gate in row["reasons"]
        assert instrument not in set(run["instrument_id"])
    else:
        score = observed[instrument]
        assert not score.research_promotion_allowed
        assert gate in {result.gate_id for result in score.canonical_score.critical_gates if not result.passed}


def test_holdings_vintage_after_decision_stays_unavailable(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("historical exposure must never read the global latest file")

    monkeypatch.setattr(scores, "load_reference_dataset", forbidden)
    eligible = _holdings("VWCE")
    future = _holdings("VWCE", vintage="2025-10-01", known="2025-09-30T08:00:00Z", weight=0.02)
    late = _holdings("VWCE", vintage="2025-09-30", known="2025-10-01T00:00:00Z", weight=0.03)
    mixed = pd.concat([eligible, future, late], ignore_index=True)
    found = scores._etf_exposure_lookup(CUTOFF, mixed)["VWCE"]
    assert found["as_of_date"] == "2025-09-29" and found["holding_count"] == 100
    assert found["largest_weight"] == 0.01
    for unavailable in (future, late, eligible.drop(columns="known_at"), eligible.drop(columns="as_of_date"),
                        eligible.assign(known_at=None), eligible.assign(as_of_date=None)):
        assert scores._etf_exposure_lookup(CUTOFF, unavailable) == {}
    assert scores._etf_exposure_lookup(CUTOFF) == {}
    # Same-day publication obeys the full timestamp, including timezone offsets.
    same_day = _holdings("VWCE", known="2025-09-30T10:00:00+02:00")
    assert scores._etf_exposure_lookup(datetime(2025, 9, 30, 7, 59, tzinfo=timezone.utc), same_day) == {}
    assert scores._etf_exposure_lookup(datetime(2025, 9, 30, 8, tzinfo=timezone.utc), same_day)
    monkeypatch.setattr(scores, "load_reference_dataset", lambda _name: mixed)
    assert scores._etf_exposure_lookup()["VWCE"]["as_of_date"] == "2025-10-01"  # live behavior


def test_debt_to_equity_only_solvency_counts():
    evidence = _evidence([replace(_period(year), values={"ib_debt": 100.0, "equity_parent": 200.0})
                          for year in (2024, 2025)])
    assert evidence.metrics["debt_to_equity"].available
    assert not evidence.metrics["net_debt_to_ebitda"].available
    assert not evidence.components["stock_quality"].used
    assert "debt_to_equity" in scores._critical_evidence_ids(evidence)
    components = scores._stock_fundamental_components(evidence)
    quality = next(part for part in components if part.key == "stock_quality")
    assert dict(quality.input_as_of_dates)["debt_to_equity"] == "2025-12-31"
    result = gates.evaluate_score_gate("STOCK", dict(quality.input_as_of_dates), decision_time=evidence.decision_time)
    assert next(gate for gate in result.gates if gate.gate_id == "solvency_liquidity").passed


@pytest.mark.parametrize("age", [None, 457, -1, 456])
def test_stale_or_undated_leverage_does_not_count(age):
    evidence = _evidence()
    as_of = None if age is None else (evidence.decision_time.date() - timedelta(days=age)).isoformat()
    leverage = {key: sm.Metric(key, key, 1.0, "multiple", sm.OK, as_of=as_of) for key in scores._LEVERAGE_METRIC_IDS}
    evidence = replace(evidence, metrics=leverage)
    emitted = set(scores._critical_evidence_ids(evidence)) & set(leverage)
    assert emitted == (set(leverage) if age == 456 else set())
    quality = next(part for part in scores._stock_fundamental_components(evidence) if part.key == "stock_quality")
    # Unscored solvency metrics never become peer-scored quality inputs.
    originally_used = {part.key for part in evidence.components["stock_quality"].used}
    assert set(quality.inputs_used) & set(leverage) == originally_used & emitted
    assert dict(quality.input_as_of_dates) == ({key: as_of for key in leverage} if age == 456 else {})
