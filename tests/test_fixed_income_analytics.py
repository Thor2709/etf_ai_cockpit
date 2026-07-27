from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest
import pandas as pd
import json
import shutil

from etf_cockpit.analysis.fixed_income_analytics import (
    CallRedemption,
    ContractualCashFlow,
    CurveNode,
    DifferentialReference,
    DiscountCurveEvidence,
    FixedIncomeAnalyticsError,
    FixedIncomeValuationInput,
    ObservedBondPrice,
    accrued_interest,
    calculate_fixed_income_analytics,
    clean_price_from_yield,
    validate_differential_reference,
    yield_from_clean_price,
)
from etf_cockpit.data.bond_analytics_store import (
    BondAnalyticsRecord,
    read_bond_analytics,
    write_bond_analytics,
)
from etf_cockpit.data.market_calendar import DayCountConvention
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.ui_facade import load_fixed_income_analytics_projection


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CHECKSUM = "a" * 64


def _bond(**changes: object) -> FixedIncomeValuationInput:
    flows = (
        ContractualCashFlow(
            date(2026, 7, 1),
            Decimal("25"),
            "coupon",
            "terms-v1",
            date(2026, 1, 1),
            date(2026, 7, 1),
        ),
        ContractualCashFlow(
            date(2027, 1, 1),
            Decimal("25"),
            "coupon",
            "terms-v1",
            date(2026, 7, 1),
            date(2027, 1, 1),
        ),
        ContractualCashFlow(date(2027, 1, 1), Decimal("1000"), "redemption", "terms-v1"),
    )
    base = FixedIncomeValuationInput(
        instrument_id="BOND-1",
        terms_version_id="terms-v1",
        currency="USD",
        face_value=Decimal("1000"),
        settlement_date=date(2026, 1, 1),
        maturity_date=date(2027, 1, 1),
        coupon_rate=Decimal("0.05"),
        coupon_frequency=2,
        day_count=DayCountConvention.THIRTY_360_US,
        cashflows=flows,
        decision_time=NOW,
        yield_to_maturity=Decimal("0.05"),
    )
    return replace(base, **changes)


def _curve(**changes: object) -> DiscountCurveEvidence:
    base = DiscountCurveEvidence(
        curve_id="usd-zero",
        curve_kind="zero",
        currency="USD",
        rate_unit="decimal",
        compounding="annual",
        interpolation="linear_zero",
        day_count=DayCountConvention.ACT_365F,
        nodes=(
            CurveNode(Decimal("0.5"), Decimal("0.04")),
            CurveNode(Decimal("2"), Decimal("0.05")),
        ),
        source_id="fixture",
        source_version="v1",
        source_checksum=CHECKSUM,
        as_of=NOW,
        retrieved_at=NOW,
        decision_time=NOW,
    )
    return replace(base, **changes)


def test_par_bond_round_trip_and_risk_measures() -> None:
    item = _bond()
    clean = clean_price_from_yield(item, Decimal("0.05"))
    assert clean == pytest.approx(Decimal("100"))
    assert yield_from_clean_price(item, clean) == pytest.approx(Decimal("0.05"), abs=Decimal("1e-8"))

    result = calculate_fixed_income_analytics(item)
    assert result.clean_price == pytest.approx(Decimal("100"))
    assert result.dirty_price == result.clean_price
    assert result.current_yield == Decimal("0.0500000000")
    assert 0 < result.modified_duration < result.macaulay_duration
    assert result.convexity > 0
    assert result.dv01 == result.pv01
    assert result.execution_allowed is False


def test_supplied_price_and_yield_must_be_consistent() -> None:
    implied = clean_price_from_yield(_bond(), Decimal("0.05"))
    assert calculate_fixed_income_analytics(
        replace(_bond(), clean_price=implied)
    ).clean_price == implied
    with pytest.raises(FixedIncomeAnalyticsError, match="contradictory"):
        calculate_fixed_income_analytics(
            replace(_bond(), clean_price=implied + Decimal("0.01"))
        )


