from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.analysis.decision.rank_validation import (
    RankReplayReport,
    evaluate_rank_validation,
    load_rank_validation_policy,
    price_momentum_risk_evidence,
    rank_validation_metrics,
    research_policy,
    run_stored_rank_validation,
    select_challenger,
    window_decision_times,
)
from etf_cockpit.core.paths import CONFIG_DIR

_ROOT = Path(__file__).resolve().parents[1]
_COST_MODEL = "execution-cost-v1"


def _policy():
    return replace(
        load_rank_validation_policy(),
        holding_period_sessions=2,
        minimum_universe_support=5,
        top_n=3,
        bottom_n=3,
        minimum_decision_dates=2,
        subperiod_count=2,
        minimum_stable_subperiods=2,
        minimum_group_support=1,
    )


def _panel(rankers: dict[str, str], *, dates: int = 30, names: int = 30, holdout_shift: float = 0.0):
    """Rows per (date, ranker, instrument); 'planted' scores predict returns, 'random' do not."""

    rng = np.random.default_rng(811)
    rows = []
    start = date(2023, 1, 2)
    for index in range(dates):
        day = start + timedelta(days=7 * index)
        latent = rng.normal(size=names)
        noise = rng.normal(size=names)
        forward = 0.02 * latent + 0.02 * noise
        if holdout_shift and index >= dates - 8:
            forward = forward + holdout_shift
        for ranker, kind in rankers.items():
            score = latent + 0.3 * rng.normal(size=names) if kind == "planted" else rng.normal(size=names)
            for item in range(names):
                rows.append(
                    {
                        "decision_time": f"{day.isoformat()}T23:59:59Z",
                        "decision_date": day.isoformat(),
                        "instrument_id": f"I{item:02d}",
                        "ranker": ranker,
                        "score": float(score[item]),
                        "net_return": float(forward[item]),
                        "benchmark_net_return": 0.001,
                        "cash_net_return": 0.0005,
                        "forward_window_end": (day + timedelta(days=2)).isoformat(),
                    }
                )
    return pd.DataFrame(rows)


def _replay(rows: pd.DataFrame) -> RankReplayReport:
    return RankReplayReport(
        rows, "complete", (), {}, {},
        {"complete": True, "covered_decisions": 30, "requested_decisions": 30, "coverage_fraction": 1.0, "reasons": {}},
    )


def test_planted_score_has_positive_rank_ic_and_random_score_near_zero():
    rows = _panel({"planted": "planted", "random": "random"})
    planted = rank_validation_metrics(rows, "planted", policy=_policy())
    noise = rank_validation_metrics(rows, "random", policy=_policy())
    assert planted["rank_ic_mean"] > 0.3 and planted["rank_ic_t"] > 3.0
    assert planted["top_minus_bottom_mean"] > 0
    assert abs(noise["rank_ic_mean"]) < 0.1
    assert abs(noise["rank_ic_t"]) < 3.0


def test_holdout_rows_never_enter_development_or_selection():
    rankers = {"QV": "random", "QVM": "random", "v3": "random", "balanced_challenger": "planted"}
    holdout = tuple(sorted(_panel(rankers)["decision_time"].unique())[-8:])
    plain = evaluate_rank_validation(_replay(_panel(rankers)), holdout_decision_times=holdout, policy=_policy())
    shifted = evaluate_rank_validation(
        _replay(_panel(rankers, holdout_shift=0.5)), holdout_decision_times=holdout, policy=_policy()
    )
    assert plain.development and plain.holdout
    assert json.dumps(plain.development, sort_keys=True, default=str) == json.dumps(
        shifted.development, sort_keys=True, default=str
    )
    assert select_challenger(plain) == select_challenger(shifted)
    assert plain.holdout["QV"]["top_net_return_mean"] != shifted.holdout["QV"]["top_net_return_mean"]


