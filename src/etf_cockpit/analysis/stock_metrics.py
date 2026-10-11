"""Canonical stock ratio definitions (one function per calculation, pure, no I/O).

Every function here is the single implementation of its definition; the stock score, the stock
pages and Stock Research all call these. Definitions (owner coordinator addendum 2026-10-09):

* TTM = sum of the last 4 reported quarters, each counted only once its ``known_at`` is on or
  before the decision time; with fewer than 4 quarters the last fiscal year is used and labelled FY.
* ROE = net income attributable to parent (window) / average parent equity ((opening + closing) / 2).
* ROIC = NOPAT / average (equity + interest-bearing debt + leases - cash);
  NOPAT = EBIT x (1 - effective tax rate), the rate clamped to 0..40 %.
* Margins (gross, EBIT, net) = item / revenue over the same window.
* FCF = cash from operations - capex (PP&E and intangibles). FCF yield = FCF / market cap.
* Net debt = interest-bearing debt + lease liabilities (when reported) - cash and short-term investments.
* Net debt / EBITDA uses window EBITDA = EBIT + D&A. Debt / equity = interest-bearing debt / parent equity.
* Market cap = decision-time price x shares of the latest filing known at the decision time.
* EV = market cap + net debt + minority interest. P/E = market cap / parent net income;
  EV/EBIT and EV/Sales follow the same rule; a loss is "not meaningful (loss)", never a negative multiple.
* P/B = market cap / parent equity. Dividend yield = dividends per share of the trailing 12 months / price.
* Growth = CAGR over the stated window; a zero or negative start is "not meaningful".
* Valuation versus history = percentile of the current multiple within the instrument's own
  point-in-time history; versus peers = median of the peer set excluding the instrument itself.
* Currency: ratios never mix currencies; a mismatch without an FX rate is ``currency_mismatch``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

FLOW_FIELDS = (
    "revenue",
    "gross_profit",
    "ebit",
    "da",
    "pretax_income",
    "income_tax",
    "interest_expense",
    "net_income_parent",
    "cfo",
    "capex",
    "dividends_paid",
)
BALANCE_FIELDS = (
    "equity_parent",
    "minority_interest",
    "ib_debt",
    "lease_liabilities",
    "cash_sti",
    "total_assets",
    "shares_outstanding",
)
PERIOD_FIELDS = FLOW_FIELDS + BALANCE_FIELDS

OK = "ok"
NOT_MEANINGFUL = "not_meaningful"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Period:
    """One reported period of one instrument; ``values`` holds only fields that were reported."""

    period_end: date
    period_type: str  # "Q" quarter, "FY" fiscal year
    known_at: datetime
    currency: str
    source: str
    values: Mapping[str, float]
    field_sources: Mapping[str, str] = field(default_factory=dict)
    source_ref: str = ""

    def has(self, *names: str) -> bool:
        return all(_finite(self.values.get(name)) is not None for name in names)

    def source_of(self, name: str) -> str:
        return str(self.field_sources.get(name) or self.source)


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    value: float | None
    unit: str  # ratio | multiple | money | count | percentile
    status: str  # ok | not_meaningful | unavailable
    reason: str | None = None
    basis: str | None = None  # TTM | FY | latest balance | spot
    as_of: str | None = None  # period end or price date, ISO
    currency: str | None = None
    source: str | None = None
    formula: str = ""

    @property
    def available(self) -> bool:
        return self.status == OK and self.value is not None


@dataclass(frozen=True)
class Window:
    basis: str  # TTM | FY
    end: date
    periods: tuple[Period, ...]
    currency: str
    known_at: datetime

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(sorted({period.source for period in self.periods}))


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def as_utc(value: object) -> datetime | None:
    """Parse an ISO date/time (or datetime) to an aware UTC datetime; a bare date is end of that day."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 23, 59, 59, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    try:
        if len(text) == 10:
            parsed = date.fromisoformat(text)
            return datetime(parsed.year, parsed.month, parsed.day, 23, 59, 59, tzinfo=timezone.utc)
        parsed_dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed_dt if parsed_dt.tzinfo else parsed_dt.replace(tzinfo=timezone.utc)


