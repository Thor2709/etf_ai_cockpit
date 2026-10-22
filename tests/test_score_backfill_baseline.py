"""Point-in-time baseline quantiles are research friction inputs, never calibrated evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pandas as pd

from etf_cockpit.application import score_backfill
from etf_cockpit.data import score_history_backfill as store
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.forecast_scores import PRIMARY_MODEL_HORIZON_DAYS
from etf_cockpit.portfolio.costs import estimate_execution_cost
from etf_cockpit.signals.friction_edge import estimate_friction_adjusted_return
from etf_cockpit.signals.signal_pipeline import BASELINE_MODEL_VERSION
from tests.test_score_backfill import AS_OF, _config, _eur_ids, _prices, _run, _fingerprint
from tests._pit_listing import verified_listing_history  # noqa: F401 (autouse)


def _stored(root, config, prices, *, force=False):
    result = score_backfill.backfill_score_history(
        root, AS_OF, AS_OF, config=config, prices=prices, fx_rates=pd.DataFrame(), force=force,
    )
    assert result.status == "available", (result.reason, result.unavailable_dates)
    return store.load_backfill_score_history(root)


def test_stored_baseline_quantiles_match_known_prices_and_ignore_future_changes(tmp_path):
    config = _config()
    prices = _prices(config)
    before = _stored(tmp_path, config, prices)
    for row in before.itertuples():
        known = prices.loc[prices["etf_id"].eq(row.instrument_id) & prices["date"].le(AS_OF)]
        adjusted = known.set_index(pd.DatetimeIndex(pd.to_datetime(known["date"])))["adjusted_close"]
        expected, = baseline_forecast(row.instrument_id, adjusted, [PRIMARY_MODEL_HORIZON_DAYS], AS_OF, row.run_id)
        for field in ("q10_return", "q50_return", "q90_return"):
            assert getattr(row, field) == getattr(expected, field)
        assert row.forecast_date == AS_OF and row.horizon_days == PRIMARY_MODEL_HORIZON_DAYS
    future = prices["date"].gt(AS_OF)
    assert future.any()
    prices.loc[future, ["open", "high", "low", "close", "adjusted_close"]] *= 25.0
    after = _stored(tmp_path, config, prices, force=True)
    pd.testing.assert_frame_equal(before, after)  # persisted quantiles and snapshot lineage are identical


def test_baseline_provenance_is_uncalibrated_and_optional_models_stay_withheld(monkeypatch, tmp_path):
    config = _config()
    original = score_backfill.build_universe_simple_scores
    seen = []

    def recording(config, signals, forecasts, prices, **kwargs):
        assert forecasts.empty and kwargs["calibration_by_id"] == {}
        sources = kwargs["as_of_sources"]
        assert sources.decision_time == datetime(2022, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
        seen.extend(sources.expected_return_distributions.values())
        return original(config, signals, forecasts, prices, **kwargs)

    monkeypatch.setattr(score_backfill, "build_universe_simple_scores", recording)
    history = _stored(tmp_path, config, _prices(config))
    assert seen and {row["model_name"] for row in seen} == {"baseline"}
    assert {row["model_version"] for row in seen} == {BASELINE_MODEL_VERSION}
    assert all(row["model_allowed_in_score"] is False for row in seen)
    for field in ("prob_positive_return", "prob_beat_benchmark"):
        assert all(row[field] is None for row in seen)
        assert history[field].isna().all()
    assert set(history["forecast_provenance"]) == {"baseline_only_non_calibrated"}
    assert set(history["probability_calibration_status"]) == {"unavailable"}
    assert set(history["calibration_status"]) == {"not_evaluated"}
    coverage = json.loads(history["pit_coverage"].iloc[0])
    for model in ("baseline", "timesfm", "toto"):
        assert coverage["terms"][model]["available"] == 0
    manifest = store.load_backfill_manifest(tmp_path)
    assert {"stored_forecasts_and_calibration", "timesfm", "toto"}.issubset(manifest["withheld_sources"])
    assert manifest["execution_allowed"] is False and history["execution_allowed"].eq(False).all()


def test_existing_friction_and_cost_gate_consume_baseline_without_changing_other_gates(monkeypatch):
    config = _config()
    prices = _prices(config)
    captured = []
    original = score_backfill.rank_and_finalize_scores

    def recording(*args, **kwargs):
        scores = original(*args, **kwargs)
        captured.append({score.display_id: score for score in scores})
        return scores

    monkeypatch.setattr(score_backfill, "rank_and_finalize_scores", recording)
    history, _ = _run(config, prices)
    assert history is not None
    monkeypatch.setattr(score_backfill, "_baseline_forecasts", lambda *_args: {})
    without, _ = _run(config, prices)
    assert without is not None
    with_baseline, without_baseline = captured
    order_value = config.risks.portfolio_limits.min_trade_value_eur
    for row in history.itertuples():
        actual = with_baseline[row.instrument_id]
        missing = without_baseline[row.instrument_id]
        cost = estimate_execution_cost(config, row.instrument_id, order_value).as_dict()
        expected = estimate_friction_adjusted_return(
            {"q10_return": row.q10_return, "q50_return": row.q50_return,
             "q90_return": row.q90_return, "horizon_days": row.horizon_days},
            order_value_eur=order_value, cost_estimate=cost,
        )
        assert expected.status == actual.friction_status == "available"
        assert actual.q10_expected_return == expected.q10_return
        assert actual.q50_expected_return == expected.q50_return
        assert actual.q90_expected_return == expected.q90_return
        assert actual.net_expected_return == expected.net_expected_return
        assert actual.expected_return_cost_eur == expected.cost_eur
        assert actual.edge_to_cost_ratio == expected.return_to_cost_ratio
        assert row.expected_return_order_value_eur == order_value
        assert row.expected_return_order_value_source == "configured_min_trade_value_eur_research_reference"
        assert missing.friction_status == "unavailable" and missing.edge_to_cost_ratio is None
        gates = {gate.gate_id: gate for gate in actual.authority_decision.gates}
        old_gates = {gate.gate_id: gate for gate in missing.authority_decision.gates}
        assert gates["cost"].passed is True and old_gates["cost"].passed is False
        for gate in ("valuation", "model_validity"):
            assert gates[gate] == old_gates[gate]
        assert actual.canonical_score == missing.canonical_score
        assert actual.execution_allowed is False and actual.research_promotion_allowed is False


def test_insufficient_sparse_or_stale_history_stays_unavailable():
    config = _config()
    young = _eur_ids(config, "etf", 4)[3]
    prices = _prices(config, young=young)
    known = prices.loc[prices["date"].le(AS_OF)]
    victim = _eur_ids(config, "etf", 2)[0]
    rows = known.loc[known["etf_id"].eq(victim)].sort_values("date")
    for invalid in (rows.tail(20), rows.iloc[::5], rows.iloc[:-10]):
        assert score_backfill._baseline_forecasts(invalid, AS_OF, "backfill") == {}
    history, eligibility = _run(config, prices)
    assert history is not None and young not in set(history["instrument_id"])
    entry = eligibility.loc[eligibility["instrument_id"].eq(young)].iloc[0]
    assert not entry["eligible"] and "insufficient_history" in entry["reasons"]


def test_pre_baseline_fingerprint_recomputes_stored_sessions(tmp_path):
    config = _config()
    prices = _prices(config)
    history = _stored(tmp_path, config, prices)
    fingerprint, material = _fingerprint(config, tmp_path)
    material.pop("baseline_forecast")
    legacy = hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()
    assert legacy != fingerprint
    history["config_fingerprint"] = legacy
    history[["q10_return", "q50_return", "q90_return"]] = None
    store.write_backfill_store(
        tmp_path, history, store.load_backfill_eligibility(tmp_path), store.load_backfill_manifest(tmp_path),
    )
    result = score_backfill.backfill_score_history(
        tmp_path, AS_OF, AS_OF, config=config, prices=prices, fx_rates=pd.DataFrame(),
    )
    assert result.runs_written == 1 and result.runs_kept == 0
    refreshed = store.load_backfill_score_history(tmp_path)
    assert set(refreshed["config_fingerprint"]) == {fingerprint}
    assert refreshed[["q10_return", "q50_return", "q90_return"]].notna().all().all()
    again = score_backfill.backfill_score_history(
        tmp_path, AS_OF, AS_OF, config=config, prices=prices, fx_rates=pd.DataFrame(),
    )
    assert again.runs_written == 0 and again.runs_kept == 1
