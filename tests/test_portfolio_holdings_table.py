from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.portfolio.holdings_table import build_portfolio_holdings_table


_DATE = "2026-09-30"


def _distribution(horizon: int, offset: float = 0.0) -> dict[str, object]:
    gross = {
        f"q{level:02d}_return": value + offset
        for level, value in zip((5, 10, 25, 50, 75, 90, 95), (-0.2, -0.1, -0.05, 0.05, 0.1, 0.2, 0.25), strict=True)
    }
    net = {field: value - 0.01 for field, value in gross.items()}
    return {
        "status": "available",
        "reason": None,
        "horizon_days": horizon,
        "decision_time": _DATE,
        "gross_quantiles": gross,
        "net_quantiles": net,
        "net_status": "available",
        "net_reason": None,
        "return_components": {"price_return": 0.04, "income_return": 0.01, "fx_return": 0.0},
    }


def _analysis_row(instrument_id: str, *, rank: int = 2) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "analysis_run_id": "run-1",
        "scores": {"evidence": 7.1, "quality": 6.4, "risk": 5.8},
        "rank": rank,
        "peer_rank": 1,
        "action": "review",
        "blockers": ("freshness_review",),
        "coverage": 0.9,
    }


def _inputs(
    holdings: list[dict[str, object]] | None = None,
    *,
    analysis_date: str = _DATE,
    policy_id: str = "policy-1",
    run_id: str = "run-1",
) -> dict[str, object]:
    positions = holdings or [
        {
            "instrument_id": "AAA",
            "asset_type": "stock",
            "quantity": 2,
            "currency": "EUR",
            "local_value": 200.0,
            "market_value_eur": 200.0,
            "current_weight": 1.0,
            "cost_basis_eur": 180.0,
            "realised_pnl_eur": 4.0,
            "unrealised_pnl_eur": 16.0,
            "income_eur": 3.0,
            "fees_eur": 1.0,
        }
    ]
    total = sum(float(row["market_value_eur"]) for row in positions)
    return {
        "holdings": pd.DataFrame(positions),
        "portfolio_snapshot": {
            "portfolio_id": "portfolio-1",
            "snapshot_id": "snapshot-1",
            "as_of": _DATE,
            "source_checksum": "checksum-1",
            "policy_id": "policy-1",
        },
        "performance_snapshot": {
            "date": _DATE,
            "snapshot_id": "snapshot-1",
            "securities_value": total,
            "policy_id": "policy-1",
        },
        "analysis_snapshot": {
            "analysis_run_id": run_id,
            "run_id": run_id,
            "decision_time": analysis_date,
            "status": "complete",
            "policy_id": policy_id,
            "policy_status": "available",
            "rows": {row["instrument_id"]: _analysis_row(str(row["instrument_id"])) for row in positions},
            "distributions": {
                str(row["instrument_id"]): {30: _distribution(30), 90: _distribution(90, 0.2)}
                for row in positions
            },
        },
        "currency_projection": SimpleNamespace(
            available=True,
            currency="EUR",
            reference_rate=1.0,
            decision_time=_DATE,
            reason=None,
        ),
    }


def _build(inputs: dict[str, object], **overrides: object) -> dict[str, object]:
    arguments = {
        "portfolio_snapshot": inputs["portfolio_snapshot"],
        "performance_snapshot": inputs["performance_snapshot"],
        "analysis_snapshot": inputs["analysis_snapshot"],
        "horizon_days": 30,
        "output_currency": "EUR",
        "currency_projection": inputs["currency_projection"],
    }
    arguments.update(overrides)
    return build_portfolio_holdings_table(inputs["holdings"], **arguments)  # type: ignore[arg-type]


def test_analysis_values_match_exact_run_snapshot() -> None:
    inputs = _inputs()
    projection = _build(inputs)
    row = projection["rows"][0]

    assert projection["analysis_run_id"] == "run-1"
    assert row["scores"]["evidence"]["value"] == 7.1
    assert row["scores"]["quality"]["value"] == 6.4
    assert row["scores"]["risk"]["value"] == 5.8
    assert row["rank"]["value"] == 2
    assert row["peer_rank"]["value"] == 1
    assert row["action"]["value"] == "review"
    assert row["blockers"]["value"] == ("freshness_review",)
    assert row["forecast_quantiles"]["gross_q50_return"]["value"] == 0.05


def test_exact_horizon_updates_return_and_all_gain_loss_quantiles() -> None:
    inputs = _inputs()
    short = _build(inputs, horizon_days=30)["rows"][0]
    long = _build(inputs, horizon_days=90)["rows"][0]

    assert short["horizon_days"] == 30
    assert long["horizon_days"] == 90
    assert short["expected_return"]["value"] == 0.04
    assert long["expected_return"]["value"] == 0.24
    for level in (5, 10, 25, 50, 75, 90, 95):
        key = f"net_q{level:02d}_return"
        assert short["forecast_quantiles"][key]["value"] != long["forecast_quantiles"][key]["value"]
        assert short["expected_gain_loss"][key]["value"] == short["value"]["value"] * short["forecast_quantiles"][key]["value"]
        assert long["expected_gain_loss"][key]["value"] == long["value"]["value"] * long["forecast_quantiles"][key]["value"]


