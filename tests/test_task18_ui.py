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


def _walk_controls(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)
    for row in getattr(control, "rows", []) or []:
        for cell in getattr(row, "cells", []) or []:
            yield from _walk_controls(getattr(cell, "content", None))


def _chip_colour(control, label: str) -> str | None:
    for candidate in _walk_controls(control):
        content = getattr(candidate, "content", None)
        controls = getattr(content, "controls", []) if content is not None else []
        if len(controls) >= 2 and getattr(controls[1], "value", None) == label:
            return getattr(controls[0], "bgcolor", None)
    return None


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


def test_score_tile_renders_distribution_cost_and_non_execution_state() -> None:
    from dataclasses import replace

    from etf_cockpit.app.components.simple_scores import _score_tile
    from etf_cockpit.signals.simple_scores import build_candidate_simple_scores

    report = pd.DataFrame(
        [{
            "instrument_id": "ABC",
            "name": "ABC Test Stock",
            "yahoo_symbol": "ABC.DE",
            "latest_date": "2026-07-10",
            "latest_price": 100.0,
            "return_3m": 0.10,
            "return_6m": 0.18,
            "return_12m": 0.25,
            "volatility_60d_ann": 0.18,
            "current_drawdown": -0.04,
            "sma50_signal": True,
            "sma200_signal": True,
            "blocked_by": "",
        }]
    )
    score = replace(
        build_candidate_simple_scores(report, pd.DataFrame())[0],
        q10_expected_return=-0.02,
        q50_expected_return=0.05,
        q90_expected_return=0.12,
        expected_return_horizon_days=60,
        net_expected_return=0.048,
        expected_return_order_value_eur=1_000.0,
        expected_return_cost_bps=20.0,
        expected_return_cost_ratio=24.0,
        expected_return_source_dataset="forecast_return_distribution",
        friction_status="available",
    )

    rendered = "\n".join(_text_values(_score_tile(score, [])))

    assert "Expected-return distribution (60d)" in rendered
    assert "-2.0% / +5.0% / +12.0% gross" in rendered
    assert "EUR 1,000.00 order" in rendered
    assert "+20.0 bps" in rendered
    assert "24.00" in rendered
    assert score.execution_allowed is False
    assert "Place order" not in rendered


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


def test_risk_holdings_quality_panel_exposes_row_summary_for_packaged_accessibility() -> None:
    from etf_cockpit.app.pages import risk as page_module

    holdings = pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "as_of_date": ["2026-05-31"],
            "completeness": ["partial"],
            "freshness": ["fresh"],
            "confidence": [0.55],
            "authority": ["issuer"],
            "score_eligible": [False],
        }
    )

    rendered = "\n".join(_text_values(page_module._holdings_quality_panel(holdings)))

    assert "VWCE" in rendered
    assert "2026-05-31" in rendered
    assert "partial" in rendered
    assert "score_eligible=False" in rendered


def test_etf_disclosures_table_reads_csv_mirror_when_parquet_is_unavailable(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages import trust_evidence as page_module

    parquet_path = tmp_path / "fund_holdings.parquet"
    csv_path = tmp_path / "fund_holdings.csv"
    pd.DataFrame(
        [{
            "instrument_id": "VWCE",
            "as_of_date": "2026-05-31",
            "source": "issuer",
            "completeness": "partial",
            "freshness": "fresh",
            "confidence": 0.55,
            "authority": "issuer",
            "score_eligible": False,
            "source_id": "issuer:vanguard:vwce",
        }]
    ).to_csv(csv_path, index=False)

    monkeypatch.setattr(page_module, "FUND_HOLDINGS_PATH", parquet_path)
    frame = page_module._read_frame(parquet_path)

    assert frame.to_dict(orient="records") == [{
        "instrument_id": "VWCE",
        "as_of_date": "2026-05-31",
        "source": "issuer",
        "completeness": "partial",
        "freshness": "fresh",
        "confidence": 0.55,
        "authority": "issuer",
        "score_eligible": False,
        "source_id": "issuer:vanguard:vwce",
    }]


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


def test_risk_crowding_counts_distinct_explicit_warning_cluster_ids(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages import risk as page_module

    crowding_path = tmp_path / "clusters.parquet"
    pd.DataFrame(
        [
            {"instrument_id": "A", "cluster_id": "cluster_singleton", "crowding_warning": "no_cluster_warning"},
            {"instrument_id": "B", "cluster_id": "cluster_pair", "crowding_warning": "high_correlation_cluster_warning"},
            {"instrument_id": "C", "cluster_id": "cluster_pair", "crowding_warning": "high_correlation_cluster_warning"},
            {"instrument_id": "D", "cluster_id": "cluster_theme", "crowding_warning": "no_theme_concentration_warning"},
        ]
    ).to_parquet(crowding_path, index=False)
    monkeypatch.setattr(page_module, "CORRELATION_CLUSTERS_PATH", crowding_path)
    monkeypatch.setattr(page_module, "BENCHMARK_ATTRIBUTION_PATH", tmp_path / "missing-attribution.parquet")

    rendered = "\n".join(_text_values(page_module._crowding_attribution_panel()))

    assert "Clusters with warnings: 1" in rendered


def test_scores_crowding_no_cluster_warning_is_not_amber() -> None:
    from dataclasses import replace

    from etf_cockpit.app import theme
    from etf_cockpit.app.components import simple_scores
    from etf_cockpit.core.config import load_config
    from etf_cockpit.signals.simple_scores import build_simple_instrument_scores

    pending = build_simple_instrument_scores(load_config(), [], pd.DataFrame(), pd.DataFrame())[0]
    score = replace(pending, crowding_warning="no_cluster_warning")

    colour = _chip_colour(simple_scores._score_tile(score, []), "Crowding")

    assert colour == theme.CYAN

    for warning_state in ("high_correlation_cluster_warning", "theme_concentration_warning"):
        warning_score = replace(pending, crowding_warning=warning_state)
        assert _chip_colour(simple_scores._score_tile(warning_score, []), "Crowding") == theme.AMBER
