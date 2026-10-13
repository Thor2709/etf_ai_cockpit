"""Golden tests: every expected number is a worked example printed in the owner's book."""

from __future__ import annotations

import pytest

from etf_cockpit.analysis.sparebank import book_calcs as bc


def test_lending_goldens_from_chapter_1() -> None:
    # p. 4, eq. 1.6: NII 287.5 m over NOK 11 bn of earning assets.
    assert bc.net_interest_margin(287.5e6, 11e9) == pytest.approx(0.02614, abs=1e-5)
    # p. 4: 20 bp lower mortgage pricing on NOK 8 bn costs about NOK 16 m a year.
    assert bc.nii_sensitivity(8e9, 0.002) == pytest.approx(16e6)
    # p. 9, eq. 1.14: +20 bp margin is cancelled by +20 bp credit losses.
    assert bc.risk_adjusted_lending_spread(0.0220, 0.0020) == pytest.approx(0.02)
    assert bc.cost_of_risk(20e6, 10e9) == pytest.approx(0.002)
    # p. 70, eq. 4.4: 15 % own growth versus a 4 % market is 11 percentage points of abnormal growth.
    assert bc.growth_gap(0.15, 0.04) == pytest.approx(0.11)
    # Missing or non-positive opening balances never produce a growth rate.
    assert bc.growth_rate(None, 10) is None
    assert bc.growth_rate(0, 10) is None
    assert bc.growth_rate(100, 110) == pytest.approx(0.10)


def test_funding_goldens_from_chapters_3_and_4() -> None:
    # p. 47, eq. 3.6: NOK 10 bn of deposits at 2.5 % versus 4.0 % alternative funding.
    assert bc.deposit_franchise_advantage(10e9, 0.04, 0.025) == pytest.approx(150e6)
    # p. 48 and p. 76: NOK 10 bn at 2.5 % plus the next NOK 1 bn at 4.0 % averages 2.64 %.
    assert bc.average_funding_cost([(10e9, 0.025), (1e9, 0.04)]) == pytest.approx(0.02636, abs=1e-5)
    # p. 76: a 5.0 % mortgage on 4.0 % marginal funding leaves 100 bp, not 250 bp.
    assert bc.marginal_spread(0.05, 0.04) == pytest.approx(0.01)
    # p. 5, eq. 1.7: deposit rate 1 % -> 2 % against a 2 pp reference move is beta 0.5.
    assert bc.deposit_beta_from_changes(0.01, 0.02) == pytest.approx(0.5)
    assert bc.deposit_beta_from_changes(0.01, 0) is None
    # p. 77, eq. 4.25: refinancing concentration.
    assert bc.refinancing_concentration(2e9, 8e9) == pytest.approx(0.25)


def test_credit_migration_and_concentration_goldens() -> None:
    # p. 71, eq. 4.7: NOK 1 bn Stage 2 on NOK 10 bn is 10 %; after NOK 2 bn of Stage 1 it is 8.3 %.
    assert bc.stage_share(1e9, 10e9) == pytest.approx(0.10)
    assert bc.stage_share(1e9, 12e9) == pytest.approx(0.0833, abs=1e-4)
    # p. 9: Trondelag corporate book, Stage 2 503 m and Stage 3 344 m of 2.663 bn.
    assert bc.stage_share(503e6, 2663e6) == pytest.approx(0.189, abs=1e-3)
    assert bc.stage_share(344e6, 2663e6) == pytest.approx(0.129, abs=1e-3)
    # p. 8, eq. 1.13: NOK 2 m provision on NOK 10 m Stage 3 is 20 % coverage.
    assert bc.stage3_coverage(2e6, 10e6) == pytest.approx(0.20)
    # p. 88, eq. 4.55-4.56 definitions.
    assert bc.cure_rate(30, 100) == pytest.approx(0.30)
    assert bc.roll_rate(10, 100) == pytest.approx(0.10)
    # p. 75, eq. 4.18: NOK 300 m stressed loss against NOK 1.5 bn CET1 consumes 20 % of the capital base.
    assert bc.stressed_loss_to_cet1(300e6, 1.5e9) == pytest.approx(0.20)
    assert bc.stressed_loss(1e9, 0.30, 1.0) == pytest.approx(300e6)


def test_capital_and_allocation_goldens() -> None:
    # p. 11: 17.32 % reported against a 16.99 % practical target is 0.33 pp, about NOK 20 m on NOK 6.028 bn RWA.
    headroom = bc.cet1_headroom(0.1732, 0.1699)
    assert headroom == pytest.approx(0.0033)
    assert bc.surplus_cet1(headroom, 6.028e9) == pytest.approx(19.9e6, rel=0.01)
    # p. 59, eq. 3.40: 1.5 pp above target on NOK 10 bn RWA is NOK 150 m.
    assert bc.surplus_cet1(0.015, 10e9) == pytest.approx(150e6)
    # p. 12: NOK 300 m of CET1 capacity at a 15 % target supports NOK 2.0 bn of additional RWA.
    assert bc.rwa_capacity(300e6, 0.15) == pytest.approx(2.0e9)
    # p. 90: legal headroom 17.3 - 15.5 = 1.8 pp but management-target headroom only 0.3 pp.
    assert bc.cet1_headroom(0.173, 0.155) == pytest.approx(0.018)
    assert bc.cet1_headroom(0.173, 0.170) == pytest.approx(0.003)
    # p. 92, eq. 4.70: raise = max(0, k* RWA - CET1).
    assert bc.required_capital_raise(0.17, 6.2e9, 0.925e9) == pytest.approx(0.129e9)
    assert bc.required_capital_raise(0.17, 6.0e9, 1.2e9) == 0.0
    # p. 112, eq. 5.42: self-funding above one means headroom can build.
    assert bc.capital_self_funding_ratio(120e6, 0.17, 500e6) == pytest.approx(1.4118, abs=1e-4)
    # p. 91-92: NOK 1.0 bn owner equity, 10 m ECs, raise NOK 300 m at NOK 60 -> NOK 86.67 per EC.
    assert bc.diluted_owner_book_per_ec(1.0e9, 10e6, 300e6, 60.0) == pytest.approx(86.667, abs=1e-3)
    # p. 113, eq. 5.45: payout symmetry gap.
    assert bc.payout_symmetry_gap(0.5, 0.2) == pytest.approx(0.3)
    # p. 60, eq. 3.41 / p. 108, eq. 5.27: reinvesting at 8 % against a 10 % COE destroys value.
    assert bc.growth_value_sign(0.08, 0.10) == pytest.approx(-0.02)


