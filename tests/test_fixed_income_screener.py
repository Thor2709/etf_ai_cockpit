from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from etf_cockpit.analysis.fixed_income_analytics import (
    ContractualCashFlow,
    CurveNode,
    DiscountCurveEvidence,
    FixedIncomeValuationInput,
)
from etf_cockpit.analysis.fixed_income_returns import (
    FixedIncomeReturnInput,
    calculate_fixed_income_return_decomposition,
    uncalibrated_fixed_income_distribution,
)
from etf_cockpit.analysis.fixed_income_screener import (
    FixedIncomeScreenerSecurity,
    build_fixed_income_screener,
    load_fixed_income_screener_config,
)
from etf_cockpit.application.ui_facade import _persist_fixed_income_screener_snapshot
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.data.market_calendar import DayCountConvention


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SHA = "a" * 64


def test_carry_roll_rate_and_spread_reconcile_to_complete_baseline() -> None:
    valuation = _valuation("BOND-COMPLETE", years=5, coupon="0.05", ytm="0.045")
    result = calculate_fixed_income_return_decomposition(
        FixedIncomeReturnInput(
            valuation,
            horizon_days=90,
            rate_shock_bps=Decimal("25"),
            spread_shock_bps=Decimal("10"),
            default_probability=Decimal("0"),
            recovery_rate=Decimal("0.4"),
            fx_return=Decimal("0"),
            cost_bps=Decimal("0"),
        )
    )

    assert result.status == "available"
    parts = (
        result.coupon_carry,
        result.pull_to_par_roll_down,
        result.rate_scenario,
        result.spread_scenario,
    )
    assert all(value is not None for value in parts)
    assert abs(sum(parts, Decimal("0")) - result.baseline_total_return) < Decimal("0.00000001")
    assert result.net_total_return is not None
    assert result.execution_allowed is False


def test_higher_yield_with_higher_duration_does_not_improve_recommendation() -> None:
    config = replace(_config(), minimum_peer_support=1, bootstrap_samples=20)
    low_risk = _security("LOW-RISK", years=2, coupon="0.05", ytm="0.05")
    high_risk = _security("HIGH-RISK", years=10, coupon="0.07", ytm="0.07")

    snapshot = build_fixed_income_screener((low_risk, high_risk), decision_time=NOW, config=config)
    rows = {row.instrument_id: row for row in snapshot.rows}

    assert rows["HIGH-RISK"].yield_to_worst > rows["LOW-RISK"].yield_to_worst
    assert rows["HIGH-RISK"].risk_penalty > rows["LOW-RISK"].risk_penalty
    assert rows["HIGH-RISK"].risk_adjusted_score < rows["LOW-RISK"].risk_adjusted_score
    assert rows["HIGH-RISK"].recommendation == "research_only"


def test_uncalibrated_forecast_is_research_only_with_unavailable_distribution_values() -> None:
    decomposition = calculate_fixed_income_return_decomposition(
        FixedIncomeReturnInput(
            _valuation("BOND-RESEARCH", years=5, coupon="0.04", ytm="0.04"),
            default_probability=Decimal("0"),
            recovery_rate=Decimal("0.4"),
            fx_return=Decimal("0"),
            cost_bps=Decimal("0"),
        )
    )

    distribution = uncalibrated_fixed_income_distribution(decomposition)
    assert distribution.status == "research_only"
    assert distribution.q05 is distribution.q50 is distribution.q95 is None
    assert distribution.loss_probability is None
    assert distribution.beat_cash_probability is None
    assert distribution.beat_benchmark_probability is None
    assert distribution.reason_codes == ("fixed_income_return_calibration_unavailable",)


def test_rejected_and_unavailable_rows_are_persisted_with_reason_codes(tmp_path: Path) -> None:
    config = replace(_config(), minimum_peer_support=1, bootstrap_samples=10)
    candidate = FixedIncomeScreenerSecurity(
        instrument_id="UNAVAILABLE-BOND",
        security_type="corporate_bond",
        issuer_id="issuer-local-test",
        issuer_sector=None,
        country=None,
        currency="EUR",
        seniority=None,
        rating=None,
        coupon_type="fixed_rate",
        maturity_date=date(2031, 1, 1),
        duration_years=None,
        liquidity_bucket=None,
        liquidity_status="unavailable",
        return_input=None,
        reason_codes=("saved_price_missing",),
    )
    snapshot = build_fixed_income_screener((candidate,), decision_time=NOW, config=config)

    assert _persist_fixed_income_screener_snapshot(tmp_path, snapshot)
    with TransactionalStore(tmp_path) as store:
        persisted = store.list("fixed_income_screener_row_v1")
    assert len(persisted) == len(snapshot.rows) == 1
    row = persisted[0].payload
    assert row["instrument_id"] == "UNAVAILABLE-BOND"
    assert row["status"] in {"rejected", "unavailable"}
    assert "saved_price_missing" in row["reason_codes"]
    assert "fixed_income_return_inputs_unavailable" in row["reason_codes"]
    assert json.loads(row["row_json"])["reason_codes"] == row["reason_codes"]
    assert row["execution_allowed"] is False


