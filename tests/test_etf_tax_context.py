from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from etf_cockpit.analysis.etf_tax_context import (
    ETFContextAssumptions,
    build_currency_context,
    calculate_core_quality_tax_bias,
    calculate_net_return_scenario,
    load_tax_hedge_assumptions,
)
from etf_cockpit.application import ui_facade


def test_trading_currency_vs_economic_currency() -> None:
    # CSPX USD on LSE and SXR8 EUR on Xetra share ISIN IE00B5BMR087.
    cspx_usd_on_lse = build_currency_context("USD", {"USD": 1.0})
    sxr8_eur_on_xetra = build_currency_context("EUR", {"USD": 1.0})

    assert cspx_usd_on_lse.trading_currency == "USD"
    assert cspx_usd_on_lse.primary_economic_currency == "USD"
    assert cspx_usd_on_lse.trading_currency_differs_from_economic is False
    assert cspx_usd_on_lse.execution_allowed is False
    assert sxr8_eur_on_xetra.trading_currency == "EUR"
    assert sxr8_eur_on_xetra.primary_economic_currency == "USD"
    assert sxr8_eur_on_xetra.trading_currency_differs_from_economic is True
    missing_exposure = build_currency_context("EUR", None)
    assert missing_exposure.trading_currency_differs_from_economic is None
    assert "not supplied" in (missing_exposure.economic_currency_reason or "")


def test_tax_assumptions_disabled_by_default() -> None:
    config_path = Path(__file__).resolve().parents[1] / "configs" / "etf_tax_assumptions_v1.yaml"
    assumptions = load_tax_hedge_assumptions(config_path)
    scenario = calculate_net_return_scenario(0.10, 0.02, assumptions)

    assert assumptions.version == 1
    assert assumptions.tax_enabled is False
    assert assumptions.tax_residence_country is None
    assert assumptions.source_withholding_rate == pytest.approx(0.15)
    assert assumptions.hedge_enabled is False
    assert calculate_core_quality_tax_bias() == 0.0
    assert scenario.net_return_rate is None
    assert scenario.tax_drag_rate is None
    assert scenario.unavailable_reason is not None
    assert scenario.execution_allowed is False
    assert any(effect.label == "Residence-based tax" for effect in scenario.excluded_tax_effects)


def test_net_return_tax_drag_scenario() -> None:
    assumptions = ETFContextAssumptions(
        tax_enabled=True,
        source_withholding_rate=0.15,
        source_withholding_label="US-Ireland treaty withholding on US-source dividends",
    )
    scenario = calculate_net_return_scenario(0.10, 0.02, assumptions)

    assert scenario.net_return_rate == pytest.approx(0.097)
    assert scenario.tax_drag_rate == pytest.approx(0.003)
    assert len(scenario.included_tax_effects) == 1
    effect = scenario.included_tax_effects[0]
    assert effect.label.startswith("US-Ireland treaty withholding")
    assert effect.rate == pytest.approx(0.15)
    assert effect.return_drag_rate == pytest.approx(0.003)
    assert any(
        excluded.label == "Residence-based tax"
        and "not supplied" in excluded.reason
        for excluded in scenario.excluded_tax_effects
    )


def test_tax_context_is_exported_through_the_application_facade() -> None:
    assert ui_facade.ETFContextAssumptions is ETFContextAssumptions
    assert ui_facade.build_currency_context is build_currency_context
    assert ui_facade.calculate_net_return_scenario is calculate_net_return_scenario
    assert ui_facade.load_tax_hedge_assumptions is load_tax_hedge_assumptions


def test_missing_or_future_tax_inputs_stay_unavailable() -> None:
    decision_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    future_assumptions = ETFContextAssumptions(
        tax_enabled=True,
        source_withholding_rate=0.15,
        known_at=decision_time + timedelta(days=1),
    )
    future_scenario = calculate_net_return_scenario(
        0.10, 0.02, future_assumptions, decision_time
    )
    missing_dividend = calculate_net_return_scenario(
        0.10,
        None,
        ETFContextAssumptions(tax_enabled=True, source_withholding_rate=0.15),
    )

    assert future_scenario.net_return_rate is None
    assert future_scenario.included_tax_effects == ()
    assert future_scenario.unavailable_reason == "Assumption was not known at the decision time."
    assert missing_dividend.net_return_rate is None
    assert missing_dividend.tax_drag_rate is None
    assert "not supplied" in (missing_dividend.unavailable_reason or "")
