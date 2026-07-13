from __future__ import annotations

import pandas as pd

from etf_cockpit.app.components import charts, tables
from etf_cockpit.data.export_tables import table_columns


def test_export_table_contract_has_stable_columns_and_textual_status() -> None:
    frame = pd.DataFrame({"instrument_id": ["A"], "status": ["unavailable"]})
    assert table_columns(frame) == ("instrument_id", "status")


def test_accessible_table_exposes_search_sort_and_non_colour_status() -> None:
    frame = pd.DataFrame({"instrument_id": ["B", "A"], "status": ["blocked", "ok"]})
    assert callable(getattr(tables, "accessible_table", None))
    table = tables.accessible_table(frame, table_id="risk", searchable=True, sortable=True)
    assert table.search_label == "Search risk"
    assert table.sortable_columns == ("instrument_id", "status")
    assert table.status_text == "2 rows; status is shown as text"


def test_price_and_backtest_charts_have_semantic_labels_and_unavailable_state() -> None:
    assert callable(getattr(charts, "history_chart", None))
    assert callable(getattr(charts, "equity_drawdown_chart", None))
    assert charts.history_chart(pd.DataFrame(), title="Price history").label == "Price history (unavailable)"
    frame = pd.DataFrame({"date": ["2026-07-01"], "equity": [1.0], "drawdown": [0.0]})
    chart = charts.equity_drawdown_chart(frame)
    assert chart.label == "Backtest equity and drawdown"
    assert chart.export_table_id == "backtest_equity_drawdown"


def test_accessible_table_search_and_sort_callbacks_are_functional() -> None:
    frame = pd.DataFrame({"instrument_id": ["B", "A"], "status": ["blocked", "ok"]})
    table = tables.accessible_table(frame, table_id="risk")
    assert callable(table.search_callback)
    assert callable(table.sort_callback)
    assert table.search("A")["instrument_id"].tolist() == ["A"]
    assert table.sort("instrument_id")["instrument_id"].tolist() == ["A", "B"]


def test_chart_descriptors_expose_observable_series_data() -> None:
    history = charts.history_chart(pd.DataFrame({"date": ["2026-07-01"], "adjusted_close": [101.5]}))
    assert history.available is True
    assert history.data["adjusted_close"] == (101.5,)
    equity = charts.equity_drawdown_chart(pd.DataFrame({"date": ["2026-07-01"], "equity": [1.0], "drawdown": [0.0]}))
    assert equity.data["equity"] == (1.0,)
    assert equity.data["drawdown"] == (0.0,)
