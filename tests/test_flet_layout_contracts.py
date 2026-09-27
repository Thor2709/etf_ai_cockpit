"""Static Flet layout contracts.

A Row with wrap=True renders as a Flutter Wrap. An expanding child
(expand=True) inside a Wrap is a layout error, which a release build paints as
a grey box. This hid most of the Import/Export Centre (ISSUE-0036 browser
smoke). The contract is enforced across every app page.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "src" / "etf_cockpit" / "app"


def _is_true_keyword(call: ast.Call, name: str) -> bool:
    return any(
        keyword.arg == name and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in call.keywords
    )


def _expanding_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _is_true_keyword(node.value, "expand"):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return names


def _wrap_row_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    expanding = _expanding_names(tree)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "Row" and _is_true_keyword(node, "wrap")):
            continue
        children = node.args[0].elts if node.args and isinstance(node.args[0], ast.List) else []
        for child in children:
            if (isinstance(child, ast.Name) and child.id in expanding) or (
                isinstance(child, ast.Call) and _is_true_keyword(child, "expand")
            ):
                violations.append(f"{path.relative_to(APP_ROOT.parents[2]).as_posix()}:{child.lineno}")
    return violations


def test_no_expanding_control_inside_a_wrapping_row() -> None:
    violations = [item for path in sorted(APP_ROOT.rglob("*.py")) for item in _wrap_row_violations(path)]
    assert violations == []


def test_contract_detects_the_import_export_regression_shape(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import flet as ft\n"
        "field = ft.TextField(expand=True)\n"
        "row = ft.Row([field, ft.OutlinedButton('Go')], wrap=True)\n"
        "cards = ft.Row([ft.Container(expand=True)], wrap=True)\n",
        encoding="utf-8",
    )
    tree = ast.parse(sample.read_text(encoding="utf-8"))
    expanding = _expanding_names(tree)
    rows = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "Row" and _is_true_keyword(n, "wrap")]
    flagged = [
        child
        for row in rows
        for child in row.args[0].elts
        if (isinstance(child, ast.Name) and child.id in expanding) or (isinstance(child, ast.Call) and _is_true_keyword(child, "expand"))
    ]
    assert len(flagged) == 2
