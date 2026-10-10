"""Missing signal evidence stays unavailable in CLI, JSON and explanations."""

from dataclasses import replace
import importlib
import json
from math import isfinite
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.application.signal_service import SignalService
from etf_cockpit.core.config import load_config
from etf_cockpit.signals.explanations import explain_signal
from etf_cockpit.signals.signal_pipeline import _signal_to_json


def test_signal_trace_is_strict_json_and_explanation_matches_published_score():
    signals = SignalService(load_config()).generate_signals()
    assert signals
    for signal in signals:
        if isfinite(signal.total_score):
            assert f"Total score {signal.total_score:.2f}" in signal.reason_long
        if isfinite(signal.confidence):
            assert f"confidence {signal.confidence:.2f}" in signal.reason_long
    missing = replace(signals[0], confidence=float("nan"), total_score=float("nan"))
    payload = _signal_to_json(missing)
    loaded = json.loads(json.dumps(payload, allow_nan=False))
    assert loaded["confidence"] is None and loaded["total_score"] is None
    assert loaded["execution_allowed"] is False


def test_explanation_preserves_zero_and_labels_absent_evidence():
    _, text = explain_signal(pd.Series({
        "total_score": 0.0, "confidence": float("nan"),
        "score_momentum": None, "score_trend": float("inf"), "score_risk": 0.0,
    }), "manual_review", [])
    assert "Total score 0.00 with confidence unavailable" in text
    assert "Momentum unavailable, trend unavailable, risk 0.00" in text
    assert "Toto unavailable, TimesFM unavailable, portfolio drift unavailable" in text
    assert "nan" not in text and "inf" not in text


def test_signal_runner_prints_unavailable_confidence(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    runner = importlib.import_module("run_signals")
    config = load_config()
    signal = SimpleNamespace(
        etf_id=config.universe.enabled_ids[0], action="manual_review",
        confidence=float("nan"), total_score=0.0, blocked_by=[],
    )
    monkeypatch.setattr(sys, "argv", ["run_signals.py"])
    monkeypatch.setattr(runner, "require_cached_inputs", lambda *paths: None)
    monkeypatch.setattr(runner, "load_config", lambda: config)
    monkeypatch.setattr(runner, "SignalService", lambda config: SimpleNamespace(generate_signals=lambda **kwargs: [signal]))
    assert runner.main() == 0
    assert "confidence=unavailable" in capsys.readouterr().out
