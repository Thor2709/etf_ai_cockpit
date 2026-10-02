from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import flet as ft
import pytest

from etf_cockpit.app import theme
from etf_cockpit.app.components import kit


def _walk(control: ft.Control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        if isinstance(child, ft.Control):
            yield from _walk(child)


@pytest.mark.parametrize(
    ("control", "key", "label"),
    [
        (kit.glass_panel(ft.Text("Body"), key="glass", label="Glass panel"), "glass", "Glass panel"),
        (kit.card("Card title", ft.Text("Body"), key="card"), "card", "Card title"),
        (kit.kpi_tile("Return", "12%", key="kpi"), "kpi", "Return"),
        (kit.status_tag("Ready", key="status"), "status", "Ready"),
        (kit.score_bar(72, key="score"), "score", "Score: 72 of 100"),
        (kit.pill_group(["One", "Two"], "One", key="pills", label="Period"), "pills", "Period"),
        (kit.toggle("Include fees", True, key="toggle"), "toggle", "Include fees"),
        (kit.cta_button("Review", key="cta", label="Review evidence"), "cta", "Review evidence"),
        (kit.table_style(ft.Text("Table"), key="table", label="Evidence table"), "table", "Evidence table"),
        (
            kit.cylinder_bar([("Europe", 2.5)], axis_label="Exposure", unit="%", maximum=10, key="bars", label="Exposure chart"),
            "bars",
            "Exposure chart",
        ),
    ],
)
def test_kit_factories_return_accessible_flet_controls(control: ft.Control, key: str, label: str) -> None:
    assert isinstance(control, ft.Control)
    assert control.key == key
    assert control.tooltip == label


def test_status_tag_keeps_its_text_label_visible() -> None:
    tag = kit.status_tag("Needs review", "w", key="review")

    text = next(control for control in _walk(tag) if isinstance(control, ft.Text))
    assert text.value == "Needs review"


def test_pill_group_marks_one_selected_option_with_quail_tokens() -> None:
    group = kit.pill_group(["1M", "3M", "1Y"], "3M", key="period", label="Period")
    items = group.content.controls
    selected = [item for item in items if item.data == "selected"]

    assert len(selected) == 1
    assert selected[0].gradient.colors == list(theme.QUAIL_SELECTED_COLORS)
    selected_text = next(control for control in _walk(selected[0]) if isinstance(control, ft.Text))
    assert selected_text.color == theme.QUAIL_SELECTED_INK
    assert sum(
        next(control for control in _walk(item) if isinstance(control, ft.Text)).color == theme.QUAIL_SELECTED_INK
        for item in items
    ) == 1


def _assigned_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_theme_keeps_base_exports_and_adds_named_ui_tokens() -> None:
    base_source = subprocess.check_output(
        ["git", "show", "HEAD:src/etf_cockpit/app/theme.py"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
    )
    current_source = Path(theme.__file__).read_text(encoding="utf-8")

    assert _assigned_names(base_source) <= _assigned_names(current_source)
    assert {
        "GLASS_PANEL_GRADIENT",
        "RECESSED_WELL_GRADIENT",
        "RAISED_CONTROL_GRADIENT",
        "HAIRLINE_BORDER",
        "CARD_RADIUS",
        "INNER_RADIUS",
        "TEXT_SHADOW",
        "FOOTER_RAIL_BACKGROUND",
    } <= _assigned_names(current_source)
    assert theme.GREEN == "#6fcfa6"
    assert theme.RED == "#e8897c"
    assert theme.AMBER == "#e6c27a"
    assert theme.PURPLE == "#a99bf0"


def test_backdrop_uses_deterministic_gradient_when_image_is_missing(tmp_path: Path) -> None:
    rendered = kit.backdrop(ft.Text("Page"), user_data_dir=tmp_path)

    assert isinstance(rendered, ft.Stack)
    assert isinstance(rendered.controls[0], ft.Container)
    assert rendered.controls[0].gradient.colors == ["#0b1424", "#0c2231", "#0a312f"]


def test_backdrop_uses_and_softens_local_image(tmp_path: Path) -> None:
    image_path = tmp_path / "ui" / "backdrop.jpg"
    image_path.parent.mkdir()
    image_path.write_bytes(b"local image fixture")

    rendered = kit.backdrop(ft.Text("Page"), user_data_dir=tmp_path)

    assert isinstance(rendered.controls[0], ft.Image)
    assert rendered.controls[0].src == str(image_path)
    assert rendered.controls[1].blur == 4
