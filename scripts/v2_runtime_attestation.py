"""Attest a spawned V2 agent from Codex's persisted read-only runtime state."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {
    "id",
    "agent_path",
    "agent_role",
    "model",
    "reasoning_effort",
    "cwd",
    "source",
    "rollout_path",
    "created_at",
    "updated_at",
}


class AttestationError(RuntimeError):
    """Raised when persisted runtime identity is absent or contradictory."""


def _normalise_path(value: str) -> str:
    value = value.replace("\\\\?\\", "", 1).replace("/", "\\")
    return value.rstrip("\\").casefold()


def _source_identity(source: Any) -> tuple[str | None, str | None, str | None]:
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except json.JSONDecodeError:
            return None, None, None
    if not isinstance(source, dict):
        return None, None, None
    subagent = source.get("subagent") or source.get("subAgent")
    if not isinstance(subagent, dict):
        return None, None, None
    spawn = subagent.get("thread_spawn")
    if not isinstance(spawn, dict):
        return None, None, None
    return spawn.get("agent_path"), spawn.get("agent_role"), spawn.get("parent_thread_id")


def _read_sqlite_row(database: Path, agent_path: str) -> dict[str, Any] | None:
    uri = database.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise AttestationError("state_db_missing_columns:" + ",".join(missing))
        fields = ", ".join(sorted(REQUIRED_COLUMNS))
        rows = connection.execute(
            f"SELECT {fields} FROM threads WHERE agent_path = ?",  # noqa: S608
            (agent_path,),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) > 1:
        raise AttestationError("ambiguous_state_db_agent_path")
    return dict(rows[0]) if rows else None


def _candidate_rollouts(codex_home: Path, agent_path: str) -> list[Path]:
    needle = agent_path.encode("utf-8")
    matches: list[Path] = []
    for folder in (codex_home / "sessions", codex_home / "archived_sessions"):
        if not folder.exists():
            continue
        for path in folder.rglob("*.jsonl"):
            try:
                if needle in path.read_bytes():
                    matches.append(path.resolve())
            except OSError:
                continue
    return matches


def _read_rollout_identity(path: Path, agent_path: str) -> dict[str, Any] | None:
    session: dict[str, Any] | None = None
    model: str | None = None
    effort: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if record.get("type") == "session_meta":
            source_path, source_role, parent_id = _source_identity(payload.get("source"))
            if source_path == agent_path and payload.get("agent_path") == agent_path:
                session = {
                    "id": payload.get("id"),
                    "agent_path": agent_path,
                    "agent_role": payload.get("agent_role") or source_role,
                    "cwd": payload.get("cwd"),
                    "source": payload.get("source"),
                    "parent_thread_id": payload.get("parent_thread_id") or parent_id,
                    "cli_version": payload.get("cli_version"),
                    "rollout_path": str(path),
                }
        elif record.get("type") == "turn_context":
            model = payload.get("model") or model
            effort = payload.get("effort") or payload.get("reasoning_effort") or effort
    if session is None:
        return None
    session.update(model=model, reasoning_effort=effort)
    return session


def attest_runtime(
    *,
    codex_home: Path,
    agent_path: str,
    expected_role: str,
    expected_model: str,
    expected_effort: str,
    expected_cwd: str | None = None,
) -> dict[str, Any]:
    database = codex_home / "state_5.sqlite"
    row = _read_sqlite_row(database, agent_path)
    source_path = source_role = parent_id = None
    if row:
        source_path, source_role, parent_id = _source_identity(row.get("source"))
        if row.get("agent_role") not in (None, expected_role):
            raise AttestationError("state_db_role_mismatch")
        if row.get("model") not in (None, expected_model):
            raise AttestationError("state_db_model_mismatch")
        if row.get("reasoning_effort") not in (None, expected_effort):
            raise AttestationError("state_db_reasoning_effort_mismatch")
        if source_path != agent_path or source_role != expected_role or not parent_id:
            raise AttestationError("state_db_spawn_identity_mismatch")

    identity = row
    source_kind = "state_db"
    if row is None or row.get("model") is None or row.get("reasoning_effort") is None:
        hinted = Path(row["rollout_path"]).resolve() if row and row.get("rollout_path") else None
        candidates = [hinted] if hinted and hinted.exists() else _candidate_rollouts(codex_home, agent_path)
        identities = [value for path in candidates if (value := _read_rollout_identity(path, agent_path))]
        unique = {value.get("id"): value for value in identities}
        if len(unique) != 1:
            raise AttestationError("persisted_rollout_identity_absent_or_ambiguous")
        identity = next(iter(unique.values()))
        source_kind = "rollout_fallback"

    assert identity is not None
    identity_path, identity_role, identity_parent = _source_identity(identity.get("source"))
    role = identity.get("agent_role") or identity_role
    parent = identity.get("parent_thread_id") or identity_parent
    checks = {
        "agent_path": identity.get("agent_path") == agent_path and identity_path == agent_path,
        "agent_role": role == expected_role,
        "model": identity.get("model") == expected_model,
        "reasoning_effort": identity.get("reasoning_effort") == expected_effort,
        "parent_thread_non_null": bool(parent),
        "cwd": expected_cwd is None
        or _normalise_path(str(identity.get("cwd") or "")) == _normalise_path(expected_cwd),
    }
    if not all(checks.values()):
        failed = ",".join(name for name, passed in checks.items() if not passed)
        raise AttestationError("runtime_identity_mismatch:" + failed)
    return {
        "status": "V2_RUNTIME_ATTESTATION_PROVEN",
        "source": source_kind,
        "checks": checks,
        "identity": {
            key: identity.get(key)
            for key in (
                "id",
                "agent_path",
                "agent_role",
                "model",
                "reasoning_effort",
                "cwd",
                "source",
                "rollout_path",
                "created_at",
                "updated_at",
            )
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--agent-path", required=True)
    parser.add_argument("--expected-role", required=True)
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--expected-effort", required=True)
    parser.add_argument("--expected-cwd")
    args = parser.parse_args(argv)
    try:
        result = attest_runtime(
            codex_home=args.codex_home,
            agent_path=args.agent_path,
            expected_role=args.expected_role,
            expected_model=args.expected_model,
            expected_effort=args.expected_effort,
            expected_cwd=args.expected_cwd,
        )
    except (AttestationError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"status": "V2_RUNTIME_ATTESTATION_FAILED", "reason": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
