"""Canonical score and gate evidence page."""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    GateCheck,
    GlassCard,
    KpiStrip,
    ListRow,
    Note,
    ScoreBar,
    TableColumn,
    Tag,
    VerdictRing,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count, format_date, format_number
from etf_cockpit.app.state import AppState
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.instrument_detail_view import (
    _latest_operational_row,
    _operational_evidence_panel,
)
from etf_cockpit.application.ui_facade import build_simple_instrument_scores
from etf_cockpit.app.components.simple_scores import simple_score_grouped_sections  # noqa: F401

_MISSING = "\u2014"


def _read(value: object, key: str, fallback: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, fallback)
    return getattr(value, key, fallback)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _shown_number(value: object, decimals: int = 1) -> str:
    return format_number(_number(value), decimals=decimals, unavailable=_MISSING)


def _tier(score: object) -> str:
    value = str(_read(score, "source_group", "") or "").casefold()
    if "sparebanken" in value:
        return "Sparebanken"
    if "secondary" in value or "yahoo" in value:
        return "Secondary"
    return "Primary"


def _label(score: object) -> tuple[str, str]:
    value = str(_read(score, "final_label", "") or "").casefold()
    if "strong" in value:
        return "Strong", "ok"
    if "positive" in value:
        return "Good", "ok"
    if "watch" in value or "mixed" in value or "hold" in value:
        return "Watch", "warn"
    if "review" in value or "manual" in value:
        return "Review", "bad"
    return "Review", "mute"


def _action(score: object) -> tuple[str, str]:
    value = str(_read(score, "final_action", "") or "").casefold()
    labels = {
        "buy": ("Buy", "ok"),
        "add": ("Add", "ok"),
        "add_candidate": ("Add candidate", "ok"),
        "hold": ("Hold", "mute"),
        "trim": ("Trim", "warn"),
        "trim_candidate": ("Trim candidate", "warn"),
        "sell": ("Sell", "bad"),
        "no_trade": ("No trade", "mute"),
        "manual_review": ("Manual review", "warn"),
        "watchlist": ("Watchlist", "mute"),
    }
    return labels.get(value, ("Unavailable", "bad"))


def _scores(snapshot: object) -> list[object]:
    if snapshot is None:
        return []
    config = getattr(snapshot, "config", None)
    signals = getattr(snapshot, "signals", ())
    forecasts = getattr(snapshot, "forecasts", pd.DataFrame())
    prices = getattr(snapshot, "prices", pd.DataFrame())
    try:
        reference = context_from_snapshot(
            snapshot,
            purpose="comparison",
            analysis_id=f"signals:{getattr(snapshot, 'universe_revision', 'unknown')}",
        )
    except (AttributeError, TypeError, ValueError):
        reference = None
    return list(
        build_simple_instrument_scores(
            config,
            signals,
            forecasts,
            prices,
            benchmark_data_id=getattr(reference, "benchmark_data_id", None),
            benchmark_reference=getattr(reference, "projection", None),
            benchmark_registry=getattr(reference, "registry", None),
            reference_identity=getattr(reference, "identity", None),
            peer_member_ids=getattr(reference, "peer_member_ids", ()),
            cash_observation_time=getattr(snapshot, "benchmark_reference_decision_time", None),
        )
    )


def _forecast_source(snapshot: object) -> str:
    forecasts = getattr(snapshot, "forecasts", None)
    if not isinstance(forecasts, pd.DataFrame) or forecasts.empty or "source_file" not in forecasts.columns:
        return "none loaded"
    value = forecasts["source_file"].iloc[0]
    return Path(str(value)).name if value is not None and str(value).strip() else "none loaded"


def _counts(scores: Sequence[object]) -> dict[str, int]:
    return {
        "strong": sum(_label(score)[0] == "Strong" for score in scores),
        "positive": sum(_label(score)[0] == "Good" for score in scores),
        "watch": sum(_label(score)[0] == "Watch" for score in scores),
        "review": sum(_label(score)[0] == "Review" for score in scores),
    }


def _matches_tier(score: object, selected: str) -> bool:
    return selected == "All" or _tier(score) == selected


