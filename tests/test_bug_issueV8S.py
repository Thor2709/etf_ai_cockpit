"""V8S: score pipeline V8 items (history, canonical scoring, simple scores, publication, features, signals)."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application import scoreboard_publication
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import DataQualityReport, DatasetMetadata
from etf_cockpit.data.score_history import append_score_run, score_history_frame
from etf_cockpit.features.feature_pipeline import robust_zscore
from etf_cockpit.models.ensemble import BASELINE_SOURCE_HEURISTIC
from etf_cockpit.signals import signal_pipeline
from etf_cockpit.signals import simple_scores as ss
from etf_cockpit.signals.canonical_scoring import (
    CanonicalComponent,
    build_canonical_score,
    canonical_score_from_signal_row,
)


def _component(key: str, raw: float | None, role: str = "attractiveness", *, status: str = "ok",
               authority: str = "vendor_unofficial", freshness: str = "ok", source: str | None = None) -> CanonicalComponent:
    return CanonicalComponent(
        key=key, raw_metric=raw, score_role=role, peer_group="synthetic", source_id=source or f"source:{key}",
        source_authority=authority, freshness_status=freshness, uncertainty="low", status=status, explanation=f"{key} explanation",
    )


# --- score history -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), 10.5, -0.1])
def test_n004_history_write_rejects_nonfinite_and_out_of_range_scores(tmp_path: Path, bad: float) -> None:
    frame = pd.DataFrame({"instrument_id": ["A", "B"], "final_combined_score_10": [7.0, bad]})
    with pytest.raises(ValueError):
        append_score_run(frame, "run-1", "2026-07-10", root=tmp_path)
    assert not (tmp_path / "data" / "derived" / "score_history.parquet").exists()


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), 12.0, -3.0])
def test_c4_n002_history_reader_drops_nonfinite_and_out_of_range_legacy_rows(tmp_path: Path, bad: float) -> None:
    path = tmp_path / "data" / "derived" / "score_history.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"run_id": "r", "instrument_id": "A", "final_combined_score_10": 8.0},
            {"run_id": "r", "instrument_id": "B", "final_combined_score_10": bad},
        ]
    ).to_parquet(path, index=False)
    history = score_history_frame(root=tmp_path)
    assert list(history["instrument_id"]) == ["A"]


def test_c5_n001_partial_run_is_reported_not_silently_persisted(tmp_path: Path) -> None:
    frame = pd.DataFrame({"instrument_id": ["A", "B", None], "final_combined_score_10": [7.0, "bad", 6.0]})
    result = append_score_run(frame, "run-1", "2026-07-10", root=tmp_path)
    assert result.rows_written == 1
    assert result.rows_submitted == 3
    assert result.rows_dropped == 2
    assert result.complete is False
    full = append_score_run(
        pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [7.0]}), "run-2", "2026-07-10", root=tmp_path
    )
    assert full.rows_dropped == 0 and full.complete is True


# --- canonical scoring -------------------------------------------------------------------------------------------

def test_b_c2_s21_n001_signal_row_maps_stock_value_and_quality() -> None:
    config = load_config()
    row = {
        "etf_id": "ABC", "asset_type": "stock", "price_freshness": "ok",
        "score_momentum": 0.2, "score_trend": 0.3, "score_risk": 0.4, "cost_penalty": 0.0,
        "score_stock_value": 0.4, "score_stock_quality": 0.2,
    }
    score = canonical_score_from_signal_row(row, config, "2026-07-10")
    components = {item["key"]: item for item in score.components}
    assert components["stock_value"]["raw_metric"] == pytest.approx(0.4)
    assert "stock_quality" in components
    # without the supplied evidence the stock components are explicit, ineligible placeholders
    bare = canonical_score_from_signal_row({k: v for k, v in row.items() if not k.startswith("score_stock")}, config, "2026-07-10")
    bare_components = {item["key"]: item for item in bare.components}
    assert bare_components["stock_value"]["score_eligible"] is False and bare_components["stock_value"]["raw_metric"] is None


def test_b_c2_s21_n002_zero_weight_components_do_not_raise_confidence() -> None:
    base = [_component("momentum", 0.5), _component("trend", 0.4), _component("risk", 0.3, "risk_implementation")]
    without = build_canonical_score(instrument_id="E", asset_type="ETF", decision_time="2026-07-10", components=base)
    # stock_value carries zero weight in the ETF policy: it must not change the confidence
    zero_weight = _component("stock_value", 0.9, authority="official_filing")
    with_zero = build_canonical_score(instrument_id="E", asset_type="ETF", decision_time="2026-07-10", components=[*base, zero_weight])
    assert with_zero.evidence_confidence_10 == without.evidence_confidence_10
    assert with_zero.coverage == without.coverage


def test_b_c2_s21_n003_duplicate_component_prefers_the_eligible_candidate() -> None:
    bad = _component("momentum", None, status="unavailable")
    good = _component("momentum", 0.6)
    others = [_component("trend", 0.4)]
    first_bad = build_canonical_score(instrument_id="E", asset_type="ETF", decision_time="2026-07-10", components=[bad, good, *others])
    first_good = build_canonical_score(instrument_id="E", asset_type="ETF", decision_time="2026-07-10", components=[good, bad, *others])
    assert first_bad.attractiveness_10 == first_good.attractiveness_10
    assert first_bad.attractiveness_10 is not None
    assert first_bad.coverage == first_good.coverage
    assert "duplicate_component:momentum" in first_bad.warnings
    # two eligible duplicates keep the first, deterministically
    other = _component("momentum", -0.6)
    a = build_canonical_score(instrument_id="E", asset_type="ETF", decision_time="2026-07-10", components=[good, other, *others])
    assert a.attractiveness_10 == first_good.attractiveness_10


# --- simple scores ----------------------------------------------------------------------------------------------

def _simple_component(key: str = "momentum", *, freshness: str | None = "ok", as_of: str | None = "2026-07-10",
                      source_id: str | None = "yfinance:prices", score: float | None = 6.0) -> ss.SimpleScoreComponent:
    return ss.SimpleScoreComponent(
        key=key, label=key, score_10=score, raw_score=None if score is None else (score - 5.0) / 5.0, status="OK",
        explanation="e", good_score="g", why="w", source_id=source_id, as_of_date=as_of, freshness_status=freshness,
    )


def _simple_score(components: list[ss.SimpleScoreComponent], **fields: object) -> ss.SimpleInstrumentScore:
    return ss.SimpleInstrumentScore(
        instrument_key="ETF1", display_id="ETF1", source_group="primary", asset_type="etf", name="Example",
        yahoo_symbol="ETF1.DE", latest_date="2026-07-10", latest_price=100.0, final_score_10=6.0, decision="watchlist",
        one_line_reason="r", components=components, warnings=[], **fields,
    )


def test_b_c3_s21_n001_future_dated_component_is_not_fresh_even_with_a_preset_status() -> None:
    future = _simple_component(freshness="ok", as_of="2026-08-01")
    [result] = ss._attach_component_provenance([future], "2026-07-10", date(2026, 7, 10))
    assert result.freshness_status == "unavailable"
    current = _simple_component(freshness="ok", as_of="2026-07-10")
    [kept] = ss._attach_component_provenance([current], "2026-07-10", date(2026, 7, 10))
    assert kept.freshness_status == "ok"


def test_b_c3_s21_n003_typed_unavailable_authority_is_not_rederived_as_complete() -> None:
    from etf_cockpit.governance.gate_policy import _diagnostic_decision

    decision = _diagnostic_decision("policy unavailable")
    assert decision.analysis_status == "unavailable"
    score = _simple_score([_simple_component()], authority_decision=decision)
    assert score.final_score_10 == 6.0 and not score.warnings
    assert score.analysis_status == "unavailable"


def test_b_c3_s24_n002_stale_or_future_allowed_source_does_not_pass_the_evidence_gate() -> None:
    def evidence_passed(component: ss.SimpleScoreComponent) -> bool:
        decision = ss._attach_authority(_simple_score([component])).authority_decision
        return next(gate for gate in decision.gates if gate.gate_id == "evidence").passed

    assert evidence_passed(_simple_component()) is True
    assert evidence_passed(_simple_component(freshness="stale")) is False
    assert evidence_passed(_simple_component(freshness="unavailable")) is False
    assert evidence_passed(_simple_component(as_of=None)) is False


@pytest.mark.parametrize("value", [12.0, -1.0, float("inf")])
def test_b_c5_s21_n002_out_of_range_optional_component_is_unavailable_not_clamped(value: float) -> None:
    component = ss._optional_score_component("stock_value", value, "why", authority="medium")
    assert component.score_10 is None and component.raw_score is None and component.status == "N/A"
    ok = ss._optional_score_component("stock_value", 7.5, "why", authority="medium")
    assert ok.score_10 == 7.5 and ok.status == "OK"
    edge = ss._optional_score_component("stock_value", 10.0, "why", authority="medium")
    assert edge.score_10 == 10.0


# --- features ---------------------------------------------------------------------------------------------------

def test_c_c3_s13_n002_robust_zscore_keeps_nonfinite_values_unavailable() -> None:
    values = pd.Series([1.0, 2.0, 3.0, 4.0, float("inf"), float("-inf"), float("nan")])
    result = robust_zscore(values)
    assert result.iloc[4:].isna().all()
    finite = robust_zscore(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert np.allclose(result.iloc[:4], finite)  # infinities do not distort the finite members' scale
    assert result.iloc[:4].notna().all() and result.abs().max() <= 3.0


# --- publication ------------------------------------------------------------------------------------------------

def _board_and_history(tmp_path: Path) -> tuple[Path, Path, pd.DataFrame]:
    derived = tmp_path / "data" / "derived"
    derived.mkdir(parents=True)
    board_path = derived / "scoreboard.parquet"
    board = pd.DataFrame({"instrument_id": ["AAA"], "current_price": [42.0]})
    board.to_parquet(board_path, index=False)
    history_path = derived / "score_history.parquet"
    pd.DataFrame(
        [
            {"run_id": "run-mine", "run_completed_at": "2026-07-10T10:00:00Z", "snapshot_hash": "a" * 64},
            {"run_id": "run-other", "run_completed_at": "2026-07-10T11:00:00Z", "snapshot_hash": "b" * 64},
        ]
    ).to_parquet(history_path, index=False)
    return board_path, history_path, board


def test_c_c5_s15_n001_binding_uses_the_current_run_not_the_newest_history(tmp_path: Path) -> None:
    board_path, history_path, board = _board_and_history(tmp_path)
    binding = scoreboard_publication._record_scoreboard_publication_binding(
        board_path, history_path, board, run_id="run-mine"
    )
    assert binding["run_id"] == "run-mine"
    assert binding["score_snapshot_hash"] == "a" * 64
    assert binding["scoreboard_sha256"] == hashlib.sha256(board_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        scoreboard_publication._record_scoreboard_publication_binding(board_path, history_path, board, run_id="run-missing")


# --- signal pipeline --------------------------------------------------------------------------------------------

def _run_signals(monkeypatch: pytest.MonkeyPatch, rows: list[dict], *, canonical_composite: float | None,
                 gate_calls: list[float] | None = None, action: str = "hold") -> list:
    config = load_config()
    ids = [row["etf_id"] for row in rows]
    scores = pd.DataFrame([
        {"total_score": 0.4, "confidence": 0.8, "current_weight": 0.0, "target_weight": 0.2, "hard_band": 0.05,
         "momentum_20d": 0.1, "relative_strength_60d": 0.1, "momentum_60d": 0.1, "momentum_120d": 0.1, "trend_200": 1.0,
         "ewma_vol_ann": 0.1, "score_baseline_source": BASELINE_SOURCE_HEURISTIC, **row}
        for row in rows
    ])
    canonical = SimpleNamespace(
        legacy_composite_raw=canonical_composite, decision_distribution={}, attractiveness_10=8.0, expected_return_10=8.0,
        risk_implementation_10=8.0, evidence_confidence_10=8.0, coverage=1.0, formula_version="t", formula_checksum="a" * 64,
        source_vintage_hash="v",
    )

    def gates(_config, _row, _report, **kwargs):
        if gate_calls is not None:
            gate_calls.append(kwargs["cash_weight"])
        return [], []

    patches = {
        "component_scores": lambda *a, **k: scores.copy(),
        "allocation_frame": lambda *a, **k: pd.DataFrame([{"etf_id": i, "drift": 0.1, "role": "core", "name": i} for i in ids]),
        "canonical_score_from_signal_row": lambda *a, **k: canonical,
        "portfolio_value": lambda _h: 1000.0,
        "preliminary_action": lambda *a, **k: action,
        "proposed_new_weight": lambda *a, **k: 0.2,
        "evaluate_risk_gates": gates,
        "suggested_trade_value": lambda *a, **k: 10_000.0,
        "estimate_execution_cost": lambda *a, **k: SimpleNamespace(total_cost_bps=1.0, model_id="t", data_quality="t", capacity_eur=1000.0),
        "_cost_stress_metrics": lambda *a, **k: {},
        "row_components": lambda _r: {},
        "explain_signal": lambda *a, **k: ("Review", "Detail"),
        "classification_score_state": lambda *a, **k: {"status": "current", "version_id": "t", "invalidation_token": "t"},
        "_structure_cap_for_row": lambda *a, **k: 1.0,
    }
    for name, value in patches.items():
        monkeypatch.setattr(signal_pipeline, name, value)
    meta = DatasetMetadata(
        source_name="prices", source_type="prices", as_of_date=date(2026, 3, 2), ingested_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        currency="EUR", timezone="UTC", provider_or_manual_source="fixture", checksum="a" * 64, staleness_status="ok", age_days=0,
    )
    return signal_pipeline.generate_signals(
        config, pd.DataFrame([{"etf_id": i} for i in ids]), pd.DataFrame([{"etf_id": i, "current_weight": 0.0} for i in ids]),
        DataQualityReport(as_of_date=date(2026, 3, 2), issues=[], dataset_metadata=[meta]),
        as_of_date=date(2026, 3, 2), run_id="v8s", publish=False, decision_time=pd.Timestamp("2026-03-02"),
        structure_confidence_caps={i: 1.0 for i in ids},
    )


def test_b_c4_s22_n001_canonical_composite_is_used_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # DEFERRED: the raw-row fallback is the deterministic price composite on every run without forecast weights
    # (the canonical legacy composite is then None for all rows); failing it closed changes the goldens/backtest
    # wholesale and needs an owner decision. This guard pins the present, canonical-first behaviour.
    [available] = _run_signals(monkeypatch, [{"etf_id": "AAA"}], canonical_composite=0.25)
    assert available.total_score == pytest.approx(0.25)


def test_c_c5_s13_n001_cash_is_reserved_across_candidate_buys(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []
    signals = _run_signals(
        monkeypatch,
        [{"etf_id": "AAA", "total_score": 0.9}, {"etf_id": "BBB", "total_score": 0.8}, {"etf_id": "CCC", "total_score": 0.7}],
        canonical_composite=0.5, gate_calls=calls, action="buy",
    )
    assert [signal.action for signal in signals]  # all three were evaluated
    assert calls == pytest.approx([1.0, 0.8, 0.6])
