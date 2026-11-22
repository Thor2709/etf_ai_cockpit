"""Dense component panel for tuning and its rank-IC objective.

The loader turns long rows into dense float64 arrays: missing data is NaN plus a mask, never zero.  Raw component
scores are clamped to [-1, 1] as ``combine_component_scores`` does.  The objective combines the eligible components
with the trial weights by the same rule (weights <= 0 drop out, the sum is divided by the eligible weight) and scores
each decision session by the Spearman rank IC of that score against the net forward return.  The forward ranks are
computed once and only recomputed for a session whose rankable rows change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import hashlib
import json

import numpy as np
import pandas as pd

OBJECTIVE_VERSION = "panel-rank-ic-v1"


@dataclass(frozen=True)
class TuningPanel:
    sessions: tuple[date, ...]  # S decision sessions
    days: tuple[date, ...]  # D return days
    instruments: tuple[str, ...]  # I
    components: tuple[str, ...]  # K
    raw: np.ndarray  # S x I x K clamped raw score (NaN: missing)
    eligible: np.ndarray  # S x I x K score-eligible component
    gate: np.ndarray  # S x I row may be ranked (research gates passed)
    fwd: np.ndarray  # S x I net forward return (NaN: missing)
    bench: np.ndarray  # S benchmark (VWCE) net forward return (NaN: missing)
    adv: np.ndarray  # S x I average daily traded value (NaN: missing)
    ret: np.ndarray  # D x I daily return (NaN: missing)
    checksum: str


def _require(frame: pd.DataFrame, name: str, columns: Sequence[str], keys: Sequence[str]) -> pd.DataFrame:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} rows lack columns {missing}")
    frame = frame.loc[:, list(columns)].copy()
    for key in keys:
        if key in {"decision_session", "date"}:
            frame[key] = pd.to_datetime(frame[key]).dt.date
        else:
            frame[key] = frame[key].astype(str)
    if frame[list(keys)].isna().any().any() or frame.duplicated(list(keys)).any():
        raise ValueError(f"{name} rows have missing or duplicate keys {list(keys)}")
    return frame


def load_tuning_panel(components: pd.DataFrame, outcomes: pd.DataFrame, returns: pd.DataFrame) -> TuningPanel:
    """Build the panel from long rows.

    ``components``: decision_session, instrument_id, component_key, raw_score, eligible.
    ``outcomes``: decision_session, instrument_id, gate, net_forward_return, benchmark_net_return, adv
    (one benchmark value per session).  ``returns``: date, instrument_id, daily_return.
    A cell without a row stays NaN (gate False); no value is filled.
    """
    comp = _require(components, "component", ("decision_session", "instrument_id", "component_key", "raw_score", "eligible"),
                    ("decision_session", "instrument_id", "component_key"))
    out = _require(outcomes, "outcome", ("decision_session", "instrument_id", "gate", "net_forward_return", "benchmark_net_return", "adv"),
                   ("decision_session", "instrument_id"))
    daily = _require(returns, "return", ("date", "instrument_id", "daily_return"), ("date", "instrument_id"))
    sessions = tuple(sorted(set(comp["decision_session"]) | set(out["decision_session"])))
    days = tuple(sorted(set(daily["date"])))
    instruments = tuple(sorted(set(comp["instrument_id"]) | set(out["instrument_id"]) | set(daily["instrument_id"])))
    keys = tuple(sorted(set(comp["component_key"])))
    s_of, d_of, i_of, k_of = (pd.Index(labels) for labels in (sessions, days, instruments, keys))
    S, D, I, K = len(sessions), len(days), len(instruments), len(keys)

    raw = np.full((S, I, K), np.nan)
    eligible = np.zeros((S, I, K), dtype=bool)
    at = (s_of.get_indexer(comp["decision_session"]), i_of.get_indexer(comp["instrument_id"]), k_of.get_indexer(comp["component_key"]))
    values = pd.to_numeric(comp["raw_score"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    raw[at] = np.clip(values, -1.0, 1.0)
    eligible[at] = comp["eligible"].astype(bool).to_numpy() & np.isfinite(values)

    gate = np.zeros((S, I), dtype=bool)
    fwd, adv = np.full((S, I), np.nan), np.full((S, I), np.nan)
    at2 = (s_of.get_indexer(out["decision_session"]), i_of.get_indexer(out["instrument_id"]))
    gate[at2] = out["gate"].astype(bool).to_numpy()
    fwd[at2] = pd.to_numeric(out["net_forward_return"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    adv[at2] = pd.to_numeric(out["adv"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    bench_rows = pd.to_numeric(out["benchmark_net_return"], errors="coerce").groupby(out["decision_session"]).agg(["min", "max"])
    if (bench_rows["min"] != bench_rows["max"]).any():
        raise ValueError("outcome rows disagree on a session's benchmark return")
    bench = bench_rows["min"].reindex(list(sessions)).to_numpy(dtype=float, na_value=np.nan)

    ret = np.full((D, I), np.nan)
    ret[d_of.get_indexer(daily["date"]), i_of.get_indexer(daily["instrument_id"])] = (
        pd.to_numeric(daily["daily_return"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    )
    digest = hashlib.sha256(json.dumps(
        [[item.isoformat() for item in sessions], [item.isoformat() for item in days], list(instruments), list(keys)]
    ).encode("utf-8"))
    for array in (raw, eligible, gate, fwd, bench, adv, ret):
        digest.update(np.ascontiguousarray(array).tobytes())
    return TuningPanel(sessions, days, instruments, keys, raw, eligible, gate, fwd, bench, adv, ret, digest.hexdigest())


def _ranks(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Average ranks per row over the masked cells (NaN elsewhere)."""
    return pd.DataFrame(np.where(mask, values, np.nan)).rank(axis=1, method="average").to_numpy()


