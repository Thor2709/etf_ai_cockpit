from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.components.shell.footer import build_footer
from etf_cockpit.app.components.shell.page_view import PageChrome
from etf_cockpit.app.components.shell.status import FooterValues
from etf_cockpit.app.pages import comparison
from etf_cockpit.app.pages.stock_research import gate_sub_line


def test_failed_gate_states_its_reason_not_the_pass_wording() -> None:
    assert gate_sub_line(True, "Valuation context is available") == "Valuation context is available"
    assert gate_sub_line(False, "Valuation context is available") == "Valuation context is not available"
    assert gate_sub_line(False, "No score warnings") == "Not met: No score warnings"
    assert gate_sub_line(False, "") == "Reason unavailable"


def _walk(control):
    yield control
    for attr in ("content", "controls"):
        child = getattr(control, attr, None)
        for item in ([child] if isinstance(child, ft.Control) else child or []):
            if isinstance(item, ft.Control):
                yield from _walk(item)


def _texts(control) -> list[str]:
    return [c.value for c in _walk(control) if isinstance(c, ft.Text)]


def _values() -> FooterValues:
    fields = {name: "x" for name in FooterValues.__dataclass_fields__}
    return FooterValues(**{**fields, "quality_kind": "ok", "quality_reason": None, "as_of_reason": None,
                           "forecast_reason": None, "sample_data": False})


def test_footer_drops_whole_items_at_narrow_widths_and_keeps_the_authority() -> None:
    footer = build_footer(_values(), depth_label="Medium", profile_text="EUR · 3y · balanced", on_data_health=lambda: None,
                          on_depth=lambda: None, on_settings=lambda: None, compact=True, width=1100)
    visible = {c.key for c in _walk(footer.control) if getattr(c, "key", None) and c.visible}
    hidden = {c.key for c in _walk(footer.control) if getattr(c, "key", None) and not c.visible}
    assert "shell.safety.execution" in visible and "shell.safety.execution-authority" in visible
    assert hidden, "lowest-priority items must hide whole instead of being cut mid-word"
    footer.set_width(1920)
    assert all(c.visible for c in _walk(footer.control) if getattr(c, "key", None) and c.key.startswith("shell."))


def test_comparison_missing_cells_use_one_dash_form() -> None:
    def score(**kw):
        base = dict(display_id="AAA", name="A", latest_price=None, final_score_10=None, evidence_quality_10=None,
                    risk_friction_10=None, instrument_period_return=None, cash_return=None, excess_over_cash=None,
                    cash_comparison_status="cash_comparison_unavailable_x", latest_date=None, final_action="x")
        base.update(kw)
        return SimpleNamespace(**base)

    table = comparison._comparison_table(score(), score(display_id="BBB"))
    shown = _texts(table)
    for form in ("Unavailable", "N/A", "unavailable", "n/a"):
        assert form not in shown  # no table cell uses these forms
    assert "—" in shown
