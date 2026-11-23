"""W2-S score lane: one policy read per run (SP-4)."""

from pathlib import Path

from etf_cockpit.analysis.decision import gates
from etf_cockpit.signals import canonical_scoring as cs


def test_policy_snapshot_reads_each_policy_once_per_run(monkeypatch):
    reads: list[str] = []
    real = Path.read_bytes

    def counting(self: Path) -> bytes:
        reads.append(self.name)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", counting)
    with cs.policy_snapshot():
        first = cs.load_score_policy("ETF")
        for _ in range(3):
            assert cs.load_score_policy("ETF") is first
            gates.load_critical_evidence_policy()
    assert reads.count(cs.FORMULA_PATH.name) == 1
    assert reads.count(gates.POLICY_PATH.name) == 1
    reads.clear()
    cs.load_score_policy("ETF")
    cs.load_score_policy("ETF")
    assert reads.count(cs.FORMULA_PATH.name) == 2  # outside a run every call reads the file, so an edit applies at once


def test_membership_log_writes_the_snapshot_pit_basis():
    import pandas as pd

    from etf_cockpit.application.score_backfill import _membership_log
    from etf_cockpit.data.import_pipeline import RECONSTRUCTED_PIT
    from etf_cockpit.data.replay_membership import ListingHistory
    from tests.test_score_backfill import _config

    bar = {"etf_id": "VWCE", "date": "2024-06-28", "close": 100.0, "volume": 1000, "source": "yfinance",
           "available_at": pd.Timestamp("2026-11-21T02:00:00Z")}  # restamped by a later refetch: admitted at the session close
    snapshot = ListingHistory().with_observed_trading(pd.DataFrame([bar]), _config()).snapshot(pd.Timestamp("2024-06-28").date(), ["VWCE"])

    log = _membership_log(pd.DataFrame({"instrument_id": ["VWCE"]}), snapshot)

    assert log["pit_basis"].tolist() == [RECONSTRUCTED_PIT]


def test_live_score_build_shares_one_correlation_matrix(monkeypatch):
    from types import SimpleNamespace

    import pandas as pd

    from etf_cockpit.core.config import load_config
    from etf_cockpit.signals import simple_scores as s

    matrix = object()
    built: list[object] = []
    seen: dict[str, object] = {}
    monkeypatch.setattr(s, "correlation_matrix", lambda prices: built.append(prices) or matrix)
    monkeypatch.setattr(s, "build_correlation_clusters", lambda *a, **kw: seen.setdefault("clusters", kw.get("matrix")) and SimpleNamespace(rows=[]))
    monkeypatch.setattr(s, "rank_and_finalize_scores", lambda scores, prices, metadata, **kw: seen.setdefault("ranked", kw.get("correlations")) and [])
    monkeypatch.setattr(s, "_generate_missing_price_signals", lambda config, sigs, px: (sigs, {}))
    monkeypatch.setattr(s, "load_latest_candidate_report", lambda: (pd.DataFrame(), None))
    monkeypatch.setattr(s, "load_forecast_history", lambda: pd.DataFrame())
    for name in ("build_market_regime", "build_portfolio_fit_lookup", "build_benchmark_attribution_lookup"):
        monkeypatch.setattr(s, name, lambda *a, **kw: {})
    monkeypatch.setattr(s, "_backtest_trust_lookup", lambda **kw: {})
    monkeypatch.setattr(s, "build_universe_simple_scores", lambda *a, **kw: [])
    monkeypatch.setattr(s, "build_candidate_simple_scores", lambda *a, **kw: [])
    prices = pd.DataFrame({"etf_id": ["VWCE"]})

    s.build_simple_instrument_scores(load_config(), [], pd.DataFrame(), prices, universe_revision="audit", cash_comparison_lookup={})

    assert len(built) == 1 and built[0] is prices
    assert seen == {"clusters": matrix, "ranked": matrix}


def test_row_freshness_skips_components_with_no_score():
    from types import SimpleNamespace

    from etf_cockpit.data import trust_artifacts

    def score(*components):
        return SimpleNamespace(components=list(components), latest_date="2026-11-20", latest_price=10.0)

    scored = SimpleNamespace(key="momentum", score_10=6.0, freshness_status="ok")
    absent = SimpleNamespace(key="baseline", score_10=None, freshness_status="unknown")  # coverage, not freshness
    stale = SimpleNamespace(key="trend", score_10=5.0, freshness_status="stale")
    at = "2026-11-22T22:30:00+00:00"
    assert trust_artifacts._score_freshness(score(scored, absent), at) == "ok"
    assert trust_artifacts._score_freshness(score(scored, absent, stale), at) == "stale"


def test_generate_signals_runs_inside_one_policy_snapshot(monkeypatch):
    from datetime import date

    import pandas as pd
    import pytest

    from etf_cockpit.core.types import DataQualityReport
    from etf_cockpit.signals import signal_pipeline

    seen: list[bool] = []

    def stop(*a, **kw):
        seen.append(cs._POLICY_SNAPSHOT.get() is not None)
        raise RuntimeError("stop")

    monkeypatch.setattr(signal_pipeline, "allocation_frame", stop)
    with pytest.raises(RuntimeError, match="stop"):
        signal_pipeline.generate_signals(None, pd.DataFrame(), pd.DataFrame(), DataQualityReport(date(2026, 11, 20), []), run_id="t")
    assert seen == [True]


def test_as_traded_factors_are_idempotent_with_an_unevidenced_recent_row():
    """S6 reuses one per-run with_as_traded_factors(prices) in every score_as_of; a second call must change nothing."""
    import pandas as pd

    from etf_cockpit.analysis.stock_universe import with_as_traded_factors

    days = pd.to_datetime(["2025-06-02", "2025-06-03", "2025-06-04"])
    prices = pd.DataFrame({
        "etf_id": ["AAA"] * 3 + ["BBB"] * 3,
        "date": list(days) * 2,
        "adjusted_close": [10.0, 5.0, 5.1, 20.0, 20.5, 21.0],
        "stock_splits": [0.0, 2.0, 0.0, 0.0, 0.0, 0.0],
        "actions_evidenced": [True, True, True, True, True, False],  # BBB's recent row is not evidenced yet
    })

    once = with_as_traded_factors(prices)

    pd.testing.assert_frame_equal(with_as_traded_factors(once), once)
    pd.testing.assert_frame_equal(with_as_traded_factors(once.loc[once["date"] <= days[1]]), once.loc[once["date"] <= days[1]])
