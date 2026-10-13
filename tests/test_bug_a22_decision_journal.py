from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from etf_cockpit.data import decision_journal as journal_module
from etf_cockpit.data.decision_journal import DecisionJournal, JournalEntry, JournalIntegrityError

_SRC = str(Path(__file__).resolve().parents[1] / "src")


def _entry(entry_id: str = "entry-1", created_at: str = "2026-07-12T00:00:00+00:00") -> JournalEntry:
    return JournalEntry(
        journal_entry_id=entry_id,
        created_at=created_at,
        thesis="thesis",
        decision="review",
        outcome="pending",
        private_notes=None,
    )


def _lock_path(root: Path) -> Path:
    return root / "decision_journal" / ".journal-write.lock"


def test_dead_owner_lock_is_recovered_and_entries_intact(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry("entry-1"), root=tmp_path)
    code = (
        "import sys, time; sys.path.insert(0, sys.argv[1]); from pathlib import Path\n"
        "from etf_cockpit.data.decision_journal import DecisionJournal\n"
        "with DecisionJournal()._journal_write_lock(Path(sys.argv[2])):\n"
        "    print('locked', flush=True); time.sleep(120)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code, _SRC, str(tmp_path)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "locked"
        assert _lock_path(tmp_path).is_file()
        child.kill()
        child.wait(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
    assert _lock_path(tmp_path).is_file()  # stale lock left by the killed writer

    journal.create(_entry("entry-2", "2026-07-13T00:00:00+00:00"), root=tmp_path)

    assert [entry.journal_entry_id for entry in journal.list_entries(root=tmp_path)] == ["entry-1", "entry-2"]
    assert not _lock_path(tmp_path).exists()
    assert journal.integrity_status(tmp_path) == "ok"


def test_live_lock_is_not_stolen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal = DecisionJournal()
    lock = _lock_path(tmp_path)
    lock.parent.mkdir(parents=True)
    import os

    payload = f"{os.getpid()}:deadbeef"  # this process is alive
    lock.write_text(payload, encoding="ascii")
    ticks = iter(range(0, 10_000, 5))
    fake_time = types.SimpleNamespace(monotonic=lambda: float(next(ticks)), sleep=lambda _s: None)
    monkeypatch.setattr(journal_module, "time", fake_time)

    with pytest.raises(TimeoutError):
        journal.create(_entry(), root=tmp_path)

    assert lock.read_text(encoding="ascii") == payload
    assert journal._recover_dead_owner_lock(lock) is False
    assert lock.read_text(encoding="ascii") == payload


def test_unparseable_lock_payload_is_never_recovered(tmp_path: Path) -> None:
    journal = DecisionJournal()
    lock = _lock_path(tmp_path)
    lock.parent.mkdir(parents=True)
    lock.write_text("", encoding="ascii")

    assert journal._recover_dead_owner_lock(lock) is False
    assert lock.is_file()


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_operations_log_damage_is_reported_on_reads(tmp_path: Path, damage: str) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)
    assert journal.integrity_status(tmp_path) == "ok"
    operations = tmp_path / "decision_journal" / "operations.jsonl"
    if damage == "missing":
        operations.unlink()
    else:
        operations.write_bytes(b"{not json\n")
    expected = f"operations_log_{damage}"

    with pytest.raises(JournalIntegrityError) as get_error:
        journal.get("entry-1", root=tmp_path)
    with pytest.raises(JournalIntegrityError) as list_error:
        journal.list_entries(root=tmp_path)

    assert get_error.value.integrity_status == expected
    assert list_error.value.integrity_status == expected
    assert journal.integrity_status(tmp_path) == expected


def test_unindexed_orphan_entry_is_reported(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)
    entries = tmp_path / "decision_journal" / "entries"
    (entries / "orphan-1.json").write_text((entries / "entry-1.json").read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(JournalIntegrityError) as get_error:
        journal.get("entry-1", root=tmp_path)
    with pytest.raises(JournalIntegrityError) as list_error:
        journal.list_entries(root=tmp_path)

    assert get_error.value.integrity_status == "orphan_entries"
    assert list_error.value.integrity_status == "orphan_entries"
    assert journal.integrity_status(tmp_path) == "orphan_entries"


def test_healthy_journal_reads_unchanged(tmp_path: Path) -> None:
    journal = DecisionJournal()
    created = journal.create(_entry(), root=tmp_path)

    assert journal.get("entry-1", root=tmp_path) == created
    assert journal.list_entries(root=tmp_path) == [created]
    assert DecisionJournal().integrity_status(tmp_path / "empty") == "ok"


def test_reader_holding_a_pre_commit_index_does_not_report_a_committed_entry_as_orphan(tmp_path: Path) -> None:
    journal = DecisionJournal()
    journal.create(_entry(), root=tmp_path)
    stale_index = journal._read_index(tmp_path)
    journal.create(_entry("entry-2", "2026-07-13T00:00:00+00:00"), root=tmp_path)

    assert journal._log_integrity_status(tmp_path, stale_index) == "ok"