def _unavailable(key: str, label: str, reason: str, *, formula: str = "", unit: str = "ratio") -> Metric:
    return Metric(key, label, None, unit, UNAVAILABLE, reason, formula=formula)


def _not_meaningful(key: str, label: str, reason: str, *, formula: str = "", unit: str = "ratio") -> Metric:
    return Metric(key, label, None, unit, NOT_MEANINGFUL, reason, formula=formula)


# ---------------------------------------------------------------------------------------------
# Point-in-time period selection
# ---------------------------------------------------------------------------------------------


def known_periods(periods: Iterable[Period], decision_time: datetime) -> list[Period]:
    """Latest known version of each (period_end, period_type); only ``known_at <= decision_time``."""

    best: dict[tuple[date, str], Period] = {}
    for period in periods:
        if period.known_at > decision_time:
            continue
        key = (period.period_end, period.period_type)
        current = best.get(key)
        source = period.source.casefold()
        current_source = current.source.casefold() if current is not None else ""
        source_rank = int(any(token in source for token in ("sec", "esef", "oam", "filing", "official")))
        current_rank = int(any(token in current_source for token in ("sec", "esef", "oam", "filing", "official")))
        candidate_key = (source_rank, source, period.source_ref)
        current_key = (current_rank, current_source, current.source_ref) if current is not None else None
        if current is None or period.known_at > current.known_at or (
            period.known_at == current.known_at and candidate_key > current_key
        ):
            best[key] = period
    return sorted(best.values(), key=lambda item: (item.period_end, item.period_type))


def flow_window(
    periods: Sequence[Period],
    fields: Sequence[str],
    *,
    quarters: int = 4,
    span_days: tuple[int, int] = (240, 300),
) -> Window | None:
    """TTM window (4 consecutive quarters carrying every field) else the latest FY carrying them."""

    quarterly = [p for p in periods if p.period_type == "Q" and p.has(*fields)]
    quarterly.sort(key=lambda item: item.period_end, reverse=True)
    ttm: Window | None = None
    if len(quarterly) >= quarters:
        chosen = quarterly[:quarters]
        ordered = sorted(chosen, key=lambda item: item.period_end)
        gaps = [(b.period_end - a.period_end).days for a, b in zip(ordered, ordered[1:])]
        span = (ordered[-1].period_end - ordered[0].period_end).days
        currencies = {p.currency for p in ordered}
        if all(55 <= gap <= 130 for gap in gaps) and span_days[0] <= span <= span_days[1] and len(currencies) == 1:
            ttm = Window("TTM", ordered[-1].period_end, tuple(ordered), ordered[-1].currency, max(p.known_at for p in ordered))
    annual = [p for p in periods if p.period_type == "FY" and p.has(*fields)]
    annual.sort(key=lambda item: item.period_end, reverse=True)
    fiscal = Window("FY", annual[0].period_end, (annual[0],), annual[0].currency, annual[0].known_at) if annual else None
    if ttm and (fiscal is None or ttm.end >= fiscal.end):
        return ttm
    return fiscal


def window_sum(window: Window, name: str) -> float | None:
    values = [_finite(period.values.get(name)) for period in window.periods]
    if any(value is None for value in values):
        return None
    return float(sum(values))  # type: ignore[arg-type]


def source_label(window: Window) -> str:
    return "+".join(window.sources)


def balance_near(periods: Sequence[Period], target: date, names: Sequence[str], *, tolerance_days: int = 40) -> Period | None:
    """The period (any type) closest to ``target`` that reports every name, within the tolerance."""

    best: Period | None = None
    best_gap = tolerance_days + 1
    for period in periods:
        if not period.has(*names):
            continue
        gap = abs((period.period_end - target).days)
        if gap < best_gap:
            best, best_gap = period, gap
    return best


def opening_balance(periods: Sequence[Period], window_end: date, names: Sequence[str]) -> Period | None:
    """Balance sheet one year before the window end (the opening of a TTM/FY window)."""

    return balance_near(periods, window_end - timedelta(days=365), names)


def latest_balance(periods: Sequence[Period], names: Sequence[str]) -> Period | None:
    candidates = [period for period in periods if period.has(*names)]
    return max(candidates, key=lambda item: (item.period_end, item.period_type == "FY"), default=None)


