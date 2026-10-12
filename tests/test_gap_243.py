from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import etf_cockpit.application.etf_economics_view as economics_view
from etf_cockpit.application.etf_economics_view import build_etf_economics_panel
from test_etf_economics_production import (
    DECISION_TIME,
    INSTRUMENT_ID,
    _load_production_inputs,
)


def _panel(monkeypatch, records, fund, benchmark, policy, *, horizon_days: int = 3):
    monkeypatch.setattr(economics_view, "load_etf_reference_context", lambda _dataset: pd.DataFrame())
    snapshot = SimpleNamespace(
        etf_economics_records=records,
        etf_fund_total_return=fund,
        etf_benchmark_total_return=benchmark,
        etf_closure_policy=policy,
        etf_metadata=None,
        etf_holdings=pd.DataFrame(),
        data_report=SimpleNamespace(as_of_date=DECISION_TIME),
    )
    return build_etf_economics_panel(snapshot, INSTRUMENT_ID, horizon_days=horizon_days)


def test_gap_243_panel_projects_tracking_error_with_point_in_time_lineage(
    monkeypatch, tmp_path
) -> None:
    records, fund, benchmark, policy, _prices = _load_production_inputs(
        monkeypatch, tmp_path
    )

    panel = _panel(monkeypatch, records, fund, benchmark, policy)
    field = panel["e1"]["tracking_error"]

    assert field["status"] == "available"
    assert field["value"] == panel["tracking_error"]
    assert field["value"] is not None
    assert field["reason"] is None
    assert field["source"] == f"{panel['fund_source_id']} / {panel['benchmark_source_id']}"
    assert field["as_of"] == panel["matched_end"]
    assert field["known_at"] == max(
        panel["fund_total_return_selected_known_at"],
        panel["benchmark_total_return_selected_known_at"],
    )
    assert field["unit"] == "decimal_fraction"


def test_gap_243_tracking_error_fails_closed_without_return_evidence(monkeypatch) -> None:
    panel = _panel(monkeypatch, (), None, None, None)

    field = panel["e1"]["tracking_error"]
    assert field["status"] == "unavailable"
    assert field["value"] is None
    assert field["reason"]
    assert field["source"] is None


def test_gap_243_tracking_error_unavailable_when_sample_is_too_short(
    monkeypatch, tmp_path
) -> None:
    records, fund, benchmark, policy, _prices = _load_production_inputs(
        monkeypatch, tmp_path
    )

    panel = _panel(monkeypatch, records, fund, benchmark, policy, horizon_days=1)
    field = panel["e1"]["tracking_error"]

    assert panel["tracking_difference"] is not None
    assert field["status"] == "unavailable"
    assert field["value"] is None
    assert field["reason"] == "fewer than two matched active daily returns"
    assert field["source"] is None
