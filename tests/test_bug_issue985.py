"""V8 intake for #985: incident reconciliation fails closed."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from etf_cockpit.trading.incidents import IncidentJournal, IncidentJournalError

AT = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)


# D.C2.S21.N001
def test_reconcile_without_active_incidents_still_compares_states(tmp_path: Path) -> None:
    journal = IncidentJournal(tmp_path)

    assert journal.reconcile({"cash": 1.0}, {"cash": 1.0})["status"] == "ready"
    result = journal.reconcile({"cash": 1.0}, {"cash": 2.0})

    assert result["status"] == "mismatch"
    assert result["frozen"] is False
    assert result["execution_allowed"] is False


# D.C2.S21.N002
@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_state_is_rejected(tmp_path: Path, bad: float) -> None:
    journal = IncidentJournal(tmp_path)
    journal.record("x", message="m", requires_freeze=True, occurred_at=AT)

    with pytest.raises(IncidentJournalError):
        journal.reconcile({"cash": bad}, {"cash": bad})
    with pytest.raises(IncidentJournalError):
        journal.append_postmortem("nope", summary="s", evidence={"v": bad})
    assert journal.is_frozen is True
