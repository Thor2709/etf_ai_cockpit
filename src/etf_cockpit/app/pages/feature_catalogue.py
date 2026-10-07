from __future__ import annotations

import flet as ft

from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import DataTable, GlassCard, KpiStrip, ListRow, Note, TableColumn, Well
from etf_cockpit.app.formatting import format_count
from etf_cockpit.app.pages._p4_common import grid, make_layout, page_view
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_views.feature_catalogue import (
    COVERAGE_WARN_BELOW,
    build_feature_catalogue_view,
)
from etf_cockpit.core.paths import ROOT

_NO_FEATURE_DEFINITIONS = "No feature definitions are available."


def feature_catalogue_page(page: ft.Page | None, state: AppState):
    """Show feature definitions and a safe local training-data preview (spec 7.20)."""

    view = build_feature_catalogue_view(ROOT, getattr(state.snapshot, "features", None))
    layout = make_layout(page, strip=True)
    count = len(view.definitions)
    strip = KpiStrip(
        "Feature catalogue",
        f"{count} features registered",
        "definitions and built-in baselines",
        [
            ("Registered features", str(count), "versioned definitions", None),
            ("Targets", str(len(view.targets)), "stored separately from features", None),
            (
                "Preview rows",
                format_count(view.preview_rows, unavailable="Unavailable"),
                "local feature snapshot" if view.preview_rows is not None else (view.unavailable_reason or ""),
                None,
            ),
            (
                "Missing rows",
                format_count(view.missing_rows, unavailable="Unavailable"),
                "visible, never silently imputed",
                None,
            ),
        ],
    )

    def_w, def_h = layout.card_body(8, 1)
    definitions = DataTable(
        [
            TableColumn("feature", "Feature", flex=3),
            TableColumn("source", "Source", flex=3),
            TableColumn("lookback", "Lookback / delay", flex=2),
            TableColumn("units", "Units", flex=3),
            TableColumn("missing", "Missing", flex=2),
        ],
        [
            {
                "feature": row.feature_id,
                "source": row.source_column,
                "lookback": row.lookback,
                "units": row.units,
                "missing": row.missing_policy,
            }
            for row in view.definitions
        ],
        row_height=40,
        height=def_h,
        empty_title="No feature definitions",
        empty_reason=_NO_FEATURE_DEFINITIONS,
    )
    definitions_card = GlassCard(
        "Feature definitions",
        "lookbacks, delay, units and missing policy are part of the contract",
        body=definitions,
        expand=True,
    )

    cov_w, cov_h = layout.card_body(4, 1, insight=True)
    lowest = view.lowest_coverage
    ranked = sorted((row for row in view.coverage if row.coverage_pct is not None), key=lambda row: row.coverage_pct or 0.0)[:10]
    ranked.reverse()
    coverage_chart = ck.horizontal_stacked_bar(
        [row.feature for row in ranked],
        [
            [ck.Segment(row.coverage_pct or 0.0, "gold" if (row.coverage_pct or 0.0) < COVERAGE_WARN_BELOW * 100 else "blue", f"{row.coverage_pct:.1f}%")]
            for row in ranked
        ],
        x_name="Coverage (%)",
        x_max=100,
        unit="%",
        margins=ck.Margins(left=min(round(cov_w * 0.5), 16 + round(7.4 * max((len(row.feature) for row in ranked), default=8))), right=44, top=12, bottom=44),
        width=cov_w,
        height=cov_h,
        unavailable_reason=None if ranked else (view.unavailable_reason or "No feature coverage has been computed."),
        empty_title="Coverage unavailable",
        insight=f"{lowest.feature} has the lowest coverage ({lowest.coverage_pct:.1f}%)." if lowest else None,
    )
    coverage_card = GlassCard(
        "Feature coverage",
        "share of rows with a value",
        insight=f"{lowest.feature} has the lowest coverage ({lowest.coverage_pct:.1f}%)." if lowest else None,
        body=Well(coverage_chart),
        expand=True,
    )

    sample_columns = [
        TableColumn(name, name, flex=2, numeric=name not in {"date", "etf_id"}) for name in view.sample_columns
    ]
    sample = DataTable(
        sample_columns,
        [
            {name: _cell(name, row[name]) for name in view.sample_columns}
            for row in view.sample_rows
        ],
        row_height=32,
        height=min(len(view.sample_rows) * 32 + 44, max(120.0, layout.card_body(8, 2)[1] - 130)),
        empty_title="No preview rows",
        empty_reason=view.unavailable_reason or "No local feature snapshot has been built yet.",
    )
    preview_card = GlassCard(
        "Training data preview",
        "selected by decision timestamp",
        body=[
            sample,
            Note("Feature matrix: local snapshot only; run materialisation for an explicit as-of date."),
            Note("Rows are selected by decision timestamp; late revisions cannot enter earlier vintages."),
            Note("Parity: offline, paper and disabled live-inference contracts share the same feature definitions."),
        ],
        expand=True,
    )

    target_sub = "; ".join(view.targets) if view.targets else "None registered; targets remain separate from inference inputs."
    targets_card = GlassCard(
        "Targets and leakage controls",
        body=[
            ListRow("info", "Targets", target_sub),
            ListRow("ok", "Embargo checks", "Overlapping target windows are rejected before validation."),
            ListRow("ok", "Parity", "Offline, paper and disabled live-inference contracts share the same feature definitions.", last=True),
            Note("Outcomes mature after the decision timestamp and are never copied into feature inputs. execution_allowed=false"),
        ],
        expand=True,
    )
    body = grid(
        layout,
        [[(strip, 12)], [(definitions_card, 8), (coverage_card, 4)], [(preview_card, 8), (targets_card, 4)]],
    )
    return page_view(
        "Feature Catalogue",
        "Versioned point-in-time feature definitions and a leakage-safe training preview",
        body,
    )


def _cell(name: str, value: object) -> object:
    if name in {"date", "etf_id"}:
        return str(value)
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if number != number else f"{number:.4f}"


__all__ = ["feature_catalogue_page"]
