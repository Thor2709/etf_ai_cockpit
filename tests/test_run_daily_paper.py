from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from etf_cockpit.application import daily_paper
from etf_cockpit.core.file_guard import PersistentFileGuard
from etf_cockpit.portfolio.paper_bots import _load_config


_NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
_SESSION = date(2026, 11, 2)
_SNAPSHOT = "b" * 64
_FULL_ORDER = [
    "capture", "decision_session", "score_run", "readiness", "feature_vintage", "paper_gate", "challengers",
    "paper_bots", "paper_bot_execution", "ai_account", "refresh", "forecast", "rescore", "publish",
]


def _bots(status: str = "available", *records: dict, snapshot: str | None = _SNAPSHOT) -> SimpleNamespace:
    return SimpleNamespace(status=status, appended=len(records), reason=None, records=records, candidate_snapshot=snapshot)


def _wire_pipeline(
    monkeypatch, events: list[str], *, bots: SimpleNamespace | None = None, passed: bool = True,
    new_session: bool = True, paper_gate: str | None = None, recorder_calls: list[dict] | None = None,
) -> None:
    session = SimpleNamespace(snapshot=SimpleNamespace())
    report = SimpleNamespace(passed=passed, format_text=lambda: "DATA READINESS -> FAIL")
    monkeypatch.setattr(daily_paper, "_capture", lambda _root, _clock: events.append("capture") or {"status": "recorded"})
    monkeypatch.setattr(daily_paper, "_decision_session", lambda _root, _clock: events.append("decision_session") or (_SESSION, new_session))
    monkeypatch.setattr(daily_paper, "_score_run", lambda _root, _day, _at: events.append("score_run") or {"status": "available"})
    monkeypatch.setattr(daily_paper, "_validate_readiness", lambda _root, _day: events.append("readiness") or (report, _SNAPSHOT, "run-1"))
    monkeypatch.setattr(daily_paper, "record_feature_observations", lambda *_args, **_kwargs: events.append("feature_vintage"))
    monkeypatch.setattr(daily_paper, "_paper_gate", lambda _root: events.append("paper_gate") or paper_gate)
    monkeypatch.setattr(
        daily_paper, "build_challenger_engines",
        lambda _root, _cutoff: events.append("challengers") or ({}, {"gbdt_rank_63": {"status": "insufficient_evidence", "preflight": ["x"]}}),
    )
    monkeypatch.setattr(daily_paper, "_refresh", lambda _root: events.append("refresh") or (session, "prices refreshed"))
    monkeypatch.setattr(daily_paper, "_forecast", lambda _session: events.append("forecast") or "forecasts refreshed")
    monkeypatch.setattr(daily_paper, "_rescore", lambda _session: events.append("rescore") or "rescored")
    monkeypatch.setattr(daily_paper, "_publish", lambda _session: events.append("publish"))
    monkeypatch.setattr(
        daily_paper,
        "run_paper_bots",
        lambda *_args, **kwargs: events.append("paper_bots") or (recorder_calls if recorder_calls is not None else []).append(kwargs)
        or (bots or _bots()),
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


def test_readiness_fail_skips_the_paper_stages_and_still_refreshes(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events, passed=False)

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 1
    assert result.stage == "readiness"
    assert events == [
        "capture", "decision_session", "score_run", "readiness", "feature_vintage", "refresh", "forecast", "rescore", "publish",
    ]
    paper_root = tmp_path / "data" / "operations" / "paper"
    assert not paper_root.exists()


def test_pass_runs_capture_score_gate_and_bots_before_the_refresh(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    calls: list[dict] = []
    _wire_pipeline(monkeypatch, events, recorder_calls=calls)

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 0 and result.stage == "complete"
    assert events == _FULL_ORDER
    assert calls[0]["decision_session"] == _SESSION and calls[0]["snapshot_hash"] == _SNAPSHOT  # the readiness run's id
    payload = json.loads(result.to_json())
    assert payload["readiness"]["snapshot_id"] == _SNAPSHOT
    assert payload["capture"]["status"] == "recorded" and payload["paper_enabled"] is True
    assert payload["challengers"]["gbdt_rank_63"]["preflight"] == ["x"]
    assert payload["paper_bot_execution"]["ledger_price_basis"] == "as_traded_units_gross_cash_dividends"
    assert payload["paper_bot_execution"]["dividend_policy"].startswith("gross cash")
    assert payload["execution_allowed"] is False


@pytest.mark.parametrize(("gate", "new_session", "stage"), [
    ("paper_disabled", True, "paper_disabled"), (None, False, "no_new_session"),
])
def test_paper_disabled_or_no_new_session_skips_the_paper_stages_and_exits_zero(monkeypatch, tmp_path: Path, gate, new_session, stage) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events, paper_gate=gate, new_session=new_session)

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 0 and result.stage == stage
    assert "paper_bots" not in events and "ai_account" not in events
    assert events[-4:] == ["refresh", "forecast", "rescore", "publish"]
    if stage == "paper_disabled":
        assert result.details["paper_enabled"] is False and "readiness" in events
    else:
        assert "score_run" not in events and "readiness" not in events


def _record(family: str, status: str, reason: str | None = None) -> dict:
    return {"bot_family": family, "bot_id": f"{family}-id", "status": status, "reason": reason}


def test_partial_is_accepted_only_for_challengers_without_a_new_trade(monkeypatch, tmp_path: Path) -> None:
    accepted = _bots("partial", _record("B1", "available"), _record("B1-r", "unavailable", "NO_NEW_TRADE: ranker scores gbdt_rank_63 are not available"))
    events: list[str] = []
    _wire_pipeline(monkeypatch, events, bots=accepted)
    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)
    assert result.exit_code == 0, result.details
    assert [item["bot_family"] for item in result.details["paper_bots"]["bots"]] == ["B1", "B1-r"]

    rejected = _bots("partial", _record("B0", "available"), _record("B1", "unavailable", "stale"))
    events = []
    _wire_pipeline(monkeypatch, events, bots=rejected)
    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)
    assert result.exit_code == 1 and result.stage == "paper_bots"
    assert "partial not accepted: B1" in result.details["error"]
    assert "paper_bot_execution" not in events and events[-4:] == ["refresh", "forecast", "rescore", "publish"]