@pytest.mark.parametrize(
    ("rate", "frequency"),
    [
        (Decimal("NaN"), 2),
        (Decimal("-0.01"), 2),
        (Decimal("1.01"), 2),
        (Decimal("0.05"), 0),
        (Decimal("0"), 2),
    ],
)
def test_coupon_rate_and_frequency_fail_closed(
    rate: Decimal, frequency: int
) -> None:
    with pytest.raises(FixedIncomeAnalyticsError, match="coupon rate/frequency"):
        calculate_fixed_income_analytics(
            replace(_bond(), coupon_rate=rate, coupon_frequency=frequency)
        )


def test_accrued_coupon_boundary_mid_period_and_ex_coupon() -> None:
    assert accrued_interest(_bond()) == 0
    midpoint = replace(_bond(), settlement_date=date(2026, 4, 1))
    assert accrued_interest(midpoint) == pytest.approx(Decimal("1.25"))
    ex_flow = replace(
        midpoint.cashflows[0],
        ex_coupon_date=date(2026, 3, 25),
    )
    ex_coupon = replace(midpoint, cashflows=(ex_flow, *midpoint.cashflows[1:]))
    assert accrued_interest(ex_coupon) == pytest.approx(Decimal("-1.25"))


def test_zero_coupon_and_negative_yield_round_trip() -> None:
    zero = replace(
        _bond(),
        coupon_rate=Decimal("0"),
        coupon_frequency=0,
        cashflows=(
            ContractualCashFlow(date(2027, 1, 1), Decimal("1000"), "redemption", "terms-v1"),
        ),
        yield_to_maturity=Decimal("-0.01"),
    )
    clean = clean_price_from_yield(zero, Decimal("-0.01"))
    assert clean > 100
    assert yield_from_clean_price(zero, clean) == pytest.approx(Decimal("-0.01"), abs=Decimal("1e-8"))


def test_calls_curve_scenarios_and_observed_price_remain_separate() -> None:
    observed = ObservedBondPrice(
        Decimal("99"),
        "USD",
        "per_100",
        "fixture",
        CHECKSUM,
        NOW,
        NOW,
    )
    item = replace(
        _bond(),
        maturity_date=date(2028, 1, 1),
        calls=(CallRedemption(date(2026, 10, 1), Decimal("990"), "terms-v1"),),
        curve=_curve(),
        observed_price=observed,
    )
    result = calculate_fixed_income_analytics(item)
    assert result.yields_to_call
    assert result.yield_to_worst <= result.yield_to_maturity
    assert result.curve_model_value != result.observed_clean_price
    assert result.observed_model_discrepancy == result.observed_clean_price - result.curve_model_value
    assert result.scenarios[0].model_value > result.curve_model_value
    assert result.scenarios[-1].model_value < result.curve_model_value


def test_every_call_yield_participates_in_exact_yield_to_worst() -> None:
    item = replace(
        _bond(),
        maturity_date=date(2028, 1, 1),
        calls=(
            CallRedemption(date(2026, 8, 1), Decimal("1010"), "terms-v1"),
            CallRedemption(date(2026, 10, 1), Decimal("980"), "terms-v1"),
        ),
    )
    result = calculate_fixed_income_analytics(item)
    assert [entry.call_date for entry in result.yields_to_call] == [
        date(2026, 8, 1),
        date(2026, 10, 1),
    ]
    candidates = {
        "maturity": result.yield_to_maturity,
        **{
            f"call:{entry.call_date.isoformat()}": entry.yield_value
            for entry in result.yields_to_call
        },
    }
    expected_basis, expected_value = min(candidates.items(), key=lambda item: item[1])
    assert result.yield_to_worst_basis == expected_basis
    assert result.yield_to_worst == expected_value


