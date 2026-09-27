from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path

import flet as ft
import pytest

from etf_cockpit.app import formatting
from etf_cockpit.app.pages.comparison import comparison_page
from etf_cockpit.app.router import PAGES
from etf_cockpit.app.state import AppState
from etf_cockpit.app.workspaces import load_workspace, save_workspace
from etf_cockpit.services import build_snapshot


_SNAPSHOT_TEMPLATE = None


@pytest.fixture(scope="module", autouse=True)
def _snapshot_template():
    global _SNAPSHOT_TEMPLATE
    _SNAPSHOT_TEMPLATE = build_snapshot()
    yield
    _SNAPSHOT_TEMPLATE = None


def _snapshot_copy():
    assert _SNAPSHOT_TEMPLATE is not None
    snapshot = _SNAPSHOT_TEMPLATE
    return replace(
        snapshot,
        config=copy.deepcopy(snapshot.config),
        prices=snapshot.prices.copy(deep=True),
        holdings=snapshot.holdings.copy(deep=True),
        features=snapshot.features.copy(deep=True),
        latest_features=snapshot.latest_features.copy(deep=True),
        data_report=replace(
            snapshot.data_report,
            issues=copy.deepcopy(snapshot.data_report.issues),
            dataset_metadata=copy.deepcopy(snapshot.data_report.dataset_metadata),
        ),
        signals=[
            replace(
                signal,
                blocked_by=copy.deepcopy(signal.blocked_by),
                warnings=copy.deepcopy(signal.warnings),
                supporting_metrics=copy.deepcopy(signal.supporting_metrics),
                model_versions_used=copy.deepcopy(signal.model_versions_used),
                authority_decision=copy.deepcopy(signal.authority_decision),
                canonical_score=copy.deepcopy(signal.canonical_score),
            )
            for signal in snapshot.signals
        ],
        forecasts=snapshot.forecasts.copy(deep=True),
        model_status=copy.deepcopy(snapshot.model_status),
        model_inventory=copy.deepcopy(snapshot.model_inventory),
        candidate_price_binding=copy.deepcopy(snapshot.candidate_price_binding),
        etf_economics_records=copy.deepcopy(snapshot.etf_economics_records),
        etf_fund_total_return=copy.deepcopy(snapshot.etf_fund_total_return),
        etf_benchmark_total_return=copy.deepcopy(snapshot.etf_benchmark_total_return),
        etf_closure_policy=copy.deepcopy(snapshot.etf_closure_policy),
        benchmark_reference_registry=copy.copy(snapshot.benchmark_reference_registry),
        benchmark_reference_instrument=copy.deepcopy(snapshot.benchmark_reference_instrument),
        benchmark_reference_portfolio_ids=copy.deepcopy(snapshot.benchmark_reference_portfolio_ids),
        vwce_anchor_evidence=copy.copy(snapshot.vwce_anchor_evidence),
        vwce_conversion_evidence=copy.deepcopy(snapshot.vwce_conversion_evidence),
        backtest=replace(
            snapshot.backtest,
            results=snapshot.backtest.results.copy(deep=True),
            equity_curves=snapshot.backtest.equity_curves.copy(deep=True),
            trade_log=snapshot.backtest.trade_log.copy(deep=True),
            signal_log=snapshot.backtest.signal_log.copy(deep=True),
            quality_notes=(
                None
                if snapshot.backtest.quality_notes is None
                else copy.deepcopy(snapshot.backtest.quality_notes)
            ),
            metadata=copy.deepcopy(snapshot.backtest.metadata),
            quality_momentum_evidence=snapshot.backtest.quality_momentum_evidence.copy(deep=True),
        ),
    )


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from _walk(getattr(cell, "content", None))


def _text(control: object) -> str:
    return "\n".join(str(item.value) for item in _walk(control) if isinstance(item, ft.Text))


def test_formatting_is_explicit_and_uses_european_currency_labels() -> None:
    assert formatting.format_number(1234.5) == "1,234.50"
    assert formatting.format_percent(0.1234) == "12.3%"
    assert formatting.format_currency(1234.5) == "EUR 1,234.50"
    assert formatting.format_currency(None) == "N/A"
    assert formatting.format_date(None) == "N/A"


def test_saved_workspace_is_local_versioned_and_reproducible(tmp_path: Path) -> None:
    path = save_workspace("latest comparison", {"instrument_ids": ["VWCE", "SPY"]}, directory=tmp_path)
    assert path.name == "latest_comparison.json"
    payload = load_workspace("latest comparison", directory=tmp_path)
    assert payload == {"execution_allowed": False, "instrument_ids": ["VWCE", "SPY"], "schema_version": "1.0"}
    assert json.loads(path.read_text(encoding="utf-8"))["execution_allowed"] is False


def test_comparison_workspace_is_registered_and_has_explicit_authority_text() -> None:
    assert PAGES["/comparison"][0] == "Comparison"
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    rendered = comparison_page(None, state)
    text = _text(rendered)
    assert "Comparison workspace" in text or "Comparison unavailable" in text
    assert "disabled" in text
    assert "local" in text.casefold()
