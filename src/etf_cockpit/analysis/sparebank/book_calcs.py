"""Pure book calculations that feed the Sparebank scorecard axes (SB2).

Every function cites the equation / page of the owner's book
(``Norwegian_Equity_Certificates.pdf``). Inputs are plain numbers; a missing
or invalid input returns ``None`` (never a zero-filled value) so the caller can
state an explicit "unavailable" reason. No function reads files or the network.
"""

from __future__ import annotations

from collections.abc import Iterable

from etf_cockpit.core.values import finite_float_or_none as _num


def _ratio(numerator: object, denominator: object) -> float | None:
    top, bottom = _num(numerator), _num(denominator)
    if top is None or bottom is None or bottom == 0:
        return None
    return top / bottom


# --- 1. Lending economics (ch. 1.2-1.3, 3.6, 4.2, 4.11) -------------------------------------


def net_interest_margin(nii: object, average_earning_assets: object) -> float | None:
    """NIM = NII / interest-earning assets (eq. 1.6, p. 4: 287.5 / 11 000 = 2.61 %)."""

    return _ratio(nii, average_earning_assets)


def risk_adjusted_lending_spread(margin: object, credit_loss_rate: object) -> float | None:
    """Risk-adjusted lending spread ~ lending margin - expected credit loss (eq. 1.14, p. 9)."""

    spread, loss = _num(margin), _num(credit_loss_rate)
    return None if spread is None or loss is None else spread - loss


def cost_of_risk(impairment: object, average_loans: object) -> float | None:
    """CoR = annualised impairment loss / average gross loans (eq. 4.59, p. 88)."""

    return _ratio(impairment, average_loans)


def growth_rate(opening: object, closing: object) -> float | None:
    """Simple period growth; a non-positive opening balance has no meaningful growth."""

    first, last = _num(opening), _num(closing)
    if first is None or last is None or first <= 0:
        return None
    return last / first - 1.0


def growth_gap(first_growth: object, second_growth: object) -> float | None:
    """Difference of two growth rates (abnormal growth, eq. 4.4, p. 70; divergences 1-2, p. 96)."""

    a, b = _num(first_growth), _num(second_growth)
    return None if a is None or b is None else a - b


def nii_sensitivity(balance: object, margin_change: object) -> float | None:
    """Annual NII change = balance x margin change (p. 4: NOK 8 bn x 0.2 % = NOK 16 m)."""

    amount, change = _num(balance), _num(margin_change)
    return None if amount is None or change is None else amount * change


def cost_to_assets(operating_costs: object, average_assets: object) -> float | None:
    """Cost-to-assets, the margin-neutral companion of C/I (p. 54)."""

    return _ratio(operating_costs, average_assets)


# --- 2. Funding franchise and fragility (ch. 1.2.2, 3.2, 4.4) --------------------------------


def deposit_franchise_advantage(deposits: object, alternative_cost: object, deposit_cost: object) -> float | None:
    """Gross funding advantage FD = D (cA - cD) (eq. 3.6, p. 47: NOK 10 bn x 1.5 % = NOK 150 m)."""

    base, alternative, own = _num(deposits), _num(alternative_cost), _num(deposit_cost)
    if base is None or alternative is None or own is None:
        return None
    return base * (alternative - own)


def average_funding_cost(tranches: Iterable[tuple[object, object]]) -> float | None:
    """Balance-weighted average cost of funding tranches (eq. 4.22, p. 76: 2.64 %)."""

    total = 0.0
    weighted = 0.0
    for balance, cost in tranches:
        amount, rate = _num(balance), _num(cost)
        if amount is None or rate is None or amount < 0:
            return None
        total += amount
        weighted += amount * rate
    return weighted / total if total > 0 else None


def marginal_spread(asset_yield: object, funding_cost: object) -> float | None:
    """Gross spread of the next krone: yield - funding cost (p. 76: 5.0 % - 4.0 % = 100 bp)."""

    y, c = _num(asset_yield), _num(funding_cost)
    return None if y is None or c is None else y - c


