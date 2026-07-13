from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, metric_card, panel, section_header
from etf_cockpit.app.components.simple_scores import score_colour, simple_score_grouped_sections, simple_score_legend
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import FORECASTS_DIR
from etf_cockpit.core.paths import DERIVED_DIR
from etf_cockpit.data.news_context import NEWS_CLEAN_PATH, load_news_items, sort_news_items
from etf_cockpit.data.run_changes import compare_runs
from etf_cockpit.models.forecast_scores import filter_forecasts_for_universe, load_latest_forecasts
from etf_cockpit.signals.simple_scores import SimpleInstrumentScore, build_simple_instrument_scores


def _rebuild(page: ft.Page, state: AppState) -> None:
    from etf_cockpit.app.router import render_shell

    render_shell(page, state, page.route or state.snapshot.config.ui.default_page)


def _go_to(page: ft.Page, state: AppState, route: str) -> None:
    from etf_cockpit.app.router import navigate_to

    navigate_to(page, state, route)


def dashboard_page(page: ft.Page, state: AppState) -> ft.Control:
    narrow = float(getattr(page, "width", 0) or state.snapshot.config.ui.window_width) < 760
    scores = build_simple_instrument_scores(
        state.snapshot.config,
        state.snapshot.signals,
        state.snapshot.forecasts,
        state.snapshot.prices,
        universe_revision=str(
            getattr(state.snapshot, "universe_revision", "")
            or getattr(state, "universe_cache_revision", "")
        ),
    )
    best = scores[0] if scores else None
    configured_count = sum(1 for score in scores if score.source_group == "Primary tier")
    candidate_count = sum(1 for score in scores if score.source_group == "Secondary tier")
    sparebanken_count = sum(1 for score in scores if score.source_group == "Sparebanken")
    model_pairs = _valid_model_pairs(state)
    cards = _summary_cards(state, best, configured_count, candidate_count, sparebanken_count, model_pairs, narrow=narrow)

    return ft.Column(
        [
            cards,
            _run_changes_digest(page, state),
            _news_digest(page, state),
            _action_bar(page, state),
            simple_score_legend(),
            panel(
                ft.Column(
                    [
                        section_header(
                            "Simple yfinance scores",
                            "Primary tier, secondary tier and Sparebanken rows are separated by asset class. Expand a row for evidence quality, risk/friction, deterministic algorithms and low-authority AI forecast confirmation.",
                        ),
                        simple_score_grouped_sections(scores, page=page, state=state),
                    ],
                    spacing=12,
                ),
            ),
            _activity_panel(state),
            _secondary_actions(page, state),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )


def _run_changes_digest(_page: ft.Page, _state: AppState) -> ft.Control:
    """Show a deterministic, informational summary of the latest run delta."""

    path = DERIVED_DIR / "score_history.parquet"
    try:
        history = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    except Exception:
        history = pd.DataFrame()
    if history.empty or "run_id" not in history.columns:
        body: ft.Control = ft.Text("Run changes unavailable; complete two score runs to populate the digest.", color=theme.MUTED, selectable=True)
    else:
        if "run_completed_at" in history.columns:
            history = history.sort_values(["run_completed_at", "run_id"], kind="stable")
        runs = list(dict.fromkeys(history["run_id"].astype(str).tolist()))
        current = runs[-1]
        previous = runs[-2] if len(runs) > 1 else None
        report = compare_runs(history, current, previous)
        lines = [ft.Text(report.summary, color=theme.MUTED, selectable=True)]
        for change in report.changes[:5]:
            lines.append(ft.Text(f"{change.instrument_id}: {change.summary}", color=theme.MUTED, selectable=True, size=11))
        body = ft.Column(lines, spacing=4)
    return panel(
        ft.Column(
            [
                section_header("Run changes digest", "Latest score-run differences are deterministic, informational and cannot change current action authority."),
                body,
                ft.TextButton("Open What Changed", key="dashboard.open-what-changed", on_click=lambda _event: _go_to(_page, _state, "/what-changed")),
            ],
            spacing=8,
        )
    )


def _news_digest(page: ft.Page, state: AppState) -> ft.Control:
    """Show the latest canonical news context without granting authority."""

    frame = sort_news_items(load_news_items(NEWS_CLEAN_PATH))
    if frame.empty:
        body: ft.Control = ft.Text("News unavailable; no timestamp-validated local context is registered.", color=theme.MUTED, selectable=True)
    else:
        rows = []
        for _, row in frame.tail(4).iterrows():
            rows.append(ft.Text(
                f"{row.get('published_at', 'unavailable')} | {row.get('headline', 'Headline unavailable')} | {row.get('provider_name', 'provider unavailable')} | timestamp={row.get('timestamp_status', 'unavailable')} | context_only=true | executable_authority=false",
                color=theme.MUTED,
                selectable=True,
                size=11,
            ))
        body = ft.Column(rows, spacing=4)
    return panel(
        ft.Column(
            [
                section_header("News & context digest", "Recent local news is dated, source-linked context only and cannot change deterministic scores or actions."),
                body,
                ft.TextButton("Open News & Context", key="dashboard.open-news-context", on_click=lambda _event: _go_to(page, state, "/news-context")),
            ],
            spacing=8,
        )
    )


def _summary_cards(
    state: AppState,
    best: SimpleInstrumentScore | None,
    configured_count: int,
    candidate_count: int,
    sparebanken_count: int,
    model_pairs: int,
    *,
    narrow: bool,
) -> ft.Control:
    total_count = configured_count + candidate_count + sparebanken_count
    data_status = state.snapshot.data_report.status
    mode = "Manual review" if data_status == "Blocked" else "Caution" if data_status == "Warning" else "Normal"
    best_score = None if best is None else best.final_score_10
    top_score_value = "N/A" if best_score is None else f"{best_score:.1f}/10"
    top_score_subtitle = "No scores yet" if best is None or best_score is None else f"{best.display_id} - {best.decision}"
    card_controls = [
        metric_card("Instruments", str(total_count), f"{configured_count} primary, {candidate_count} secondary, {sparebanken_count} Sparebanken", theme.CYAN),
        metric_card(
            "Top score",
            top_score_value,
            top_score_subtitle,
            score_colour(best_score),
        ),
        metric_card("Data health", data_status, f"as of {state.snapshot.data_report.as_of_date}", theme.GREEN if data_status == "Clean" else theme.AMBER),
        metric_card("Model rows", str(model_pairs), "valid baseline/Toto/TimesFM pairs", theme.PURPLE),
        metric_card(
            "Regime",
            "N/A" if best is None else best.market_regime_label,
            "yfinance market context" if best is not None else "run scores",
            score_colour(None if best is None else best.market_regime_score_10),
        ),
        metric_card("Final mode", mode, "advisory scoring only", theme.RED if mode == "Manual review" else theme.AMBER if mode == "Caution" else theme.GREEN),
    ]
    return ft.Column(card_controls, spacing=8) if narrow else ft.Row(card_controls, spacing=12)


def _action_bar(page: ft.Page, state: AppState) -> ft.Control:
    return panel(
        ft.Column(
            [
                section_header("Workflow", "Refresh yfinance data, run algorithms, run forecasting models, then inspect the scores."),
                ft.Row(
                    [
                        _workflow_button(
                            "1. Refresh yfinance data",
                            key_name="dashboard.refresh-yfinance",
                            icon=ft.Icons.REFRESH,
                            on_click=lambda _event: _run_action(page, state, "Refresh yfinance data", state.refresh_yfinance_data),
                            width=220,
                        ),
                        _workflow_button(
                            "2. Run algorithms",
                            key_name="dashboard.run-algorithms",
                            icon=ft.Icons.AUTO_GRAPH,
                            on_click=lambda _event: _run_action(page, state, "Run algorithms", state.run_algorithm_scores),
                            width=190,
                        ),
                        _workflow_button(
                            "3. Run forecasting models",
                            key_name="dashboard.run-forecasting-models",
                            icon=ft.Icons.MODEL_TRAINING,
                            on_click=lambda _event: _run_action(page, state, "Run forecasting models", state.run_forecasting_models),
                            width=245,
                        ),
                        _workflow_button(
                            "4. Show scores",
                            key_name="dashboard.show-scores",
                            icon=ft.Icons.SCORE,
                            on_click=lambda _event: _go_to(page, state, "/signals"),
                            width=170,
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Text(state.last_message, color=theme.MUTED, size=12),
            ],
            spacing=10,
        )
    )


def _activity_panel(state: AppState) -> ft.Control:
    current = state.current_activity
    rows: list[ft.Control] = []
    if current is not None:
        rows.extend(
            [
                ft.Row(
                    [
                        ft.ProgressRing(width=18, height=18, stroke_width=2, color=theme.CYAN),
                        ft.Text(current.label, color=theme.TEXT, weight=ft.FontWeight.BOLD),
                        evidence_chip("Status", "running", theme.CYAN),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.ProgressBar(
                    value=(current.completed_units / current.total_units if current.total_units else None),
                    color=theme.CYAN,
                    bgcolor=theme.SURFACE_2,
                ),
                ft.Text(f"Current step: {current.step}", color=theme.MUTED),
            ]
        )
    else:
        rows.append(ft.Text(state.last_message, color=theme.MUTED))

    recent = list(reversed(state.recent_activity[-5:]))
    if recent:
        rows.append(ft.Text("Recent activity", color=theme.TEXT, weight=ft.FontWeight.BOLD, size=12))
        for entry in recent:
            colour = theme.GREEN if entry.status == "success" else theme.RED if entry.status == "failed" else theme.CYAN
            output = f" | output: {Path(entry.output_path).name}" if entry.output_path else ""
            rows.append(
                ft.Column(
                    [
                        evidence_chip(entry.status, entry.label, colour),
                        ft.Text(
                            f"{entry.finished_at or entry.started_at} | {entry.message}{output}",
                            color=theme.MUTED,
                            size=11,
                            max_lines=3,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=8,
                )
            )
    return panel(
        ft.Column(
            [
                section_header("Activity log", "Long-running actions show progress here and are saved to the session trace at logs/session.jsonl."),
                *rows,
            ],
            spacing=8,
        )
    )


def _workflow_button(label: str, *, key_name: str, icon: str, on_click, width: int) -> ft.Control:
    button = ft.OutlinedButton(
        label,
        key=key_name,
        tooltip=label,
        icon=icon,
        on_click=on_click,
    )
    return ft.Container(
        content=button,
        width=width,
        height=42,
    )


def _secondary_actions(page: ft.Page, state: AppState) -> ft.Control:
    return ft.Row(
        [
            ft.OutlinedButton(
                "Renew/import local files",
                key="dashboard.renew-import",
                icon=ft.Icons.DOWNLOAD,
                on_click=lambda _event: _open_renew_dialog(page, state),
            ),
            ft.OutlinedButton(
                "Audit packet",
                key="dashboard.export-audit",
                icon=ft.Icons.CHECK_CIRCLE,
                on_click=lambda _event: _export_pack(page, state),
            ),
            ft.OutlinedButton(
                "Advanced data/model diagnostics",
                key="dashboard.open-data-models",
                icon=ft.Icons.INSIGHTS,
                on_click=lambda _event: _go_to(page, state, "/data-models"),
            ),
        ],
        spacing=10,
        wrap=True,
    )


def _run_action(page: ft.Page, state: AppState, label: str, action: Callable[[], str]) -> None:
    if state.current_activity is not None:
        state.last_message = f"{state.current_activity.label} is still running. Please wait for it to finish."
        _rebuild(page, state)
        return
    state.begin_activity(label, "Starting")
    _rebuild(page, state)

    def worker() -> None:
        try:
            state.update_activity("Running local workflow")
            try:
                page.update()
            except Exception:
                pass
            message = action()
            state.finish_activity(message, label=label)
        except Exception as exc:
            state.fail_activity(label, exc, retry_callback=action)
        _rebuild(page, state)

    threading.Thread(target=worker, daemon=True).start()


def _run_dialog_action(page: ft.Page, state: AppState, result_text: ft.Text, label: str, step: str, action: Callable[[], str]) -> None:
    if state.current_activity is not None:
        result_text.value = f"{state.current_activity.label} is still running. Please wait for it to finish."
        page.update()
        return
    state.begin_activity(label, step)
    result_text.value = f"{step}..."
    page.update()

    def worker() -> None:
        try:
            message = action()
            result_text.value = message
            state.finish_activity(message, label=label)
        except Exception as exc:
            state.fail_activity(label, exc, retry_callback=action)
            result_text.value = state.last_message
        page.update()

    threading.Thread(target=worker, daemon=True).start()


def _export_pack(page: ft.Page, state: AppState) -> None:
    if state.current_activity is not None:
        state.last_message = f"{state.current_activity.label} is still running. Please wait for it to finish."
        _rebuild(page, state)
        return
    state.begin_activity("Export audit packet", "Writing audit packet")
    _rebuild(page, state)

    def worker() -> None:
        try:
            path = state.export_audit_packet()
            state.finish_activity(f"Audit packet exported: {path}", output_path=path)
        except Exception as exc:
            state.fail_activity("Export audit packet", exc, retry_callback=state.export_audit_packet)
        _rebuild(page, state)

    threading.Thread(target=worker, daemon=True).start()


def _valid_model_pairs(state: AppState) -> int:
    universe_revision = str(
        getattr(state.snapshot, "universe_revision", "")
        or getattr(state, "universe_cache_revision", "")
    )
    candidate_forecasts = load_latest_forecasts(
        "yfinance_candidate_forecasts_*.csv",
        FORECASTS_DIR,
        universe_revision=universe_revision,
    )
    configured_forecasts = filter_forecasts_for_universe(state.snapshot.forecasts, universe_revision)
    forecasts = pd.concat([configured_forecasts, candidate_forecasts], ignore_index=True)
    if forecasts.empty or not {"status", "model_allowed_in_score", "model_name", "etf_id"}.issubset(forecasts.columns):
        return 0
    allowed = forecasts["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
    valid = forecasts[(forecasts["status"].astype(str).str.lower() == "ok") & allowed]
    return int(valid[["model_name", "etf_id"]].drop_duplicates().shape[0])


def _open_renew_dialog(page: ft.Page, state: AppState) -> None:
    result_text = ft.Text(
        "Choose a local update action. Imported files are validated before they replace clean data.",
        color=theme.MUTED,
    )

    def close_dialog(_event: ft.ControlEvent | None = None) -> None:
        if hasattr(page, "pop_dialog"):
            page.pop_dialog()
            return
        dialog.open = False
        page.update()

    def dry_run(_event: ft.ControlEvent) -> None:
        _run_dialog_action(page, state, result_text, "Validate current data", "Running dry-run validation", state.renew_data_dry_run)

    def api_status(_event: ft.ControlEvent) -> None:
        _run_dialog_action(page, state, result_text, "Use API/yfinance provider", "Checking provider configuration", state.renew_data_api_status)

    def rollback_prices(_event: ft.ControlEvent) -> None:
        _run_dialog_action(page, state, result_text, "Rollback prices", "Searching previous clean price snapshot", state.rollback_latest_prices)

    file_picker = ft.FilePicker(key="dashboard.renew-import.file-picker")
    try:
        if file_picker not in page.services:
            page.services.append(file_picker)
    except Exception:
        try:
            if file_picker not in page.overlay:
                page.overlay.append(file_picker)
        except Exception:
            pass

    async def import_file(dataset_type: str) -> None:
        state.begin_activity(f"Import {dataset_type}", "Opening local file picker")
        result_text.value = f"Opening local file picker for {dataset_type}..."
        page.update()
        try:
            files = await file_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["csv", "xlsx", "xls", "json", "jsonl", "parquet", "pq"],
                allow_multiple=False,
                with_data=True,
            )
        except Exception as exc:
            state.fail_activity(f"Import {dataset_type}", exc)
            result_text.value = f"Local file picker unavailable: {exc}"
            page.update()
            return

        if not files:
            result_text.value = "No local file selected."
            state.finish_activity("No local file selected.")
            page.update()
            return
        selected = files[0]
        try:
            state.update_activity(f"Validating selected {dataset_type} file")
            page.update()
            if selected.path:
                result_text.value = state.validate_local_import(selected.path, dataset_type)
            elif selected.bytes is not None:
                result_text.value = state.import_local_upload(selected.name, selected.bytes, dataset_type)
            else:
                result_text.value = "Selected file did not expose a path or readable bytes."
            state.finish_activity(result_text.value)
        except Exception as exc:
            state.fail_activity(f"Import {dataset_type}", exc)
            result_text.value = state.last_message
        page.update()

    async def import_prices(_event: ft.ControlEvent) -> None:
        await import_file("prices")

    async def import_manual_notes(_event: ft.ControlEvent) -> None:
        await import_file("manual_news")

    async def import_etf_factsheets(_event: ft.ControlEvent) -> None:
        await import_file("etf_metadata")

    async def import_etf_holdings(_event: ft.ControlEvent) -> None:
        await import_file("etf_holdings")

    async def import_fx_rates(_event: ft.ControlEvent) -> None:
        await import_file("fx")

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Renew local data", color=theme.TEXT),
        content=ft.Container(
            width=640,
            height=430,
            content=ft.Column(
                [
                    ft.Text("Local imports", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                    ft.Text("Prices, FX, ETF factsheets, holdings and notes are copied to raw storage, validated, then committed only if clean enough.", color=theme.MUTED),
                    ft.Row(
                        [
                            ft.TextButton("Import prices", key="dashboard.import-prices", on_click=import_prices),
                            ft.TextButton("Import manual notes", key="dashboard.import-manual-notes", on_click=import_manual_notes),
                            ft.TextButton("Import ETF factsheets", key="dashboard.import-etf-factsheets", on_click=import_etf_factsheets),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            ft.TextButton("Import ETF holdings", key="dashboard.import-etf-holdings", on_click=import_etf_holdings),
                            ft.TextButton("Import FX rates", key="dashboard.import-fx-rates", on_click=import_fx_rates),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Text("API provider", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                    ft.Text("With yfinance configured, this refreshes Yahoo data. Without provider details, it returns a safe message.", color=theme.MUTED),
                    result_text,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
        actions=[
            ft.TextButton("Use API/yfinance provider", key="dashboard.renew-api-status", on_click=api_status),
            ft.TextButton("Validate current data", key="dashboard.renew-dry-run", on_click=dry_run),
            ft.TextButton("Rollback prices", key="dashboard.renew-rollback", on_click=rollback_prices),
            ft.TextButton("Close", key="dashboard.renew-close", on_click=close_dialog),
        ],
    )
    if hasattr(page, "show_dialog"):
        page.show_dialog(dialog)
    else:
        page.dialog = dialog
        dialog.open = True
        page.update()