def _matches_label(score: object, selected: str) -> bool:
    return selected == "All" or _label(score)[0] == selected


def _requested_tier(page: object | None) -> str:
    query = parse_qs(urlsplit(str(getattr(page, "route", "") or "")).query)
    requested = query.get("tier", ["All"])[0]
    return requested if requested in {"All", "Primary", "Secondary", "Sparebanken"} else "All"


def _scorecard_reason(score: object) -> str | None:
    if _tier(score) != "Sparebanken" or str(_read(score, "final_label", "") or "").casefold() != "scorecard_owned":
        return None
    return str(_read(score, "one_line_reason", "") or "")


def _score_rows(scores: Sequence[object], on_scorecard_click=None) -> list[dict[str, object]]:
    rows = []
    for index, score in enumerate(scores, start=1):
        label, kind = _label(score)
        action, action_kind = _action(score)
        components = _read(score, "components", ()) or ()
        valid_components = sum(
            _number(_read(component, "score_10")) is not None
            for component in components
        )
        warning_value = _read(score, "warnings")
        warning_count = len(warning_value) if isinstance(warning_value, Sequence) else None
        warning_cell: object = _MISSING
        if warning_count is not None:
            warning_cell = Tag(str(warning_count), "warn" if warning_count else "mute")
        reason = _scorecard_reason(score)
        if reason:
            score_cell: ft.Control = Tag("Scorecard", "mute")
            score_cell.tooltip = reason
            score_cell.on_click = on_scorecard_click
        else:
            score_cell = ScoreBar(_number(_read(score, "final_score_10")))
        rows.append(
            {
                "rank": format_count(index),
                "instrument": (
                    str(_read(score, "display_id", "") or _MISSING),
                    str(_read(score, "name", "") or _MISSING),
                ),
                "score": score_cell,
                "label": Tag(label, kind),
                "action": Tag(action, action_kind),
                "quality": _shown_number(_read(score, "evidence_quality_10")),
                "risk_friction": _shown_number(_read(score, "risk_friction_10")),
                "components": f"{valid_components}/10 valid"
                if components
                else _MISSING,
                "warnings": warning_cell,
            }
        )
    return rows


def _score_table(scores: Sequence[object], selected: object | None, on_select, on_scorecard_click=None) -> ft.Control:
    rows = _score_rows(scores, on_scorecard_click)
    selected_index = next(
        (index for index, score in enumerate(scores) if score is selected),
        None,
    )
    if not scores:
        return DataTable(
            [
                TableColumn("rank", "#", numeric=True),
                TableColumn("instrument", "Instrument"),
                TableColumn("score", "Score", numeric=True),
                TableColumn("label", "Label"),
                TableColumn("action", "Action"),
                TableColumn("quality", "Quality", numeric=True),
                TableColumn("risk_friction", "Risk/friction", numeric=True),
                TableColumn("components", "Components"),
                TableColumn("warnings", "Warnings", numeric=True),
            ],
            [],
            empty_title="Unavailable",
            empty_reason="No canonical score rows are available in this snapshot.",
        )
    return DataTable(
        [
            TableColumn("rank", "#", numeric=True),
            TableColumn("instrument", "Instrument"),
            TableColumn("score", "Score ▼", numeric=True, sortable=False),
            TableColumn("label", "Label"),
            TableColumn("action", "Action"),
            TableColumn("quality", "Quality", numeric=True),
            TableColumn("risk_friction", "Risk/friction", numeric=True),
            TableColumn("components", "Components"),
            TableColumn("warnings", "Warnings", numeric=True),
        ],
        rows,
        selected_index=selected_index,
        on_select=on_select,
        empty_title="Unavailable",
        empty_reason="No canonical score rows are available in this snapshot.",
    )


