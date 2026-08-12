from __future__ import annotations

import json
import math

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
    RiskFreeProxyMapping,
)
from etf_cockpit.features.benchmark_attribution import build_benchmark_attribution
from etf_cockpit.features.cash_comparison import (
    adjusted_endpoint_available_at,
    build_cash_comparison,
    exact_adjusted_total_return,
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
        "available_at": "2024-12-31T00:00:00+00:00",
        "source_id": "official-curve",
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
        freshness_status=freshness,
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
    )
    assert result.cash_return == pytest.approx(cash.cash_return)
    assert result.excess_over_cash == pytest.approx(cash.excess_over_cash)
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

    frame = simple_scoreboard_frame([available])
    row = frame.iloc[0]
    assert row["cash_return"] == pytest.approx(injected["cash_return"])
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
    assert persisted["cash_return"] == pytest.approx(injected["cash_return"])
    assert persisted["cash_source_terms"] == injected["source_terms"]
    assert persisted["cash_knowledge_cutoff"] == injected["knowledge_cutoff"]
    assert not bool(persisted["execution_allowed"])
    assert readback["cash_return"] == pytest.approx(injected["cash_return"])
    assert readback["cash_source_id"] == injected["source_id"]
    assert readback["cash_source_terms"] == injected["source_terms"]
    assert readback["cash_knowledge_cutoff"] == injected["knowledge_cutoff"]
    assert readback["execution_allowed"] is False

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
    available = (pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=1)).isoformat()

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
            available_at=available,
            ingested_at=available,
            source_id="official-local-public-file",
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
    assert available_score.cash_curve_id == "eur-official-local-spot"
    assert available_score.cash_decision_time == adjusted_endpoint_available_at(end)
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
