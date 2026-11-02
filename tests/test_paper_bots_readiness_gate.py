from __future__ import annotations

from datetime import date, datetime, timezone
import importlib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.application import data_readiness
from etf_cockpit.portfolio import paper_bots_execution as execution
from etf_cockpit.portfolio.paper_bots import run_paper_bots
from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay


def test_replay_blocked_by_readiness_writes_nothing(tmp_path: Path) -> None:
    cutoff = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    history = pd.DataFrame([{"as_of_date": "2026-10-14"}])

    result = run_historical_replay(cutoff, root=tmp_path, history=history, now=cutoff)

    assert result.status == "unavailable"
    assert "DATA READINESS" in (result.reason or "")
    assert "FAIL" in (result.reason or "")
    assert "failing checks/families:" in (result.reason or "")
    assert list(tmp_path.rglob("*")) == []


def test_forward_run_blocked_by_readiness_writes_nothing(tmp_path: Path) -> None:
    now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)

    result = run_paper_bots(now, root=tmp_path, now=now)

    assert result.status == "unavailable"
    assert "DATA READINESS" in (result.reason or "")
    assert "failing checks/families:" in (result.reason or "")
    assert list(tmp_path.rglob("*")) == []


def test_pipeline_record_and_fill_are_blocked_before_pipeline_writes(monkeypatch, tmp_path: Path, capsys) -> None:
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    cli = importlib.import_module("run_pipeline_cli")
    root = tmp_path
    (root / "configs").mkdir()
    (root / "configs" / "universe.yaml").write_text("universe: []\n", encoding="utf-8")
    (root / "data").mkdir()
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(root))
    calls: list[str] = []

    result = cli.run_cli(lambda: calls.append("pipeline") or 0, record_paper_bots=True)

    assert result == 1
    assert calls == []
    assert "DATA READINESS" in capsys.readouterr().out
    assert {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()} == {
        "configs/universe.yaml"
    }


def test_replay_cli_selects_exact_benchmark_dates_and_refuses_mismatch(monkeypatch, tmp_path: Path, capsys) -> None:
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    cli = importlib.import_module("replay_paper_bots_from_backfill")
    from etf_cockpit.application import score_backfill
    from etf_cockpit.data import replay_membership, score_history_backfill
    from etf_cockpit.core import paths
    from etf_cockpit.portfolio import paper_bots_replay

    monkeypatch.setattr(paths, "ROOT", tmp_path)
    days = [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]
    history = pd.DataFrame(
        [
            {"as_of_date": day.isoformat(), "run_id": f"run-{day.day}", "instrument_id": instrument}
            for day in days
            for instrument in ("AAA", "BBB")
        ]
    )
    book = SimpleNamespace(sessions=[*days, date(2026, 10, 8)])
    captured: list[pd.DataFrame] = []
    monkeypatch.setattr(score_history_backfill, "load_backfill_score_history", lambda _root: history)
    monkeypatch.setattr(score_history_backfill, "load_backfill_eligibility", lambda _root: pd.DataFrame())
    monkeypatch.setattr(score_backfill, "run_label", lambda _frame: "fixture")
    monkeypatch.setattr(replay_membership, "unverified_instruments", lambda _frame: [])
    monkeypatch.setattr(execution.PriceBook, "from_root", classmethod(lambda cls, _root: book))

    def stop_after_selection(*args, **kwargs):
        captured.append(kwargs["history"])
        return SimpleNamespace(
            status="unavailable", label="conditional historical simulation", as_of=None, appended=0,
            reason="captured", warnings=(), survivorship_unverified=False,
        )

    monkeypatch.setattr(paper_bots_replay, "run_historical_replay", stop_after_selection)
    common = ["--root", str(tmp_path), "--start", days[0].isoformat(), "--end", days[-1].isoformat(), "--as-of", "2026-10-10"]

    for count in (1, 3):
        assert cli.main([*common, "--decision-dates", str(count)]) == 1
        selected = pd.to_datetime(captured[-1]["as_of_date"]).dt.date
        assert set(selected) == set(days[:count])
        assert len(set(selected)) == count
        assert book.sessions[-1] == date(2026, 10, 8)  # the next-session fill tail remains available

    calls_before_mismatch = len(captured)
    assert cli.main([*common, "--decision-dates", "4"]) == 1
    output = capsys.readouterr().out
    assert "requested 4 distinct benchmark score dates, found 3" in output
    assert "no writes were made" in output
    assert len(captured) == calls_before_mismatch


def test_passing_readiness_preserves_normal_replay_behavior(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.portfolio import paper_bots
    from etf_cockpit.portfolio.paper_bots_report import REPLAY_LABEL
    from etf_cockpit.data.replay_membership import ListingHistory
    from tests._pit_listing import listed_since
    from tests.test_paper_bots import _rows
    from tests.test_paper_bots_execution import _allow, _book, _exec_config, _history_with_columns, _records

    def passing_evaluation(_inputs, start, end, thresholds, *, every=None):
        checks = {name: data_readiness.CheckResult(True, "passed") for name in data_readiness.CHECKS}
        day_reports = (data_readiness.DateReport(start.isoformat(), checks),)
        intervals = {
            "decision_dates": data_readiness.CheckResult(True, "passed"),
            "benchmark_sessions": data_readiness.CheckResult(True, "passed"),
        }
        return data_readiness.ReadinessReport(
            start.isoformat(), end.isoformat(), thresholds.policy_version,
            thresholds.decision_cadence_sessions if every is None else every, day_reports, intervals,
        )

    monkeypatch.setattr(data_readiness, "evaluate_readiness", passing_evaluation)
    monkeypatch.setattr(paper_bots, "project_classification_score_frame", lambda frame, *, root: frame)
    listing = listed_since(("AAA", "BBB", "BAD", "VWCE"))
    monkeypatch.setattr(ListingHistory, "from_root", classmethod(lambda cls, _root: listing))
    october = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    november = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    cutoff = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    history = pd.DataFrame(_history_with_columns(_rows(october) + _rows(november, run_id="score-run-nov", snapshot="b")))
    book = _book(known_at=cutoff)
    replay_track = execution.replay_track(tmp_path, _exec_config())
    _allow(tmp_path, replay_track)

    result = run_historical_replay(cutoff, root=tmp_path, history=history, price_book=book, now=cutoff)

    assert result.label == REPLAY_LABEL
    assert result.status in {"available", "partial"}, (result.reason, result.warnings)
    assert result.appended > 0
    records = _records(tmp_path, replay_track)
    assert records
    assert all(item["track"] == "replay" and item["label"] == REPLAY_LABEL for item in records)
    assert {item["session"] for item in records if item.get("session")}  # next-session fills remain active
