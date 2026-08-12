from __future__ import annotations

import math

import pandas as pd
import pytest

from etf_cockpit.app.pages.comparison import _comparison_table
from etf_cockpit.app.selectors import instrument_detail as instrument_detail_selector
from etf_cockpit.data import trust_artifacts
from etf_cockpit.data.macro_warehouse import (
    CurvePoint,
    CurveSnapshot,
    MacroWarehouse,
    RiskFreeProxyMapping,
)
from etf_cockpit.features.benchmark_attribution import build_benchmark_attribution
from etf_cockpit.features.cash_comparison import (
    build_cash_comparison,
    exact_adjusted_total_return,
    total_return_from_rate,
    year_fraction,
)
from etf_cockpit.services import build_snapshot
from etf_cockpit.signals.simple_scores import (
    build_simple_instrument_scores,
    simple_scoreboard_frame,
)


def _evidence(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "status": "available",
        "curve_type": "spot",
        "currency": "AUD",
        "tenor_years": 1.0 / 365.0,
        "rate": 0.05,
        "compounding": "annual",
        "day_count": "ACT/365F",
        "reinvestment": "reinvested_income",
        "freshness": "fresh",
        "vintage": "2024-12-31T00:00:00+00:00",
        "effective_at": "2024-01-01T00:00:00+00:00",
        "available_at": "2024-12-31T00:00:00+00:00",
        "source_id": "official-curve",
        "source_checksum": "a" * 64,
        "source_terms": "official-public-file",
        "methodology": "official spot curve",
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


def test_annual_rate_domain_is_strict() -> None:
    with pytest.raises(ValueError, match="annual_rate > -1"):
        total_return_from_rate(-1.0, 1.0, compounding="annual")


def test_exact_adjusted_return_requires_both_period_endpoints() -> None:
    prices = pd.Series([100.0, 110.0], index=pd.to_datetime(["2025-01-01", "2025-01-03"]))
    assert exact_adjusted_total_return(prices, "2025-01-01", "2025-01-03") == pytest.approx(0.10)
    with pytest.raises(ValueError, match="exact adjusted-return period"):
        exact_adjusted_total_return(prices, "2025-01-01", "2025-01-02")


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
        ({"available_at": "2025-01-02T00:00:00+00:00"}, "point-in-time"),
        ({"available_at": "2024-12-31T00:00:00"}, "timezone-aware"),
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


def _curve(*, version: str = "v1", available_at: str = "2024-12-31T00:00:00+00:00", rate: float = 0.05, curve_type: str = "spot", freshness: str | None = "fresh", revision: int = 1) -> CurveSnapshot:
    return CurveSnapshot(
        curve_id="aud-cash",
        curve_version=version,
        curve_type=curve_type,
        currency="AUD",
        effective_at="2024-01-01T00:00:00+00:00",
        available_at=available_at,
        ingested_at=available_at,
        source_id="official-curve",
        source_checksum=("a" if version == "v1" else "b") * 64,
        source_terms="official-public-file",
        methodology="official spot curve",
        compounding="annual",
        day_count="ACT/365F",
        reinvestment="reinvested_income",
        freshness=freshness,
        points=(CurvePoint(tenor_years=1.0 / 365.0, rate=rate),),
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


def test_benchmark_attribution_and_projection_fields_keep_cash_descriptive() -> None:
    index = pd.date_range("2025-01-01", periods=3, freq="D")
    result = build_benchmark_attribution(
        pd.Series([0.01, 0.02, 0.0], index=index),
        pd.Series([0.005, 0.01, 0.0], index=index),
        cash_comparison={
            "status": "available",
            "cash_return": 0.01,
            "excess_over_cash": 0.02,
            "currency": "AUD",
            "horizon_years": 1.0,
            "vintage": "2025-01-02T00:00:00+00:00",
        },
    )
    assert result.cash_return == pytest.approx(0.01)
    assert result.excess_over_cash == pytest.approx(0.02)
    assert result.execution_allowed is False


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
    injected = {
        "status": "available",
        "instrument_return": 0.0579,
        "cash_return": 0.0123,
        "excess_over_cash": 0.0456,
        "currency": "EUR",
        "start_date": "2025-01-01",
        "end_date": "2026-01-01",
        "horizon_years": 1.0,
        "rate": 0.0123,
        "vintage": "2024-12-31T00:00:00+00:00",
        "source_id": "official-caller-provided-curve",
        "source_checksum": "c" * 64,
        "source_terms": "official-public-file",
        "methodology": "official spot curve",
        "mapping_methodology": "caller-provided EUR cash mapping",
        "day_count": "ACT/365F",
        "compounding": "annual",
        "reinvestment": "reinvested_income",
        "effective_at": "2024-12-31T00:00:00+00:00",
        "available_at": "2024-12-31T00:00:00+00:00",
        "curve_id": "eur-caller-provided-spot",
        "curve_version": "v1",
        "curve_type": "spot",
        "fallback": False,
        "fallback_from": None,
        "interpolation": "none",
        "freshness": "fresh",
        "decision_time": "2025-01-02T00:00:00+00:00",
        "knowledge_cutoff": "2025-01-01T00:00:00+00:00",
        "inflation_context": {"status": "unavailable"},
        "execution_allowed": False,
    }
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
    assert available.cash_return == injected["cash_return"]
    assert available.cash_source_terms == injected["source_terms"]
    assert available.cash_knowledge_cutoff == injected["knowledge_cutoff"]
    assert available.inflation_context is injected["inflation_context"]
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

    frame = simple_scoreboard_frame([available])
    row = frame.iloc[0]
    assert row["cash_return"] == injected["cash_return"]
    assert row["cash_source_id"] == injected["source_id"]
    assert row["cash_source_terms"] == injected["source_terms"]
    assert row["cash_knowledge_cutoff"] == injected["knowledge_cutoff"]
    assert row["execution_allowed"] is False or not bool(row["execution_allowed"])

    attribution_path = tmp_path / "benchmark_attribution.parquet"
    monkeypatch.setattr(trust_artifacts, "BENCHMARK_ATTRIBUTION_PATH", attribution_path)
    monkeypatch.setattr(
        instrument_detail_selector, "BENCHMARK_ATTRIBUTION_PATH", attribution_path
    )
    trust_artifacts.write_benchmark_attribution(frame)
    persisted = pd.read_parquet(attribution_path).iloc[0]
    readback = instrument_detail_selector._derived_evidence_panel(instrument_id)[
        "attribution"
    ]
    assert persisted["cash_return"] == injected["cash_return"]
    assert persisted["cash_source_terms"] == injected["source_terms"]
    assert persisted["cash_knowledge_cutoff"] == injected["knowledge_cutoff"]
    assert not bool(persisted["execution_allowed"])
    assert readback["cash_return"] == injected["cash_return"]
    assert readback["cash_source_id"] == injected["source_id"]
    assert readback["cash_source_terms"] == injected["source_terms"]
    assert readback["cash_knowledge_cutoff"] == injected["knowledge_cutoff"]
    assert readback["execution_allowed"] is False

    comparison_text = _control_text(_comparison_table(available, unavailable))
    assert "Cash return" in comparison_text
    assert "1.2%" in comparison_text
    assert "unavailable" in comparison_text
