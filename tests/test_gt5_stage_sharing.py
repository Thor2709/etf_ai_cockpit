"""GT5: the three cost regimes of a backtest comparison share their cost-independent work, with identical results."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.backtest import engine
from etf_cockpit.backtest.engine import COST_REGIME_MODELLED, run_backtest, run_backtest_cost_regimes
from etf_cockpit.core.config import load_config
from etf_cockpit.data import classification, fx_data
from etf_cockpit.data.fx_data import EurRateBook
from etf_cockpit.data.sample_data import generate_sample_prices

END = pd.Timestamp("2026-06-26").date()


@pytest.fixture(scope="module")
def config():
    return load_config()


@pytest.fixture(scope="module")
def prices(config) -> pd.DataFrame:
    return generate_sample_prices(config, periods=340, end_date=END)


def test_cost_regimes_validate_each_cutoff_once_and_match_a_standalone_run(config, prices, monkeypatch) -> None:
    calls: list[int] = []
    original = engine.validate_prices

    def counting(frame, **kwargs):
        calls.append(len(frame))
        return original(frame, **kwargs)

    monkeypatch.setattr(engine, "validate_prices", counting)
    standalone = run_backtest(config, prices, rebalance_frequency_days=42, enforce_capacity=True)
    standalone_calls = len(calls)
    calls.clear()

    regimes = run_backtest_cost_regimes(config, prices, rebalance_frequency_days=42)

    assert standalone_calls > 0 and len(calls) == standalone_calls  # one data-quality check per cutoff, not per regime
    modelled = regimes.reports[COST_REGIME_MODELLED]
    pd.testing.assert_frame_equal(modelled.results, standalone.results)
    pd.testing.assert_frame_equal(modelled.signal_log, standalone.signal_log)
    pd.testing.assert_frame_equal(modelled.equity_curves, standalone.equity_curves)


def _fx_frame(rate: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "as_of_date": "2026-01-02",
                "base_currency": "USD",
                "quote_currency": "EUR",
                "rate": rate,
                "source": "ECB",
                "ingested_at": "2026-01-02T09:00:00Z",
            }
        ]
    )


def test_fx_cross_rate_is_validated_once_per_distinct_day_content_inside_the_scope(monkeypatch) -> None:
    computed: list[float] = []
    original = EurRateBook._compute_cross_rate

    def counting(dated, quote_day, currency):
        computed.append(float(dated["rate"].iloc[0]))
        return original(dated, quote_day, currency)

    monkeypatch.setattr(EurRateBook, "_compute_cross_rate", staticmethod(counting))
    sessions = [date(2026, 1, 2)]

    with fx_data.fx_cross_rate_memo():
        first = EurRateBook(_fx_frame(0.9), known_by="2026-01-10").series("USD", sessions).rates.iloc[0]
        second = EurRateBook(_fx_frame(0.9), known_by="2026-01-10").series("USD", sessions).rates.iloc[0]
        revised = EurRateBook(_fx_frame(0.8), known_by="2026-01-10").series("USD", sessions).rates.iloc[0]

    assert first == second == pytest.approx(0.9)
    assert revised == pytest.approx(0.8)  # a revised quote is different content and is never served from the memo
    assert computed == [0.9, 0.8]


def test_fx_cross_rate_memo_exists_only_inside_the_scope_and_is_gone_after_exit_or_error(monkeypatch) -> None:
    computed: list[float] = []
    original = EurRateBook._compute_cross_rate

    def counting(dated, quote_day, currency):
        computed.append(float(dated["rate"].iloc[0]))
        return original(dated, quote_day, currency)

    monkeypatch.setattr(EurRateBook, "_compute_cross_rate", staticmethod(counting))
    sessions = [date(2026, 1, 2)]

    def read() -> float:
        return float(EurRateBook(_fx_frame(0.9), known_by="2026-01-10").series("USD", sessions).rates.iloc[0])

    assert fx_data._CROSS_RATE_MEMO.get() is None
    read()
    read()
    assert computed == [0.9, 0.9]  # outside a scope nothing is remembered

    with fx_data.fx_cross_rate_memo():
        assert fx_data._CROSS_RATE_MEMO.get() == {}
        read()
        assert len(fx_data._CROSS_RATE_MEMO.get()) == 1
    assert fx_data._CROSS_RATE_MEMO.get() is None

    with pytest.raises(RuntimeError, match="boom"), fx_data.fx_cross_rate_memo():
        read()
        raise RuntimeError("boom")
    assert fx_data._CROSS_RATE_MEMO.get() is None
    computed.clear()
    read()
    assert computed == [0.9]  # the earlier scope left nothing behind


def test_backtest_scope_installs_and_removes_every_memo(config, prices, monkeypatch) -> None:
    seen: dict[str, object] = {}
    original = engine.generate_signals

    def spying(*args, **kwargs):
        seen.setdefault("fx", fx_data._CROSS_RATE_MEMO.get() is not None)
        seen.setdefault("classification", classification._STATE_MEMO.get() is not None)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, "generate_signals", spying)
    run_backtest(config, prices, rebalance_frequency_days=84)
    assert seen == {"fx": True, "classification": True}
    assert fx_data._CROSS_RATE_MEMO.get() is None and classification._STATE_MEMO.get() is None
    assert engine._STAGE_SHARE.get() is None


def test_classification_state_is_read_once_per_instrument_only_inside_the_memo_scope(monkeypatch, tmp_path: Path) -> None:
    reads: list[str] = []

    def fake_context(root, instrument_id, **_kwargs):
        reads.append(instrument_id)
        return SimpleNamespace(
            classification_status="resolved",
            version_id=f"v{len(reads)}",
            score_invalidation_token="token",
            invalidated_score_keys=(),
        )

    monkeypatch.setattr(classification, "read_instrument_context", fake_context)

    first = classification.classification_score_state(tmp_path, "ETF.A")
    second = classification.classification_score_state(tmp_path, "ETF.A")
    assert reads == ["ETF.A", "ETF.A"] and first["version_id"] != second["version_id"]  # no reuse outside a scope

    reads.clear()
    with classification.classification_state_memo():
        inside = [classification.classification_score_state(tmp_path, "ETF.A") for _ in range(3)]
        classification.classification_score_state(tmp_path, "ETF.B")
    assert reads == ["ETF.A", "ETF.B"]
    assert {item["version_id"] for item in inside} == {"v1"}

    classification.classification_score_state(tmp_path, "ETF.A")
    assert reads == ["ETF.A", "ETF.B", "ETF.A"]  # the scope ended: a later change is visible again