# ---------------------------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------------------------


def minor_unit(currency: str, table: Mapping[str, Sequence[object]]) -> tuple[str, float]:
    """``GBp`` -> (``GBP``, 0.01); a major currency maps to itself with factor 1."""

    entry = table.get(currency)
    if entry:
        return str(entry[0]), float(entry[1])  # type: ignore[arg-type]
    return currency, 1.0


def to_currency(
    amount: float | None,
    source_currency: str,
    target_currency: str,
    *,
    fx_rate: float | None,
    minor_units: Mapping[str, Sequence[object]],
) -> tuple[float | None, str | None]:
    """Convert ``amount``; ``fx_rate`` is target units per one source major unit at the same date.

    Returns ``(value, reason)``. Same major currency needs no rate; otherwise a missing rate gives
    ``currency_mismatch``. Minor units (GBp) are scaled to the major unit first.
    """

    if amount is None:
        return None, "amount_unavailable"
    major, factor = minor_unit(source_currency, minor_units)
    scaled = amount * factor
    target_major, target_factor = minor_unit(target_currency, minor_units)
    scaled = scaled / target_factor if target_factor != 1.0 else scaled
    if major == target_major:
        return scaled, None
    rate = _finite(fx_rate)
    if rate is None or rate <= 0:
        return None, "currency_mismatch"
    return scaled * rate, None


# ---------------------------------------------------------------------------------------------
# Pure formulas
# ---------------------------------------------------------------------------------------------


def roe(net_income_parent: float | None, equity_open: float | None, equity_close: float | None) -> Metric:
    key, label, formula = "roe", "Return on equity", "net income to parent / average parent equity ((opening + closing) / 2)"
    if net_income_parent is None or equity_open is None or equity_close is None:
        return _unavailable(key, label, "needs net income and opening and closing parent equity", formula=formula)
    if equity_open <= 0 or equity_close <= 0:
        return _not_meaningful(key, label, "parent equity was zero or negative at the start or end of the window", formula=formula)
    average = (equity_open + equity_close) / 2.0
    return Metric(key, label, net_income_parent / average, "ratio", OK, formula=formula)


def effective_tax_rate(income_tax: float | None, pretax_income: float | None) -> float | None:
    """Tax / pretax income clamped to 0..40 %; a non-positive pretax income gives 0 (no tax shield assumed)."""

    if income_tax is None or pretax_income is None:
        return None
    if pretax_income <= 0:
        return 0.0
    return min(max(income_tax / pretax_income, 0.0), 0.40)


def nopat(ebit: float | None, tax_rate: float | None) -> float | None:
    if ebit is None or tax_rate is None:
        return None
    return ebit * (1.0 - tax_rate)


def invested_capital(equity: float | None, ib_debt: float | None, lease: float | None, cash: float | None) -> float | None:
    """equity + interest-bearing debt + leases (when reported) - cash and short-term investments."""

    if equity is None or ib_debt is None or cash is None:
        return None
    return equity + ib_debt + (lease or 0.0) - cash


def roic(nopat_value: float | None, capital_open: float | None, capital_close: float | None) -> Metric:
    key, label = "roic", "Return on invested capital"
    formula = "NOPAT / average (equity + debt + leases - cash); NOPAT = EBIT x (1 - tax rate 0..40 %)"
    if nopat_value is None or capital_open is None or capital_close is None:
        return _unavailable(key, label, "needs EBIT, tax, and opening and closing invested capital", formula=formula)
    average = (capital_open + capital_close) / 2.0
    if average <= 0:
        return _not_meaningful(key, label, "average invested capital is zero or negative", formula=formula)
    return Metric(key, label, nopat_value / average, "ratio", OK, formula=formula)


def margin(key: str, label: str, item: float | None, revenue: float | None) -> Metric:
    formula = f"{label.lower()} / revenue over the same window"
    if item is None or revenue is None:
        return _unavailable(key, label, "needs the item and revenue in the same window", formula=formula)
    if revenue <= 0:
        return _not_meaningful(key, label, "revenue is zero or negative", formula=formula)
    return Metric(key, label, item / revenue, "ratio", OK, formula=formula)


