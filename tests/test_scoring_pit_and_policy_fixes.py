"""Focused edge cases for the S3-01/03/04/07/08 scoring fixes (bug-hunt group E)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace as N

import pandas as pd
import pytest

import etf_cockpit.signals.simple_scores as s
from etf_cockpit.signals.canonical_scoring import canonical_score_from_signal_row


def test_authority_evidence_gate_normalises_component_status() -> None:
    components = s._attach_component_provenance(
        [replace(s._component("momentum", 1.0, ""), status=" Ok ")], "2026-01-01", date(2026, 1, 1)
    )
    score = s.SimpleInstrumentScore(
        "X", "X", "Primary tier", "ETF", "X", "X", "2026-01-01",
        100.0, 9.0, "Positive", "", components, [], backtest_validity="usable_low_authority",
    )
    gates = {g.gate_id: g for g in s._attach_authority(score).authority_decision.gates}
    assert gates["evidence"].passed

    blocked = replace(score, components=[replace(components[0], status="N/A")])
    gates = {g.gate_id: g for g in s._attach_authority(blocked).authority_decision.gates}
    assert not gates["evidence"].passed


def test_exposure_component_is_unavailable_when_vintage_is_after_decision() -> None:
    info = {"holding_count": 10, "top_weight_sum": 0.4, "largest_weight": 0.1, "as_of_date": "2026-10-05"}
    future = s._etf_exposure_component(info, date(2026, 1, 20))
    assert future.score_10 is None and future.status == "N/A"
    undated = s._etf_exposure_component({**info, "as_of_date": None}, date(2026, 1, 20))
    assert undated.score_10 is None
    known = s._etf_exposure_component({**info, "as_of_date": "2026-01-10"}, date(2026, 1, 20))
    assert known.score_10 is not None and known.as_of_date == "2026-01-10"
    (attached,) = s._attach_component_provenance([known], "2026-01-20", date(2026, 1, 20))
    assert attached.score_eligible


def test_exposure_lookup_uses_one_latest_vintage_and_exposes_its_date(monkeypatch) -> None:
    holdings = pd.DataFrame(
        {
            "etf_id": ["VWCE"] * 3,
            "weight": [0.5, 0.4, 0.2],
            "as_of_date": ["2026-01-10", "2026-01-10", "2026-02-10"],
        }
    )
    monkeypatch.setattr(s, "load_reference_dataset", lambda *_: holdings)
    info = s._etf_exposure_lookup()["VWCE"]
    assert info["as_of_date"] == "2026-02-10"
    assert info["holding_count"] == 1
    assert info["largest_weight"] == pytest.approx(0.2)


def test_candidate_peer_reference_ignores_future_and_undated_peers() -> None:
    frame = pd.DataFrame(
        {
            "latest_date": ["2026-01-20", "2026-02-20", None],
            "return_6m": [0.1, 0.9, 0.9],
        }
    )
    assert s._candidate_relative_reference(frame, date(2026, 1, 20)) == pytest.approx(0.1)
    # Without a decision date the legacy unbounded median is unchanged.
    assert s._candidate_relative_reference(frame) == pytest.approx(0.9)
    # No known peer at all: unavailable, never a median of future rows.
    assert s._candidate_relative_reference(frame, date(2025, 1, 1)) is None


def test_baseline_weight_is_redistributed_from_unavailable_models() -> None:
    config = N(models=N(ensemble={"weights": {"momentum": 0.5, "baseline_ml": 0.25, "timesfm": 0.25}}))
    row = {"etf_id": "X", "score_momentum": 0.0, "score_baseline_ml": 1.0}
    unknown = canonical_score_from_signal_row(row, config, "2026-01-01")
    score = canonical_score_from_signal_row({**row, "price_freshness": "ok"}, config, "2026-01-01")
    # P04-N012 blocks unknown freshness; with fresh evidence, unavailable
    # timesfm's 0.25 still splits 50/50 into momentum and baseline.
    assert (unknown.legacy_composite_raw, score.legacy_composite_raw) == (None, pytest.approx(0.375))


@pytest.mark.parametrize(
    ("declared", "expected"),
    [("stock", "STOCK"), ("etf", "ETF"), (None, "ETF")],
)
def test_signal_canonical_policy_follows_configured_instrument_type(declared, expected) -> None:
    identity = N(instrument_type=declared) if declared else None
    config = N(
        models=N(ensemble={"weights": {"momentum": 1.0}}),
        universe=N(by_id=lambda: {"X": identity} if identity else {}),
    )
    score = canonical_score_from_signal_row({"etf_id": "X", "score_momentum": 0.5}, config, "2026-01-01")
    assert score.asset_type == expected
