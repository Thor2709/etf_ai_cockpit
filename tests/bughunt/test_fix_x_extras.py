"""Focused tests for the leftover items R1, R2, R3 and S11-top."""

from __future__ import annotations

import json
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.portfolio.valuation import SNAPSHOT_COLUMNS


def _snapshot_rows(days: list[str], values: list[float]) -> pd.DataFrame:
    rows = []
    for index, (day, value) in enumerate(zip(days, values)):
        previous = values[index - 1] if index else None
        rows.append(
            dict(
                dict.fromkeys(SNAPSHOT_COLUMNS, 0.0),
                date=day,
                total_value=value,
                securities_value=value,
                invested_capital=100.0,
                period_return=float("nan") if previous is None else value / previous - 1.0,
                investment_pnl=float("nan") if previous is None else value - previous,
                valuation_status="available",
                flow_status="available",
                availability_evidence="timestamped",
                missing_reasons="",
                execution_allowed=False,
            )
        )
    return pd.DataFrame(rows)


# R1 ---------------------------------------------------------------------------------------


def test_r1_range_first_day_pnl_uses_pre_range_anchor():
    from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series

    frame = _snapshot_rows(
        ["2025-01-30", "2025-01-31", "2025-02-03", "2025-02-04"], [100.0, 100.0, 110.0, 121.0]
    )
    result = build_portfolio_performance_series(
        frame,
        metric="investment_pnl",
        aggregation="month",
        date_range="custom",
        custom_start="2025-02-03",
        custom_end="2025-02-04",
    )
    assert result.points[-1].value == pytest.approx(21.0)  # 10 (first in-range day) + 11
    assert result.points[-1].status == "available"


def test_r1_range_first_day_twr_return_uses_pre_range_anchor():
    from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series

    frame = _snapshot_rows(
        ["2025-01-30", "2025-01-31", "2025-02-03", "2025-02-04"], [100.0, 100.0, 110.0, 121.0]
    )
    kwargs = dict(metric="twr_return", date_range="custom", custom_start="2025-02-03", custom_end="2025-02-04")
    month = build_portfolio_performance_series(frame, aggregation="month", **kwargs)
    assert month.points[-1].value == pytest.approx(0.21)
    day = build_portfolio_performance_series(frame, aggregation="day", **kwargs)
    assert day.points[0].value == pytest.approx(0.10)


def test_r1_non_adjacent_anchor_fails_closed():
    from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series

    frame = _snapshot_rows(["2025-01-30", "2025-02-03", "2025-02-04"], [100.0, 110.0, 121.0])
    result = build_portfolio_performance_series(
        frame,
        metric="investment_pnl",
        aggregation="month",
        date_range="custom",
        custom_start="2025-02-03",
        custom_end="2025-02-04",
    )
    assert result.points[-1].value is None  # 2025-01-31 is missing: no gap-spanning P&L


def test_r1_inception_range_has_no_invented_first_day_pnl():
    from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series

    frame = _snapshot_rows(["2025-02-03", "2025-02-04"], [110.0, 121.0])
    result = build_portfolio_performance_series(frame, metric="investment_pnl", aggregation="month")
    assert result.points[-1].value == pytest.approx(11.0)


# R2 ---------------------------------------------------------------------------------------