def free_cash_flow(cfo: float | None, capex: float | None) -> float | None:
    """Cash from operations - capex, where capex is the (positive) outflow for PP&E and intangibles."""

    if cfo is None or capex is None:
        return None
    return cfo - abs(capex)


def net_debt(ib_debt: float | None, lease: float | None, cash: float | None) -> float | None:
    if ib_debt is None or cash is None:
        return None
    return ib_debt + (lease or 0.0) - cash


def ebitda(ebit: float | None, da: float | None) -> float | None:
    if ebit is None or da is None:
        return None
    return ebit + abs(da)


def net_debt_to_ebitda(net_debt_value: float | None, ebitda_value: float | None) -> Metric:
    key, label, formula = "net_debt_to_ebitda", "Net debt / EBITDA", "net debt / (EBIT + D&A) over the window"
    if net_debt_value is None or ebitda_value is None:
        return _unavailable(key, label, "needs net debt and EBIT plus D&A", formula=formula, unit="multiple")
    if ebitda_value <= 0:
        return _not_meaningful(key, label, "EBITDA is zero or negative", formula=formula, unit="multiple")
    return Metric(key, label, net_debt_value / ebitda_value, "multiple", OK, formula=formula)


def debt_to_equity(ib_debt: float | None, equity_parent: float | None) -> Metric:
    key, label, formula = "debt_to_equity", "Debt / equity", "interest-bearing debt / parent equity"
    if ib_debt is None or equity_parent is None:
        return _unavailable(key, label, "needs interest-bearing debt and parent equity", formula=formula, unit="multiple")
    if equity_parent <= 0:
        return _not_meaningful(key, label, "parent equity is zero or negative", formula=formula, unit="multiple")
    return Metric(key, label, ib_debt / equity_parent, "multiple", OK, formula=formula)


def market_cap(price: float | None, shares: float | None) -> float | None:
    if price is None or shares is None or price <= 0 or shares <= 0:
        return None
    return price * shares


def enterprise_value(mcap: float | None, net_debt_value: float | None, minority: float | None) -> float | None:
    if mcap is None or net_debt_value is None:
        return None
    return mcap + net_debt_value + (minority or 0.0)


def multiple(key: str, label: str, numerator: float | None, denominator: float | None, *, formula: str, denominator_name: str) -> Metric:
    """numerator / denominator where a non-positive denominator is a loss/negative base, never a negative multiple."""

    if numerator is None or denominator is None:
        return _unavailable(key, label, f"needs {denominator_name} and the numerator in one currency", formula=formula, unit="multiple")
    if denominator <= 0:
        return _not_meaningful(key, label, f"not meaningful (loss): {denominator_name} is zero or negative", formula=formula, unit="multiple")
    if numerator <= 0:
        return _not_meaningful(key, label, "not meaningful: the numerator (market cap or enterprise value) is zero or negative", formula=formula, unit="multiple")
    return Metric(key, label, numerator / denominator, "multiple", OK, formula=formula)


def yield_of(key: str, label: str, amount: float | None, mcap: float | None, *, formula: str) -> Metric:
    if amount is None or mcap is None:
        return _unavailable(key, label, "needs the amount and market cap", formula=formula)
    if mcap <= 0:
        return _unavailable(key, label, "market cap is not positive", formula=formula)
    return Metric(key, label, amount / mcap, "ratio", OK, formula=formula)


def dividend_yield(dividends_per_share_12m: float | None, price: float | None) -> Metric:
    key, label, formula = "dividend_yield", "Dividend yield", "dividends per share paid over the trailing 12 months / price"
    if dividends_per_share_12m is None or price is None or price <= 0:
        return _unavailable(key, label, "needs dividends per share (12 months) and a price", formula=formula)
    return Metric(key, label, dividends_per_share_12m / price, "ratio", OK, formula=formula)


def cagr(start: float | None, end: float | None, years: float, *, key: str, label: str) -> Metric:
    formula = f"(end / start)^(1 / {years:g} years) - 1"
    if start is None or end is None or years <= 0:
        return _unavailable(key, label, "needs the first and last value of the window", formula=formula)
    if start <= 0 or end <= 0:
        return _not_meaningful(key, label, "start or end value is zero or negative", formula=formula)
    return Metric(key, label, (end / start) ** (1.0 / years) - 1.0, "ratio", OK, formula=formula)


