"""SCORE audit regressions: eight test functions, one case per applicable finding."""

from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
from math import tanh
from types import SimpleNamespace as N

import pandas as pd
import pytest

from etf_cockpit.analysis.decision import gates
from etf_cockpit.core.config import load_config
from etf_cockpit.signals import simple_scores as s


DAY = date(2026, 10, 20)


def _component(key, **changes):
    return replace(s._component(key, 0.6, "audit fixture"), as_of_date=DAY.isoformat(), freshness_status="ok", **changes)


def _score(**changes):
    row = s.SimpleInstrumentScore(
        instrument_key="configured:VWCE", display_id="VWCE", source_group="Primary tier",
        asset_type="Stock", name="audit fixture", yahoo_symbol="VWCE.DE",
        latest_date=DAY.isoformat(), latest_price=100.0, final_score_10=8.0,
        decision="Strong Evidence Candidate", one_line_reason="audit fixture",
        components=[_component("momentum"), _component("stock_value"), _component("stock_quality")],
        warnings=[], final_label="strong_evidence_candidate", final_action="add_candidate",
        backtest_validity="usable_low_authority", portfolio_fit_score_10=8.0,
        net_expected_edge_bps=100.0, edge_to_cost_ratio=2.0,
    )
    return replace(row, **changes)


@pytest.fixture
def local(monkeypatch):
    config = load_config()
    identities = [row for row in config.universe.etfs if row.id in {"VWCE", "LYP6"}]
    assert {row.id for row in identities} == {"VWCE", "LYP6"}
    config = config.model_copy(update={"universe": config.universe.model_copy(update={"etfs": identities})})
    monkeypatch.setattr(s, "_stock_evidence_lookup", lambda *a, **kw: ({}, None))
    monkeypatch.setattr(s, "_etf_exposure_lookup", lambda *a, **kw: {})
    monkeypatch.setattr(s, "_kid_record_lookup", lambda: {})
    monkeypatch.setattr(s, "_etf_product_quality_lookup", lambda *a, **kw: ({}, {}))
    monkeypatch.setattr(s, "_identity_conflict_reasons", lambda ids: {})
    monkeypatch.setattr(s, "classification_score_state", lambda *a: {"status": "current", "invalidation_token": "audit-token"})
    return config


def _signal(instrument_id="VWCE", day=DAY):
    return N(etf_id=instrument_id, signal_date=day, blocked_by=[], warnings=[],
             supporting_metrics={}, components=N(momentum=0.6, trend=0.6, risk=0.6, relative_strength=0.6))


def test_attach_authority_failed_predicates():
    """A01-F1: each failed predicate must fail its own gate, including pending states."""
    baseline = _score()
    assert all(g.passed for g in s._attach_authority(baseline).authority_decision.gates)
    failures = [
        ("identity", {"identity_conflict_reason": "unresolved identity"}),
        ("cost", {"net_expected_edge_bps": -100.0, "edge_to_cost_ratio": -2.0}),
        ("cost", {"net_expected_edge_bps": 0.0}),
        ("cost", {"edge_to_cost_ratio": 0.9}),
        ("portfolio_fit", {"portfolio_fit_score_10": None, "portfolio_fit_label": "Portfolio fit pending"}),
        ("model_validity", {"backtest_validity": "unverified_backtest"}),
        ("risk", {"warnings": ["high_60d_volatility"]}),
        ("data_quality", {"warnings": ["insufficient_12m_history"]}),
        ("valuation", {"components": [_component("stock_value", status="N/A")]}),
    ]
    for gate_id, changes in failures:
        result = s._attach_authority(replace(baseline, **changes))
        assert not next(g for g in result.authority_decision.gates if g.gate_id == gate_id).passed, gate_id
        assert not result.research_promotion_allowed and result.execution_allowed is False
    for asset_type in ("ETF", "Certificate"):
        result = s._attach_authority(replace(baseline, asset_type=asset_type, components=[_component("momentum")]))
        assert next(g for g in result.authority_decision.gates if g.gate_id == "valuation").passed


