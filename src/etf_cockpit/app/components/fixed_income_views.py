"""Small read-only bond and portfolio maturity views over saved projections."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.app.formatting import format_currency, format_number, format_percent


@dataclass(frozen=True)
class FixedIncomeBondViewModel:
    """Presentation-ready references to the canonical bond projections."""

    instrument_id: str
    status: str
    projections: Mapping[str, Mapping[str, object]]
    coverage: Mapping[str, str]
    source_as_of_dates: Mapping[str, tuple[str, ...]]
    warnings: tuple[str, ...]
    execution_allowed: bool = False


def build_fixed_income_bond_view_model(
    instrument_id: str,
    *,
    terms_projection: Mapping[str, object] | None,
    market_data_projection: Mapping[str, object] | None,
    analytics_projection: Mapping[str, object] | None,
    risk_projection: Mapping[str, object] | None,
) -> FixedIncomeBondViewModel:
    """Bind the existing API/export projections without recalculating values."""

    projections = {
        name: _projection(value, name)
        for name, value in (
            ("terms", terms_projection),
            ("market_data", market_data_projection),
            ("analytics", analytics_projection),
            ("risk", risk_projection),
        )
    }
    terms = projections["terms"]
    terms_value = terms.get("terms")
    terms_record = terms_value if isinstance(terms_value, Mapping) else {}
    schedules = {
        key: terms.get(key) if isinstance(terms.get(key), Sequence) and not isinstance(terms.get(key), (str, bytes)) else ()
        for key in ("coupon_schedule", "redemption_schedule")
    }
    coverage = {
        name: str(value.get("status") or "unavailable")
        for name, value in projections.items()
    }
    coverage["coupon_schedule"] = "available" if schedules["coupon_schedule"] else "unavailable"
    coverage["redemption_schedule"] = "available" if schedules["redemption_schedule"] else "unavailable"

    dates: dict[str, tuple[str, ...]] = {}
    term_dates = tuple(
        str(terms_record[key])
        for key in ("known_at", "retrieved_at")
        if terms_record.get(key) not in (None, "")
    )
    if term_dates:
        dates["terms"] = term_dates
    market = projections["market_data"]
    for collection in ("observations", "curves", "liquidity"):
        records = market.get(collection)
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            continue
        values = tuple(
            str(row.get("as_of") or row.get("valid_at"))
            for row in records
            if isinstance(row, Mapping) and (row.get("as_of") or row.get("valid_at"))
        )
        if values:
            dates[f"market_data.{collection}"] = values

    warnings = _unsupported_warnings(terms)
    for name, projection in projections.items():
        reasons = projection.get("reason_codes")
        if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)):
            warnings.extend(f"{name}:{reason}" for reason in reasons if str(reason) not in {"unsupported_structure"})
    available = any(value.get("status") == "available" for value in projections.values())
    return FixedIncomeBondViewModel(
        instrument_id=str(instrument_id),
        status="available" if available else "unavailable",
        projections=projections,
        coverage=coverage,
        source_as_of_dates=dates,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def fixed_income_bond_panel(view_model: FixedIncomeBondViewModel) -> ft.Control:
    """Render the saved terms, valuation, risk and source coverage for one bond."""

    terms_projection = view_model.projections["terms"]
    terms_value = terms_projection.get("terms")
    terms = terms_value if isinstance(terms_value, Mapping) else {}
    analytics = view_model.projections["analytics"]
    risk = view_model.projections["risk"]
    market = view_model.projections["market_data"]
    optionality = terms_projection.get("optionality_schedule")
    optionality = optionality if isinstance(optionality, Mapping) else {}
    warning_controls = [
        ft.Container(
            content=ft.Text(
                warning,
                color=theme.AMBER,
                weight=ft.FontWeight.BOLD,
                selectable=True,
            ),
            border=border_all(1, theme.AMBER),
            padding=8,
        )
        for warning in view_model.warnings
        if warning.upper().startswith("UNSUPPORTED FIXED-INCOME STRUCTURE:")
    ]
    coverage_text = ", ".join(f"{key}={value}" for key, value in view_model.coverage.items())
    date_text = "; ".join(
        f"{key}: {', '.join(values)}" for key, values in view_model.source_as_of_dates.items()
    ) or "Unavailable"
    controls: list[ft.Control] = [
        section_header(
            "Bond detail",
            "Saved contractual terms and canonical analytics. Values match the read-only API/export projections.",
        ),
        ft.Text(
            f"Instrument: {view_model.instrument_id}; status: {view_model.status}; execution_allowed=false.",
            color=theme.MUTED,
            selectable=True,
        ),
        *warning_controls,
        ft.Text(f"Coverage: {coverage_text}", color=theme.MUTED, selectable=True),
        ft.Text(f"Source as-of / known dates: {date_text}", color=theme.MUTED, selectable=True),
        ft.Text(
            "Terms: "
            + "; ".join(
                f"{key}={_text_value(terms.get(key))}"
                for key in (
                    "security_type",
                    "issuer_id",
                    "currency",
                    "maturity_date",
                    "face_value",
                    "coupon_type",
                    "coupon_rate",
                    "coupon_frequency",
                    "country",
                    "source_id",
                    "source_document",
                    "confidence",
                )
            ),
            selectable=True,
        ),
        ft.Text(_analytics_line(analytics), selectable=True),
        ft.Text(
            "Risk and forecast: "
            + _projection_summary(risk)
            + "; forecast="
            + ("available" if _has_forecast(analytics, risk) else "unavailable (no saved fixed-income forecast projection)"),
            selectable=True,
        ),
        ft.Text(f"Market evidence: {_market_summary(market)}", selectable=True),
        ft.Text(
            "Call/optionality terms: " + _text_value(optionality),
            selectable=True,
        ),
    ]
    for title, key in (("Coupon schedule", "coupon_schedule"), ("Principal/redemption schedule", "redemption_schedule")):
        rows = terms_projection.get(key)
        controls.extend(_schedule_controls(title, rows, str(terms_projection.get("reason_codes") or "terms unavailable")))
    return ft.Container(
        key="instrument-detail.fixed-income-overview",
        content=panel(ft.Column(controls, spacing=6)),
    )


def portfolio_maturity_ladder_panel(projection: Mapping[str, object]) -> ft.Control:
    """Render the calculated maturity ladder without adding UI-side totals."""

    flows = projection.get("cash_flows")
    flow_rows = flows if isinstance(flows, Sequence) and not isinstance(flows, (str, bytes)) else ()
    rows: list[ft.DataRow] = []
    for item in flow_rows:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(item.get("payment_date") or "Unavailable"), selectable=True)),
                    ft.DataCell(ft.Text(str(item.get("flow_type") or "Unavailable"), selectable=True)),
                    ft.DataCell(ft.Text(format_currency(item.get("amount"), currency=str(item.get("currency") or "EUR")), selectable=True)),
                    ft.DataCell(ft.Text(str(item.get("source_confidence") or "unavailable"), selectable=True)),
                    ft.DataCell(ft.Text(str(item.get("status") or "unavailable"), selectable=True)),
                    ft.DataCell(ft.Text(", ".join(map(str, item.get("source_ids", ()))) or "Unavailable", selectable=True)),
                ]
            )
        )
    table: ft.Control = (
        ft.DataTable(
            columns=[ft.DataColumn(ft.Text(label)) for label in ("Payment date", "Cash flow", "Expected amount", "Source confidence", "Coverage", "Source")],
            rows=rows,
        )
        if rows
        else ft.Text(str(projection.get("reason") or "No saved bond cash flows are available."), color=theme.MUTED, selectable=True)
    )
    totals = projection.get("totals")
    total_lines = [
        ft.Text(
            f"{item.get('flow_type')}: {format_currency(item.get('amount'), currency=str(item.get('currency') or 'EUR'))} ({item.get('status')})",
            selectable=True,
        )
        for item in totals
        if isinstance(item, Mapping)
    ] if isinstance(totals, Sequence) and not isinstance(totals, (str, bytes)) else []
    coverage = projection.get("coverage")
    coverage = coverage if isinstance(coverage, Mapping) else {}
    source_dates = projection.get("source_as_of_dates")
    source_dates = source_dates if isinstance(source_dates, Mapping) else {}
    date_lines = [
        f"{instrument_id}: " + ", ".join(f"{field}={value}" for field, value in dates.items())
        for instrument_id, dates in source_dates.items()
        if isinstance(dates, Mapping)
    ]
    exposure_lines = _exposure_lines(projection.get("exposures"))
    warnings = projection.get("warnings")
    warning_text = "; ".join(map(str, warnings)) if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes)) else ""
    controls: list[ft.Control] = [
        section_header(
            "Fixed-income maturity and income ladder",
            "Exact certified payment dates from the saved portfolio calendar. Source confidence describes terms evidence, not a probability forecast.",
        ),
        ft.Text(
            f"Status: {projection.get('status', 'unavailable')}; as of {projection.get('decision_time') or 'unavailable'}; currency {projection.get('currency') or 'unavailable'}; "
            f"coverage: {coverage.get('known_flow_count', 0)}/{coverage.get('flow_count', 0)} flows; execution_allowed=false.",
            color=theme.AMBER if warning_text or projection.get("status") != "available" else theme.MUTED,
            selectable=True,
        ),
        ft.Text(warning_text or "No coverage warnings.", color=theme.AMBER if warning_text else theme.MUTED, selectable=True),
        table,
        section_header("Expected income and maturity proceeds"),
        *(total_lines or [ft.Text("Unavailable: no supported total is present.", color=theme.MUTED, selectable=True)]),
        section_header("Fixed-income exposures"),
        *exposure_lines,
        ft.Text("Terms source dates: " + ("; ".join(date_lines) or "Unavailable"), color=theme.MUTED, selectable=True),
    ]
    return ft.Container(key="portfolio.fixed-income-maturity-ladder", content=panel(ft.Column(controls, spacing=6)))


def _projection(value: Mapping[str, object] | None, name: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {"status": "unavailable", "reason_codes": [f"{name}_projection_unavailable"], "execution_allowed": False}


def _unsupported_warnings(terms_projection: Mapping[str, object]) -> list[str]:
    reasons = terms_projection.get("reason_codes")
    has_unsupported_reason = isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)) and "unsupported_structure" in reasons
    optionality = terms_projection.get("optionality_schedule")
    optionality = optionality if isinstance(optionality, Mapping) else {}
    terms_value = terms_projection.get("terms")
    terms = terms_value if isinstance(terms_value, Mapping) else {}
    nested_optionality = terms.get("optionality")
    nested_optionality = nested_optionality if isinstance(nested_optionality, Mapping) else {}
    features = optionality.get("features", nested_optionality.get("features", ()))
    unsupported = [str(item) for item in features if str(item).strip()] if isinstance(features, Sequence) and not isinstance(features, (str, bytes)) else []
    unsupported.extend(str(item) for item in optionality.get("unsupported_features", ()) if str(item).strip()) if isinstance(optionality.get("unsupported_features"), Sequence) and not isinstance(optionality.get("unsupported_features"), (str, bytes)) else None
    if has_unsupported_reason or unsupported:
        detail = ", ".join(dict.fromkeys(unsupported)) or "unsupported terms or optionality"
        return [f"UNSUPPORTED FIXED-INCOME STRUCTURE: {detail}. Contractual valuation and projections are unavailable or may not apply."]
    return []


def _schedule_controls(title: str, value: object, fallback_reason: str) -> list[ft.Control]:
    rows = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
    if not rows:
        return [ft.Text(f"{title}: unavailable ({fallback_reason})", color=theme.MUTED, selectable=True)]
    lines = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            ft.Text(
                f"{title}: date={row.get('payment_date') or 'unavailable'}; amount={row.get('amount', 'unavailable')} {row.get('currency') or ''}; source={row.get('source_id') or 'unavailable'}; version={row.get('source_version_id') or 'unavailable'}",
                selectable=True,
            )
        )
    return lines or [ft.Text(f"{title}: unavailable ({fallback_reason})", color=theme.MUTED, selectable=True)]


def _analytics_line(projection: Mapping[str, object]) -> str:
    values = projection
    keys = (
        "clean_price",
        "dirty_price",
        "accrued_interest",
        "current_yield",
        "yield_to_maturity",
        "yield_to_worst",
        "macaulay_duration",
        "modified_duration",
        "convexity",
        "dv01",
        "status",
    )
    parts = []
    for key in keys:
        value = values.get(key)
        if key in {"current_yield", "yield_to_maturity", "yield_to_worst"}:
            display = format_percent(value)
        else:
            display = format_number(value) if value is not None else "unavailable"
        parts.append(f"{key}={display}")
    return "Canonical valuation and risk metrics: " + "; ".join(parts)


def _projection_summary(projection: Mapping[str, object]) -> str:
    reasons = projection.get("reason_codes")
    reason_text = ", ".join(map(str, reasons)) if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)) else ""
    return f"status={projection.get('status', 'unavailable')}" + (f"; reason={reason_text}" if reason_text else "")


def _market_summary(projection: Mapping[str, object]) -> str:
    observations = projection.get("observations")
    records = observations if isinstance(observations, Sequence) and not isinstance(observations, (str, bytes)) else ()
    dates = [str(row.get("as_of") or "unavailable") for row in records if isinstance(row, Mapping)]
    return f"status={projection.get('status', 'unavailable')}; saved observations={len(records)}; source as-of={', '.join(dates) or 'unavailable'}"


def _has_forecast(*projections: Mapping[str, object]) -> bool:
    return any(isinstance(item.get("forecast"), Mapping) or isinstance(item.get("distribution"), Mapping) for item in projections)


def _exposure_lines(value: object) -> list[ft.Control]:
    exposures = value if isinstance(value, Mapping) else {}
    lines: list[ft.Control] = []
    for category, raw in exposures.items():
        item = raw if isinstance(raw, Mapping) else {}
        records = item.get("rows")
        rows = records if isinstance(records, Sequence) and not isinstance(records, (str, bytes)) else ()
        rendered = ", ".join(
            f"{row.get('label')}: {format_currency(row.get('market_value_eur'), currency='EUR')}"
            for row in rows
            if isinstance(row, Mapping)
        )
        reason = str(item.get("reason") or "")
        lines.append(
            ft.Text(
                f"{category}: {item.get('status', 'unavailable')}"
                + (f"; {rendered}" if rendered else "")
                + (f"; reason={reason}" if reason else ""),
                color=theme.MUTED if item.get("status") == "available" else theme.AMBER,
                selectable=True,
            )
        )
    return lines or [ft.Text("Fixed-income exposure breakdown unavailable.", color=theme.MUTED, selectable=True)]


def _text_value(value: object) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    return str(value)
