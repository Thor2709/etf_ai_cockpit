from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import select_focused_tests, validation_summary

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release-gate.yml"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(repo: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _select(repo: Path, capsys: pytest.CaptureFixture[str], base: str, head: str) -> tuple[int, list[str]]:
    capsys.readouterr()
    code = select_focused_tests.main(["--root", str(repo), "--base", base, "--head", head])
    return code, capsys.readouterr().out.split()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _write(
        tmp_path,
        {
            "src/etf_cockpit/__init__.py": "",
            "src/etf_cockpit/core/__init__.py": "",
            "src/etf_cockpit/core/math.py": "X = 1\n",
            "src/etf_cockpit/other.py": "Y = 1\n",
            "src/etf_cockpit/app/pages/settings.py": "Z = 1\n",
            "tests/test_plain.py": "def test_plain():\n    pass\n",
            "tests/test_import_plain.py": "import etf_cockpit.core.math\n",
            "tests/test_from_pkg.py": "from etf_cockpit.core import math\n",
            "tests/test_from_module.py": "from etf_cockpit.core.math import X\n",
            "tests/test_string_ref.py": "TARGET = 'etf_cockpit.core.math.X'\n",
            "tests/test_unrelated.py": "import etf_cockpit.other\n",
            "tests/test_settings.py": "from etf_cockpit.app.pages import settings\n",
            "tests/fixtures/test_ignored.py": "VALUE = 1\n",
            **{
                name: "def test_sweep():\n    pass\n"
                for name in select_focused_tests.UI_CONTRACT_SWEEP
            },
            "docs/note.md": "one\n",
        },
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _commit_change(repo: Path, files: dict[str, str]) -> tuple[str, str]:
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    return base, _git(repo, "rev-parse", "HEAD")


def test_selector_picks_changed_tests_and_skips_fixtures(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, head = _commit_change(
        repo,
        {"tests/test_plain.py": "def test_plain():\n    assert True\n", "tests/fixtures/test_ignored.py": "VALUE = 2\n"},
    )

    assert _select(repo, capsys, base, head) == (0, ["tests/test_plain.py"])


def test_selector_picks_every_importer_form_of_a_changed_module(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, head = _commit_change(repo, {"src/etf_cockpit/core/math.py": "X = 2\n"})

    code, selected = _select(repo, capsys, base, head)

    assert code == 0
    assert selected == [
        "tests/test_from_module.py",
        "tests/test_from_pkg.py",
        "tests/test_import_plain.py",
        "tests/test_string_ref.py",
    ]


def test_selector_adds_ui_sweep_for_app_changes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, head = _commit_change(repo, {"src/etf_cockpit/app/pages/settings.py": "Z = 2\n"})

    code, selected = _select(repo, capsys, base, head)

    assert code == 0
    assert set(selected) == {"tests/test_settings.py", *select_focused_tests.UI_CONTRACT_SWEEP}
    assert "tests/test_unrelated.py" not in selected


def test_selector_is_empty_for_docs_only_and_fails_closed_on_bad_input(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, head = _commit_change(repo, {"docs/note.md": "two\n"})

    assert _select(repo, capsys, base, head) == (0, [])
    capsys.readouterr()
    assert select_focused_tests.main(["--root", str(repo), "--base", "main", "--head", head]) == 2
    assert "unavailable" in capsys.readouterr().err
    code, _ = _select(repo, capsys, "0" * 40, head)
    assert code == 2


def test_selector_fails_closed_when_ui_sweep_file_is_missing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / select_focused_tests.UI_CONTRACT_SWEEP[0]).unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "drop sweep file")
    base, head = _commit_change(repo, {"src/etf_cockpit/app/pages/settings.py": "Z = 3\n"})

    capsys.readouterr()
    code = select_focused_tests.main(["--root", str(repo), "--base", base, "--head", head])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "unavailable" in captured.err


def test_workflow_defines_focused_tests_job_and_summary_requires_it() -> None:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    job = jobs["focused-tests"]

    assert job["needs"] == ["classifier"]
    assert job["if"] == (
        "github.event_name == 'pull_request' && needs.classifier.outputs.package_gate_required != 'true'"
    )
    assert job["runs-on"] == "ubuntu-latest"
    names = [step["name"] for step in job["steps"]]
    assert names.index("Install pinned release environment") < names.index("Select and run focused tests")
    run = next(step for step in job["steps"] if step["name"] == "Select and run focused tests")["run"]
    assert "scripts/select_focused_tests.py" in run
    assert "-n auto" in run
    assert "--junitxml=artifacts/focused/junit-focused.xml" in run
    upload = next(step for step in job["steps"] if step["name"] == "Upload focused test evidence")
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "junit-focused-${{ github.sha }}"
    assert "focused-tests" in jobs["validation-summary"]["needs"]
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '--job-result "focused=$FOCUSED_RESULT"' in text
    assert "focused_tests_failures(" in text


def test_summary_fails_on_focused_failure_only_when_package_gate_not_required() -> None:
    fail = validation_summary.focused_tests_failures
    for result in ("failure", "cancelled", "skipped", None):
        assert fail(package_gate_required=False, focused=result)
    assert not fail(package_gate_required=False, focused="success")
    assert not fail(package_gate_required=False, focused="not-applicable")
    for result in ("skipped", "failure", "success"):
        assert not fail(package_gate_required=True, focused=result)


def test_terminal_summary_validation_rejects_missing_or_failed_focused_result_without_package_gate() -> None:
    from tests.test_issue_0179_validation_summary import _summary

    ok = _summary("O")
    assert validation_summary.validate_summary(ok) == []
    for value in ("failure", "skipped"):
        broken = _summary("O")
        broken["job_results"]["focused"] = value
        assert "terminal summary focused-tests result is inconsistent" in validation_summary.validate_summary(broken)
    missing = _summary("O")
    del missing["job_results"]["focused"]
    assert validation_summary.validate_summary(missing)
    gated = _summary("H")
    gated["job_results"]["focused"] = "skipped"
    assert validation_summary.validate_summary(gated) == []
