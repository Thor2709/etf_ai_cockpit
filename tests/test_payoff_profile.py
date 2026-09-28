from __future__ import annotations

import inspect
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages.backtests import backtests_page
from etf_cockpit.app.selectors.instrument_detail import (
    _TAIL_DIAGNOSTIC_FIELDS,
    _strategy_tail_diagnostics,
)
from etf_cockpit.backtest.metrics import _payoff_diagnostics


def test_payoff_profile_classifies_populated_return_distributions() -> None:
    trend_like = pd.Series([-0.01] * 16 + [0.03] * 14)
    mean_reversion_like = pd.Series([0.01] * 18 + [-0.02] * 12)
    mixed = pd.Series([0.01, -0.01] * 10)
    insufficient = pd.Series([0.01, -0.01] * 9 + [0.01])

    assert _payoff_diagnostics(trend_like)["payoff_profile"] == "trend-like"
    assert _payoff_diagnostics(mean_reversion_like)["payoff_profile"] == "mean-reversion-like"
    assert _payoff_diagnostics(mixed)["payoff_profile"] == "mixed"
    assert _payoff_diagnostics(insufficient)["payoff_profile"] == "insufficient data"


def test_payoff_diagnostics_uses_sample_skew_and_fails_closed() -> None:
    returns = pd.Series([-0.02, -0.01, 0.005, 0.01, 0.02] * 4)
    diagnostics = _payoff_diagnostics(returns)

    assert diagnostics["skew"] == round(float(returns.skew()), 6)
    assert _payoff_diagnostics(pd.Series([0.01] * 20))["skew"] is None
    assert _payoff_diagnostics(pd.Series([0.01, -0.01] * 9 + [0.01]))["skew"] is None


def test_payoff_diagnostics_warns_when_losses_dominate_wins() -> None:
    diagnostics = _payoff_diagnostics(pd.Series([0.005] * 10 + [-0.02] * 10))

    assert diagnostics["losses_dominate_wins"] is True
    assert diagnostics["loss_dominance_warning"] == "losses_dominate_wins"
    assert diagnostics["expected_value_per_period"] < 0


def test_payoff_profile_disclaimer_is_explicit_and_non_executable() -> None:
    disclaimer = _payoff_diagnostics(pd.Series([0.01, -0.01]))["payoff_profile_disclaimer"]

    assert "no trade recommendation" in str(disclaimer)
    assert "execution_allowed=false" in str(disclaimer)


def test_instrument_detail_projection_and_backtests_ui_expose_payoff_fields() -> None:
    results = pd.DataFrame(
        [
            {
                "strategy_name": "signal_strategy",
                "return_hit_rate": 0.5,
                "payoff_ratio": 1.0,
                "skew": 0.0,
                "payoff_profile": "mixed",
                "losses_dominate_wins": False,
                "loss_dominance_warning": "wins_dominate_losses",
                "payoff_asymmetry_warning": "balanced_or_positive_payoff",
                "payoff_profile_disclaimer": "Descriptive payoff profile only; execution_allowed=false.",
            }
        ]
    )
    records = _strategy_tail_diagnostics(SimpleNamespace(results=results))
    assert records and records[0]["payoff_profile"] == "mixed"
    assert all(field in records[0] for field in (
        "return_hit_rate",
        "payoff_ratio",
        "skew",
        "payoff_profile",
        "losses_dominate_wins",
        "loss_dominance_warning",
        "payoff_profile_disclaimer",
    ))
    assert set((
        "return_hit_rate",
        "payoff_ratio",
        "skew",
        "payoff_profile",
        "losses_dominate_wins",
        "loss_dominance_warning",
        "payoff_profile_disclaimer",
    )).issubset(_TAIL_DIAGNOSTIC_FIELDS)

    source = inspect.getsource(backtests_page)
    for label in ("Return skew", "Payoff profile", "Loss dominance warning", "no trade recommendation"):
        assert label in source
