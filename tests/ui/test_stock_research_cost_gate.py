"""Missing cost evidence must show the Cost check as unavailable, never as a pass."""
from datetime import date
from types import SimpleNamespace

from etf_cockpit.app.pages.stock_research import _gate_rows


def _cost_row(ter: str, friction: float | None):
    score = SimpleNamespace(risk_friction_10=friction, authority_decision=None)
    view = SimpleNamespace(max_drawdown=-0.1, range_key="1Y", adjusted_share=1.0, gap_count=0, last_date=date(2026, 10, 7))
    return next(row for row in _gate_rows(score, view, {"ter": ter}) if row[1] == "Cost")


def test_cost_without_ter_is_unavailable_not_pass():
    assert _cost_row("", 8.0)[0] is None


def test_cost_with_ter_uses_friction_score():
    assert _cost_row("0.22%", 8.0)[0] is True
    assert _cost_row("0.22%", 2.0)[0] is False