def deposit_beta_from_changes(deposit_rate_change: object, reference_rate_change: object) -> float | None:
    """Deposit beta = change in deposit rate / change in reference rate (eq. 1.7 / 4.23, p. 4, 77)."""

    deposit, reference = _num(deposit_rate_change), _num(reference_rate_change)
    if deposit is None or reference in (None, 0):
        return None
    return deposit / reference


def refinancing_concentration(maturing_within_12m: object, total_wholesale: object) -> float | None:
    """MR12 = wholesale funding maturing within 12 months / total wholesale (eq. 4.25, p. 77)."""

    return _ratio(maturing_within_12m, total_wholesale)


# --- 3. Credit migration and concentration (ch. 1.3, 4.3, 4.7) -------------------------------


def stage_share(stage_exposure: object, gross_loans: object) -> float | None:
    """Stage 2 / Stage 3 as a share of the relevant loan book (p. 9)."""

    return _ratio(stage_exposure, gross_loans)


def cure_rate(stage2_to_stage1: object, opening_stage2: object) -> float | None:
    """Cure2 = Stage 2 -> Stage 1 / opening Stage 2 (eq. 4.55, p. 88)."""

    return _ratio(stage2_to_stage1, opening_stage2)


def roll_rate(stage2_to_stage3: object, opening_stage2: object) -> float | None:
    """Roll23 = Stage 2 -> Stage 3 / opening Stage 2 (eq. 4.56, p. 88)."""

    return _ratio(stage2_to_stage3, opening_stage2)


def stage3_coverage(stage3_allowance: object, stage3_exposure: object) -> float | None:
    """CR3 = Stage 3 allowance / Stage 3 exposure (eq. 4.57, p. 88; eq. 1.13, p. 8: 20 %)."""

    return _ratio(stage3_allowance, stage3_exposure)


def stressed_loss(exposure: object, stressed_pd: object, stressed_lgd: object) -> float | None:
    """SL_j = EAD_j x sPD_j x sLGD_j (eq. 4.17, p. 75)."""

    ead, pd_, lgd = _num(exposure), _num(stressed_pd), _num(stressed_lgd)
    return None if ead is None or pd_ is None or lgd is None else ead * pd_ * lgd


def stressed_loss_to_cet1(loss: object, cet1_capital: object) -> float | None:
    """CL_j = SL_j / CET1 capital (eq. 4.18, p. 75: NOK 300 m / NOK 1.5 bn = 20 %)."""

    return _ratio(loss, cet1_capital)


# --- 4. Capital, excess capital and allocation (ch. 1.4, 3.9, 4.8, 5.7, 5.8) -----------------


def cet1_headroom(actual_ratio: object, required_ratio: object) -> float | None:
    """headroom = CET1 actual - CET1 required (eq. 1.17, p. 10; 3.39, p. 59; 4.66, p. 90)."""

    actual, required = _num(actual_ratio), _num(required_ratio)
    return None if actual is None or required is None else actual - required


def surplus_cet1(headroom_ratio: object, rwa: object) -> float | None:
    """Static surplus CET1 = H x RWA (eq. 3.40, p. 59; 5.39, p. 112: 1.5 pp x NOK 10 bn = NOK 150 m)."""

    h, r = _num(headroom_ratio), _num(rwa)
    return None if h is None or r is None else h * r


def rwa_capacity(available_cet1: object, target_ratio: object) -> float | None:
    """Additional RWA capacity = available CET1 / target intensity (p. 12: NOK 300 m / 0.15 = NOK 2.0 bn)."""

    capital, target = _num(available_cet1), _num(target_ratio)
    return None if capital is None or target in (None, 0) else capital / target


def capital_self_funding_ratio(internal_cet1_generation: object, target_ratio: object, rwa_growth: object) -> float | None:
    """CSFR = ICG / (k* x delta RWA) (eq. 5.42, p. 112). Above 1 the planned growth is self-funded."""

    icg, k, drwa = _num(internal_cet1_generation), _num(target_ratio), _num(rwa_growth)
    if icg is None or k is None or drwa is None or k * drwa <= 0:
        return None
    return icg / (k * drwa)