def test_frozen_input_ranking_and_bootstrap_are_reproducible_from_seed() -> None:
    config = replace(_config(), minimum_peer_support=1, bootstrap_samples=25, ranking_seed=19)
    securities = tuple(
        _security(f"BOND-{index}", years=3 + index, coupon=f"0.0{4 + index}", ytm=f"0.0{4 + index}")
        for index in range(1, 5)
    )

    first = build_fixed_income_screener(securities, decision_time=NOW, config=config)
    second = build_fixed_income_screener(tuple(reversed(securities)), decision_time=NOW, config=config)

    assert first.analysis_snapshot_id == second.analysis_snapshot_id
    assert first.top_n_instrument_ids == second.top_n_instrument_ids
    assert [row.record_id for row in first.rows] == [row.record_id for row in second.rows]
    assert [row.rank for row in first.rows] == [row.rank for row in second.rows]
    assert [row.rank_stability for row in first.rows] == [row.rank_stability for row in second.rows]
    assert all(row.rank_stability_seed == 19 for row in first.rows)
    assert all(row.peer_status == "supported" for row in first.rows)
    assert all(row.peer_level == "currency_type_parent" for row in first.rows)


def _security(instrument_id: str, *, years: int, coupon: str, ytm: str) -> FixedIncomeScreenerSecurity:
    valuation = _valuation(instrument_id, years=years, coupon=coupon, ytm=ytm)
    return FixedIncomeScreenerSecurity(
        instrument_id=instrument_id,
        security_type="corporate_bond",
        issuer_id=f"issuer-{instrument_id}",
        issuer_sector=None,
        country=None,
        currency="EUR",
        seniority="senior_unsecured",
        rating="investment_grade",
        coupon_type="fixed_rate",
        maturity_date=valuation.maturity_date,
        duration_years=None,
        liquidity_bucket="liquid",
        liquidity_status="available",
        return_input=FixedIncomeReturnInput(
            valuation,
            default_probability=Decimal("0"),
            recovery_rate=Decimal("0.4"),
            fx_return=Decimal("0"),
            cost_bps=Decimal("0"),
        ),
        source_lineage=(valuation.input_hash,),
    )


def _valuation(instrument_id: str, *, years: int, coupon: str, ytm: str) -> FixedIncomeValuationInput:
    start = date(2026, 1, 1)
    flows: list[ContractualCashFlow] = []
    for year in range(1, years + 1):
        period_start = date(2025 + year, 1, 1)
        period_end = date(2026 + year, 1, 1)
        flows.append(
            ContractualCashFlow(
                payment_date=period_end,
                amount=Decimal(coupon) * Decimal("100"),
                kind="coupon",
                source_version_id=f"terms-{instrument_id}",
                accrual_start=period_start,
                accrual_end=period_end,
            )
        )
    maturity = date(2026 + years, 1, 1)
    flows.append(
        ContractualCashFlow(
            payment_date=maturity,
            amount=Decimal("100"),
            kind="redemption",
            source_version_id=f"terms-{instrument_id}",
        )
    )
    curve = DiscountCurveEvidence(
        curve_id=f"curve-{instrument_id}",
        curve_kind="zero",
        currency="EUR",
        rate_unit="decimal",
        compounding="continuous",
        interpolation="linear_zero",
        day_count=DayCountConvention.ACT_365F,
        nodes=(CurveNode(Decimal("1"), Decimal("0.03")), CurveNode(Decimal("20"), Decimal("0.035"))),
        source_id="local-test-curve",
        source_version="v1",
        source_checksum=_SHA,
        as_of=NOW,
        retrieved_at=NOW,
        decision_time=NOW,
    )
    return FixedIncomeValuationInput(
        instrument_id=instrument_id,
        terms_version_id=f"terms-{instrument_id}",
        currency="EUR",
        face_value=Decimal("100"),
        settlement_date=start,
        maturity_date=maturity,
        coupon_rate=Decimal(coupon),
        coupon_frequency=1,
        day_count=DayCountConvention.ACT_365F,
        cashflows=tuple(flows),
        decision_time=NOW,
        yield_to_maturity=Decimal(ytm),
        curve=curve,
    )


def _config():
    return load_fixed_income_screener_config(
        Path(__file__).parents[1] / "configs" / "fixed_income_returns_v1.yaml"
    )
