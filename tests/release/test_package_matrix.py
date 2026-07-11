from __future__ import annotations

from pathlib import Path

from scripts.dev_finish_check import select_gates


def test_package_matrix_declares_all_required_modes() -> None:
    from scripts.verify_issue import PACKAGE_MODES

    assert {
        "baseline",
        "optional_models_missing",
        "lm_studio_offline",
        "offline_cached_data",
        "empty_first_run",
        "migrated_existing_data",
        "long_unicode_path",
        "read_only_permission_failure",
        "display_125_150_percent",
        "source_package",
    } <= set(PACKAGE_MODES)


def test_runtime_changes_keep_the_build_gate_in_the_finish_plan() -> None:
    plan = select_gates({Path("src/etf_cockpit/app/router.py")}, ("ISSUE-0045",))

    assert "focused" in plan.gates
    assert "full" in plan.gates
    assert "build" in plan.gates
    assert "browser" in plan.gates


def test_finish_plan_is_deterministic_for_the_same_paths_and_issue() -> None:
    changed = {Path("scripts/verify_issue.py"), Path("tests/release/test_package_matrix.py")}

    first = select_gates(changed, ("ISSUE-0013",))
    second = select_gates(set(reversed(tuple(changed))), ("ISSUE-0013",))

    assert first == second
    assert first.commands == second.commands
