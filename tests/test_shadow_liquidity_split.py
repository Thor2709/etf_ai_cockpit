"""The decision shadow guard scopes the price history once, not once per instrument (nightly run speed)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from etf_cockpit.analysis.decision import shadow_run
from etf_cockpit.application import signal_service
from etf_cockpit.core.config import load_config
from etf_cockpit.features import etf_economics
from etf_cockpit.features.etf_economics import calculate_etf_liquidity, price_history_by_instrument


def _rows(etf_id: str, days: int, **identity: object) -> pd.DataFrame:
    dates = pd.date_range("2026-09-01", periods=days, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "etf_id": etf_id,
            "close": 50.0 + pd.Series(range(days), dtype=float),
            "volume": 2_000.0,
            "currency": "EUR",
            "known_at": (dates + pd.Timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            **identity,
        }
    )


def _mixed_history() -> pd.DataFrame:
    """Rows that only the identity rule can sort: padded ids, a display-id-only row, conflicting columns."""

    ids = list(load_config().universe.enabled_ids[:3])
    first, second, third = ids
    padded = _rows(first, 30, instrument_id=f" {first} ", display_id=None)
    display_only = _rows(second, 30, instrument_id=None, display_id=second)
    display_only["etf_id"] = None
    conflicting = _rows(second, 5, instrument_id=third, display_id=None)  # names two instruments: in scope for neither
    revised = _rows(third, 30, instrument_id=third, display_id=third)
    late = revised.tail(3).assign(close=99.0, known_at="2026-10-30T00:00:00+00:00")  # a later revision of three closes
    other = _rows("NOT_ENABLED", 30, instrument_id=None, display_id=None)
    frame = pd.concat([revised, other, padded, conflicting, late, display_only], ignore_index=True)
    return frame.sample(frac=1.0, random_state=7)  # input order must not matter either


def test_lookup_gives_the_same_report_as_the_full_history() -> None:
    config = load_config()
    history = _mixed_history()
    rows_for = price_history_by_instrument(history)
    as_of = date(2026, 10, 20)
    for instrument in [*config.universe.enabled_ids[:3], "NOT_ENABLED", "MISSING"]:
        expected = calculate_etf_liquidity(config, history, instrument, as_of=as_of)
        assert repr(calculate_etf_liquidity(config, rows_for(instrument), instrument, as_of=as_of)) == repr(expected)
        assert len(rows_for(instrument)) < len(history)


def test_lookup_keeps_every_row_when_the_history_has_no_identity_column() -> None:
    history = _rows("ANY", 10).drop(columns=["etf_id"])
    assert price_history_by_instrument(history)("ANY").equals(history)


def test_shadow_guard_hands_each_instrument_only_its_own_rows(monkeypatch) -> None:
    config = load_config()
    history = _mixed_history()
    seen: dict[str, int] = {}
    captured: dict[str, object] = {}
    real = etf_economics.calculate_etf_liquidity

    def recording(config_, price_history, instrument, **kwargs):
        seen[instrument] = len(price_history)
        return real(config_, price_history, instrument, **kwargs)

    monkeypatch.setattr(etf_economics, "calculate_etf_liquidity", recording)
    monkeypatch.setattr(shadow_run, "run_decision_shadow", lambda *args, **kwargs: captured.update(kwargs))
    signal_service._run_decision_shadow_guard(config, [], decision_time=date(2026, 10, 20), price_history=history)

    assert set(seen) == set(config.universe.enabled_ids)
    assert max(seen.values()) < len(history)
    assert set(captured["liquidity_reports"]) == set(config.universe.enabled_ids)
