from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.v2_runtime_attestation import AttestationError, attest_runtime


AGENT_PATH = "/root/attested-child"
PARENT_ID = "parent-thread"


def _source(role: str = "diagnostician") -> str:
    return json.dumps(
        {
            "subagent": {
                "thread_spawn": {
                    "agent_path": AGENT_PATH,
                    "agent_role": role,
                    "parent_thread_id": PARENT_ID,
                }
            }
        }
    )


def _database(home: Path, *, model: str | None = "gpt-6-astra", effort: str | None = "medium") -> Path:
    database = home / "state_5.sqlite"
    con = sqlite3.connect(database)
    con.execute(
        """CREATE TABLE threads (
        id TEXT, agent_path TEXT, agent_role TEXT, model TEXT, reasoning_effort TEXT,
        cwd TEXT, source TEXT, rollout_path TEXT, created_at INTEGER, updated_at INTEGER
        )"""
    )
    con.execute(
        "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("child-thread", AGENT_PATH, "diagnostician", model, effort, "C:/repo", _source(), "", 1, 2),
    )
    con.commit()
    con.close()
    return database


def _attest(home: Path) -> dict:
    return attest_runtime(
        codex_home=home,
        agent_path=AGENT_PATH,
        expected_role="diagnostician",
        expected_model="gpt-6-astra",
        expected_effort="medium",
        expected_cwd="C:/repo",
    )


def test_exact_state_db_identity_is_preferred(tmp_path: Path) -> None:
    _database(tmp_path)
    result = _attest(tmp_path)
    assert result["status"] == "V2_RUNTIME_ATTESTATION_PROVEN"
    assert result["source"] == "state_db"
    assert result["identity"]["id"] == "child-thread"


def test_duplicate_exact_agent_path_fails_closed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    con = sqlite3.connect(database)
    con.execute(
        "INSERT INTO threads SELECT 'second-child', agent_path, agent_role, model, reasoning_effort, cwd, source, rollout_path, created_at, updated_at FROM threads"
    )
    con.commit()
    con.close()
    with pytest.raises(AttestationError, match="ambiguous_state_db_agent_path"):
        _attest(tmp_path)


def test_null_runtime_fields_use_exact_rollout_fallback(tmp_path: Path) -> None:
    database = _database(tmp_path, model=None, effort=None)
    rollout = tmp_path / "sessions" / "2026" / "rollout.jsonl"
    rollout.parent.mkdir(parents=True)
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": "child-thread",
                "agent_path": AGENT_PATH,
                "agent_role": "diagnostician",
                "cwd": "C:/repo",
                "parent_thread_id": PARENT_ID,
                "source": json.loads(_source()),
            },
        },
        {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "medium"}},
    ]
    rollout.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    con = sqlite3.connect(database)
    con.execute("UPDATE threads SET rollout_path = ?", (str(rollout),))
    con.commit()
    con.close()
    result = _attest(tmp_path)
    assert result["source"] == "rollout_fallback"
    assert result["identity"]["model"] == "gpt-6-astra"


def test_contradictory_model_fails_before_rollout(tmp_path: Path) -> None:
    _database(tmp_path, model="wrong-model")
    with pytest.raises(AttestationError, match="state_db_model_mismatch"):
        _attest(tmp_path)


def test_fallback_requires_database_and_rollout_binding(tmp_path: Path) -> None:
    database = _database(tmp_path, model=None, effort=None)
    rollout = tmp_path / "sessions" / "rollout.jsonl"
    rollout.parent.mkdir()
    source = json.loads(_source())
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": "different-thread",
                "agent_path": AGENT_PATH,
                "agent_role": "diagnostician",
                "cwd": "C:/repo",
                "parent_thread_id": PARENT_ID,
                "source": source,
            },
        },
        {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "medium"}},
    ]
    rollout.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
    con = sqlite3.connect(database)
    con.execute("UPDATE threads SET rollout_path = ?", (str(rollout),))
    con.commit()
    con.close()
    with pytest.raises(AttestationError, match="state_db_rollout_binding_mismatch"):
        _attest(tmp_path)


def test_mixed_turn_contexts_fail_closed(tmp_path: Path) -> None:
    database = _database(tmp_path, model=None, effort=None)
    rollout = tmp_path / "sessions" / "rollout.jsonl"
    rollout.parent.mkdir()
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": "child-thread",
                "agent_path": AGENT_PATH,
                "agent_role": "diagnostician",
                "cwd": "C:/repo",
                "parent_thread_id": PARENT_ID,
                "source": json.loads(_source()),
            },
        },
        {"type": "turn_context", "payload": {"model": "wrong", "effort": "medium"}},
        {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "medium"}},
    ]
    rollout.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
    con = sqlite3.connect(database)
    con.execute("UPDATE threads SET rollout_path = ?", (str(rollout),))
    con.commit()
    con.close()
    with pytest.raises(AttestationError, match="missing_or_ambiguous_rollout_runtime_context"):
        _attest(tmp_path)


def test_missing_thread_id_fails_closed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    con = sqlite3.connect(database)
    con.execute("UPDATE threads SET id = NULL")
    con.commit()
    con.close()
    with pytest.raises(AttestationError, match="state_db_spawn_identity_mismatch"):
        _attest(tmp_path)


def test_live_database_files_are_not_opened_or_modified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _database(tmp_path)
    before = {path.name: (path.stat().st_size, path.stat().st_mtime_ns) for path in tmp_path.iterdir()}
    real_connect = sqlite3.connect

    def guarded_connect(target, *args, **kwargs):
        assert Path(target).resolve() != database.resolve()
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    assert _attest(tmp_path)["status"] == "V2_RUNTIME_ATTESTATION_PROVEN"
    after = {path.name: (path.stat().st_size, path.stat().st_mtime_ns) for path in tmp_path.iterdir()}
    assert after == before
