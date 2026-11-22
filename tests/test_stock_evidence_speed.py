"""Stock evidence speed: the faster forms give the old output (bootstrap stream, peer index, known rows) and the
point-in-time periods are built once per stored file state."""

from __future__ import annotations

import os
import random
import zlib
from datetime import datetime, timedelta, timezone

import pandas as pd

from etf_cockpit.analysis import peer_cohorts as pc
from etf_cockpit.analysis import stock_universe as su
from etf_cockpit.analysis.stock_peers import PeerIndex, PeerProfile, auto_peers, cohort_members
from etf_cockpit.data import stock_fundamentals as store

UTC = timezone.utc
CONFIG = store.load_stock_config()


def _python_bootstrap(values, weights, target, *, parent_percentile, shrinkage_strength, seed, samples, lower_quantile, upper_quantile):
    """The former pure-Python form (``random.choices`` per draw): the oracle for the numpy replay of the same stream."""

    pairs = pc._valid_pairs(values, weights)
    rng = random.Random(seed)
    population = list(range(len(pairs)))
    probabilities = [weight for _, weight in pairs]
    n = pc.effective_sample_size(probabilities)
    draws = []
    for _ in range(samples):
        indices = rng.choices(population, weights=probabilities, k=len(pairs))
        rank = pc.weighted_empirical_cdf([pairs[index][0] for index in indices], [1.0] * len(indices), target)
        draws.append((n * rank + shrinkage_strength * parent_percentile) / (n + shrinkage_strength))
    draws.sort()
    return draws[int(lower_quantile * (samples - 1))], draws[int(upper_quantile * (samples - 1))]


def test_bootstrap_interval_replays_the_python_random_stream_exactly() -> None:
    rng = random.Random(11)
    cases = 0
    for k in (1, 2, 3, 5, 13, 40, 250):
        for rep in range(6):
            values = [round(rng.gauss(0, 1), 1 if rep % 2 else 6) for _ in range(k)]  # rounding makes ties
            weights = [1.0] * k if rep < 3 else [rng.choice((0.5, 1.0, 2.5, 1e-9)) for _ in range(k)]
            target = values[rng.randrange(k)] if rep % 3 == 0 else rng.gauss(0, 1)
            seed = (zlib.crc32(f"id{k}|roe".encode()), -7, 2**40 + 3, "text-seed", 0, 2**70)[rep]
            kwargs = dict(parent_percentile=0.5 if rep % 2 else 0.3, shrinkage_strength=0.0 if rep % 2 else 3.0, seed=seed,
                          samples=(1, 7, 200)[rep % 3], lower_quantile=0.1, upper_quantile=0.9)
            assert pc.bootstrap_percentile_interval(values, weights, target, **kwargs) == _python_bootstrap(values, weights, target, **kwargs)
            cases += 1
    assert cases == 42


def _old_cohort_members(target, candidates):
    def same(left, right):
        return bool(left) and bool(right) and left.strip().casefold() == right.strip().casefold()

    others = [item for item in candidates if item.instrument_id != target.instrument_id]
    return {
        level: tuple(item.instrument_id for item in others if same(getattr(target, level), getattr(item, level)))
        for level in ("industry", "sector", "region")
    } | {"universe": tuple(item.instrument_id for item in others)}


def test_peer_index_gives_the_peers_and_cohorts_of_a_scan_over_every_candidate() -> None:
    rng = random.Random(5)
    traits = ("Banks", "banks ", "BANKS", "", " ", "Tech", "Energy")
    candidates = [
        PeerProfile(f"S{index:02d}", f"name {index}", rng.choice(traits), rng.choice(traits), rng.choice(("EU", "eu", "US", "")),
                    rng.choice((None, 1.0, 5.0, 20.0, 80.0)))
        for index in range(80)
    ]
    candidates.append(candidates[3])  # a repeated candidate keeps its place in both forms
    index = PeerIndex(candidates)
    for target in [*candidates, PeerProfile("X", "outside", "", "", "", None), PeerProfile("Y", "outside", "tech", "BANKS", "eu", 6.0)]:
        assert auto_peers(target, index.classified(target), CONFIG) == auto_peers(target, candidates, CONFIG)
        assert cohort_members(target, candidates) == _old_cohort_members(target, candidates)


def test_known_price_rows_end_at_the_close_of_each_stored_day() -> None:
    prices = pd.DataFrame({
        "etf_id": ["AAA"] * 3, "date": pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04"]), "close": [10.0, 11.0, 12.0],
        "currency": ["EUR"] * 3, "stock_splits": [0.0] * 3, "actions_evidenced": [True] * 3,
    })
    fx = pd.DataFrame(columns=store.FX_COLUMNS)
    # a stored day is known from the next midnight UTC: 2026-03-03 is known at 2026-03-04T00:00Z, not one microsecond earlier
    before = su.market_inputs(prices, None, "EUR", datetime(2026, 3, 3, 23, 59, 59, 999999, tzinfo=UTC), fx, CONFIG)
    at = su.market_inputs(prices, None, "EUR", datetime(2026, 3, 4, tzinfo=UTC), fx, CONFIG)
    assert (before.price_date.isoformat(), before.price) == ("2026-03-02", 10.0)
    assert (at.price_date.isoformat(), at.price) == ("2026-03-03", 11.0)


def _write_store(root, revenue: float) -> None:
    clean = root / "data" / "clean"
    clean.mkdir(parents=True, exist_ok=True)
    rows = [
        {"instrument_id": instrument, "period_end": f"{year}-12-31", "period_type": "FY", "fiscal_year": year, "currency": "EUR",
         "source": "yfinance", "source_ref": "t", "known_at": "2026-03-01T00:00:00+00:00", "revenue": revenue, "ebit": revenue / 10}
        for instrument in ("AAA", "BBB") for year in (2024, 2025)
    ]
    path = clean / "stock_fundamentals.parquet"
    stamp = path.stat().st_mtime_ns if path.is_file() else 0
    pd.DataFrame(rows).to_parquet(path)
    os.utime(path, ns=(stamp + 10**9, stamp + 10**9))  # a later file state even on a coarse clock


def test_periods_are_built_once_per_stored_file_state_and_rebuilt_after_a_write(tmp_path, monkeypatch) -> None:
    _write_store(tmp_path, 100.0)
    real, calls = store.periods_for, []
    monkeypatch.setattr(store, "periods_for", lambda instrument, frame, chain: calls.append(instrument) or real(instrument, frame, chain))
    records = [su.StockRecord(instrument, instrument, instrument, "EUR", "Europe", "Industrials") for instrument in ("AAA", "BBB")]
    decision = datetime(2026, 3, 2, tzinfo=UTC)
    first = su.build_universe_evidence(records, pd.DataFrame(), decision, root=tmp_path, config=CONFIG)
    second = su.build_universe_evidence(records, pd.DataFrame(), decision + timedelta(days=1), root=tmp_path, config=CONFIG)
    assert sorted(calls) == ["AAA", "BBB"]  # no decision-time input: one build per id, reused by the next session
    assert second.periods == first.periods
    _write_store(tmp_path, 200.0)
    changed = su.build_universe_evidence(records, pd.DataFrame(), decision, root=tmp_path, config=CONFIG)
    assert sorted(calls) == ["AAA", "AAA", "BBB", "BBB"]
    assert changed.periods["AAA"][-1].values["revenue"] == 200.0
