"""Formula registry for normal-stock metrics: one formula ID per metric (Blueprint Part 1 §6).

Pure metadata, no calculation: the calculations stay the single functions in ``stock_metrics``.
Each entry records the numerator, denominator, period basis and units, so a number shown anywhere
can be traced to exactly one definition. FCF is a screening proxy (CFO minus capex), not FCFE and not
owner earnings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from etf_cockpit.analysis.stock_metrics import FCF_PROXY_LABEL


@dataclass(frozen=True)
class FormulaSpec:
    formula_id: str
    metric_key: str
    label: str
    numerator: str
    denominator: str  # "1" when the metric is a plain amount
    period: str  # TTM | FY | latest balance | spot | multi-year
    units: str  # ratio | multiple | money | percentile
    note: str = ""


def _spec(metric_key: str, label: str, numerator: str, denominator: str, period: str, units: str, note: str = "") -> FormulaSpec:
    return FormulaSpec(f"stock.{metric_key}.v1", metric_key, label, numerator, denominator, period, units, note)


_SPECS: tuple[FormulaSpec, ...] = (
    _spec("revenue", "Revenue", "revenue", "1", "TTM|FY", "money"),
    _spec("ebit", "Operating profit (EBIT)", "EBIT", "1", "TTM|FY", "money"),
    _spec("net_income", "Net income to parent", "net income attributable to parent", "1", "TTM|FY", "money"),
    _spec("gross_margin", "Gross margin", "gross profit", "revenue", "TTM|FY", "ratio"),
    _spec("ebit_margin", "EBIT margin", "EBIT", "revenue", "TTM|FY", "ratio"),
    _spec("net_margin", "Net margin", "net income attributable to parent", "revenue", "TTM|FY", "ratio"),
    _spec("roe", "Return on equity", "net income attributable to parent", "closing parent equity", "TTM|FY", "ratio"),
    _spec("nopat", "NOPAT", "EBIT x (1 - effective tax rate clamped to 0..40 %)", "1", "TTM|FY", "money"),
    _spec("roic", "Return on invested capital", "NOPAT", "closing (parent equity + interest-bearing debt + leases - cash)", "TTM|FY", "ratio",
          "not meaningful when either capital endpoint is zero or negative"),
    _spec("accruals", "Accruals ratio", "net income - CFO", "average total assets", "TTM|FY", "ratio"),
    _spec("cash_conversion", "Cash conversion", "CFO", "net income attributable to parent", "TTM|FY", "ratio"),
    _spec("fcf_conversion", "FCF / net income", "CFO - capex", "net income attributable to parent", "TTM|FY", "ratio", FCF_PROXY_LABEL),
    _spec("fcf", "Free cash flow (screening proxy)", "CFO - capex (PP&E and intangibles)", "1", "TTM|FY", "money",
          f"{FCF_PROXY_LABEL}; a screening proxy, not owner earnings"),
    _spec("fcf_yield", "FCF yield", "CFO - capex", "market cap", "TTM|FY / spot", "ratio", FCF_PROXY_LABEL),
    _spec("net_debt", "Net debt", "interest-bearing debt + lease liabilities - cash and short-term investments", "1", "latest balance", "money",
          "finance leases are counted once; a missing debt part is never 0"),
    _spec("net_debt_to_ebitda", "Net debt / EBITDA", "net debt", "EBIT + D&A", "latest balance / TTM|FY", "multiple",
          "no multiple when EBITDA is zero or negative"),
    _spec("debt_to_equity", "Debt / equity", "interest-bearing debt", "parent equity", "latest balance", "multiple"),
    _spec("interest_cover", "Interest cover", "EBIT", "interest expense", "TTM|FY", "multiple"),
    _spec("revenue_cagr", "Revenue growth (CAGR)", "(last / first) ^ (1 / fiscal years) - 1 of revenue", "1", "multi-year", "ratio",
          "consecutive fiscal years only; a missing year is never bridged"),
    _spec("net_income_cagr", "Net income growth (CAGR)", "(last / first) ^ (1 / fiscal years) - 1 of net income", "1", "multi-year", "ratio",
          "consecutive fiscal years only; a missing year is never bridged"),
    _spec("dilution", "Share dilution", "closing shares", "opening shares", "multi-year", "ratio", "minus 1"),
    _spec("market_cap", "Market cap", "decision-time price x shares", "1", "spot", "money"),
    _spec("ev", "Enterprise value", "market cap + net debt + minority interest", "1", "spot", "money"),
    _spec("pe", "P/E", "market cap", "net income attributable to parent", "spot / TTM|FY", "multiple"),
    _spec("ev_ebit", "EV / EBIT", "enterprise value", "EBIT", "spot / TTM|FY", "multiple"),
    _spec("ev_sales", "EV / Sales", "enterprise value", "revenue", "spot / TTM|FY", "multiple"),
    _spec("pb", "P/B", "market cap", "parent equity", "spot / latest balance", "multiple"),
    _spec("earnings_yield", "Earnings yield", "net income attributable to parent", "market cap", "spot / TTM|FY", "ratio"),
    _spec("ebit_ev_yield", "EBIT / EV", "EBIT", "enterprise value", "spot / TTM|FY", "ratio"),
    _spec("dividend_yield", "Dividend yield", "dividends per share (12 months)", "price", "12 months", "ratio"),
    _spec("pe_percentile", "P/E percentile vs own history", "past month-end P/E readings at or below the current P/E", "all readings", "5y point-in-time", "percentile"),
    _spec("pe_vs_peers", "P/E vs peer median", "own P/E", "median peer P/E", "spot", "ratio", "minus 1; the instrument is excluded from the peer set"),
    _spec("implied_growth_pe", "Implied growth (P/E)", "cost of equity - payout / P/E", "1", "spot", "ratio", "needs a configured cost of equity"),
    _spec("implied_growth_dcf", "Implied growth (2-stage DCF)", "stage-1 FCF growth that equates the DCF to market cap", "1", "spot", "ratio",
          f"needs configured cost of equity and terminal growth; FCF is {FCF_PROXY_LABEL}"),
)

FORMULA_REGISTRY: Mapping[str, FormulaSpec] = MappingProxyType({spec.metric_key: spec for spec in _SPECS})


def formula_for(metric_key: str) -> FormulaSpec | None:
    """The one registered formula of a metric key, or ``None`` when the metric has no definition."""

    return FORMULA_REGISTRY.get(metric_key)


def formula_ids() -> tuple[str, ...]:
    return tuple(spec.formula_id for spec in _SPECS)
