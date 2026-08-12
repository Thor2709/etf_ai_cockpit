from __future__ import annotations

import json
import math
from datetime import datetime

import pandas as pd
import pytest

from etf_cockpit.app.pages.comparison import _comparison_table
from etf_cockpit.app.selectors import instrument_detail as instrument_detail_selector
from etf_cockpit.data import trust_artifacts
from etf_cockpit.data import macro_warehouse as macro_warehouse_module
from etf_cockpit.data.macro_warehouse import (
    CurvePoint,
    CurveSnapshot,
    MacroWarehouse,
    MacroWarehouseError,
    RiskFreeProxyMapping,
)
from etf_cockpit.features.benchmark_attribution import build_benchmark_attribution
from etf_cockpit.features.cash_comparison import (
    adjusted_endpoint_available_at,
    build_cash_comparison,
    cash_comparison_from_projection,
    exact_adjusted_total_return,
    cash_comparison_to_projection,
    total_return_from_rate,
    validate_cash_comparison_result,
    year_fraction,
)
from etf_cockpit.services import build_snapshot
from etf_cockpit.signals.simple_scores import (
    build_simple_instrument_scores,
    simple_scoreboard_frame,
)
from etf_cockpit.signals import simple_scores as simple_scores_module


def _evidence(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "status": "available",
        "dataset_kind": "risk_free",
        "unit": "decimal",
        "curve_type": "spot",
        "currency": "AUD",
        "tenor_years": 1.0 / 365.0,
        "rate": 0.05,
        "compounding": "annual",
        "day_count": "ACT/365F",
        "reinvestment": "reinvested_income",
        "freshness": "fresh",
        "freshness_status": "fresh",
        "vintage": "2024-12-31T00:00:00+00:00",
        "effective_at": "2024-01-01T00:00:00+00:00",
        "published_at": "2024-12-31T00:00:00+00:00",
        "available_at": "2024-12-31T00:00:00+00:00",
        "source_id": "official-curve",
        "source_authority": "official_public_file",
        "source_checksum": "a" * 64,
        "source_terms": "official-public-file",
        "methodology": "official spot curve",
        "mapping_methodology": "official AUD cash mapping",
        "curve_id": "aud-cash",
        "curve_version": "v1",
        "curve_revision": 1,
        "interpolation": "none",
        "extrapolation_allowed": False,
        "fallback": False,
        "execution_allowed": False,
    }
    value.update(updates)
    return value


@pytest.mark.parametrize(
    ("day_count", "expected"),
    (
        ("ACT/360", 2.0 / 360.0),
        ("ACT/365F", 2.0 / 365.0),
        ("ACT/ACT-ISDA", 1.0 / 366.0 + 1.0 / 365.0),
    ),
)
def test_day_count_conventions_include_leap_boundary(day_count: str, expected: float) -> None:
    assert year_fraction("2024-12-31", "2025-01-02", day_count) == pytest.approx(expected)


@pytest.mark.parametrize("compounding", ("annual", "continuous", "simple"))
def test_total_return_conventions_and_negative_rates(compounding: str) -> None:
    result = total_return_from_rate(-0.01, 1.0, compounding=compounding)
    expected = {
        "annual": -0.01,
        "continuous": math.exp(-0.01) - 1.0,
        "simple": -0.01,
    }[compounding]
    assert result == pytest.approx(expected)


@pytest.mark.parametrize("value", (True, "0.01"))
@pytest.mark.parametrize("field_name", ("annual_rate", "years"))
def test_total_return_rejects_coercive_financial_values(
    field_name: str, value: object
) -> None:
    arguments: dict[str, object] = {"annual_rate": 0.01, "years": 1.0}
    arguments[field_name] = value
    with pytest.raises(ValueError, match="must be numeric"):
        total_return_from_rate(**arguments, compounding="annual")  # type: ignore[arg-type]


def test_annual_rate_domain_is_strict() -> None:
    with pytest.raises(ValueError, match="annual_rate > -1"):
        total_return_from_rate(-1.0, 1.0, compounding="annual")


def test_simple_rate_domain_is_strict_at_and_below_zero_wealth() -> None:
    with pytest.raises(ValueError, match=r"1 \+ annual_rate \* horizon > 0"):
        total_return_from_rate(-0.5, 2.0, compounding="simple")
    with pytest.raises(ValueError, match=r"1 \+ annual_rate \* horizon > 0"):
        total_return_from_rate(-0.6, 2.0, compounding="simple")
    assert total_return_from_rate(-0.499, 2.0, compounding="simple") == pytest.approx(-0.998)


def test_exact_adjusted_return_requires_both_period_endpoints() -> None:
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-03"]))
    assert exact_adjusted_total_return(prices, "2025-01-01", "2025-01-03") == pytest.approx(0.10)
    with pytest.raises(ValueError, match="exact adjusted-return period"):
        exact_adjusted_total_return(prices, "2025-01-01", "2025-01-02")


@pytest.mark.parametrize(
    "prices",
    (
        pd.DataFrame(
            {"date": ["2025-01-01", "2025-01-02"], "adjusted_close": [100.0, True]}
        ),
        pd.DataFrame(
            {"date": ["2025-01-01", "2025-01-02"], "adjusted_close": [100.0, "101.0"]}
        ),
        pd.DataFrame(
            {
                "date": ["2025-01-01", "not-a-date", "2025-01-03"],
                "adjusted_close": [100.0, 101.0, 102.0],
            }
        ),
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025-01-02", "2025-01-02"],
                "adjusted_close": [100.0, 101.0, 101.5],
            }
        ),
    ),
)
def test_exact_adjusted_return_rejects_malformed_raw_evidence(prices: pd.DataFrame) -> None:
    with pytest.raises(ValueError):
        exact_adjusted_total_return(prices, "2025-01-01", "2025-01-03")