def test_ineligible_fundamentals_fail_critical_gate():
    """A01-F2: neither unavailable inputs nor a price-stamped fundamental can supply capital."""
    base = _component("stock_value", inputs_used=("cet1_ratio", "market_cap"),
                      input_as_of_dates=(("cet1_ratio", DAY.isoformat()),))
    for changes in ({"status": "N/A"}, {"freshness_status": "stale"}, {"conflict_id": "audit-conflict"}):
        score = _score(business_model="bank", components=[replace(base, **changes)])
        held = s._critical_evidence_dated(score)
        assert "cet1_ratio" not in held and "market_cap" not in held
        decision = gates.evaluate_score_gate("BANK", held, decision_time=DAY)
        assert not next(g for g in decision.gates if g.gate_id == "capital").passed
        assert s._with_critical_evidence(score).final_action == "manual_review"
    for key in ("stock_value", "stock_quality", "analyst_revision", "baseline"):
        undated = s._component(key, 0.6, "undated")
        (attached,) = s._attach_component_provenance([undated], DAY.isoformat(), DAY)
        assert attached.as_of_date is None and not attached.score_eligible
        assert key not in s._critical_evidence_dated(_score(components=[attached]))


def test_historical_price_lookups_ignore_future_rows(local):
    """A01-F3: own signal dates and the explicit earlier decision bound every price lookup."""
    days = pd.bdate_range(end=DAY, periods=260)
    past = pd.DataFrame([
        {"etf_id": key, "date": day, "close": 100.0, "adjusted_close": 100.0,
         "high": 102.0, "low": 98.0, "volume": 100_000.0, "currency": "EUR", "is_adjusted": True}
        for key in ("VWCE", "LYP6") for day in days
    ])
    future = past.tail(1).assign(date="2026-10-21", close=10000.0, adjusted_close=10000.0, volume=1.0)
    signals = [_signal(), _signal("LYP6", date(2026, 10, 19))]
    def build(frame, sources=None):
        return s.build_universe_simple_scores(local, signals, pd.DataFrame(), frame, as_of_sources=sources, fx_rates=pd.DataFrame())
    clean, mixed = build(past), build(pd.concat([past, future], ignore_index=True))
    assert [(r.latest_date, r.latest_price, r.components, r.final_score_10, r.risk_friction_10) for r in clean] == [
        (r.latest_date, r.latest_price, r.components, r.final_score_10, r.risk_friction_10) for r in mixed
    ]
    assert [row.latest_date for row in mixed] == [DAY.isoformat(), "2026-10-19"]
    assert all(next(c for c in row.components if c.key == "data_quality").score_10 == 9.0 for row in mixed)
    sources = s.AsOfScoreSources(datetime(2026, 10, 16, 23, 59, tzinfo=timezone.utc))
    bounded = build(past, sources)
    assert all(row.latest_date == "2026-10-16" for row in bounded)
    assert bounded == build(past.loc[past["date"] <= pd.Timestamp("2026-10-16")], sources)


def test_sparebank_evidence_respects_decision_time(monkeypatch):
    """A01-F4: a native scorecard learned later cannot supply historical capital or claim evidence."""
    observed = []
    def lookup(*, decision_time):
        observed.append(decision_time)
        if str(decision_time) < "2026-10-21":
            return {}
        return {"AURG": {"final_combined_score_10": 8.0, "missing_components": "", "data_as_of_date": DAY.isoformat()}}
    monkeypatch.setattr(s, "latest_sparebank_scores", lookup)
    score = _score(display_id="AURG", asset_type="Equity certificate", components=[])
    assert not ({"cet1_ratio", "eierbrok", "equity_certificates"} & s._critical_evidence_ids_of(score))
    assert s._with_critical_evidence(score).final_action == "manual_review"
    assert observed and set(observed) == {DAY.isoformat()}
    assert {"cet1_ratio", "eierbrok", "equity_certificates"} <= s._critical_evidence_ids_of(replace(score, latest_date="2026-10-21"))


def test_stale_bank_capital_fails_gate():
    """A02-F1: even metrics reported available must be dated and at most 456 days old."""
    parts = {key: N(score_10=8.0, why="audit", source_id="sec_edgar:fundamentals", as_of=DAY.isoformat(),
                    freshness="ok", band_low=None, band_high=None,
                    used=(N(key="market_cap"), N(key="cet1_ratio"), N(key="total_capital_ratio")))
             for key in ("stock_value", "stock_quality", "analyst_revision")}
    for vintage, expected in (("2022-12-31", False), (None, False), ("2026-10-21", False), ("2026-10-19", True)):
        metrics = {key: N(available=True, as_of=vintage) for key in ("market_cap", "cet1_ratio", "total_capital_ratio")}
        evidence = N(components=parts, metrics=metrics, decision_time=datetime(2026, 10, 20, tzinfo=timezone.utc))
        components = s._stock_fundamental_components(evidence)
        held = s._critical_evidence_dated(_score(components=components))
        assert ({"market_cap", "cet1_ratio", "total_capital_ratio"} <= set(held)) is expected
        result = gates.evaluate_score_gate("BANK", held, decision_time=DAY)
        assert next(g for g in result.gates if g.gate_id == "capital").passed is expected
        for component in components[:2]:
            assert dict(component.input_as_of_dates) == ({key: vintage for key in metrics} if expected else {})


