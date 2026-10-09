"""Read-only view model of the normal-stock page (score first, numbers, valuation, peers, notes).

Everything shown comes from the canonical score row and the shared stock evidence; each unavailable
value keeps the reason from the calculation that produced it. Nothing here changes a score or a gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis import stock_text as tx
from etf_cockpit.analysis.stock_evidence import METRIC_LABELS, StockEvidence
from etf_cockpit.analysis.stock_metrics import Metric
from etf_cockpit.application.score_views import score_coverage
from etf_cockpit.application.stock_service import snapshot_stock_evidence
from etf_cockpit.data import stock_notes
from etf_cockpit.signals.simple_scores import STOCK_EVIDENCE_WEIGHTS

NUMBER_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Earnings and returns", ("revenue", "ebit", "net_income", "gross_margin", "ebit_margin", "net_margin", "roe", "roic", "revenue_cagr", "net_income_cagr")),
    ("Cash and balance sheet", ("fcf", "fcf_conversion", "net_debt", "net_debt_to_ebitda", "debt_to_equity")),
    ("Valuation", ("market_cap", "ev", "pe", "ev_ebit", "ev_sales", "pb", "fcf_yield", "dividend_yield", "pe_percentile", "pe_vs_peers")),
    ("Reverse valuation", ("implied_growth_pe", "implied_growth_dcf")),
)
PEER_COLUMNS = (("pe", "P/E"), ("ev_ebit", "EV/EBIT"), ("roe", "ROE"), ("ebit_margin", "EBIT margin"), ("fcf_yield", "FCF yield"), ("dividend_yield", "Div. yield"), ("revenue_cagr", "Rev. CAGR"))
_SHORT = 100


@dataclass(frozen=True)
class NumberRow:
    key: str
    label: str
    display: str
    detail: str  # basis, as-of and source
    reason: str | None  # why the value is unavailable
    formula: str = ""
    available: bool = False


@dataclass(frozen=True)
class ComponentRow:
    key: str
    label: str
    score: float | None
    weight_share: float
    eligible: bool
    why: str


@dataclass(frozen=True)
class PeerRow:
    instrument_id: str
    name: str
    origin: str  # self | user | auto | median
    reasons: str
    cells: dict[str, tuple[str, str | None]]  # column -> (display, reason)


@dataclass
class StockPageModel:
    instrument_id: str
    name: str
    symbol: str
    available: bool
    unavailable_reason: str | None = None
    score: float | None = None
    coverage: float | None = None
    used: int = 0
    total: int = 0
    label: str = ""
    one_line: str = ""
    headline: str = ""
    sentences: list[str] = field(default_factory=list)
    components: list[ComponentRow] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    numbers: list[tuple[str, list[NumberRow]]] = field(default_factory=list)
    fiscal_rows: list[dict[str, str]] = field(default_factory=list)
    peers: list[PeerRow] = field(default_factory=list)
    peer_summary: str = ""
    user_peers: list[str] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    identity: list[tuple[str, str, str | None]] = field(default_factory=list)  # label, value, reason
    sources: tuple[str, ...] = ()


def short_reason(text: object, limit: int = _SHORT) -> str:
    clean = " ".join(str(text or "").split())
    for stop in (". ", "; "):
        if stop in clean:
            clean = clean.split(stop, 1)[0]
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def format_metric(metric: Metric, currency: str | None = None) -> str:
    if metric.value is None:
        return "—"
    if metric.key == "pe_vs_peers":
        return f"{metric.value * 100:+.0f}% vs peers"
    if metric.key == "pe_percentile":
        return f"{metric.value * 100:.0f}th percentile"
    if metric.unit == "ratio":
        return tx.pct(metric.value)
    if metric.unit == "multiple":
        return tx.times(metric.value)
    return tx.money(metric.value, metric.currency or currency)


def number_row(metric: Metric, currency: str | None = None) -> NumberRow:
    detail = " · ".join(part for part in (metric.basis, metric.as_of, metric.source) if part) or "—"
    available = metric.value is not None and metric.status == "ok"
    reason = None if available else (metric.reason or metric.status)
    display = format_metric(metric, currency)
    return NumberRow(metric.key, metric.label, display, detail, reason, metric.formula, available)


def _reason_for(component: Any) -> str:
    """Why a component does not enter the score (its own text when it was never calculated)."""

    if component.score_eligible:
        return component.why
    if component.score_10 is not None:
        if str(component.source_id or "").startswith("model:"):
            return "model forecasts are low-authority confirmation and are not part of the evidence score"
        if str(component.freshness_status or "") in {"stale", "unavailable"}:
            return f"its data is {component.freshness_status}; it is shown but not scored"
        return "not score-eligible (source, freshness or conflict check failed)"
    return component.why


def _component_rows(score_row: Any) -> list[ComponentRow]:
    total = sum(STOCK_EVIDENCE_WEIGHTS.values()) or 1.0
    by_key = {c.key: c for c in getattr(score_row, "components", ())}
    rows = []
    for key, weight in STOCK_EVIDENCE_WEIGHTS.items():
        component = by_key.get(key)
        if component is None:
            rows.append(ComponentRow(key, key.replace("_", " ").title(), None, weight / total, False, "this component was not built for the instrument"))
            continue
        rows.append(ComponentRow(key, component.label, component.score_10 if component.score_eligible else None, weight / total, bool(component.score_eligible), _reason_for(component)))
    return rows


def _peer_rows(evidence_map: Any, instrument_id: str) -> tuple[list[PeerRow], str]:
    own = evidence_map.evidence.get(instrument_id)
    picks = evidence_map.peers.get(instrument_id, [])

    def cells_of(ev: StockEvidence | None) -> dict[str, tuple[str, str | None]]:
        out: dict[str, tuple[str, str | None]] = {}
        for key, _label in PEER_COLUMNS:
            if ev is None:
                out[key] = ("—", "no evidence was built for this peer")
                continue
            metric = ev.metrics[key]
            out[key] = (format_metric(metric), None if metric.value is not None else short_reason(metric.reason))
        return out

    rows = [PeerRow(instrument_id, evidence_map.names.get(instrument_id, instrument_id), "self", "this stock", cells_of(own))]
    for pick in picks:
        ev = evidence_map.evidence.get(pick.instrument_id)
        shown = pick.instrument_id.removeprefix("peer:")
        rows.append(PeerRow(shown, pick.name, pick.origin, ", ".join(pick.reasons), cells_of(ev)))
    medians: dict[str, tuple[str, str | None]] = {}
    for key, _label in PEER_COLUMNS:
        stat = own.peer_stats.get(key) if own is not None else None
        if stat is None or stat.median is None:
            medians[key] = ("—", "no peer has a meaningful value")
        else:
            probe = Metric(key, key, stat.median, METRIC_LABELS[key][1], "ok")
            medians[key] = (f"{format_metric(probe)} (n={stat.count})", None)
    rows.append(PeerRow("", "Peer median (this stock excluded)", "median", "", medians))
    summary = (
        f"{len(picks)} peers: " + ", ".join(f"{p.name} ({p.origin})" for p in picks[:8]) + "."
        if picks
        else "No peers: no other stock shares the sector, industry or region needed (min. similarity in configs/stock_fundamentals_v1.yaml); pick peers yourself."
    )
    return rows, summary


def _fiscal_rows(periods: list[Any], currency: str | None) -> list[dict[str, str]]:
    rows = []
    for period in sorted((p for p in periods if p.period_type == "FY"), key=lambda p: p.period_end, reverse=True)[:6]:
        values = period.values
        cfo, capex = values.get("cfo"), values.get("capex")
        fcf = sm.free_cash_flow(cfo, capex)

        def cell(name: str, value: object) -> str:
            shown = tx.money(value, None)
            return shown if value is not None else f"{shown} · {name} is not reported in this fiscal year"

        missing_fcf = [name for name, value in (("cash from operations", cfo), ("capital expenditure", capex)) if value is None]
        fcf_cell = tx.money(fcf, None) if fcf is not None else f"— · needs {' and '.join(missing_fcf)}"
        row_currency = period.currency or (currency or "")
        rows.append(
            {
                "period": f"FY {period.period_end.isoformat()}",
                "revenue": cell("revenue", values.get("revenue")),
                "ebit": cell("EBIT", values.get("ebit")),
                "net_income": cell("net income", values.get("net_income_parent")),
                "fcf": fcf_cell,
                "equity": cell("parent equity", values.get("equity_parent")),
                "source": period.source,
                "currency": row_currency or "— · reporting currency is not available",
            }
        )
    return rows


def build_stock_page_model(snapshot: Any, instrument_id: str, score_row: Any | None = None) -> StockPageModel:
    """Everything the stock page shows, from the shared evidence; unavailable parts carry their reason."""

    universe = snapshot_stock_evidence(snapshot)
    evidence = universe.evidence.get(instrument_id)
    record_name = universe.names.get(instrument_id, instrument_id)
    profile = universe.profiles.get(instrument_id)
    symbol = str(getattr(score_row, "yahoo_symbol", "") or "")
    if evidence is None:
        return StockPageModel(instrument_id, record_name, symbol, False, "this instrument is not a normal stock in the universe (bank, certificate, ETF or disabled)")
    model = StockPageModel(instrument_id, record_name, symbol, True)
    cfg = universe.config
    cfg_text = cfg.get("text", {}) if isinstance(cfg.get("text"), dict) else {}
    model.components = _component_rows(score_row) if score_row is not None else []
    if score_row is not None:
        score = getattr(score_row, "final_score_10", None)
        model.score = None if score is None else float(score)
        model.coverage = score_coverage(score_row)
        model.used = sum(1 for c in model.components if c.eligible)
        model.total = len(model.components)
        model.label = str(getattr(score_row, "final_label", "") or "")
        model.one_line = str(getattr(score_row, "one_line_reason", "") or "")
        model.missing = [(c.label, short_reason(c.why, 90)) for c in model.components if not c.eligible]
        step = "pick a score row for this instrument: it has no configured score row" if model.score is None and not model.components else ""
        model.headline = tx.score_headline(model.score, model.coverage, model.used, model.total, dict(model.missing), float(cfg_text.get("strong_score", 7.0)), float(cfg_text.get("weak_score", 4.0)))
        if model.score is None and step:
            model.unavailable_reason = step
    else:
        model.headline = "No score: the score list has no row for this instrument (add it to the universe and run the algorithms)."
    model.sentences = tx.describe_stock(evidence, cfg_text, int(cfg.get("valuation", {}).get("history_years", 5)))
    for title, keys in NUMBER_GROUPS:
        model.numbers.append((title, [number_row(evidence.metrics[k], evidence.reporting_currency) for k in keys]))
    market = universe.prices.get(instrument_id)
    price_line: list[NumberRow] = []
    if market is not None:
        if market.price is not None:
            price_line.append(NumberRow("price", "Last price", f"{market.price:,.2f} {market.price_currency or ''}".strip(), f"{market.price_date} · price file", None, available=True))
        else:
            price_line.append(NumberRow("price", "Last price", "—", "—", market.unavailable_reason or "no decision-time price"))
    model.numbers.insert(0, ("Market", price_line))
    model.fiscal_rows = _fiscal_rows(universe.periods.get(instrument_id, []), evidence.reporting_currency)
    model.peers, model.peer_summary = _peer_rows(universe, instrument_id)
    model.user_peers = list(universe.user_peers.get(instrument_id, []))
    model.notes = stock_notes.list_notes(instrument_id)
    snap = universe.snapshots.get(instrument_id, {})
    model.identity = [
        ("Company", str(snap.get("long_name") or record_name), None if snap.get("long_name") else "the provider returned no company name"),
        ("Sector / industry", " / ".join(p for p in (str(snap.get("sector") or ""), str(snap.get("industry") or "")) if p) or "—", None if snap.get("sector") else "no provider classification; the universe sector is used for peers"),
        ("Country", str(snap.get("country") or "—"), None if snap.get("country") else "not returned by the provider"),
        ("Reporting currency", evidence.reporting_currency or "—", None if evidence.reporting_currency else (evidence.unavailable_reason or "no statements")),
        ("Fundamentals sources", ", ".join(evidence.sources) or "—", None if evidence.sources else (evidence.unavailable_reason or "none loaded")),
    ]
    model.sources = evidence.sources
    if profile is not None and profile.market_cap_eur_bn is not None:
        model.identity.append(("Size", f"EUR {profile.market_cap_eur_bn:,.1f}bn market cap", None))
    return model


def stock_notes_for(instrument_id: str) -> list[dict[str, Any]]:
    """The instrument's active dated notes, newest first (one canonical reader for the page)."""

    return stock_notes.list_notes(instrument_id)
