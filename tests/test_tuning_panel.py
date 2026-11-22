from __future__ import annotations

from datetime import date, timedelta
import importlib.util
import json
import math
from pathlib import Path
import time

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.validation.tuning_panel import PanelRankIc, load_tuning_panel

COMPONENTS = ("liquidity_cost", "momentum", "risk", "trend")
WEIGHTS = {"momentum": 0.165, "trend": 0.135, "risk": 0.4083, "liquidity_cost": 0.2917}


def _long_rows(sessions: int, instruments: int, seed: int = 1):
    rng = np.random.default_rng(seed)
    start = date(2020, 1, 1)
    days = [start + timedelta(days=position) for position in range(sessions)]
    names = [f"I{position:04d}" for position in range(instruments)]
    comp, out, daily = [], [], []
    quality = rng.normal(0.0, 1.0, instruments)
    for day in days:
        for position, name in enumerate(names):
            if rng.random() < 0.03:
                continue  # no row at all: stays NaN, gate False
            for key in COMPONENTS:
                if rng.random() < 0.05:
                    continue
                comp.append({"decision_session": day, "instrument_id": name, "component_key": key,
                             "raw_score": float(rng.normal(quality[position] * 0.3, 0.8)), "eligible": rng.random() > 0.05})
            out.append({"decision_session": day, "instrument_id": name, "gate": rng.random() > 0.05,
                        "net_forward_return": float(rng.normal(0.01 * quality[position], 0.05)) if rng.random() > 0.03 else math.nan,
                        "benchmark_net_return": 0.004, "adv": float(rng.lognormal(12, 1))})
            daily.append({"date": day, "instrument_id": name, "daily_return": float(rng.normal(0, 0.01))})
    return pd.DataFrame(comp), pd.DataFrame(out), pd.DataFrame(daily)


def _oracle_session_ic(comp, out, day, weights):
    """Per-session pandas rule: combine_component_scores' weighting, then Series.corr(method='spearman')."""
    scores = {}
    for name, rows in comp.loc[comp["decision_session"].eq(day)].groupby("instrument_id"):
        used = rows.loc[rows["eligible"] & rows["component_key"].map(lambda key: weights.get(key, 0.0) > 0)]
        total = sum(weights[key] for key in used["component_key"])
        if total > 0:
            scores[name] = sum(max(-1.0, min(1.0, raw)) * weights[key] for raw, key in zip(used["raw_score"], used["component_key"])) / total
    rows = out.loc[out["decision_session"].eq(day) & out["gate"] & out["net_forward_return"].notna()]
    rows = rows.loc[rows["instrument_id"].isin(scores)]
    return pd.Series([scores[name] for name in rows["instrument_id"]]).corr(rows["net_forward_return"].reset_index(drop=True), method="spearman")


def test_panel_rank_ic_matches_the_per_session_pandas_rule() -> None:
    comp, out, daily = _long_rows(12, 40)
    panel = load_tuning_panel(comp, out, daily)
    objective = PanelRankIc(panel, WEIGHTS, "score.etf.headline")
    for trial in ({}, {"score.etf.headline.momentum": 0.0, "score.etf.headline.trend": 0.3}):
        weights = dict(WEIGHTS) | {key.rsplit(".", 1)[1]: value for key, value in trial.items()}
        got = objective.per_session(trial)
        expected = [_oracle_session_ic(comp, out, day, weights) for day in panel.sessions]
        assert np.allclose(got, expected, rtol=0, atol=1e-12, equal_nan=True)
        assert np.isfinite(got).all()
        assert objective(trial, [0, 3, 5], None) == pytest.approx(float(np.mean(got[[0, 3, 5]])), abs=1e-15)


def test_loader_keeps_missing_cells_as_nan_clamps_and_rejects_duplicates() -> None:
    comp, out, daily = _long_rows(4, 6)
    comp.loc[0, "raw_score"] = 7.5
    panel = load_tuning_panel(comp, out, daily)
    first = comp.iloc[0]
    s, i, k = (panel.sessions.index(first["decision_session"]), panel.instruments.index(first["instrument_id"]),
               panel.components.index(first["component_key"]))
    assert panel.raw[s, i, k] == 1.0
    assert panel.raw.shape == (4, 6, 4) and panel.ret.shape == (4, 6) and panel.adv.shape == (4, 6)
    stored = set(zip(comp["decision_session"], comp["instrument_id"], comp["component_key"]))
    for (s, i, k), value in np.ndenumerate(panel.raw):
        assert np.isnan(value) == ((panel.sessions[s], panel.instruments[i], panel.components[k]) not in stored)
    assert np.isnan(panel.fwd[~panel.gate & np.isnan(panel.adv)]).all()  # a session/instrument without a row
    assert load_tuning_panel(comp, out, daily).checksum == panel.checksum
    changed = comp.copy(); changed.loc[1, "raw_score"] += 0.01
    assert load_tuning_panel(changed, out, daily).checksum != panel.checksum
    with pytest.raises(ValueError, match="duplicate"):
        load_tuning_panel(pd.concat([comp, comp.iloc[:1]]), out, daily)


def test_panel_trial_takes_at_most_0_8_seconds_on_a_small_panel() -> None:
    rng = np.random.default_rng(5)
    S, I = 120, 600
    days = [date(2020, 1, 1) + timedelta(days=position) for position in range(S)]
    key = pd.MultiIndex.from_product([days, [f"I{n:04d}" for n in range(I)]], names=["decision_session", "instrument_id"]).to_frame(index=False)
    comp = pd.concat([key.assign(component_key=name, raw_score=rng.normal(0, 0.8, len(key)), eligible=True) for name in COMPONENTS])
    out = key.assign(gate=True, net_forward_return=rng.normal(0, 0.05, len(key)), benchmark_net_return=0.004, adv=1e6)
    daily = key.rename(columns={"decision_session": "date"}).assign(daily_return=0.0)
    objective = PanelRankIc(load_tuning_panel(comp, out, daily), WEIGHTS, "score.etf.headline")
    started = time.perf_counter()
    for trial in range(5):
        objective({"score.etf.headline.momentum": 0.1 + 0.01 * trial}, range(S), None)
    assert (time.perf_counter() - started) / 5 <= 0.8


def test_walk_forward_cli_tunes_on_a_panel_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    comp, out, daily = _long_rows(460, 12, seed=3)
    panel_dir = tmp_path / "panel"
    panel_dir.mkdir()
    for name, frame in (("components", comp), ("outcomes", out), ("returns", daily)):
        frame.to_parquet(panel_dir / f"{name}.parquet", index=False)
    spec = importlib.util.spec_from_file_location("run_tuning_panel_cli", Path(__file__).resolve().parents[1] / "scripts" / "run_tuning.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    code = cli.main(["--mode", "walk-forward", "--panel", str(panel_dir), "--output-dir", str(tmp_path / "out")])
    printed = capsys.readouterr().out
    assert code == 0, printed
    proposal = json.loads((tmp_path / "out" / "tuning_proposal.json").read_text(encoding="utf-8"))
    assert proposal["decision"] in {"keep_current", "propose_change"}
    assert cli.main(["--mode", "walk-forward", "--output-dir", str(tmp_path / "out2")]) == 2
