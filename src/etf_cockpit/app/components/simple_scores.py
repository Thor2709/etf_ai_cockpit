from __future__ import annotations

import math

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.application.ui_facade import SCORE_LEGEND, SimpleInstrumentScore, SimpleScoreComponent, group_simple_scores, load_score_history_summary


def _is_crowding_warning_state(value: object) -> bool:
    """Return whether a crowding state represents an explicit warning."""

    state = "" if value is None else str(value).strip().casefold()
    if not state or state.startswith("no_"):
        return False
    if state in {"n/a", "na", "none", "null", "nan", "<na>", "unavailable", "partial", "pending"}:
        return False
    return not state.endswith("_unavailable")


def simple_score_legend() -> ft.Control:
    return ft.Row(
        [evidence_chip(label.split(":", 1)[0], label.split(":", 1)[1].strip(), _legend_colour(label)) for label in SCORE_LEGEND],
        spacing=8,
        wrap=True,
    )


def simple_score_tiles(scores: list[SimpleInstrumentScore], *, max_items: int | None = None) -> ft.Control:
    if not scores:
        return panel(
            ft.Column(
                [
                    section_header("Scores", "No instruments are available yet."),
                    ft.Text("Refresh yfinance data, then run algorithms and forecasting models.", color=theme.MUTED),
                ],
                spacing=8,
            )
        )
    visible_scores = scores if max_items is None else scores[:max_items]
    history = load_score_history_summary()
    return ft.Column(
        [
            ft.Text(
                "Maturity | Sanity | Benchmark | Alpha proxy | Sector/theme | Backtest validity | Model contamination",
                color=theme.MUTED,
                size=11,
            ),
            *[_score_tile(score, history.get(score.display_id, [])) for score in visible_scores],
        ],
        spacing=8,
    )


def simple_score_grouped_sections(scores: list[SimpleInstrumentScore], *, page: ft.Page | None = None, state: object | None = None) -> ft.Control:
    history = load_score_history_summary()
    groups = group_simple_scores(scores)
    return ft.Column(
        [_score_group_section(group.label, group.scores, history, page=page, state=state) for group in groups],
        spacing=10,
    )


def score_value_text(score: float | None, *, size: int = 18) -> ft.Text:
    if score is None:
        return ft.Text("N/A", color=theme.MUTED, size=size, weight=ft.FontWeight.BOLD)
    return ft.Text(f"{score:.1f}/10", color=score_colour(score), size=size, weight=ft.FontWeight.BOLD)


def score_colour(score: float | None) -> str:
    if score is None:
        return theme.MUTED
    if score >= 8.0:
        return theme.GREEN
    if score >= 6.5:
        return theme.LIGHT_GREEN
    if score >= 5.0:
        return theme.CYAN
    if score >= 4.0:
        return theme.AMBER
    return theme.RED


def _score_group_section(label: str, scores: list[SimpleInstrumentScore], history: dict[str, list[dict[str, object]]], *, page: ft.Page | None = None, state: object | None = None) -> ft.Control:
    if not scores:
        body: list[ft.Control] = [ft.Text("No instruments in this group yet.", color=theme.MUTED, size=11)]
    else:
        body = [
            ft.Text(
                "Maturity | Sanity | Benchmark | Alpha proxy | Sector/theme | Backtest validity | Model contamination",
                color=theme.MUTED,
                size=11,
            ),
            *[_score_tile(score, history.get(score.display_id, []), page=page, state=state) for score in scores],
        ]
    return ft.Container(
        bgcolor=theme.SURFACE_2,
        border_radius=8,
        border=border_all(1, theme.BORDER),
        padding=10,
        content=ft.Column(
            [
                section_header(label, f"{len(scores)} instruments"),
                *body,
            ],
            spacing=8,
        ),
    )


