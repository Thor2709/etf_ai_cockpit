from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import dev_finish_check, smoke_app
from scripts.dev_finish_check import FinishGateError, build_cli_plan, run_finish_gates, select_gates


def test_parser_change_requires_parser_export_build_and_browser_gates() -> None:
    plan = select_gates({Path("src/etf_cockpit/parsers/esef_ixbrl.py")}, {"UPDATEV2-0013"})

    assert {"focused", "full", "fixtures", "export", "build", "browser", "computer_use"} <= set(plan.gates)


def test_runtime_change_cannot_use_no_build() -> None:
    with pytest.raises(FinishGateError, match="--no-build"):
        build_cli_plan(changed=["src/etf_cockpit/app/state.py"], no_build=True)


def test_document_only_change_can_skip_build() -> None:
    plan = build_cli_plan(changed=["README.md"], no_build=True)

    assert "build" not in plan.gates
    assert plan.no_build is True


def test_json_evidence_redacts_command_output_and_uses_argument_arrays(tmp_path, monkeypatch) -> None:
    plan = select_gates({Path("README.md")}, set())
    captured: list[object] = []

    def fake_run(command, **kwargs):
        captured.append(command)
        return SimpleNamespace(returncode=0, stdout="token=super-secret", stderr="api_key: super-secret")

    monkeypatch.setattr(dev_finish_check.subprocess, "run", fake_run)

    report = run_finish_gates(plan, tmp_path)
    report_path = tmp_path / "finish-report.json"
    dev_finish_check.write_json_report(report, report_path)
    evidence = report_path.read_text(encoding="utf-8")

    assert captured
    assert all(isinstance(command, list) for command in captured)
    assert "super-secret" not in evidence
    assert "[REDACTED]" in evidence
    assert json.loads(evidence)["passed"] is True


def test_unverified_browser_and_computer_use_gates_keep_report_pending(tmp_path, monkeypatch) -> None:
    plan = select_gates({Path("scripts/build_windows.bat")}, {"UPDATEV2-0029"})
    monkeypatch.setattr(
        dev_finish_check.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    report = run_finish_gates(plan, tmp_path)

    statuses = {result.gate: result.status for result in report.results}
    assert statuses["browser"] == "pending_external_verification"
    assert statuses["computer_use"] == "pending_external_verification"
    assert report.passed is False


def test_finish_check_executes_by_default_and_plan_only_is_explicit(tmp_path):
    changed = tmp_path / "changed.txt"
    changed.write_text("README.md\n", encoding="utf-8")

    default_args = dev_finish_check.parse_args(
        ["--changed-paths-file", str(changed), "--json-report", str(tmp_path / "report.json")]
    )
    planning_args = dev_finish_check.parse_args(
        [
            "--changed-paths-file",
            str(changed),
            "--json-report",
            str(tmp_path / "plan.json"),
            "--plan-only",
        ]
    )

    assert default_args.plan_only is False
    assert planning_args.plan_only is True


def test_smoke_declares_all_required_modes() -> None:
    parser = smoke_app.build_parser()
    mode_action = next(action for action in parser._actions if action.dest == "mode")

    assert set(mode_action.choices) == {"source", "native", "portable-native", "launcher", "first-run", "offline"}
    assert smoke_app.parse_args(["--mode", "offline"]).mode == "offline"


def test_smoke_validates_the_configured_flet_title(tmp_path, monkeypatch) -> None:
    title_source = tmp_path / "src" / "etf_cockpit" / "app" / "flet_app.py"
    title_source.parent.mkdir(parents=True)
    title_source.write_text('page.title = "ETF AI Evidence Cockpit"\n', encoding="utf-8")
    monkeypatch.setattr(smoke_app, "ROOT", tmp_path)

    smoke_app.verify_expected_title()


def test_smoke_rejects_a_process_from_an_unexpected_path(tmp_path) -> None:
    expected = tmp_path / "expected.exe"
    unexpected = tmp_path / "unexpected.exe"
    process = SimpleNamespace(args=[str(unexpected)])

    with pytest.raises(RuntimeError, match="unexpected executable"):
        smoke_app.verify_process_path(process, expected)