def _score_detail(score: object | None, page: ft.Page | None, state: object) -> ft.Control:
    if score is None:
        return GlassCard(
            "Score details",
            body=EmptyState(
                "Unavailable",
                "Select a score row to inspect its stored components and gates.",
            ),
            expand=True,
        )
    instrument_id = str(_read(score, "display_id", "") or _MISSING)
    tier = _tier(score)
    ticker = str(_read(score, "yahoo_symbol", "") or _MISSING)
    latest_date = format_date(_read(score, "latest_date"), unavailable=_MISSING)
    canonical = _read(score, "canonical_score")
    component_specs = (
        ("attractiveness_10", "Attractiveness"),
        ("expected_return_10", "Expected return"),
        ("risk_implementation_10", "Risk/implementation"),
        ("evidence_confidence_10", "Evidence confidence"),
        ("coverage", "Coverage"),
        ("model_authority_10", "Model authority"),
        ("calibration_10", "Calibration"),
        ("backtest_trust_10", "Backtest"),
    )
    components = [
        ft.Row(
            [
                Note(label),
                ScoreBar(_number(_read(canonical, field))),
            ],
            spacing=8,
        )
        for field, label in component_specs
    ]
    authority = _read(score, "authority_decision")
    gates = _read(authority, "gates", ()) or ()
    gate_controls = []
    for gate in gates:
        gate_id = str(_read(gate, "gate_id", "Gate"))
        passed = _read(gate, "passed")
        gate_controls.append(
            GateCheck(
                passed if isinstance(passed, bool) else None,
                gate_id.replace("_", " ").title(),
                "Gate passed" if passed is True else "Review required" if passed is False else "Evaluation unavailable",
            )
        )
    fit_fields = (
        ("strategy_template_label", "Strategy template"),
        ("benchmark_id", "Benchmark"),
        ("benchmark_beta", "Beta"),
        ("benchmark_correlation", "Corr"),
        ("alpha_proxy", "Alpha proxy"),
        ("crowding_average_peer_correlation", "Crowding"),
        ("gross_edge", "Gross edge"),
        ("estimated_cost_bps", "Cost"),
        ("net_edge", "Net edge"),
        ("edge_cost_ratio", "Edge/cost"),
        ("cost_scenario", "Cost scenario"),
        ("sector_relative", "Sector-relative"),
        ("theme_relative", "Theme-relative"),
        ("evidence_maturity_label", "Maturity"),
        ("evidence_sample_days", "Sample"),
    )
    fit_rows = [
        {
            "field": label,
            "value": _shown_number(_read(score, field))
            if isinstance(_read(score, field), (int, float))
            else str(_read(score, field) or _MISSING),
        }
        for field, label in fit_fields
    ]
    formula_payload = {
        "canonical_score": _read(score, "canonical_score"),
        "formula_version": _read(canonical, "formula_version"),
        "formula_checksum": _read(canonical, "formula_checksum"),
        "source_vintage_hash": _read(canonical, "source_vintage_hash"),
    }

    def open_detail(_event: ft.ControlEvent | None = None) -> None:
        try:
            state.selected_etf = instrument_id
        except (AttributeError, TypeError):
            pass
        if page is not None and callable(getattr(page, "go", None)):
            page.go(f"/instrument/{instrument_id}")

    def open_gates(_event: ft.ControlEvent | None = None) -> None:
        if page is not None and callable(getattr(page, "go", None)):
            page.go("/help#manual_review")

    body: list[ft.Control] = [
        ft.Row(
            [
                VerdictRing(
                    _number(_read(score, "final_score_10")) * 10
                    if _number(_read(score, "final_score_10")) is not None
                    else None
                ),
                Tag(*_label(score)),
                Tag(*_action(score)),
            ],
            spacing=8,
        ),
        *components,
        *(gate_controls or [GateCheck(None, "Gate results", "Gate evaluation is unavailable.")]),
        DataTable(
            [TableColumn("field", "Portfolio fit"), TableColumn("value", "Value")],
            fit_rows,
            empty_title="Unavailable",
            empty_reason="Portfolio-fit evidence is unavailable.",
        ),
        Note(str(_read(score, "one_line_reason", "") or "Score reasons are unavailable.")),
        Note("Momentum, drawdown, volatility, liquidity and spread details are in the evidence disclosure."),
        Disclosure("Formula and source-vintage details", json.dumps(formula_payload, default=str, ensure_ascii=False)),
        Disclosure(
            "Gate details",
            json.dumps(
                [
                    {
                        "gate_id": _read(gate, "gate_id"),
                        "passed": _read(gate, "passed"),
                        "reason": _read(gate, "reason"),
                    }
                    for gate in gates
                ],
                default=str,
                ensure_ascii=False,
            ),
        ),
        ft.Row(
            [
                Button.primary(
                    "Open instrument detail",
                    on_click=open_detail,
                    key=f"dashboard.score-row-detail.{instrument_id}",
                ),
                Button.secondary(
                    "View all gates",
                    on_click=open_gates,
                    key="authority-gates.view-all",
                ),
            ],
            spacing=8,
            wrap=True,
        ),
    ]
    return GlassCard(
        f"Score details · {instrument_id}",
        note=f"{tier} · Yahoo {ticker} · latest {latest_date}",
        body=body,
        expand=True,
    )


