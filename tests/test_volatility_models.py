from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.core.constants import TRADING_DAYS_PER_YEAR
from etf_cockpit.features.volatility import ewma_volatility
from etf_cockpit.models.volatility_models import gjr_garch_variance_forecast, volatility_model_report

HORIZON = 5


def _log_returns(n: int = 420) -> pd.Series:
    """Seeded GJR-style returns with volatility clustering."""
    rng = np.random.default_rng(7)
    shocks = rng.standard_normal(n)
    variance, out = 1e-4, np.empty(n)
    for i in range(n):
        out[i] = np.sqrt(variance) * shocks[i]
        variance = 2e-6 + (0.04 + 0.08 * (out[i] < 0)) * out[i] ** 2 + 0.88 * variance
    return pd.Series(out, index=pd.bdate_range("2020-01-01", periods=n))


def test_gjr_non_convergence_returns_ewma_value_with_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    arch_base = pytest.importorskip("arch.univariate.base")
    returns = _log_returns()
    ewma_variance = HORIZON * float(ewma_volatility(returns).iloc[-1]) ** 2 / TRADING_DAYS_PER_YEAR

    converged = gjr_garch_variance_forecast(returns, HORIZON)
    assert converged.status == "ok"
    assert converged.variance != pytest.approx(ewma_variance)

    monkeypatch.setattr(arch_base.ARCHModelResult, "convergence_flag", property(lambda self: 1))
    fallback = gjr_garch_variance_forecast(returns, HORIZON)
    assert fallback.status == "warning"
    assert fallback.variance == pytest.approx(ewma_variance)


def test_report_has_qlike_per_model_on_the_same_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("arch")
    returns = _log_returns()

    report = volatility_model_report(returns, HORIZON, min_train=300, step=10).set_index("model")

    assert set(report.index) == {"ewma", "gjr_garch"}
    assert (report["horizon"] == HORIZON).all()
    assert report.loc["ewma", "n_oos_points"] == report.loc["gjr_garch", "n_oos_points"] > 0
    assert report["qlike"].map(np.isfinite).all()
    assert list(report["status"]) == ["ok", "ok"]

    # Missing arch is "unavailable" (not a warning); EWMA keeps its row.
    monkeypatch.setitem(sys.modules, "arch", None)
    degraded = volatility_model_report(returns, HORIZON, min_train=300, step=10).set_index("model")
    assert degraded.loc["gjr_garch", "status"] == "unavailable"
    assert degraded.loc["gjr_garch", "n_oos_points"] == 0
    assert pd.isna(degraded.loc["gjr_garch", "qlike"])
    assert degraded.loc["ewma", "qlike"] == pytest.approx(report.loc["ewma", "qlike"])
