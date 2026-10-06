from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.portfolio.attribution import build_performance_attribution
from etf_cockpit.portfolio.stress_testing import reverse_stress


def _reference_context() -> SimpleNamespace:
    return SimpleNamespace(
        resolution=SimpleNamespace(
            declaration=SimpleNamespace(
                start_date="2025-01-02",
                end_date="2025-01-03",
                decision_time="2025-01-03T23:59:59.999999Z",
            )
        )
    )


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2025-01-02", "etf_id": "ALT", "adjusted_close": 100.0},
            {"date": "2025-01-03", "etf_id": "ALT", "adjusted_close": 110.0},
        ]
    )


def test_explicit_tax_is_deducted_only_once_from_net_return() -> None:
    report = build_performance_attribution(
        _prices(),
        pd.DataFrame([{"etf_id": "ALT", "current_weight": 1.0}]),
        costs=pd.DataFrame(
            [
                {"date": "2025-01-03", "category": "commission", "amount": 3.0},
                {"date": "2025-01-03", "category": "tax", "amount": 2.0},
            ]
        ),
        reference_context=_reference_context(),
    )

    assert report["time_weighted_return"] == pytest.approx(0.1)
    assert report["net_return_after_explicit_costs"] == pytest.approx(-4.9)


def test_liquidity_reverse_stress_probes_positive_shocks() -> None:
    allocation = pd.DataFrame([{"instrument_id": "ALT", "weight": 1.0}])

    result = reverse_stress(
        allocation,
        shock_name="liquidity",
        loss_limit=1_000.0,
        notional=100_000.0,
        upper_bound=0.1,
    )

    assert result["status"] == "available"
    assert result["threshold"] == pytest.approx(0.01, abs=1e-8)


def test_partially_excluded_cost_rows_are_reported_as_excluded() -> None:
    report = build_performance_attribution(
        _prices(),
        pd.DataFrame([{"etf_id": "ALT", "current_weight": 1.0}]),
        costs=pd.DataFrame(
            [
                {"date": "2025-01-03", "category": "commission", "amount": 3.0},
                {"date": "2025-01-04", "category": "tax", "amount": 2.0},
            ]
        ),
        reference_context=_reference_context(),
    )

    assert report["status"] == "partial"
    assert "explicit_costs_outside_canonical_window_excluded" in report["warnings"]
    assert report["net_return_after_explicit_costs"] == pytest.approx(-2.9)
    assert set(report["cost_attribution"]["category"]) == {"commission"}
