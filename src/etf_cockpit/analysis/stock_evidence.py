"""Stock evidence for one instrument: metrics, valuation context and the three score components.

Pure calculation over already-loaded periods and market inputs (no I/O, no clock). The score
(value, quality, analyst revision), the stock pages and Stock Research all read this one result,
so every number has a single calculation path (definitions: ``stock_metrics``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis import stock_text as tx
from etf_cockpit.analysis.stock_metrics import Metric, Period

NO_PERIODS_REASON = "no fundamentals have been loaded for this instrument"


@dataclass(frozen=True)
class MarketInputs:
    """Decision-time market data; every value must already be known at the decision time."""

    price: float | None = None  # last close in ``price_currency`` (a minor unit such as GBp is allowed)
    price_currency: str | None = None
    price_date: date | None = None
    fx_to_reporting: float | None = None  # reporting-currency units per one major quote-currency unit at ``price_date``
    dividends_per_share_12m: float | None = None  # quote-currency units, trailing 12 months
    price_series: tuple[tuple[date, float], ...] = ()  # month-end closes for the valuation history
    shares_fallback: float | None = None
    shares_fallback_known_at: datetime | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class AnalystInputs:
    eps_current: float | None = None
    eps_90d_ago: float | None = None
    revisions_up_30d: float | None = None
    revisions_down_30d: float | None = None
    known_at: datetime | None = None
    source: str = "yfinance"
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class SubScore:
    key: str
    label: str
    value: float | None
    display: str
    score: float | None
    reason: str | None = None


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    score_10: float | None
    inputs: tuple[SubScore, ...]
    source_id: str
    as_of: str | None
    freshness: str
    why: str

    @property
    def used(self) -> tuple[SubScore, ...]:
        return tuple(item for item in self.inputs if item.score is not None)

    @property
    def missing(self) -> tuple[SubScore, ...]:
        return tuple(item for item in self.inputs if item.score is None)


@dataclass(frozen=True)
class PeerStat:
    key: str
    own: float | None
    median: float | None
    count: int
    premium: float | None  # own / median - 1


@dataclass(frozen=True)
class StockEvidence:
    instrument_id: str
    decision_time: datetime
    reporting_currency: str | None
    metrics: Mapping[str, Metric]
    components: Mapping[str, Component]
    history_points: int
    peer_stats: Mapping[str, PeerStat]
    periods_used: tuple[str, ...]
    sources: tuple[str, ...]
    unavailable_reason: str | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def metric(self, key: str) -> Metric:
        return self.metrics[key]


# key -> (label, unit, formula text lives on the Metric itself)
METRIC_LABELS: dict[str, tuple[str, str]] = {
    "revenue": ("Revenue", "money"),
    "ebit": ("Operating profit (EBIT)", "money"),
    "net_income": ("Net income to parent", "money"),
    "fcf": ("Free cash flow", "money"),
    "net_debt": ("Net debt", "money"),
    "market_cap": ("Market cap", "money"),
    "ev": ("Enterprise value", "money"),
    "gross_margin": ("Gross margin", "ratio"),
    "ebit_margin": ("EBIT margin", "ratio"),
    "net_margin": ("Net margin", "ratio"),
    "roe": ("Return on equity", "ratio"),
    "roic": ("Return on invested capital", "ratio"),
    "fcf_conversion": ("FCF / net income", "ratio"),
    "fcf_yield": ("FCF yield", "ratio"),
    "earnings_yield": ("Earnings yield", "ratio"),
    "ebit_ev_yield": ("EBIT / EV", "ratio"),
    "net_debt_to_ebitda": ("Net debt / EBITDA", "multiple"),
    "debt_to_equity": ("Debt / equity", "multiple"),
    "pe": ("P/E", "multiple"),
    "ev_ebit": ("EV / EBIT", "multiple"),
    "ev_sales": ("EV / Sales", "multiple"),
    "pb": ("P/B", "multiple"),
    "dividend_yield": ("Dividend yield", "ratio"),
    "revenue_cagr": ("Revenue growth (CAGR)", "ratio"),
    "net_income_cagr": ("Net income growth (CAGR)", "ratio"),
    "pe_percentile": ("P/E percentile vs own history", "percentile"),
    "pe_vs_peers": ("P/E vs peer median", "ratio"),
    "implied_growth_pe": ("Implied growth (P/E)", "ratio"),
    "implied_growth_dcf": ("Implied growth (2-stage DCF)", "ratio"),
}


def linear_score(value: float | None, low: float, high: float) -> float | None:
    """0 at ``low``, 10 at ``high`` (``low`` may be above ``high``), linear and clamped."""

    if value is None or low == high:
        return None
    fraction = (value - low) / (high - low)
    return round(10.0 * min(max(fraction, 0.0), 1.0), 4)


def _metric(key: str, **kwargs: object) -> Metric:
    label, unit = METRIC_LABELS[key]
    values: dict[str, object] = {"key": key, "label": label, "unit": unit}
    values.update(kwargs)
    return Metric(**values)  # type: ignore[arg-type]


def _missing(key: str, reason: str, formula: str = "") -> Metric:
    return _metric(key, value=None, status=sm.UNAVAILABLE, reason=reason, formula=formula)


def _from(key: str, base: Metric, **context: object) -> Metric:
    label, unit = METRIC_LABELS[key]
    return sm.with_context(base, key=key, label=label, unit=unit, **context)


class _Builder:
    """One evidence build; helpers close over the known periods and the decision time."""

    def __init__(
        self,
        instrument_id: str,
        periods: Sequence[Period],
        decision_time: datetime,
        market: MarketInputs,
        analyst: AnalystInputs | None,
        config: Mapping[str, object],
        peer_values: Mapping[str, Mapping[str, float]] | None,
        no_data_reason: str | None,
    ) -> None:
        self.id = instrument_id
        self.all_periods = list(periods)
        self.decision_time = decision_time
        self.market = market
        self.analyst = analyst
        self.config = config
        self.peer_values = peer_values or {}
        self.no_data_reason = no_data_reason
        self.known = sm.known_periods(self.all_periods, decision_time)
        reporting = config.get("reporting", {}) if isinstance(config.get("reporting"), Mapping) else {}
        self.minor = reporting.get("minor_currency_units", {}) or {}  # type: ignore[union-attr]
        self.span = tuple(reporting.get("ttm_span_days", (240, 300)))  # type: ignore[union-attr]
        self.stale_days = int(reporting.get("max_balance_staleness_days", 400))  # type: ignore[union-attr]
        valuation = config.get("valuation", {}) if isinstance(config.get("valuation"), Mapping) else {}
        self.valuation = valuation
        self.scoring = config.get("scoring", {}) if isinstance(config.get("scoring"), Mapping) else {}
        self.reporting_currency = self.known[-1].currency if self.known else None
        self.metrics: dict[str, Metric] = {}
        self.notes: list[str] = []
        self.peer_stats: dict[str, PeerStat] = {}
        self.history_points = 0

    # ----- windows ---------------------------------------------------------------------

    def window(self, *fields: str) -> sm.Window | None:
        return sm.flow_window(self.known, fields, span_days=self.span)  # type: ignore[arg-type]

    def _flow(self, window: sm.Window | None, name: str) -> float | None:
        return None if window is None else sm.window_sum(window, name)

    def _no_window(self, what: str, fields: Sequence[str] = ()) -> str:
        if not self.known:
            return self.no_data_reason or NO_PERIODS_REASON
        missing = [name for name in fields if not any(p.has(name) for p in self.known)]
        if missing:
            return "not reported by the source: " + ", ".join(name.replace("_", " ") for name in missing)
        quarters = sum(1 for p in self.known if p.period_type == "Q" and p.has(*fields))
        years = sum(1 for p in self.known if p.period_type == "FY" and p.has(*fields))
        return (
            f"needs 4 consecutive quarters or one fiscal year with {what}; "
            f"{quarters} quarters (not consecutive or fewer than 4) and {years} fiscal years carry them"
        )

    def _ctx(self, window: sm.Window, **extra: object) -> dict[str, object]:
        return {"basis": window.basis, "as_of": window.end.isoformat(), "currency": window.currency, "source": sm.source_label(window), **extra}

    # ----- market cap ------------------------------------------------------------------

    def price_in_reporting(self) -> tuple[float | None, str | None]:
        market = self.market
        if market.unavailable_reason and market.price is None:
            return None, market.unavailable_reason
        if market.price is None or not market.price_currency:
            return None, "no decision-time price is available"
        if self.reporting_currency is None:
            return None, self.no_data_reason or NO_PERIODS_REASON
        price, reason = sm.to_currency(
            market.price,
            market.price_currency,
            self.reporting_currency,
            fx_rate=market.fx_to_reporting,
            minor_units=self.minor,
        )
        if price is None:
            return None, (
                f"currency_mismatch: price in {market.price_currency}, statements in {self.reporting_currency}, "
                "no FX rate at the price date"
                if reason == "currency_mismatch"
                else str(reason)
            )
        return price, None

    def shares(self) -> tuple[float | None, str | None, str | None]:
        market = self.market
        provider_ok = bool(market.shares_fallback and market.shares_fallback_known_at and market.shares_fallback_known_at <= self.decision_time)
        balance = sm.latest_balance(self.known, ["shares_outstanding"])
        if balance is not None:
            filed = balance.values["shares_outstanding"]
            tolerance = float(self.valuation.get("share_count_tolerance", 0.25))
            if provider_ok and market.shares_fallback and not (1 / (1 + tolerance) <= filed / market.shares_fallback <= 1 + tolerance):
                self.notes.append(
                    f"Share count in the {balance.period_end.isoformat()} statements ({filed:,.0f}) differs from the provider count "
                    f"({market.shares_fallback:,.0f}) by more than {tolerance:.0%} (share classes or a later split); the provider count is used."
                )
                return market.shares_fallback, "yfinance:snapshot", market.shares_fallback_known_at.date().isoformat()  # type: ignore[union-attr]
            return filed, balance.source_of("shares_outstanding"), balance.period_end.isoformat()
        if provider_ok:
            return market.shares_fallback, "yfinance:snapshot", market.shares_fallback_known_at.date().isoformat()  # type: ignore[union-attr]
        return None, None, None

    def market_cap(self) -> tuple[float | None, str | None, dict[str, object]]:
        price, reason = self.price_in_reporting()
        if price is None:
            return None, reason, {}
        shares, source, as_of = self.shares()
        if shares is None:
            return None, "no share count from a filing known at the decision time", {}
        value = sm.market_cap(price, shares)
        if value is None:
            return None, "price or share count is not positive", {}
        return value, None, {"basis": "spot", "as_of": self.market.price_date.isoformat() if self.market.price_date else as_of, "source": f"price x shares ({source})"}

    # ----- build -----------------------------------------------------------------------

    def build(self) -> StockEvidence:
        if not self.known:
            reason = self.no_data_reason or NO_PERIODS_REASON
            for key in METRIC_LABELS:
                self.metrics[key] = _missing(key, reason)
            components = self.components()
            return self._finish(components, reason)
        self.flow_metrics()
        self.balance_metrics()
        self.valuation_metrics()
        components = self.components()
        return self._finish(components, None)

    def _finish(self, components: dict[str, Component], reason: str | None) -> StockEvidence:
        used = tuple(sorted({f"{p.period_type} {p.period_end.isoformat()}" for p in self.known[-6:]}))
        sources = tuple(sorted({p.source for p in self.known}))
        return StockEvidence(
            self.id,
            self.decision_time,
            self.reporting_currency,
            dict(self.metrics),
            components,
            self.history_points,
            dict(self.peer_stats),
            used,
            sources,
            reason,
            tuple(self.notes),
        )

    def flow_metrics(self) -> None:
        for key, item, formula_label in (
            ("gross_margin", "gross_profit", "gross profit"),
            ("ebit_margin", "ebit", "EBIT"),
            ("net_margin", "net_income_parent", "net income to parent"),
        ):
            window = self.window("revenue", item)
            if window is None:
                self.metrics[key] = _missing(key, self._no_window(f"revenue and {formula_label}", ("revenue", item)))
                continue
            metric = sm.margin(key, METRIC_LABELS[key][0], sm.window_sum(window, item), sm.window_sum(window, "revenue"))
            self.metrics[key] = _from(key, metric, **self._ctx(window))
        for key, item, label in (
            ("revenue", "revenue", "revenue"),
            ("ebit", "ebit", "EBIT"),
            ("net_income", "net_income_parent", "net income to parent"),
        ):
            window = self.window(item)
            if window is None:
                self.metrics[key] = _missing(key, self._no_window(label))
                continue
            self.metrics[key] = _metric(key, value=sm.window_sum(window, item), status=sm.OK, formula=f"{label}, {window.basis} window", **self._ctx(window))
        self.metrics["fcf"], fcf_window = self._fcf()
        self.roe_roic()
        self.growth()
        self.fcf_conversion()

    def _fcf(self) -> tuple[Metric, sm.Window | None]:
        window = self.window("cfo", "capex")
        if window is None:
            return _missing("fcf", self._no_window("cash from operations and capex", ("cfo", "capex")), "cash from operations - capex"), None
        value = sm.free_cash_flow(sm.window_sum(window, "cfo"), sm.window_sum(window, "capex"))
        return _metric("fcf", value=value, status=sm.OK, formula="cash from operations - capex (PP&E and intangibles)", **self._ctx(window)), window

    def roe_roic(self) -> None:
        window = self.window("net_income_parent")
        if window is None:
            self.metrics["roe"] = _missing("roe", self._no_window("net income to parent", ("net_income_parent",)))
        else:
            close = sm.balance_near(self.known, window.end, ["equity_parent"], tolerance_days=45)
            opening = sm.opening_balance(self.known, window.end, ["equity_parent"])
            base = sm.roe(
                sm.window_sum(window, "net_income_parent"),
                None if opening is None else opening.values["equity_parent"],
                None if close is None else close.values["equity_parent"],
            )
            if close is not None and opening is not None and (close.currency != window.currency or opening.currency != window.currency):
                base = _missing("roe", "currency_mismatch between income and equity")
            self.metrics["roe"] = _from("roe", base, **self._ctx(window))
        window = self.window("ebit", "income_tax", "pretax_income")
        if window is None:
            self.metrics["roic"] = _missing("roic", self._no_window("EBIT, income tax and pretax income", ("ebit", "income_tax", "pretax_income")))
            return
        names = ["equity_parent", "ib_debt", "cash_sti"]
        close = sm.balance_near(self.known, window.end, names, tolerance_days=45)
        opening = sm.opening_balance(self.known, window.end, names)
        rate = sm.effective_tax_rate(sm.window_sum(window, "income_tax"), sm.window_sum(window, "pretax_income"))
        nopat = sm.nopat(sm.window_sum(window, "ebit"), rate)

        def capital(period: Period | None) -> float | None:
            if period is None:
                return None
            return sm.invested_capital(
                period.values.get("equity_parent"),
                period.values.get("ib_debt"),
                period.values.get("lease_liabilities"),
                period.values.get("cash_sti"),
            )

        self.metrics["roic"] = _from("roic", sm.roic(nopat, capital(opening), capital(close)), **self._ctx(window))

    def growth(self) -> None:
        years = int((self.config.get("growth", {}) or {}).get("years", 3))  # type: ignore[union-attr]
        annual = sorted((p for p in self.known if p.period_type == "FY"), key=lambda item: item.period_end)
        for key, name in (("revenue_cagr", "revenue"), ("net_income_cagr", "net_income_parent")):
            label = METRIC_LABELS[key][0]
            series = [p for p in annual if p.has(name)]
            if len(series) < years + 1:
                self.metrics[key] = _missing(
                    key,
                    f"needs {years + 1} fiscal years of {name.replace('_', ' ')}; {len(series)} known at the decision time",
                    f"(end / start)^(1 / {years} years) - 1",
                )
                continue
            last, first = series[-1], series[-1 - years]
            span_years = round((last.period_end - first.period_end).days / 365.25)
            base = sm.cagr(first.values[name], last.values[name], float(span_years or years), key=key, label=label)
            self.metrics[key] = _from(
                key,
                base,
                basis="FY",
                as_of=last.period_end.isoformat(),
                currency=last.currency,
                source=f"FY{first.period_end.year}->FY{last.period_end.year} ({last.source})",
            )

    def balance_metrics(self) -> None:
        latest = sm.latest_balance(self.known, ["ib_debt", "cash_sti"])
        if latest is None:
            reason = "no balance sheet with interest-bearing debt and cash is known at the decision time"
            self.metrics["net_debt"] = _missing("net_debt", reason, "debt + leases - cash and short-term investments")
        else:
            lease = latest.values.get("lease_liabilities")
            value = sm.net_debt(latest.values.get("ib_debt"), lease, latest.values.get("cash_sti"))
            note = "" if lease is not None else " (leases not reported separately)"
            self.metrics["net_debt"] = _metric(
                "net_debt",
                value=value,
                status=sm.OK,
                basis="latest balance",
                as_of=latest.period_end.isoformat(),
                currency=latest.currency,
                source=latest.source,
                formula="interest-bearing debt + lease liabilities - cash and short-term investments" + note,
            )
        equity = sm.latest_balance(self.known, ["equity_parent", "ib_debt"])
        if equity is None:
            self.metrics["debt_to_equity"] = _missing("debt_to_equity", "no balance sheet with parent equity and debt is known at the decision time")
        else:
            self.metrics["debt_to_equity"] = _from(
                "debt_to_equity",
                sm.debt_to_equity(equity.values.get("ib_debt"), equity.values.get("equity_parent")),
                basis="latest balance",
                as_of=equity.period_end.isoformat(),
                currency=equity.currency,
                source=equity.source,
            )
        window = self.window("ebit", "da")
        net = self.metrics["net_debt"]
        if window is None or not net.available:
            reason = self._no_window("EBIT and D&A", ("ebit", "da")) if window is None else str(net.reason)
            self.metrics["net_debt_to_ebitda"] = _missing("net_debt_to_ebitda", reason, "net debt / (EBIT + D&A)")
        elif net.currency != window.currency:
            self.metrics["net_debt_to_ebitda"] = _missing("net_debt_to_ebitda", "currency_mismatch between debt and income")
        else:
            value = sm.ebitda(sm.window_sum(window, "ebit"), sm.window_sum(window, "da"))
            self.metrics["net_debt_to_ebitda"] = _from("net_debt_to_ebitda", sm.net_debt_to_ebitda(net.value, value), **self._ctx(window))

    def valuation_metrics(self) -> None:
        mcap, reason, ctx = self.market_cap()
        if mcap is None:
            for key in ("market_cap", "ev", "pe", "ev_ebit", "ev_sales", "pb", "fcf_yield", "earnings_yield", "ebit_ev_yield", "dividend_yield", "pe_percentile", "pe_vs_peers", "implied_growth_pe", "implied_growth_dcf"):
                if key == "dividend_yield":
                    continue
                self.metrics[key] = _missing(key, str(reason))
            self.dividend_yield()
            return
        self.metrics["market_cap"] = _metric("market_cap", value=mcap, status=sm.OK, currency=self.reporting_currency, formula="decision-time price x shares of the latest known filing", **ctx)
        net = self.metrics["net_debt"]
        minority = sm.latest_balance(self.known, ["minority_interest"])
        minority_value = minority.values["minority_interest"] if minority is not None else 0.0
        ev = sm.enterprise_value(mcap, net.value if net.available else None, minority_value)
        if ev is None:
            self.metrics["ev"] = _missing("ev", f"needs net debt: {net.reason}", "market cap + net debt + minority interest")
        else:
            self.metrics["ev"] = _metric("ev", value=ev, status=sm.OK, currency=self.reporting_currency, formula="market cap + net debt + minority interest", basis="spot", as_of=net.as_of, source=f"market cap + {net.source}")
        ni_window = self.window("net_income_parent")
        ebit_window = self.window("ebit")
        revenue_window = self.window("revenue")
        self.multiple("pe", mcap, ni_window, "net_income_parent", "market cap / net income to parent", "net income to parent")
        self.multiple("ev_ebit", ev, ebit_window, "ebit", "EV / EBIT", "EBIT")
        self.multiple("ev_sales", ev, revenue_window, "revenue", "EV / revenue", "revenue")
        equity = sm.latest_balance(self.known, ["equity_parent"])
        if equity is None:
            self.metrics["pb"] = _missing("pb", "no parent equity is known at the decision time", "market cap / parent equity")
        elif equity.currency != self.reporting_currency:
            self.metrics["pb"] = _missing("pb", "currency_mismatch between market cap and equity")
        else:
            base = sm.multiple("pb", "P/B", mcap, equity.values["equity_parent"], formula="market cap / parent equity", denominator_name="parent equity")
            self.metrics["pb"] = _from("pb", base, basis="latest balance", as_of=equity.period_end.isoformat(), currency=equity.currency, source=equity.source)
        fcf = self.metrics["fcf"]
        if fcf.available and fcf.currency == self.reporting_currency:
            self.metrics["fcf_yield"] = _from("fcf_yield", sm.yield_of("fcf_yield", "FCF yield", fcf.value, mcap, formula="free cash flow / market cap"), basis=fcf.basis, as_of=fcf.as_of, currency=None, source=fcf.source)
        else:
            self.metrics["fcf_yield"] = _missing("fcf_yield", str(fcf.reason or "currency_mismatch between FCF and market cap"), "free cash flow / market cap")
        self.metrics["earnings_yield"] = self._yield_of_metric("earnings_yield", "net_income", mcap, "net income to parent / market cap")
        ebit = self.metrics["ebit"]
        if ebit.available and ev is not None and ev > 0 and ebit.currency == self.reporting_currency:
            self.metrics["ebit_ev_yield"] = _from("ebit_ev_yield", sm.yield_of("ebit_ev_yield", "EBIT / EV", ebit.value, ev, formula="EBIT / enterprise value"), basis=ebit.basis, as_of=ebit.as_of, source=ebit.source)
        else:
            self.metrics["ebit_ev_yield"] = _missing("ebit_ev_yield", "needs EBIT and a positive enterprise value", "EBIT / enterprise value")
        self.dividend_yield()
        self.history(mcap)
        self.peer_context()
        self.reverse_valuation(mcap)

    def _yield_of_metric(self, key: str, source_key: str, mcap: float, formula: str) -> Metric:
        item = self.metrics[source_key]
        if not item.available or item.currency != self.reporting_currency:
            return _missing(key, str(item.reason or "currency_mismatch between income and market cap"), formula)
        return _from(key, sm.yield_of(key, METRIC_LABELS[key][0], item.value, mcap, formula=formula), basis=item.basis, as_of=item.as_of, source=item.source)

    def multiple(self, key: str, numerator: float | None, window: sm.Window | None, item: str, formula: str, denominator_name: str) -> None:
        if window is None:
            self.metrics[key] = _missing(key, self._no_window(denominator_name, (item,)), formula)
            return
        if window.currency != self.reporting_currency:
            self.metrics[key] = _missing(key, "currency_mismatch between statements and market cap", formula)
            return
        if numerator is None:
            self.metrics[key] = _missing(key, "needs enterprise value (net debt unavailable)" if key.startswith("ev") else "needs market cap", formula)
            return
        base = sm.multiple(key, METRIC_LABELS[key][0], numerator, sm.window_sum(window, item), formula=formula, denominator_name=denominator_name)
        self.metrics[key] = _from(key, base, **self._ctx(window))

    def dividend_yield(self) -> None:
        market = self.market
        base = sm.dividend_yield(market.dividends_per_share_12m, market.price)
        if market.dividends_per_share_12m is None and market.price is not None:
            base = _missing("dividend_yield", "no dividend history is stored for this instrument", base.formula)
        self.metrics["dividend_yield"] = _from(
            "dividend_yield", base, basis="12 months", as_of=market.price_date.isoformat() if market.price_date else None, source="price file dividends"
        )

    def fcf_conversion(self) -> None:
        window = self.window("cfo", "capex", "net_income_parent")
        formula = "free cash flow / net income to parent"
        if window is None:
            self.metrics["fcf_conversion"] = _missing("fcf_conversion", self._no_window("cash flow and net income", ("cfo", "capex", "net_income_parent")), formula)
            return
        net_income = sm.window_sum(window, "net_income_parent")
        fcf = sm.free_cash_flow(sm.window_sum(window, "cfo"), sm.window_sum(window, "capex"))
        if net_income is None or fcf is None:
            self.metrics["fcf_conversion"] = _missing("fcf_conversion", "needs free cash flow and net income", formula)
        elif net_income <= 0:
            self.metrics["fcf_conversion"] = _metric("fcf_conversion", value=None, status=sm.NOT_MEANINGFUL, reason="not meaningful (loss): net income is zero or negative", formula=formula, **self._ctx(window))
        else:
            self.metrics["fcf_conversion"] = _metric("fcf_conversion", value=fcf / net_income, status=sm.OK, formula=formula, **self._ctx(window))

    # ----- history / peers / reverse valuation -------------------------------------------

    def history(self, mcap: float) -> None:
        pe = self.metrics["pe"]
        min_points = int(self.valuation.get("history_min_points", 12))
        years = int(self.valuation.get("history_years", 5))
        key = "pe_percentile"
        if not pe.available:
            self.metrics[key] = _missing(key, f"needs a meaningful P/E: {pe.reason}")
            return
        series = self.market.price_series
        if not series:
            self.metrics[key] = _missing(key, "no stored price history to rebuild past P/E readings")
            return
        quote_major, _ = sm.minor_unit(self.market.price_currency or "", self.minor)
        reporting_major, _ = sm.minor_unit(self.reporting_currency or "", self.minor)
        if quote_major != reporting_major:
            self.metrics[key] = _missing(key, f"the price currency ({quote_major}) differs from the reporting currency ({reporting_major}); rebuilding past P/E needs a daily FX series, which is not loaded")
            return
        values: list[float] = []
        start = self.decision_time.date() - timedelta(days=int(365.25 * years))
        for sample_date, close in series:
            if sample_date < start or sample_date > self.decision_time.date():
                continue
            value = self._pe_at(sample_date, close)
            if value is not None:
                values.append(value)
        self.history_points = len(values)
        if len(values) < min_points:
            self.metrics[key] = _missing(
                key,
                f"needs {min_points} month-end P/E readings in {years} years; only {len(values)} can be rebuilt "
                "from filings known at each date",
                "share of past month-end P/E readings at or below the current P/E",
            )
            return
        rank = sm.percentile_rank(values, pe.value)
        self.metrics[key] = _metric(
            key,
            value=rank,
            status=sm.OK,
            basis=f"{years}y point-in-time",
            as_of=series[-1][0].isoformat(),
            source=f"{len(values)} month-end readings",
            formula="share of the instrument's own past month-end P/E readings (each from filings known then) at or below today's P/E",
        )

    def _pe_at(self, when: date, close: float) -> float | None:
        moment = sm.as_utc(when)
        if moment is None:
            return None
        known = sm.known_periods(self.all_periods, moment)
        window = sm.flow_window(known, ["net_income_parent"], span_days=self.span)  # type: ignore[arg-type]
        balance = sm.latest_balance(known, ["shares_outstanding"])
        if window is None or balance is None:
            return None
        income = sm.window_sum(window, "net_income_parent")
        price, _ = sm.to_currency(close, self.market.price_currency or "", window.currency, fx_rate=None, minor_units=self.minor)
        mcap = sm.market_cap(price, balance.values["shares_outstanding"])
        if mcap is None or income is None or income <= 0:
            return None
        return mcap / income

    def peer_context(self) -> None:
        peers_cfg = self.config.get("peers", {}) if isinstance(self.config.get("peers"), Mapping) else {}
        for key in ("pe", "ev_ebit", "ev_sales", "pb", "roe", "ebit_margin", "fcf_yield", "dividend_yield", "revenue_cagr"):
            others = {pid: v for pid, v in (self.peer_values.get(key) or {}).items() if pid != self.id and v is not None}
            own = self.metrics.get(key)
            own_value = own.value if own is not None and own.available else None
            median = sm.median(others.values())
            premium = None
            if own_value is not None and median not in (None, 0.0) and key in {"pe", "ev_ebit", "ev_sales", "pb"}:
                premium = own_value / median - 1.0  # type: ignore[operator]
            self.peer_stats[key] = PeerStat(key, own_value, median, len(others), premium)
        stat = self.peer_stats["pe"]
        minimum = int(peers_cfg.get("min_for_score", 3))
        if stat.premium is None:
            reason = "no meaningful own P/E" if stat.own is None else f"needs {minimum} peers with a meaningful P/E; have {stat.count}"
            self.metrics["pe_vs_peers"] = _missing("pe_vs_peers", reason, "own P/E / median peer P/E - 1")
        elif stat.count < minimum:
            self.metrics["pe_vs_peers"] = _metric("pe_vs_peers", value=stat.premium, status=sm.UNAVAILABLE, reason=f"only {stat.count} peer{'' if stat.count == 1 else 's'} with a meaningful P/E; {minimum} needed", formula="own P/E / median peer P/E - 1")
        else:
            self.metrics["pe_vs_peers"] = _metric("pe_vs_peers", value=stat.premium, status=sm.OK, basis="spot", source=f"median of {stat.count} peers (instrument excluded)", formula="own P/E / median peer P/E - 1")

    def reverse_valuation(self, mcap: float) -> None:
        r = sm._finite(self.valuation.get("cost_of_equity"))
        terminal = sm._finite(self.valuation.get("terminal_growth"))
        years = int(self.valuation.get("stage1_years", 5))
        pe = self.metrics["pe"]
        window = self.window("dividends_paid", "net_income_parent")
        payout = None
        if window is not None:
            income = sm.window_sum(window, "net_income_parent")
            dividends = sm.window_sum(window, "dividends_paid")
            if income and income > 0 and dividends is not None:
                payout = abs(dividends) / income
        base = sm.implied_growth_from_pe(pe.value if pe.available else None, payout, r)
        if not pe.available and r is not None:
            base = _missing("implied_growth_pe", f"needs a meaningful P/E: {pe.reason}", base.formula)
        self.metrics["implied_growth_pe"] = _from("implied_growth_pe", base, basis="spot", source="P/E, payout, configured cost of equity" if base.available else None)
        fcf = self.metrics["fcf"]
        dcf = sm.implied_growth_from_dcf(mcap, fcf.value if fcf.available else None, r, terminal, years)
        self.metrics["implied_growth_dcf"] = _from("implied_growth_dcf", dcf, basis="spot", source="FCF, market cap, configured cost of equity" if dcf.available else None)

    # ----- components ----------------------------------------------------------------

    def _sub(self, group: str, key: str, label: str, value: float | None, display: str, *, reason: str | None = None, forced: float | None = None) -> SubScore:
        cfg = (self.scoring.get(group, {}) or {}).get(key, {})  # type: ignore[union-attr]
        if forced is not None:
            return SubScore(key, label, value, display, forced, reason)
        if value is None:
            return SubScore(key, label, None, "—", None, reason or "unavailable")
        score = linear_score(value, float(cfg.get("low", 0.0)), float(cfg.get("high", 1.0)))
        return SubScore(key, label, value, display, score, reason)

    def _metric_sub(self, group: str, key: str, metric_key: str, label: str, fmt) -> SubScore:  # noqa: ANN001
        metric = self.metrics.get(metric_key)
        loss = float(self.scoring.get("loss_subscore", 0.0))
        if metric is None:
            return SubScore(key, label, None, "—", None, "not calculated")
        if metric.available:
            return self._sub(group, key, label, metric.value, fmt(metric.value))
        if metric.status == sm.NOT_MEANINGFUL and "loss" in str(metric.reason):
            return SubScore(key, label, None, "loss", loss, f"{metric.reason}; scored {loss:g} (a known loss, not missing data)")
        return SubScore(key, label, None, "—", None, metric.reason or "unavailable")

    def components(self) -> dict[str, Component]:
        return {
            "stock_value": self.value_component(),
            "stock_quality": self.quality_component(),
            "analyst_revision": self.analyst_component(),
        }

    def _assemble(self, key: str, label: str, subs: list[SubScore], group: str, source_id: str, as_of: str | None, freshness: str) -> Component:
        cfg = self.scoring.get(group, {}) or {}
        min_inputs = int(cfg.get("min_inputs", 2)) if isinstance(cfg, Mapping) else 2
        used = [s for s in subs if s.score is not None]
        weights = {s.key: float((cfg.get(s.key, {}) or {}).get("weight", 1.0)) for s in subs} if isinstance(cfg, Mapping) else {}
        total_weight = sum(weights.get(s.key, 1.0) for s in used)
        score = None
        if len(used) >= min_inputs and total_weight > 0:
            score = round(sum(float(s.score) * weights.get(s.key, 1.0) for s in used) / total_weight, 2)  # type: ignore[arg-type]
        why = self._why(label, score, subs, min_inputs)
        if freshness == "stale" and score is not None:
            why = f"Stale: the newest reporting period ends more than {self.stale_days} days before the decision, so this is shown but not scored. {why}"
        return Component(key, label, score, tuple(subs), source_id, as_of, freshness if score is not None else "unavailable", why)

    def _why(self, label: str, score: float | None, subs: list[SubScore], min_inputs: int) -> str:
        used = [s for s in subs if s.score is not None]
        parts = [f"{s.label} {s.display} ({tx.score(s.score)}/10)" for s in used]
        missing = [f"{s.label} ({s.reason})" for s in subs if s.score is None]
        if score is None:
            lead = f"{label} has {len(used)} of {len(subs)} inputs; at least {min_inputs} are needed, so it is not scored."
        else:
            lead = f"{label} {score:.1f}/10 from {len(used)} of {len(subs)} inputs: " + "; ".join(parts) + "."
        if missing and score is not None:
            lead += " Not used: " + "; ".join(missing) + "."
        elif missing:
            lead += " Missing: " + "; ".join(missing) + "."
        return lead

    def _freshness(self) -> tuple[str | None, str]:
        if not self.known:
            return None, "unavailable"
        newest = max(self.known, key=lambda p: p.known_at)
        as_of = newest.known_at.date().isoformat()
        latest_end = max(p.period_end for p in self.known)
        age = (self.decision_time.date() - latest_end).days
        return as_of, "ok" if age <= self.stale_days else "stale"

    def _dataset(self) -> str:
        sources = sorted({p.source for p in self.known})
        return sources[0] if len(sources) == 1 else "sec_edgar" if "sec_edgar" in sources else (sources[0] if sources else "yfinance")

    def value_component(self) -> Component:
        group = "value"
        subs = [
            self._metric_sub(group, "earnings_yield", "earnings_yield", "Earnings yield", tx.pct),
            self._metric_sub(group, "fcf_yield", "fcf_yield", "FCF yield", tx.pct),
            self._metric_sub(group, "ebit_ev_yield", "ebit_ev_yield", "EBIT/EV", tx.pct),
        ]
        pct = self.metrics.get("pe_percentile")
        if pct is not None and pct.available:
            subs.append(self._sub(group, "pe_history_percentile", "P/E vs own history", pct.value, f"{pct.value * 100:.0f}th pct"))
        else:
            subs.append(SubScore("pe_history_percentile", "P/E vs own history", None, "—", None, getattr(pct, "reason", None) or "not calculated"))
        rel = self.metrics.get("pe_vs_peers")
        if rel is not None and rel.available:
            subs.append(self._sub(group, "pe_vs_peers_discount", "P/E vs peers", -rel.value, f"{-rel.value * 100:+.0f}% discount"))
        else:
            subs.append(SubScore("pe_vs_peers_discount", "P/E vs peers", None, "—", None, getattr(rel, "reason", None) or "not calculated"))
        as_of, freshness = self._freshness()
        return self._assemble("stock_value", "Stock value", subs, group, f"{self._dataset()}:fundamentals", as_of, freshness)

    def quality_component(self) -> Component:
        group = "quality"
        subs = [
            self._metric_sub(group, "roe", "roe", "ROE", tx.pct),
            self._metric_sub(group, "roic", "roic", "ROIC", tx.pct),
            self._metric_sub(group, "ebit_margin", "ebit_margin", "EBIT margin", tx.pct),
        ]
        leverage = self.metrics.get("net_debt_to_ebitda")
        net = self.metrics.get("net_debt")
        if leverage is not None and leverage.available:
            subs.append(self._sub(group, "net_debt_to_ebitda", "Net debt/EBITDA", leverage.value, tx.times(leverage.value)))
        elif leverage is not None and leverage.status == sm.NOT_MEANINGFUL and net is not None and net.available:
            if net.value <= 0:
                subs.append(SubScore("net_debt_to_ebitda", "Net debt/EBITDA", None, "net cash", 10.0, "EBITDA is not positive but the company holds net cash"))
            else:
                subs.append(SubScore("net_debt_to_ebitda", "Net debt/EBITDA", None, "n/m", 0.0, "EBITDA is not positive while net debt is positive"))
        else:
            subs.append(SubScore("net_debt_to_ebitda", "Net debt/EBITDA", None, "—", None, getattr(leverage, "reason", None) or "not calculated"))
        subs.append(self._metric_sub(group, "fcf_conversion", "fcf_conversion", "FCF/net income", tx.pct))
        subs.append(self._metric_sub(group, "revenue_cagr", "revenue_cagr", "Revenue growth", tx.pct))
        as_of, freshness = self._freshness()
        return self._assemble("stock_quality", "Stock quality", subs, group, f"{self._dataset()}:fundamentals", as_of, freshness)

    def analyst_component(self) -> Component:
        group = "analyst_revision"
        a = self.analyst
        cfg = self.scoring.get(group, {}) or {}
        subs: list[SubScore] = []
        reason = (a.unavailable_reason if a is not None else None) or "no analyst estimate snapshot is stored for this instrument"
        known = a is not None and a.known_at is not None and a.known_at <= self.decision_time
        if a is not None and a.known_at is not None and not known:
            reason = "analyst snapshot is dated after the decision time"
        change = None
        if known and a.eps_current is not None and a.eps_90d_ago not in (None, 0.0):
            change = a.eps_current / a.eps_90d_ago - 1.0 if a.eps_90d_ago > 0 else None
        subs.append(
            self._sub(group, "eps_estimate_change_90d", "EPS estimate change (90d)", change, tx.pct(change), reason=None if change is not None else (reason if not known else "needs a positive EPS estimate 90 days ago"))
        )
        share = None
        min_analysts = float(cfg.get("min_analysts", 3)) if isinstance(cfg, Mapping) else 3.0
        if known and a.revisions_up_30d is not None and a.revisions_down_30d is not None:
            total = a.revisions_up_30d + a.revisions_down_30d
            share = a.revisions_up_30d / total if total >= min_analysts else None
        subs.append(
            self._sub(group, "up_share_30d", "Upward share of revisions (30d)", share, tx.pct(share), reason=None if share is not None else (reason if not known else f"fewer than {min_analysts:g} revisions in 30 days"))
        )
        as_of = a.known_at.date().isoformat() if known and a.known_at else None
        component = self._assemble("analyst_revision", "Analyst revision", subs, group, f"{(a.source if a else 'yfinance')}:analyst_estimates", as_of, "ok" if known else "unavailable")
        return component


def build_stock_evidence(
    instrument_id: str,
    periods: Sequence[Period],
    decision_time: datetime,
    market: MarketInputs,
    analyst: AnalystInputs | None,
    config: Mapping[str, object],
    *,
    peer_values: Mapping[str, Mapping[str, float]] | None = None,
    no_data_reason: str | None = None,
) -> StockEvidence:
    """Metrics, peer context and the three score components for one stock at ``decision_time``."""

    return _Builder(instrument_id, periods, decision_time, market, analyst, config, peer_values, no_data_reason).build()
