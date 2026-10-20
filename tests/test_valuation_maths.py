"""#940 valuation maths: claim contract, EV-to-equity bridge, clean-surplus RI, driver DCF, stress and bug-hunt guards."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.application import valuation_views
from etf_cockpit.data import stock_research as sr
from etf_cockpit.data.capital_efficiency import build_cost_of_capital_ledger, cost_of_capital_sensitivity_grid

NIL_BRIDGE = {
    "lease_liabilities": "no leases reported",
    "minority_interest": "no minorities",
    "preferred_equity": "no preferreds",
    "pension_deficit": "no pension plan",
    "non_operating_assets": "none held",
}


def _values(**overrides: float) -> dict[str, float]:
    base = {"free_cash_flow": 92.0, "shares_outstanding": 100.0, "net_debt": 400.0, "revenue": 1000.0}
    return {**base, **overrides}


def _assumptions(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "forecast_years": 5,
        "terminal_growth": 0.0,
        "scenarios": {"base": {"growth": 0.0}},
        "bridge_not_applicable": NIL_BRIDGE,
    }
    return {**base, **overrides}


def _base_per_share(result: dict[str, object]) -> float:
    return float(result["scenarios"]["base"]["per_share"])  # type: ignore[index]


# --- required tests -----------------------------------------------------------------------------------------


def test_tv01_fcff_and_fcfe_converge_under_consistent_leverage() -> None:
    # E=600, D=400 (5 % cost, no tax, constant debt), k_e=12 %: WACC = 9.2 %, FCFF = 92, FCFE = 92 - 20 = 72.
    fcff = sr._intrinsic_value(_values(), _assumptions(cash_flow_claim_type="fcff", wacc=0.092))
    fcfe = sr._intrinsic_value(_values(free_cash_flow=72.0), _assumptions(cash_flow_claim_type="fcfe", cost_of_equity=0.12))
    assert fcff["status"] == fcfe["status"] == "available"
    assert fcff["discount_rate_kind"] == "wacc" and fcfe["discount_rate_kind"] == "cost_of_equity"
    assert _base_per_share(fcff) == pytest.approx(6.0)
    assert _base_per_share(fcfe) == pytest.approx(_base_per_share(fcff))


def test_fcfe_never_subtracts_debt_and_fcff_does_exactly_once() -> None:
    fcfe = sr._intrinsic_value(_values(free_cash_flow=72.0, net_debt=10_000.0), _assumptions(cash_flow_claim_type="fcfe", cost_of_equity=0.12))
    scenario = fcfe["scenarios"]["base"]
    assert scenario["equity_value"] == scenario["enterprise_value"] == pytest.approx(600.0)
    assert fcfe["bridge"]["status"] == "not_applicable"
    # FCFE does not even need a net debt figure.
    no_debt = {key: value for key, value in _values(free_cash_flow=72.0).items() if key != "net_debt"}
    assert sr._intrinsic_value(no_debt, _assumptions(cash_flow_claim_type="fcfe", cost_of_equity=0.12))["status"] == "available"
    fcff = sr._intrinsic_value(_values(), _assumptions(cash_flow_claim_type="fcff", wacc=0.092))["scenarios"]["base"]
    assert fcff["enterprise_value"] - fcff["equity_value"] == pytest.approx(400.0)


def test_b106_n001_unlabelled_levered_fcf_is_a_proxy_not_an_fcff() -> None:
    result = sr._intrinsic_value(_values(), _assumptions(discount_rate=0.092))
    assert result["cash_flow_claim_type"] == "proxy" and result["claim_type_source"] == "default_proxy"
    assert result["score_eligible"] is False and result["label"] == "diagnostic_flat_growth"
    assert sr._intrinsic_value(_values(), _assumptions(cash_flow_claim_type="levered", discount_rate=0.1))["status"] == "unavailable"


def test_tv05_clean_surplus_roll_and_dividend_reconciliation() -> None:
    values = {"equity": 100.0, "net_income": 10.0, "shares_outstanding": 10.0, "dividend_per_share": 0.4}
    assumptions = {"forecast_years": 4, "cost_of_equity": 0.10, "terminal_growth": 0.02, "payout_ratio": 0.4, "net_issuance": 1.0}
    result = sr._residual_income(values, assumptions)
    roll = result["clean_surplus"]["book_roll"]
    assert result["status"] == "available" and result["clean_surplus"]["status"] == "reconciled"
    for previous, current in zip(roll, roll[1:]):
        assert current["opening_book"] == pytest.approx(previous["closing_book"])
    for row in roll:
        assert row["closing_book"] == pytest.approx(row["opening_book"] + row["net_income"] - row["dividends"] + row["issuance"])
        assert row["residual_income"] == pytest.approx(row["net_income"] - 0.10 * row["opening_book"])
    assert roll[0]["closing_book"] == pytest.approx(100.0 + 10.0 - 4.0 + 1.0)
    assert result["dividend_reconciliation"]["status"] == "reconciled" and result["score_eligible"] is True
    mismatch = sr._residual_income({**values, "dividend_per_share": 0.9}, assumptions)
    assert mismatch["dividend_reconciliation"]["status"] == "mismatch" and mismatch["score_eligible"] is False
    unevidenced = sr._residual_income({"equity": 100.0, "net_income": 10.0, "shares_outstanding": 10.0}, {**assumptions, "payout_ratio": None})
    assert unevidenced["clean_surplus"]["dividend_basis"] == "default_full_payout_unevidenced" and unevidenced["score_eligible"] is False


@pytest.mark.parametrize(
    ("terminal_growth", "claim", "rates"),
    [(0.10, "fcff", {"wacc": 0.10}), (0.12, "fcff", {"wacc": 0.10}), (0.06, "fcfe", {"cost_of_equity": 0.05}), (-1.0, "fcff", {"wacc": 0.10}), (0.06, "proxy", {"discount_rate": 0.10})],
)
def test_terminal_growth_at_or_above_the_discount_rate_or_the_cap_is_rejected(terminal_growth: float, claim: str, rates: dict[str, float]) -> None:
    result = sr._intrinsic_value(_values(), _assumptions(cash_flow_claim_type=claim, terminal_growth=terminal_growth, **rates))
    assert result["status"] == "unavailable" and result["scenarios"] == {}
    assert sr._reverse_dcf(_values(market_cap=500.0), _assumptions(cash_flow_claim_type=claim, terminal_growth=terminal_growth, **rates))["status"] == "unavailable"


def test_a_proxy_is_never_score_eligible_even_when_everything_else_is_perfect() -> None:
    ledger = build_cost_of_capital_ledger({"wacc": 0.09, "cost_of_equity": 0.11, "risk_free_rate": 0.03, "equity_risk_premium": 0.05, "beta": 1.0, "beta_source": "provider", "risk_free_source": "curve", "equity_risk_premium_source": "survey"})
    assert ledger.basis == "observed"
    current = {"status": "current", "refresh_reason": ""}
    proxy = {"status": "available", "cash_flow_claim_type": "proxy", "score_eligible": True}
    driver = {"status": "available", "cash_flow_claim_type": "fcff"}
    result = sr._score_eligibility({"driver_dcf": driver, "intrinsic_value": proxy}, ledger=ledger, strict_comparability=True, expiry=current, bank_route=False)
    assert result["models"]["driver_dcf"]["score_eligible"] is True
    assert result["models"]["intrinsic_value"]["score_eligible"] is False
    assert proxy["score_eligible"] is False
    provisional = sr._score_eligibility({"driver_dcf": {"status": "available", "cash_flow_claim_type": "fcff"}}, ledger=ledger, strict_comparability=True, expiry={"status": "provisional", "refresh_reason": "stale"}, bank_route=False)
    assert provisional["models"]["driver_dcf"]["score_eligible"] is False
    diagnostic = sr._score_eligibility({"driver_dcf": {"status": "available", "cash_flow_claim_type": "fcff"}}, ledger=ledger, strict_comparability=False, expiry=current, bank_route=False)
    assert diagnostic["any_eligible"] is False


def test_refinancing_stress_is_unavailable_without_a_maturity_schedule_and_prices_only_repricing_debt() -> None:
    values = {"revenue": 1000.0, "operating_income": 100.0, "debt": 500.0, "interest_expense": 25.0, "cash": 50.0, "free_cash_flow": 20.0}
    stress = sr._stress_scenarios(values, pd.DataFrame())
    assert stress["refinancing_shock"]["status"] == "unavailable"
    assert "maturity schedule" in stress["refinancing_shock"]["reason"]
    assert stress["dilution_insolvency"]["status"] == "unavailable"
    scheduled = sr._stress_scenarios({**values, "debt_due_1y": 100.0}, pd.DataFrame())
    shock = scheduled["refinancing_shock"]
    assert shock["stressed_interest"] == pytest.approx(25.0 + 100.0 * 0.02)
    assert shock["interest_coverage"] == pytest.approx(100.0 / 27.0)
    assert scheduled["dilution_insolvency"]["liquidity_shortfall"] == pytest.approx(30.0)
    for name in ("baseline", "favourable", "recession_operating_leverage", "refinancing_shock", "dilution_insolvency"):
        assert scheduled[name]["kind"] == "sensitivity" and scheduled[name]["is_probability"] is False
    assert scheduled["recession_operating_leverage"]["stressed_operating_income"] < scheduled["baseline"]["stressed_operating_income"]
    assert scheduled["baseline"]["stressed_operating_income"] == pytest.approx(100.0)
    # costs 900, half fixed: 800 revenue - (450 + 450 * 0.8) = -10, worse than the proportional 80
    assert scheduled["recession_operating_leverage"]["stressed_operating_income"] == pytest.approx(-10.0)


# --- bridge, negative cash flow, driver DCF ------------------------------------------------------------------


def test_fcff_bridge_requires_every_item_evidenced_or_declared() -> None:
    incomplete = sr._intrinsic_value(_values(), {**_assumptions(cash_flow_claim_type="fcff", wacc=0.092), "bridge_not_applicable": {"lease_liabilities": "none"}})
    assert incomplete["status"] == "unavailable" and "minority_interest" in incomplete["reason"]
    evidenced = sr._intrinsic_value(_values(lease_liabilities=20.0, minority_interest=30.0, pension_deficit=10.0, non_operating_assets=60.0), _assumptions(cash_flow_claim_type="fcff", wacc=0.092, bridge_not_applicable={"preferred_equity": "none"}))
    scenario = evidenced["scenarios"]["base"]
    assert scenario["enterprise_value"] - scenario["equity_value"] == pytest.approx(400.0 + 20.0 + 30.0 + 10.0 - 60.0)


def test_negative_free_cash_flow_is_never_extrapolated_to_a_negative_fair_value() -> None:
    result = sr._intrinsic_value(_values(free_cash_flow=-50.0), _assumptions(cash_flow_claim_type="fcff", wacc=0.092))
    assert result["status"] == "unavailable"
    assert result["rejected_scenarios"]["base"] == "negative_or_zero_base_cash_flow_not_extrapolated"
    # Net debt larger than enterprise value is not a negative price either.
    levered = sr._intrinsic_value(_values(net_debt=5_000.0), _assumptions(cash_flow_claim_type="fcff", wacc=0.092))
    assert levered["status"] == "unavailable"


def test_driver_dcf_chain_matches_the_growing_perpetuity_and_uses_terminal_reinvestment() -> None:
    g, roic, wacc, margin, tax, revenue = 0.02, 0.10, 0.09, 0.20, 0.25, 1000.0
    assumptions = _assumptions(wacc=wacc, terminal_growth=g, tax_rate=tax, driver_dcf={"revenue_growth": g, "operating_margin": margin, "incremental_roic": roic, "terminal_roic": roic})
    result = sr._driver_dcf({"revenue": revenue, "shares_outstanding": 100.0, "net_debt": 400.0}, assumptions)
    assert result["status"] == "available" and result["cash_flow_claim_type"] == "fcff"
    first_fcff = revenue * (1 + g) * margin * (1 - tax) * (1 - g / roic)
    assert result["enterprise_value"] == pytest.approx(first_fcff / (wacc - g))
    assert result["terminal_reinvestment_rate"] == pytest.approx(g / roic)
    assert result["per_share"] == pytest.approx((result["enterprise_value"] - 400.0) / 100.0)
    fade = sr._driver_dcf({"revenue": revenue, "shares_outstanding": 100.0, "net_debt": 400.0}, _assumptions(wacc=wacc, terminal_growth=g, tax_rate=tax, driver_dcf={"revenue_growth": 0.08, "operating_margin": margin, "incremental_roic": 0.20}))
    growth_path = [row["revenue_growth"] for row in fade["path"]]
    assert growth_path[0] > growth_path[-1] == pytest.approx(g)  # growth fades to the terminal rate
    assert fade["path"][-1]["incremental_roic"] == pytest.approx(wacc)  # ROIC fades to WACC by default
    unfundable = sr._driver_dcf({"revenue": revenue, "shares_outstanding": 100.0, "net_debt": 400.0}, _assumptions(wacc=wacc, terminal_growth=g, tax_rate=tax, driver_dcf={"revenue_growth": 0.30, "operating_margin": margin, "incremental_roic": 0.10, "terminal_roic": 0.01}))
    assert unfundable["status"] == "unavailable" and "reinvestment" in unfundable["reason"]
    assert sr._driver_dcf({"revenue": revenue, "shares_outstanding": 100.0}, assumptions)["status"] == "unavailable"  # bridge: net debt not evidenced


# --- ledger, disagreement, expiry, operator weights ----------------------------------------------------------


def test_cost_of_capital_ledger_is_immutable_labelled_and_shows_a_grid_when_not_observed() -> None:
    scenario = build_cost_of_capital_ledger({"wacc": 0.09, "cost_of_equity": 0.11})
    assert scenario.basis == "scenario"
    grid = cost_of_capital_sensitivity_grid(scenario)
    assert grid["status"] == "available" and len(grid["cells"]) == 9
    with pytest.raises(dataclasses.FrozenInstanceError):
        scenario.wacc = 0.5  # type: ignore[misc]
    observed = build_cost_of_capital_ledger({"risk_free_rate": 0.03, "equity_risk_premium": 0.05, "beta": 1.2, "beta_source": "a", "risk_free_source": "b", "equity_risk_premium_source": "c", "wacc": 0.08})
    assert observed.basis == "observed" and observed.cost_of_equity == pytest.approx(0.09)
    assert cost_of_capital_sensitivity_grid(observed)["status"] == "not_required"
    conflict = build_cost_of_capital_ledger({"wacc": 0.09, "discount_rate": 0.12})
    assert conflict.wacc is None and conflict.conflicts


def test_method_disagreement_reports_deltas_under_one_claim_and_never_averages() -> None:
    intrinsic = {"cash_flow_claim_type": "fcfe", "scenarios": {"base": {"per_share": 10.0}}}
    residual = {"per_share": 12.0}
    peers = {"metrics": {"price_to_earnings": {"status": "available", "median": 15.0}}}
    result = sr._model_disagreement(intrinsic, residual, peer_metrics=peers, values={"net_income": 100.0, "shares_outstanding": 100.0})
    assert result["averaged"] is False
    assert result["deltas"]["dcf_vs_residual_income"]["delta"] == pytest.approx(-2.0)
    assert result["deltas"]["dcf_vs_peer"]["delta"] == pytest.approx(10.0 - 15.0)
    assert "mean" not in result and "average" not in result
    proxy = sr._model_disagreement({"cash_flow_claim_type": "proxy", "scenarios": {"base": {"per_share": 10.0}}}, residual)
    assert proxy["deltas"]["dcf_vs_residual_income"]["status"] == "incompatible_claim"


def _statement_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"instrument_id": "ACME", "canonical_metric": metric, "value": value, "currency": "USD", "start": "2025-01-01", "end": "2025-12-31", "period_end": "2025-12-31", "filed": "2026-02-01", "available_at": "2026-02-01T00:00:00Z", "source_id": f"f-{metric}", "consolidation_scope": "consolidated"}
            for metric, value in (("free_cash_flow", 92.0), ("revenue", 1000.0), ("net_income", 80.0), ("equity", 500.0), ("shares_outstanding", 100.0))
        ]
    )


@pytest.mark.parametrize(("decision", "expected"), [("2026-06-30T00:00:00Z", "current"), ("2028-01-01T00:00:00Z", "provisional")])
def test_valuation_expiry_makes_stale_evidence_provisional(decision: str, expected: str) -> None:
    result = sr.valuation_analysis(_statement_frame(), instrument_id="ACME", assumptions=_assumptions(as_of="2026-01-01T00:00:00Z"), as_known_at=decision, strict_comparability=False)
    assert result["expiry"]["status"] == expected == result["valuation_status"]
    assert result["comparability_mode"] == "diagnostic_only"
    if expected == "provisional":
        assert result["expires_at"] and "expired" in result["refresh_reason"]
        assert result["score_eligibility"]["any_eligible"] is False
    else:
        assert result["expires_at"].startswith("2027-01-01")


def test_valuation_analysis_is_strict_by_default_and_labels_operator_weights() -> None:
    weights = {"bear": 0.2, "base": 0.5, "bull": 0.3}
    strict = sr.valuation_analysis(_statement_frame(), instrument_id="ACME", assumptions=_assumptions(scenario_weights=weights, cash_flow_claim_type="fcff", wacc=0.092), as_known_at="2026-06-30T00:00:00Z")
    assert strict["comparability_mode"] == "strict"
    assert strict["operator_weights"]["label"] == "operator_supplied" and strict["operator_weights"]["is_probability"] is False
    assert strict["intrinsic_value"]["status"] == "unavailable"  # statements share no market-input lineage in strict mode
    assert sr.valuation_analysis(_statement_frame(), instrument_id="ACME", as_known_at="2026-06-30T00:00:00Z", strict_comparability=False)["operator_weights"]["status"] == "not_supplied"


def test_bank_stress_is_evidence_gated_and_flags_a_capital_breach() -> None:
    assert sr._bank_stress_scenarios({})["capital_breach"]["status"] == "unavailable"
    values = {"cet1_capital": 100.0, "risk_weighted_assets": 1000.0, "gross_loans": 800.0, "cre_exposure": 200.0, "deposits": 900.0, "wholesale_funding": 100.0}
    stress = sr._bank_stress_scenarios(values, {"cet1_requirement": 0.09})
    # losses: CRE 40 + impairment 16 + funding (100 + 90) * 1 % = 1.9 -> (100 - 57.9) / 1000
    assert stress["capital_breach"]["stressed_cet1_ratio"] == pytest.approx(0.0421)
    assert stress["capital_breach"]["breach"] is True and stress["capital_breach"]["is_probability"] is False


# --- bug-hunt guards -----------------------------------------------------------------------------------------


def test_b106_n003_trailing_pe_gordon_equation_round_trips() -> None:
    implied = sm.implied_growth_from_pe(20.0, 0.4, 0.08).value
    assert implied is not None
    assert 0.4 * (1.0 + implied) / (0.08 - implied) == pytest.approx(20.0)


@pytest.mark.parametrize("cost_of_equity", [-1.0, -1.5])
def test_b06_c2_n003_growth_at_or_below_minus_100_percent_is_not_available(cost_of_equity: float) -> None:
    pe_metric = sm.implied_growth_from_pe(0.5, 0.4, cost_of_equity)
    assert pe_metric.status == sm.NOT_MEANINGFUL and pe_metric.value is None
    dcf_metric = sm.implied_growth_from_dcf(1000.0, 50.0, cost_of_equity, -1.5, 5)
    assert dcf_metric.value is None and dcf_metric.status == sm.UNAVAILABLE
    assert sm.implied_growth_from_dcf(1000.0, 50.0, 0.09, -1.0, 5).status == sm.UNAVAILABLE


def test_b06_c2_n002_preview_rejects_terminal_growth_the_dcf_rejects() -> None:
    contract = {"forecast_years": 5, "discount_rate": 0.1, "terminal_growth": -1.0, "scenarios": {"bear": {"growth": -0.1}, "base": {"growth": 0.0}, "bull": {"growth": 0.1}}}
    with pytest.raises(ValueError):
        valuation_views._normalise_valuation_assumptions(contract)
    assert sr._intrinsic_value(_values(), _assumptions(discount_rate=0.1, terminal_growth=-1.0))["status"] == "unavailable"
    assert valuation_views._normalise_valuation_assumptions({**contract, "terminal_growth": -0.99})["terminal_growth"] == -0.99


def test_fcff_bridge_items_must_share_the_net_debt_period_in_strict_mode() -> None:
    frame = _statement_frame()
    nd = {"instrument_id": "ACME", "currency": "USD", "start": "2025-01-01", "end": "2025-12-31", "period_end": "2025-12-31", "filed": "2026-02-01", "available_at": "2026-02-01T00:00:00Z", "consolidation_scope": "consolidated"}
    mi = {**nd, "start": "2024-01-01", "end": "2024-12-31", "period_end": "2024-12-31", "filed": "2025-02-01", "available_at": "2025-02-01T00:00:00Z"}
    rows = [{**nd, "canonical_metric": "net_debt", "value": 400.0, "source_id": "f-nd"}, {**mi, "canonical_metric": "minority_interest", "value": 30.0, "source_id": "f-mi"}]
    assumptions = _assumptions(cash_flow_claim_type="fcff", wacc=0.092, bridge_not_applicable={k: v for k, v in NIL_BRIDGE.items() if k != "minority_interest"})
    mixed = sr.valuation_analysis(pd.concat([frame, pd.DataFrame(rows)]), instrument_id="ACME", assumptions=assumptions, as_known_at="2026-06-30T00:00:00Z")
    assert mixed["intrinsic_value"]["status"] == mixed["reverse_dcf"]["status"] == mixed["driver_dcf"]["status"] == "unavailable"
    assert "reporting period" in mixed["intrinsic_value"]["reason"]
    aligned = pd.DataFrame([rows[0], {**rows[1], **nd, "canonical_metric": "minority_interest"}])
    ok = sr.valuation_analysis(pd.concat([frame, aligned]), instrument_id="ACME", assumptions=assumptions, as_known_at="2026-06-30T00:00:00Z")
    assert "reporting period" not in str(ok["intrinsic_value"].get("reason"))


def test_residual_income_uses_the_shared_cost_of_capital_ledger() -> None:
    values = {"equity": 500.0, "net_income": 80.0, "shares_outstanding": 100.0}
    capm = {"forecast_years": 5, "terminal_growth": 0.02, "discount_rate": 0.08, "risk_free_rate": 0.03, "equity_risk_premium": 0.05, "beta": 1.2}
    ledger = build_cost_of_capital_ledger(capm)
    result = sr._residual_income(values, capm)
    assert ledger.cost_of_equity == pytest.approx(0.09) and result["cost_of_equity"] == pytest.approx(0.09)
    assert sr._residual_income(values, {k: v for k, v in capm.items() if k not in {"risk_free_rate", "beta"}})["cost_of_equity"] == 0.08  # no ledger k_e -> discount_rate
    assert sr._residual_income(values, {**capm, "cost_of_equity": None})["status"] == "unavailable"  # explicit None (bank route) still blocks


# --- correction pass 1 ---------------------------------------------------------------------------------------


def _dividend_model_value(book_roll: list[dict[str, float]], cost: float, growth: float, payout: float, issuance: float, periods: int = 3000) -> float:
    """Independent check: discounted (dividends - issuance), explicit years then the terminal stream summed term by term."""

    total = sum((row["dividends"] - row["issuance"]) / (1 + cost) ** row["year"] for row in book_roll)
    last_earnings, horizon = book_roll[-1]["net_income"], len(book_roll)
    for step in range(1, periods):
        total += (payout * last_earnings * (1 + growth) ** step - issuance * (1 + growth) ** step) / (1 + cost) ** (horizon + step)
    return total


def test_residual_income_terminal_value_is_horizon_invariant_and_reconciles_to_discounted_dividends() -> None:
    values = {"equity": 100.0, "net_income": 10.0, "shares_outstanding": 1.0}
    flat = {"cost_of_equity": 0.10, "terminal_growth": 0.0, "payout_ratio": 0.4, "net_issuance": 0.0}
    for years in (1, 3, 8):  # retained earnings keep changing book equity: the value is the 4 / 10 % dividend perpetuity
        assert sr._residual_income(values, {**flat, "forecast_years": years})["equity_value"] == pytest.approx(40.0)
    growing = {"cost_of_equity": 0.10, "terminal_growth": 0.02, "payout_ratio": 0.4, "net_issuance": 0.0}
    assert len({round(sr._residual_income(values, {**growing, "forecast_years": years})["equity_value"], 9) for years in (1, 4, 9)}) == 1
    issued = {**growing, "net_issuance": 1.5, "forecast_years": 4}
    result = sr._residual_income(values, issued)
    assert result["equity_value"] == pytest.approx(_dividend_model_value(result["clean_surplus"]["book_roll"], 0.10, 0.02, 0.4, 1.5), rel=1e-6)
    assert result["dividend_model_reconciliation"]["status"] == "reconciled"
    assert result["dividend_model_value"] == pytest.approx(result["equity_value"])


def _driver_frame(**currencies: str) -> pd.DataFrame:
    base = {"instrument_id": "ACME", "currency": "USD", "start": "2025-01-01", "end": "2025-12-31", "period_end": "2025-12-31", "filed": "2026-02-01", "available_at": "2026-02-01T00:00:00Z", "consolidation_scope": "consolidated"}
    rows = [
        {**base, "canonical_metric": metric, "value": value, "currency": currencies.get(metric, "USD"), "source_id": f"f-{metric}"}
        for metric, value in (("free_cash_flow", 92.0), ("revenue", 1000.0), ("net_debt", 400.0), ("shares_outstanding", 100.0))
    ]
    return pd.DataFrame(rows)


def test_strict_driver_dcf_has_its_own_comparability_check_on_revenue_and_the_bridge() -> None:
    assumptions = _assumptions(cash_flow_claim_type="fcff", wacc=0.092, tax_rate=0.25, driver_dcf={"revenue_growth": 0.02, "operating_margin": 0.2, "incremental_roic": 0.12})

    def run(frame: pd.DataFrame) -> dict[str, object]:
        return sr.valuation_analysis(frame, instrument_id="ACME", assumptions=assumptions, as_known_at="2026-06-30T00:00:00Z")

    mismatched = run(_driver_frame(revenue="EUR"))  # USD FCF and net debt must not validate an EUR revenue
    assert mismatched["driver_dcf"]["status"] == "unavailable" and "currency" in mismatched["driver_dcf"]["reason"]
    assert mismatched["driver_dcf"]["score_eligible"] is False
    assert run(_driver_frame())["driver_dcf"]["status"] == "available"
    flat_only_mismatch = run(_driver_frame(free_cash_flow="EUR"))  # free cash flow is not a driver input
    assert flat_only_mismatch["driver_dcf"]["status"] == "available" and flat_only_mismatch["intrinsic_value"]["status"] == "unavailable"
    assert run(_driver_frame(net_debt="EUR"))["driver_dcf"]["status"] == "unavailable"  # the bridge is checked with the revenue


def test_balance_sheet_analysis_applies_stress_assumptions_from_statement_rows() -> None:
    base = {"instrument_id": "ACME", "currency": "USD", "start": "2025-01-01", "end": "2025-12-31", "period_end": "2025-12-31", "period_type": "annual", "period_key": "FY2025", "filed": "2026-02-01", "available_at": "2026-02-01T00:00:00Z", "consolidation_scope": "consolidated"}

    def frame(**metrics: float) -> pd.DataFrame:
        return pd.DataFrame([{**base, "canonical_metric": name, "value": value, "source_id": f"f-{name}"} for name, value in metrics.items()])

    industrial = frame(revenue=1000.0, operating_income=100.0, interest_expense=20.0, debt=400.0, cash=50.0, debt_due_1y=100.0, free_cash_flow=30.0)
    default = sr.balance_sheet_analysis(industrial, instrument_id="ACME", sector="industrials")["stress_scenarios"]
    assert default["refinancing_shock"]["stressed_interest"] == pytest.approx(20.0 + 100.0 * 0.02)
    tuned = sr.balance_sheet_analysis(industrial, instrument_id="ACME", sector="industrials", assumptions={"refinancing_rate_add": 0.05, "fixed_cost_share": 0.8})["stress_scenarios"]
    assert tuned["refinancing_shock"]["stressed_interest"] == pytest.approx(20.0 + 100.0 * 0.05)
    assert tuned["recession_operating_leverage"]["assumptions"]["fixed_cost_share"] == 0.8
    no_schedule = sr.balance_sheet_analysis(frame(revenue=1000.0, operating_income=100.0, interest_expense=20.0, debt=400.0), instrument_id="ACME", sector="industrials")["stress_scenarios"]
    assert no_schedule["refinancing_shock"]["status"] == "unavailable"
    bank = frame(cet1_capital=100.0, risk_weighted_assets=1000.0, gross_loans=800.0, cre_exposure=200.0, deposits=900.0, wholesale_funding=100.0)
    with_requirement = sr.balance_sheet_analysis(bank, instrument_id="ACME", sector="banks", assumptions={"cet1_requirement": 0.09})["stress_scenarios"]
    assert with_requirement["capital_breach"]["stressed_cet1_ratio"] == pytest.approx(0.0421) and with_requirement["capital_breach"]["breach"] is True
    assert with_requirement["capital_breach"]["source_ids"]
    without = sr.balance_sheet_analysis(bank, instrument_id="ACME", sector="banks")["stress_scenarios"]
    assert without["capital_breach"]["status"] == "unavailable" and "cet1_requirement" in without["capital_breach"]["reason"]
    unmapped = sr.balance_sheet_analysis(frame(cet1_capital=100.0), instrument_id="ACME", sector="banks", assumptions={"cet1_requirement": 0.09})["stress_scenarios"]
    assert unmapped["cre_property_stress"]["status"] == "unavailable" and "input not mapped" in unmapped["cre_property_stress"]["reason"]


def _input_frame(equity_year: int, other_year: int) -> pd.DataFrame:
    def row(metric: str, value: float, year: int) -> dict[str, object]:
        return {"instrument_id": "ACME", "canonical_metric": metric, "value": value, "currency": "USD", "start": f"{year}-01-01", "end": f"{year}-12-31", "period_end": f"{year}-12-31", "filed": f"{year + 1}-02-01", "available_at": f"{year + 1}-02-01T00:00:00Z", "source_id": f"f-{metric}-{year}", "consolidation_scope": "consolidated"}

    return pd.DataFrame([row("equity", 500.0, equity_year), row("net_income", 80.0, equity_year), row("shares_outstanding", 100.0, equity_year), row("revenue", 1000.0, other_year)])


def test_expiry_judges_each_consumed_input_and_rejects_future_dated_evidence() -> None:
    assumptions = {"forecast_years": 5, "terminal_growth": 0.02, "cost_of_equity": 0.09, "payout_ratio": 0.5, "net_issuance": 0.0, "as_of": "2026-01-01T00:00:00Z"}

    def run(frame: pd.DataFrame, fx: str | None = None, **overrides: object) -> dict[str, object]:
        market = {} if fx is None else {"currency_conversion_timestamp": fx}
        return sr.valuation_analysis(frame, instrument_id="ACME", assumptions={**assumptions, **overrides}, market_inputs=market, as_known_at="2026-06-30T00:00:00Z", strict_comparability=False)

    stale = run(_input_frame(2023, 2025))  # a newer, unrelated revenue row must not refresh the FY2023 equity/net income
    assert stale["residual_income"]["status"] == "available"
    assert stale["expiry"]["status"] == "provisional" and "statements evidence expired" in stale["refresh_reason"]
    assert stale["expiry"]["components"]["statements"]["basis"] == "2023-12-31"
    assert run(_input_frame(2025, 2025))["expiry"]["status"] == "current"
    future_assumption = run(_input_frame(2025, 2025), as_of="2026-09-01T00:00:00Z")
    assert future_assumption["expiry"]["status"] == "provisional" and "assumptions as_of" in future_assumption["refresh_reason"] and "after the decision cutoff" in future_assumption["refresh_reason"]
    assert "assumptions" not in future_assumption["expiry"]["components"]
    future_fx = run(_input_frame(2025, 2025), fx="2026-07-15T00:00:00Z")
    assert future_fx["expiry"]["status"] == "provisional" and "FX conversion timestamp" in future_fx["refresh_reason"] and "fx" not in future_fx["expiry"]["components"]


def test_economic_spread_consumes_only_the_ledger_wacc_when_legacy_aliases_conflict() -> None:
    from tests.test_stock_research import _statements

    def spread(assumptions: dict[str, object]) -> dict[str, object]:
        report = sr.build_stock_research_report(_statements(), instrument_id="ACME", sector="industrials", strict_comparability=False, assumptions=assumptions)
        return report["capital_efficiency"]["reported"]["metrics"]["economic_profit_spread"]

    assert spread({"tax_rate": 0.25, "cost_of_capital": 0.08})["value"] == pytest.approx(20.25 / 86.0 - 0.08)
    conflicted = spread({"tax_rate": 0.25, "cost_of_capital": 0.08, "discount_rate": 0.10})
    assert conflicted["value"] is None and conflicted["status"] != "available"


def test_model_disagreement_range_and_status_include_driver_and_peer_values() -> None:
    peers = {"metrics": {"price_to_earnings": {"status": "available", "median": 15.0}}}
    result = sr._model_disagreement({"status": "unavailable", "scenarios": {}}, {"status": "unavailable"}, driver={"per_share": 20.0}, peer_metrics=peers, values={"net_income": 100.0, "shares_outstanding": 100.0})
    assert result["deltas"]["dcf_vs_peer"]["status"] == "available"
    assert result["status"] == "available" and result["range"] == [15.0, 20.0]
    lone = sr._model_disagreement({"status": "unavailable", "scenarios": {}}, {"status": "unavailable"}, driver={"per_share": 20.0})
    assert lone["status"] == "unavailable"