def test_capture_is_stamped_after_the_page_is_in_hand_and_a_failure_is_only_logged(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.data import sp500_capture

    events: list[object] = []
    monkeypatch.setattr(sp500_capture, "_fetch", lambda _url: events.append("fetch") or b"page")

    def capture(_root, *, now, fetch):
        events.append(("capture", now, fetch("url")))
        return sp500_capture.Sp500Capture("recorded", "2026-11-03", "t", 503, 499, 4, 503)

    monkeypatch.setattr(sp500_capture, "capture_sp500", capture)
    clock = lambda: events.append("clock") or _NOW  # noqa: E731
    assert daily_paper._capture(tmp_path, clock)["status"] == "recorded"
    assert events == ["fetch", "clock", ("capture", _NOW, b"page")]

    def failing(_root, *, now, fetch):
        raise sp500_capture.Sp500CaptureError("capture failed: guard")

    monkeypatch.setattr(sp500_capture, "capture_sp500", failing)
    assert daily_paper._capture(tmp_path, clock) == {"status": "failed", "reason": "capture failed: guard"}


def test_a_new_session_is_one_later_than_the_latest_forward_run() -> None:
    import pandas as pd

    saturday = datetime(2026, 10, 31, 21, 32, tzinfo=timezone.utc)
    friday = date(2026, 10, 30)
    history = pd.DataFrame({"as_of_date": [friday.isoformat()], "provenance": ["forward_nightly"], "run_completed_at": [saturday.isoformat()]})
    assert daily_paper._is_new_session(pd.DataFrame(), friday)
    assert not daily_paper._is_new_session(history, friday)  # S <= the latest forward session: no_new_session (SDD C8)
    assert not daily_paper._is_new_session(history, date(2026, 10, 29))
    assert daily_paper._is_new_session(history, date(2026, 11, 2))


def test_an_unexpected_error_in_the_paper_stages_blocks_the_run_and_still_refreshes(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events)
    monkeypatch.setattr(daily_paper, "_check_recorder", lambda *_args: (_ for _ in ()).throw(KeyError("bot_family")))

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 1 and result.stage == "paper_stages"
    assert "KeyError" in result.details["error"]
    assert events[-4:] == ["refresh", "forecast", "rescore", "publish"]


def test_a_forecast_failure_is_a_stage_failure_after_the_committed_refresh(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events)
    monkeypatch.setattr(daily_paper, "_forecast", lambda _session: (_ for _ in ()).throw(RuntimeError("baseline failed")))

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 1 and result.stage == "forecast"
    assert "baseline failed" in result.details["error"] and result.details["refresh"] == "prices refreshed"
    assert events[-3:] == ["refresh", "rescore", "publish"]


def test_a_failed_refresh_keeps_the_full_error_text(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events)
    symbols = ", ".join(f"SYM{index}" for index in range(400)) + ", LASTSYM"
    monkeypatch.setattr(daily_paper, "_refresh", lambda _root: (_ for _ in ()).throw(RuntimeError(f"no data: {symbols}")))

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.stage == "refresh" and len(symbols) > 1200
    assert result.details["error"].endswith("LASTSYM")


def test_the_forecast_stage_runs_the_request_the_scores_read(tmp_path: Path) -> None:
    calls: list[dict] = []

    class Service:
        last_operation_succeeded = True

        def __init__(self, _config) -> None:
            pass

        def run_yfinance_forecasts(self, **kwargs) -> str:
            calls.append(kwargs)
            return "Configured ETF forecasts refreshed"

    models = SimpleNamespace(shadow_optional_models=False)
    guard = object()
    session = SimpleNamespace(
        snapshot=SimpleNamespace(config=SimpleNamespace(models=models)), data_service_factory=Service, activity_publication=guard,
    )

    assert daily_paper._forecast(session) == "Configured ETF forecasts refreshed"
    models.shadow_optional_models = True  # owner opt-in: the scores read optional-model forecasts
    assert daily_paper._forecast(session) == "Configured ETF forecasts refreshed"
    assert [call["live_optional_models"] for call in calls] == [False, True]
    assert calls[0] == {"include_candidates": False, "horizons": [60], "live_optional_models": False, "publish_guard": guard}

    Service.last_operation_succeeded = False
    with pytest.raises(RuntimeError, match="Configured ETF forecasts refreshed"):
        daily_paper._forecast(session)


def _real_gate(monkeypatch, events: list[str], controls: dict) -> None:
    paper_gate = daily_paper._paper_gate
    _wire_pipeline(monkeypatch, events)
    monkeypatch.setattr(daily_paper, "_paper_gate", paper_gate)
    settings = SimpleNamespace(controls=SimpleNamespace(paper=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(daily_paper, "load_settings_bundle", lambda _root: settings)
    monkeypatch.setattr(daily_paper, "load_paper_controls_status", lambda _root, _account: controls)


def test_an_active_kill_switch_skips_the_recorder_and_exits_zero(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    _real_gate(monkeypatch, events, {"status": "available", "kill_switch_active": True})

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 0 and result.stage == "paper_kill_switch_active"
    assert result.details["paper_enabled"] is True  # paper is enabled; the kill switch is not "disabled"
    assert "paper_bots" not in events and events[-4:] == ["refresh", "forecast", "rescore", "publish"]


def test_unreadable_paper_controls_block_the_run_and_still_refresh(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    _real_gate(monkeypatch, events, {"status": "unavailable", "kill_switch_active": None})

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 1 and result.stage == "paper_gate"
    assert "paper_bots" not in events and events[-4:] == ["refresh", "forecast", "rescore", "publish"]


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


@pytest.mark.parametrize("opening_cash", [1, Decimal("1"), Decimal("40000.0000000000000001")])
def test_application_refuses_nondefault_cash_without_writes(monkeypatch, tmp_path: Path, opening_cash) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events)
    root = tmp_path / "runtime"

    with pytest.raises(ValueError, match="opening cash of exactly EUR 40,000"):
        daily_paper.run_daily_paper(root, initial_cash_eur=opening_cash, now=_NOW)

    assert events == []
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


def test_application_refuses_another_account_without_writes(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events)
    root = tmp_path / "runtime"

    with pytest.raises(ValueError, match="AI account id 'ai-paper'"):
        daily_paper.run_daily_paper(root, ai_account="another-account", now=_NOW)

    assert events == []
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_overrides_and_default_opens_fixed_account(monkeypatch, tmp_path: Path, capsys) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_daily_paper.py"
    main = runpy.run_path(str(script))["main"]
    events: list[str] = []
    open_account = daily_paper._open_ai_account
    _wire_pipeline(monkeypatch, events)
    monkeypatch.setattr(daily_paper, "_open_ai_account", open_account)
    # Stub only the CLI root prerequisite; no configuration file is created or edited.
    is_file = Path.is_file
    config_path = tmp_path / "configs" / "universe.yaml"
    monkeypatch.setattr(Path, "is_file", lambda path: path == config_path or is_file(path))
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(tmp_path))

    for option, value in [("--ai-account", "another-account"), ("--initial-cash-eur", "1")]:
        with pytest.raises(SystemExit) as exc_info:
            main(["--root", str(tmp_path), option, value])
        assert exc_info.value.code == 2
        assert f"unrecognized arguments: {option} {value}" in capsys.readouterr().err
        assert events == []
        assert list(tmp_path.iterdir()) == []

    assert main(["--root", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ai_account"]["account_id"] == "ai-paper"
    assert payload["ai_account"]["cash"] == 40_000
    assert payload["ai_account"]["monthly_contribution_eur"] == 0
    assert payload["execution_allowed"] is False
    # Exact Decimal cash is accepted and an earlier opening remains idempotent.
    assert daily_paper.run_daily_paper(tmp_path, initial_cash_eur=Decimal("40000"), now=_NOW).exit_code == 0
    ledger_path = tmp_path / "data" / "operations" / "paper" / "accounts" / "ai-paper" / "ledger.jsonl"
    records = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["event_type"] == "account_opened"
    assert Decimal(records[0]["payload"]["initial_cash"]) == Decimal("40000")


def test_second_concurrent_driver_is_refused_by_shared_writer_lock(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(daily_paper, "_refresh", lambda _root: (_ for _ in ()).throw(AssertionError("must not refresh")))
    lock_path = tmp_path / "data" / ".headless-writer.lock"

    with PersistentFileGuard(lock_path, timeout_seconds=0.0):
        result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 1
    assert result.stage == "lock"


@pytest.mark.parametrize("candidate", [None, "d" * 64])
def test_decisions_bound_to_another_run_than_the_readiness_pass_are_rejected(monkeypatch, tmp_path: Path, candidate) -> None:
    events: list[str] = []
    _wire_pipeline(monkeypatch, events, bots=_bots(snapshot=candidate))

    result = daily_paper.run_daily_paper(tmp_path, now=_NOW)

    assert result.exit_code == 1
    assert result.stage == "paper_bots"
    assert "recorded snapshot differs from H" in result.details["error"]
    assert "paper_bot_execution" not in events and events[-4:] == ["refresh", "forecast", "rescore", "publish"]


def test_paper_bot_config_remains_exactly_four_families() -> None:
    config_path = Path(__file__).resolve().parents[1] / "configs" / "paper_bots_v1.yaml"
    _raw, config = _load_config(config_path)

    assert {bot["family_id"] for bot in config["bots"]} == {"B0", "B1", "B2", "B3"}
    assert len(config["bots"]) == 4


def test_cli_refresh_flags_reach_refresh_and_defaults_keep_one_argument_call(monkeypatch, tmp_path: Path, capsys) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_daily_paper.py"
    main = runpy.run_path(str(script))["main"]
    events: list[str] = []
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    _wire_pipeline(monkeypatch, events)
    session = SimpleNamespace(snapshot=SimpleNamespace())
    monkeypatch.setattr(
        daily_paper,
        "_refresh",
        lambda *args, **kwargs: calls.append((args, kwargs)) or (session, "prices refreshed"),
    )
    config_path = tmp_path / "configs" / "universe.yaml"
    is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: path == config_path or is_file(path))
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(tmp_path))

    assert main(["--root", str(tmp_path), "--dry-run"]) == 0
    capsys.readouterr()
    assert calls[-1] == ((Path(tmp_path).resolve(),), {})

    assert main([
        "--root", str(tmp_path), "--dry-run", "--incremental-prices", "--skip-fundamentals"
    ]) == 0
    capsys.readouterr()
    assert calls[-1] == (
        (Path(tmp_path).resolve(),),
        {"incremental": True, "include_fundamentals": False},
    )


def test_cli_refresh_fx_flag_reaches_refresh(monkeypatch, tmp_path: Path, capsys) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_daily_paper.py"
    main = runpy.run_path(str(script))["main"]
    events: list[str] = []
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    _wire_pipeline(monkeypatch, events)
    session = SimpleNamespace(snapshot=SimpleNamespace())
    monkeypatch.setattr(
        daily_paper,
        "_refresh",
        lambda *args, **kwargs: calls.append((args, kwargs)) or (session, "prices refreshed"),
    )
    config_path = tmp_path / "configs" / "universe.yaml"
    is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: path == config_path or is_file(path))
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(tmp_path))

    assert main(["--root", str(tmp_path), "--dry-run", "--refresh-fx"]) == 0
    capsys.readouterr()

    assert calls == [
        (
            (Path(tmp_path).resolve(),),
            {"incremental": False, "include_fundamentals": True, "include_fx": True},
        )
    ]


@pytest.mark.parametrize("include_fundamentals", [False, True])
def test_nightly_refresh_skips_reference_data_only_with_fundamentals(monkeypatch, tmp_path: Path, include_fundamentals) -> None:
    calls: list[dict[str, object]] = []
    service = SimpleNamespace(refresh_yfinance_data=lambda **kwargs: calls.append(kwargs) or "ok")
    session = SimpleNamespace(
        snapshot=SimpleNamespace(config=None),
        data_service_factory=lambda _config: service,
        activity_publication=None,
        refresh_snapshot=lambda: None,
    )
    monkeypatch.setattr(daily_paper, "_new_session", lambda _root: session)

    daily_paper._refresh(tmp_path, incremental=True, include_fundamentals=include_fundamentals)

    assert calls[0]["include_reference_data"] is include_fundamentals
