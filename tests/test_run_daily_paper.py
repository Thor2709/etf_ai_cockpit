from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from etf_cockpit.application import daily_paper
from etf_cockpit.core.file_guard import PersistentFileGuard
from etf_cockpit.portfolio.paper_bots import _load_config


_NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
_SNAPSHOT_ID = {"scoreboard_sha256": "a" * 64, "score_snapshot_hash": "b" * 64}


def _wire_pipeline(monkeypatch, events: list[str], *, snapshot_id: dict[str, str] | None = None) -> None:
    identity = dict(_SNAPSHOT_ID if snapshot_id is None else snapshot_id)
    session = SimpleNamespace(snapshot=SimpleNamespace())
    monkeypatch.setattr(daily_paper, "_refresh", lambda _root: events.append("refresh") or (session, "prices refreshed"))
    monkeypatch.setattr(daily_paper, "_rescore", lambda _session: events.append("rescore") or "rescored")
    monkeypatch.setattr(
        daily_paper,
        "_validate_readiness",
        lambda _root, _snapshot, _now: events.append("readiness") or (date(2026, 11, 2), identity["score_snapshot_hash"]),
    )
    monkeypatch.setattr(daily_paper, "_publish", lambda _session: events.append("publish"))
    monkeypatch.setattr(daily_paper, "_published_snapshot_id", lambda _root: dict(identity))
    monkeypatch.setattr(
        daily_paper,
        "run_paper_bots",
        lambda *_args, **_kwargs: events.append("paper_bots") or SimpleNamespace(status="available", appended=0, reason=None),
    )
    monkeypatch.setattr(
        daily_paper,
        "run_paper_bot_execution",
        lambda *_args, **_kwargs: events.append("paper_bot_execution") or SimpleNamespace(status="available", appended=0, reason=None),
    )
    monkeypatch.setattr(
        daily_paper,
        "_open_ai_account",
        lambda *_args, **_kwargs: events.append("ai_account")
        or SimpleNamespace(account_id="ai-paper", status="open", base_currency="EUR", cash=40_000, event_count=1),
    )


def test_readiness_fail_stops_before_bot_or_ledger_writes(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events)

    def fail_gate(_root, _snapshot, _now):
        events.append("readiness")
        raise daily_paper._failure("readiness", "DATA READINESS -> FAIL")

    monkeypatch.setattr(daily_paper, "_validate_readiness", fail_gate)
    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 1
    assert result.stage == "readiness"
    assert events == ["refresh", "rescore", "readiness"]
    paper_root = tmp_path / "data" / "operations" / "paper"
    assert not paper_root.exists()


def test_pass_runs_refresh_rescore_gate_publish_then_bots(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events)

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 0
    assert events == [
        "refresh",
        "rescore",
        "readiness",
        "publish",
        "paper_bots",
        "paper_bot_execution",
        "ai_account",
    ]
    payload = json.loads(result.to_json())
    assert payload["readiness"]["snapshot_id"] == "b" * 64
    assert payload["execution_allowed"] is False


def test_ai_account_is_idempotent_and_does_not_add_cash_on_second_run(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    open_account = daily_paper._open_ai_account
    _wire_pipeline(monkeypatch, events)
    monkeypatch.setattr(daily_paper, "_open_ai_account", open_account)

    first = daily_paper.run_daily_paper(tmp_path, now=_NOW)
    second = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    ledger_path = tmp_path / "data" / "operations" / "paper" / "accounts" / "ai-paper" / "ledger.jsonl"
    records = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert first.exit_code == second.exit_code == 0
    assert first.details["ai_account"]["cash"] == second.details["ai_account"]["cash"] == 40_000
    assert len(records) == 1
    assert records[0]["event_type"] == "account_opened"
    assert records[0]["payload"]["initial_cash"] == "40000.0"
    assert records[0]["payload"]["base_currency"] == "EUR"


def test_second_concurrent_driver_is_refused_by_shared_writer_lock(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(daily_paper, "_refresh", lambda _root: (_ for _ in ()).throw(AssertionError("must not refresh")))
    lock_path = tmp_path / "data" / ".headless-writer.lock"

    with PersistentFileGuard(lock_path, timeout_seconds=0.0):
        result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 1
    assert result.stage == "lock"


def test_pass_bound_to_older_published_snapshot_is_rejected(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    old_identity = {"scoreboard_sha256": "c" * 64, "score_snapshot_hash": "d" * 64}
    _wire_pipeline(monkeypatch, events, snapshot_id=old_identity)
    monkeypatch.setattr(
        daily_paper,
        "_published_snapshot_id",
        lambda _root: {"scoreboard_sha256": "e" * 64, "score_snapshot_hash": "f" * 64},
    )

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 1
    assert result.stage == "readiness"
    assert "older published snapshot id" in result.details["error"]
    assert events == ["refresh", "rescore", "readiness", "publish"]


def test_paper_bot_config_remains_exactly_four_families() -> None:
    config_path = Path(__file__).resolve().parents[1] / "configs" / "paper_bots_v1.yaml"
    _raw, config = _load_config(config_path)

    assert {bot["family_id"] for bot in config["bots"]} == {"B0", "B1", "B2", "B3"}
    assert len(config["bots"]) == 4
