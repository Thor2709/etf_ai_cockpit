from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from etf_cockpit.analysis.fund_analysis import FundAnalysisError, load_fund_analysis_config
from etf_cockpit.analysis.fund_forecasts import (
    FundRecommendationProjection,
    FundReturnDistribution,
)
from etf_cockpit.analysis.fund_peers import build_fund_peer_cohort
from etf_cockpit.analysis.fund_screener import (
    FundScreenerInput,
    build_fund_screener,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.fund_identity import FundLifecycleEvent, FundLifecycleStatus
from test_fund_peer_cohorts import DECISION, EFFECTIVE, _fund


def test_share_classes_use_one_slot_and_the_earliest_inception_by_default() -> None:
    classes = tuple(
        _make_fund(
            f"FUND-{name}",
            f"CLASS-{name}",
            strategy_id="MANDATE-1",
            launch_date=launch,
            return_value=Decimal("0.10"),
        )
        for name, launch in (("LATE", "2021-01-01"), ("EARLY", "2019-01-01"), ("MIDDLE", "2020-01-01"))
    )
    comparison = tuple(
        _make_fund(f"PEER-{index}", f"PEER-CLASS-{index}", return_value=Decimal("0.02"))
        for index in range(4)
    )
    funds = _screen_inputs((*classes, *comparison))
    config = replace(load_fund_analysis_config().screener, top_n=20)

    snapshot = build_fund_screener(funds, decision_time=_decision(), config=config)
    mandate_rows = [row for row in snapshot.rows if row.economic_strategy_id == "MANDATE-1"]
    assert len(mandate_rows) == 1
    row = mandate_rows[0]
    assert row.representative_share_class_id == "CLASS-EARLY"
    assert row.share_class_ids == ("CLASS-EARLY", "CLASS-LATE", "CLASS-MIDDLE")
    assert {item.distribution.share_class_id for item in row.class_recommendations} == set(
        row.share_class_ids
    )
    for view in _mandate_views(snapshot, "MANDATE-1"):
        assert sum(entry.economic_strategy_id == "MANDATE-1" for entry in view.entries) == 1

    multiple = replace(config, allow_multiple_classes=True)
    multiple_snapshot = build_fund_screener(funds, decision_time=_decision(), config=multiple)
    for view in _mandate_views(multiple_snapshot, "MANDATE-1"):
        assert sum(entry.economic_strategy_id == "MANDATE-1" for entry in view.entries) == 3
        assert {entry.share_class_id for entry in view.entries if entry.economic_strategy_id == "MANDATE-1"} == set(
            row.share_class_ids
        )


def test_total_sector_country_and_intersection_views_have_deterministic_orders() -> None:
    specs = (
        ("FUND-A", "CLASS-A", "tech", "US", "0.20", "0.10", "0.18", "10"),
        ("FUND-B", "CLASS-B", "tech", "US", "0.15", "0.05", "0.12", "20"),
        ("FUND-C", "CLASS-C", "health", "DE", "0.05", "-0.05", "0.03", "40"),
        ("FUND-D", "CLASS-D", "health", "DE", "0.10", "0.00", "0.08", "30"),
        ("FUND-E", "CLASS-E", "tech", None, "0.25", "0.15", "0.22", "5"),
    )
    funds = tuple(
        _make_fund(
            fund_id,
            class_id,
            sector=sector,
            country=country,
            return_value=Decimal(total),
            q05=Decimal(q05),
            q50=Decimal(q50),
            total_fee_bps=Decimal(fee),
        )
        for fund_id, class_id, sector, country, total, q05, q50, fee in specs
    )
    inputs = _screen_inputs(funds)
    config = replace(load_fund_analysis_config().screener, top_n=10)
    snapshot = build_fund_screener(inputs, decision_time=_decision(), config=config)

    assert _strategy_order(snapshot, "total") == ["FUND-E", "FUND-A", "FUND-B", "FUND-D", "FUND-C"]
    assert _strategy_order(snapshot, "sector", "tech") == ["FUND-E", "FUND-A", "FUND-B"]
    assert _strategy_order(snapshot, "sector", "health") == ["FUND-D", "FUND-C"]
    assert _strategy_order(snapshot, "country", "US") == ["FUND-A", "FUND-B"]
    assert _strategy_order(snapshot, "country", "DE") == ["FUND-D", "FUND-C"]
    assert _strategy_order(snapshot, "country_sector", ("US", "tech")) == ["FUND-A", "FUND-B"]
    assert _strategy_order(snapshot, "country_sector", ("DE", "health")) == ["FUND-D", "FUND-C"]
    countryless = next(row for row in snapshot.rows if row.fund_id == "FUND-E")
    assert countryless.status == "ranked"
    assert "country_view_classification_missing" in countryless.reason_codes
    assert "FUND-E" not in _strategy_order(snapshot, "country", "US")


def test_blocked_and_unavailable_funds_are_excluded_and_research_only_is_a_later_tier() -> None:
    ordinary = tuple(
        _make_fund(f"FUND-{index}", f"CLASS-{index}", return_value=Decimal(index) / Decimal("100"))
        for index in range(5)
    )
    blocked = replace(
        _make_fund("FUND-BLOCKED", "CLASS-BLOCKED"),
        analysis_record=replace(
            _make_fund("FUND-BLOCKED", "CLASS-BLOCKED").analysis_record,
            status="blocked",
            blockers=("missing_fee",),
        ),
    )
    unavailable = _make_fund("FUND-UNAVAILABLE", "CLASS-UNAVAILABLE")
    inputs = list(_screen_inputs((*ordinary, blocked, unavailable)))
    inputs = [
        replace(
            item,
            distribution=_distribution(item.peer_fund, status="unavailable"),
            recommendation_projection=_projection(
                item.peer_fund.analysis_record,
                _distribution(item.peer_fund, status="unavailable"),
            ),
        )
        if item.peer_fund.analysis_record.fund_id == "FUND-UNAVAILABLE"
        else item
        for item in inputs
    ]
    research_fund = _make_fund(
        "FUND-RESEARCH",
        "CLASS-RESEARCH",
        return_value=Decimal("0.99"),
        q05=Decimal("0.50"),
        q50=Decimal("0.75"),
    )
    inputs.extend(_screen_inputs((research_fund,), peer_universe=(*ordinary, blocked, unavailable, research_fund)))
    research_input = inputs[-1]
    research_distribution = _distribution(research_fund, status="research_only")
    inputs[-1] = replace(
        research_input,
        distribution=research_distribution,
        recommendation_projection=_projection(research_fund.analysis_record, research_distribution),
    )
    snapshot = build_fund_screener(
        tuple(inputs),
        decision_time=_decision(),
        config=replace(load_fund_analysis_config().screener, top_n=10),
    )

    blocked_row = next(row for row in snapshot.rows if row.fund_id == "FUND-BLOCKED")
    unavailable_row = next(row for row in snapshot.rows if row.fund_id == "FUND-UNAVAILABLE")
    assert blocked_row.status == "excluded"
    assert "fund_analysis_blocked" in blocked_row.reason_codes
    assert unavailable_row.status == "excluded"
    assert "fund_distribution_unavailable" in unavailable_row.reason_codes
    assert _strategy_order(snapshot, "total")[0] != "FUND-RESEARCH"
    assert _view(snapshot, "total").entries[-1].economic_strategy_id == "FUND-RESEARCH"
    assert _view(snapshot, "total").entries[-1].tier == "research_only"
    funnel = {item.reason_code: item.count for item in snapshot.exclusion_funnel}
    assert funnel["fund_analysis_blocked"] == 1
    assert funnel["fund_distribution_unavailable"] == 1


def test_row_values_match_sealed_sources_and_snapshot_hash_is_stable_and_config_sensitive() -> None:
    funds = tuple(
        _make_fund(f"FUND-{index}", f"CLASS-{index}", return_value=Decimal(index) / Decimal("100"))
        for index in range(5)
    )
    inputs = _screen_inputs(funds)
    config = replace(load_fund_analysis_config().screener, top_n=10)
    snapshot = build_fund_screener(inputs, decision_time=_decision(), config=config)
    repeated = build_fund_screener(inputs, decision_time=_decision(), config=config)
    changed = build_fund_screener(
        inputs,
        decision_time=_decision(),
        config=replace(config, top_n=9),
    )
    source = inputs[0]
    row = next(row for row in snapshot.rows if row.record_id == source.peer_fund.analysis_record.record_id)

    assert row.return_decomposition is source.peer_fund.analysis_record.return_decomposition
    assert row.distribution is source.distribution
    assert row.total_fee_bps == source.peer_fund.analysis_record.total_fee_bps
    assert row.record_id == source.peer_fund.analysis_record.record_id
    assert snapshot.analysis_snapshot_id == repeated.analysis_snapshot_id
    assert snapshot.analysis_snapshot_id != changed.analysis_snapshot_id


def test_ties_bootstrap_missing_config_and_output_metric_boundaries(tmp_path) -> None:
    funds = tuple(
        _make_fund(f"FUND-{name}", f"CLASS-{name}", return_value=Decimal("0.05"))
        for name in ("C", "A", "B", "D", "E")
    )
    inputs = _screen_inputs(funds)
    config = replace(load_fund_analysis_config().screener, top_n=2, ranking_seed=91)
    snapshot = build_fund_screener(inputs, decision_time=_decision(), config=config)
    repeated = build_fund_screener(inputs, decision_time=_decision(), config=config)
    assert _strategy_order(snapshot, "total") == ["FUND-A", "FUND-B"]
    for row in snapshot.rows:
        assert row.rank_stability == next(
            other.rank_stability for other in repeated.rows if other.record_id == row.record_id
        )
        assert row.rank_stability_seed == 91
        assert row.rank_stability is not None
    assert snapshot.execution_allowed is False
    assert not any(
        metric_name in repr(snapshot)
        for metric_name in ("market_premium_discount", "exchange_spread", "intraday_liquidity")
    )

    source = Path("configs/fund_analysis_v1.yaml")
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    del payload["screener"]
    missing = tmp_path / "fund_analysis_missing_screener_test.yaml"
    missing.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(FundAnalysisError):
        load_fund_analysis_config(missing)


def _make_fund(
    fund_id: str,
    class_id: str,
    *,
    strategy_id: str | None = None,
    sector: str | None = "technology",
    country: str | None = "US",
    return_value: Decimal = Decimal("0.05"),
    q05: Decimal | None = Decimal("0.00"),
    q50: Decimal | None = Decimal("0.04"),
    total_fee_bps: Decimal = Decimal("30"),
    launch_date: str = "2018-01-01",
) -> object:
    fund = _fund(
        fund_id,
        class_id,
        sub_fund_id=strategy_id,
        return_value=return_value,
    )
    record = replace(fund.analysis_record, total_fee_bps=total_fee_bps)
    context = fund.context
    confidence = dict(context.field_confidence)
    alternatives = dict(context.alternatives)
    for field_name, value in (("sector", sector), ("legal_domicile", country)):
        if value is not None:
            confidence[field_name] = 0.99
        alternatives[field_name] = ()
    context = replace(
        context,
        sector=sector,
        legal_domicile=country,
        field_confidence=confidence,
        alternatives=alternatives,
    )
    launch = FundLifecycleEvent(
        fund_id=fund_id,
        event_id=f"launch:{class_id}",
        status=FundLifecycleStatus.LAUNCHED,
        effective_at=f"{launch_date}T00:00:00Z",
        available_at=DECISION,
        source="fixture",
        source_id=f"launch:{class_id}",
        authority=SourceAuthority.OFFICIAL,
    )
    return replace(fund, analysis_record=record, context=context, lifecycle_events=(launch,))


def _screen_inputs(funds, *, peer_universe=None) -> tuple[FundScreenerInput, ...]:
    universe = tuple(peer_universe or funds)
    config = load_fund_analysis_config()
    result = []
    for fund in funds:
        peers = tuple(
            peer
            for peer in universe
            if peer.context.instrument_id != fund.context.instrument_id
        )
        cohort = build_fund_peer_cohort(
            fund,
            peers,
            effective_at=EFFECTIVE,
            decision_time=DECISION,
            config=config,
        )
        distribution = _distribution(fund)
        result.append(
            FundScreenerInput(
                peer_fund=fund,
                distribution=distribution,
                recommendation_projection=_projection(fund.analysis_record, distribution),
                peer_cohort=cohort,
            )
        )
    return tuple(result)


def _distribution(fund, *, status: str = "calibrated") -> FundReturnDistribution:
    record = fund.analysis_record
    total = record.return_decomposition.total_return or Decimal("0")
    q05 = total - Decimal("0.10") if status != "unavailable" else None
    q50 = total - Decimal("0.02") if status != "unavailable" else None
    return FundReturnDistribution(
        fund_id=record.fund_id,
        share_class_id=record.share_class_id,
        economic_strategy_id=fund.share_class.sub_fund_id or record.fund_id,
        decision_time=record.decision_time,
        horizon=record.return_decomposition.requested_horizon,
        horizon_days=365,
        selected_currency=record.return_decomposition.selected_currency,
        status=status,
        q05=q05,
        q50=q50,
        q95=total + Decimal("0.02") if status != "unavailable" else None,
        loss_probability=Decimal("0.25") if status == "calibrated" else None,
        beat_benchmark_probability=Decimal("0.60") if status == "calibrated" else None,
        sample_count=30 if status != "unavailable" else 0,
        calibration_cohort_key="fund:test" if status == "calibrated" else None,
        calibration_fallback_path=(),
        calibration_id="calibration:test" if status == "calibrated" else None,
        reason_codes=("fund_return_calibration_unavailable",) if status == "research_only" else (),
        evidence_references=(),
    )


def _projection(record, distribution) -> FundRecommendationProjection:
    return FundRecommendationProjection(
        analysis_id=record.record_id,
        distribution=distribution,
        profile_results=(),
        blockers=(),
        projection_id=f"projection:{record.record_id}",
    )


def _decision() -> datetime:
    return datetime.fromisoformat(DECISION.replace("Z", "+00:00")).astimezone(timezone.utc)


def _view(snapshot, dimension: str, bucket=None):
    return next(view for view in snapshot.views if view.dimension == dimension and view.bucket == bucket)


def _strategy_order(snapshot, dimension: str, bucket=None) -> list[str]:
    return [entry.economic_strategy_id for entry in _view(snapshot, dimension, bucket).entries]


def _mandate_views(snapshot, strategy_id: str):
    return tuple(
        view
        for view in snapshot.views
        if any(entry.economic_strategy_id == strategy_id for entry in view.entries)
    )
