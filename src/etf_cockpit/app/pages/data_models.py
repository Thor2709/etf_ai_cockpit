from __future__ import annotations

import json

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import DERIVED_DIR, FORECASTS_DIR, MODEL_DIR, REPORTS_DIR
from etf_cockpit.application.ui_facade import format_model_inventory_line, fx_data_inventory, load_manual_news, reference_data_inventory
from etf_cockpit.plugins.builtins import plugin_status_rows


def data_models_page(_page: ft.Page, state: AppState) -> ft.Control:
    latest_dates = state.snapshot.prices.groupby("etf_id")["date"].max().reset_index()
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(row["etf_id"], color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(str(row["date"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(state.snapshot.data_report.status, color=theme.MUTED, size=12)),
            ]
        )
        for _, row in latest_dates.iterrows()
    ]
    forecast_files = sorted(FORECASTS_DIR.glob("*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)[:6]
    report_files = sorted(REPORTS_DIR.glob("yfinance_trade_candidate_analysis_*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)[:3]
    derived_files = sorted(DERIVED_DIR.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)[:10]
    model_lines = [
        "baseline: available deterministic forecast",
        f"timesfm: {'available' if state.snapshot.model_status.get('timesfm') else 'unavailable'} ({MODEL_DIR / 'timesfm'})",
        f"toto: {'available' if state.snapshot.model_status.get('toto') else 'unavailable'} ({MODEL_DIR / 'toto'})",
        "Model scores are used only when forecast rows are status ok and model_allowed_in_score=true.",
    ]
    inventory_lines = [format_model_inventory_line(item) for item in state.snapshot.model_inventory]
    plugin_lines = [
        f"{row['provider_id']} | kind={row['dataset_type']} | status={row['status']} | authority={row['authority']} | execution=false"
        for row in plugin_status_rows()
    ]
    metadata_lines = [
        (
            f"{meta.source_type}: source={meta.source_name}, as_of={meta.as_of_date}, "
            f"staleness={meta.staleness_status}, currency={meta.currency}, checksum={meta.checksum[:12]}"
        )
        for meta in state.snapshot.data_report.dataset_metadata
    ]
    manual_notes = load_manual_news()
    if manual_notes.empty:
        manual_note_lines = ["No manual thesis/news notes imported."]
    else:
        recent_notes = manual_notes.copy()
        recent_notes["as_of_date"] = recent_notes["as_of_date"].astype(str)
        recent_notes = recent_notes.sort_values("as_of_date", ascending=False).head(8)
        manual_note_lines = [
            (
                f"{row['as_of_date']} | {row.get('etf_id') or 'portfolio'} | {row.get('title') or 'Untitled note'} | "
                f"source={row.get('source') or 'manual_import'} | executable_authority=false"
            )
            for _, row in recent_notes.iterrows()
        ]
    reference_lines = []
    for item in reference_data_inventory():
        if item["present"]:
            reference_lines.append(
                (
                    f"{item['dataset_type']}: rows={item['rows']}, as_of={item['as_of_date']}, "
                    f"staleness={item['staleness_status']}, checksum={str(item['checksum'])[:12]}"
                )
            )
        else:
            reference_lines.append(f"{item['dataset_type']}: not imported")
    fx_inventory = fx_data_inventory()
    if fx_inventory["present"]:
        reference_lines.append(
            (
                f"fx: rows={fx_inventory['rows']}, as_of={fx_inventory['as_of_date']}, "
                f"pairs={','.join(fx_inventory['pairs'])}, staleness={fx_inventory['staleness_status']}, "
                f"checksum={str(fx_inventory['checksum'])[:12]}"
            )
        )
    else:
        reference_lines.append("fx: not imported")
    latest_status_panel = panel(
        ft.Column(
            [
                section_header("Latest local price data", "Per instrument date from the clean price store."),
                ft.DataTable(columns=[ft.DataColumn(ft.Text("Instrument")), ft.DataColumn(ft.Text("Latest date")), ft.DataColumn(ft.Text("Data status"))], rows=rows),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )
    evidence_panels = ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Model availability", "Local baseline, TimesFM and Toto status."),
                        ft.Text("\n".join(model_lines), color=theme.MUTED, selectable=True),
                        ft.Text("Local model files", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                        ft.Text("\n".join(inventory_lines) or "No local model files detected.", color=theme.MUTED, selectable=True),
                    ],
                    spacing=8,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Unified plugin capability status", "Provider, model and paper-broker adapters use the same local contract and allow-list. Disabled adapters remain visible without authority."),
                        ft.Text("\n".join(plugin_lines), color=theme.MUTED, selectable=True),
                    ],
                    spacing=8,
                )
            ),
            panel(ft.Column([section_header("Forecast artefacts", "Latest generated model/algorithm forecast CSV files."), ft.Text("\n".join(str(path) for path in forecast_files) or "No forecast CSV files found.", color=theme.MUTED, selectable=True)])),
            panel(
                ft.Column(
                    [
                        section_header("Derived evidence artefacts", "Scoreboard, calibration, regime and strategy-template files used by the UI and audit export."),
                        ft.Text("\n".join(str(path) for path in derived_files) or "No derived evidence files found.", color=theme.MUTED, selectable=True),
                    ]
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Market regime", "Yfinance-only regime context from configured and candidate instruments."),
                        ft.Text(_market_regime_text(), color=theme.MUTED, selectable=True),
                    ]
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Forecast calibration", "Only matured local forecast rows are scored. Current forecasts remain pending until their horizon passes."),
                        ft.Text(_calibration_text(), color=theme.MUTED, selectable=True),
                    ]
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Strategy templates", "Simple deterministic template tags derived from the x/10 evidence components."),
                        ft.Text(_strategy_template_text(), color=theme.MUTED, selectable=True),
                    ]
                )
            ),
            panel(ft.Column([section_header("Candidate reports", "Latest yfinance stock/ETF candidate analysis files."), ft.Text("\n".join(str(path) for path in report_files) or "No yfinance candidate report files found.", color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Dataset provenance", "Source, as-of date, staleness and checksum for loaded local data."), ft.Text("\n".join(metadata_lines) or "No dataset metadata available.", color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Reference data", "Optional factsheets, holdings and FX datasets."), ft.Text("\n".join(reference_lines), color=theme.MUTED, selectable=True)])),
            panel(
                ft.Column(
                    [
                        section_header("Manual thesis and news notes", "Dated notes are evidence only and never executable authority."),
                        ft.Text("\n".join(manual_note_lines), color=theme.MUTED, selectable=True),
                    ]
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Validation findings", "Hard data failures block analysis; portfolio allocation findings are context."),
                        ft.Text("\n".join(issue.message for issue in state.snapshot.data_report.issues) or "No data-quality issues.", color=theme.MUTED, selectable=True),
                    ]
                )
            ),
        ],
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return ft.Row(
        [latest_status_panel, evidence_panels],
        spacing=14,
        expand=True,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def _market_regime_text() -> str:
    path = DERIVED_DIR / "market_regime.json"
    if not path.exists():
        return "No regime artefact yet. Refresh data or run algorithms to create it."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Could not read market regime artefact: {exc}"
    return "\n".join(
        [
            f"Label: {data.get('regime_label')}",
            f"Score: {data.get('regime_score_10')}/10",
            f"Benchmark: {data.get('benchmark_id')}",
            f"Universe above SMA200: {data.get('combined_pct_above_sma200')}",
            f"Median drawdown: {data.get('median_current_drawdown')}",
            f"Summary: {data.get('summary')}",
        ]
    )


def _calibration_text() -> str:
    path = DERIVED_DIR / "model_calibration.csv"
    if not path.exists():
        return "No calibration artefact yet. Run forecasting models, then refresh scores."
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return f"Could not read calibration artefact: {exc}"
    if frame.empty:
        return "Calibration artefact is empty. No valid local forecast rows were found."
    lines = []
    for _, row in frame.head(12).iterrows():
        score = row.get("calibration_score_10")
        score_text = "N/A" if pd.isna(score) else f"{float(score):.1f}/10"
        lines.append(
            (
                f"{row.get('instrument_id')} | {row.get('model_name')} | {score_text} | "
                f"matured={row.get('matured_forecasts')} | {row.get('calibration_status')}"
            )
        )
    return "\n".join(lines)


def _strategy_template_text() -> str:
    path = DERIVED_DIR / "strategy_templates.csv"
    if not path.exists():
        return "No strategy-template artefact yet. Run scores to create it."
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return f"Could not read strategy-template artefact: {exc}"
    if frame.empty:
        return "Strategy-template artefact is empty."
    lines = []
    for _, row in frame.head(12).iterrows():
        lines.append(
            (
                f"{row.get('instrument_id')} | {row.get('asset_type')} | "
                f"{row.get('strategy_template_label')} | evidence={row.get('evidence_score_10')}"
            )
        )
    return "\n".join(lines)