def test_cash_builder_rejects_non_risk_free_curve_evidence() -> None:
    prices = pd.Series([100.0, 101.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    result = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(dataset_kind="benchmark"),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert result.status == "unavailable"
    assert result.execution_allowed is False


@pytest.mark.parametrize(
    "update",
    (
        {"unit": "percentage"},
        {"dataset_kind": "benchmark"},
        {"execution_allowed": True},
        {"execution_allowed": 0},
    ),
)
def test_cash_builder_rejects_contradictory_unit_kind_or_authority(
    update: dict[str, object],
) -> None:
    prices = pd.Series([100.0, 101.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    result = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(**update),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert result.status == "unavailable"
    assert result.execution_allowed is False


def test_cash_comparison_is_currency_horizon_vintage_and_inflation_context_matched() -> None:
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    result = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
        inflation_context={"status": "available", "rate": 0.03},
    )
    assert result.status == "available"
    assert result.instrument_return == pytest.approx(0.10)
    assert result.cash_return == pytest.approx((1.05 ** (1.0 / 365.0)) - 1.0)
    assert result.excess_over_cash == pytest.approx(0.10 - result.cash_return)
    assert result.inflation_context == {"status": "available", "rate": 0.03}
    assert result.execution_allowed is False


@pytest.mark.parametrize(
    ("decision_time", "expected_status"),
    (
        ("2025-01-01T00:00:00+00:00", "unavailable"),
        ("2025-01-02T23:59:59+00:00", "unavailable"),
        ("2025-01-03T00:00:00+00:00", "available"),
    ),
)
def test_date_only_adjusted_endpoint_is_available_next_utc_day(
    decision_time: str, expected_status: str
) -> None:
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    result = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time=decision_time,
    )
    assert result.status == expected_status
    assert adjusted_endpoint_available_at("2025-01-02") == "2025-01-03T00:00:00+00:00"


@pytest.mark.parametrize(
    "value",
    (datetime(2025, 1, 1), "1/01-02-2025", "2025-01-01T00:00:00+00:00"),
)
def test_cash_period_dates_reject_datetime_and_noncanonical_strings(value: object) -> None:
    with pytest.raises(ValueError, match="strict YYYY-MM-DD"):
        year_fraction(value, "2025-01-02")


def test_cash_builder_rejects_cutoff_before_period_start_and_validates_immediately() -> None:
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    before_start = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
        knowledge_cutoff="2024-12-31T23:59:59.999999+00:00",
    )
    assert before_start.status == "unavailable"
    assert "knowledge cutoff" in str(before_start.reason)

    built = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert built.status == "available"
    assert validate_cash_comparison_result(built.as_dict(), expected_currency="AUD").status == "available"
    assert built.execution_allowed is False


@pytest.mark.parametrize(
    ("updates", "reason"),
    (
        ({"currency": "EUR"}, "currency"),
        ({"tenor_years": 1.0}, "horizon"),
        ({"curve_type": "par"}, "spot"),
        ({"freshness": "stale"}, "freshness"),
        ({"compounding": None}, "convention"),
        ({"reinvestment": None}, "convention"),
        ({"source_checksum": "bad"}, "checksum"),
        ({"source_terms": None}, "lineage"),
        ({"rate": None}, "lineage"),
        ({"available_at": "2025-01-02T00:00:00+00:00"}, "vintage"),
        ({"available_at": "2024-12-31T00:00:00"}, "timezone-aware"),
        ({"vintage": "2025-01-02T00:00:00+00:00"}, "vintage"),
        ({"freshness_status": "stale"}, "freshness"),
    ),
)
def test_cash_comparison_fail_closed_for_mismatch_or_unavailable_evidence(updates: dict[str, object], reason: str) -> None:
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    result = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(**updates),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert result.status == "unavailable"
    assert reason in str(result.reason)
    assert result.cash_return is None
    assert result.execution_allowed is False


@pytest.mark.parametrize("authority", (None, "official", "vendor_text_claim"))
def test_cash_comparison_requires_positive_official_provenance(authority: str | None) -> None:
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    result = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(source_authority=authority),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert result.status == "unavailable"
    assert "provenance" in str(result.reason)


def test_cash_builder_and_serialized_validator_reject_inverted_bitemporal_evidence() -> None:
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    built = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(
            effective_at="2025-01-03T00:00:00+00:00",
            available_at="2024-12-31T00:00:00+00:00",
        ),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert built.status == "unavailable"
    assert "effective_at" in str(built.reason)

    valid = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
    ).as_dict()
    forged = {**valid, "effective_at": "2025-01-01T00:00:00+00:00", "available_at": "2024-12-31T00:00:00+00:00", "vintage": "2024-12-31T00:00:00+00:00"}
    assert validate_cash_comparison_result(forged, expected_currency="AUD").status == "unavailable"


