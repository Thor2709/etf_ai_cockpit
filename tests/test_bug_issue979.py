"""#979 V8 intake items on the risk lane (native RED tests; each names its register ID)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import math

import pandas as pd
import pytest

from etf_cockpit.analysis.fixed_income_risk import calculate_fixed_income_risk
from etf_cockpit.portfolio.benchmark_relative_diagnostics import (
    BenchmarkDiagnosticsError,
    canonical_report_hash,
    verify_benchmark_relative_report,
)
from etf_cockpit.portfolio.factor_risk import (
    build_factor_exposures,
    build_factor_risk_report,
)
from etf_cockpit.portfolio.risk_analytics import drawdown_contribution
from etf_cockpit.portfolio.robust_risk import integrate_fixed_income_risk
from test_benchmark_relative_diagnostics import _build, _complete, _evidence
from test_factor_risk import _fixture as _factor_fixture
from test_fixed_income_risk import _risk


def _bond(instrument_id: str, *, complete: bool = True):
    kwargs = (
        dict(
            spread_shock_bps=Decimal("20"),
            rating_change_loss=Decimal("1"),
            default_probability=Decimal("0.01"),
            recovery_rate=Decimal("0.4"),
            liquidity_cost_bps=Decimal("5"),
        )
        if complete
        else {}
    )
    return replace(calculate_fixed_income_risk(_risk(**kwargs)), instrument_id=instrument_id)


def test_d_c2_s08_n002_scenario_coverage_is_component_coverage_not_instrument_presence() -> None:
    report = integrate_fixed_income_risk((_bond("B1", complete=True), _bond("B2", complete=False)))
    row = {item["scenario_id"]: item for item in report["scenarios"]}["up-10"]

    assert row["missing_instruments"] == []  # both instruments present ...
    assert row["coverage"] == pytest.approx(Decimal("0.6"))  # ... but only (1 + 0.2) / 2 of the components known
    assert row["total_pnl"] is None and row["reconciled"] is False


def test_d_c2_s08_n003_mixed_units_are_never_summed_into_a_known_total() -> None:
    first = _bond("B1")
    second = _bond("B2")
    second = replace(second, scenarios=tuple(replace(item, unit="EUR") for item in second.scenarios))
    report = integrate_fixed_income_risk((first, second))
    row = {item["scenario_id"]: item for item in report["scenarios"]}["up-10"]

    assert row["unit"] is None
    assert row["known_component_total"] is None
    assert row["total_pnl"] is None and row["reconciled"] is False

    same_unit = {item["scenario_id"]: item for item in integrate_fixed_income_risk((first, _bond("B3")))["scenarios"]}["up-10"]
    assert same_unit["known_component_total"] == first.scenarios[0].known_component_total * 2


def test_d_c2_s08_n004_duplicate_identity_cannot_multiply_drawdown_rows() -> None:
    allocation = pd.DataFrame({"etf_id": ["A", "B"], "name": ["a", "b"], "current_weight": [0.5, 0.5]})
    features = pd.DataFrame(
        {"etf_id": ["A", "B"], "drawdown_current": [-0.1, -0.2], "drawdown_60d_max": [-0.2, -0.3], "vol_60d_ann": [0.1, 0.2]}
    )
    assert drawdown_contribution(allocation, features).attrs["status"] == "available"

    duplicated = pd.concat([features, features.iloc[[0]]], ignore_index=True)
    result = drawdown_contribution(allocation, duplicated)
    assert result.attrs["status"] == "unavailable" and result.attrs["reason_code"] == "duplicate_etf_identity"
    assert result["risk_share"].isna().all()
    assert drawdown_contribution(pd.concat([allocation, allocation.iloc[[1]]]), features).attrs["reason_code"] == "duplicate_etf_identity"


def test_d_c3_s04_n001_sparse_lookthrough_category_does_not_abort_the_whole_report() -> None:
    prices, allocation, _features = _factor_fixture()
    rows = []
    for index in range(6):  # ETF6/ETF7 hold no Technology at all, ETF0-5 do (varying weights)
        tech = 0.2 + 0.1 * index
        rows.append({"instrument_id": f"ETF{index}", "weight": tech, "sector": "Technology", "region": "US", "currency": "USD"})
        rows.append({"instrument_id": f"ETF{index}", "weight": 1.0 - tech, "sector": "Health", "region": "US", "currency": "USD"})
    for index in (6, 7):
        rows.append({"instrument_id": f"ETF{index}", "weight": 1.0, "sector": "Health", "region": "US", "currency": "USD"})
    holdings = pd.DataFrame(rows)

    report = build_factor_risk_report(prices, allocation, holdings=holdings)

    assert report["status"] != "unavailable", report.get("message")
    assert report.get("reason_code") != "factor_exposures_unavailable"
    assert "industry:Technology" in report["diagnostics"]["selected_factors"]
    matrix = report["exposure_matrix"]
    assert matrix.loc["ETF6", "industry:Technology"] == 0.0  # mapped instrument, absent bucket


def test_d_c3_s04_n001_unmapped_instruments_stay_unknown_and_factor_is_excluded_not_zero_filled() -> None:
    prices, allocation, _features = _factor_fixture()
    rows = [
        {"instrument_id": f"ETF{index}", "weight": 0.2 + 0.1 * index, "sector": "Technology"} for index in range(6)
    ]  # ETF6/ETF7 have no look-through mapping at all
    report = build_factor_risk_report(prices, allocation, holdings=pd.DataFrame(rows))

    assert report["status"] != "unavailable", report.get("message")
    assert report["diagnostics"]["excluded_factors"]["industry:Technology"] == "incomplete_category_exposure"


def test_d_c3_s04_n002_lookthrough_full_coverage_uses_all_positive_weight_holdings() -> None:
    prices, allocation, _features = _factor_fixture()
    allocation = allocation.copy()

    def holdings_for(ids: list[str]) -> pd.DataFrame:
        return pd.DataFrame(
            [{"instrument_id": item, "weight": 1.0, "sector": "Technology", "region": "US", "currency": "USD"} for item in ids]
        )

    partial = build_factor_risk_report(prices, allocation, holdings=holdings_for(["ETF0", "ETF1"]))["coverage"]["lookthrough"]
    complete = build_factor_risk_report(prices, allocation, holdings=holdings_for([f"ETF{i}" for i in range(8)]))["coverage"]["lookthrough"]
    assert partial["dimensions"]["industry"]["full_coverage"] is False
    assert partial["dimensions"]["industry"]["mean_coverage"] == pytest.approx(0.25)
    assert complete["dimensions"]["industry"]["full_coverage"] is True


@pytest.mark.parametrize("bad", ["abc", None, float("nan")])
def test_d_c3_s04_n003_invalid_weight_is_not_coerced_to_zero_in_factor_risk(bad: object) -> None:
    prices, allocation, features = _factor_fixture()
    allocation = allocation.copy()
    allocation["current_weight"] = allocation["current_weight"].astype(object)
    allocation.loc[0, "current_weight"] = bad

    report = build_factor_risk_report(prices, allocation, features)
    assert report["status"] == "unavailable"
    assert report["reason_code"] == "invalid_allocation_weight"


def test_d04_c2_n002_feature_dated_after_the_decision_is_not_selected() -> None:
    _prices, allocation, _features = _factor_fixture()
    features = pd.DataFrame(
        [
            {"etf_id": "ETF0", "date": "2025-03-03", "momentum_120d": 1.0},
            {"etf_id": "ETF0", "date": "2025-03-10", "momentum_120d": 9.0},  # after the decision
        ]
    )

    def raw_momentum(**kwargs: object) -> float:
        frame = build_factor_exposures(allocation, features, **kwargs)
        return float(frame[(frame["instrument_id"] == "ETF0") & (frame["factor"] == "momentum")]["raw_value"].iloc[0])

    assert raw_momentum(as_of="2025-03-05") == 1.0
    assert raw_momentum(as_of=pd.Timestamp("2025-03-10")) == 9.0


def test_d04_c2_n003_undated_feature_never_overwrites_the_latest_dated_observation() -> None:
    _prices, allocation, _features = _factor_fixture()
    features = pd.DataFrame(
        [
            {"etf_id": "ETF0", "date": "2025-03-03", "momentum_120d": 1.0},
            {"etf_id": "ETF0", "date": None, "momentum_120d": 100.0},
        ]
    )
    frame = build_factor_exposures(allocation, features)
    value = float(frame[(frame["instrument_id"] == "ETF0") & (frame["factor"] == "momentum")]["raw_value"].iloc[0])
    assert value == 1.0
    cutoff = build_factor_exposures(allocation, features, as_of="2025-03-04")
    assert float(cutoff[(cutoff["instrument_id"] == "ETF0") & (cutoff["factor"] == "momentum")]["raw_value"].iloc[0]) == 1.0


def test_c_c2_s12_n001_currency_fx_evidence_in_another_currency_is_not_summed_unconverted() -> None:
    evidence = [row for row in _complete() if row.dimension != "currency_fx"]
    evidence.append(_evidence("currency_fx", "EURUSD", 0.001, currency="USD"))
    with pytest.raises(BenchmarkDiagnosticsError, match="currency mismatch"):
        _build(evidence)


def test_c_c2_s12_n003_verifier_sums_contributions_exactly_like_the_builder() -> None:
    report = _build()
    first = report.dimensions[0]
    template = first.contributions[0]
    values = [1.0, *([1.0e-16] * 10_000)]
    contributions = tuple(replace(template, contribution=value) for value in values)
    component_sum = math.fsum(values)
    naive = 0.0
    for value in values:
        naive += value
    assert naive != pytest.approx(component_sum, abs=1e-15)  # naive accumulation drifts
    other = [item.contribution for dimension in report.dimensions[1:] for item in dimension.contributions]
    total = math.fsum([*values, *other])
    gap = report.relative_return - total - (report.residual or 0.0)
    rebuilt = replace(
        report,
        dimensions=(replace(first, contributions=contributions), *report.dimensions[1:]),
        component_sum=total,
        reconciliation_gap=gap,
        report_hash="",
    )
    rebuilt = replace(rebuilt, report_hash=canonical_report_hash(rebuilt))
    verify_benchmark_relative_report(rebuilt)  # must not reject on summation order alone