def test_r2_rediscovered_official_filing_replaces_row_stored_under_legacy_id(tmp_path):
    import hashlib

    from etf_cockpit.data.oam_adapters import (
        OAMDiscoveryResult,
        OAMRecord,
        write_oam_discovery_registry,
    )

    def record(source_id: str, **overrides) -> OAMRecord:
        values = dict(
            provider_id="nl-afm",
            country="NL",
            issuer="Acme NV",
            isin="",
            title="Annual report",
            document_type="annual",
            published_at="2025-03-01",
            available_at="2025-03-01",
            availability_precision="date",
            source_url="https://example.invalid/oam",
            document_url="https://example.invalid/a.pdf",
            source_id=source_id,
            source_authority="official_oam",
            terms_url="",
            coverage_status="available",
            identity_status="issuer_only_manual_review",
        )
        values.update(overrides)
        return OAMRecord(**values)

    legacy_id = "oam:" + hashlib.sha256(
        "|".join(("nl-afm", "https://example.invalid/oam", "", "Annual report", "2025-03-01")).encode()
    ).hexdigest()[:24]
    other_filing = record("oam:" + "f" * 24, issuer="Other NV", document_url="https://example.invalid/o.pdf")
    destination = tmp_path / "oam.parquet"

    def write(*records: OAMRecord) -> pd.DataFrame:
        write_oam_discovery_registry(
            OAMDiscoveryResult("nl-afm", "available", "ok", records=records), destination=destination
        )
        return pd.read_parquet(destination)

    write(record(legacy_id), other_filing)  # registry persisted before the identity change
    new_id = "oam:" + "a" * 24
    frame = write(record(new_id))
    acme = frame[frame["issuer"].eq("Acme NV")]
    assert list(acme["source_id"]) == [new_id]
    assert legacy_id not in set(frame["source_id"])
    assert "Other NV" in set(frame["issuer"])  # a different filing is never dropped by the alias


# R3 ---------------------------------------------------------------------------------------


def test_r3_dimensional_facts_never_reach_roic():
    from etf_cockpit.data.capital_efficiency import capital_efficiency_analysis
    from test_stock_research import _statements

    frame = _statements()
    consolidated = capital_efficiency_analysis(frame, instrument_id="ACME", tax_rate=0.25)["reported"]["metrics"]
    template = frame[frame["fiscal_year"] == 2026].iloc[0].to_dict()
    segment = [
        {**template, "canonical_metric": "operating_income", "value": 999.0, "source_id": "zz-segment",
         "dimensions": json.dumps({"StatementBusinessSegmentsAxis": "Cloud"}, sort_keys=True)},
        {**template, "canonical_metric": "equity", "value": 1.0, "source_id": "zz-segment",
         "dimensions": json.dumps({"StatementBusinessSegmentsAxis": "Cloud"}, sort_keys=True)},
    ]
    mixed = pd.concat([frame, pd.DataFrame(segment)], ignore_index=True)
    mixed["dimensions"] = mixed.get("dimensions", pd.Series(index=mixed.index, dtype=object)).fillna("")
    result = capital_efficiency_analysis(mixed, instrument_id="ACME", tax_rate=0.25)["reported"]["metrics"]
    for name in ("nopat", "invested_capital", "roic"):
        assert result[name]["value"] == consolidated[name]["value"]
        assert "zz-segment" not in result[name].get("source_ids", ())


# S11-top ----------------------------------------------------------------------------------


def _walk(control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        if isinstance(child, ft.Control):
            yield from _walk(child)


def _pill_text(view, key):
    pill = next(item for item in _walk(view) if getattr(item, "key", None) == key)
    return [str(item.value) for item in _walk(pill) if isinstance(item, ft.Text)], pill.data


def test_s11_top_shell_topbar_shows_saved_settings_controls(tmp_path):
    from etf_cockpit.app.router import build_shell
    from etf_cockpit.app.state import AppState
    from etf_cockpit.application.settings import load_settings_bundle, preview_settings, save_settings
    from etf_cockpit.application.snapshot_builder import build_snapshot

    bundle = load_settings_bundle(tmp_path)
    candidate = bundle.model_copy(
        update={
            "controls": bundle.controls.model_copy(
                update={"horizon": "2Y", "output_currency": "USD", "risk_profile": "aggressive"}
            )
        }
    )
    preview_settings(candidate, expected_revision=bundle.revision, root=tmp_path)
    save_settings(candidate, expected_revision=bundle.revision, root=tmp_path)

    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf, settings_root=tmp_path)
    view = build_shell(SimpleNamespace(width=1920, route="/"), state, "/")
    assert _pill_text(view, "shell.as-of.horizon") == (["Horizon", "2Y"], "available")
    assert _pill_text(view, "shell.as-of.currency") == (["Currency", "USD"], "available")
    assert _pill_text(view, "shell.as-of.risk-profile") == (["Risk profile", "aggressive"], "available")

    unbound = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    unbound_view = build_shell(SimpleNamespace(width=1920, route="/"), unbound, "/")
    assert _pill_text(unbound_view, "shell.as-of.horizon")[1] == "unavailable"
