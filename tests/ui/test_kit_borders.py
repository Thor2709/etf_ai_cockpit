"""Token test (spec 9.3 / 9.10): Flutter paints a non-uniform ft.Border as a square box and ignores border_radius.

Only uniform borders (all four sides identical) or none may exist under src/etf_cockpit/app; separators are
1px Containers. ``LEGACY_NON_UNIFORM`` lists the files that still contain old violations. The shell wave must
delete router.py's and flet_compat.border_only; the test then forces the entries off the list.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "src" / "etf_cockpit" / "app"
SIDES = ("left", "top", "right", "bottom")
ONE_SIDED_HELPERS = {"border_only", "only", "symmetric", "vertical", "horizontal"}

# Files allowed to violate until the shell/page waves replace them (relative to APP, posix style).
LEGACY_NON_UNIFORM = {
    "router.py": "dock/top bar built in the old shell; replaced by the shell wave",
    "components/flet_compat.py": "border_only helper; delete when router.py no longer imports it",
}


def _violations(path: Path) -> list[int]:
    found: list[int] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        owner = ast.unparse(node.func.value) if isinstance(node.func, ast.Attribute) else ""
        if name == "Border" or (name in ONE_SIDED_HELPERS and ("border" in owner.lower() or name == "border_only")):
            if name != "Border":
                found.append(node.lineno)
                continue
            sides = {keyword.arg: ast.dump(keyword.value) for keyword in node.keywords if keyword.arg in SIDES}
            if len(sides) != 4 or len(set(sides.values())) != 1:
                found.append(node.lineno)
    return found


def _app_files() -> list[Path]:
    return sorted(path for path in APP.rglob("*.py"))


def test_no_non_uniform_border_anywhere_in_the_app() -> None:
    offenders = {}
    for path in _app_files():
        relative = path.relative_to(APP).as_posix()
        lines = _violations(path)
        if lines and relative not in LEGACY_NON_UNIFORM:
            offenders[relative] = lines
    assert not offenders, f"non-uniform ft.Border (use border_all / 1px Container separators): {offenders}"


def test_legacy_allow_list_only_shrinks() -> None:
    assert set(LEGACY_NON_UNIFORM) == {"router.py", "components/flet_compat.py"}
    stale = [name for name in LEGACY_NON_UNIFORM if not _violations(APP / name)]
    assert not stale, f"remove fixed files from LEGACY_NON_UNIFORM: {stale}"


def test_the_kit_package_has_no_one_sided_borders() -> None:
    kit_files = sorted((APP / "components" / "kit").glob("*.py"))
    assert len(kit_files) >= 6
    assert all(not _violations(path) for path in kit_files)


def test_detector_flags_known_bad_patterns(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text(
        "import flet as ft\n"
        "a = ft.Border(left=ft.BorderSide(1, 'x'), top=ft.BorderSide(1, 'y'), right=ft.BorderSide(1, 'x'),"
        " bottom=ft.BorderSide(1, 'x'))\n"
        "b = ft.border.only(bottom=ft.BorderSide(1, 'x'))\n"
        "c = border_only(bottom=1)\n"
        "d = ft.Border(left=s, top=s, right=s, bottom=s)\n",
        encoding="utf-8",
    )
    assert _violations(bad) == [2, 3, 4]