def test_cash_builder_and_serialized_validator_reject_future_publication() -> None:
    prices = pd.Series(
        [100.0, 110.0],
        index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
    )
    built = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(published_at="2030-01-01T00:00:00+00:00"),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert built.status == "unavailable"
    assert "published_at" in str(built.reason)

    valid = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
    ).as_dict()
    forged = {**valid, "published_at": "2030-01-01T00:00:00+00:00"}
    assert (
        validate_cash_comparison_result(forged, expected_currency="AUD").status
        == "unavailable"
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("source_id", " "),
        ("mapping_methodology", "  "),
        ("curve_version", "\t"),
        ("reinvestment", " "),
    ),
)
def test_cash_builder_and_validator_reject_blank_lineage(
    field_name: str,
    value: object,
) -> None:
    prices = pd.Series(
        [100.0, 110.0],
        index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
    )
    built = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(**{field_name: value}),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert built.status == "unavailable"

    valid = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
    ).as_dict()
    forged = {**valid, field_name: value}
    assert (
        validate_cash_comparison_result(forged, expected_currency="AUD").status
        == "unavailable"
    )


def test_cash_builder_and_validator_reject_unsupported_reinvestment() -> None:
    prices = pd.Series(
        [100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"])
    )
    built = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(reinvestment="unsupported"),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert built.status == "unavailable"
    assert "reinvestment" in str(built.reason)

    forged = {**_available_eur_result(), "reinvestment": "unsupported"}
    validated = validate_cash_comparison_result(forged, expected_currency="EUR")
    assert validated.status == "unavailable"
    assert "reinvestment" in str(validated.reason)


@pytest.mark.parametrize("revision", (True, 1.5, "1"))
def test_cash_builder_and_validator_reject_non_integral_revision(
    revision: object,
) -> None:
    prices = pd.Series(
        [100.0, 110.0],
        index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
    )
    built = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(curve_revision=revision),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert built.status == "unavailable"

    valid = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
    ).as_dict()
    assert (
        validate_cash_comparison_result(
            {**valid, "curve_revision": revision},
            expected_currency="AUD",
        ).status
        == "unavailable"
    )


@pytest.mark.parametrize("instrument_return", (-1.0, -1.5))
def test_serialized_cash_comparison_rejects_impossible_instrument_return(
    instrument_return: float,
) -> None:
    valid = _available_eur_result()
    forged = {
        **valid,
        "instrument_return": instrument_return,
        "excess_over_cash": instrument_return - float(valid["cash_return"]),
    }
    result = validate_cash_comparison_result(forged, expected_currency="EUR")
    assert result.status == "unavailable"
    assert result.instrument_return is None
    assert result.cash_return is None


def test_continuous_cash_return_rejects_underflow_to_total_loss() -> None:
    with pytest.raises(ValueError, match="greater than -1"):
        total_return_from_rate(
            -1_000_000.0,
            1.0,
            compounding="continuous",
        )


def test_adjusted_return_construction_rejects_underflow_to_total_loss() -> None:
    prices = pd.Series(
        [1e308, 5e-324],
        index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
    )
    with pytest.raises(ValueError, match="greater than -1"):
        exact_adjusted_total_return(prices, "2025-01-01", "2025-01-02")

    result = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert result.status == "unavailable"
    assert result.instrument_return is None


def test_fallback_lineage_must_be_nonblank_at_construction_and_readback() -> None:
    prices = pd.Series(
        [100.0, 101.0],
        index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
    )
    built = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(fallback=True, fallback_from="   "),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert built.status == "unavailable"

    valid = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
    ).as_dict()
    forged = {**valid, "fallback": True, "fallback_from": "   "}
    assert (
        validate_cash_comparison_result(forged, expected_currency="AUD").status
        == "unavailable"
    )