def required_capital_raise(target_ratio: object, stressed_rwa: object, stressed_cet1: object) -> float | None:
    """Raise = max(0, k* RWA_s - CET1_s) (eq. 4.70, p. 92)."""

    k, rwa, cet1 = _num(target_ratio), _num(stressed_rwa), _num(stressed_cet1)
    return None if k is None or rwa is None or cet1 is None else max(0.0, k * rwa - cet1)


def payout_symmetry_gap(owner_payout_rate: object, ownerless_payout_rate: object) -> float | None:
    """PSG = pE - pG (eq. 5.45, p. 113). PSG > 0 pushes the owner fraction down over time."""

    owner, ownerless = _num(owner_payout_rate), _num(ownerless_payout_rate)
    return None if owner is None or ownerless is None else owner - ownerless


def growth_value_sign(incremental_roe_: object, cost_of_equity: object) -> float | None:
    """GVS = ROE_inc - COE (eq. 5.27, p. 108): positive means growth creates value."""

    roe, coe = _num(incremental_roe_), _num(cost_of_equity)
    return None if roe is None or coe is None else roe - coe


def incremental_roe(
    delta_owner_earnings: object,
    delta_owner_book: object,
    *,
    opening_owner_book: object = None,
    minimum_book_change_ratio: float = 0.03,
) -> float | None:
    """ROE_inc = delta NI_O / delta B_O (eq. 5.25, p. 108).

    A tiny or non-positive change in owner book makes the quotient meaningless, so it is
    withheld unless owner book grew by at least ``minimum_book_change_ratio`` of the opening
    book (conservative documented default 3 %).
    """

    earnings, book = _num(delta_owner_earnings), _num(delta_owner_book)
    opening = _num(opening_owner_book)
    if earnings is None or book is None or book <= 0:
        return None
    if opening is None or opening <= 0 or book / opening < minimum_book_change_ratio:
        return None
    return earnings / book


# --- 5. Sustainable ROE versus cost of equity (ch. 3.10, 5.2-5.3) ----------------------------


def quality_spread(sustainable_roe_: object, cost_of_equity: object) -> float | None:
    """QS = ROE_sustainable - COE (eq. 3.42, p. 61)."""

    roe, coe = _num(sustainable_roe_), _num(cost_of_equity)
    return None if roe is None or coe is None else roe - coe


def sustainable_roe(normalised_owner_earnings: object, normalised_owner_book: object) -> float | None:
    """SROE = NI_O^sus / B_O^sus (eq. 5.10-5.11, p. 104)."""

    return _ratio(normalised_owner_earnings, normalised_owner_book)


def roe_on_required_capital(normalised_owner_earnings: object, required_owner_book: object) -> float | None:
    """ROE on required operating capital (eq. 5.12, p. 104; p. 16: NOK 50 m / NOK 400 m = 12.5 %)."""

    return _ratio(normalised_owner_earnings, required_owner_book)


def normalised_roe_walk(reported_roe: object, adjustments_pp: Iterable[object]) -> float | None:
    """Sustainable ROE as reported ROE plus signed adjustments (p. 60: 16 - 2.0 - 0.8 - 0.5 + 0.7 = 13.4)."""

    base = _num(reported_roe)
    if base is None:
        return None
    total = base
    for item in adjustments_pp:
        value = _num(item)
        if value is None:
            return None
        total += value
    return total


def tax_effected(pre_tax_amount: object, tax_rate: object) -> float | None:
    """After-tax value of a pre-tax adjustment (p. 16: the net adjustment is tax-effected)."""

    amount, rate = _num(pre_tax_amount), _num(tax_rate)
    if amount is None or rate is None or not 0.0 <= rate < 1.0:
        return None
    return amount * (1.0 - rate)


# --- 6. Owner valuation: justified P/B, reverse valuation, decision metrics (ch. 5.4-5.6, 5.10) -


