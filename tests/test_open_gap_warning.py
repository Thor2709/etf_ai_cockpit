from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from etf_cockpit.app.pages.backtests import _open_gap_warning_label
from etf_cockpit.app.selectors.instrument_detail import _open_gap_warning_consistent
from etf_cockpit.backtest.engine import _open_gap_warning, run_backtest
from etf_cockpit.core.config import CostModel, load_config
from etf_cockpit.data.sample_data import generate_sample_prices


@pytest.mark.parametrize(
    ("gap", "threshold", "expected"),
    [
        (0.03, 0.02, True),
        (-0.025, 0.02, True),
        (0.02, 0.02, True),
        (0.0199, 0.02, False),
        (-0.001, 0.02, False),
        (None, 0.02, None),
        (0.05, None, None),
        (float("nan"), 0.02, None),
    ],
)
def test_open_gap_warning_flags_absolute_gap_and_keeps_unknown_unknown(gap, threshold, expected) -> None:
    assert _open_gap_warning(gap, threshold) is expected


def test_open_gap_threshold_is_configured_and_validated() -> None:
    # The shipped costs.yaml leaves the threshold to the typed default so the
    # settings companion revision of existing installations stays valid.
    assert load_config().costs.cost_model.open_gap_warning_threshold == pytest.approx(0.02)
    assert CostModel().open_gap_warning_threshold == pytest.approx(0.02)
    assert CostModel(open_gap_warning_threshold=0.05).open_gap_warning_threshold == pytest.approx(0.05)
    for invalid in (0.0, -0.01, 1.5):
        with pytest.raises(ValidationError):
            CostModel(open_gap_warning_threshold=invalid)


def _operational_rows(threshold: float) -> pd.DataFrame:
    config = load_config()
    cost_model = config.costs.cost_model.model_copy(update={"open_gap_warning_threshold": threshold})
    config = config.model_copy(update={"costs": config.costs.model_copy(update={"cost_model": cost_model})})
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    evidence = run_backtest(config, prices, rebalance_frequency_days=42).operational_evidence
    return evidence.loc[evidence["close_to_next_open_gap"].notna()]


def test_backtest_operational_rows_carry_config_bound_open_gap_warning() -> None:
    rows = _operational_rows(0.02)
    assert not rows.empty
    assert rows["open_gap_warning_threshold"].eq(0.02).all()
    expected = rows["close_to_next_open_gap"].abs() >= 0.02
    assert rows["open_gap_warning"].map(type).eq(bool).all()
    assert (rows["open_gap_warning"] == expected).all()
    assert rows["execution_allowed"].eq(False).all()

    # The flag follows the configured threshold; it never changes the gap.
    tight = _operational_rows(1e-9)
    loose = _operational_rows(1.0)
    assert tight.loc[tight["close_to_next_open_gap"].abs() >= 1e-9, "open_gap_warning"].all()
    assert not loose["open_gap_warning"].any()
    pd.testing.assert_series_equal(
        tight["close_to_next_open_gap"].reset_index(drop=True),
        loose["close_to_next_open_gap"].reset_index(drop=True),
    )


def test_selector_rejects_inconsistent_open_gap_warning_but_accepts_legacy_rows() -> None:
    assert _open_gap_warning_consistent({"close_to_next_open_gap": 0.01})
    assert _open_gap_warning_consistent({"close_to_next_open_gap": 0.03, "open_gap_warning": True, "open_gap_warning_threshold": 0.02})
    assert _open_gap_warning_consistent({"close_to_next_open_gap": -0.01, "open_gap_warning": False, "open_gap_warning_threshold": 0.02})
    for tampered in (
        {"close_to_next_open_gap": 0.03, "open_gap_warning": False, "open_gap_warning_threshold": 0.02},
        {"close_to_next_open_gap": 0.01, "open_gap_warning": True, "open_gap_warning_threshold": 0.02},
        {"close_to_next_open_gap": 0.03, "open_gap_warning": "yes", "open_gap_warning_threshold": 0.02},
        {"close_to_next_open_gap": 0.03, "open_gap_warning": True, "open_gap_warning_threshold": 0.0},
        {"close_to_next_open_gap": 0.03, "open_gap_warning": True},
        {"close_to_next_open_gap": None, "open_gap_warning": True, "open_gap_warning_threshold": 0.02},
    ):
        assert not _open_gap_warning_consistent(tampered)


def test_backtests_page_labels_open_gap_warning_state() -> None:
    assert _open_gap_warning_label({"open_gap_warning": True, "open_gap_warning_threshold": 0.02}).startswith("WARNING")
    assert _open_gap_warning_label({"open_gap_warning": False, "open_gap_warning_threshold": 0.02}).startswith("within")
    assert _open_gap_warning_label({"open_gap_warning": None}) == "unavailable"