def _bubble_chart(scores: Sequence[object]) -> tuple[ft.Control, str]:
    points = []
    unconfirmed = 0
    for score in scores:
        confidence = _number(
            _read(_read(score, "canonical_score"), "evidence_confidence_10")
        )
        final_score = _number(_read(score, "final_score_10"))
        coverage = _number(
            _read(_read(score, "canonical_score"), "coverage")
        )
        points.append(
            ck.Bubble(
                str(_read(score, "display_id", "") or _MISSING),
                confidence,
                final_score,
                size=coverage,
                group=_label(score)[0],
            )
        )
        if confidence is not None and final_score is not None and final_score >= 6 and confidence < 3:
            unconfirmed += 1
    if scores:
        insight = (
            f"{unconfirmed} instruments score 6 or more with evidence confidence below 3; "
            "treat them as unconfirmed."
        )
    else:
        insight = "No score points are available."
    return (
        ck.scatter_bubble(
            points,
            groups=[
                ("Strong", theme.GREEN),
                ("Good", theme.LIGHT_GREEN),
                ("Watch", theme.AMBER),
                ("Review", theme.RED),
            ],
            x_name="Evidence confidence (0–10)",
            y_name="Score (0–10)",
            x_unit="score",
            y_unit="score",
            unavailable_reason="No canonical score points are available.",
            insight=insight,
        ),
        insight,
    )


def _signals_operational_evidence(scores: list[object], report: object) -> ft.Control:
    """Render exact-instrument operational evidence and keep unavailable states explicit."""

    evidence_fields = (
        "evidence_status", "evidence_reason", "signal_date", "signal_timestamp",
        "execution_date", "execution_timestamp", "decision_price", "decision_price_basis",
        "decision_price_source_identity", "next_open_reference_price", "next_open_reference_basis",
        "next_open_source_identity", "next_period_reference_price", "next_period_reference_basis",
        "next_period_source_identity", "close_to_next_open_gap", "open_gap_warning",
        "open_gap_warning_threshold", "price_provenance", "arrival_price_assumption",
        "execution_delay_sessions", "same_bar_execution_avoided", "observed_range_spread_proxy",
        "spread_proxy", "cost_spread_assumption_bps", "cost_spread_assumption_source",
        "estimated_cost_bps", "estimated_cost_bps_source", "session_state", "auction_state",
        "expiry_state", "order_lifecycle", "fill_source", "paper_fill_source",
        "reconciled_fill_source", "execution_allowed",
    )

    def display(value: object) -> str:
        return "unavailable" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)

    rows: list[ft.Control] = []
    details: list[str] = []
    scoped_scores = [score for score in scores if str(getattr(score, "display_id", "")).strip()]
    for index, score in enumerate(scoped_scores):
        instrument_id = str(getattr(score, "display_id", "")).strip()
        projection = _operational_evidence_panel(report, instrument_id)
        if projection.get("status") == "available":
            latest = _latest_operational_row(projection.get("rows", []))
            status = display(latest.get("evidence_status", "available"))
            reason = display(latest.get("evidence_reason", getattr(score, "one_line_reason", "Operational evidence is available.")))
            kind = "ok" if status.casefold() in {"available", "valid", "complete"} else "warn"
            rows.append(ListRow(theme.GREEN if kind == "ok" else theme.AMBER, instrument_id, reason, tag=Tag(status, kind), last=index == len(scoped_scores) - 1))
            details.append(f"{instrument_id}: " + "; ".join(f"{field}={display(latest.get(field))}" for field in evidence_fields))
        else:
            reason = display(projection.get("message", "exact operational evidence unavailable"))
            rows.append(ListRow(theme.MUTED, instrument_id, reason, tag=Tag("unavailable", "mute"), last=index == len(scoped_scores) - 1))
            unavailable_fields = "; ".join(
                f"{field}=unavailable" for field in evidence_fields if field not in {"evidence_reason", "execution_allowed"}
            )
            details.append(
                f"{instrument_id}: unavailable/context-only; {unavailable_fields}; evidence_reason={reason}; "
                "execution_allowed=false; aggregate aliases are excluded"
            )
    if not rows:
        rows = [ListRow(theme.MUTED, "Instrument-scoped operational evidence unavailable", "No instrument score rows are available.", last=True)]
    return GlassCard(
        "Operational evidence",
        note="Exact-instrument backtest evidence · context only",
        body=[
            *rows,
            Disclosure(
                "Instrument operational details",
                "\n".join(details) if details else "Instrument-scoped operational evidence unavailable; execution_allowed=false",
            ),
        ],
    )


