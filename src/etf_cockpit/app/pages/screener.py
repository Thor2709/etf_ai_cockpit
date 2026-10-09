"""Local fundamentals screening and saved-selection views."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence

import flet as ft
import pandas as pd

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
    Pipeline,
    ScoreBar,
    Segmented,
    TableColumn,
    Tag,
    Well,
    field_input_style,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_number, format_percent
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    FUNDAMENTAL_CLEAN_PATH,
    ScreenFilter,
    ScreenSort,
    build_screen_rows,
    export_screen_csv,
    export_table,
    latest_fundamental_rows,
    load_fixed_income_screener,
    load_fundamental_evidence,
    load_screen,
    load_top_n_selection,
    query_for_snapshot,
    run_screen,
    save_screen,
)
from etf_cockpit.core.paths import EXPORTS_DIR

_FUNDAMENTAL_FIELDS = (
    ("valuation", "Valuation"),
    ("profitability", "Profitability"),
    ("leverage", "Leverage"),
    ("growth", "Growth"),
    ("shareholder_return", "Shareholder return"),
)
_SCREEN_COLUMNS = (
    TableColumn("instrument_id", "Instrument Id"),
    TableColumn("region", "Region"),
    TableColumn("sector", "Sector"),
    TableColumn("score", "Score", numeric=True),
    TableColumn("quality", "Quality", numeric=True),
    TableColumn("risk_friction", "Risk Friction", numeric=True),
)


def _read(record: object, name: str, fallback: object = None) -> object:
    if isinstance(record, Mapping):
        return record.get(name, fallback)
    return getattr(record, name, fallback)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _shown(value: object) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return "—"
    try:
        if bool(pd.isna(value)):
            return "—"
    except (TypeError, ValueError):
        pass
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value) or "—"
    return str(value)


def _human(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "Unavailable"
    return text.replace("_", " ").replace("-", " ").capitalize()


def _field(
    label: str,
    key: str,
    options: Sequence[tuple[str, str]],
    value: str,
    on_change=None,
    columns: int = 4,
) -> tuple[ft.Control, ft.Dropdown]:
    control = ft.Dropdown(
        key=key,
        value=value,
        options=[ft.DropdownOption(option, caption) for option, caption in options],
        dense=True,
    )
    control.on_change = on_change
    return (
        ft.Container(
            content=Field(label, control=control, expand=True),
            col={"xs": 12, "md": columns},
        ),
        control,
    )


def _text_field(label: str, key: str, placeholder: str = "", *, columns: int = 4) -> ft.Control:
    control = ft.TextField(key=key, **field_input_style(placeholder=placeholder))
    return ft.Container(
        content=Field(label, control=control, expand=True),
        col={"xs": 12, "md": columns},
    )


def _screen_table(result: object, sort_key: str | None, descending: bool, on_sort) -> ft.Control:
    records = _read(result, "rows", ())
    rows = []
    for record in records if isinstance(records, (tuple, list)) else ():
        values: dict[str, object] = {}
        for column in _SCREEN_COLUMNS:
            value = _read(record, column.key)
            if column.key == "score":
                values[column.key] = ScoreBar(_number(value), maximum=10)
            elif column.key in {"quality", "risk_friction"}:
                number = _number(value)
                values[column.key] = format_number(number, decimals=1, unavailable="—")
            else:
                values[column.key] = _shown(value)
        rows.append(values)
    return DataTable(
        _SCREEN_COLUMNS,
        rows,
        sort_key=sort_key,
        descending=descending,
        on_sort=on_sort,
        empty_title="No screen results",
        empty_reason="Unavailable · no local instruments match the current evidence screen.",
    )


def _distribution(result: object, field: str) -> ft.Control:
    records = _read(result, "rows", ())
    values = [
        number
        for record in records if isinstance(records, (tuple, list))
        if (number := _number(_read(record, field))) is not None
    ]
    if not values:
        chart = ck.histogram(
            [],
            [],
            x_name=f"{_human(field)} (bin start)",
            y_name="Instruments (count)",
            unavailable_reason=f"Unavailable · no numeric values are available for {_human(field)}.",
        )
    else:
        low, high = min(values), max(values)
        bucket_count = min(5, len(values))
        span = high - low
        width = span / bucket_count if span else 1.0
        counts = [0] * bucket_count
        for value in values:
            index = min(bucket_count - 1, int((value - low) / width))
            counts[index] += 1
        bins = [format_number(low + index * width, decimals=1) for index in range(bucket_count)]
        chart = ck.histogram(
            bins,
            counts,
            x_name=f"{_human(field)} (bin start)",
            y_name="Instruments (count)",
            insight=f"{len(values)} local values in the current screen.",
        )
    return Well(chart, expand=True)


def _quality_risk_chart(result: object) -> ft.Control:
    records = _read(result, "rows", ())
    points = [
        ck.Bubble(
            _shown(_read(record, "instrument_id")),
            _number(_read(record, "risk_friction")),
            _number(_read(record, "quality")),
        )
        for record in records if isinstance(records, (tuple, list))
        if _number(_read(record, "risk_friction")) is not None
        and _number(_read(record, "quality")) is not None
    ]
    return Well(
        ck.scatter_bubble(
            points,
            x_name="Risk friction (0–10)",
            y_name="Quality (0–10)",
            x_unit="score",
            y_unit="score",
            unavailable_reason=(
                "Unavailable · saved quality and risk-friction values are not present in this screen."
                if not points
                else None
            ),
            empty_title="Quality and risk friction",
        ),
        expand=True,
    )


def _present(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return True
    try:
        return not bool(pd.isna(value))
    except (TypeError, ValueError):
        return True


def _evidence(value: object, fallback: str = "N/A") -> str:
    """Evidence text, or an explicit unavailable marker; a missing value is never shown as zero."""

    if not _present(value):
        return fallback
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item) for item in value) or fallback
    return str(value)


def _fundamentals(frame: pd.DataFrame) -> ft.Control:
    if frame.empty:
        return EmptyState(
            "Fundamentals unavailable",
            "The local clean store has no canonical rows; missing metrics are not inferred or scored.",
            expand=True,
        )
    records = frame.to_dict(orient="records")
    columns = (
        TableColumn("instrument_id", "Instrument Id"),
        *(TableColumn(name, label, numeric=True) for name, label in _FUNDAMENTAL_FIELDS),
        TableColumn("eligibility", "Eligibility"),
        TableColumn("source", "Source"),
        TableColumn("as_of", "As of"),
        TableColumn("sector_status", "Sector-relative"),
    )
    rows = []
    for record in records:
        rows.append(
            {
                "instrument_id": _shown(record.get("instrument_id")),
                **{
                    name: format_number(_number(record.get(name)), decimals=1, unavailable="N/A")
                    for name, _label in _FUNDAMENTAL_FIELDS
                },
                "eligibility": _evidence(record.get("eligibility"), "unavailable"),
                "source": _evidence(record.get("source", record.get("source_authority")), "unavailable"),
                "as_of": _evidence(record.get("as_of_date", record.get("as_of")), "unavailable"),
                "sector_status": _evidence(record.get("sector_relative_status"), "unavailable"),
            }
        )
    detail_columns = (
        TableColumn("instrument_id", "Instrument Id"),
        TableColumn("missing", "Missing"),
        TableColumn("warnings", "Warnings"),
        TableColumn("limitations", "Limitations"),
        TableColumn("value", "Sector value", numeric=True),
        TableColumn("peer", "Sector peer"),
        TableColumn("benchmark", "Sector benchmark"),
        TableColumn("delta", "Sector delta", numeric=True),
        TableColumn("sector_limitation", "Sector limitation"),
        TableColumn("authority", "Executable authority"),
    )
    detail_rows = [
        {
            "instrument_id": _shown(record.get("instrument_id")),
            "missing": _evidence(record.get("missing_fields"), "none recorded"),
            "warnings": _evidence(record.get("warnings"), "none recorded"),
            "limitations": _evidence(record.get("limitations"), "unavailable"),
            "value": _evidence(record.get("sector_relative_value"), "unavailable"),
            "peer": _evidence(record.get("sector_relative_peer"), "unavailable"),
            "benchmark": _evidence(record.get("sector_relative_benchmark"), "unavailable"),
            "delta": _evidence(record.get("sector_relative_delta"), "unavailable"),
            "sector_limitation": _evidence(
                record.get("sector_relative_limitation"), "No sector-relative comparison evidence supplied."
            ),
            "authority": "false",
        }
        for record in records
    ]
    return ft.Column(
        [
            DataTable(columns, rows, empty_title="Fundamentals unavailable"),
            Disclosure("Evidence, limitations and sector-relative detail", DataTable(detail_columns, detail_rows)),
        ],
        spacing=12,
    )


def _fundamental_details(frame: pd.DataFrame) -> str:
    return json.dumps(frame.to_dict(orient="records"), default=str, ensure_ascii=False, indent=2)


def _fixed_income_card(page: ft.Page | None, result: object) -> ft.Control:
    projection = result if isinstance(result, dict) else {}
    rows = projection.get("rows")
    records = [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []
    reason_codes = projection.get("reason_codes")
    reason = (
        ", ".join(_human(item) for item in reason_codes)
        if isinstance(reason_codes, (tuple, list)) and reason_codes
        else "Saved fixed-income expected-return evidence is unavailable."
    )
    available = bool(records)
    first = records[0] if records else {}
    tiles = ft.ResponsiveRow(
        [
            KpiTile(
                "Expected return status",
                _human(projection.get("status")) if available else None,
                reason if not available else "Saved fixed-income projection.",
            ),
            KpiTile(
                "Horizon",
                _shown(projection.get("horizon_days")) if available and projection.get("horizon_days") is not None else None,
                "days" if available else reason,
            ),
            KpiTile(
                "Yield to worst",
                format_percent(_number(first.get("yield_to_worst")), unavailable="—") if available else None,
                "Saved debt-term evidence." if available else reason,
            ),
            KpiTile(
                "Risk-adjusted return",
                format_percent(_number(first.get("risk_adjusted_score")), unavailable="—") if available else None,
                "Research context only." if available else reason,
            ),
        ],
        spacing=16,
        run_spacing=16,
    )
    fields = (
        "instrument_id",
        "yield_to_worst",
        "duration_years",
        "baseline_total_return",
        "risk_adjusted_score",
        "q05",
        "q50",
        "q95",
        "liquidity_status",
        "peer_support",
        "rank",
    )
    labels = (
        "Instrument Id",
        "Yield to worst",
        "Duration",
        "Baseline return",
        "Risk-adjusted return",
        "Q05",
        "Q50",
        "Q95",
        "Liquidity",
        "Peer support",
        "Rank",
    )
    columns = tuple(
        TableColumn(name, label, numeric=index > 0)
        for index, (name, label) in enumerate(zip(fields, labels, strict=True))
    )
    table_rows = []
    for record in records:
        item = {}
        for name, _label in zip(fields, labels, strict=True):
            value = record.get(name)
            if name in {"yield_to_worst", "baseline_total_return", "risk_adjusted_score", "q05", "q50", "q95"}:
                item[name] = format_percent(_number(value), unavailable="—")
            elif name == "duration_years":
                item[name] = format_number(_number(value), decimals=2, unavailable="—")
            else:
                item[name] = _human(value) if name == "liquidity_status" else _shown(value)
        table_rows.append(item)
    table = DataTable(
        columns,
        table_rows,
        empty_title="Fixed-income evidence unavailable",
        empty_reason=reason,
    )
    export_note = Note("Export includes decomposition, peer, distribution and gate evidence.", key="screener.fixed-income.export-status")

    def export_fixed_income(_event: object) -> None:
        if not records:
            export_note.value = "Debt audit export unavailable · no saved fixed-income rows are present."
            if page is not None:
                page.update()
            return
        audit_rows = []
        for record in records:
            audit = {
                key: record.get(key)
                for key in (
                    "instrument_id", "status", "recommendation", "yield_to_worst", "duration_years",
                    "baseline_total_return", "net_total_return", "risk_penalty", "risk_adjusted_score",
                    "forecast_status", "q05", "q50", "q95", "loss_probability", "beat_cash_probability",
                    "beat_benchmark_probability", "liquidity_status", "peer_support", "peer_minimum_support",
                    "peer_level", "peer_status", "robust_percentile", "peer_score_ci_q05", "peer_score_ci_q95",
                    "rank_stability", "rank_stability_seed", "rank", "top_n", "portfolio_fit", "persisted",
                )
            }
            audit["reason_codes"] = ";".join(map(str, record.get("reason_codes", ())))
            for key in ("decomposition", "peer_cohort", "distribution"):
                audit[f"{key}_json"] = json.dumps(record.get(key), sort_keys=True)
            audit["source_lineage"] = ";".join(map(str, record.get("source_lineage", ())))
            audit["analysis_snapshot_id"] = projection.get("analysis_snapshot_id")
            audit["decision_time"] = projection.get("decision_time")
            audit["horizon_days"] = projection.get("horizon_days")
            audit["execution_allowed"] = False
            audit_rows.append(audit)
        exported = export_table(
            "fixed_income_screener",
            pd.DataFrame(audit_rows),
            EXPORTS_DIR / "fixed_income_screener.csv",
        )
        export_note.value = "Debt audit CSV is ready." if exported.ok else "Debt audit export is unavailable."
        if page is not None:
            page.update()

    return GlassCard(
        "Fixed-income expected returns",
        note="Saved debt evidence · advisory context",
        body=[
            tiles,
            table,
            Button.secondary(
                "Export debt audit",
                on_click=export_fixed_income,
                key="screener.fixed-income.export",
            ),
            export_note,
            Disclosure(
                "Fixed-income source details",
                json.dumps(projection, default=str, ensure_ascii=False, indent=2),
            ),
        ],
    )


def _selection_view(page: ft.Page | None, decision_time: str, snapshot: object) -> ft.Control:
    current = [load_top_n_selection(mode="cross_asset", decision_time=decision_time, snapshot=snapshot)]
    initial = current[0] if isinstance(current[0], dict) else {}
    policy = initial.get("policy") if isinstance(initial.get("policy"), dict) else {}
    maximum = _number(policy.get("maximum_top_n")) or 25
    top_n_options = [(str(value), str(value)) for value in range(1, max(1, min(25, int(maximum))) + 1)]
    selected_top_n = str(initial.get("top_n") or policy.get("top_n") or top_n_options[0][0])
    if selected_top_n not in {value for value, _label in top_n_options}:
        selected_top_n = top_n_options[0][0]
    mode_options = [("asset_specific", "Per-asset top N"), ("cross_asset", "Cross-asset portfolio fit")]
    current_mode = str(initial.get("mode") or "cross_asset")
    if current_mode not in {value for value, _label in mode_options}:
        current_mode = "cross_asset"
    mode_control = ft.Dropdown(
        key="screener.selection.mode",
        value=current_mode,
        options=[ft.DropdownOption(value, label) for value, label in mode_options],
        dense=True,
    )
    mode_input = Field("Selection mode", control=mode_control)
    top_n_control = ft.Dropdown(
        key="screener.selection.top-n",
        value=selected_top_n,
        options=[ft.DropdownOption(value, label) for value, label in top_n_options],
        dense=True,
    )
    top_n_input = Field("Top N", control=top_n_control)
    dimensions = [("total", "Total"), ("sector", "Sector"), ("country", "Country"), ("country_sector", "Country × sector")]
    dimension_control = ft.Dropdown(
        key="screener.selection.slice.dimension",
        value="total",
        options=[ft.DropdownOption(value, label) for value, label in dimensions],
        dense=True,
    )
    dimension_input = Field("Slice", control=dimension_control)
    slice_control = ft.Dropdown(
        key="screener.selection.slice.value",
        value="",
        options=[ft.DropdownOption("", "All candidates")],
        dense=True,
    )
    slice_input = Field("Slice value", control=slice_control)
    status = Note("Unavailable · saved selection evidence is not available.", key="screener.selection.status")
    metrics = ft.ResponsiveRow(spacing=16, run_spacing=16)
    funnel_holder = ft.Column(spacing=12)
    winners_holder = ft.Column(spacing=12)
    policy_disclosure = Disclosure(
        "Selection policy and run details",
        json.dumps({"policy": policy, "selection": initial}, default=str, ensure_ascii=False, indent=2),
    )

    def render(result: dict[str, object]) -> None:
        current[0] = result
        raw_slices = result.get("slices")
        slices = [item for item in raw_slices if isinstance(item, dict)] if isinstance(raw_slices, (tuple, list)) else []
        matching = [(index, item) for index, item in enumerate(slices) if item.get("dimension") == dimension_control.value]
        slice_control.options = [
            ft.DropdownOption(str(index), _selection_slice_label(item)) for index, item in matching
        ] or [ft.DropdownOption("", "All candidates")]
        slice_control.value = str(matching[0][0]) if matching else ""
        selected_slice = next((item for index, item in matching if str(index) == slice_control.value), None)
        candidate_rows = result.get("candidate_table")
        candidates = [item for item in candidate_rows if isinstance(item, dict)] if isinstance(candidate_rows, (tuple, list)) else []
        selected_ids = set(selected_slice.get("selected_ids", ())) if selected_slice else set(result.get("selected_ids", ()))
        selected = [item for item in candidates if item.get("instrument_id") in selected_ids]
        reason = str(result.get("reason") or "Saved selection evidence is unavailable.")
        has_result = bool(candidates) and not bool(result.get("reason"))
        status.value = (
            f"Selection {_human(result.get('status'))}."
            if has_result
            else f"Unavailable · {_human(reason)}."
        )
        policy_disclosure.controls[1].content.value = json.dumps(
            {"policy": policy, "selection": result}, default=str, ensure_ascii=False, indent=2
        )
        probabilities = [_number(item.get("selection_probability")) for item in selected]
        confidence = next((value for value in probabilities if value is not None), None) if len(selected) == 1 else None
        marginal_items = [
            _number((item.get("common_metrics") or {}).get("marginal_impact"))
            for item in selected
            if isinstance(item.get("common_metrics"), dict)
        ]
        marginal = marginal_items[0] if len(selected) == 1 and marginal_items else None
        metrics.controls = [
            KpiTile(
                "Selection confidence",
                format_percent(confidence, unavailable="—") if confidence is not None else None,
                "Saved selection probability." if confidence is not None else "No single saved confidence value is available.",
            ),
            KpiTile(
                "Marginal portfolio impact",
                format_number(marginal, decimals=3, unavailable="—") if marginal is not None else None,
                "Saved portfolio-fit evidence." if marginal is not None else "No single saved impact value is available.",
            ),
        ]
        funnel = result.get("exclusion_funnel")
        if isinstance(funnel, dict):
            pairs = list(funnel.items())
        elif isinstance(funnel, (tuple, list)):
            pairs = [tuple(item) for item in funnel if isinstance(item, (tuple, list)) and len(item) == 2]
        else:
            pairs = []
        known_pairs = [(name, value) for name, count in pairs if (value := _number(count)) is not None]
        labels = [_human(name) for name, _value in known_pairs]
        values = [value for _name, value in known_pairs]
        if labels and any(value is not None for value in values):
            funnel_holder.controls = [
                Pipeline(labels, key="screener.selection.pipeline"),
                Well(
                    ck.horizontal_stacked_bar(
                        labels,
                        [[ck.Segment(value or 0, "pos", label)] for label, value in zip(labels, values, strict=True)],
                        x_name="Instruments (count)",
                    ),
                    expand=True,
                ),
            ]
        else:
            funnel_holder.controls = [
                EmptyState(
                    "Exclusion funnel unavailable",
                    "No saved pipeline counts are present for this selection.",
                    expand=True,
                )
            ]
        winner_rows = []
        for item in selected:
            winner_rows.append(
                {
                    "instrument_id": _shown(item.get("instrument_id")),
                    "asset_family": _human(item.get("asset_family")),
                    "peer_rank": _shown(item.get("peer_rank")),
                    "utility_score": format_number(_number(item.get("utility_score")), unavailable="—"),
                    "selection_probability": format_percent(_number(item.get("selection_probability")), unavailable="—"),
                }
            )
        winners_holder.controls = [
            DataTable(
                (
                    TableColumn("instrument_id", "Instrument Id"),
                    TableColumn("asset_family", "Asset family"),
                    TableColumn("peer_rank", "Peer rank", numeric=True),
                    TableColumn("utility_score", "Utility score", numeric=True),
                    TableColumn("selection_probability", "Selection probability", numeric=True),
                ),
                winner_rows,
                empty_title="No winners are supported by this slice or saved run.",
                empty_reason="No saved winners match this selection.",
            )
        ]

    def refresh(_event: object = None) -> None:
        try:
            result = load_top_n_selection(
                mode=str(mode_control.value or "cross_asset"),
                top_n=int(top_n_control.value),
                decision_time=decision_time,
                snapshot=snapshot,
            )
        except (TypeError, ValueError):
            result = {"status": "unavailable", "reason": "top_n_value_invalid"}
        render(result)
        if page is not None:
            page.update()

    def refresh_slice(_event: object = None) -> None:
        render(current[0])
        if page is not None:
            page.update()

    mode_control.on_change = refresh
    top_n_control.on_change = refresh
    dimension_control.on_change = refresh_slice
    slice_control.on_change = refresh_slice
    render(initial)
    return ft.Column(
        [
            GlassCard(
                "Top-N opportunity selection",
                note="Saved point-in-time selection evidence · advisory context",
                body=[
                    ft.ResponsiveRow([mode_input, top_n_input, dimension_input, slice_input], spacing=16, run_spacing=12),
                    status,
                    metrics,
                    policy_disclosure,
                ],
            ),
            GlassCard("Exclusion funnel", body=[funnel_holder]),
            GlassCard("Winners", body=[winners_holder]),
        ],
        spacing=16,
    )


def _selection_slice_label(item: dict[str, object]) -> str:
    value = item.get("value")
    if isinstance(value, (tuple, list)):
        return " × ".join(str(part) for part in value)
    return "All candidates" if value is None else str(value)


def _lineage(query: object) -> str:
    return json.dumps(
        {
            "as_of": _read(query, "as_of"),
            "universe_revision": _read(query, "universe_revision"),
            "query_checksum": _read(query, "checksum"),
            "execution_allowed": False,
        },
        default=str,
        ensure_ascii=False,
        indent=2,
    )


def screener_page(page: ft.Page | None, state: AppState, *, _deferred: bool = False) -> PageView:
    """Render reproducible local screens and saved selection evidence."""

    if not _deferred and page is not None and (isinstance(page, ft.Page) or bool(getattr(page, "_shell_defer_render", False))):
        placeholder = ft.Container(content=Note("Loading screener evidence..."), expand=True)
        placeholder.data = {"shell.deferred-update": lambda: screener_page(page, state, _deferred=True)}
        return PageView(
            PageChrome(
                "Fundamentals Screener",
                "Reproducible local screens on loaded evidence \\u00b7 context only",
            ),
            placeholder,
        )

    frame = load_fundamental_evidence(FUNDAMENTAL_CLEAN_PATH)
    frame = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if "instrument_id" not in frame.columns:
        frame = pd.DataFrame()
    if not frame.empty:
        frame = latest_fundamental_rows(frame)
    snapshot = getattr(state, "snapshot", None)
    screen_frame = build_screen_rows(snapshot, frame) if snapshot is not None else pd.DataFrame()
    available_fields = sorted(str(field) for field in screen_frame.columns)
    initial_field = "region" if "region" in available_fields else (available_fields[0] if available_fields else "")
    initial_sort = "score" if "score" in available_fields else initial_field
    filters: list[ScreenFilter] = []
    query = [query_for_snapshot(snapshot, screen_frame)]
    result = [run_screen(screen_frame, query[0])]
    status = Note(
        f"{result[0].total_matched} of {result[0].total_input} local instruments shown."
        if result[0].total_input
        else "Unavailable · no local instruments are present in the current evidence screen.",
        key="screener.result.status",
    )
    filter_summary = Note("No active filters.", key="screener.filter.summary")
    filter_chips = ft.Row(spacing=8, wrap=True)
    results_holder = ft.Column(spacing=12, key="screener.results")
    distribution_holder = ft.Column(spacing=12)
    quality_holder = ft.Column(spacing=12)

    field_input, field_control = _field(
        "Filter field",
        "screener.filter.field",
        [(value, _human(value)) for value in available_fields],
        initial_field,
    )
    operator_options = [("eq", "equals"), ("min", "minimum"), ("max", "maximum")]
    operator_input, operator_control = _field(
        "Operator", "screener.filter.operator", operator_options, "eq"
    )
    value_input = _text_field("Value", "screener.filter.value")
    sort_input, sort_control = _field(
        "Sort field",
        "screener.sort.field",
        [(value, _human(value)) for value in available_fields],
        initial_sort,
        columns=6,
    )
    direction_state = {"value": "Descending"}
    results_card_ref: dict[str, ft.Control | None] = {"card": None}
    saved_name_input = _text_field("Saved screen name", "screener.saved.name", columns=6)

    def render_screen() -> None:
        sort_field = str(sort_control.value or "")
        descending = direction_state["value"] == "Descending"
        try:
            query[0] = query_for_snapshot(
                snapshot,
                screen_frame,
                filters=tuple(filters),
                sort=(ScreenSort(sort_field, descending=descending),) if sort_field else (),
            )
            result[0] = run_screen(screen_frame, query[0])
            message = (
                f"{result[0].total_matched} of {result[0].total_input} local instruments shown."
                if result[0].total_input
                else "Unavailable · no local instruments are present in the current evidence screen."
            )
            status.value = message
        except (TypeError, ValueError):
            status.value = "Screen unavailable · the selected field or value is not supported by this evidence."
        filter_summary.value = (
            "No active filters."
            if not filters
            else "Active filters: " + "; ".join(f"{item.field} {item.operator} {item.value}" for item in filters)
        )
        filter_chips.controls = []
        for index, item in enumerate(filters):
            chip = Tag(f"{_human(item.field)} {item.operator} {_shown(item.value)} ×", "mute")
            chip.on_click = lambda _event, position=index: remove_filter(position)
            chip.ink = True
            filter_chips.controls.append(chip)
        results_holder.controls = [
            Note(
                f"{result[0].total_matched} of {result[0].total_input} local instruments shown."
                if result[0].total_input
                else "Unavailable · no local instruments are present in the current evidence screen."
            ),
            _screen_table(result[0], sort_field, descending, sort_changed),
            Disclosure("As-of, universe revision and query checksum", _lineage(query[0])),
        ]
        distribution_holder.controls = [_distribution(result[0], sort_field)]
        quality_holder.controls = [_quality_risk_chart(result[0])]
        results_card = results_card_ref["card"]
        if results_card is not None:
            note_control = results_card.data.get("note_control")
            if isinstance(note_control, ft.Text):
                note_control.value = (
                    f"{result[0].total_matched} of {result[0].total_input} local instruments shown"
                    if result[0].total_input
                    else "Unavailable · no local instruments are present in the current evidence screen."
                )
        if page is not None:
            page.update()

    def sort_changed(field: str, descending: bool) -> None:
        sort_control.value = field
        direction_state["value"] = "Descending" if descending else "Ascending"
        render_screen()

    def add_filter(_event: object) -> None:
        filter_field = str(field_control.value or "")
        raw_value = str(value_control.value or "").strip()
        try:
            filters.append(ScreenFilter(filter_field, str(operator_control.value or "eq"), raw_value))
            value_control.value = ""
            render_screen()
        except ValueError as exc:
            status.value = f"Filter not applied · {exc}"
            if page is not None:
                page.update()

    def remove_filter(index: int) -> None:
        if 0 <= index < len(filters):
            filters.pop(index)
            render_screen()

    # The input controls are inside kit Fields; the keyed controls retain their existing contracts.
    value_control = next(
        control
        for control in _walk(value_input)
        if isinstance(control, ft.TextField)
    )
    saved_name_control = next(
        control
        for control in _walk(saved_name_input)
        if isinstance(control, ft.TextField)
    )

    def clear_filters(_event: object) -> None:
        filters.clear()
        render_screen()

    def run_query(_event: object) -> None:
        render_screen()

    def save_query(_event: object) -> None:
        try:
            save_screen(str(saved_name_control.value or ""), query[0])
            status.value = "Saved local screen revision."
        except (OSError, ValueError):
            status.value = "Screen revision could not be saved."
        if page is not None:
            page.update()

    def load_query(_event: object) -> None:
        try:
            loaded = load_screen(str(saved_name_control.value or ""))
            filters[:] = list(loaded.filters)
            if loaded.sort:
                sort_control.value = loaded.sort[0].field
                direction_state["value"] = "Descending" if loaded.sort[0].descending else "Ascending"
                direction_control.value = direction_state["value"].casefold()
            render_screen()
            status.value = "Loaded latest saved screen."
        except (OSError, ValueError):
            status.value = "Saved screen could not be loaded."
        if page is not None:
            page.update()

    def export_results(_event: object) -> None:
        try:
            destination = EXPORTS_DIR / "screener_results.csv"
            exported = export_screen_csv(result[0], query[0], destination)
            state.last_export_path = exported
            state.last_message = "Screener CSV exported."
            status.value = state.last_message
        except (OSError, ValueError):
            status.value = "Screener CSV export is unavailable."
        if page is not None:
            page.update()

    value_control = next(control for control in _walk(value_input) if isinstance(control, ft.TextField))
    field_control.on_change = None
    operator_control.on_change = None
    sort_control.on_change = lambda _event: render_screen()
    def change_direction(value: str) -> None:
        direction_state["value"] = value
        direction_control.value = value.casefold()
        render_screen()

    direction_control = Segmented(
        ["Descending", "Ascending"],
        direction_state["value"],
        on_change=change_direction,
        key="screener.sort.direction",
    )
    direction_control.value = direction_state["value"].casefold()

    render_screen()
    screen_card = GlassCard(
        "Reproducible local screen",
        note="Loaded local evidence · context only",
        body=[
            ft.ResponsiveRow([field_input, operator_input, value_input], spacing=16, run_spacing=12),
            ft.Row(
                [
                    Button.secondary("Add filter", on_click=add_filter, key="screener.filter.add"),
                    ft.TextButton("Clear filters", key="screener.filter.clear", on_click=clear_filters),
                ],
                spacing=8,
                wrap=True,
            ),
            ft.ResponsiveRow(
                [
                    sort_input,
                    ft.Container(
                        content=ft.Column(
                            [
                                Note("DIRECTION"),
                                direction_control,
                            ],
                            spacing=4,
                            tight=True,
                        ),
                        col={"xs": 12, "md": 6},
                    ),
                ],
                spacing=16,
                run_spacing=12,
            ),
            filter_summary,
            filter_chips,
            ft.ResponsiveRow([saved_name_input], spacing=16, run_spacing=12),
            ft.Row(
                [
                    Button.secondary("Save revision", on_click=save_query, key="screener.saved.save"),
                    Button.secondary("Load latest", on_click=load_query, key="screener.saved.load"),
                    Button.secondary("Export CSV", on_click=export_results, key="screener.export.csv"),
                    Button.primary("Run screen", on_click=run_query, key="screener.run"),
                ],
                spacing=8,
                wrap=True,
            ),
            status,
        ],
    )
    screen_results_card = GlassCard(
        "Screen results",
        note=f"{result[0].total_matched} of {result[0].total_input} local instruments shown",
        body=[results_holder],
    )
    results_card_ref["card"] = screen_results_card
    distribution_card = GlassCard(f"Distribution of {_human(initial_sort)}", body=[distribution_holder])
    quality_card = GlassCard("Quality vs. risk friction", body=[quality_holder])

    fundamentals_card = GlassCard(
        "Instrument fundamentals",
        note="Five canonical sections · local evidence",
        body=[
            _fundamentals(frame),
            Note("executable_authority=false | fundamentals are not an action or broker authority"),
            Note("Missing values remain unavailable and are not inferred or scored."),
            Disclosure("Fundamental source and row details", _fundamental_details(frame)),
        ],
    )
    try:
        as_of = getattr(getattr(snapshot, "data_report", None), "as_of_date", None)
        decision_time = f"{as_of}T23:59:59+00:00" if as_of is not None else ""
        fixed_income = load_fixed_income_screener(decision_time=decision_time)
    except (OSError, TypeError, ValueError):
        fixed_income = {"status": "unavailable", "reason_codes": ["saved_fixed_income_evidence_unavailable"], "rows": []}
    fixed_income_card = _fixed_income_card(page, fixed_income)
    selection_body = _selection_view(page, decision_time, snapshot)

    view_state = {"selected": "Screen"}
    body = ft.Column(
        [
            ft.Column([screen_card, screen_results_card, distribution_card, quality_card], spacing=16, visible=True),
            ft.Column([selection_body], spacing=16, visible=False),
            ft.Column([fixed_income_card, fundamentals_card], spacing=16, visible=False),
        ],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    def change_view(selected: str) -> None:
        view_state["selected"] = selected
        for panel, name in zip(body.controls, ("Screen", "Top-N", "Fixed income"), strict=True):
            panel.visible = name == selected
        if page is not None:
            page.update()

    chrome = PageChrome(
        "Fundamentals Screener",
        "Reproducible local screens on loaded evidence · context only",
        [SegmentGroup("screener-view", ["Screen", "Top-N", "Fixed income"], view_state["selected"], change_view)],
    )
    return PageView(chrome=chrome, body=body)


def _walk(control: ft.Control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


__all__ = ["screener_page"]
