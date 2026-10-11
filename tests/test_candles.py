from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.analysis.candles import (
    backtest_candle_templates,
    calculate_candle_features,
    detect_candle_templates,
    score_candle_contribution,
    validate_ohlcv,
)
from etf_cockpit.app.pages import instrument_detail as instrument_detail_page_module
from etf_cockpit.application.instrument_detail_view import InstrumentDetailViewModel, _candle_evidence_panel


def _candle(day: str, *, open_: float, high: float, low: float, close: float, volume: float = 100.0) -> dict[str, object]:
    return {
        "date": day,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def test_valid_ohlcv_fixture_passes_and_features_are_available() -> None:
    candle = _candle("2026-01-02", open_=10.0, high=10.5, low=9.5, close=10.25)

    validation = validate_ohlcv(candle)
    features = calculate_candle_features(candle)

    assert validation["valid"] is True
    assert validation["reasons"] == ()
    assert features["status"] == "available"
    assert features["body_fraction"] == pytest.approx(0.25)
    assert features["execution_allowed"] is False


def test_instrument_detail_accepts_raw_ohlc_with_adjusted_close() -> None:
    prices = pd.DataFrame(
        [
            {
                "instrument_id": "TEST",
                **_candle("2026-01-02", open_=100.0, high=101.0, low=99.0, close=100.0),
                "adjusted_close": 50.0,
                "known_at": "2026-01-02T21:00:00Z",
            }
        ]
    )

    panel = _candle_evidence_panel(SimpleNamespace(prices=prices), "TEST", "2026-01-02")

    assert panel["status"] == "available"
    assert panel["latest_candle"]["price_basis"] == "adjusted_ohlc_from_same_row_adjustment"
    assert panel["latest_candle"]["close"] == pytest.approx(50.0)


@pytest.mark.parametrize(
    ("changes", "expected_reason"),
    [
        ({"high": 9.0, "low": 10.0}, "high_below_low"),
        ({"open": 11.0}, "open_outside_low_high"),
        ({"close": 11.0}, "close_outside_low_high"),
        ({"open": 0.0}, "non_positive_open"),
    ],
)
def test_invalid_ohlcv_is_rejected_with_reason(changes: dict[str, float], expected_reason: str) -> None:
    candle = _candle("2026-01-02", open_=10.0, high=10.5, low=9.5, close=10.25)
    candle.update(changes)

    validation = validate_ohlcv(candle)

    assert validation["valid"] is False
    assert expected_reason in validation["reasons"]


def test_gap_and_rejection_templates_are_detected() -> None:
    previous = _candle("2026-01-01", open_=99.5, high=100.5, low=99.0, close=100.0)
    gap_up = _candle("2026-01-02", open_=102.0, high=103.0, low=101.5, close=102.5)
    rejection = _candle("2026-01-03", open_=100.0, high=100.2, low=98.8, close=100.1)

    gap_templates = detect_candle_templates(gap_up, previous)
    rejection_templates = detect_candle_templates(rejection)

    assert "gap_up" in gap_templates["patterns"]
    assert "bullish_rejection" in rejection_templates["patterns"]
    assert gap_templates["action"] == "none"
    assert rejection_templates["action_authority"] is False


def test_same_bar_stop_and_target_are_reported_without_exit_fill() -> None:
    signal = _candle("2026-01-01", open_=100.0, high=100.5, low=98.0, close=100.4)
    execution = _candle("2026-01-02", open_=100.0, high=105.0, low=95.0, close=100.0)

    result = backtest_candle_templates([signal, execution], stop_pct=0.02, target_pct=0.04)

    assert result["execution_basis"] == "next_bar_open"
    assert result["ambiguity_count"] == 1
    assert result["rows"][0]["status"] == "ambiguous"
    assert result["rows"][0]["entry_price"] == pytest.approx(100.0)
    assert result["rows"][0]["exit_price"] is None
    assert result["rows"][0]["fill_assumed"] is False
    assert "no ambiguous exit fill assumed" in result["ambiguity_warning"]


def test_later_holding_bar_stop_and_target_are_reported_as_ambiguous() -> None:
    signal = _candle("2026-01-01", open_=100.0, high=100.5, low=98.0, close=100.0)
    entry = _candle("2026-01-02", open_=100.0, high=101.0, low=99.8, close=100.8)
    later_ambiguous = _candle("2026-01-03", open_=100.8, high=105.0, low=97.0, close=100.0)

    result = backtest_candle_templates([signal, entry, later_ambiguous], stop_pct=0.02, target_pct=0.04)

    assert result["ambiguity_count"] == 1
    assert result["rows"][0]["status"] == "ambiguous"
    assert result["rows"][0]["execution_date"] == "2026-01-02"
    assert result["rows"][0]["ambiguity_date"] == "2026-01-03"
    assert result["rows"][0]["exit_price"] is None
    assert result["rows"][0]["fill_assumed"] is False


def test_score_is_capped_and_patterns_never_create_actions() -> None:
    templates = {
        "status": "available",
        "patterns": ("gap_up", "bullish_rejection", "gap_up", "bullish_rejection"),
    }

    score = score_candle_contribution(templates, cap=0.2)

    assert abs(score["contribution"]) <= score["cap"]
    assert score["contribution"] == pytest.approx(0.2)
    assert score["action"] == "none"
    assert score["action_authority"] is False


def test_backtest_enters_on_next_bar_open() -> None:
    signal = _candle("2026-01-01", open_=100.0, high=100.5, low=98.0, close=100.4)
    execution = _candle("2026-01-02", open_=101.0, high=102.0, low=100.5, close=101.5)

    result = backtest_candle_templates([signal, execution])

    assert result["rows"][0]["execution_date"] == "2026-01-02"
    assert result["rows"][0]["entry_price"] == pytest.approx(101.0)
    assert result["rows"][0]["execution_basis"] == "next_bar_open"


def test_candle_selector_applies_decision_and_knownness_cutoffs() -> None:
    prices = pd.DataFrame(
        [
            {
                "instrument_id": "TEST",
                **_candle("2026-01-01", open_=100.0, high=100.5, low=98.0, close=100.4),
                "known_at": "2026-01-01T23:00:00Z",
            },
            {
                "instrument_id": "TEST",
                **_candle("2026-01-02", open_=101.0, high=102.0, low=100.5, close=101.5),
                "known_at": "2026-01-02T23:00:00Z",
            },
            {
                "instrument_id": "TEST",
                **_candle("2026-01-03", open_=102.0, high=103.0, low=101.5, close=102.5),
                "known_at": "2026-01-04T00:00:00Z",
            },
        ]
    )
    snapshot = SimpleNamespace(prices=prices)

    panel = _candle_evidence_panel(snapshot, "TEST", "2026-01-03")

    assert panel["status"] == "available"
    assert panel["latest_candle"]["date"] == "2026-01-02"
    assert panel["context_filter_status"] == "applied: event-date and source-knowledge cutoffs"


def _walk_controls(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)


def test_instrument_detail_renders_candle_evidence_section(monkeypatch: pytest.MonkeyPatch) -> None:
    model = InstrumentDetailViewModel(
        instrument_id="TEST",
        display_name="Test instrument",
        status="ready",
        identity={"instrument_id": "TEST", "status": "available"},
        sections={
            "candle_evidence": {
                "status": "available",
                "latest_candle": {"date": "2026-01-02", "close": 101.5},
                "template": "bullish_rejection",
                "context_filter_status": "passed",
                "assessment": "confirms",
                "score_contribution": 0.15,
                "score_cap": 0.25,
                "backtest_count": 1,
                "ambiguity_warning": "No same-bar stop/target ambiguity reported.",
                "execution_allowed": False,
            },
        },
    )
    monkeypatch.setattr(instrument_detail_page_module, "build_instrument_detail", lambda *_args, **_kwargs: model)
    monkeypatch.setattr(instrument_detail_page_module, "bitemporal_history_summary", lambda _instrument_id: {"status": "unavailable"})
    monkeypatch.setattr(instrument_detail_page_module, "contradiction_digest_records", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(instrument_detail_page_module, "_instrument_alerts_panel", lambda _model, _state: ft.Text("alerts"))
    monkeypatch.setattr(instrument_detail_page_module, "_render_feature_driver_panel", lambda _value: ft.Text("drivers"))
    monkeypatch.setattr(instrument_detail_page_module, "_render_crowding_attribution_panel", lambda _value: ft.Text("crowding"))
    monkeypatch.setattr(instrument_detail_page_module, "render_etf_disclosure_panel", lambda _model: ft.Text("disclosure"))
    monkeypatch.setattr(instrument_detail_page_module, "render_etf_structure_panel", lambda _model: ft.Text("structure"))
    monkeypatch.setattr(instrument_detail_page_module, "render_news_context_panel", lambda _model: ft.Text("news"))
    monkeypatch.setattr(instrument_detail_page_module, "render_news_contradiction_panel", lambda *_args: ft.Text("contradictions"))
    monkeypatch.setattr(instrument_detail_page_module, "render_event_calendar_panel", lambda _model: ft.Text("events"))
    monkeypatch.setattr(instrument_detail_page_module, "_valuation_workspace", lambda *_args: ft.Text("valuation"))
    state = SimpleNamespace(
        snapshot=SimpleNamespace(
            data_report=SimpleNamespace(as_of_date="2026-01-02"),
            prices=pd.DataFrame(),
        ),
        selected_etf="TEST",
        export_audit_packet=lambda: "unused",
    )

    page = instrument_detail_page_module.instrument_detail_page(None, state)
    controls = list(_walk_controls(page))
    texts = [getattr(control, "value", "") for control in controls]
    keys = [getattr(control, "key", None) for control in controls]

    assert "Candle Evidence" in texts
    assert "instrument-detail.candle-evidence" in keys
    assert any("same-bar exits" in str(text) for text in texts)
