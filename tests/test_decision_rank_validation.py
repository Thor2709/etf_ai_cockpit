from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json

import pandas as pd

from etf_cockpit.analysis.decision.rank_validation import (
    RankReplayReport,
    RankValidationReport,
    evaluate_rank_validation,
    load_rank_validation_policy,
    promotion_decision,
    rank_validation_metrics,
    replay_rank_panel,
    route_consumer_rank,
    select_challenger,
)
import etf_cockpit.application.ui_facade as ui_facade
from etf_cockpit.application.ui_facade import (
    load_opportunity_assessment,
    load_score_metric_history_projection,
    route_decision_rank_rows,
)
from etf_cockpit.portfolio.costs import COST_MODEL_ID


def _policy():
    return replace(
        load_rank_validation_policy(),
        holding_period_sessions=2,
        minimum_universe_support=2,
        top_n=1,
        bottom_n=1,
        minimum_decision_dates=2,
        subperiod_count=2,
        minimum_stable_subperiods=2,
        minimum_group_support=1,
    )


def _pit_inputs(policy=None):
    cutoff = datetime(2024, 1, 1, 23, 59, 59, tzinfo=timezone.utc)
    decision_time = cutoff.isoformat().replace("+00:00", "Z")
    decision_day = cutoff.date()
    prior = cutoff - timedelta(days=1)
    evidence_rows = []
    membership_rows = []
    price_rows = []
    cost_rows = []
    for instrument, quality, value, momentum, v3 in (
        ("DELISTED", 0.5, 0.4, 0.3, 0.2),
        ("SURVIVOR", 0.2, 0.6, 0.7, 0.4),
    ):
        membership_rows.append(
            {
                "instrument_id": instrument,
                "valid_from": date(2023, 1, 1),
                "valid_to": None,
                "known_at": prior,
                "snapshot_date": decision_day,
                "snapshot_complete": True,
            }
        )
        evidence_rows.append(
            {
                "instrument_id": instrument,
                "effective_at": prior,
                "known_at": prior,
                "quality_score": quality,
                "value_score": value,
                "momentum_score": momentum,
                "v3_score": v3,
                "sector": "technology",
                "size_bucket": "large",
                "size_value": 1_000_000.0,
            }
        )
        cost_rows.append(
            {
                "instrument_id": instrument,
                "known_at": prior,
                "round_trip_cost_bps": 10.0,
                "cost_model_id": COST_MODEL_ID,
            }
        )
        price_rows.append(
            {
                "instrument_id": instrument,
                "date": decision_day,
                "known_at": cutoff - timedelta(seconds=30),
                "adjusted_close": 100.0,
                "delisted": False,
            }
        )
    evidence_rows.append(
        {
            "instrument_id": "DELISTED",
            "effective_at": cutoff + timedelta(days=1),
            "known_at": cutoff + timedelta(days=1),
            "quality_score": 100.0,
            "value_score": 100.0,
            "momentum_score": 100.0,
            "v3_score": 100.0,
            "sector": "technology",
            "size_bucket": "large",
        }
    )
    membership_rows.append(
        {
            "instrument_id": "ADDED_LATER",
            "valid_from": date(2024, 1, 2),
            "valid_to": None,
            "known_at": cutoff + timedelta(days=1),
            "snapshot_date": date(2024, 1, 2),
            "snapshot_complete": True,
        }
    )
    price_rows.extend(
        [
            {
                "instrument_id": "DELISTED",
                "date": date(2024, 1, 2),
                "known_at": datetime(2024, 1, 2, 23, 59, tzinfo=timezone.utc),
                "adjusted_close": 40.0,
                "delisted": True,
            },
            {
                "instrument_id": "SURVIVOR",
                "date": date(2024, 1, 2),
                "known_at": datetime(2024, 1, 2, 23, 59, tzinfo=timezone.utc),
                "adjusted_close": 101.0,
                "delisted": False,
            },
            {
                "instrument_id": "SURVIVOR",
                "date": date(2024, 1, 3),
                "known_at": datetime(2024, 1, 3, 23, 59, tzinfo=timezone.utc),
                "adjusted_close": 102.0,
                "delisted": False,
            },
        ]
    )
    return {
        "evidence": pd.DataFrame(evidence_rows),
        "memberships": pd.DataFrame(membership_rows),
        "prices": pd.DataFrame(price_rows),
        "costs": pd.DataFrame(cost_rows),
        "benchmark_returns": pd.DataFrame(
            [{"decision_date": decision_day.isoformat(), "net_return": 0.001}]
        ),
        "cash_returns": pd.DataFrame(
            [{"decision_date": decision_day.isoformat(), "net_return": 0.0001}]
        ),
        "decision_times": [decision_time],
        "policy": policy or _policy(),
    }