def _score_tile(item: SimpleInstrumentScore, history_rows: list[dict[str, object]], *, page: ft.Page | None = None, state: object | None = None) -> ft.Control:
    subtitle = (
        f"{item.source_group} | Yahoo {item.yahoo_symbol} | ISIN {item.isin or 'N/A'} | "
        f"{item.asset_type} | Latest {item.latest_date} | {item.one_line_reason}"
    )
    details = ft.Container(
        visible=False,
        padding=ft.Padding(left=10, top=8, right=10, bottom=12),
        content=ft.Column(
            [
                ft.Row(
                    [
                        evidence_chip("Source", item.source_group, theme.CYAN),
                        evidence_chip("Action", item.final_action, _action_colour(item.final_action)),
                        evidence_chip("Quality", _score_badge(item.evidence_quality_10), score_colour(item.evidence_quality_10)),
                        evidence_chip("Risk/friction", _score_badge(item.risk_friction_10), score_colour(item.risk_friction_10)),
                        evidence_chip(
                            "Components",
                            f"{item.valid_component_count}/{item.total_component_count} valid",
                            theme.GREEN if item.valid_component_count >= max(5, item.total_component_count - 3) else theme.AMBER,
                        ),
                        evidence_chip("Warnings", str(len(item.warnings)), theme.AMBER if item.warnings else theme.GREEN),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Row(
                    [
                        evidence_chip("Attractiveness", _score_badge(item.canonical_score.attractiveness_10 if item.canonical_score else None), score_colour(item.canonical_score.attractiveness_10 if item.canonical_score else None)),
                        evidence_chip("Expected return", _score_badge(item.canonical_score.expected_return_10 if item.canonical_score else None), score_colour(item.canonical_score.expected_return_10 if item.canonical_score else None)),
                        evidence_chip("Risk/implementation", _score_badge(item.canonical_score.risk_implementation_10 if item.canonical_score else None), score_colour(item.canonical_score.risk_implementation_10 if item.canonical_score else None)),
                        evidence_chip("Evidence confidence", _score_badge(item.canonical_score.evidence_confidence_10 if item.canonical_score else None), score_colour(item.canonical_score.evidence_confidence_10 if item.canonical_score else None)),
                        evidence_chip("Coverage", f"{item.canonical_score.coverage:.0%}" if item.canonical_score else "N/A", theme.CYAN),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Text(
                    f"Formula {item.canonical_score.formula_version} | formula checksum {item.canonical_score.formula_checksum} | source-vintage {item.canonical_score.source_vintage_hash}"
                    if item.canonical_score
                    else "Canonical v3 score unavailable.",
                    color=theme.MUTED,
                    size=10,
                    selectable=True,
                ),
                ft.Row(
                    [
                        evidence_chip("Model authority", item.model_authority_label, theme.PURPLE),
                        evidence_chip("Calibration", item.model_calibration_label, score_colour(item.model_calibration_score_10)),
                        evidence_chip("Backtest", item.backtest_trust_label, score_colour(item.backtest_trust_score_10)),
                        evidence_chip("Final label", item.final_label, score_colour(item.final_score_10)),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Row(
                    [
                        evidence_chip("Backtest validity", item.backtest_validity, _validity_colour(item.backtest_validity)),
                        evidence_chip("Model contamination", item.model_contamination_risk, _contamination_colour(item.model_contamination_risk)),
                        evidence_chip("Calibration required", "yes" if item.calibration_required else "no", theme.AMBER if item.calibration_required else theme.GREEN),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Text(item.model_authority_reason, color=theme.MUTED, size=11),
                ft.Row(
                    [
                        evidence_chip("Regime", _regime_badge(item), score_colour(item.market_regime_score_10)),
                        evidence_chip("Portfolio fit", item.portfolio_fit_label, score_colour(item.portfolio_fit_score_10)),
                        evidence_chip("Strategy template", item.strategy_template_label, theme.CYAN),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Row(
                    [
                        evidence_chip("Benchmark", _benchmark_badge(item), theme.CYAN),
                        evidence_chip("Beta", _number_badge(item.benchmark_beta), _benchmark_colour(item)),
                        evidence_chip("Corr", _number_badge(item.benchmark_correlation), _benchmark_colour(item)),
                        evidence_chip("Alpha proxy", _pct_badge(item.alpha_proxy), _alpha_colour(item.alpha_proxy)),
                        evidence_chip("Sector/theme", _sector_theme_badge(item), theme.AMBER if "warning" in item.sector_theme_warning.lower() else theme.CYAN),
                        evidence_chip(
                            "Crowding",
                            item.crowding_warning,
                            theme.AMBER if _is_crowding_warning_state(item.crowding_warning) else theme.CYAN,
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Row(
                    [
                        evidence_chip("Gross edge", _bps_badge(item.gross_expected_edge_bps), _edge_colour(item.gross_expected_edge_bps)),
                        evidence_chip("Cost", _bps_badge(item.estimated_total_cost_bps), theme.AMBER),
                        evidence_chip("Net edge", _bps_badge(item.net_expected_edge_bps), _edge_colour(item.net_expected_edge_bps)),
                        evidence_chip("Edge/cost", _number_badge(item.edge_to_cost_ratio), _ratio_colour(item.edge_to_cost_ratio)),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Text(f"Cost scenario: {item.cost_stress_scenario}", color=theme.MUTED, size=11),
                ft.Text(item.benchmark_attribution_label, color=theme.MUTED, size=11),
                ft.Text(
                    f"Sector-relative: {_pct_badge(item.sector_relative_return)} | alpha {_pct_badge(item.sector_alpha_proxy)} | status {item.sector_attribution_status}",
                    color=theme.MUTED,
                    size=11,
                ),
                ft.Text(
                    f"Theme-relative: {_pct_badge(item.theme_relative_return)} | alpha {_pct_badge(item.theme_alpha_proxy)} | status {item.theme_attribution_status}",
                    color=theme.MUTED,
                    size=11,
                ),
                ft.Text(
                    f"Crowding cluster: {item.crowding_cluster_label} | peers {item.crowding_average_peer_correlation if item.crowding_average_peer_correlation is not None else 'N/A'} | risk contribution {item.crowding_cluster_risk_contribution if item.crowding_cluster_risk_contribution is not None else 'N/A'} | coverage {item.crowding_ranking_coverage if item.crowding_ranking_coverage is not None else 'N/A'} | pair sample {item.crowding_pair_sample_size if item.crowding_pair_sample_size is not None else 'N/A'} / row sample {item.crowding_sample_size if item.crowding_sample_size is not None else 'N/A'} | top-theme concentration {item.crowding_top_ranked_theme_concentration if item.crowding_top_ranked_theme_concentration is not None else 'N/A'} | top-theme warning {item.crowding_top_ranked_theme_warning} | as of {item.crowding_as_of or 'N/A'}",
                    color=theme.MUTED,
                    size=11,
                ),
                ft.Text(item.sector_theme_warning, color=theme.MUTED, size=11),
                ft.Row(
                    [
                        evidence_chip("Maturity", item.evidence_maturity_label, _maturity_colour(item.evidence_maturity_state)),
                        evidence_chip("Sample", _sample_badge(item), _maturity_colour(item.evidence_maturity_state)),
                        evidence_chip("Sanity", item.too_good_to_be_true_warning, _sanity_colour(item)),
                        evidence_chip("Evidence warnings", str(item.evidence_warning_count), theme.AMBER if item.evidence_warning_count else theme.GREEN),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                _sanity_warning_text(item),
                _score_history_panel(item, history_rows),
                ft.Text(item.strategy_template_descriptions, color=theme.MUTED, size=11),
                ft.Column([_component_row(component) for component in item.components], spacing=6),
            ],
            spacing=10,
        ),
    )

    def toggle_details(event: ft.ControlEvent) -> None:
        details.visible = not bool(details.visible)
        arrow_button.icon = ft.Icons.KEYBOARD_ARROW_UP if details.visible else ft.Icons.KEYBOARD_ARROW_DOWN
        page = event.page or details.page or arrow_button.page
        if page is not None:
            page.update()

    arrow_button = ft.IconButton(
        key=f"dashboard.score-row-expand.{item.display_id}",
        icon=ft.Icons.KEYBOARD_ARROW_DOWN,
        icon_color=theme.MUTED,
        icon_size=20,
        tooltip="Show score details",
        on_click=toggle_details,
    )

    detail_button: ft.Control | None = None
    if page is not None and state is not None:
        def open_detail(_event: ft.ControlEvent) -> None:
            from etf_cockpit.app.router import navigate_to, instrument_detail_route

            navigate_to(page, state, instrument_detail_route(item.display_id), candidate_score=item)

        detail_button = ft.TextButton(
            "Open instrument detail",
            key=f"dashboard.score-row-detail.{item.display_id}",
            tooltip="Open instrument detail",
            on_click=open_detail,
        )
    return ft.Container(
        bgcolor=theme.SURFACE,
        border_radius=8,
        border=border_all(1, theme.BORDER),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column(
            [
                ft.Container(
                    padding=ft.Padding(left=12, top=10, right=12, bottom=10),
                    ink=True,
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(f"{item.display_id} - {item.name}", color=theme.TEXT, size=14, weight=ft.FontWeight.BOLD),
                                    ft.Text(subtitle, color=theme.MUTED, size=11, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                    detail_button if detail_button is not None else ft.Container(),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Column(
                                [
                                    score_value_text(item.final_score_10),
                                    ft.Text(item.decision, color=score_colour(item.final_score_10), size=11, weight=ft.FontWeight.BOLD),
                                ],
                                spacing=2,
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                            ),
                            arrow_button,
                        ],
                        spacing=8,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
                details,
            ],
            spacing=0,
        ),
    )


def _score_history_panel(item: SimpleInstrumentScore, history_rows: list[dict[str, object]]) -> ft.Control:
    valid_rows = [
        row
        for row in history_rows
        if _history_score(row) is not None
    ]
    if not valid_rows:
        return ft.Container(
            bgcolor=theme.SURFACE_2,
            border_radius=6,
            padding=10,
            content=ft.Column(
                [
                    ft.Text("Score history", color=theme.TEXT, size=12, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "No score history available yet. History will appear after another run. Pending/N/A rows are stored but do not affect actions.",
                        color=theme.MUTED,
                        size=11,
                    ),
                ],
                spacing=4,
            ),
        )
    scores = [_history_score(row) for row in valid_rows[-12:]]
    scores = [score for score in scores if score is not None]
    latest = scores[-1]
    sparkline = " ".join(_score_bar(value) for value in scores)
    if len(scores) == 1:
        return ft.Container(
            bgcolor=theme.SURFACE_2,
            border_radius=6,
            padding=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Score history", color=theme.TEXT, size=12, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Latest {latest:.1f}/10 | One snapshot", color=score_colour(latest), size=11),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                    ),
                    ft.Text(f"Score evolution: {sparkline}", color=theme.TEXT, size=11, selectable=True),
                    ft.Text("A previous snapshot is not available yet; history will appear after another run. History is informational only and cannot change the current action.", color=theme.MUTED, size=11),
                ],
                spacing=6,
            ),
        )
    previous = scores[-2]
    delta = latest - previous
    return ft.Container(
        bgcolor=theme.SURFACE_2,
        border_radius=6,
        padding=10,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Score history", color=theme.TEXT, size=12, weight=ft.FontWeight.BOLD),
                        ft.Text(f"Latest {latest:.1f}/10 | Previous {previous:.1f}/10 | Delta {delta:+.1f}", color=score_colour(latest), size=11),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    wrap=True,
                ),
                ft.Text(f"Score evolution: {sparkline}", color=theme.TEXT, size=11, selectable=True),
                ft.Text(
                    "Local score history is informational only and cannot directly change the current action.",
                    color=theme.MUTED,
                    size=11,
                ),
            ],
            spacing=6,
        ),
    )


def _score_bar(value: float) -> str:
    filled = max(0, min(10, int(round(value))))
    return "[" + ("#" * filled).ljust(10, ".") + f"] {value:.1f}"


def _component_row(component: SimpleScoreComponent) -> ft.Container:
    score_label = "N/A" if component.score_10 is None else f"{component.score_10:.1f}/10"
    return ft.Container(
        bgcolor=theme.SURFACE_2,
        border_radius=6,
        padding=10,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(component.label, color=theme.TEXT, size=12, weight=ft.FontWeight.BOLD, expand=True),
                        ft.Text(score_label, color=score_colour(component.score_10), size=13, weight=ft.FontWeight.BOLD),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Row(
                    [
                        evidence_chip("Authority", component.authority, _authority_colour(component.authority)),
                        evidence_chip("Role", component.score_role, theme.CYAN),
                        evidence_chip("Source", component.source_id or "unavailable", theme.BLUE_GREY),
                        evidence_chip("Freshness", component.freshness_status or "unknown", _freshness_colour(component.freshness_status)),
                    ],
                    spacing=6,
                    wrap=True,
                ),
                ft.Text(component.explanation, color=theme.MUTED, size=11),
                ft.Text(component.good_score, color=theme.MUTED, size=11),
                ft.Text(component.why, color=theme.TEXT if component.score_10 is not None else theme.AMBER, size=11),
                ft.Text(_driver_classification(component), color=theme.MUTED, size=10),
            ],
            spacing=4,
        ),
    )


def _legend_colour(label: str) -> str:
    if label.startswith("8-10"):
        return theme.GREEN
    if label.startswith("6-7.9"):
        return theme.LIGHT_GREEN
    if label.startswith("4-5.9"):
        return theme.AMBER
    return theme.RED


def _score_badge(score: float | None) -> str:
    return "N/A" if score is None else f"{score:.1f}/10"


def _regime_badge(item: SimpleInstrumentScore) -> str:
    score = "N/A" if item.market_regime_score_10 is None else f"{item.market_regime_score_10:.1f}/10"
    return f"{item.market_regime_label} ({score})"


def _benchmark_badge(item: SimpleInstrumentScore) -> str:
    if not item.benchmark_id:
        return "pending"
    days = "N/A" if item.benchmark_period_days is None else f"{item.benchmark_period_days}d"
    return f"{item.benchmark_id} {days}: {_pct_badge(item.benchmark_return)}"


def _pct_badge(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.1%}"


def _number_badge(value: float | None) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "N/A"
    return "N/A" if not math.isfinite(number) else f"{number:.2f}"


def _bps_badge(value: float | None) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "N/A"
    return "N/A" if not math.isfinite(number) else f"{number:+.1f} bps"


def _edge_colour(value: float | None) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return theme.MUTED
    if not math.isfinite(number):
        return theme.MUTED
    if number > 0:
        return theme.GREEN
    if number < 0:
        return theme.AMBER
    return theme.CYAN


def _ratio_colour(value: float | None) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return theme.MUTED
    if not math.isfinite(number):
        return theme.MUTED
    if number >= 2.5:
        return theme.GREEN
    if number >= 1.0:
        return theme.AMBER
    return theme.RED


def _benchmark_colour(item: SimpleInstrumentScore) -> str:
    if item.benchmark_beta is None and item.benchmark_correlation is None:
        return theme.MUTED
    if (item.benchmark_correlation or 0.0) > 0.85:
        return theme.AMBER
    return theme.CYAN


def _alpha_colour(value: float | None) -> str:
    if value is None:
        return theme.MUTED
    if value > 0:
        return theme.GREEN
    if value < 0:
        return theme.AMBER
    return theme.CYAN


def _sector_theme_badge(item: SimpleInstrumentScore) -> str:
    if "pending" in item.sector_theme_warning.lower():
        return "pending"
    if "warning" in item.sector_theme_warning.lower():
        return "review"
    return "context"


def _sample_badge(item: SimpleInstrumentScore) -> str:
    if item.evidence_sample_days is None:
        return "unknown"
    return f"{item.evidence_sample_days} price rows"


def _sanity_warning_text(item: SimpleInstrumentScore) -> ft.Control:
    warnings = item.evidence_sanity_warnings or []
    if not warnings:
        return ft.Container()
    return ft.Text("Evidence sanity checks: " + " ".join(warnings), color=theme.AMBER, size=11)


def _maturity_colour(state: str) -> str:
    value = state.lower()
    if value == "mature_price_history":
        return theme.GREEN
    if value == "developing":
        return theme.CYAN
    if value in {"young", "young_noisy"}:
        return theme.AMBER
    return theme.RED


def _sanity_colour(item: SimpleInstrumentScore) -> str:
    return theme.GREEN if item.too_good_to_be_true_warning == "No sanity warning" else theme.AMBER


def _validity_colour(value: str) -> str:
    text = value.lower()
    if text in {"usable_low_authority", "model_claim_unverified"}:
        return theme.CYAN
    if "weak" in text or "unverified" in text:
        return theme.AMBER
    if "not_backtested" in text:
        return theme.MUTED
    return theme.CYAN


def _contamination_colour(value: str) -> str:
    text = value.lower()
    if "reduced" in text or "baseline_only" in text or "no_model" in text:
        return theme.GREEN
    if "unverified" in text:
        return theme.AMBER
    return theme.CYAN


def _authority_colour(authority: str) -> str:
    value = authority.lower()
    if value == "hard":
        return theme.RED
    if value == "high":
        return theme.GREEN
    if value == "low":
        return theme.PURPLE
    return theme.CYAN


def _freshness_colour(status: str | None) -> str:
    value = str(status or "unknown").casefold()
    if value in {"ok", "fresh", "valid"}:
        return theme.GREEN
    if value in {"stale", "stale_block", "expired"}:
        return theme.AMBER
    return theme.MUTED


def _driver_classification(component: SimpleScoreComponent) -> str:
    score = component.score_10
    if score is None:
        direction = "missing"
    elif score >= 6.5:
        direction = "positive"
    elif score < 4.0:
        direction = "negative"
    else:
        direction = "mixed"
    authority = str(component.authority or "unknown").casefold()
    freshness = str(component.freshness_status or "unknown").casefold()
    flags = []
    if authority in {"low", "unknown"} or str(component.source_authority or "").casefold() in {"model_advisory", "unknown"}:
        flags.append("low authority")
    if freshness in {"stale", "stale_block", "expired"}:
        flags.append("stale")
    elif freshness in {"partial", "warning", "unknown"}:
        flags.append("partial")
    return "Driver classification: " + direction + (" (" + ", ".join(flags) + ")" if flags else "") + ". Informational only."


def _action_colour(action: str) -> str:
    value = action.lower()
    if value == "add_candidate":
        return theme.GREEN
    if value == "manual_review":
        return theme.AMBER
    if value == "trim_candidate":
        return theme.RED
    return theme.CYAN


def _safe_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except Exception:
        return None
    if number != number:
        return None
    return number


def _history_score(row: dict[str, object]) -> float | None:
    return _safe_float(row.get("final_combined_score_10", row.get("final_score_10")))