@pytest.mark.parametrize("finding", ["A01-F5", "A01-F6", "A01-F8"])
def test_finalization_and_bound_sources(local, monkeypatch, finding):
    if finding in {"A01-F5", "A01-F6"}:
        base = s._with_canonical_score(_score())
        if finding == "A01-F6":
            bound = s._with_canonical_score(s._with_classification_dependency(base))
            raw = s.canonical_score_from_simple_components(base.display_id, base.asset_type, base.latest_date, base.components,
                                                         critical_evidence=s._critical_evidence_dated(base), business_model=base.business_model)
            expected = hashlib.sha256(f"{raw.source_vintage_hash}|classification:audit-token".encode()).hexdigest()
            assert bound.canonical_score.source_vintage_hash == expected != base.canonical_score.source_vintage_hash
            assert s._with_canonical_score(bound) == bound
        else:
            monkeypatch.setattr(s, "_identity_conflict_reasons", lambda ids: {"VWCE": "audit conflict"})
            cohort = []
            def clusters(*a, **kw):
                cohort.extend(kw["ranked_instruments"])
                return N(rows=[])
            monkeypatch.setattr(s, "build_correlation_clusters", clusters)
            conflict = replace(base, score_band_low=7.0, score_band_high=9.0, score_band_basis="audit")
            valid = _score(display_id="LYP6", final_score_10=7.0)
            unscored = _score(display_id="AURG", final_score_10=None)
            result = s.rank_and_finalize_scores([conflict, unscored, valid], pd.DataFrame(), {}, news_inventory={})
            assert cohort == ["LYP6"] and result[0].display_id == "LYP6" and result[0].rank == 1
            bad = next(row for row in result if row.display_id == "VWCE")
            assert bad.rank is None and bad.score_rank is None and bad.canonical_score is None
            assert bad.score_band_low is bad.score_band_high is bad.score_band_basis is None
            assert bad.final_action == bad.legacy_action == "manual_review" and bad.internal_intent.value == "none"
            assert next(row for row in result if row.display_id == "AURG").rank is None
    else:
        from etf_cockpit.features import feature_pipeline as fp
        seen = []
        monkeypatch.setattr(fp, "eur_basis_prices", lambda frame, *a, **kw: (seen.append(frame["date"].max()), (_ for _ in ()).throw(ValueError("stop after cutoff")))[1])
        monkeypatch.setattr(s, "fx_rates_for_prices", lambda frame: pd.DataFrame())
        prices = pd.DataFrame({"etf_id": ["LYP6", "LYP6"], "date": ["2025-06-15", DAY.isoformat()]})
        s._generate_missing_price_signals(local, [_signal(day=date(2025, 6, 15)), _signal()], prices)
        assert seen == [DAY]
        monkeypatch.setattr(s, "_generate_missing_price_signals", lambda config, sigs, px: (sigs, {}))
        monkeypatch.setattr(s, "load_latest_candidate_report", lambda: (pd.DataFrame(), None))
        monkeypatch.setattr(s, "load_latest_forecasts", lambda *a, **kw: pd.DataFrame())
        monkeypatch.setattr(s, "load_forecast_history", lambda: pd.DataFrame())
        monkeypatch.setattr(s, "build_market_regime", lambda *a, **kw: {})
        monkeypatch.setattr(s, "build_portfolio_fit_lookup", lambda *a, **kw: {})
        monkeypatch.setattr(s, "build_benchmark_attribution_lookup", lambda *a, **kw: {})
        monkeypatch.setattr(s, "build_correlation_clusters", lambda *a, **kw: N(rows=[]))
        monkeypatch.setattr(s, "_backtest_trust_lookup", lambda **kw: {})
        received = []
        def universe(config, sigs, forecasts, px, **kw):
            received.append(forecasts)
            return []
        monkeypatch.setattr(s, "build_universe_simple_scores", universe)
        monkeypatch.setattr(s, "build_candidate_simple_scores", lambda *a, **kw: [])
        s.build_simple_instrument_scores(local, [], pd.DataFrame({"etf_id": ["VWCE"]}), pd.DataFrame(),
                                         universe_revision="audit", cash_comparison_lookup={})
        assert len(received) == 1 and received[0].empty