def test_incremental_roe_is_withheld_when_owner_book_barely_moves() -> None:
    assert bc.incremental_roe(50, 100, opening_owner_book=1000) == pytest.approx(0.5)
    assert bc.incremental_roe(50, 5, opening_owner_book=1000) is None  # +0.5 % book: meaningless quotient
    assert bc.incremental_roe(50, -10, opening_owner_book=1000) is None
    assert bc.incremental_roe(50, 100) is None  # no opening book, no guard evidence


def test_sustainable_roe_goldens_from_chapters_1_3_and_5() -> None:
    # p. 60: 16 % reported - 2.0 - 0.8 - 0.5 + 0.7 = 13.4 %.
    assert bc.normalised_roe_walk(16.0, [-2.0, -0.8, -0.5, 0.7]) == pytest.approx(13.4)
    assert bc.normalised_roe_walk(16.0, [-2.0, None]) is None
    # p. 16: NOK 50 m on NOK 500 m is 10 %, on the NOK 400 m actually required it is 12.5 %.
    assert bc.sustainable_roe(50, 500) == pytest.approx(0.10)
    assert bc.roe_on_required_capital(50, 400) == pytest.approx(0.125)
    # p. 61, eq. 3.42: 14 % sustainable ROE against a 10 % hurdle is a 4 pp quality spread.
    assert bc.quality_spread(0.14, 0.10) == pytest.approx(0.04)
    # p. 14: P/E = P/B / ROE; 0.8x book at 12 % ROE is about 6.7.
    assert bc.price_to_earnings_from_pb(0.8, 0.12) == pytest.approx(6.667, abs=1e-3)
    assert bc.tax_effected(100, 0.25) == pytest.approx(75)


def test_justified_pb_and_reverse_valuation_goldens() -> None:
    # p. 104: 12 % ROE and 3 % growth give 1.50x at a 9 % COE and 1.125x at 11 %.
    assert bc.justified_price_to_book(0.12, 0.09, 0.03) == pytest.approx(1.5)
    assert bc.justified_price_to_book(0.12, 0.11, 0.03) == pytest.approx(1.125)
    # p. 15, eq. 1.25: ROE = COE gives one times book.
    assert bc.justified_price_to_book(0.10, 0.10, 0.03) == pytest.approx(1.0)
    # g = b ROE (eq. 5.20) cannot exceed ROE: a 2 % ROE cannot sustain 3 % growth, so the stable value is floored at zero.
    assert bc.justified_price_to_book(0.02, 0.10, 0.03) == pytest.approx(0.0)
    assert bc.justified_price_to_book(-0.01, 0.10, 0.03) is None
    assert bc.justified_price_to_book(0.12, 0.03, 0.03) is None
    # p. 111, eq. 5.35: Romerike 1.18x at 10 % COE and 3 % growth implies about 11.3 % ROE.
    assert bc.implied_roe(1.18, 0.10, 0.03) == pytest.approx(0.1126, abs=1e-4)
    # p. 111, eq. 5.36: Trondelag 0.96x implies about 9.7 %.
    assert bc.implied_roe(0.96, 0.10, 0.03) == pytest.approx(0.0972, abs=1e-4)
    # p. 110, eq. 5.33: inversion for COE returns the COE that produced the multiple.
    assert bc.implied_cost_of_equity(1.5, 0.12, 0.03) == pytest.approx(0.09)
    # p. 111, eq. 5.34: analyst 12 % against 9.7 % implied is a positive expectations gap.
    assert bc.expectations_gap(0.12, 0.097) == pytest.approx(0.023)
    # p. 117, eq. 5.54: price 100 against base value 125 is a 20 % margin of safety.
    assert bc.margin_of_safety(100, 125) == pytest.approx(0.20)
    assert bc.residual_income_per_unit(0.14, 0.10, 100) == pytest.approx(4.0)


def test_dividend_yield_requires_positive_price_and_non_negative_dividend() -> None:
    assert bc.dividend_yield(5.0, 100.0) == pytest.approx(0.05)
    assert bc.dividend_yield(5.0, 0.0) is None
    assert bc.dividend_yield(-1.0, 100.0) is None
    assert bc.dividend_yield(None, 100.0) is None
    assert bc.payout_rate(50, 100) == pytest.approx(0.5)