def _replay(inputs):
    return replay_rank_panel(
        inputs["evidence"],
        inputs["memberships"],
        inputs["prices"],
        inputs["costs"],
        inputs["benchmark_returns"],
        inputs["cash_returns"],
        inputs["decision_times"],
        policy=inputs["policy"],
    )


def _promotion_record():
    return {
        "schema_version": 1,
        "record_id": "rankpromo_test",
        "validation_id": "rankval_test",
        "selected_rank": "balanced_challenger",
        "status": "promoted",
        "reason": "synthetic promotion fixture",
        "rationale": "synthetic validation record for consumer routing",
        "pit_availability": {"complete": True, "coverage_fraction": 1.0},
        "incremental_ic": 0.02,
        "rank_authority": True,
        "execution_allowed": False,
    }


def test_pit_replay_excludes_post_decision_data_and_keeps_delisted_members() -> None:
    inputs = _pit_inputs()
    replay = _replay(inputs)

    assert replay.status == "complete"
    assert set(replay.rows["instrument_id"]) == {"DELISTED", "SURVIVOR"}
    delisted = replay.rows.loc[
        replay.rows["ranker"].eq("QV") & replay.rows["instrument_id"].eq("DELISTED")
    ].iloc[0]
    assert delisted["score"] == 0.45
    assert delisted["forward_status"] == "available_delisted_terminal_price"
    assert delisted["net_return"] == -0.601
    assert "ADDED_LATER" not in set(replay.rows["instrument_id"])

    inputs["memberships"].loc[:, "snapshot_complete"] = False
    incomplete = _replay(inputs)
    assert incomplete.status == "insufficient_evidence"
    assert incomplete.rows.empty
    assert "dated_membership_snapshot_missing_or_incomplete" in str(
        incomplete.pit_availability["reasons"]
    )


def test_conflicting_latest_rank_evidence_is_insufficient_in_any_input_order() -> None:
    inputs = _pit_inputs()
    duplicate = inputs["evidence"].iloc[[0]].copy()
    duplicate.loc[:, "v3_score"] = 0.99
    evidence = pd.concat([inputs["evidence"], duplicate], ignore_index=True)

    for ordered in (evidence, evidence.iloc[::-1].reset_index(drop=True)):
        replay = _replay(inputs | {"evidence": ordered})
        assert replay.status == "insufficient_evidence"
        assert replay.insufficient_decision_times
        assert "ambiguous_latest_rows" in str(replay.pit_availability["reasons"])


def test_total_loss_delisting_is_minus_one_net_of_costs() -> None:
    for use_explicit_return in (True, False):
        inputs = _pit_inputs()
        terminal = inputs["prices"]["instrument_id"].eq("DELISTED") & inputs["prices"]["date"].eq(
            date(2024, 1, 2)
        )
        if use_explicit_return:
            inputs["prices"].loc[terminal, "adjusted_close"] = float("nan")
            inputs["prices"].loc[terminal, "delisting_return"] = -1.0
        else:
            inputs["prices"].loc[terminal, "adjusted_close"] = 0.0

        replay = _replay(inputs)
        total_loss = replay.rows.loc[
            replay.rows["ranker"].eq("QV") & replay.rows["instrument_id"].eq("DELISTED")
        ].iloc[0]
        assert total_loss["forward_status"].startswith("available_delisted") or (
            total_loss["forward_status"] == "available_delisting_return"
        )
        assert total_loss["gross_return"] == -1.0
        assert total_loss["net_return"] == -1.0