def justified_price_to_book(sustainable_roe_: object, cost_of_equity: object, growth: object) -> float | None:
    """P/B = (ROE - g) / (COE - g) (eq. 5.22, p. 107: 12 % ROE, 9 % COE, 3 % g -> 1.50x).

    ``g = b ROE`` (eq. 5.20) cannot exceed ROE, so growth is capped at ROE; a non-positive ROE
    or COE <= g has no stable-model value; a negative g has none either (same rule as stable_pb).
    """

    roe, coe, g = _num(sustainable_roe_), _num(cost_of_equity), _num(growth)
    if roe is None or coe is None or g is None or roe <= 0 or g < 0:
        return None
    g_effective = min(g, roe)
    if coe <= g_effective:
        return None
    return (roe - g_effective) / (coe - g_effective)


def residual_income_per_unit(sustainable_roe_: object, cost_of_equity: object, opening_book: object) -> float | None:
    """RI = (ROE - COE) B_(t-1) (eq. 5.28, p. 109)."""

    roe, coe, book = _num(sustainable_roe_), _num(cost_of_equity), _num(opening_book)
    return None if roe is None or coe is None or book is None else (roe - coe) * book


def implied_roe(price_to_book_: object, cost_of_equity: object, growth: object) -> float | None:
    """ROE_implied = g + (P/B)(COE - g) (eq. 5.32, p. 110; eq. 5.35: 3 % + 1.18 x 7 % = 11.3 %)."""

    pb, coe, g = _num(price_to_book_), _num(cost_of_equity), _num(growth)
    if pb is None or coe is None or g is None or pb <= 0 or coe <= g:
        return None
    return g + pb * (coe - g)


def implied_cost_of_equity(price_to_book_: object, sustainable_roe_: object, growth: object) -> float | None:
    """COE_implied = g + (ROE - g) / (P/B) (eq. 5.33, p. 110)."""

    pb, roe, g = _num(price_to_book_), _num(sustainable_roe_), _num(growth)
    if pb is None or roe is None or g is None or pb <= 0:
        return None
    return g + (roe - g) / pb


def expectations_gap(analyst_sustainable_roe: object, roe_implied: object) -> float | None:
    """EG = SROE_A - ROE_implied (eq. 5.34, p. 111)."""

    analyst, implied = _num(analyst_sustainable_roe), _num(roe_implied)
    return None if analyst is None or implied is None else analyst - implied


def margin_of_safety(price: object, base_value: object) -> float | None:
    """MOS_base = 1 - P0 / V_base (eq. 5.54, p. 117)."""

    p, v = _num(price), _num(base_value)
    return None if p is None or v is None or v <= 0 else 1.0 - p / v


def price_to_earnings_from_pb(price_to_book_: object, roe: object) -> float | None:
    """P/E = (P/B) / ROE when both refer to the same claim (eq. 1.23, p. 14: 0.8 / 12 % = 6.7)."""

    pb, r = _num(price_to_book_), _num(roe)
    return None if pb is None or r is None or r <= 0 else pb / r


# --- 7. Dividends, ownerless distributions and yield (ch. 5.8) ---------------------------------


def payout_rate(distribution: object, profit: object) -> float | None:
    """Payout rate on the profit allocated to a capital pool (p. 113)."""

    return _ratio(distribution, profit)


def dividend_yield(dividend_per_ec: object, price: object) -> float | None:
    """Cash yield to EC holders = dividend per EC / price (p. 113, first bullet)."""

    d, p = _num(dividend_per_ec), _num(price)
    return None if d is None or p is None or p <= 0 or d < 0 else d / p


def diluted_owner_book_per_ec(owner_book: object, ec_count: object, raise_amount: object, issue_price: object) -> float | None:
    """Post-raise owner book per EC (p. 91-92: NOK 1.3 bn / 15 m = NOK 86.67)."""

    book, count, amount, price = _num(owner_book), _num(ec_count), _num(raise_amount), _num(issue_price)
    if None in (book, count, amount, price) or price <= 0 or count <= 0:
        return None
    return (book + amount) / (count + amount / price)
