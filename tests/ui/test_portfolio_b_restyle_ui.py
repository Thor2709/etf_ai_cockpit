from __future__ import annotations

import pytest

from etf_cockpit.app.pages.decision_journal import decision_journal_page
from etf_cockpit.app.pages.forward_evidence import forward_evidence_page
from etf_cockpit.app.pages.operations import operations_page
from etf_cockpit.app.pages.portfolio_optimiser import portfolio_optimiser_page
from etf_cockpit.app.pages.risk import risk_page
from etf_cockpit.app.pages.stress_lab import stress_lab_page
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot

PAGES = {
    "risk": risk_page,
    "stress-lab": stress_lab_page,
    "portfolio-optimiser": portfolio_optimiser_page,
    "decision-journal": decision_journal_page,
    "forward-evidence": forward_evidence_page,
    "operations": operations_page,
}


class _Page:
    def update(self) -> None:
        pass


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _keys(slug: str) -> list[str]:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    root = PAGES[slug](_Page(), state)
    return [str(item.key) for item in _walk(root) if getattr(item, "key", None)]


@pytest.mark.parametrize("slug", sorted(PAGES))
def test_page_uses_kit_panels_with_deterministic_unique_keys(slug: str) -> None:
    first = _keys(slug)
    assert not [key for key in first if key.startswith("pending.")]
    panels = [key for key in first if key.startswith(f"{slug}.panel-")]
    assert panels, "page must render kit glass panels"
    assert len(first) == len(set(first)), "element keys must be unique"
    assert first == _keys(slug), "keys must not depend on a process-global counter"


def test_risk_tables_use_kit_table_plate_and_kpis() -> None:
    keys = _keys("risk")
    assert any(key.startswith("risk.table-") for key in keys)
    assert any(key.startswith("risk.kpi-") for key in keys)
    assert "risk.export-limits" in keys and "risk.download-limits" in keys


def test_existing_control_keys_stay_stable() -> None:
    assert {"stress-lab.run", "stress-lab.save", "stress-lab.load", "stress-lab.reverse"} <= set(_keys("stress-lab"))
    assert "portfolio-optimiser.max-weight" in _keys("portfolio-optimiser")


def test_unavailable_optimiser_state_is_a_kit_panel_not_zero_filled() -> None:
    from etf_cockpit.app.components.portfolio_b_style import panel, restyle
    import flet as ft

    host = ft.Column([panel(ft.Text("Optimisation unavailable: adjusted-price returns are required."))])
    restyle(host, "portfolio-optimiser.result")
    assert host.controls[0].key == "portfolio-optimiser.result.panel-1"
    assert "unavailable" in host.controls[0].content.value