def test_cash_comparison_does_not_turn_missing_inflation_into_real_return() -> None:
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    result = build_cash_comparison(
        adjusted_prices=prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert result.status == "available"
    assert result.inflation_context is None
    assert "real" not in result.as_dict()


def _curve(*, version: str = "v1", available_at: str = "2024-12-31T00:00:00+00:00", published_at: str | None = None, effective_at: str = "2024-01-01T00:00:00+00:00", rate: float = 0.05, curve_type: str = "spot", freshness: str | None = "fresh", revision: int = 1, day_count: str = "ACT/365F", tenor_years: float = 1.0 / 365.0) -> CurveSnapshot:
    return CurveSnapshot(
        curve_id="aud-cash",
        curve_version=version,
        curve_type=curve_type,
        currency="AUD",
        effective_at=effective_at,
        published_at=published_at or available_at,
        available_at=available_at,
        ingested_at=available_at,
        source_id="official-curve",
        source_authority="official_public_file",
        source_checksum=("a" if version == "v1" else "b") * 64,
        source_terms="official-public-file",
        methodology="official spot curve",
        compounding="annual",
        day_count=day_count,
        reinvestment="reinvested_income",
        freshness=freshness,
        freshness_status=freshness,
        points=(CurvePoint(tenor_years=tenor_years, rate=rate),),
        revision=revision,
    )


def test_warehouse_cash_comparison_selects_only_vintage_known_by_period_start(tmp_path) -> None:
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(_curve(), root=tmp_path)
    warehouse.ingest_curve(_curve(version="v2", available_at="2025-01-02T00:00:00+00:00", rate=0.06, revision=2), root=tmp_path)
    mapping = RiskFreeProxyMapping(
        currency="AUD",
        minimum_horizon_years=1.0 / 365.0,
        maximum_horizon_years=1.0 / 365.0,
        curve_id="aud-cash",
        methodology="official cash mapping",
    )
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
    historical = warehouse.cash_comparison(
        root=tmp_path,
        mappings=(mapping,),
        currency="AUD",
        start_date="2025-01-01",
        end_date="2025-01-02",
        decision_time="2025-01-15T00:00:00+00:00",
        adjusted_prices=prices,
    )
    assert historical["status"] == "available"
    assert historical["vintage"] == "2024-12-31T00:00:00+00:00"
    assert historical["rate"] == pytest.approx(0.05)
    assert historical["knowledge_cutoff"] == "2025-01-01T00:00:00+00:00"

    par_root = tmp_path / "par"
    warehouse.ingest_curve(_curve(curve_type="par"), root=par_root)
    unsupported = warehouse.cash_comparison(
        root=par_root,
        mappings=(mapping,),
        currency="AUD",
        start_date="2025-01-01",
        end_date="2025-01-02",
        decision_time="2025-01-15T00:00:00+00:00",
        adjusted_prices=prices,
    )
    assert unsupported["status"] == "unavailable"
    assert "spot" in str(unsupported["reason"])


@pytest.mark.parametrize("day_count", ("ACT/360", "ACT/ACT-ISDA"))
def test_warehouse_queries_exact_tenor_under_selected_curve_day_count(tmp_path, day_count: str) -> None:
    start, end = "2024-12-31", "2025-01-02"
    horizon = year_fraction(start, end, day_count)
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(
        _curve(day_count=day_count, tenor_years=horizon),
        root=tmp_path,
    )
    mapping = RiskFreeProxyMapping(
        currency="AUD",
        minimum_horizon_years=horizon,
        maximum_horizon_years=horizon,
        curve_id="aud-cash",
        methodology="official cash mapping",
    )
    result = warehouse.cash_comparison(
        root=tmp_path,
        mappings=(mapping,),
        currency="AUD",
        start_date=start,
        end_date=end,
        decision_time="2025-01-03T00:00:00+00:00",
        adjusted_prices=pd.Series([100.0, 110.0], index=pd.to_datetime([start, end])),
    )
    assert result["status"] == "available"
    assert result["day_count"] == day_count
    assert result["horizon_years"] == pytest.approx(horizon)


def test_curve_ingest_rejects_ambiguous_timestamps_and_unofficial_provenance(tmp_path) -> None:
    with pytest.raises(MacroWarehouseError, match="timezone-aware"):
        MacroWarehouse().ingest_curve(
            _curve(effective_at="2024-01-01"),
            root=tmp_path,
        )
    with pytest.raises(ValueError):
        CurveSnapshot(
            **_curve().model_dump(exclude={"source_authority"}),
            source_authority="official",
        )


def test_curve_interpolation_never_mixes_partial_revisions(tmp_path) -> None:
    warehouse = MacroWarehouse()
    old = _curve().model_copy(
        update={
            "points": (
                CurvePoint(tenor_years=1.0, rate=0.01),
                CurvePoint(tenor_years=2.0, rate=0.02),
            )
        }
    )
    partial_revision = _curve(
        version="v2",
        available_at="2024-12-31T00:00:00+00:00",
        revision=2,
    ).model_copy(
        update={"points": (CurvePoint(tenor_years=2.0, rate=0.20),)}
    )
    warehouse.ingest_curve(old, root=tmp_path)
    warehouse.ingest_curve(partial_revision, root=tmp_path)

    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="aud-cash",
        tenor_years=1.5,
        decision_time="2025-01-01T00:00:00+00:00",
    )

    assert selected["status"] == "unavailable"
    assert "conflicted" in str(selected["reason"])
    assert selected.get("rate") != pytest.approx(0.105)


