from __future__ import annotations

from etf_cockpit.signals.research_states import AuthorityDecision, GateResult
from etf_cockpit.app.components.governance_badges import build_gate_summary


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_gate_drawer_is_keyboard_addressable() -> None:
    decision = AuthorityDecision(
        gates=(GateResult(gate_id="evidence", order=1, severity="notice", passed=True, message="Evidence present"),),
        execution_allowed=False,
    )
    def open_help(_event: object) -> None:
        return None

    buttons = [item for item in _walk(build_gate_summary(decision, open_help=open_help)) if getattr(item, "key", "") == "authority-gates.view-all"]
    assert len(buttons) == 1
    assert buttons[0].disabled is False
    assert buttons[0].tooltip


def test_gate_summary_has_real_navigation_callback() -> None:
    decision = AuthorityDecision(
        gates=(GateResult(gate_id="evidence", order=1, severity="notice", passed=True, message="Evidence present"),),
        execution_allowed=False,
    )
    def open_help(_event: object) -> None:
        return None

    buttons = [item for item in _walk(build_gate_summary(decision, open_help=open_help)) if getattr(item, "key", "") == "authority-gates.view-all"]
    assert callable(buttons[0].on_click)
    assert buttons[0].on_click.__name__ == "open_help"