def _price_table(sessions: int, names: int = 25, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = [item.date() for item in pd.bdate_range("2023-01-02", periods=sessions)]
    rows = []
    for item in range(names):
        level = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, size=sessions)))
        rows.extend(
            {"instrument_id": f"I{item:02d}", "date": day, "adjusted_close": float(price)}
            for day, price in zip(days, level)
        )
    return pd.DataFrame(rows)


def test_insufficient_history_is_reported_not_filled():
    prices = _price_table(100)
    times, excluded = window_decision_times(prices, 5, step_sessions=21, holding_period_sessions=21)
    assert excluded and set(excluded.values()) <= {
        "insufficient_price_history_for_indicator_lookback",
        "forward_window_not_matured",
    }
    assert not times
    cutoff = f"{prices['date'].max().isoformat()}T23:59:59Z"
    evidence, skipped = price_momentum_risk_evidence(prices, [cutoff])
    assert evidence.empty and set(skipped[cutoff].values()) == {"insufficient_price_history"}
    policy = research_policy(load_rank_validation_policy(), fundamentals=False)
    replay, validation = run_stored_rank_validation(
        evidence, pd.DataFrame(), prices, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), [cutoff], policy=policy
    )
    assert replay.status == "insufficient_evidence" and not replay.pit_availability["complete"]
    assert validation.status == "insufficient_evidence" and not validation.holdout


def _digest(paths: list[Path]) -> dict[str, str]:
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_runner_leaves_settings_and_champion_files_unchanged(tmp_path):
    spec = importlib.util.spec_from_file_location("run_rank_validation", _ROOT / "scripts" / "run_rank_validation.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    prices = _price_table(420)
    prices_path = tmp_path / "prices.parquet"
    prices.to_parquet(prices_path)
    policy = load_rank_validation_policy()
    times, _ = window_decision_times(
        prices, 1, step_sessions=policy.holding_period_sessions,
        holding_period_sessions=policy.holding_period_sessions,
    )
    assert len(times) >= 4
    members = [
        {
            "instrument_id": instrument, "valid_from": "2020-01-01", "valid_to": None,
            "known_at": "2023-01-01T00:00:00Z", "snapshot_date": stamp[:10], "snapshot_complete": True,
        }
        for stamp in times
        for instrument in sorted(prices["instrument_id"].unique())
    ]
    pd.DataFrame(members).to_csv(tmp_path / "membership.csv", index=False)
    pd.DataFrame(
        [
            {"instrument_id": instrument, "known_at": "2023-01-01T00:00:00Z",
             "round_trip_cost_bps": 10.0, "cost_model_id": _COST_MODEL}
            for instrument in sorted(prices["instrument_id"].unique())
        ]
    ).to_csv(tmp_path / "costs.csv", index=False)
    pd.DataFrame([{"decision_date": stamp[:10], "net_return": 0.001} for stamp in times]).to_csv(
        tmp_path / "cash.csv", index=False
    )
    champion = tmp_path / "champion.json"
    champion.write_text('{"selected_rank": "v3"}', encoding="utf-8")
    watched = sorted(CONFIG_DIR.glob("decision_*.yaml")) + [champion]
    before = _digest(watched)

    out = tmp_path / "report.json"
    code = runner.main(
        [
            "--root", str(tmp_path), "--years", "1", "--prices", str(prices_path),
            "--membership", str(tmp_path / "membership.csv"), "--costs", str(tmp_path / "costs.csv"),
            "--cash", str(tmp_path / "cash.csv"), "--benchmark-id", "I00", "--out", str(out),
        ]
    )

    assert code == 0 and _digest(watched) == before
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["rank_authority"] is False and report["promotion_applied"] is False
    section = report["windows"][0]["sections"]
    assert section["price_factors"]["status"] == "insufficient_evidence"
    assert section["fundamental_factors"]["status"] == "unavailable"
    assert section["price_factors"]["holdout"]["momentum"]["status"] in {"available", "insufficient_evidence"}
    assert runner.main(["--years", "1", "--out", str(CONFIG_DIR / "report.json")]) == 2