def test_rank_ic_and_top_minus_bottom_spread_use_net_forward_returns() -> None:
    rows = []
    for day_number in range(4):
        decision_time = datetime(2024, 1, day_number + 1, tzinfo=timezone.utc).isoformat()
        for instrument_number in range(20):
            score = float(instrument_number)
            rows.append(
                {
                    "decision_time": decision_time,
                    "instrument_id": f"ETF_{instrument_number:02d}",
                    "ranker": "balanced_challenger",
                    "score": score,
                    "net_return": score * (0.001 + day_number / 10_000.0),
                    "benchmark_net_return": 0.004,
                    "cash_net_return": 0.0001,
                    "sector": f"sector_{instrument_number % 4}",
                    "size_bucket": f"size_{instrument_number % 4}",
                }
            )

    metrics = rank_validation_metrics(
        pd.DataFrame(rows), "balanced_challenger", policy=_policy()
    )
    assert metrics["rank_ic_mean"] == 1.0
    assert metrics["top_minus_bottom_mean"] > 0.0
    assert metrics["top_minus_bottom_t"] is not None
    assert metrics["decile_monotonicity_fraction"] == 1.0
    assert metrics["quintile_monotonicity_fraction"] == 1.0
    assert metrics["sector_neutral"]["status"] == "available"
    assert metrics["size_neutral"]["status"] == "available"


def test_sector_and_size_neutral_spreads_match_group_weights() -> None:
    rows = []
    for instrument, score, sector, size_bucket, net_return in (
        ("A1", 30.0, "A", "A", 0.10),
        ("A2", 15.0, "A", "A", 0.10),
        ("A3", 15.0, "A", "A", 0.10),
        ("B1", 25.0, "B", "B", -0.10),
        ("B2", 25.0, "B", "B", -0.10),
        ("B3", 10.0, "B", "B", -0.10),
    ):
        rows.append(
            {
                "decision_time": "2024-01-01T23:59:59Z",
                "instrument_id": instrument,
                "ranker": "balanced_challenger",
                "score": score,
                "net_return": net_return,
                "benchmark_net_return": 0.0,
                "cash_net_return": 0.0,
                "sector": sector,
                "size_bucket": size_bucket,
            }
        )

    metrics = rank_validation_metrics(pd.DataFrame(rows), "balanced_challenger", policy=_policy())

    assert abs(metrics["sector_neutral"]["top_minus_bottom_mean"]) < 1e-12
    assert abs(metrics["size_neutral"]["top_minus_bottom_mean"]) < 1e-12


def test_promotion_rejects_challenger_below_t_haircut() -> None:
    dates = [f"2024-01-{day:02d}T23:59:59Z" for day in range(1, 7)]

    def metrics(mean, ic_t, spread_t):
        return {
            "status": "available",
            "net_return_mean": mean,
            "rank_ic_mean": 0.1,
            "rank_ic_t": ic_t,
            "top_minus_bottom_t": spread_t,
            "per_decision": [
                {
                    "decision_time": item,
                    "top_net_return": mean,
                    "top_minus_bottom": 0.01,
                }
                for item in dates
            ],
        }

    report = RankValidationReport(
        validation_id="rankval_t_haircut",
        status="available",
        development={
            "QV": metrics(0.01, 4.0, 4.0),
            "QVM": metrics(0.015, 4.0, 4.0),
            "balanced_challenger": metrics(0.02, 4.0, 4.0),
        },
        holdout={
            "QV": metrics(0.02, 2.0, 2.0),
            "QVM": metrics(0.025, 2.0, 2.0),
            "v3": metrics(0.01, 2.0, 2.0),
            "balanced_challenger": metrics(0.04, 2.99, 2.5),
        },
        holdout_decision_times=tuple(dates),
        walk_forward_splits=pd.DataFrame(),
        pit_availability={"complete": True, "coverage_fraction": 1.0},
        replay_config_hashes={"decision_cutover_v1": "frozen"},
    )

    record = promotion_decision(
        report,
        "balanced_challenger",
        rationale="holdout gate fixture",
        policy=_policy(),
    )
    assert record["selected_rank"] == "QV"
    assert record["status"] == "baseline_champion"
    assert "t haircut" in record["reason"]


def test_holdout_is_untouched_by_challenger_selection() -> None:
    development = {
        "QV": {"status": "available", "net_return_mean": 0.01},
        "QVM": {"status": "available", "net_return_mean": 0.015},
        "balanced_challenger": {"status": "available", "net_return_mean": 0.02},
    }
    holdout = {
        "QV": {"status": "available", "net_return_mean": 0.01},
        "QVM": {"status": "available", "net_return_mean": 0.015},
        "balanced_challenger": {"status": "available", "net_return_mean": -0.5},
        "other_challenger": {"status": "available", "net_return_mean": 100.0},
    }
    report = RankValidationReport(
        validation_id="rankval_holdout_isolation",
        status="available",
        development=development,
        holdout=holdout,
        holdout_decision_times=("2024-02-01T23:59:59Z",),
        walk_forward_splits=pd.DataFrame(),
        pit_availability={"complete": True, "coverage_fraction": 1.0},
        replay_config_hashes={},
    )
    before = json.dumps(report.holdout, sort_keys=True)

    selected = select_challenger(report)

    assert selected == "balanced_challenger"
    assert json.dumps(report.holdout, sort_keys=True) == before