def test_product_quality_stale_metric_unavailable(monkeypatch):
    """A02-F3: fresh KID evidence cannot mask a stale, future or undated product metric."""
    peers = {"ter": [0.001, 0.002, 0.003], "tracking_difference": [0.001, 0.002, 0.003]}
    kid = replace(_component("etf_product_quality"), source_id="priips_kid:" + "a" * 64)
    monkeypatch.setattr(s, "build_priips_kid_cost_evidence", lambda *a, **kw: kid)
    for vintage in (None, "2022-12-31", "2026-10-21"):
        for inputs in ({"ter": 0.002}, {"kid_record": object(), "tracking_difference": 0.002},
                       {"kid_record": object(), "premium_discount_bps": 5.0}):
            component = s._etf_product_quality_component({**inputs, "as_of_date": vintage}, peers, DAY)
            assert component.score_10 is None and not component.score_eligible
    fresh = s._etf_product_quality_component({"ter": 0.002, "as_of_date": DAY.isoformat()}, peers, DAY)
    assert fresh.score_10 is not None and fresh.score_eligible


@pytest.mark.parametrize("finding", ["A02-F4", "A02-F5", "A02-F6", "A02-F7", "A02-F8"])
def test_numeric_evidence_boundaries(finding):
    if finding == "A02-F4":
        for keys in (("risk",), ("liquidity_cost",), ("etf_exposure",), ("risk", "etf_exposure")):
            friction = s._risk_friction_score([_component(key) for key in keys], warnings=[])
            assert friction is None
            assert s.final_label_from_scores(9.0, 9.0, friction, warnings=[])[1] == "manual_review"
        assert s._risk_friction_score([_component("risk"), _component("liquidity_cost")], warnings=[]) == 8.0
    elif finding == "A02-F5":
        frame = pd.DataFrame({"etf_id": ["VWCE"] * 260, "date": [DAY.isoformat()] * 260, "adjusted_close": [100.0] * 260})
        for flag in (False, 0, None, float("nan"), "unknown", "missing_column", True, "true", 1):
            prices = frame if flag == "missing_column" else frame.assign(is_adjusted=flag)
            info = s._price_quality_lookup(prices)["VWCE"]
            expected = 9.0 if s._bool_like(flag) is True else 2.0
            assert s._data_quality_component(info, [], DAY).score_10 == expected
            row = pd.Series({**info, "latest_date": DAY.isoformat()})
            assert s._candidate_data_quality_component(row, [], DAY).score_10 == expected
        unknown = pd.Series({"latest_date": DAY.isoformat(), "rows": 260})
        assert s._candidate_data_quality_component(unknown, [], DAY).score_10 == 2.0
    elif finding == "A02-F6":
        lookup = {"__strategy__": {"score": 6.0, "quality": "medium", "wf": 20}}
        assert s._backtest_trust_info(lookup, "VWCE", candidate=False)["score"] == 5.0
        assert s._backtest_trust_info(lookup, "VWCE", candidate=True)["score"] is None
        assert s._backtest_trust_info({"__strategy__": {"score": None}}, "VWCE", candidate=False)["score"] is None
    elif finding == "A02-F7":
        info = {"top_weight_sum": 0.499, "largest_weight": 0.08, "total_weight_sum": 1.0,
                "holding_count": 100, "as_of_date": DAY.isoformat()}
        lower = s._etf_exposure_component(info, DAY)
        higher = s._etf_exposure_component({**info, "top_weight_sum": 0.500}, DAY)
        assert lower.score_10 >= higher.score_10 and lower.score_eligible
        partial = s._etf_exposure_component({**info, "total_weight_sum": 0.49}, DAY)
        assert partial.score_10 == pytest.approx(lower.score_10 - 1.0)
        stale = s._etf_exposure_component({**info, "as_of_date": "2022-12-31"}, DAY)
        (attached,) = s._attach_component_provenance([stale], DAY.isoformat(), DAY)
        assert attached.freshness_status == "stale" and not attached.score_eligible
        holdings = pd.DataFrame({"etf_id": ["VWCE"] * 20, "weight": [0.05] * 20, "as_of_date": [DAY.isoformat()] * 20})
        found = s._etf_exposure_lookup(holdings=holdings)["VWCE"]
        assert found["total_weight_sum"] == pytest.approx(1.0) and found["top_weight_sum"] == pytest.approx(0.5)
    else:
        frame = pd.DataFrame({"return_6m": [0.12, None], "return_3m": [0.10, 0.08]})
        reference = s._candidate_relative_reference(frame)
        assert reference == ("return_6m", 0.12)
        assert s._candidate_relative_strength_raw(frame.iloc[1], reference) is None
        matched = s._candidate_relative_strength_raw(pd.Series({"return_6m": 0.15, "return_3m": 0.08}), reference)
        assert matched == pytest.approx(tanh((0.15 - 0.12) / 0.15))
