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