def test_curve_model_and_observed_discrepancy_use_clean_units() -> None:
    midpoint = replace(
        _bond(),
        settlement_date=date(2026, 4, 1),
        curve=_curve(nodes=(
            CurveNode(Decimal("0.25"), Decimal("0.05")),
            CurveNode(Decimal("2"), Decimal("0.05")),
        )),
        observed_price=ObservedBondPrice(
            Decimal("99"), "USD", "per_100", "fixture", CHECKSUM, NOW, NOW
        ),
    )
    result = calculate_fixed_income_analytics(midpoint)
    assert result.curve_dirty_value - result.accrued_interest == result.curve_model_value
    assert result.observed_model_discrepancy == Decimal("99") - result.curve_model_value


def test_curve_tenor_uses_declared_curve_day_count() -> None:
    curve = _curve(day_count=DayCountConvention.ACT_365F)
    first = calculate_fixed_income_analytics(replace(_bond(), curve=curve))
    second = calculate_fixed_income_analytics(
        replace(_bond(), curve=curve, day_count=DayCountConvention.THIRTY_E_360)
    )
    assert first.curve_model_value == second.curve_model_value


def test_invalid_stub_curve_and_future_evidence_are_rejected() -> None:
    irregular = replace(
        _bond(),
        cashflows=(
            replace(
                _bond().cashflows[0],
                accrual_end=date(2026, 5, 1),
                payment_date=date(2026, 5, 1),
            ),
            *_bond().cashflows[1:],
        ),
    )
    with pytest.raises(FixedIncomeAnalyticsError, match="stub"):
        calculate_fixed_income_analytics(irregular)
    with pytest.raises(FixedIncomeAnalyticsError, match="duplicate or out of order"):
        calculate_fixed_income_analytics(
            replace(_bond(), curve=_curve(nodes=(_curve().nodes[1], _curve().nodes[0])))
        )
    future = replace(_curve(), retrieved_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    with pytest.raises(FixedIncomeAnalyticsError, match="future-known"):
        calculate_fixed_income_analytics(replace(_bond(), curve=future))
    incoherent = replace(
        _curve(),
        as_of=datetime(2026, 1, 3, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    with pytest.raises(FixedIncomeAnalyticsError, match="future-known"):
        calculate_fixed_income_analytics(replace(_bond(), curve=incoherent))


def test_differential_harness_and_parquet_replay(tmp_path) -> None:
    result = calculate_fixed_income_analytics(_bond())
    reference = DifferentialReference(
        "par-bond",
        "v1",
        "checked local golden fixture",
        "local_golden",
        "locally_reviewed",
        {"clean_price": Decimal("100")},
        {"clean_price": Decimal("0.000001")},
        CHECKSUM,
    )
    assert validate_differential_reference(result, reference).status == "passed"
    quarantined = replace(reference, expected={"clean_price": Decimal("90")})
    assert validate_differential_reference(result, quarantined).status == "quarantined"
    with pytest.raises(FixedIncomeAnalyticsError, match="provenance"):
        validate_differential_reference(
            result, replace(reference, expected={"clean_price": Decimal("NaN")})
        )

    path = tmp_path / "data" / "analytics" / "bond_analytics.parquet"
    record = BondAnalyticsRecord("record-1", NOW, _bond(), result)
    write_bond_analytics(path, (record,))
    loaded = read_bond_analytics(path)
    assert loaded[0]["input_hash"] == _bond().input_hash
    assert loaded[0]["result"]["execution_allowed"] is False

    frame = pd.read_parquet(path)
    frame.loc[0, "input_hash"] = "b" * 64
    frame.to_parquet(path, index=False)
    with pytest.raises(FixedIncomeAnalyticsError, match="diverges"):
        read_bond_analytics(path)


def test_result_tampering_and_unknown_schema_fail_closed(tmp_path) -> None:
    path = tmp_path / "data" / "analytics" / "bond_analytics.parquet"
    item = _bond()
    result = calculate_fixed_income_analytics(item)
    altered = replace(result, clean_price=Decimal("88"))
    with pytest.raises(FixedIncomeAnalyticsError, match="not canonical"):
        write_bond_analytics(path, (BondAnalyticsRecord("bad", NOW, item, altered),))

    write_bond_analytics(path, (BondAnalyticsRecord("good", NOW, item, result),))
    frame = pd.read_parquet(path)
    payload = json.loads(frame.loc[0, "result_json"])
    payload["clean_price"] = "88"
    frame.loc[0, "result_json"] = json.dumps(payload, sort_keys=True)
    from etf_cockpit.data import bond_analytics_store as analytics

    frame.loc[0, "result_checksum"] = analytics._hash(payload)
    frame.to_parquet(path, index=False)
    with pytest.raises(FixedIncomeAnalyticsError, match="diverges"):
        read_bond_analytics(path)

    frame.loc[0, "schema_version"] = 99
    frame.to_parquet(path, index=False)
    with pytest.raises(FixedIncomeAnalyticsError, match="unsupported"):
        read_bond_analytics(path)


def test_failed_publication_preserves_prior_valid_projection(tmp_path, monkeypatch) -> None:
    from etf_cockpit.data import bond_analytics_store as analytics

    path = tmp_path / "data" / "analytics" / "bond_analytics.parquet"
    first = _bond()
    write_bond_analytics(
        path,
        (BondAnalyticsRecord("first", NOW, first, calculate_fixed_income_analytics(first)),),
    )
    before = path.read_bytes()
    second = replace(_bond(), instrument_id="BOND-2")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr(analytics, "atomic_write_bytes", fail)
    with pytest.raises(OSError, match="injected"):
        write_bond_analytics(
            path,
            (BondAnalyticsRecord("second", NOW, second, calculate_fixed_income_analytics(second)),),
        )
    assert path.read_bytes() == before


def test_divergent_projection_is_rejected_and_next_append_recovers(tmp_path) -> None:
    path = tmp_path / "data" / "analytics" / "bond_analytics.parquet"
    first = _bond()
    write_bond_analytics(
        path,
        (BondAnalyticsRecord("first", NOW, first, calculate_fixed_income_analytics(first)),),
    )
    frame = pd.read_parquet(path)
    phantom = frame.iloc[0].copy()
    phantom["record_id"] = "phantom"
    pd.concat([frame, phantom.to_frame().T], ignore_index=True).to_parquet(
        path, index=False
    )
    with pytest.raises(FixedIncomeAnalyticsError, match="diverges"):
        read_bond_analytics(path)

    second = replace(_bond(), instrument_id="BOND-2")
    write_bond_analytics(
        path,
        (BondAnalyticsRecord("second", NOW, second, calculate_fixed_income_analytics(second)),),
    )
    assert {row["record_id"] for row in read_bond_analytics(path)} == {
        "first",
        "second",
    }


def test_read_with_missing_transactional_store_has_no_side_effects(tmp_path) -> None:
    source = tmp_path / "source" / "data" / "analytics" / "bond_analytics.parquet"
    item = _bond()
    write_bond_analytics(
        source,
        (BondAnalyticsRecord("first", NOW, item, calculate_fixed_income_analytics(item)),),
    )
    isolated = tmp_path / "isolated" / "data" / "analytics" / "bond_analytics.parquet"
    isolated.parent.mkdir(parents=True)
    shutil.copyfile(source, isolated)
    before = {path.relative_to(tmp_path / "isolated") for path in (tmp_path / "isolated").rglob("*")}
    with pytest.raises(FixedIncomeAnalyticsError, match="committed analytics"):
        read_bond_analytics(isolated)
    after = {path.relative_to(tmp_path / "isolated") for path in (tmp_path / "isolated").rglob("*")}
    assert after == before


def test_empty_duplicate_and_true_authority_records_fail_closed(tmp_path) -> None:
    path = tmp_path / "bond_analytics.parquet"
    with pytest.raises(FixedIncomeAnalyticsError, match="empty"):
        write_bond_analytics(path, ())
    result = calculate_fixed_income_analytics(_bond())
    record = BondAnalyticsRecord("same", NOW, _bond(), result)
    write_bond_analytics(path, (record, record))
    assert len(read_bond_analytics(path)) == 1
    conflict = replace(record, calculated_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    with pytest.raises(FixedIncomeAnalyticsError, match="different content"):
        write_bond_analytics(path, (conflict,))
    unsafe = replace(record, execution_allowed=True)
    with pytest.raises(FixedIncomeAnalyticsError, match="authority"):
        write_bond_analytics(path, (unsafe,))
    early = replace(record, calculated_at=datetime(2025, 12, 31, tzinfo=timezone.utc))
    with pytest.raises(FixedIncomeAnalyticsError, match="time"):
        write_bond_analytics(path, (early,))


def test_concurrent_distinct_appends_retain_history(tmp_path) -> None:
    path = tmp_path / "data" / "analytics" / "bond_analytics.parquet"

    def append(index: int) -> None:
        item = replace(_bond(), instrument_id=f"BOND-{index}")
        result = calculate_fixed_income_analytics(item)
        write_bond_analytics(
            path,
            (BondAnalyticsRecord(f"record-{index}", NOW, item, result),),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        tuple(pool.map(append, (1, 2)))
    assert {row["instrument_id"] for row in read_bond_analytics(path)} == {
        "BOND-1",
        "BOND-2",
    }


def test_application_calculate_append_replay_matches_facade(tmp_path) -> None:
    api = LocalApplicationApi(lambda: object(), root=tmp_path)
    first = api.calculate_and_persist_fixed_income_analytics(_bond())
    second_input = replace(_bond(), instrument_id="BOND-2")
    second = api.calculate_and_persist_fixed_income_analytics(second_input)
    assert first == api.get_fixed_income_analytics("BOND-1")
    assert second == load_fixed_income_analytics_projection(
        "BOND-2", storage_root=tmp_path
    )
    assert len(
        read_bond_analytics(
            tmp_path / "data" / "analytics" / "bond_analytics.parquet"
        )
    ) == 2


def test_application_selection_uses_decision_time_not_later_replay_time(
    tmp_path,
) -> None:
    path = tmp_path / "data" / "analytics" / "bond_analytics.parquet"
    historical = replace(
        _bond(),
        decision_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        yield_to_maturity=Decimal("0.04"),
    )
    current = _bond()
    historical_result = calculate_fixed_income_analytics(historical)
    current_result = calculate_fixed_income_analytics(current)
    write_bond_analytics(
        path,
        (
            BondAnalyticsRecord("current", NOW, current, current_result),
            BondAnalyticsRecord(
                "historical-replay",
                datetime(2027, 1, 1, tzinfo=timezone.utc),
                historical,
                historical_result,
            ),
        ),
    )

    api = LocalApplicationApi(lambda: object(), root=tmp_path)
    assert api.get_fixed_income_analytics("BOND-1")["input_hash"] == current.input_hash
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert (
        api.get_fixed_income_analytics("BOND-1", decision_time=cutoff)["input_hash"]
        == historical.input_hash
    )
    assert load_fixed_income_analytics_projection(
        "BOND-1",
        storage_root=tmp_path,
        decision_time="2025-01-01T00:00:00Z",
    )["input_hash"] == historical.input_hash


def test_explicit_stub_and_near_maturity_leap_year_are_typed() -> None:
    stub = replace(
        _bond(),
        explicit_stub=True,
        cashflows=(
            ContractualCashFlow(
                date(2026, 5, 1),
                Decimal("16.6667"),
                "coupon",
                "terms-v1",
                date(2026, 1, 1),
                date(2026, 5, 1),
            ),
            *_bond().cashflows[1:],
        ),
    )
    assert calculate_fixed_income_analytics(stub).status == "partial"
    near = replace(
        _bond(),
        settlement_date=date(2026, 12, 31),
        day_count=DayCountConvention.ACT_ACT_ISDA,
    )
    assert calculate_fixed_income_analytics(near).modified_duration > 0
