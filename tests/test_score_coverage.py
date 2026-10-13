from __future__ import annotations

from datetime import date

import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import ComponentScores, SignalResult
from etf_cockpit.signals import simple_scores as simple_scores_module
from etf_cockpit.signals.simple_scores import build_universe_simple_scores, simple_scoreboard_frame
from scripts.score_coverage_report import _first_failure


def _price_history(instrument_id: str, currency: str) -> pd.DataFrame:
    as_of = date(2026, 10, 8)
    dates = pd.bdate_range(end=as_of, periods=260)
    prices = pd.Series(range(100, 100 + len(dates)), dtype=float)
    return pd.DataFrame(
        {
            "etf_id": instrument_id,
            "date": dates,
            "open": prices,
            "high": prices * 1.01,
            "low": prices * 0.99,
            "close": prices,
            "adjusted_close": prices,
            "volume": 100_000,
            "currency": currency,
            "is_adjusted": True,
        }
    )


def _signal(instrument_id: str) -> SignalResult:
    return SignalResult(
        run_id="score-coverage-test",
        signal_date=date(2026, 10, 8),
        etf_id=instrument_id,
        action="no_trade",
        confidence=0.5,
        total_score=0.2,
        components=ComponentScores(
            momentum=0.2,
            trend=0.1,
            risk=0.1,
            rebalance=0.0,
            relative_strength=0.3,
            toto=0.0,
            timesfm=0.0,
            baseline_ml=0.0,
            chatgpt_thesis=0.0,
            cost_penalty=0.0,
            turnover_penalty=0.0,
            concentration_penalty=0.0,
        ),
        blocked_by=[],
        warnings=[],
        reason_short="Test signal from available price history.",
        reason_long="Test signal from available price history.",
        horizon_primary="1-3 months",
    )


def _score_for(instrument_id: str, monkeypatch) -> object:
    config = load_config()
    identity = config.universe.by_id()[instrument_id]
    monkeypatch.setattr(simple_scores_module, "_etf_exposure_lookup", lambda: {})
    return build_universe_simple_scores(
        config,
        [_signal(instrument_id)],
        pd.DataFrame(),
        _price_history(instrument_id, identity.currency),
    )[0]


def test_etf_with_prices_and_missing_holdings_gets_partial_score(monkeypatch) -> None:
    score = _score_for("VWCE", monkeypatch)
    row = simple_scoreboard_frame([score]).iloc[0]

    assert score.final_score_10 is not None
    assert 0.0 < score.score_coverage < 1.0
    assert "etf_exposure" in score.missing_components
    assert row["final_combined_score_10"] == score.final_score_10
    assert row["coverage"] == score.score_coverage
    assert "etf_exposure" in row["missing_components"].split("|")


def test_stock_with_prices_only_gets_partial_score(monkeypatch) -> None:
    score = _score_for("MSFT", monkeypatch)

    assert score.final_score_10 is not None
    assert 0.0 < score.score_coverage < 1.0
    assert {"stock_value", "stock_quality", "analyst_revision"}.issubset(score.missing_components)


def test_identity_conflict_still_blocks_score() -> None:
    from etf_cockpit.signals.simple_scores import (
        SimpleInstrumentScore,
        _identity_projection_conflict_reason,
        _with_canonical_score,
        _with_identity_conflict,
    )

    identity_reason = _identity_projection_conflict_reason(
        {
            "identity_conflicts": [
                {"requires_manual_review": True, "reason": "Provider symbols conflict for the resolved identity."}
            ]
        }
    )
    score = SimpleInstrumentScore(
        instrument_key="configured:VWCE",
        display_id="VWCE",
        source_group="Primary tier",
        asset_type="ETF",
        name="VWCE",
        yahoo_symbol="VWCE.DE",
        latest_date="2026-10-08",
        latest_price=100.0,
        final_score_10=7.0,
        decision="Watchlist",
        one_line_reason="Available price evidence.",
        components=[],
        warnings=[],
    )

    blocked = _with_canonical_score(_with_identity_conflict(score, identity_reason))

    assert blocked.final_score_10 is None
    assert blocked.identity_conflict_reason == "Provider symbols conflict for the resolved identity."
    assert blocked.canonical_score is None


def test_no_price_history_reports_obtain_step_and_reason() -> None:
    identity = load_config().universe.by_id()["VWCE"]

    reason = _first_failure("VWCE", identity, 0, 0, None, None, None, None)

    assert reason == "obtain: no local price rows for VWCE in data/clean/prices.parquet"