def test_promotion_requires_the_development_selected_challenger() -> None:
    dates = [f"2024-02-{day:02d}T23:59:59Z" for day in range(1, 5)]

    def metrics(mean):
        return {
            "status": "available",
            "net_return_mean": mean,
            "rank_ic_mean": 0.2,
            "rank_ic_t": 10.0,
            "top_minus_bottom_t": 10.0,
            "per_decision": [
                {"decision_time": item, "top_net_return": mean, "top_minus_bottom": 0.1}
                for item in dates
            ],
        }

    report = RankValidationReport(
        validation_id="rankval_development_selection_gate",
        status="available",
        development={
            "QV": metrics(0.01),
            "QVM": metrics(0.02),
            "balanced_challenger": metrics(0.03),
            "other_challenger": metrics(0.015),
        },
        holdout={
            "QV": metrics(0.01),
            "QVM": metrics(0.02),
            "v3": metrics(0.005),
            "other_challenger": metrics(0.2),
        },
        holdout_decision_times=tuple(dates),
        walk_forward_splits=pd.DataFrame(),
        pit_availability={"complete": True, "coverage_fraction": 1.0},
        replay_config_hashes={},
    )

    record = promotion_decision(
        report,
        "other_challenger",
        rationale="holdout metrics must not bypass development selection",
        policy=_policy(),
    )

    assert select_challenger(report) == "balanced_challenger"
    assert record["selected_rank"] != "other_challenger"
    assert record["status"] != "promoted"
    assert "development-only" in record["reason"]


def test_development_excludes_overlapping_outcomes_and_rejects_nonterminal_holdout() -> None:
    dates = [date(2024, 1, day) for day in range(1, 11)]
    rankers = ("QV", "QVM", "v3", "balanced_challenger")
    scores = (30.0, 15.0, 15.0, 25.0, 25.0, 10.0)
    rows = []
    for day in dates:
        decision_time = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)
        for ranker in rankers:
            for index, score in enumerate(scores):
                sector = "A" if index < 3 else "B"
                rows.append(
                    {
                        "decision_time": decision_time.isoformat().replace("+00:00", "Z"),
                        "decision_date": day.isoformat(),
                        "instrument_id": f"{sector}{index % 3}",
                        "ranker": ranker,
                        "score": score,
                        "net_return": 0.1 if sector == "A" else -0.1,
                        "benchmark_net_return": 0.001,
                        "cash_net_return": 0.0001,
                        "sector": sector,
                        "size_bucket": sector,
                        "forward_window_end": (
                            date(2024, 1, 10).isoformat()
                            if day == date(2024, 1, 9)
                            else (day + timedelta(days=1)).isoformat()
                        ),
                    }
                )
    replay = RankReplayReport(
        rows=pd.DataFrame(rows),
        status="complete",
        insufficient_decision_times=(),
        config_hashes={},
        config_versions={},
        pit_availability={"complete": True, "coverage_fraction": 1.0},
    )

    report = evaluate_rank_validation(
        replay,
        holdout_decision_times=["2024-01-10T23:59:59Z"],
        policy=_policy(),
    )
    development_times = {
        item["decision_time"] for item in report.development["balanced_challenger"]["per_decision"]
    }
    assert "2024-01-09T23:59:59Z" not in development_times
    assert "2024-01-08T23:59:59Z" in development_times

    nonterminal = evaluate_rank_validation(
        replay,
        holdout_decision_times=["2024-01-08T23:59:59Z"],
        policy=_policy(),
    )
    assert nonterminal.status == "insufficient_evidence"
    assert "terminal" in nonterminal.reason