def test_missing_stale_or_mismatched_analysis_blocks_proposal_handoff() -> None:
    base = _inputs()
    cases = []
    missing = dict(base)
    missing["analysis_snapshot"] = None
    cases.append((missing, "analysis_missing_or_incomplete"))
    stale = _inputs()
    stale["analysis_snapshot"]["status"] = "stale"  # type: ignore[index]
    cases.append((stale, "analysis_missing_or_incomplete"))
    stale = _inputs(analysis_date="2026-09-29")
    cases.append((stale, "portfolio_analysis_date_mismatch"))
    policy = _inputs(policy_id="policy-old")
    cases.append((policy, "portfolio_analysis_policy_mismatch"))
    wrong_run = _inputs(run_id="run-old")
    wrong_run["analysis_snapshot"]["run_id"] = "run-1"  # type: ignore[index]
    cases.append((wrong_run, "analysis_run_id_mismatch"))
    wrong_snapshot = dict(base)
    wrong_snapshot["portfolio_snapshot"] = dict(base["portfolio_snapshot"], snapshot_id="snapshot-old")  # type: ignore[arg-type]
    cases.append((wrong_snapshot, "portfolio_performance_snapshot_identity_mismatch"))
    future_model = _inputs()
    future_model["analysis_snapshot"]["distributions"]["AAA"][30]["decision_time"] = "2026-10-01"  # type: ignore[index]
    cases.append((future_model, "forecast_distribution_postdates_portfolio_snapshot"))

    for inputs, expected_reason in cases:
        projection = _build(inputs)
        assert projection["proposal_handoff_allowed"] is False
        assert expected_reason in (*projection["reasons"], *projection["conflicts"])
        assert projection["proposal_handoff_reason"] is not None


def test_holding_values_reconcile_to_selected_performance_snapshot() -> None:
    inputs = _inputs()
    projection = _build(inputs)
    row = projection["rows"][0]

    assert projection["performance_snapshot"]["reconciliation"] == {
        "status": "available",
        "value": True,
        "reason": None,
    }
    assert row["quantity"]["value"] == 2
    assert row["value"]["value"] == 200.0
    assert row["weight"]["value"] == 1.0
    assert row["cost_basis"]["value"] == 180.0
    assert row["realised_pnl"]["value"] == 4.0
    assert row["unrealised_pnl"]["value"] == 16.0
    assert row["income"]["value"] == 3.0
    assert row["fees"]["value"] == 1.0
    assert row["portfolio_snapshot_id"] == "snapshot-1"
    assert row["performance_snapshot_date"] == _DATE
    assert row["analysis_run_id"] == "run-1"


def test_mixed_asset_sorting_filtering_keeps_asset_columns_and_unavailable_cells() -> None:
    positions = [
        {"instrument_id": "STOCK", "asset_type": "stock", "quantity": 1, "market_value_eur": 100.0, "current_weight": 0.5},
        {"instrument_id": "ETF", "asset_type": "etf", "quantity": 2, "market_value_eur": 60.0, "current_weight": 0.3},
        {"instrument_id": "BOND", "asset_type": "bond", "face_value": 1000.0, "market_value_eur": 40.0, "current_weight": 0.2},
    ]
    inputs = _inputs(positions)
    projection = _build(inputs, sort_by="value", descending=True)
    rows = projection["rows"]

    assert [row["instrument_id"] for row in rows] == ["STOCK", "ETF", "BOND"]
    assert rows[0]["asset_details"].keys() == {"shares", "sector"}
    assert rows[1]["asset_details"].keys() == {"issuer", "expense_ratio", "distribution_policy"}
    assert rows[2]["asset_details"].keys() == {"face_value", "coupon_rate", "maturity_date"}
    filtered = _build(inputs, asset_type="bond")["rows"]
    assert [row["instrument_id"] for row in filtered] == ["BOND"]
    assert filtered[0]["quantity"]["status"] == "unavailable"
    assert filtered[0]["cost_basis"]["value"] is None
    assert filtered[0]["cost_basis"]["value"] != 0


def test_same_day_future_analysis_and_distribution_are_rejected_before_date_display() -> None:
    analysis_future = _inputs()
    analysis_future["portfolio_snapshot"]["as_of"] = "2026-09-30T09:00:00+00:00"  # type: ignore[index]
    analysis_future["analysis_snapshot"]["decision_time"] = "2026-09-30T17:00:00+00:00"  # type: ignore[index]
    analysis_future["analysis_snapshot"]["distributions"]["AAA"][30]["decision_time"] = "2026-09-30T08:00:00+00:00"  # type: ignore[index]
    future_analysis_projection = _build(analysis_future)

    distribution_future = _inputs()
    distribution_future["portfolio_snapshot"]["as_of"] = "2026-09-30T09:00:00+00:00"  # type: ignore[index]
    distribution_future["analysis_snapshot"]["decision_time"] = "2026-09-30T08:00:00+00:00"  # type: ignore[index]
    distribution_future["analysis_snapshot"]["distributions"]["AAA"][30]["decision_time"] = "2026-09-30T17:00:00+00:00"  # type: ignore[index]
    future_distribution_projection = _build(distribution_future)

    assert future_analysis_projection["analysis_date"] == _DATE
    assert future_analysis_projection["proposal_handoff_allowed"] is False
    assert "portfolio_analysis_postdates_snapshot" in future_analysis_projection["conflicts"]
    assert future_distribution_projection["proposal_handoff_allowed"] is False
    assert "forecast_distribution_postdates_portfolio_snapshot" in future_distribution_projection["conflicts"]
    assert future_distribution_projection["rows"][0]["expected_gain_loss"]["net_q50_return"]["value"] is None


def test_missing_fx_scenario_blocks_numeric_gain_loss_amounts() -> None:
    inputs = _inputs()
    del inputs["analysis_snapshot"]["distributions"]["AAA"][30]["return_components"]["fx_return"]  # type: ignore[index]

    row = _build(inputs)["rows"][0]

    amount = row["expected_gain_loss"]["net_q50_return"]
    assert row["distribution_return_components"]["status"] == "unavailable"
    assert amount["status"] == "unavailable"
    assert amount["value"] is None
    assert amount["reason"] == "stored_fx_scenario_unavailable"
