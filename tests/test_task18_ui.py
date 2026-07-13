from __future__ import annotations

import pandas as pd


def _text_values(control) -> list[str]:
    values: list[str] = []
    value = getattr(control, "value", None)
    if value is not None:
        values.append(str(value))
    for child in getattr(control, "controls", []) or []:
        values.extend(_text_values(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.extend(_text_values(content))
    for row in getattr(control, "rows", []) or []:
        for cell in getattr(row, "cells", []) or []:
            values.extend(_text_values(getattr(cell, "content", None)))
    return values


def test_instrument_detail_renders_cost_edge_fields(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages import instrument_detail as page_module
    from etf_cockpit.app.selectors import instrument_detail as selector
    from etf_cockpit.services import build_snapshot

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    scoreboard_path = tmp_path / "scoreboard.parquet"
    pd.DataFrame([{
        "display_id": instrument_id,
        "gross_expected_edge_bps": 42.0,
        "estimated_total_cost_bps": 7.0,
        "net_expected_edge_bps": 35.0,
        "edge_to_cost_ratio": 5.0,
        "cost_stress_scenario": "high",
    }]).to_parquet(scoreboard_path, index=False)
    monkeypatch.setattr(selector, "SCOREBOARD_PATH", scoreboard_path)

    control = page_module.instrument_detail_page(None, type("State", (), {"selected_etf": instrument_id, "snapshot": snapshot})())
    rendered = "\n".join(_text_values(control))
    for expected in ("Gross edge", "42.00 bps", "Estimated cost", "7.00 bps", "Net edge", "35.00 bps", "Edge/cost", "5.00", "Cost scenario: high"):
        assert expected in rendered


def test_risk_page_renders_cost_edge_fields_and_unavailable_state(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages import risk as page_module

    scoreboard_path = tmp_path / "scoreboard.parquet"
    pd.DataFrame([{
        "display_id": "A",
        "gross_expected_edge_bps": 42.0,
        "estimated_total_cost_bps": 7.0,
        "net_expected_edge_bps": 35.0,
        "edge_to_cost_ratio": 5.0,
        "cost_stress_scenario": "high",
    }]).to_parquet(scoreboard_path, index=False)
    monkeypatch.setattr(page_module, "SCOREBOARD_PATH", scoreboard_path)
    panel = page_module._friction_edge_panel()
    rendered = "\n".join(_text_values(panel))
    for expected in ("Gross edge", "42.00 bps", "Estimated cost", "7.00 bps", "Net edge", "35.00 bps", "Edge/cost", "5.00", "Cost scenario: high"):
        assert expected in rendered

    monkeypatch.setattr(page_module, "SCOREBOARD_PATH", tmp_path / "missing.parquet")
    unavailable = "\n".join(_text_values(page_module._friction_edge_panel()))
    assert "unavailable" in unavailable.lower()


def test_risk_friction_panel_formats_non_finite_edge_values_as_unavailable(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages import risk as page_module

    scoreboard_path = tmp_path / "scoreboard.parquet"
    pd.DataFrame([{
        "display_id": "A",
        "gross_expected_edge_bps": float("nan"),
        "estimated_total_cost_bps": None,
        "net_expected_edge_bps": float("inf"),
        "edge_to_cost_ratio": float("-inf"),
        "cost_stress_scenario": float("nan"),
    }]).to_parquet(scoreboard_path, index=False)
    monkeypatch.setattr(page_module, "SCOREBOARD_PATH", scoreboard_path)

    rendered = "\n".join(_text_values(page_module._friction_edge_panel()))

    assert "N/A" in rendered
    assert "unavailable" in rendered.lower()
    assert "nan" not in rendered.lower()
    assert "inf" not in rendered.lower()


def test_scores_friction_helpers_hide_non_finite_values() -> None:
    from etf_cockpit.app import theme
    from etf_cockpit.app.components import simple_scores

    for value in (float("nan"), float("inf"), float("-inf")):
        assert simple_scores._number_badge(value) == "N/A"
        assert simple_scores._bps_badge(value) == "N/A"
        assert simple_scores._edge_colour(value) == theme.MUTED
        assert simple_scores._ratio_colour(value) == theme.MUTED

    assert simple_scores._number_badge(1.234) == "1.23"
    assert simple_scores._bps_badge(42.0) == "+42.0 bps"


def test_instrument_detail_friction_non_finite_values_are_unavailable(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages import instrument_detail as page_module
    from etf_cockpit.app.selectors import instrument_detail as selector
    from etf_cockpit.services import build_snapshot

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    scoreboard_path = tmp_path / "scoreboard.parquet"
    pd.DataFrame([{
        "display_id": instrument_id,
        "gross_expected_edge_bps": float("nan"),
        "estimated_total_cost_bps": float("inf"),
        "net_expected_edge_bps": float("-inf"),
        "edge_to_cost_ratio": float("nan"),
        "cost_stress_scenario": float("inf"),
    }]).to_parquet(scoreboard_path, index=False)
    monkeypatch.setattr(selector, "SCOREBOARD_PATH", scoreboard_path)

    model = selector.build_instrument_detail(snapshot, instrument_id)
    friction = model.sections["scores"]["friction"]
    assert friction["status"] == "unavailable"
    assert all(friction[field] is None for field in ("gross_expected_edge_bps", "estimated_total_cost_bps", "net_expected_edge_bps", "edge_to_cost_ratio"))
    assert friction["cost_stress_scenario"] == "unavailable"

    control = page_module._render_crowding_attribution_panel(model.sections)
    rendered = "\n".join(_text_values(control))
    friction_line = next(line for line in rendered.splitlines() if line.startswith("Gross edge:"))
    assert "nan" not in friction_line.lower()
    assert "inf" not in friction_line.lower()
    assert "N/A" in friction_line
