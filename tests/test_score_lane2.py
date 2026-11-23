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
