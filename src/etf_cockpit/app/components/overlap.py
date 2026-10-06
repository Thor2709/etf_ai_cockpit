"""Reusable presentation for direct overlap evidence."""

from __future__ import annotations

import math

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header


def report_weight(report: object, name: str) -> float | None:
    """Return a finite report weight, or None when it is missing (never 0)."""

    if str(getattr(report, "status", "missing")) == "missing" and not getattr(report, "report_hash", ""):
        return None
    try:
        number = float(getattr(report, name, None))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _weight_text(report: object, name: str) -> str:
    """Format a report weight; a missing/non-finite value is Unavailable, never 0."""

    number = report_weight(report, name)
    if number is None:
        return "Unavailable (no holdings evidence or weight not reported)"
    return f"{number:.1%}"


def overlap_evidence_panel(report: object, *, key: str, title: str = "ETF direct overlap") -> ft.Control:
    status = str(getattr(report, "status", "missing"))
    coverage = tuple(getattr(report, "coverage", ()))
    pairs = tuple(getattr(report, "pairs", ()))
    concentrations = tuple(getattr(report, "concentrations", ()))
    exposures = tuple(getattr(report, "exposures", ()))
    warnings = tuple(getattr(report, "warnings", ()))
    coverage_lines = [
        (
            f"{item.instrument_id}: coverage={item.status} | freshness={item.freshness} | "
            f"as_of={item.as_of or 'N/A'} | resolved={item.resolved_weight:.1%} | "
            f"unresolved={item.unresolved_weight:.1%} | source_id={item.source_id or 'N/A'} | "
            f"authority={getattr(item, 'authority', None) or 'N/A'} | "
            f"known_at={getattr(item, 'known_at', None) or 'N/A'} | "
            f"checksum={item.source_checksum or 'N/A'}"
        )
        for item in coverage
    ]
    pair_lines: list[str] = []
    for pair in pairs:
        observed = "N/A" if pair.observed_overlap_weight is None else f"{pair.observed_overlap_weight:.1%}"
        current = "N/A" if pair.current_overlap_weight is None else f"{pair.current_overlap_weight:.1%}"
        top = ", ".join(f"{item.display_name} {item.shared_weight:.1%}" for item in pair.top_holdings) or "none observed"
        pair_lines.append(
            f"{pair.left_instrument_id} / {pair.right_instrument_id}: status={pair.status} | "
            f"observed dated overlap={observed} | current overlap={current} | top shared: {top}"
        )
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(item.dimension, size=11)),
                ft.DataCell(ft.Text(item.bucket, size=11)),
                ft.DataCell(ft.Text(f"{item.current_weight:.1%}", size=11)),
                ft.DataCell(ft.Text(f"{item.target_weight:.1%}", size=11)),
            ]
        )
        for item in concentrations[:20]
    ]
    body: list[ft.Control] = [
        section_header(title, "Exact typed identities and weighted-min overlap; unresolved holdings are never renormalised."),
        ft.Text(f"coverage_status={status} | execution_allowed=false", color=theme.TEXT, selectable=True),
        ft.Text(
            "look-through: "
            f"mapped={_weight_text(report, 'mapped_weight')} | "
            f"unknown/unmapped={_weight_text(report, 'unknown_weight')} | "
            f"report_hash={getattr(report, 'report_hash', '') or 'N/A'}",
            color=theme.TEXT,
            selectable=True,
        ),
        *[ft.Text(line, color=theme.MUTED, size=11, selectable=True) for line in coverage_lines or ["No holdings coverage is available."]],
        *[ft.Text(line, color=theme.MUTED, size=11, selectable=True) for line in pair_lines or ["No ETF pair can be compared."]],
    ]
    exposure_lines = [
        (
            f"{item.dimension}/{item.bucket}: direct={item.direct_weight:.1%} | "
            f"indirect={item.indirect_weight:.1%} | combined={item.combined_weight:.1%} | "
            f"contributors={len(item.contributors)}"
        )
        for item in exposures[:30]
    ]
    body.extend(ft.Text(line, color=theme.MUTED, size=11, selectable=True) for line in exposure_lines)
    if rows:
        body.append(
            ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("Dimension")),
                    ft.DataColumn(ft.Text("Bucket")),
                    ft.DataColumn(ft.Text("Current")),
                    ft.DataColumn(ft.Text("Target")),
                ],
                rows=rows,
            )
        )
    if warnings:
        body.append(ft.Text("Warnings: " + " ".join(warnings), color=theme.AMBER, size=11, selectable=True))
    return panel(ft.Column(body, key=key, spacing=6, scroll=ft.ScrollMode.AUTO))


__all__ = ["overlap_evidence_panel", "report_weight"]
