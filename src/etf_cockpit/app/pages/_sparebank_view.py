"""Sparebank EC workspace for the instrument page (SB2).

Presentation only: every number comes from the facade's ``sparebank_workspace`` (scorecard, claim, valuation,
dividends, history, peers, Pillar 3 queue); this module formats and lays it out. Missing values are shown with the
reason the analysis recorded, never as a bare dash.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import math

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    KpiTile,
    Note,
    ScoreBar,
    TableColumn,
    Tag,
    field_input_style,
)
from etf_cockpit.application.sparebank_evidence import review_pillar3_figure
from etf_cockpit.application.sparebank_peers import set_picked_peers

# Plain-language copy for the scorecard's gate codes (the codes themselves come from the analysis).
GATE_TEXT = {
    "OWNER_CLAIM_UNRESOLVED": "The EC owner claim is not fully resolved (a pool, count or result is missing), so per-certificate figures are partial.",
    "PIT_CHECK_UNVERIFIED": "A point-in-time check could not be verified for some evidence.",
    "MINIMUM_COMPOSITE_COVERAGE_NOT_MET": "Too little of the scorecard has evidence, so no composite score is shown.",
    "DAYS_TO_TRADE_ABOVE_LIMIT": "A reference position would take longer to trade than the limit, which caps the score.",
}
_UNIT_SUFFIX = {"percent": " %", "percentage_points": " pp", "basis_points": " bps", "days": " days", "nok": " NOK", "nok_per_day": " NOK/day", "ratio": "x"}
_UNIT_DECIMALS = {"percent": 1, "percentage_points": 1, "basis_points": 0, "days": 2, "nok": 0, "nok_per_day": 0, "ratio": 2, "score_input": 1}


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def format_value(value: object, unit: str | None) -> str | None:
    number = _number(value)
    if number is None:
        return None
    decimals = _UNIT_DECIMALS.get(str(unit), 2)
    signed = "+" if unit == "percentage_points" and number > 0 else ""
    return f"{signed}{number:,.{decimals}f}{_UNIT_SUFFIX.get(str(unit), '')}"


def _percent(value: object, decimals: int = 1) -> str | None:
    number = _number(value)
    return None if number is None else f"{number * 100:.{decimals}f} %"


def _text(text: str, *, size: float = 12.5, color: str = theme.INK2, bold: bool = False) -> ft.Text:
    return ft.Text(text, size=size, color=color, selectable=True, weight=ft.FontWeight.W_600 if bold else ft.FontWeight.W_400)


def _tiles(items: Sequence[ft.Control]) -> ft.Control:
    return ft.Row(list(items), spacing=10, run_spacing=10, wrap=True)


def _unavailable(title: str, reason: object) -> ft.Control:
    return EmptyState(title, str(reason or "No evidence is recorded for this section."))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _summary(workspace: Mapping[str, object]) -> ft.Control:
    scorecard = _mapping(workspace.get("scorecard"))
    underwriting = _mapping(workspace.get("underwriting_horizon"))
    claim = _mapping(workspace.get("ownership_passport"))
    composite = _number(scorecard.get("composite_10"))
    coverage = _number(scorecard.get("composite_coverage"))
    gates = [str(item) for item in _sequence(scorecard.get("gate_reasons"))]
    share = _number(claim.get("reconstructed_eierbrok"))
    if share is None:
        share = _number(claim.get("reported_eierbrok"))
    tiles = [
        KpiTile(
            "Composite score",
            None if composite is None else f"{composite:.1f}",
            "of 10" if composite is not None else "Not computed: see the gate reasons below",
            tone=None if composite is None else "pos" if composite >= 6 else "attention" if composite >= 5 else "neg",
        ),
        KpiTile("Evidence coverage", _percent(coverage, 0), "share of scored inputs with evidence" if coverage is not None else "No scored input has evidence"),
        KpiTile("EC share of owner capital", _percent(share, 1), "ownership fraction (eierbrok), reconstructed from the pools" if share is not None else "Pools incomplete: the fraction cannot be reconstructed"),
    ]
    status = str(underwriting.get("status") or "UNAVAILABLE")
    lines: list[ft.Control] = [
        _tiles(tiles),
        ft.Row(
            [
                _text(f"Underwriting horizon — {underwriting.get('horizon', 'multi-year owner economics')}", bold=True, color=theme.INK),
                Tag(status.replace("_", " ").lower(), "ok" if status.casefold() == "rated" else "warn" if status.casefold() == "partial" else "mute", dense=True),
            ],
            spacing=8,
            wrap=True,
        ),
    ]
    if gates:
        lines.append(_text("Gate reasons", bold=True, color=theme.INK))
        lines.extend(_text(f"{code}: {GATE_TEXT.get(code, code.replace('_', ' ').capitalize())}") for code in gates)
    else:
        lines.append(Note("No gate is active: nothing caps or withholds the composite."))
    missing = [str(item).replace("_", " ") for item in _sequence(scorecard.get("missing_axes"))]
    if missing:
        lines.append(Note("Axes without evidence: " + ", ".join(missing) + ". Each axis below states why."))
    return ft.Column(lines, spacing=8)


# ---------------------------------------------------------------------------
# Axes and inputs
# ---------------------------------------------------------------------------


def _input_rows(inputs: Sequence[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in inputs:
        entry = _mapping(item)
        value = _number(entry.get("value"))
        rating = _number(entry.get("rating_10"))
        scored = entry.get("scored") is not False
        shown = format_value(value, str(entry.get("unit") or ""))
        if value is None:
            basis = _text(str(entry.get("reason") or entry.get("missing_reason") or "No evidence recorded."), size=12)
            role = Tag("missing" if scored else "missing · not scored", "warn" if scored else "mute", dense=True)
        elif not scored:
            basis = _text("Shown for context; it does not enter the score (" + str(entry.get("book") or "see the scorecard notes") + ").", size=12)
            role = Tag("shown only", "mute", dense=True)
        else:
            basis = _text(str(entry.get("book") or ""), size=12)
            role = Tag("scored", "ok", dense=True)
        calculation_id = str(entry.get("calculation_id") or "")
        source = entry.get("source_locator") or entry.get("source_url") or entry.get("document_title")
        citation = str(source) if source else "Source unavailable"
        rows.append(
            {
                "input": (str(entry.get("label") or entry.get("id")), f"{calculation_id} · {citation}".strip(" ·")),
                "value": shown,
                "rating": ScoreBar(rating) if rating is not None else _text("not rated", size=12),
                "role": role,
                "basis": basis,
            }
        )
    return rows


def _axes(workspace: Mapping[str, object]) -> ft.Control:
    scorecard = _mapping(workspace.get("scorecard"))
    axes = _mapping(scorecard.get("axes"))
    if not axes:
        return _unavailable("No axes", "The scorecard produced no axis results.")
    summary_rows: list[dict[str, object]] = []
    details: list[ft.Control] = []
    for axis_id, raw in axes.items():
        axis = _mapping(raw)
        label = str(axis.get("label") or axis_id)
        rating = _number(axis.get("rating_10"))
        coverage = _number(axis.get("coverage"))
        inputs = _sequence(axis.get("inputs"))
        scored = [item for item in inputs if _mapping(item).get("scored") is not False]
        rated = [item for item in scored if _number(_mapping(item).get("rating_10")) is not None]
        status = str(axis.get("status") or "UNAVAILABLE")
        weight = _number(axis.get("weight"))
        summary_rows.append(
            {
                "axis": (label, str(axis.get("group") or "")),
                "rating": ScoreBar(rating) if rating is not None else _text("no rating", size=12),
                "coverage": _percent(coverage, 0) if coverage is not None else None,
                "inputs": f"{len(rated)}/{len(scored)} scored inputs",
                "status": Tag(status.replace("_", " ").lower(), "ok" if status.casefold() == "rated" else "warn" if status.casefold() == "partial" else "mute", dense=True),
            }
        )
        reason_lines: list[ft.Control] = []
        if axis.get("explain"):
            reason_lines.append(Note(str(axis.get("explain"))))
        if rating is None and not rated:
            missing = [str(_mapping(item).get("label") or _mapping(item).get("id")) for item in scored]
            reason_lines.append(Note("No rating: " + (", ".join(missing) if missing else "this axis has no scored input") + " lack evidence (reasons below)." if scored else "No rating: this axis currently has no scored input; it is shown for context only."))
        if weight is not None and weight == 0:
            reason_lines.append(Note("Weight 0 in this scorecard version: shown for context, it does not move the composite."))
        details.append(
            ft.ExpansionTile(
                title=ft.Text(f"{label} · {'no rating' if rating is None else f'{rating:.1f}'}", size=13.5),
                subtitle=ft.Text(f"{len(rated)}/{len(scored)} scored inputs rated · coverage {_percent(coverage, 0) or 'none'}", size=12),
                controls=[
                    ft.Column(
                        [
                            *reason_lines,
                            DataTable(
                                [
                                    TableColumn("input", "Input", flex=3, sortable=False),
                                    TableColumn("value", "Value", flex=2, numeric=True, sortable=False),
                                    TableColumn("rating", "Rating", flex=2, sortable=False),
                                    TableColumn("role", "Role", flex=2, sortable=False),
                                    TableColumn("basis", "Book basis or reason", flex=6, sortable=False),
                                ],
                                _input_rows(inputs),
                                row_height=60,
                                max_visible_rows=8,
                                empty_title="No inputs",
                                empty_reason="This axis has no inputs configured.",
                            ),
                        ],
                        spacing=8,
                    )
                ],
                expanded=False,
                key=f"instrument-detail.sparebank-axis.{axis_id}",
            )
        )
    return ft.Column(
        [
            DataTable(
                [
                    TableColumn("axis", "Axis", flex=4, sortable=False),
                    TableColumn("rating", "Rating", flex=3, sortable=False),
                    TableColumn("coverage", "Coverage", flex=1, numeric=True, sortable=False),
                    TableColumn("inputs", "Inputs", flex=2, sortable=False),
                    TableColumn("status", "Status", flex=2, sortable=False),
                ],
                summary_rows,
                row_height=48,
                max_visible_rows=14,
            ),
            *details,
        ],
        spacing=8,
    )


# ---------------------------------------------------------------------------
# Ownership, bank economics, valuation
# ---------------------------------------------------------------------------


def _money(value: object) -> str | None:
    number = _number(value)
    return None if number is None else f"{number / 1e6:,.0f} m NOK"


def _ownership(workspace: Mapping[str, object]) -> ft.Control:
    claim = _mapping(workspace.get("ownership_passport"))
    if not claim:
        return _unavailable("Ownership unavailable", "No EC claim evidence was recorded.")
    owner = _mapping(claim.get("owner_pools"))
    own = _mapping(claim.get("self_owned_pools"))
    rows = [{"pool": name.replace("_", " "), "holder": "EC holders", "amount": _money(value)} for name, value in owner.items()]
    rows += [{"pool": name.replace("_", " "), "holder": "Ownerless (the bank itself)", "amount": _money(value)} for name, value in own.items()]
    reported, rebuilt = _number(claim.get("reported_eierbrok")), _number(claim.get("reconstructed_eierbrok"))
    used_share = rebuilt if rebuilt is not None else reported
    status = str(claim.get("claim_status") or "unknown")
    body: list[ft.Control] = [
        _tiles(
            [
                KpiTile("Claim status", status.replace("_", " "), "pools and counts reconcile" if status == "resolved" else "see the unavailable fields below", tone="pos" if status == "resolved" else "attention"),
                KpiTile("EC ownership fraction", _percent(used_share, 2), "reconstructed: EC pools / (EC pools + ownerless pools)" if rebuilt is not None else "reported by the bank; a missing pool prevents reconstruction" if reported is not None else "Cannot be reconstructed: a pool is missing"),
                KpiTile("Reported by the bank", _percent(reported, 2), "as printed in the report" if reported is not None else "The bank does not print it in the structured filing"),
                KpiTile("Certificates", None if _number(claim.get("registered_ec_count")) is None else f"{_number(claim.get('registered_ec_count')) / 1e6:,.1f} m", "registered" if _number(claim.get("registered_ec_count")) is not None else "Count not tagged in the filing"),
            ]
        ),
        DataTable(
            [TableColumn("pool", "Equity pool", flex=3, sortable=False), TableColumn("holder", "Belongs to", flex=3, sortable=False), TableColumn("amount", "Amount", flex=2, numeric=True, sortable=False)],
            rows,
            row_height=40,
            empty_title="No pools",
            empty_reason="No equity pool was extracted from the filing.",
        ),
    ]
    unavailable = [str(item).replace("_", " ") for item in _sequence(claim.get("unavailable_fields"))]
    if unavailable:
        body.append(Note("Not available: " + ", ".join(unavailable) + "."))
    return GlassCard("Ownership passport — What this EC owns", note="owner pools vs ownerless pools (book ch. 2)", body=body, key="instrument-detail.sparebank-ownership")


def _bank_economics(workspace: Mapping[str, object]) -> ft.Control:
    economics = _mapping(workspace.get("bank_economics"))
    lending = _mapping(economics.get("lending"))
    normalised = _mapping(economics.get("normalised"))
    resilience = _mapping(economics.get("resilience"))
    reasons = _mapping(economics.get("reasons"))
    specs = (
        ("Net interest margin", lending.get("net_interest_margin"), "percent", "net_interest_margin", True),
        ("Risk-adjusted margin", lending.get("risk_adjusted_margin"), "percent", "risk_adjusted_margin_pct", True),
        ("Cost of risk", lending.get("cost_of_risk"), "percent", "cost_of_risk_bps", True),
        ("Loan growth", lending.get("loan_growth"), "percent", "loan_growth", True),
        ("Deposit growth", lending.get("deposit_growth"), "percent", "deposit_growth", True),
        ("Cost / average assets", lending.get("cost_to_average_assets"), "percent", "cost_to_assets_pct", True),
        ("Normalised ROE", normalised.get("normalised_roe"), "percent", "normalised_roe_minus_cost_of_equity_pp", True),
        ("CET1 headroom vs requirement", resilience.get("headroom_pp"), "percentage_points", "cet1_headroom_pp", False),
    )
    rows = []
    for label, value, unit, reason_key, is_ratio in specs:
        number = _number(value)
        shown = None
        if number is not None:
            shown = f"{number * 100:.2f} %" if is_ratio else format_value(number, unit)
        rows.append({"metric": label, "value": shown, "reason": _text("" if number is not None else str(reasons.get(reason_key) or "Not available in the evidence."), size=12)})
    adjustments = [item for item in _sequence(normalised.get("adjustments"))]
    body: list[ft.Control] = [
        DataTable(
            [TableColumn("metric", "Metric", flex=3, sortable=False), TableColumn("value", "Value", flex=2, numeric=True, sortable=False), TableColumn("reason", "If missing, why", flex=7, sortable=False)],
            rows,
            row_height=48,
            max_visible_rows=10,
        )
    ]
    for item in adjustments:
        entry = _mapping(item) if isinstance(item, Mapping) else {"label": getattr(item, "label", "adjustment"), "amount": getattr(item, "amount", None), "note": getattr(item, "note", "")}
        amount = _number(entry.get("amount"))
        if amount is not None:
            body.append(Note(f"Normalisation: {entry.get('label', 'adjustment')} {amount / 1e6:+,.1f} m NOK. {entry.get('note', '')}".strip()))
    if normalised.get("notes"):
        body.extend(Note(str(note)) for note in _sequence(normalised.get("notes")))
    return GlassCard("Bank economics", note="lending, normalised earnings and capital (book ch. 1, 3, 4)", body=body, key="instrument-detail.sparebank-economics")


def _valuation(workspace: Mapping[str, object]) -> ft.Control:
    valuation = _mapping(workspace.get("valuation_expectations"))
    standalone = _mapping(valuation.get("standalone"))
    central = _mapping(valuation.get("central_owner_value_per_ec"))
    reverse = _mapping(valuation.get("reverse"))
    price = _mapping(workspace.get("decision_price"))
    last = _number(price.get("price"))
    value_per_ec = _number(central.get("value_per_ec"))
    owner_pb, justified = _number(standalone.get("owner_pb")), _number(central.get("justified_pb"))
    body: list[ft.Control] = []
    tiles = [
        KpiTile("Price (decision)", None if last is None else f"{last:,.2f} NOK", str(price.get("date") or "") if last is not None else "No price at the decision time"),
        KpiTile("P/B vs justified P/B", None if owner_pb is None else f"{owner_pb:.2f}x", f"justified {justified:.2f}x" if justified is not None else str(central.get("reason_code") or "Justified P/B needs a sustainable ROE and a cost of equity")),
        KpiTile("Owner value per EC", None if value_per_ec is None else f"{value_per_ec:,.0f} NOK", "" if value_per_ec is None else (f"{(value_per_ec / last - 1) * 100:+.0f} % vs price" if last else "")),
        KpiTile("Residual income per EC", None if _number(central.get("residual_income_per_ec_next_year")) is None else f"{_number(central.get('residual_income_per_ec_next_year')):,.2f} NOK", "next year, (ROE - COE) x opening book"),
    ]
    body.append(_tiles(tiles))
    if central.get("equation"):
        body.append(Note(f"{central.get('equation')}. ROE {_percent(central.get('sustainable_roe')) or 'n/a'}, COE {_percent(central.get('cost_of_equity')) or 'n/a'}, g {_percent(central.get('growth')) or 'n/a'}. {central.get('assumption_source', '')}"))
    if reverse.get("status") == "resolved":
        body.append(_text("Reverse valuation (what the price implies)", bold=True, color=theme.INK))
        body.append(
            _tiles(
                [
                    KpiTile("Implied ROE", _percent(reverse.get("implied_r")), "at the cost of equity above"),
                    KpiTile("Implied cost of equity", _percent(reverse.get("implied_k")), "at the sustainable ROE above"),
                    KpiTile("Expectations gap", None if _number(reverse.get("expectations_gap")) is None else f"{_number(reverse.get('expectations_gap')) * 100:+.1f} pp", "analyst ROE minus price-implied ROE"),
                ]
            )
        )
        if reverse.get("wording"):
            body.append(Note(str(reverse.get("wording"))))
    else:
        body.append(Note("Reverse valuation unavailable: " + str(reverse.get("reason_code") or "it needs an owner P/B, a cost of equity and a growth rate") + "."))
    sources = _mapping(standalone.get("count_sources"))
    if sources:
        body.append(Note("Certificate counts used: book per EC on " + str(sources.get("book_count")) + "; earnings per EC on " + str(sources.get("earnings_count")) + "."))
    return GlassCard("Valuation and expectations", note="P/B is context; ROE vs cost of equity is the thesis (book eq. 5.22-5.34)", body=body, key="instrument-detail.sparebank-valuation")


# ---------------------------------------------------------------------------
# Dividends, history, peers
# ---------------------------------------------------------------------------


def _dividends(workspace: Mapping[str, object]) -> ft.Control:
    dividends = _mapping(workspace.get("dividends"))
    if dividends.get("status") != "available":
        return GlassCard("Dividends", note="EC cash distributions", body=[_unavailable("No dividend history", str(dividends.get("reason_code") or "Not available").replace("_", " ").capitalize() + ". The price source records no distribution events for this certificate.")], key="instrument-detail.sparebank-dividends")
    rows = [
        {"year": str(item.get("year")) + ("" if item.get("complete") else " (so far)"), "amount": f"{_number(item.get('amount')):,.2f} NOK", "events": str(item.get("count"))}
        for item in (_mapping(entry) for entry in _sequence(dividends.get("by_year")))
    ]
    body: list[ft.Control] = [
        _tiles(
            [
                KpiTile("Trailing 12-month yield", _percent(dividends.get("ttm_yield")), "cash distributions / decision price" if dividends.get("ttm_yield") is not None else "No distribution in the last 12 months"),
                KpiTile("Trailing 12-month cash", None if _number(dividends.get("ttm_amount")) is None else f"{_number(dividends.get('ttm_amount')):,.2f} NOK", "per certificate"),
                KpiTile("Last ex-date", str(dividends.get("last_ex_date") or "") or None, f"{dividends.get('years_with_dividend')} calendar years with a distribution"),
            ]
        ),
        DataTable(
            [TableColumn("year", "Year", sortable=False), TableColumn("amount", "Per certificate", numeric=True, sortable=False), TableColumn("events", "Payments", numeric=True, sortable=False)],
            list(reversed(rows)),
            row_height=36,
            max_visible_rows=8,
        ),
        Note("Source: " + str(dividends.get("source")) + ". Distributions to the ownerless capital (gifts, foundation) are not in this series."),
    ]
    return GlassCard("Dividends", note="EC cash distributions and yield (book 5.8)", body=body, key="instrument-detail.sparebank-dividends")


def _history(workspace: Mapping[str, object]) -> ft.Control:
    history = [_mapping(item) for item in _sequence(workspace.get("history"))]
    if not history:
        return GlassCard("Score history", note="per quarter", body=[_unavailable("No stored scores", "No native scorecard run is stored for this certificate yet. A refresh writes one row per run.")], key="instrument-detail.sparebank-history")
    rows = []
    for item in reversed(history):
        change = _number(item.get("change"))
        rows.append(
            {
                "quarter": str(item.get("quarter")),
                "run_started_at": str(item.get("run_started_at") or ""),
                "run_completed_at": str(item.get("run_completed_at") or item.get("run_timestamp") or ""),
                "composite": None if _number(item.get("composite")) is None else f"{_number(item.get('composite')):.1f}",
                "coverage": _percent(item.get("coverage"), 0),
                "trend": Tag("n/a (first or formula changed)" if change is None else f"{change:+.1f}", "mute" if change is None else "ok" if change > 0 else "warn" if change < 0 else "mute", dense=True),
                "formula": str(item.get("formula_version") or ""),
            }
        )
    chart = ck.line_chart(
        [str(item.get("quarter")) for item in history],
        [ck.Series("Composite", [_number(item.get("composite")) for item in history], color=theme.CYAN, glow=True, markers=7.0)],
        x_name="Reporting quarter",
        y_name="Composite (0-10)",
        y_min=0,
        y_max=10,
        height=220,
        insight=f"{len(history)} reporting quarter(s) with a stored score; run timestamps are shown separately.",
    )
    body = [
        chart,
        DataTable(
            [TableColumn("quarter", "Reporting quarter", sortable=False), TableColumn("run_started_at", "Run started", flex=2, sortable=False), TableColumn("run_completed_at", "Run completed", flex=2, sortable=False), TableColumn("composite", "Composite", numeric=True, sortable=False), TableColumn("coverage", "Coverage", numeric=True, sortable=False), TableColumn("trend", "Change", sortable=False), TableColumn("formula", "Formula", flex=2, sortable=False)],
            rows,
            row_height=40,
            max_visible_rows=8,
        ),
        Note("One row per reporting quarter (the latest run stored for that period). Run started and completed times remain separate. The change is shown only between rows of the same formula version."),
    ]
    return GlassCard("Score history", note="per quarter with trend", body=body, key="instrument-detail.sparebank-history")


def _peers(workspace: Mapping[str, object], root: object, page: object | None, instrument_id: str) -> ft.Control:
    peers = [_mapping(item) for item in _sequence(workspace.get("peers"))]
    rows = []
    for item in peers:
        rows.append(
            {
                "peer": (str(item.get("instrument_id")), str(item.get("name") or "")),
                "pick": Tag("picked", "ok", dense=True) if item.get("picked") else _text("auto", size=12),
                "composite": None if _number(item.get("composite")) is None else f"{_number(item.get('composite')):.1f}",
                "coverage": _percent(item.get("coverage"), 0),
                "pb": None if _number(item.get("owner_pb")) is None else f"{_number(item.get('owner_pb')):.2f}x",
                "justified": None if _number(item.get("justified_pb")) is None else f"{_number(item.get('justified_pb')):.2f}x",
                "roe": _percent(item.get("roe"), 1),
                "ci": None if _number(item.get("cost_income_pct")) is None else f"{_number(item.get('cost_income_pct')):.0f} %",
                "yield": _percent(item.get("ttm_yield"), 1),
            }
        )
    field = ft.TextField(key="instrument-detail.sparebank-peer-input", **field_input_style(placeholder="e.g. HELG"))
    note = Note("Peers are the other scored certificates; picked peers are listed first.")

    def apply(ids: list[str]) -> None:
        try:
            set_picked_peers(root, instrument_id, ids)
        except (OSError, ValueError):
            note.value = "Could not save the peer selection."
        else:
            note.value = "Peer selection saved. Reopen the page to see the new order."
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    picked = [str(item) for item in _sequence(workspace.get("picked_peers"))]

    def add(_event: object) -> None:
        candidate = str(field.value or "").strip().upper()
        known = {str(item.get("instrument_id")) for item in peers}
        if candidate not in known:
            note.value = f"{candidate or 'That id'} is not a scored certificate in the peer list."
        else:
            apply(sorted({*picked, candidate}))
            return
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    def clear(_event: object) -> None:
        apply([])

    body: list[ft.Control] = [
        DataTable(
            [
                TableColumn("peer", "Certificate", flex=3, sortable=False),
                TableColumn("pick", "Source", flex=1, sortable=False),
                TableColumn("composite", "Composite", numeric=True, sortable=False),
                TableColumn("coverage", "Coverage", numeric=True, sortable=False),
                TableColumn("pb", "P/B", numeric=True, sortable=False),
                TableColumn("justified", "Justified P/B", numeric=True, sortable=False),
                TableColumn("roe", "ROE", numeric=True, sortable=False),
                TableColumn("ci", "Cost/income", numeric=True, sortable=False),
                TableColumn("yield", "Yield", numeric=True, sortable=False),
            ],
            rows,
            row_height=48,
            max_visible_rows=12,
            empty_title="No peers scored yet",
            empty_reason="Peer rows are written when certificates are rescored (scripts/sparebank_refresh.py).",
        ),
        ft.Row([Field("Add peer (certificate id)", control=field, width=200), Button.secondary("Add peer", add, key="instrument-detail.sparebank-peer-add"), Button.secondary("Clear picks", clear, key="instrument-detail.sparebank-peer-clear")], spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.END),
        note,
    ]
    return GlassCard("Peers", note="other certificates, auto plus picked", body=body, key="instrument-detail.sparebank-peers")


# ---------------------------------------------------------------------------
# Pillar 3 confirmation
# ---------------------------------------------------------------------------


def _pillar3(workspace: Mapping[str, object], root: object, page: object | None, instrument_id: str) -> ft.Control:
    queue = _mapping(workspace.get("pillar3"))
    figures = [_mapping(item) for item in _sequence(queue.get("figures"))]
    documents = {str(_mapping(item).get("document_id")): _mapping(item) for item in _sequence(queue.get("documents"))}
    if not figures:
        return GlassCard(
            "Pillar 3 and annual-report figures",
            note="semi-automatic: you confirm every figure",
            body=[_unavailable("Nothing proposed", "No Pillar 3 or annual-report PDF has been read for this certificate. Run scripts/extract_pillar3.py with the issuer's PDF; proposed figures appear here and never count until you confirm them.")],
            key="instrument-detail.sparebank-pillar3",
        )
    status_note = Note("Proposed figures are never used as evidence until you confirm them. Confirming a figure replaces an earlier confirmation of the same metric and period. Reopen the page to see the score change.")

    def decide(figure_id: str, decision: str) -> None:
        try:
            review_pillar3_figure(root, instrument_id, figure_id, decision)
        except (KeyError, OSError, ValueError) as exc:
            status_note.value = f"Could not save the decision: {exc}"
        else:
            status_note.value = f"Figure {decision}. Reopen the page to see the score change."
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    rows = []
    for item in figures:
        document = documents.get(str(item.get("document_id")), {})
        figure_id = str(item.get("figure_id"))
        state = str(item.get("status") or "pending")
        flags = ", ".join(str(flag).replace("_", " ") for flag in _sequence(item.get("flags")))
        actions: ft.Control
        if state == "pending":
            actions = ft.Row(
                [
                    Button.primary("Confirm", lambda _e, fid=figure_id: decide(fid, "confirmed"), key=f"instrument-detail.pillar3-confirm.{figure_id}"),
                    Button.secondary("Reject", lambda _e, fid=figure_id: decide(fid, "rejected"), key=f"instrument-detail.pillar3-reject.{figure_id}"),
                ],
                spacing=6,
            )
        else:
            actions = Tag(state, "ok" if state == "confirmed" else "mute", dense=True)
        rows.append(
            {
                "metric": (str(item.get("label") or item.get("metric")), str(item.get("metric"))),
                "value": f"{_number(item.get('value')):g} %" if _number(item.get("value")) is not None else None,
                "period": str(item.get("period") or ""),
                "source": (f"{document.get('title', 'document')} · page {item.get('page')}", str(item.get("printed_text") or "")[:90]),
                "flags": _text(flags or "none", size=12, color=theme.AMBER if flags else theme.INK3),
                "action": actions,
            }
        )
    pending = sum(1 for item in figures if item.get("status") == "pending")
    body: list[ft.Control] = [
        status_note,
        DataTable(
            [
                TableColumn("metric", "Figure", flex=3, sortable=False),
                TableColumn("value", "Value", numeric=True, sortable=False),
                TableColumn("period", "Period", flex=2, sortable=False),
                TableColumn("source", "Source page and printed text", flex=5, sortable=False),
                TableColumn("flags", "Uncertainty", flex=3, sortable=False),
                TableColumn("action", "Decision", flex=3, sortable=False),
            ],
            rows,
            row_height=58,
            max_visible_rows=10,
        ),
    ]
    return GlassCard("Pillar 3 and annual-report figures", note=f"{pending} awaiting your decision", body=body, key="instrument-detail.sparebank-pillar3")


# ---------------------------------------------------------------------------
# Remaining sections
# ---------------------------------------------------------------------------


def _structural(workspace: Mapping[str, object]) -> ft.Control:
    events = _mapping(workspace.get("structural_transition"))
    items = [_mapping(item) for item in _sequence(events.get("events"))]
    if not items:
        body: ft.Control = Note("No merger, conversion or sell-down event is recorded for this certificate, so the structural-transition axis has no evidence. Events are added by the owner; none is inferred.")
    else:
        body = DataTable(
            [TableColumn("event", "Event", sortable=False), TableColumn("status", "Status", sortable=False)],
            [{"event": str(item.get("event_type") or item.get("id") or "event"), "status": str(item.get("status") or "")} for item in items],
            row_height=40,
        )
    return GlassCard("Structural transition", note="mergers, conversions, sell-downs (book ch. 6-7)", body=[body], key="instrument-detail.sparebank-structural")


def _marketability(workspace: Mapping[str, object]) -> ft.Control:
    market = _mapping(_mapping(workspace.get("marketability_implementation")).get("marketability"))
    days, turnover = _number(market.get("days_to_trade")), _number(market.get("median_turnover_nok_60d"))
    tiles = [
        KpiTile("Days to trade", None if days is None else f"{days:.2f}", f"reference position {_number(market.get('reference_position_nok')):,.0f} NOK at {_percent(market.get('participation_rate'), 0)} of volume" if days is not None and _number(market.get("reference_position_nok")) else "Needs price and volume history"),
        KpiTile("Median turnover (60d)", None if turnover is None else f"{turnover / 1e6:,.1f} m NOK", "per day" if turnover is not None else "Needs price and volume history"),
    ]
    return GlassCard("Marketability and implementation", note="liquidity of the certificate", body=[_tiles(tiles)], key="instrument-detail.sparebank-marketability")


def _tactical(workspace: Mapping[str, object]) -> ft.Control:
    tactical = _mapping(workspace.get("tactical_horizon"))
    evidence = _mapping(tactical.get("evidence"))
    rows = [{"component": str(_mapping(item).get("key") or ""), "value": None if _number(_mapping(item).get("raw_metric")) is None else f"{_number(_mapping(item).get('raw_metric')):.2f}"} for item in _sequence(evidence.get("components"))]
    body: list[ft.Control] = [
        _text(f"Tactical horizon — {tactical.get('horizon', '1-3 months')} · status {str(tactical.get('status', 'UNAVAILABLE')).lower()}", bold=True, color=theme.INK),
        Note("Tactical evidence is separate and never changes the underwriting score."),
    ]
    if rows:
        body.append(DataTable([TableColumn("component", "Component", sortable=False), TableColumn("value", "Value", numeric=True, sortable=False)], rows, row_height=36))
    return GlassCard("Tactical evidence", note="separate from underwriting", body=body, key="instrument-detail.sparebank-tactical")


def render_sparebank_workspace(workspace: object, *, root: object = None, page: object | None = None) -> ft.Control:
    """The Sparebank EC workspace: summary, axes, ownership, economics, valuation, dividends, history, peers."""

    if not isinstance(workspace, Mapping) or workspace.get("status") != "available":
        return ft.Container()
    scorecard = _mapping(workspace.get("scorecard"))
    instrument_id = str(workspace.get("instrument_id") or "")
    raw = json.dumps(dict(workspace), default=str, ensure_ascii=False, sort_keys=True, indent=2)
    body: list[ft.Control] = [
        Note("Bank soundness, EC owner value, and purchase-price attractiveness are separate conclusions; no automatic buy/sell rule is produced."),
        _summary(workspace),
        GlassCard("Scorecard axes", note=f"formula {scorecard.get('formula_version', 'unavailable')}", body=[_axes(workspace)], key="instrument-detail.sparebank-axes"),
        _ownership(workspace),
        _bank_economics(workspace),
        _valuation(workspace),
        _dividends(workspace),
        _history(workspace),
        _peers(workspace, root, page, instrument_id),
        _pillar3(workspace, root, page, instrument_id),
        _structural(workspace),
        _marketability(workspace),
        _tactical(workspace),
        Disclosure("Audit: complete stored analysis", raw, expanded=False),
    ]
    return ft.ExpansionTile(
        title=ft.Text("Sparebank EC workspace"),
        subtitle=ft.Text(f"Scorecard {scorecard.get('formula_version', 'unavailable')} | execution_allowed=false"),
        controls=[ft.Column(body, spacing=10)],
        expanded=True,
        key="instrument-detail.sparebank-workspace",
    )
