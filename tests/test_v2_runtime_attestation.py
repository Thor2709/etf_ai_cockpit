from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
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


def test_incomplete_conflicting_turn_context_fails_closed(tmp_path: Path) -> None:
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
        {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "medium"}},
        {"type": "turn_context", "payload": {"model": "wrong-model"}},
    ]
    rollout.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
    con = sqlite3.connect(database)
    con.execute("UPDATE threads SET rollout_path = ?", (str(rollout),))
    con.commit()
    con.close()
    with pytest.raises(AttestationError, match="incomplete_rollout_runtime_context"):
        _attest(tmp_path)


def test_second_session_metadata_fails_closed(tmp_path: Path) -> None:
    database = _database(tmp_path, model=None, effort=None)
    rollout = tmp_path / "sessions" / "rollout.jsonl"
    rollout.parent.mkdir()
    target = {
        "type": "session_meta",
        "payload": {
            "id": "child-thread",
            "agent_path": AGENT_PATH,
            "agent_role": "diagnostician",
            "cwd": "C:/repo",
            "parent_thread_id": PARENT_ID,
            "source": json.loads(_source()),
        },
    }
    other = json.loads(json.dumps(target))
    other["payload"]["id"] = "other-thread"
    other["payload"]["agent_path"] = "/root/other"
    other["payload"]["source"]["subagent"]["thread_spawn"]["agent_path"] = "/root/other"
    records = [target, other, {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "medium"}}]
    rollout.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
    con = sqlite3.connect(database)
    con.execute("UPDATE threads SET rollout_path = ?", (str(rollout),))
    con.commit()
    con.close()
    with pytest.raises(AttestationError, match="ambiguous_rollout_session_metadata"):
        _attest(tmp_path)


def test_missing_thread_id_fails_closed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    con = sqlite3.connect(database)
    con.execute("UPDATE threads SET id = NULL")
    con.commit()
    con.close()
    with pytest.raises(AttestationError, match="state_db_spawn_identity_mismatch"):
        _attest(tmp_path)


def test_live_database_uses_read_only_uri_and_query_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "state # with % reserved characters"
    home.mkdir()
    database = _database(home)
    before = database.read_bytes()
    real_connect = sqlite3.connect
    statements = []

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("SELECT") or sql.startswith("PRAGMA table_info"):
                assert self.in_transaction
                assert super().execute("PRAGMA query_only").fetchone()[0] == 1
            return super().execute(sql, parameters)

    def guarded_connect(target, *args, **kwargs):
        assert target == database.resolve().as_uri() + "?mode=ro"
        assert kwargs["uri"] is True
        assert 0 < kwargs["timeout"] <= 1
        connection = real_connect(target, *args, factory=ObservedConnection, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    assert _attest(home)["status"] == "V2_RUNTIME_ATTESTATION_PROVEN"
    assert database.read_bytes() == before
    assert [p.name for p in home.iterdir()] == [database.name]
    assert statements == [
        "PRAGMA query_only=ON", "BEGIN", "PRAGMA query_only",
        "PRAGMA table_info(threads)", "PRAGMA query_only",
        "SELECT agent_path, agent_role, created_at, cwd, id, model, reasoning_effort, "
        "rollout_path, source, updated_at FROM threads WHERE agent_path = '/root/attested-child'",
    ]


@pytest.mark.parametrize("kind", ["missing", "malformed", "schema"])
def test_invalid_database_is_not_created_or_repaired(tmp_path: Path, kind: str) -> None:
    database = tmp_path / "state_5.sqlite"
    if kind == "malformed":
        database.write_bytes(b"not a SQLite database")
    elif kind == "schema":
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE threads (id TEXT)")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises((AttestationError, sqlite3.DatabaseError)):
        _attest(tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("agent_role", "reviewer", "state_db_role_mismatch"),
        ("reasoning_effort", "low", "state_db_reasoning_effort_mismatch"),
        ("source", _source("reviewer"), "state_db_spawn_identity_mismatch"),
        ("source", _source().replace(PARENT_ID, ""), "state_db_spawn_identity_mismatch"),
        ("cwd", "C:/elsewhere", "runtime_identity_mismatch:cwd"),
    ],
)
def test_contradictory_identity_fails_closed(tmp_path: Path, column: str, value: str, reason: str) -> None:
    database = _database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE threads SET {column} = ?", (value,))
    with pytest.raises(AttestationError, match=reason):
        _attest(tmp_path)


def test_no_exact_row_remains_unresolved(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE threads SET agent_path = ?", (AGENT_PATH + "-other",))
    with pytest.raises(AttestationError, match="persisted_rollout_identity_absent_or_ambiguous"):
        _attest(tmp_path)


def test_rollout_hint_outside_session_roots_fails_closed(tmp_path: Path) -> None:
    database = _database(tmp_path, model=None)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}", encoding="utf-8")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE threads SET rollout_path = ?", (str(outside),))
    with pytest.raises(AttestationError, match="rollout_path_outside_codex_session_roots"):
        _attest(tmp_path)


def test_wal_observer_does_not_mutate_database_files(tmp_path: Path) -> None:
    database = _database(tmp_path)
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE threads SET updated_at = 3")
        writer.commit()
        # Establish the current WAL read mark before measuring observer contents.
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as reader:
            reader.execute("SELECT * FROM threads").fetchall()
        paths = [database, Path(str(database) + "-wal"), Path(str(database) + "-shm")]
        before = {p.name: p.read_bytes() for p in paths}
        assert _attest(tmp_path)["source"] == "state_db"
        assert {p.name: p.read_bytes() for p in paths} == before
    finally:
        writer.close()


def test_concurrent_wal_commit_preserves_one_read_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(tmp_path)
    real_connect = sqlite3.connect
    keeper = real_connect(database)
    keeper.execute("PRAGMA journal_mode=WAL")
    keeper.execute("CREATE TABLE unrelated (value INTEGER)")
    keeper.execute("INSERT INTO unrelated VALUES (0)")
    keeper.commit()
    lookup_started = Event()
    committed = Event()

    def write_unrelated():
        assert lookup_started.wait(5)
        with real_connect(database, timeout=1) as writer:
            writer.execute("UPDATE unrelated SET value = value + 1")
            writer.commit()
        committed.set()

    class ConcurrentConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("SELECT"):
                assert self.in_transaction
                lookup_started.set()
                assert committed.wait(5), "WAL writer must commit while observer transaction is open"
                # Schema read already pinned the snapshot before the writer committed.
                assert super().execute("SELECT value FROM unrelated").fetchone()[0] == 0
            return super().execute(sql, parameters)

    def observed_connect(target, *args, **kwargs):
        return real_connect(target, *args, factory=ConcurrentConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(write_unrelated)
            result = _attest(tmp_path)
            future.result(timeout=5)
        assert result["identity"]["id"] == "child-thread"
        assert result["identity"]["model"] == "gpt-6-astra"
        assert result["identity"]["reasoning_effort"] == "medium"
        assert keeper.execute("SELECT value FROM unrelated").fetchone()[0] == 1
    finally:
        keeper.close()