def test_benchmark_attribution_and_projection_fields_keep_cash_descriptive() -> None:
    index = pd.date_range("2025-01-01", periods=3, freq="D")
    cash = build_cash_comparison(
        adjusted_prices=pd.Series(
            [100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-02"])
        ),
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="AUD",
        cash_evidence=_evidence(),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    result = build_benchmark_attribution(
        pd.Series([0.01, 0.02, 0.0], index=index),
        pd.Series([0.005, 0.01, 0.0], index=index),
        cash_comparison=cash.as_dict(),
        instrument_currency="AUD",
    )
    assert result.cash_return == pytest.approx(cash.cash_return)
    assert result.excess_over_cash == pytest.approx(cash.excess_over_cash)
    assert result.cash_unit == "decimal"
    assert result.cash_dataset_kind == "risk_free"
    assert result.execution_allowed is False


def test_benchmark_attribution_rejects_cash_for_another_instrument_currency() -> None:
    index = pd.date_range("2025-01-01", periods=3, freq="D")
    result = build_benchmark_attribution(
        pd.Series([0.01, 0.02, 0.0], index=index),
        pd.Series([0.005, 0.01, 0.0], index=index),
        cash_comparison=_available_eur_result(),
        instrument_currency="USD",
    )

    assert result.cash_comparison_status == "unavailable"
    assert result.cash_return is None
    assert result.excess_over_cash is None
    assert result.execution_allowed is False


def test_valid_cash_survives_insufficient_broad_attribution() -> None:
    index = pd.date_range("2025-01-01", periods=1, freq="D")
    cash = _available_eur_result()
    result = build_benchmark_attribution(
        pd.Series([0.01], index=index),
        pd.Series([0.005], index=index),
        cash_comparison=cash,
        instrument_currency="EUR",
    )
    assert result.status == "unavailable"
    assert result.cash_comparison_status == "available"
    assert result.cash_return == pytest.approx(cash["cash_return"])
    assert result.cash_unit == "decimal"
    assert result.cash_dataset_kind == "risk_free"
    assert result.excess_over_cash == pytest.approx(cash["excess_over_cash"])


@pytest.mark.parametrize("instrument_currency", (None, "USD"))
def test_persistence_requires_matching_instrument_currency_for_cash(
    tmp_path, monkeypatch, instrument_currency: str | None
) -> None:
    valid = _available_eur_result()
    projection = cash_comparison_to_projection(valid, expected_currency="EUR")
    frame = pd.DataFrame(
        [{"instrument_id": "EUR-TEST", "instrument_currency": instrument_currency, **projection}]
    )
    attribution_path = tmp_path / "benchmark_attribution.parquet"
    monkeypatch.setattr(trust_artifacts, "BENCHMARK_ATTRIBUTION_PATH", attribution_path)
    trust_artifacts.write_benchmark_attribution(frame)
    persisted = pd.read_parquet(attribution_path)
    assert persisted.loc[0, "cash_comparison_status"] == "unavailable"
    assert pd.isna(persisted.loc[0, "cash_return"])


def _control_text(control: object) -> str:
    values: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        values.append(value)
    for child in getattr(control, "controls", ()) or ():
        values.append(_control_text(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.append(_control_text(content))
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            values.append(_control_text(getattr(cell, "content", None)))
    return "\n".join(item for item in values if item)


def _available_eur_result() -> dict[str, object]:
    result = build_cash_comparison(
        adjusted_prices=pd.Series(
            [100.0, 105.79], index=pd.to_datetime(["2025-01-01", "2026-01-01"])
        ),
        start_date="2025-01-01",
        end_date="2026-01-01",
        instrument_currency="EUR",
        cash_evidence=_evidence(
            currency="EUR",
            tenor_years=1.0,
            rate=0.0123,
            source_id="official-caller-provided-curve",
            source_checksum="c" * 64,
            mapping_methodology="caller-provided EUR cash mapping",
            curve_id="eur-caller-provided-spot",
        ),
        decision_time="2026-01-02T00:00:00+00:00",
        inflation_context={"status": "unavailable"},
    )
    assert result.status == "available"
    return result.as_dict()


@pytest.mark.parametrize("value", (True, "0.01"))
@pytest.mark.parametrize("field_name", ("rate", "tenor_years"))
def test_cash_builder_rejects_coercive_curve_values(
    field_name: str, value: object
) -> None:
    evidence = _evidence(currency="EUR", tenor_years=1.0)
    evidence[field_name] = value
    result = build_cash_comparison(
        adjusted_prices=pd.Series(
            [100.0, 105.79], index=pd.to_datetime(["2025-01-01", "2026-01-01"])
        ),
        start_date="2025-01-01",
        end_date="2026-01-01",
        instrument_currency="EUR",
        cash_evidence=evidence,
        decision_time="2026-01-02T00:00:00+00:00",
    )
    assert result.status == "unavailable"


@pytest.mark.parametrize("value", (True, "0.01"))
@pytest.mark.parametrize(
    "field_name",
    ("instrument_return", "cash_return", "excess_over_cash", "horizon_years", "rate"),
)
def test_serialized_cash_comparison_rejects_coercive_financial_values(
    field_name: str, value: object
) -> None:
    result = validate_cash_comparison_result(
        {**_available_eur_result(), field_name: value},
        expected_currency="EUR",
    )
    assert result.status == "unavailable"
    assert result.execution_allowed is False


def test_instrument_detail_fallback_preserves_valid_scoreboard_cash() -> None:
    scoreboard = {
        "instrument_currency": "EUR",
        **cash_comparison_to_projection(
            _available_eur_result(), expected_currency="EUR"
        ),
    }
    panel = instrument_detail_selector._attribution_panel(
        {"attribution": {"status": "unavailable"}},
        scoreboard,
    )
    assert panel["status"] == "available"
    assert panel["cash_comparison_status"] == "available"
    assert panel["cash_return"] == pytest.approx(scoreboard["cash_return"])
    assert panel["execution_allowed"] is False

    missing_currency = dict(scoreboard)
    missing_currency.pop("instrument_currency")
    rejected = instrument_detail_selector._attribution_panel(
        {"attribution": {"status": "unavailable"}},
        missing_currency,
    )
    assert rejected["status"] == "unavailable"
    assert rejected.get("cash_comparison_status") != "available"
    assert rejected["execution_allowed"] is False


def test_cash_projection_round_trip_preserves_non_execution_authority() -> None:
    projection = cash_comparison_to_projection(
        _available_eur_result(), expected_currency="EUR"
    )
    assert projection["execution_allowed"] is False
    assert projection["cash_unit"] == "decimal"
    assert projection["cash_dataset_kind"] == "risk_free"
    round_trip = validate_cash_comparison_result(
        cash_comparison_from_projection(projection), expected_currency="EUR"
    )
    assert round_trip.status == "available"
    assert round_trip.unit == "decimal"
    assert round_trip.dataset_kind == "risk_free"
    assert round_trip.execution_allowed is False


def test_cash_validator_and_simple_consumer_fail_closed_on_pd_na_status() -> None:
    forged = {**_available_eur_result(), "status": pd.NA}
    validated = validate_cash_comparison_result(forged, expected_currency="EUR")
    assert validated.status == "unavailable"
    assert validated.execution_allowed is False

    snapshot = build_snapshot()
    instrument_id = snapshot.signals[0].etf_id
    score = next(
        item
        for item in build_simple_instrument_scores(
            snapshot.config,
            snapshot.signals,
            snapshot.forecasts,
            snapshot.prices,
            cash_comparison_lookup={instrument_id: forged},
        )
        if item.display_id == instrument_id
    )
    assert score.cash_comparison_status == "unavailable"
    assert score.cash_unit is None
    assert score.cash_dataset_kind is None


def test_cash_builder_fails_closed_on_pd_na_evidence_currency() -> None:
    result = build_cash_comparison(
        adjusted_prices=pd.Series(
            [100.0, 101.0],
            index=pd.to_datetime(["2025-01-01", "2026-01-01"]),
        ),
        start_date="2025-01-01",
        end_date="2026-01-01",
        instrument_currency="EUR",
        cash_evidence=_evidence(currency=pd.NA),
        decision_time="2026-01-02T00:00:00+00:00",
    )
    assert result.status == "unavailable"
    assert "currency" in str(result.reason)
    assert result.execution_allowed is False


def test_cash_builder_fails_closed_on_pd_na_instrument_currency() -> None:
    result = build_cash_comparison(
        adjusted_prices=pd.Series(
            [100.0, 101.0],
            index=pd.to_datetime(["2025-01-01", "2026-01-01"]),
        ),
        start_date="2025-01-01",
        end_date="2026-01-01",
        instrument_currency=pd.NA,
        cash_evidence=_evidence(currency="EUR"),
        decision_time="2026-01-02T00:00:00+00:00",
    )
    assert result.status == "unavailable"
    assert "currency" in str(result.reason)
    assert result.execution_allowed is False


def test_cash_builder_rejects_offset_price_endpoint_before_utc_availability() -> None:
    result = build_cash_comparison(
        adjusted_prices=pd.Series(
            [100.0, 110.0],
            index=["2025-01-01", "2025-01-02T23:30:00-12:00"],
        ),
        start_date="2025-01-01",
        end_date="2025-01-02",
        instrument_currency="EUR",
        cash_evidence=_evidence(currency="EUR"),
        decision_time="2025-01-03T00:00:00+00:00",
    )
    assert result.status == "unavailable"
    assert "date" in str(result.reason) or "timestamp" in str(result.reason)
    assert result.execution_allowed is False


def test_injected_cash_comparison_propagates_without_changing_score_authority(
    tmp_path, monkeypatch
) -> None:
    snapshot = build_snapshot()
    instrument_id = snapshot.signals[0].etf_id
    baseline = {
        score.display_id: score
        for score in build_simple_instrument_scores(
            snapshot.config, snapshot.signals, snapshot.forecasts, snapshot.prices
        )
    }[instrument_id]
    injected = _available_eur_result()
    available = {
        score.display_id: score
        for score in build_simple_instrument_scores(
            snapshot.config,
            snapshot.signals,
            snapshot.forecasts,
            snapshot.prices,
            cash_comparison_lookup={instrument_id: injected},
        )
    }[instrument_id]
    unavailable = {
        score.display_id: score
        for score in build_simple_instrument_scores(
            snapshot.config,
            snapshot.signals,
            snapshot.forecasts,
            snapshot.prices,
            cash_comparison_lookup={
                instrument_id: {
                    "status": "unavailable",
                    "reason": "caller mapping unavailable",
                    "execution_allowed": False,
                }
            },
        )
    }[instrument_id]

    def authority(score):
        return (
            score.final_score_10,
            score.decision,
            score.final_action,
            score.research_state,
            score.portfolio_review_state,
            score.authority_decision,
            score.canonical_score,
        )
    assert authority(available) == authority(baseline) == authority(unavailable)
    assert available.cash_return == pytest.approx(injected["cash_return"])
    assert available.cash_source_terms == injected["source_terms"]
    assert available.cash_knowledge_cutoff == injected["knowledge_cutoff"]
    assert available.inflation_context == injected["inflation_context"]
    assert available.execution_allowed is False
    assert baseline.cash_comparison_status == "unavailable"
    assert unavailable.cash_comparison_status == "unavailable"
    assert unavailable.cash_comparison_reason == "caller mapping unavailable"

    malformed = {
        score.display_id: score
        for score in build_simple_instrument_scores(
            snapshot.config,
            snapshot.signals,
            snapshot.forecasts,
            snapshot.prices,
            cash_comparison_lookup={
                instrument_id: {
                    "status": "available",
                    "cash_return": 99.0,
                    "execution_allowed": False,
                }
            },
        )
    }[instrument_id]
    assert malformed.cash_comparison_status == "unavailable"
    assert malformed.cash_return is None
    assert authority(malformed) == authority(baseline)

    other_unavailable = next(
        score
        for score in build_simple_instrument_scores(
            snapshot.config, snapshot.signals, snapshot.forecasts, snapshot.prices
        )
        if score.display_id != instrument_id
    )
    frame = simple_scoreboard_frame([available, other_unavailable])
    row = frame.iloc[0]
    assert row["cash_return"] == pytest.approx(injected["cash_return"])
    assert row["cash_unit"] == "decimal"
    assert row["cash_dataset_kind"] == "risk_free"
    assert row["cash_source_id"] == injected["source_id"]
    assert row["cash_source_terms"] == injected["source_terms"]
    assert row["cash_knowledge_cutoff"] == injected["knowledge_cutoff"]
    assert str(frame["cash_curve_revision"].dtype) == "Int64"
    assert bool(row["execution_allowed"]) is False

    attribution_path = tmp_path / "benchmark_attribution.parquet"
    monkeypatch.setattr(trust_artifacts, "BENCHMARK_ATTRIBUTION_PATH", attribution_path)
    monkeypatch.setattr(
        instrument_detail_selector, "BENCHMARK_ATTRIBUTION_PATH", attribution_path
    )
    trust_artifacts.write_benchmark_attribution(frame)
    persisted = pd.read_parquet(attribution_path).iloc[0]
    readback = instrument_detail_selector._derived_evidence_panel(
        instrument_id, expected_currency="EUR"
    )[
        "attribution"
    ]
    assert persisted["cash_return"] == pytest.approx(injected["cash_return"])
    assert persisted["cash_unit"] == "decimal"
    assert persisted["cash_dataset_kind"] == "risk_free"
    assert persisted["cash_source_terms"] == injected["source_terms"]
    assert persisted["cash_knowledge_cutoff"] == injected["knowledge_cutoff"]
    assert str(pd.read_parquet(attribution_path)["cash_curve_revision"].dtype) == "Int64"
    assert bool(persisted["execution_allowed"]) is False
    assert readback["cash_return"] == pytest.approx(injected["cash_return"])
    assert readback["cash_unit"] == "decimal"
    assert readback["cash_dataset_kind"] == "risk_free"
    assert readback["cash_source_id"] == injected["source_id"]
    assert readback["cash_source_terms"] == injected["source_terms"]
    assert readback["cash_knowledge_cutoff"] == injected["knowledge_cutoff"]
    assert readback["execution_allowed"] is False

    missing_currency = instrument_detail_selector._derived_evidence_panel(
        instrument_id
    )["attribution"]
    assert missing_currency["cash_comparison_status"] == "unavailable"
    assert missing_currency.get("cash_return") is None
    assert missing_currency["execution_allowed"] is False

    comparison_text = _control_text(_comparison_table(available, unavailable))
    assert "Cash return" in comparison_text
    assert "1.2%" in comparison_text
    assert "unavailable" in comparison_text


def test_forged_cash_results_fail_closed_through_every_generic_consumer(
    tmp_path, monkeypatch
) -> None:
    snapshot = build_snapshot()
    eur_ids = [
        signal.etf_id
        for signal in snapshot.signals
        if snapshot.config.universe.by_id()[signal.etf_id].currency == "EUR"
    ]
    mutations = (
        {"currency": "USD"},
        {"freshness": "stale", "freshness_status": "stale"},
        {"curve_type": "par"},
        {"compounding": "unsupported"},
        {"cash_return": 99.0},
        {"excess_over_cash": 99.0},
        {"horizon_years": 2.0},
        {
            "vintage": "2025-01-02T00:00:00+00:00",
            "available_at": "2025-01-02T00:00:00+00:00",
        },
    )
    assert len(eur_ids) >= len(mutations)
    lookup: dict[str, dict[str, object]] = {}
    for instrument_id, mutation in zip(
        eur_ids[: len(mutations)], mutations, strict=True
    ):
        forged = {**_available_eur_result(), **mutation}
        validated = validate_cash_comparison_result(
            forged, expected_currency="EUR"
        )
        assert validated.status == "unavailable"
        assert validated.instrument_return is None
        assert validated.cash_return is None
        assert validated.excess_over_cash is None
        assert validated.rate is None
        assert validated.horizon_years is None
        lookup[instrument_id] = forged

    baseline = {
        score.display_id: score
        for score in build_simple_instrument_scores(
            snapshot.config, snapshot.signals, snapshot.forecasts, snapshot.prices
        )
    }
    scores = build_simple_instrument_scores(
        snapshot.config,
        snapshot.signals,
        snapshot.forecasts,
        snapshot.prices,
        cash_comparison_lookup=lookup,
    )
    by_id = {score.display_id: score for score in scores}
    for instrument_id in lookup:
        score = by_id[instrument_id]
        assert score.cash_comparison_status == "unavailable"
        assert score.cash_instrument_return is None
        assert score.cash_return is None
        assert score.excess_over_cash is None
        assert score.cash_rate is None
        assert score.final_score_10 == baseline[instrument_id].final_score_10
        assert score.decision == baseline[instrument_id].decision
        assert score.final_action == baseline[instrument_id].final_action
        assert score.authority_decision == baseline[instrument_id].authority_decision
        assert score.execution_allowed is False

    frame = simple_scoreboard_frame([by_id[item] for item in lookup])
    assert set(frame["cash_comparison_status"]) == {"unavailable"}
    assert frame["cash_return"].isna().all()
    assert frame["excess_over_cash"].isna().all()
    attribution_path = tmp_path / "forged_benchmark_attribution.parquet"
    monkeypatch.setattr(trust_artifacts, "BENCHMARK_ATTRIBUTION_PATH", attribution_path)
    monkeypatch.setattr(
        instrument_detail_selector, "BENCHMARK_ATTRIBUTION_PATH", attribution_path
    )
    trust_artifacts.write_benchmark_attribution(frame)
    persisted = pd.read_parquet(attribution_path)
    assert set(persisted["cash_comparison_status"]) == {"unavailable"}
    assert persisted["cash_return"].isna().all()
    for instrument_id in lookup:
        readback = instrument_detail_selector._derived_evidence_panel(
            instrument_id, expected_currency="EUR"
        )["attribution"]
        assert readback["cash_comparison_status"] == "unavailable"
        assert readback["cash_return"] is None
        assert readback["execution_allowed"] is False
    ui_text = _control_text(_comparison_table(by_id[eur_ids[0]], by_id[eur_ids[1]]))
    assert ui_text.count("unavailable") >= 2


def test_local_official_curve_flows_through_normal_score_build_and_ui(
    tmp_path, monkeypatch
) -> None:
    snapshot = build_snapshot()
    identity_by_id = snapshot.config.universe.by_id()
    instrument_id = next(
        signal.etf_id
        for signal in snapshot.signals
        if identity_by_id[signal.etf_id].currency == "EUR"
    )
    instrument_prices = snapshot.prices.loc[
        snapshot.prices["etf_id"].astype(str) == instrument_id,
        ["date", "adjusted_close"],
    ].dropna()
    instrument_prices["date"] = pd.to_datetime(instrument_prices["date"], utc=True)
    instrument_prices = instrument_prices.sort_values("date").tail(121)
    start = instrument_prices.iloc[0]["date"].date()
    end = instrument_prices.iloc[-1]["date"].date()
    horizon = (end - start).days / 365.0
    available = (pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=2)).isoformat()

    mapping_path = tmp_path / "risk_free_proxies.json"
    mapping_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "mappings": [
                    {
                        "currency": "EUR",
                        "minimum_horizon_years": 0.0,
                        "maximum_horizon_years": 10.0,
                        "curve_id": "eur-official-local-spot",
                        "fallback_curve_ids": [],
                        "methodology": "Explicit official EUR local proxy mapping v1",
                        "execution_allowed": False,
                    }
                ],
                "execution_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        macro_warehouse_module, "RISK_FREE_PROXY_CONFIG_PATH", mapping_path
    )
    monkeypatch.setattr(simple_scores_module, "CASH_MACRO_ROOT", tmp_path)
    MacroWarehouse().ingest_curve(
        CurveSnapshot(
            curve_id="eur-official-local-spot",
            curve_version="official-local-v1",
            curve_type="spot",
            currency="EUR",
            effective_at=available,
            published_at=available,
            available_at=available,
            ingested_at=available,
            source_id="official-local-public-file",
            source_authority="official_public_file",
            source_checksum="d" * 64,
            source_terms="official-public-file",
            methodology="Official EUR spot curve",
            interpolation="none",
            compounding="annual",
            day_count="ACT/365F",
            reinvestment="reinvested_income",
            freshness="fresh",
            freshness_status="fresh",
            points=(CurvePoint(tenor_years=horizon, rate=0.02),),
            revision=1,
        ),
        root=tmp_path,
    )

    scores = build_simple_instrument_scores(
        snapshot.config, snapshot.signals, snapshot.forecasts, snapshot.prices
    )
    available_score = {score.display_id: score for score in scores}[instrument_id]
    assert available_score.cash_comparison_status == "available"
    assert available_score.cash_currency == "EUR"
    assert available_score.cash_source_authority == "official_public_file"
    assert available_score.cash_curve_id == "eur-official-local-spot"
    assert available_score.cash_decision_time == adjusted_endpoint_available_at(
        available_score.cash_end_date
    )
    assert pd.Timestamp(available_score.cash_decision_time) <= pd.Timestamp.now(tz="UTC")
    assert available_score.execution_allowed is False

    frame = simple_scoreboard_frame([available_score])
    attribution_path = tmp_path / "local_benchmark_attribution.parquet"
    monkeypatch.setattr(trust_artifacts, "BENCHMARK_ATTRIBUTION_PATH", attribution_path)
    monkeypatch.setattr(
        instrument_detail_selector, "BENCHMARK_ATTRIBUTION_PATH", attribution_path
    )
    trust_artifacts.write_benchmark_attribution(frame)
    readback = instrument_detail_selector._derived_evidence_panel(
        instrument_id, expected_currency="EUR"
    )["attribution"]
    assert readback["cash_comparison_status"] == "available"
    assert readback["cash_return"] == pytest.approx(available_score.cash_return)
    assert readback["cash_source_authority"] == "official_public_file"
    assert "available" in _control_text(
        _comparison_table(available_score, available_score)
    )

    baseline_authority = (
        available_score.final_score_10,
        available_score.decision,
        available_score.final_action,
        available_score.authority_decision,
    )
    mapping_path.unlink()
    absent_score = {
        score.display_id: score
        for score in build_simple_instrument_scores(
            snapshot.config, snapshot.signals, snapshot.forecasts, snapshot.prices
        )
    }[instrument_id]
    mapping_path.write_text("{malformed", encoding="utf-8")
    corrupt_score = {
        score.display_id: score
        for score in build_simple_instrument_scores(
            snapshot.config, snapshot.signals, snapshot.forecasts, snapshot.prices
        )
    }[instrument_id]
    for score in (absent_score, corrupt_score):
        assert score.cash_comparison_status == "unavailable"
        assert score.cash_return is None
        assert score.execution_allowed is False
        assert (
            score.final_score_10,
            score.decision,
            score.final_action,
            score.authority_decision,
        ) == baseline_authority


def test_local_cash_lookup_excludes_an_adjusted_endpoint_not_yet_available(
    monkeypatch,
) -> None:
    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    identity = snapshot.config.universe.by_id()[instrument_id]
    future_end = pd.Timestamp("2030-01-02T00:00:00Z")
    prices = pd.DataFrame(
        {
            "etf_id": [instrument_id, instrument_id],
            "date": [future_end - pd.Timedelta(days=1), future_end],
            "adjusted_close": [100.0, 101.0],
        }
    )
    mapping = RiskFreeProxyMapping(
        currency=identity.currency,
        minimum_horizon_years=0.0,
        maximum_horizon_years=10.0,
        curve_id="unused",
        fallback_curve_ids=(),
        methodology="test mapping",
    )
    monkeypatch.setattr(
        simple_scores_module,
        "load_risk_free_proxy_mappings",
        lambda: (mapping,),
    )
    lookup = simple_scores_module._build_local_cash_comparison_lookup(
        snapshot.config,
        prices,
        as_of="2030-01-02T12:00:00Z",
    )

    assert instrument_id not in lookup
