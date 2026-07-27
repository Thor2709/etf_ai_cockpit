from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pandas as pd
import pytest

from etf_cockpit.analysis.fixed_income_analytics import (
    ContractualCashFlow,
    CallRedemption,
    CurveNode,
    DiscountCurveEvidence,
    FixedIncomeValuationInput,
)
from etf_cockpit.analysis.fixed_income_risk import (
    CurveShock,
    FixedIncomeRiskError,
    FixedIncomeRiskInput,
    aggregate_portfolio_scenarios,
    calculate_fixed_income_risk,
)
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.ui_facade import (
    calculate_fixed_income_risk_projection,
    load_fixed_income_risk_projection,
)
from etf_cockpit.data.fixed_income_risk_store import (
    StoredFixedIncomeRisk,
    read_fixed_income_risk,
    write_fixed_income_risk,
)
from etf_cockpit.data.market_calendar import DayCountConvention

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _valuation() -> FixedIncomeValuationInput:
    flows = (
        ContractualCashFlow(
            date(2026, 7, 1), Decimal("2.5"), "coupon", "terms-v1",
            date(2026, 1, 1), date(2026, 7, 1),
        ),
        ContractualCashFlow(date(2027, 1, 1), Decimal("102.5"), "redemption", "terms-v1"),
    )
    curve = DiscountCurveEvidence(
        "usd-zero", "zero", "USD", "decimal", "annual", "linear_zero",
        DayCountConvention.ACT_365F,
        (CurveNode(Decimal("0.5"), Decimal("0.04")), CurveNode(Decimal("2"), Decimal("0.05"))),
        "fixture", "v1", "a" * 64, NOW, NOW, NOW,
    )
    return FixedIncomeValuationInput(
        "BOND-1", "terms-v1", "USD", Decimal("100"), date(2026, 1, 1),
        date(2027, 1, 1), Decimal("0.05"), 2, DayCountConvention.THIRTY_360_US,
        flows, NOW, yield_to_maturity=Decimal("0.05"), curve=curve,
    )


def _risk(**changes: object) -> FixedIncomeRiskInput:
    base = FixedIncomeRiskInput(
        _valuation(), "bond", Decimal("1000"),
        (
            CurveShock("up-10", Decimal("10")),
            CurveShock("key-up", key_rate_bps=((Decimal("0.5"), Decimal("10")),)),
        ),
        issuer_id="ISSUER-1",
        quote_age_seconds=Decimal("120"),
        minimum_size=Decimal("100"),
        intended_liquidation_size=Decimal("1000"),
        evidence_lineage=("fixture:v1",),
    )
    return replace(base, **changes)


def test_parallel_and_key_rate_reprice_sign_tolerance_and_unknowns() -> None:
    result = calculate_fixed_income_risk(_risk())
    assert result.scenarios[0].rate_full_reprice_pnl < 0
    assert result.scenarios[0].parallel_bps == Decimal("10")
    assert abs(result.scenarios[0].approximation_discrepancy) < Decimal("0.02")
    assert result.scenarios[1].rate_full_reprice_pnl < 0
    assert result.scenarios[1].key_rate_bps == (
        (Decimal("0.5"), Decimal("10")),
    )
    assert result.components["spread"].value is None
    assert result.components["default_recovery"].unknown_amount == Decimal("1000")
    assert result.scenarios[0].total_pnl is None
    assert result.execution_allowed is False


def test_explicit_components_reconcile_and_validate_default_recovery() -> None:
    complete = _risk(
        spread_shock_bps=Decimal("25"),
        rating_change_loss=Decimal("1"),
        default_probability=Decimal("0.02"),
        recovery_rate=Decimal("0.4"),
        liquidity_cost_bps=Decimal("10"),
    )
    result = calculate_fixed_income_risk(complete)
    row = result.scenarios[0]
    assert row.total_pnl == row.known_component_total
    portfolio = {
        entry["scenario_id"]: entry
        for entry in aggregate_portfolio_scenarios((result, result))
    }
    assert portfolio[row.scenario_id]["total_pnl"] == row.total_pnl * 2
    incomplete = replace(result, scenarios=(result.scenarios[0],))
    partial = {
        entry["scenario_id"]: entry
        for entry in aggregate_portfolio_scenarios((result, incomplete))
    }
    assert partial["key-up"]["total_pnl"] is None
    assert partial["key-up"]["missing_instruments"] == ("BOND-1",)
    with pytest.raises(FixedIncomeRiskError):
        calculate_fixed_income_risk(replace(complete, recovery_rate=None))
    with pytest.raises(FixedIncomeRiskError):
        calculate_fixed_income_risk(replace(complete, default_probability=Decimal("1.01")))


def test_low_duration_never_masks_flags_liquidity_or_unknown_credit() -> None:
    result = calculate_fixed_income_risk(
        _risk(
            callable=True,
            quote_age_seconds=Decimal("901"),
            minimum_size=Decimal("2000"),
        )
    )
    assert result.risk_label == "review_required"
    assert {"call_risk", "reinvestment_risk", "stale_quote", "below_minimum_size"} <= set(result.warnings)
    explicit_loss = calculate_fixed_income_risk(
        _risk(
            spread_shock_bps=Decimal("0"),
            rating_change_loss=Decimal("0"),
            default_probability=Decimal("0.25"),
            recovery_rate=Decimal("0"),
            liquidity_cost_bps=Decimal("0"),
        )
    )
    assert explicit_loss.risk_label == "review_required"


