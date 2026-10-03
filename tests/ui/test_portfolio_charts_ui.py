from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.components.charts import allocation_donut, portfolio_performance_chart
from etf_cockpit.app.components.overlap import overlap_evidence_panel
from etf_cockpit.app.pages.portfolio import HOLDINGS_MODE_LABELS, holdings_mode_toggle


def _walk(control):
    if control is None:
        return
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def _text(control) -> str:
    return "\n".join(str(getattr(c, "value", "")) for c in _walk(control) if getattr(c, "value", None) is not None)


def test_donut_shows_unknown_and_unmapped_slices() -> None:
    control = allocation_donut([("VWCE", 0.5), ("LYP6", 0.3)], key="d", unknown_weight=0.1, unmapped_weight=0.05)
    text = _text(control)
    assert "Unknown: 10.0%" in text and "Unmapped: 5.0%" in text and "VWCE: 50.0%" in text
    assert control.key == "d"


def test_donut_missing_unknown_is_unavailable_not_zero() -> None:
    text = _text(allocation_donut([("VWCE", 0.5)], key="d", unknown_weight=None, unmapped_weight=None))
    assert "Unknown: Unavailable" in text and "Unmapped: Unavailable" in text
    assert "Unknown: 0.0%" not in text and "Unmapped: 0.0%" not in text


def test_partial_period_marker_and_legend() -> None:
    frame = pd.DataFrame(
        {
            "period_start": ["2026-01-01", "2026-02-01"],
            "period_end": ["2026-01-31", "2026-02-15"],
            "value": [1.0, 1.1],
            "partial": [False, True],
            "status": ["available", "partial"],
        }
    )
    chart = portfolio_performance_chart(frame, metric="twr_index", unit="index", currency="EUR", status="partial", reason=None, aggregation="month")
    assert "partial period (1 marked)" in _text(chart.control)
    clean = frame.assign(partial=[False, False])
    chart = portfolio_performance_chart(clean, metric="twr_index", unit="index", currency="EUR", status="available", reason=None, aggregation="month")
    assert "partial period" not in _text(chart.control)


def test_overlap_unknown_weight_missing_is_unavailable() -> None:
    report = SimpleNamespace(status="missing", coverage=(), pairs=(), concentrations=(), exposures=(), warnings=())
    text = _text(overlap_evidence_panel(report, key="o"))
    assert "unknown/unmapped=Unavailable" in text and "mapped=Unavailable" in text
    present = SimpleNamespace(status="full", coverage=(), pairs=(), concentrations=(), exposures=(), warnings=(), mapped_weight=0.9, unknown_weight=0.1, report_hash="h")
    assert "unknown/unmapped=10.0%" in _text(overlap_evidence_panel(present, key="o"))


def test_holdings_mode_toggle_maps_labels_to_views() -> None:
    chosen: list[str] = []
    toggle = holdings_mode_toggle("look_through", on_change=chosen.append)
    pills = [c for c in _walk(toggle) if str(getattr(c, "key", "")).startswith("portfolio.holdings-mode:")]
    assert len(pills) == len(HOLDINGS_MODE_LABELS) == 3
    assert [p.data for p in pills] == ["unselected", "selected", "unselected"]
    pills[0].on_click(None)
    assert chosen == ["direct"]
