from __future__ import annotations

import pandas as pd
import inspect
import pytest

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


def test_accessible_table_renders_structured_cells_without_scalar_missing_checks() -> None:
    records = [{"date": "2026-06-03", "return": -0.08}]
    other_records = [{"date": "2026-06-04", "return": -0.07}]
    table = tables.accessible_table(
        pd.DataFrame({"strategy": ["B", "A"], "largest_negative_contribution_periods": [records, other_records]}),
        table_id="backtests.strategy-results",
    )

    assert table.control.rows[0].cells[1].content.value == str(records)
    assert table.sortable_columns == ("strategy",)
    assert table.control.columns[1].on_sort is None
    assert table.control.columns[1].label.tooltip is None
    pd.testing.assert_frame_equal(table.sort("largest_negative_contribution_periods"), table.frame)


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
    assert table.search_control is not None
    assert callable(table.search_control.on_change)
    assert any(callable(column.on_sort) for column in table.control.columns)


def test_accessible_table_callbacks_refresh_visible_control_and_status() -> None:
    from types import SimpleNamespace

    frame = pd.DataFrame({"instrument_id": ["B", "A"], "status": ["blocked", "ok"]})
    table = tables.accessible_table(frame, table_id="risk")
    updates: list[int] = []
    table.control.update = lambda: updates.append(len(table.control.rows))
    status_updates: list[str] = []
    table.status_control.update = lambda: status_updates.append(table.status_control.value)

    table.search_control.on_change(SimpleNamespace(data="A"))
    assert len(table.control.rows) == 1
    assert table.status_control.value.startswith("1 rows")
    assert updates == [1]
    assert status_updates == ["1 rows; status is shown as text"]

    table.control.columns[0].on_sort(SimpleNamespace(ascending=False))
    assert len(table.control.rows) == 2
    assert table.status_control.value.startswith("2 rows")
    assert updates[-1] == 2
    assert status_updates[-1] == "2 rows; status is shown as text"


def test_accessible_table_search_treats_regex_punctuation_literally_and_updates() -> None:
    from types import SimpleNamespace

    frame = pd.DataFrame({"label": ["A[1]", "A(2)", "plain"]})
    table = tables.accessible_table(frame, table_id="risk")
    updates: list[int] = []
    table.control.update = lambda: updates.append(len(table.control.rows))

    table.search_control.on_change(SimpleNamespace(data="["))
    assert table.control.rows and len(table.control.rows) == 1
    assert table.status_control.value.startswith("1 rows")

    table.search_control.on_change(SimpleNamespace(data="("))
    assert len(table.control.rows) == 1
    assert table.status_control.value.startswith("1 rows")
    assert updates == [1, 1]


def test_accessible_table_does_not_mask_unrelated_runtime_errors() -> None:
    from types import SimpleNamespace

    frame = pd.DataFrame({"label": ["A[1]"]})
    table = tables.accessible_table(frame, table_id="risk")
    table.control.update = lambda: (_ for _ in ()).throw(
        RuntimeError("cache was added to the page but persistence failed")
    )
    with pytest.raises(RuntimeError, match="persistence failed"):
        table.search_control.on_change(SimpleNamespace(data="["))

    table = tables.accessible_table(frame, table_id="risk")
    table.status_control.update = lambda: (_ for _ in ()).throw(
        RuntimeError("status update added to the page but persistence failed")
    )
    with pytest.raises(RuntimeError, match="persistence failed"):
        table.search_control.on_change(SimpleNamespace(data="["))


def test_accessible_table_only_masks_exact_detached_control_error() -> None:
    from types import SimpleNamespace

    frame = pd.DataFrame({"label": ["A[1]"]})
    table = tables.accessible_table(frame, table_id="risk")
    table.control.update = lambda: (_ for _ in ()).throw(
        RuntimeError("Control must be added to the page first")
    )
    table.search_control.on_change(SimpleNamespace(data="["))

    table = tables.accessible_table(frame, table_id="risk")
    table.control.update = lambda: (_ for _ in ()).throw(
        RuntimeError("Control must be added to the page first: persistence failed")
    )
    with pytest.raises(RuntimeError, match="persistence failed"):
        table.search_control.on_change(SimpleNamespace(data="["))


def test_chart_descriptors_expose_observable_series_data() -> None:
    history = charts.history_chart(pd.DataFrame({"date": ["2026-07-01"], "adjusted_close": [101.5]}))
    assert history.available is True
    assert history.data["adjusted_close"] == (101.5,)
    equity = charts.equity_drawdown_chart(pd.DataFrame({"date": ["2026-07-01"], "equity": [1.0], "drawdown": [0.0]}))
    assert equity.data["equity"] == (1.0,)
    assert equity.data["drawdown"] == (0.0,)


def test_backtests_page_connects_real_chart_and_accessible_table_helpers() -> None:
    from etf_cockpit.app.pages.backtests import backtests_page

    source = inspect.getsource(backtests_page)
    assert "history_chart" in source
    assert "accessible_table" in source
    assert "recent_evidence" in source


def test_settings_page_documents_issue_0044_packaged_update_workflow() -> None:
    from etf_cockpit.app.pages.settings import settings_page

    source = inspect.getsource(settings_page)
    assert "ISSUE-0044" in source
    assert "packaged-app update workflow" in source
    assert "checksum" in source
