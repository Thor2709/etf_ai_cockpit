from __future__ import annotations

import json
import math

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.monthly_decision_template import (
    build_monthly_decision_template,
    monthly_decision_template_lines,
    unavailable_monthly_evidence,
)
from etf_cockpit.core.paths import DERIVED_DIR, FORECASTS_DIR, MODEL_DIR, REPORTS_DIR
from etf_cockpit.application.ui_facade import (
    build_coverage_audit,
    coverage_summary_lines,
    format_model_inventory_line,
    fx_data_inventory,
    load_manual_news,
    reference_data_inventory,
    write_coverage_audit,
)
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
    try:
        manual_notes = load_manual_news()
        manual_note_error = None
    except Exception as exc:
        manual_notes = pd.DataFrame()
        manual_note_error = type(exc).__name__
    if manual_note_error is not None:
        manual_note_lines = [
            f"Manual note credibility evidence unavailable; manual review required ({manual_note_error}). executable_authority=false"
        ]
    elif manual_notes.empty:
        manual_note_lines = ["No manual thesis/news notes imported; credibility flags are unavailable. executable_authority=false"]
    else:
        recent_notes = manual_notes.copy()
        recent_notes["as_of_date"] = recent_notes["as_of_date"].astype(str)
        recent_notes = recent_notes.sort_values("as_of_date", ascending=False).head(8)
        manual_note_lines = [
            (
                f"{row['as_of_date']} | {row.get('etf_id') or 'portfolio'} | {row.get('title') or 'Untitled note'} | "
                f"source={row.get('source') or 'manual_import'} | credibility_flag_status={row.get('credibility_flag_status', 'unavailable')} | "
                f"credibility_flags={row.get('credibility_flags', 'unknown')} | credibility_reason_codes={row.get('credibility_reason_codes', 'unknown')} | "
                f"executable_authority=false"
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
    coverage_report = build_coverage_audit(
        state.snapshot.config.universe.etfs,
        state.snapshot.prices,
        state.snapshot.forecasts,
        state.snapshot.signals,
        as_of_date=state.snapshot.data_report.as_of_date,
        provenance={
            "dataset_metadata": [
                {
                    "source": meta.source_name,
                    "as_of": meta.as_of_date.isoformat() if meta.as_of_date else None,
                    "checksum": meta.checksum,
                }
                for meta in state.snapshot.data_report.dataset_metadata
            ]
        },
    )
    coverage_status = ft.Text("", color=theme.MUTED, selectable=True)

    def export_coverage(_event: ft.ControlEvent) -> None:
        try:
            json_path, markdown_path = write_coverage_audit(coverage_report)
            coverage_status.value = f"Coverage audit exported: {json_path.name}, {markdown_path.name}"
            state.last_message = coverage_status.value
        except (OSError, ValueError, TypeError) as exc:
            coverage_status.value = f"Coverage audit export failed: {type(exc).__name__}: {exc}"
            state.last_message = coverage_status.value
        try:
            _page.update()
        except (AttributeError, RuntimeError):
            pass
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
                        section_header("Strategy templates", "Simple deterministic template tags and a monthly basket/benchmark/cash comparison."),
                        ft.Text(_strategy_template_text(), color=theme.MUTED, selectable=True),
                        ft.Text(
                            "Monthly decision template\n" + _monthly_decision_text(state),
                            key="data-models.monthly-decision-template",
                            color=theme.MUTED,
                            selectable=True,
                        ),
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
                        section_header(
                            "Data coverage and model monitoring",
                            "Local adjusted-price coverage and subgroup evidence. Unsupported groups stay in manual review; aggregate metrics never grant subgroup authority.",
                        ),
                        ft.Text("\n".join(coverage_summary_lines(coverage_report)), color=theme.MUTED, selectable=True),
                        ft.OutlinedButton("Export coverage audit", key="data-models.export-coverage", icon=ft.Icons.DOWNLOAD, on_click=export_coverage),
                        coverage_status,
                    ],
                    spacing=8,
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


def _monthly_decision_text(state: AppState) -> str:
    path = DERIVED_DIR / "strategy_templates.csv"
    try:
        frame = pd.read_csv(path) if path.exists() else pd.DataFrame()
    except Exception as exc:
        return f"Monthly decision template unavailable: {type(exc).__name__}."
    reference = context_from_snapshot(
        state.snapshot,
        purpose="comparison",
        analysis_id=f"monthly-decision:{getattr(state.snapshot, 'universe_revision', 'unknown')}",
    )
    components = [
        _strategy_distribution_component(row.to_dict())
        for _, row in frame.iterrows()
    ]
    alternatives = _monthly_strategy_alternatives(frame, reference.projection)
    template = build_monthly_decision_template(
        benchmark_reference=reference.projection,
        benchmark_registry=reference.registry,
        alternatives=alternatives,
        expected_returns={
            "status": "partial" if components else "unavailable",
            "reason": "canonical_basket_distribution_unavailable",
            "components": components,
            "execution_allowed": False,
        } if components else unavailable_monthly_evidence("strategy_distribution_rows_unavailable"),
        optimiser=unavailable_monthly_evidence("optimiser_projection_not_produced_on_strategy_templates_surface"),
        costs=unavailable_monthly_evidence("portfolio_cost_projection_not_produced_on_strategy_templates_surface"),
        events=unavailable_monthly_evidence("event_replay_projection_not_produced_on_strategy_templates_surface"),
        forward_evidence=unavailable_monthly_evidence("forward_evidence_snapshot_not_produced_on_strategy_templates_surface"),
        paper_outcomes=unavailable_monthly_evidence("paper_account_snapshot_not_produced_on_strategy_templates_surface"),
        concentration={
            "status": "partial",
            "reason": "portfolio_concentration_not_available_from_instrument_rows",
            "sector": unavailable_monthly_evidence("portfolio_sector_concentration_unavailable"),
            "theme": unavailable_monthly_evidence("portfolio_theme_concentration_unavailable"),
            "components": [
                {
                    "instrument_id": str(row.get("instrument_id") or "unavailable"),
                    "sector_theme_warning": str(row.get("sector_theme_warning") or "unavailable"),
                    "theme_concentration": _optional_number(row.get("crowding_top_ranked_theme_concentration")),
                }
                for _, row in frame.iterrows()
            ],
            "execution_allowed": False,
        },
        assumptions={
            "status": "available",
            "version": "monthly-decision-assumptions.v1",
            "source_id": "ISSUE-0046",
            "values": {
                "rebalance_cadence": "monthly",
                "execution_assumption": "next_session",
                "financial_values_are_caller_supplied": True,
            },
            "execution_allowed": False,
        },
        evidence_maturity="unavailable",
        source=f"strategy_templates:{len(frame)}-instrument-components",
    )
    return "\n".join(monthly_decision_template_lines(template))


def _monthly_strategy_alternatives(frame: pd.DataFrame, reference: dict[str, object]) -> dict[str, object]:
    """Use explicit monthly return fields; instrument rows alone are not a basket."""

    result = {
        name: unavailable_monthly_evidence(f"strategy_templates_{name}_portfolio_return_unavailable")
        for name in ("basket", "benchmark", "cash", "no_action")
    }
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return result

    rows = [row.to_dict() for _, row in frame.iterrows()]
    for name in result:
        field = f"monthly_{name}_return"
        if field not in frame.columns:
            continue
        values = [_optional_number(row.get(field)) for row in rows]
        if (
            not values
            or any(value is None for value in values)
            or len({float(value) for value in values if value is not None}) != 1
            or _strategy_metadata_consensus(rows, name) is None
        ):
            continue
        first = rows[0]
        item = _monthly_strategy_alternative(name, float(values[0]), first, reference)
        if item is not None:
            result[name] = item

    weights_column = next((name for name in ("basket_weight", "portfolio_weight") if name in frame.columns), None)
    if weights_column is not None and "instrument_period_return" in frame.columns:
        weights = [_optional_number(row.get(weights_column)) for row in rows]
        returns = [_optional_number(row.get("instrument_period_return")) for row in rows]
        if (
            all(value is not None for value in (*weights, *returns))
            and all(float(value) >= 0 for value in weights if value is not None)
            and math.isclose(sum(float(value) for value in weights if value is not None), 1.0, rel_tol=0.0, abs_tol=1e-9)
            and _strategy_metadata_consensus(rows, "basket") is not None
        ):
            basket = _monthly_strategy_alternative(
                "basket",
                sum(float(weight) * float(value) for weight, value in zip(weights, returns)),
                rows[0],
                reference,
            )
            if basket is not None:
                result["basket"] = basket

    basket = result["basket"]
    benchmark = result["benchmark"]
    cash = result["cash"]
    no_action = result["no_action"]
    if isinstance(basket, dict) and basket.get("status") == "available":
        if (
            isinstance(benchmark, dict)
            and isinstance(cash, dict)
            and isinstance(no_action, dict)
            and benchmark.get("status") == cash.get("status") == no_action.get("status") == "available"
        ):
            basket["benchmark_relative_return"] = float(basket["period_return"]) - float(benchmark["period_return"])
            basket["cash_relative_return"] = float(basket["period_return"]) - float(cash["period_return"])
            basket["no_action_relative_return"] = float(basket["period_return"]) - float(no_action["period_return"])
        else:
            result["basket"] = unavailable_monthly_evidence("strategy_templates_basket_relative_evidence_unavailable")
    return result


def _monthly_strategy_alternative(
    name: str,
    period_return: float,
    row: dict[str, object],
    reference: dict[str, object],
) -> dict[str, object] | None:
    if not math.isfinite(period_return) or period_return < -1:
        return None
    version = row.get(f"monthly_{name}_version")
    source_id = row.get(f"monthly_{name}_source_id")
    source_dataset = row.get(f"monthly_{name}_source_dataset")
    source_digest = row.get(f"monthly_{name}_source_digest")
    as_of = row.get(f"monthly_{name}_as_of")
    known_at = row.get(f"monthly_{name}_known_at")
    horizon = _optional_number(row.get(f"monthly_{name}_horizon_days"))
    if not all(isinstance(value, str) and value.strip() for value in (version, source_id, source_dataset)) or horizon is None or horizon <= 0:
        return None
    selected_reference = _strategy_reference(row, name)
    if selected_reference is None and name in {"benchmark", "cash", "no_action"}:
        return None
    return {
        "status": "available",
        "version": version,
        "source_id": source_id,
        "source_dataset": source_dataset,
        "source_digest": source_digest,
        "as_of": as_of,
        "known_at": known_at,
        "period_return": period_return,
        "horizon_days": horizon,
        "reference_id": selected_reference.get("id") if isinstance(selected_reference, dict) else None,
        "reference_version": selected_reference.get("version") if isinstance(selected_reference, dict) else None,
        "reference_content_hash": selected_reference.get("content_hash") if isinstance(selected_reference, dict) else None,
        "reference_method": "no_trade" if name == "no_action" else None,
        "trust": row.get(f"monthly_{name}_trust"),
        "source_bound": row.get(f"monthly_{name}_source_bound"),
        "execution_allowed": False,
    }


def _strategy_metadata_consensus(rows: list[dict[str, object]], name: str) -> tuple[object, ...] | None:
    fields = [
        f"monthly_{name}_version",
        f"monthly_{name}_source_id",
        f"monthly_{name}_source_dataset",
        f"monthly_{name}_source_digest",
        f"monthly_{name}_as_of",
        f"monthly_{name}_known_at",
        f"monthly_{name}_horizon_days",
        f"monthly_{name}_trust",
        f"monthly_{name}_source_bound",
    ]
    if name != "basket":
        fields.extend(
            (
                f"monthly_{name}_reference_id",
                f"monthly_{name}_reference_version",
                f"monthly_{name}_reference_content_hash",
            )
        )
    if not rows or any(_strategy_value_key(row.get(field)) is None for field in fields for row in rows):
        return None
    expected = tuple(_strategy_value_key(rows[0].get(field)) for field in fields)
    return expected if all(tuple(_strategy_value_key(row.get(field)) for field in fields) == expected for row in rows) else None


def _strategy_reference(row: dict[str, object], name: str) -> dict[str, object] | None:
    value = row.get(f"monthly_{name}_reference")
    if isinstance(value, dict):
        return {"id": value.get("id"), "version": value.get("version"), "content_hash": value.get("content_hash")}
    candidate = {
        "id": row.get(f"monthly_{name}_reference_id"),
        "version": row.get(f"monthly_{name}_reference_version"),
        "content_hash": row.get(f"monthly_{name}_reference_content_hash"),
    }
    return candidate if all(_strategy_value_key(value) is not None for value in candidate.values()) else None


def _strategy_value_key(value: object) -> object:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def _strategy_distribution_component(row: dict[str, object]) -> dict[str, object]:
    values = {
        "q10": _optional_number(row.get("q10_expected_return")),
        "q50": _optional_number(row.get("q50_expected_return")),
        "q90": _optional_number(row.get("q90_expected_return")),
        "net_q10": _optional_number(row.get("net_q10_expected_return")),
        "net_q50": _optional_number(row.get("net_expected_return")),
        "net_q90": _optional_number(row.get("net_q90_expected_return")),
        "horizon": _optional_number(row.get("expected_return_horizon_days")),
    }
    version = row.get("expected_return_distribution_version")
    source_id = row.get("expected_return_source_id")
    source_dataset = row.get("expected_return_source_dataset")
    source_digest = row.get("expected_return_source_digest")
    as_of = row.get("expected_return_as_of")
    known_at = row.get("expected_return_known_at")
    available = (
        all(value is not None for value in values.values())
        and isinstance(version, str)
        and bool(version.strip())
        and isinstance(source_id, str)
        and bool(source_id.strip())
        and isinstance(source_dataset, str)
        and bool(source_dataset.strip())
        and isinstance(source_digest, str)
        and len(source_digest.strip()) == 64
        and isinstance(as_of, str)
        and isinstance(known_at, str)
        and row.get("expected_return_trust") is True
        and row.get("expected_return_source_bound") is True
    )
    if not available:
        return {
            "instrument_id": str(row.get("instrument_id") or "unavailable"),
            "status": "unavailable",
            "reason": "complete_gross_net_distribution_unavailable",
            "execution_allowed": False,
        }
    return {
        "instrument_id": str(row.get("instrument_id") or "unavailable"),
        "status": "available",
        "version": version,
        "source_id": source_id,
        "source_dataset": source_dataset,
        "source_digest": source_digest,
        "as_of": as_of,
        "known_at": known_at,
        "trust": row.get("expected_return_trust"),
        "source_bound": row.get("expected_return_source_bound"),
        "horizon_days": values["horizon"],
        "gross": {"q10": values["q10"], "q50": values["q50"], "q90": values["q90"]},
        "net": {"q10": values["net_q10"], "q50": values["net_q50"], "q90": values["net_q90"]},
        "execution_allowed": False,
    }


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
