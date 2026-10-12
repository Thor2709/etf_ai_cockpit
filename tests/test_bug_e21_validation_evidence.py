"""Bughunt E21 (#936): validation evidence must not overstate what ran."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

import conftest
from scripts import release_gate, select_focused_tests, validate_app, validation_summary

HEAD = "b" * 40
BASE = "a" * 40


# --- E21-N001: skipped tests are not executed tests --------------------------------------------
def _report(path: Path, cases: list[tuple[str, str, str]]) -> Path:
    body = "".join(
        f'<testcase classname="{classname}" name="{name}">{inner}</testcase>' for classname, name, inner in cases
    )
    path.write_text(f'<testsuites><testsuite name="pytest">{body}</testsuite></testsuites>', encoding="utf-8")
    return path


def test_skipped_test_without_documented_reason_is_not_execution(tmp_path: Path) -> None:
    nodes = {"tests/test_x.py::test_a", "tests/test_y.py::test_b"}
    run = lambda inner: release_gate._junit_execution_problems(  # noqa: E731
        (_report(tmp_path / "r.xml", [("tests.test_x", "test_a", ""), ("tests.test_y", "test_b", inner)]),), nodes
    )

    assert run("") == []  # control: both passed
    problems = run('<skipped type="pytest.skip" message="flaky on CI" />')
    assert any("skipped without a documented reason: tests.test_y::test_b" in problem for problem in problems)
    assert run('<skipped type="pytest.skip" message="directory symlinks are unavailable on this platform" />') == []
    assert run('<skipped type="pytest.xfail" message="xfail: known gap" />') == []  # xfail counted separately


def test_protected_gate_tests_must_execute_even_with_an_allowed_reason(tmp_path: Path) -> None:
    nodes = {"tests/test_release_gate.py::test_a"}
    report = _report(
        tmp_path / "r.xml",
        [("tests.test_release_gate", "test_a", '<skipped type="pytest.skip" message="requires Windows only" />')],
    )

    problems = release_gate._junit_execution_problems((report,), nodes)

    assert any("protected test(s) skipped: tests.test_release_gate::test_a" in problem for problem in problems)


def test_outcomes_are_counted_separately(tmp_path: Path) -> None:
    report = _report(
        tmp_path / "r.xml",
        [
            ("t", "ok", ""),
            ("t", "bad", '<failure message="x" />'),
            ("t", "err", '<error message="x" />'),
            ("t", "skip", '<skipped type="pytest.skip" message="s" />'),
            ("t", "xf", '<skipped type="pytest.xfail" message="xfail" />'),
        ],
    )

    assert release_gate._junit_outcome_counts((report,)) == {
        "passed": 1, "failed": 1, "error": 1, "skipped": 1, "xfail": 1,
    }


# --- E21-N002/N003: one canonical report per shard, shard coverage proven ----------------------
def _artifacts(
    tmp_path: Path,
    *,
    sha: str = HEAD,
    shards: tuple[int, ...] = (1, 2, 3),
    platforms: tuple[str, ...] = ("windows", "linux"),
    overlap: bool = False,
    phases: bool = True,
) -> Path:
    artifacts = tmp_path / "validation-evidence"
    classifier = artifacts / "validation-classifier-head" / "classifier.json"
    classifier.parent.mkdir(parents=True)
    classifier.write_text(
        json.dumps({"tier": "H", "package_gate_required": True, "reasons": ["r"], "paths": [{"path": "a.py", "tier": "H", "reason": "r"}], "evidence_reuse": {}}),
        encoding="utf-8",
    )
    for platform in platforms:
        for shard in shards:
            directory = artifacts / f"release-gate-{sha}-{platform}-s{shard}"
            directory.mkdir(parents=True)
            names = [f"t{shard}a", f"t{shard}b"]
            cases = "".join(f'<testcase classname="tests.m{shard}" name="{name}" />' for name in names)
            if overlap:  # the same test executed in every shard
                names.append("shared")
                cases += '<testcase classname="tests.shared" name="shared" />'
            merged = f'<testsuites><testsuite tests="{len(names)}">{cases}</testsuite></testsuites>'
            (directory / "junit-full.xml").write_text(merged, encoding="utf-8")
            if phases:  # the merged report's inputs are uploaded too; they must not be added again
                (directory / "junit-parallel.xml").write_text(merged, encoding="utf-8")
                (directory / "junit-serial.xml").write_text(
                    '<testsuites><testsuite tests="0" /></testsuites>', encoding="utf-8"
                )
            evidence = {"test_shard": f"{shard}/3", "collection_node_counts": {"full": len(names)}}
            (directory / "full_tests.log").write_text(
                validation_summary.EVIDENCE_PREFIX + json.dumps(evidence) + "\n", encoding="utf-8"
            )
    return artifacts


def _collect(artifacts: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(validation_summary, "_tree_identity", lambda *_args: "d" * 64)
    return validation_summary.collect_summary(
        tmp_path,
        artifacts,
        base=BASE,
        head=HEAD,
        job_results={"classifier": "success", "preflight": "success", "supply_chain": "success", "release": "success"},
    )


def test_junit_totals_count_each_test_once_not_merged_plus_phase_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _collect(_artifacts(tmp_path), tmp_path, monkeypatch)

    assert report["platform_junit"] == {"windows": 6, "linux": 6}  # 3 shards x 2 tests, not doubled
    assert validation_summary.validate_summary(report) == []


def test_terminal_summary_requires_all_shards_exact_sha_and_no_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one_shard = _collect(_artifacts(tmp_path / "a", shards=(1,)), tmp_path, monkeypatch)
    assert any("shards are incomplete" in error for error in validation_summary.validate_summary(one_shard))

    stale = _collect(_artifacts(tmp_path / "b", sha="c" * 40), tmp_path, monkeypatch)
    assert any("exact head SHA" in error for error in validation_summary.validate_summary(stale))

    duplicated = _collect(_artifacts(tmp_path / "c", overlap=True), tmp_path, monkeypatch)
    assert any("duplicate test(s)" in error for error in validation_summary.validate_summary(duplicated))

    good = _collect(_artifacts(tmp_path / "d"), tmp_path, monkeypatch)
    forged = copy.deepcopy(good)
    forged["platform_shards"]["linux"]["collected"] += 1  # collection larger than what executed
    assert any("does not equal the collection" in error for error in validation_summary.validate_summary(forged))
    missing = copy.deepcopy(good)
    missing.pop("platform_shards")
    assert "terminal summary shard coverage is required" in validation_summary.validate_summary(missing)
    assert validation_summary.validate_summary(good) == []  # control


# --- E21-N004 / E021: --changed and the focused selector cover impacted tests ------------------
def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _write(repo: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _write(
        tmp_path,
        {
            "src/etf_cockpit/__init__.py": "",
            "src/etf_cockpit/core.py": "X = 1\n",
            "src/etf_cockpit/lonely.py": "Y = 1\n",
            "tests/conftest.py": "",
            "tests/test_core.py": "import etf_cockpit.core\n",
            "tests/test_other.py": "def test_o():\n    pass\n",
            "tests/test_ui.py": "CONFIG = 'configs/ui_acceptance.yaml'  # ui_acceptance\n",
            "configs/ui_acceptance.yaml": "a: 1\n",
            "docs/note.md": "one\n",
            **{name: "def test_s():\n    pass\n" for name in select_focused_tests.UI_CONTRACT_SWEEP},
        },
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _changed(repo: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> str:
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    monkeypatch.setenv("ETF_COCKPIT_VALIDATION_BASE_SHA", base)
    monkeypatch.setenv("ETF_COCKPIT_VALIDATION_HEAD_SHA", _git(repo, "rev-parse", "HEAD"))
    return base


def test_changed_mode_selects_tests_importing_a_changed_source_module(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _changed(repo, monkeypatch, {"src/etf_cockpit/core.py": "X = 2\n"})

    assert validate_app._changed_test_paths(repo) == ["tests/test_core.py"]


def test_changed_mode_fails_when_production_changed_but_no_test_is_selected(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _changed(repo, monkeypatch, {"src/etf_cockpit/lonely.py": "Y = 2\n"})
    monkeypatch.setattr(release_gate, "resolve_xdist_workers", lambda: 0)

    checks = validate_app._checks_for_mode(repo, "changed", {})
    scope = next(check for check in checks if check.name == "changed_scope")
    completed = subprocess.run([*scope.command], capture_output=True, text=True, check=False)

    assert completed.returncode != 0 and "lonely.py" in completed.stderr


def test_changed_mode_docs_only_change_still_passes_scope(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _changed(repo, monkeypatch, {"docs/note.md": "two\n"})

    checks = validate_app._checks_for_mode(repo, "changed", {})
    scope = next(check for check in checks if check.name == "changed_scope")

    assert subprocess.run([*scope.command], capture_output=True, text=True, check=False).returncode == 0


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (["tests/conftest.py"], {"tests/test_core.py", "tests/test_other.py", "tests/test_ui.py"}),
        (["configs/ui_acceptance.yaml"], {"tests/test_ui.py", *select_focused_tests.UI_CONTRACT_SWEEP}),
    ],
)
def test_selector_covers_conftest_and_ui_acceptance_changes(repo: Path, changed: list[str], expected: set[str]) -> None:
    assert expected <= set(select_focused_tests.select_tests(repo, changed))


def test_selector_expands_a_large_selection_to_the_whole_suite(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(select_focused_tests, "LARGE_SELECTION", 2)

    selected = select_focused_tests.select_tests(repo, ["tests/test_core.py", "tests/test_other.py", "tests/test_ui.py"])

    assert set(selected) == set(select_focused_tests._all_test_files(repo))
    assert "tests/test_core.py" in selected and len(selected) > 3  # includes the sweep files


def test_seed_key_changes_with_non_python_src_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src" / "etf_cockpit").mkdir(parents=True)
    (tmp_path / "configs").mkdir()
    resource = tmp_path / "src" / "etf_cockpit" / "defaults.yaml"
    resource.write_text("a: 1\n", encoding="utf-8")
    monkeypatch.setattr(conftest, "ROOT", tmp_path)
    monkeypatch.setattr(conftest, "_tracked_files", lambda _dirs: [])
    first = conftest._seed_key()

    resource.write_text("a: 2\n", encoding="utf-8")

    assert conftest._seed_key() != first
    assert sys.version  # key stays version-scoped