def percentile_rank(history: Sequence[float], current: float | None) -> float | None:
    """Share of historical observations at or below ``current`` (0 cheapest .. 1 dearest)."""

    if current is None:
        return None
    values = [v for v in (_finite(item) for item in history) if v is not None]
    if not values:
        return None
    return sum(1 for item in values if item <= current) / len(values)


def median(values: Iterable[float | None]) -> float | None:
    clean = sorted(v for v in (_finite(item) for item in values) if v is not None)
    if not clean:
        return None
    middle = len(clean) // 2
    return clean[middle] if len(clean) % 2 else (clean[middle - 1] + clean[middle]) / 2.0


def implied_growth_from_pe(pe: float | None, payout: float | None, cost_of_equity: float | None) -> Metric:
    """g in P/E = payout / (r - g)  =>  g = r - payout / (P/E). r must come from configuration."""

    key, label, formula = "implied_growth_pe", "Implied growth (P/E)", "g = r - payout / (P/E), from P/E = payout / (r - g)"
    if cost_of_equity is None:
        return _unavailable(key, label, "cost of equity is not configured (configs/stock_fundamentals_v1.yaml valuation.cost_of_equity)", formula=formula)
    if pe is None:
        return _unavailable(key, label, "needs a meaningful P/E", formula=formula)
    if payout is None or payout <= 0:
        return _unavailable(key, label, "needs a positive payout ratio (dividends / net income)", formula=formula)
    g = cost_of_equity - payout / pe
    if g >= cost_of_equity:
        return _not_meaningful(key, label, "implied growth is not below the cost of equity", formula=formula)
    return Metric(key, label, g, "ratio", OK, formula=formula)


def _dcf_value(fcf0: float, growth: float, cost: float, years: int, terminal: float) -> float:
    present = 0.0
    cash = fcf0
    for year in range(1, years + 1):
        cash *= 1.0 + growth
        present += cash / (1.0 + cost) ** year
    terminal_value = cash * (1.0 + terminal) / (cost - terminal)
    return present + terminal_value / (1.0 + cost) ** years


def implied_growth_from_dcf(
    mcap: float | None,
    fcf: float | None,
    cost_of_equity: float | None,
    terminal_growth: float | None,
    stage1_years: int,
) -> Metric:
    """Stage-1 FCF growth g such that the 2-stage DCF of FCF at ``cost_of_equity`` equals the market cap."""

    key, label = "implied_growth_dcf", "Implied growth (2-stage DCF)"
    formula = f"g such that sum FCF(1+g)^t/(1+r)^t over {stage1_years} years + terminal value = market cap"
    if cost_of_equity is None or terminal_growth is None:
        missing = "cost of equity" if cost_of_equity is None else "terminal growth"
        return _unavailable(key, label, f"{missing} is not configured (configs/stock_fundamentals_v1.yaml valuation)", formula=formula)
    if terminal_growth >= cost_of_equity:
        return _unavailable(key, label, "terminal growth must be below the cost of equity", formula=formula)
    if mcap is None or fcf is None:
        return _unavailable(key, label, "needs market cap and free cash flow", formula=formula)
    if fcf <= 0 or mcap <= 0:
        return _not_meaningful(key, label, "free cash flow or market cap is zero or negative", formula=formula)
    low, high = -0.5, 1.0
    if _dcf_value(fcf, low, cost_of_equity, stage1_years, terminal_growth) > mcap:
        return _not_meaningful(key, label, "market cap is below the DCF value even at -50 % growth", formula=formula)
    if _dcf_value(fcf, high, cost_of_equity, stage1_years, terminal_growth) < mcap:
        return _not_meaningful(key, label, "market cap needs more than +100 % stage-1 growth", formula=formula)
    for _ in range(80):
        mid = (low + high) / 2.0
        if _dcf_value(fcf, mid, cost_of_equity, stage1_years, terminal_growth) < mcap:
            low = mid
        else:
            high = mid
    return Metric(key, label, (low + high) / 2.0, "ratio", OK, formula=formula)


def with_context(metric: Metric, **changes: object) -> Metric:
    return replace(metric, **changes)  # type: ignore[arg-type]
