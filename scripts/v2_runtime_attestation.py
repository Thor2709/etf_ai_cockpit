"""Attest a spawned V2 agent from Codex's persisted read-only runtime state."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
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


def _file_signature(path: Path) -> tuple[bool, int, str]:
    try:
        size = path.stat().st_size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return False, 0, ""
    return True, size, digest


def _snapshot_database(database: Path, target: Path) -> Path:
    """Copy a stable SQLite/WAL set without opening Codex's live database."""

    sources = [database, Path(str(database) + "-wal"), Path(str(database) + "-shm")]
    if not database.is_file():
        raise AttestationError("state_db_missing")
    before = [_file_signature(path) for path in sources]
    for path, signature in zip(sources, before, strict=True):
        if signature[0]:
            shutil.copy2(path, target / path.name)
            if _file_signature(target / path.name) != signature:
                raise AttestationError("state_db_snapshot_copy_mismatch")
    after = [_file_signature(path) for path in sources]
    if before != after:
        raise AttestationError("state_db_changed_during_snapshot")
    return target / database.name


def _read_sqlite_row(database: Path, agent_path: str) -> dict[str, Any] | None:
    with tempfile.TemporaryDirectory(prefix="codex-attestation-") as temporary:
        snapshot = _snapshot_database(database.resolve(), Path(temporary))
        return _read_snapshot_row(snapshot, agent_path)


def _read_snapshot_row(database: Path, agent_path: str) -> dict[str, Any] | None:
    connection = sqlite3.connect(database)
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
                resolved = path.resolve(strict=True)
                resolved.relative_to(folder.resolve(strict=True))
                if needle in resolved.read_bytes():
                    matches.append(resolved)
            except (OSError, ValueError) as exc:
                raise AttestationError(f"rollout_discovery_failed:{path}") from exc
    return matches


def _read_rollout_identity(path: Path, agent_path: str) -> dict[str, Any] | None:
    sessions: list[dict[str, Any]] = []
    contexts: list[tuple[str, str]] = []
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
            sessions.append({
                    "id": payload.get("id"),
                    "agent_path": payload.get("agent_path"),
                    "agent_role": payload.get("agent_role") or source_role,
                    "cwd": payload.get("cwd"),
                    "source": payload.get("source"),
                    "parent_thread_id": payload.get("parent_thread_id") or parent_id,
                    "cli_version": payload.get("cli_version"),
                    "rollout_path": str(path),
                })
        elif record.get("type") == "turn_context":
            model = payload.get("model")
            effort = payload.get("effort")
            alternate_effort = payload.get("reasoning_effort")
            if effort is not None and alternate_effort is not None and effort != alternate_effort:
                raise AttestationError("contradictory_rollout_reasoning_effort")
            effective_effort = effort or alternate_effort
            if not (
                isinstance(model, str)
                and model
                and isinstance(effective_effort, str)
                and effective_effort
            ):
                raise AttestationError("incomplete_rollout_runtime_context")
            contexts.append((model, effective_effort))
    if not sessions:
        return None
    if len(sessions) != 1:
        raise AttestationError("ambiguous_rollout_session_metadata")
    if sessions[0]["agent_path"] != agent_path:
        return None
    unique_contexts = set(contexts)
    if len(unique_contexts) != 1:
        raise AttestationError("missing_or_ambiguous_rollout_runtime_context")
    session = sessions[0]
    model, effort = next(iter(unique_contexts))
    session.update(model=model, reasoning_effort=effort)
    return session


def _require_rollout_path(codex_home: Path, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    allowed = [
        folder.resolve(strict=True)
        for folder in (codex_home / "sessions", codex_home / "archived_sessions")
        if folder.exists()
    ]
    if not any(resolved.is_relative_to(folder) for folder in allowed):
        raise AttestationError("rollout_path_outside_codex_session_roots")
    return resolved


def _binding(identity: dict[str, Any]) -> dict[str, Any]:
    source_path, source_role, parent = _source_identity(identity.get("source"))
    role = identity.get("agent_role")
    if role != source_role:
        raise AttestationError("identity_role_sources_disagree")
    top_parent = identity.get("parent_thread_id")
    if top_parent is not None and top_parent != parent:
        raise AttestationError("identity_parent_sources_disagree")
    return {
        "id": identity.get("id"),
        "agent_path": identity.get("agent_path"),
        "agent_role": role,
        "cwd": identity.get("cwd"),
        "parent_thread_id": top_parent or parent,
        "source_agent_path": source_path,
    }


def attest_runtime(
    *,
    codex_home: Path,
    agent_path: str,
    expected_role: str,
    expected_model: str,
    expected_effort: str,
    expected_cwd: str,
) -> dict[str, Any]:
    database = codex_home / "state_5.sqlite"
    row = _read_sqlite_row(database, agent_path)
    source_path = source_role = parent_id = None
    if row:
        source_path, source_role, parent_id = _source_identity(row.get("source"))
        if row.get("agent_role") != expected_role:
            raise AttestationError("state_db_role_mismatch")
        if row.get("model") not in (None, expected_model):
            raise AttestationError("state_db_model_mismatch")
        if row.get("reasoning_effort") not in (None, expected_effort):
            raise AttestationError("state_db_reasoning_effort_mismatch")
        if (
            not row.get("id")
            or not row.get("cwd")
            or source_path != agent_path
            or source_role != expected_role
            or not parent_id
        ):
            raise AttestationError("state_db_spawn_identity_mismatch")

    identity = row
    source_kind = "state_db"
    if row is None or row.get("model") is None or row.get("reasoning_effort") is None:
        hinted = (
            _require_rollout_path(codex_home, Path(row["rollout_path"]))
            if row and row.get("rollout_path")
            else None
        )
        candidates = [hinted] if hinted else _candidate_rollouts(codex_home, agent_path)
        identities = [value for path in candidates if (value := _read_rollout_identity(path, agent_path))]
        if len(identities) != 1 or not identities[0].get("id"):
            raise AttestationError("persisted_rollout_identity_absent_or_ambiguous")
        identity = identities[0]
        if row and _binding(row) != _binding(identity):
            raise AttestationError("state_db_rollout_binding_mismatch")
        source_kind = "rollout_fallback"

    assert identity is not None
    binding = _binding(identity)
    checks = {
        "thread_id_non_null": bool(binding["id"]),
        "agent_path": binding["agent_path"] == agent_path
        and binding["source_agent_path"] == agent_path,
        "agent_role": binding["agent_role"] == expected_role,
        "model": identity.get("model") == expected_model,
        "reasoning_effort": identity.get("reasoning_effort") == expected_effort,
        "parent_thread_non_null": bool(binding["parent_thread_id"]),
        "cwd": bool(binding["cwd"])
        and _normalise_path(str(binding["cwd"])) == _normalise_path(expected_cwd),
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
    parser.add_argument("--expected-cwd", required=True)
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