def _body(
    scores: Sequence[object],
    selected: object | None,
    state: object,
    page: ft.Page | None,
    forecast_source: str,
    on_select,
    on_scorecard_click=None,
) -> ft.Control:
    counts = _counts(scores)
    missing = not scores
    formula_version = next(
        (
            str(_read(_read(score, "canonical_score"), "formula_version"))
            for score in scores
            if _read(_read(score, "canonical_score"), "formula_version")
        ),
        "none loaded",
    )
    forecast_label = str(forecast_source or "none loaded")
    items = [
        ("Strong evidence", str(counts["strong"]) if not missing else None, "score, quality and friction all pass", None),
        ("Positive evidence", str(counts["positive"]) if not missing else None, "usable evidence with enough quality", None),
        ("Watch/mixed", str(counts["watch"]) if not missing else None, "mixed or context-only evidence", None),
        ("Manual review", str(counts["review"]) if not missing else None, "blocked, weak or low-quality evidence", "neg" if counts["review"] else None),
    ]
    strip = KpiStrip(
        "Canonical scores",
        f"{len(scores)} instruments scored" if not missing else "Unavailable",
        f"formula {formula_version} · forecast source {forecast_label}",
        items,
    )
    groups = []
    for tier in ("Primary", "Secondary", "Sparebanken"):
        count = sum(_tier(score) == tier for score in scores)
        if count:
            groups.append(ListRow("info", f"{tier} tier", f"{count} instruments", last=False))
    scores_card = GlassCard(
        "All stock and ETF scores",
        note="grouped by tier · click a row for details",
        body=[
            *groups,
            _score_table(scores, selected, on_select, on_scorecard_click),
            Disclosure(
                "Formula and forecast source",
                json.dumps(
                    {
                        "formula_version": next(
                            (_read(_read(score, "canonical_score"), "formula_version") for score in scores),
                            None,
                        ),
                        "forecast_source": forecast_source,
                    },
                    default=str,
                    ensure_ascii=False,
                ),
            ),
        ],
        expand=True,
    )
    details = _score_detail(selected, page, state)
    chart, insight = _bubble_chart(scores)
    scatter = GlassCard(
        "Score vs. evidence confidence",
        note="each dot is an instrument",
        insight=insight,
        body=Well(chart, expand=True),
        expand=True,
    )
    operational = _signals_operational_evidence(
        list(scores),
        getattr(getattr(state, "snapshot", None), "backtest", None),
    )
    scores_card.col = {"xs": 12, "lg": 8}
    details.col = {"xs": 12, "lg": 4}
    scatter.col = {"xs": 12, "lg": 8}
    return ft.Column(
        [
            strip,
            ft.ResponsiveRow([scores_card, details], spacing=16, run_spacing=16),
            ft.ResponsiveRow([scatter], spacing=16, run_spacing=16),
            operational,
        ],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def signals_page(page: ft.Page | None, state: AppState, *, _deferred: bool = False) -> PageView:
    if not _deferred and page is not None and (
        isinstance(page, ft.Page)
        or bool(getattr(page, "_shell_defer_render", False))
        or callable(getattr(page, "run_thread", None))
    ):
        placeholder = ft.Container(content=Note("Loading score evidence..."), expand=True)
        placeholder.data = {
            "shell.deferred-update": lambda: signals_page(page, state, _deferred=True)
        }
        return PageView(
            PageChrome(
                "Scores",
                "Canonical score components, gates and reasons \u00b7 research context, not instructions",
            ),
            placeholder,
        )
    scores = _scores(getattr(state, "snapshot", None))
    snapshot = getattr(state, "snapshot", None)
    forecast_source = _forecast_source(snapshot)
    filter_state: dict[str, object] = {"tier": _requested_tier(page), "label": "All", "selected": None}
    body_holder = ft.Container(key="signals.body", expand=True)
    generation = [0]
    render_lock = threading.Lock()
    pending_render: list[int | None] = [None]
    render_worker = [False]

    def render_body(expected: int | None = None) -> None:
        filtered = [
            score
            for score in scores
            if _matches_tier(score, str(filter_state["tier"]))
            and _matches_label(score, str(filter_state["label"]))
        ]
        current = filter_state.get("selected")
        if current not in filtered:
            current = filtered[0] if filtered else None
        filter_state["selected"] = current

        def select_row(index: int) -> None:
            if 0 <= index < len(filtered):
                filter_state["selected"] = filtered[index]
                render()

        def open_sparebanken(_event: object) -> None:
            if page is not None and callable(getattr(page, "go", None)):
                page.go("/signals?tier=Sparebanken")

        on_scorecard_click = open_sparebanken if page is not None and callable(getattr(page, "go", None)) else None
        body = _body(filtered, current, state, page, forecast_source, select_row, on_scorecard_click)
        if expected is not None and expected != generation[0]:
            return
        body_holder.content = body
        if callable(getattr(body_holder, "update", None)):
            try:
                body_holder.update()
            except Exception:
                if page is not None and callable(getattr(page, "update", None)):
                    page.update()

    def render() -> None:
        if page is None or (not isinstance(page, ft.Page) and not hasattr(page, "views")):
            render_body()
            return
        generation[0] += 1
        expected = generation[0]
        body_holder.content = Note("Updating score evidence...")
        if callable(getattr(body_holder, "update", None)):
            try:
                body_holder.update()
            except Exception:
                if callable(getattr(page, "update", None)):
                    page.update()
        with render_lock:
            pending_render[0] = expected
            if render_worker[0]:
                return
            render_worker[0] = True
        threading.Thread(target=render_pending, name="signals-segment-render", daemon=True).start()

    def render_pending() -> None:
        while True:
            with render_lock:
                expected = pending_render[0]
                pending_render[0] = None
                if expected is None:
                    render_worker[0] = False
                    return
            render_body(expected)

    def change_tier(value: str) -> None:
        filter_state["tier"] = value
        render()

    def change_label(value: str) -> None:
        filter_state["label"] = value
        render()

    chrome = PageChrome(
        "Scores",
        "Canonical score components, gates and reasons \u00b7 research context, not instructions",
        [
            SegmentGroup(
                "score-tier",
                ["All", "Primary", "Secondary", "Sparebanken"],
                str(filter_state["tier"]),
                on_change=change_tier,
            ),
            SegmentGroup(
                "score-label",
                ["All", "Strong", "Good", "Watch", "Review"],
                str(filter_state["label"]),
                on_change=change_label,
            ),
        ],
    )
    deferred = not _deferred and page is not None and (
        isinstance(page, ft.Page) or bool(getattr(page, "_shell_defer_render", False))
    )
    if not deferred:
        render_body()
    else:
        body_holder.content = Note("Loading score evidence...")
        body_holder.data = {"shell.deferred-update": render_body}
    return PageView(chrome, body_holder)


__all__ = ["signals_page"]