def test_bond_etf_is_explicitly_distinct_and_unavailable() -> None:
    result = calculate_fixed_income_risk(_risk(instrument_kind="bond_etf"))
    assert result.status == "unavailable"
    assert result.scenarios == ()
    assert "bond_etf_requires_lookthrough_risk" in result.warnings


def test_store_retry_collision_replay_corruption_and_api_facade_parity(tmp_path) -> None:
    item = _risk()
    result = calculate_fixed_income_risk(item)
    path = tmp_path / "data" / "analytics" / "fixed_income_risk.parquet"
    record = StoredFixedIncomeRisk(item.input_hash, NOW, item, result)
    write_fixed_income_risk(path, (record,))
    write_fixed_income_risk(path, (record,))
    assert read_fixed_income_risk(path)[0]["result"]["input_hash"] == item.input_hash
    with pytest.raises(FixedIncomeRiskError):
        changed = replace(item, position_face_value=Decimal("2000"))
        write_fixed_income_risk(
            path,
            (StoredFixedIncomeRisk(item.input_hash, NOW, changed, calculate_fixed_income_risk(changed)),),
        )

    api = LocalApplicationApi(lambda: object(), root=tmp_path)
    assert api.calculate_and_persist_fixed_income_risk(item) == api.get_fixed_income_risk("BOND-1")
    assert api.get_fixed_income_risk("BOND-1") == load_fixed_income_risk_projection("BOND-1", storage_root=tmp_path)
    assert calculate_fixed_income_risk_projection(item)["input_hash"] == item.input_hash

    frame = pd.read_parquet(path)
    payload = json.loads(frame.loc[0, "result_json"])
    payload["risk_label"] = "low"
    frame.loc[0, "result_json"] = json.dumps(payload)
    frame.to_parquet(path, index=False)
    with pytest.raises(FixedIncomeRiskError):
        read_fixed_income_risk(path)


def test_point_in_time_selection_and_execution_denial(tmp_path) -> None:
    first = _risk()
    later_valuation = replace(first.valuation, decision_time=NOW.replace(day=2), curve=replace(first.valuation.curve, decision_time=NOW.replace(day=2), as_of=NOW.replace(day=2), retrieved_at=NOW.replace(day=2)))
    second = replace(first, valuation=later_valuation, position_face_value=Decimal("2000"))
    path = tmp_path / "data" / "analytics" / "fixed_income_risk.parquet"
    write_fixed_income_risk(
        path,
        (
            StoredFixedIncomeRisk(first.input_hash, NOW, first, calculate_fixed_income_risk(first)),
            StoredFixedIncomeRisk(second.input_hash, NOW.replace(day=2), second, calculate_fixed_income_risk(second)),
        ),
    )
    api = LocalApplicationApi(lambda: object(), root=tmp_path)
    historical = api.get_fixed_income_risk("BOND-1", decision_time=NOW)
    assert historical["input_hash"] == first.input_hash
    assert api.get_fixed_income_risk("BOND-1")["input_hash"] == second.input_hash
    assert historical["execution_allowed"] is False


def test_position_dv01_key_rate_approximation_and_callable_schedule() -> None:
    item = _risk(
        valuation=replace(
            _valuation(),
            calls=(CallRedemption(date(2026, 10, 1), Decimal("99"), "terms-v1"),),
        )
    )
    result = calculate_fixed_income_risk(item)
    from etf_cockpit.analysis.fixed_income_analytics import calculate_fixed_income_analytics

    base = calculate_fixed_income_analytics(item.valuation)
    assert result.components["rates"].value == base.dv01 * Decimal("10")
    key = next(row for row in result.scenarios if row.scenario_id == "key-up")
    assert abs(key.approximation_discrepancy) < Decimal("0.02")
    assert "sum_of_canonical_single_node_full_reprices" in key.method
    assert {"call_risk", "reinvestment_risk"} <= set(result.warnings)


@pytest.mark.parametrize(
    "scenarios",
    (
        (CurveShock("bad", Decimal("NaN")),),
        (CurveShock("bad", key_rate_bps=((Decimal("9"), Decimal("1")),)),),
        (CurveShock("bad", key_rate_bps=((Decimal("0.5"), Decimal("1")), (Decimal("0.5"), Decimal("2")))),),
        (CurveShock("same"), CurveShock("same")),
    ),
)
def test_invalid_shocks_fail_closed(scenarios) -> None:
    with pytest.raises(FixedIncomeRiskError):
        calculate_fixed_income_risk(_risk(scenarios=scenarios))


def test_actual_concurrent_distinct_writers_reconcile(tmp_path) -> None:
    path = tmp_path / "data" / "analytics" / "fixed_income_risk.parquet"
    first = _risk()
    second = replace(first, position_face_value=Decimal("2000"))
    records = (
        StoredFixedIncomeRisk(first.input_hash, NOW, first, calculate_fixed_income_risk(first)),
        StoredFixedIncomeRisk(second.input_hash, NOW, second, calculate_fixed_income_risk(second)),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda record: write_fixed_income_risk(path, (record,)), records))
    assert {row["record_id"] for row in read_fixed_income_risk(path)} == {
        first.input_hash,
        second.input_hash,
    }