def _row_pearson(left: np.ndarray, right: np.ndarray, mask: np.ndarray) -> np.ndarray:
    count = mask.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        centred = [np.where(mask, side - np.where(mask, side, 0.0).sum(axis=1, keepdims=True) / count[:, None], 0.0)
                   for side in (left, right)]
        scale = np.sqrt((centred[0] ** 2).sum(axis=1) * (centred[1] ** 2).sum(axis=1))
        result = (centred[0] * centred[1]).sum(axis=1) / scale
    result[(count < 2) | ~(scale > 0)] = np.nan
    return result


class PanelRankIc:
    """``TuningEvaluator`` on a panel: the mean session rank IC over the given session indices (higher is better).

    ``weights`` is the full current weight table of the panel's components; a parameter named
    ``f"{knob_prefix}.{component}"`` replaces that component's weight for a trial.
    """

    def __init__(self, panel: TuningPanel, weights: Mapping[str, float], knob_prefix: str) -> None:
        self.panel = panel
        self._base = np.array([float(weights.get(key, 0.0)) for key in panel.components])
        self._knobs = {f"{knob_prefix}.{key}": position for position, key in enumerate(panel.components)}
        self._valid = panel.gate & np.isfinite(panel.fwd) & panel.eligible.any(axis=2)
        self._fwd_ranks = _ranks(panel.fwd, self._valid)
        self.identity = f"{OBJECTIVE_VERSION}:{panel.checksum}:{knob_prefix}:" + hashlib.sha256(self._base.tobytes()).hexdigest()[:16]

    def per_session(self, parameters: Mapping[str, float]) -> np.ndarray:
        """Rank IC per decision session (NaN: fewer than two rankable rows or a constant side)."""
        weights = self._base.copy()
        for name, value in parameters.items():
            if name in self._knobs:
                weights[self._knobs[name]] = float(value)
        used = self.panel.eligible & (weights > 0)
        total = np.where(used, weights, 0.0).sum(axis=2)
        with np.errstate(invalid="ignore", divide="ignore"):
            score = np.where(used, self.panel.raw * weights, 0.0).sum(axis=2) / total
        valid = self._valid & (total > 0)
        fwd_ranks = self._fwd_ranks
        changed = (valid != self._valid).any(axis=1)
        if changed.any():
            fwd_ranks = fwd_ranks.copy()
            fwd_ranks[changed] = _ranks(self.panel.fwd[changed], valid[changed])
        return _row_pearson(_ranks(score, valid), fwd_ranks, valid)

    def __call__(self, parameters: Mapping[str, float], indices: Sequence[int], context: object) -> float:
        values = self.per_session(parameters)[np.asarray(list(indices), dtype=np.int64)]
        values = values[np.isfinite(values)]
        return float(values.mean()) if len(values) else float("nan")