def test_cutover_routes_facade_consumers_and_preserves_v3_replay(tmp_path, monkeypatch) -> None:
    promotion = _promotion_record()
    scores = {"balanced_challenger": 0.9, "v3": 0.3}
    screen = route_decision_rank_rows(
        pd.DataFrame(
            [
                {
                    "instrument_id": "ACME",
                    "score": 0.3,
                    "rank_score__balanced_challenger": 0.9,
                    "rank_score__v3": 0.3,
                }
            ]
        ),
        "screener",
        promotion_record=promotion,
        cutover_enabled=True,
    )
    assert screen.iloc[0]["score"] == 0.9
    assert screen.iloc[0]["v3_replay_score"] == 0.3

    history_columns = (
        "run_id", "instrument_id", "component_group", "component_name", "source_id",
        "raw_metric_value", "normalised_score_10", "score_available", "na_reason",
        "source_dataset", "as_of_date", "freshness_status", "authority_label",
        "formula_version", "formula_checksum", "source_vintage_hash", "execution_allowed",
    )
    history = pd.DataFrame(
        [{column: "evidence" for column in history_columns}]
    )
    history["instrument_id"] = "ACME"
    history["raw_metric_value"] = 1.0
    history["normalised_score_10"] = 8.0
    monkeypatch.setattr(ui_facade, "LOG_DIR", tmp_path)
    missing_rank_evidence = load_score_metric_history_projection(
        "ACME",
        frame=history,
        promotion_record=promotion,
        cutover_enabled=True,
    )
    assert missing_rank_evidence["status"] == "unavailable"
    assert missing_rank_evidence["reason_code"] == "rank_evidence_unavailable"
    assert missing_rank_evidence["rank_evidence_reason"] == "opportunity_result_unavailable"
    projection = load_score_metric_history_projection(
        "ACME",
        frame=history,
        rank_scores=scores,
        promotion_record=promotion,
        cutover_enabled=True,
    )
    assert projection["active_ranker"] == "balanced_challenger"
    assert projection["active_rank_score"] == 0.9
    assert projection["v3_replay_score"] == 0.3

    artifact = {
        "schema_version": 1,
        "artifact_version": "decision-opportunity-shadow-v1",
        "run_id": "run-test",
        "decision_time": "2024-01-01T23:59:59Z",
        "config_hashes": {"decision_domains_v1": "frozen"},
        "execution_allowed": False,
        "results": [
            {
                "instrument": "ACME",
                "execution_allowed": False,
                "benchmark_rankers": [
                    {"ranker": "balanced_challenger", "score": 0.9},
                    {"ranker": "v3", "score": 0.3},
                ],
            }
        ],
    }
    (tmp_path / "decision_opportunity_run-test.json").write_text(
        json.dumps(artifact), encoding="utf-8"
    )
    detail = load_opportunity_assessment(
        "ACME",
        artifact_directory=tmp_path,
        promotion_record=promotion,
        cutover_enabled=True,
    )
    assert detail["active_ranker"] == "balanced_challenger"
    assert detail["active_rank_score"] == 0.9
    assert detail["v3_replay_score"] == 0.3
    stored_projection = load_score_metric_history_projection(
        "ACME",
        frame=history,
        promotion_record=promotion,
        cutover_enabled=True,
    )
    assert stored_projection["active_ranker"] == "balanced_challenger"
    assert stored_projection["active_rank_score"] == 0.9

    inputs = _pit_inputs()
    first = _replay(inputs)
    second = _replay(inputs)
    first_v3 = first.rows.loc[first.rows["ranker"].eq("v3"), "score"].tolist()
    second_v3 = second.rows.loc[second.rows["ranker"].eq("v3"), "score"].tolist()
    assert first_v3 == [0.2, 0.4]
    assert second_v3 == [0.2, 0.4]
    for consumer in ("screener", "score_history", "instrument_detail"):
        route = route_consumer_rank(
            consumer,
            scores,
            promotion_record=promotion,
            cutover_enabled=True,
        )
        assert route["ranker"] == "balanced_challenger"
        assert route["v3_replay_score"] == 0.3


def test_default_off_keeps_all_consumers_on_v3() -> None:
    promotion = _promotion_record()
    for consumer in ("screener", "score_history", "instrument_detail"):
        route = route_consumer_rank(
            consumer,
            {"balanced_challenger": 0.9, "v3": 0.3},
            promotion_record=promotion,
        )
        assert route["ranker"] == "v3"
        assert route["rank_score"] == 0.3
        assert route["cutover_active"] is False

    fallback = dict(promotion)
    fallback.update(
        status="stay_on_v3",
        selected_rank="v3",
        rank_authority=False,
        reason="QV failed against v3 on holdout",
    )
    recorded = route_consumer_rank(
        "instrument_detail",
        {"v3": 0.3, "QV": 0.2},
        promotion_record=fallback,
        cutover_enabled=True,
    )
    assert recorded["ranker"] == "v3"
    assert "QV failed against v3" in recorded["reason"]
