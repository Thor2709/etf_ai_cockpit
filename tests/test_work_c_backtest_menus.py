from dataclasses import fields
from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.pages import backtests, data_models


def walk(control):
    yield control
    for field in fields(control):
        if field.name.startswith("_") or field.name == "data":
            continue
        value = getattr(control, field.name, None)
        if isinstance(value, ft.Control):
            yield from walk(value)
        elif isinstance(value, (list, tuple)):
            for child in value:
                if isinstance(child, ft.Control):
                    yield from walk(child)


def test_page_card_menus_export_and_show_real_price_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(backtests, "EXPORTS_DIR", tmp_path)
    report = SimpleNamespace(
        results=pd.DataFrame([{"strategy_name": "signal_strategy", "cagr": 0.04}]),
        quality_label="medium", ai_added_value=None,
        equity_curves=pd.DataFrame(), operational_evidence=pd.DataFrame(), trade_log=pd.DataFrame(),
    )
    updates = []
    page = SimpleNamespace(update=lambda: updates.append(True))
    state = SimpleNamespace(snapshot=SimpleNamespace(backtest=report, config=None))
    view = backtests.backtests_page(page, state)
    for label in ("Export strategy results CSV", "Export equity/drawdown CSV"):
        item = next(c for c in walk(view.body) if isinstance(c, ft.PopupMenuItem)
                    and label in [getattr(child, "value", None) for child in walk(c)])
        item.on_click(SimpleNamespace(control=item))
        values = [str(getattr(c, "value", "")) for c in walk(view.body)]
        if "strategy" in label:
            assert any("Export complete:" in value and "backtest_strategy_results.csv" in value for value in values)
        else:
            assert any("Export complete:" in value and "backtest_equity_drawdown.csv" in value and "(0 rows)" in value for value in values)
    assert updates
    assert (tmp_path / "backtest_strategy_results.csv").is_file()

    page = SimpleNamespace(update=lambda: None)
    snapshot = SimpleNamespace(model_status={}, model_inventory=(),
                               prices=pd.DataFrame({"etf_id": ["VWCE"], "date": ["2026-07-09"]}))
    view = data_models.data_models_page(page, SimpleNamespace(snapshot=snapshot))
    controls = list(walk(view.body))
    item = next(c for c in controls if isinstance(c, ft.PopupMenuItem)
                and "Show table" in [getattr(child, "value", None) for child in walk(c)])
    item.on_click(SimpleNamespace(control=item))
    table = next(c for c in controls if isinstance(getattr(c, "data", None), dict) and c.data.get("kit") == "Disclosure"
                 and c.data.get("label") == "Price rows")
    assert table.visible
    assert table.controls[1].visible
    assert "VWCE" in [getattr(c, "value", None) for c in walk(table)]

