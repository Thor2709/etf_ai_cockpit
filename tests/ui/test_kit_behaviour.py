from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import (
    Badge,
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    EvidenceTable,
    EvidenceTableSwitcher,
    Field,
    GateCheck,
    GlassCard,
    KpiStrip,
    KpiTile,
    ListRow,
    Pipeline,
    ScoreBar,
    Segmented,
    StatTile,
    Stepper,
    TableColumn,
    Tag,
    Toggle,
    VerdictRing,
    Well,
    score_colors,
)


def walk(control: object):
    yield control
    for name in ("controls", "rows", "cells", "columns", "items"):
        for child in getattr(control, name, None) or ():
            yield from walk(child)
    for name in ("content", "label", "body"):
        child = getattr(control, name, None)
        if child is not None and not isinstance(child, str):
            yield from walk(child)


def texts(control: object) -> list[str]:
    found: list[str] = []
    for node in walk(control):
        value = getattr(node, "value", None)
        if isinstance(value, str):
            found.append(value)
    return found


def find_kit(control: object, kind: str) -> list[ft.Control]:
    return [n for n in walk(control) if isinstance(getattr(n, "data", None), dict) and n.data.get("kit") == kind]


# --- surfaces -----------------------------------------------------------------------------------------------


def test_glass_card_header_note_insight_and_body() -> None:
    card = GlassCard("Scores", "0-100", insight="Higher is stronger.", body=Well(ft.Text("chart")))
    body = texts(card)
    assert body[:3] == ["Scores", "0-100", "Higher is stronger."]
    assert find_kit(card, "Well") and card.data["kit"] == "GlassCard"


def test_glass_card_quiet_uses_tighter_padding_and_reduce_effects_drops_blur() -> None:
    normal = GlassCard("a", reduce_effects=False)
    quiet = GlassCard("a", quiet=True, reduce_effects=True)
    panel = lambda holder: holder.content.controls[0]  # noqa: E731
    assert panel(normal).padding.top == 24 and panel(normal).padding.left == 24 and panel(normal).padding.bottom == 20
    assert panel(quiet).padding.top == 16 and panel(quiet).padding.left == 20 and panel(quiet).padding.bottom == 12
    assert panel(normal).blur == theme.GLASS_PANEL_BLUR and panel(quiet).blur is None
    assert panel(quiet).bgcolor == theme.GLASS_FILL_SOLID


def test_empty_state_has_title_reason_and_optional_action() -> None:
    state = EmptyState("No rows", "x.csv has no rows.", Button.secondary("Load"))
    assert {"No rows", "x.csv has no rows.", "Load"} <= set(texts(state))


def test_disclosure_toggles_visibility_and_label() -> None:
    disclosure = Disclosure("paths", "C:/x.csv")
    caption = texts(disclosure)[0]
    well = find_kit(disclosure, "Well")[0]
    assert caption == "Show paths \u25be" and well.visible is False
    disclosure.controls[0].on_click(None)
    assert well.visible is True and texts(disclosure)[0] == "Hide paths \u25b4"


# --- controls -----------------------------------------------------------------------------------------------


def test_segmented_click_and_arrow_keys_change_selection_once() -> None:
    seen: list[str] = []
    segmented = Segmented(["All", "Primary", "Secondary"], "All", on_change=seen.append)
    listener = segmented.content
    segments = listener.content.controls
    segments[1].on_click(None)
    assert seen == ["Primary"] and segments[1].data["selected"] and not segments[0].data["selected"]
    listener.on_key_down(SimpleNamespace(key="Arrow Right"))
    listener.on_key_down(SimpleNamespace(key="Arrow Right"))  # already last: no change
    listener.on_key_down(SimpleNamespace(key="Arrow Left"))
    assert seen == ["Primary", "Secondary", "Primary"]
    assert segments[1].gradient is not None and segments[0].gradient is None


def test_segmented_requires_exactly_one_selected_item() -> None:
    with pytest.raises(ValueError):
        Segmented(["a", "b"], "c")


def test_toggle_flips_and_reports() -> None:
    seen: list[bool] = []
    toggle = Toggle(False, on_change=seen.append)
    assert (toggle.width, toggle.height) == (40, 22) and toggle.data["on"] is False
    toggle.on_click(None)
    toggle.on_click(None)
    assert seen == [True, False] and toggle.data["on"] is False


def test_button_metrics_press_and_disabled_state() -> None:
    clicks: list[object] = []
    primary = Button.primary("Run", clicks.append)
    secondary = Button.secondary("Export")
    assert primary.height == 36 and primary.border_radius == 13 and primary.data["kind"] == "primary"
    assert secondary.data["kind"] == "secondary"
    primary.on_tap_down(None)
    assert primary.offset.y > 0
    primary.on_click("evt")
    assert clicks == ["evt"] and primary.offset.y == 0
    disabled = Button.primary("Run", clicks.append, disabled=True, disabled_reason="No data loaded")
    assert disabled.opacity == 0.45 and disabled.on_click is None and disabled.tooltip == "No data loaded"
    assert disabled.shadow is None


def test_field_label_is_uppercase_and_input_height_is_40_or_96() -> None:
    plain = Field("Instrument", ft.Text("VWCE"))
    area = Field("Notes", ft.Text("n"), multiline=True)
    assert texts(plain)[0] == "INSTRUMENT"
    assert plain.controls[1].height == 40 and area.controls[1].height == 96
    assert find_kit(Field("Horizon", options=["1m", "3m"], value="3m"), "Field")
    with pytest.raises(ValueError):
        Field("Empty")


# --- data components ----------------------------------------------------------------------------------------


def test_tag_kinds_and_invalid_kind() -> None:
    tag = Tag("Fresh", "ok")
    assert tag.border_radius == theme.RADIUS_PILL and tag.content.style.color == "#8fdcbc"
    with pytest.raises(ValueError):
        Tag("x", "info")


def test_score_bar_colour_rule_and_missing_value() -> None:
    assert score_colors(8.2) == (theme.ACC, theme.CHART_POS)
    assert score_colors(5.4) == ("#c9a45e", "#e6c27a")
    assert score_colors(4.7) == ("#c8625a", "#e6c27a")
    assert texts(ScoreBar(8.24)) == ["8.2"]
    assert texts(ScoreBar(None)) == ["\u2014"]
    weight = ScoreBar(42, maximum=100)
    assert texts(weight) == ["42"] and weight.data["maximum"] == 100


def test_data_table_header_sort_selection_and_missing_cells() -> None:
    sorted_calls: list[tuple[str, bool]] = []
    columns = [TableColumn("n", "Name", flex=2), TableColumn("v", "Value", numeric=True)]
    rows = [{"n": ("VWCE", "Vanguard"), "v": "72"}, {"n": "IWDA", "v": None}]
    table = DataTable(columns, rows, sort_key="v", descending=True, on_sort=lambda k, d: sorted_calls.append((k, d)),
                      selected_index=0, on_select=lambda i: None)
    found = texts(table)
    assert "NAME" in found and "\u25bc" in found and "\u2014" in found and "Vanguard" in found
    header = table.controls[0].controls[0].content
    header.controls[1].on_click(None)  # active column flips direction
    assert sorted_calls == [("v", False)]
    row_nodes = find_kit(table, "DataTableRow")
    assert [r.data["selected"] for r in row_nodes] == [True, False]
    assert isinstance(table.controls[1], ft.ListView) and table.controls[1].item_extent == 44


def test_data_table_without_rows_is_an_explicit_empty_state() -> None:
    result = DataTable([TableColumn("a", "A")], [], empty_title="No rows", empty_reason="file.csv has no rows.")
    assert result.data["kit"] == "EmptyState" and "file.csv has no rows." in texts(result)


def test_evidence_table_switcher_empty_state_and_switch() -> None:
    cols = [TableColumn("a", "A")]
    switcher = EvidenceTableSwitcher(
        [
            EvidenceTable("Prices", cols, [{"a": "1"}], "prices.csv", "data/prices.csv"),
            EvidenceTable("Holdings", cols, [], "holdings.csv", "data/holdings.csv"),
        ]
    )
    assert switcher.data["note_control"].value == "1 row"
    segmented = find_kit(switcher, "Segmented")[0]
    segmented.content.content.controls[1].on_click(None)
    assert switcher.data["note_control"].value == "0 rows"
    assert "holdings.csv has no rows. This is an explicit unavailable state, not zero." in texts(switcher)


def test_list_row_last_has_no_hairline_and_tag_is_optional() -> None:
    first = ListRow("ok", "Title", "Sub", ("OK", "ok"))
    last = ListRow("warn", "Title", last=True)
    assert len(first.controls) == 2 and len(last.controls) == 1
    assert first.data["dot"] == theme.DOT_COLOURS["ok"] and find_kit(first, "Tag")


def test_badge_hidden_at_zero_and_caps_large_counts() -> None:
    assert Badge(0).visible is False and Badge(3).visible is True
    assert texts(Badge(150)) == ["99+"]


# --- tiles and flows ----------------------------------------------------------------------------------------


def test_kpi_tile_unavailable_shows_reason_and_never_zero() -> None:
    tile = KpiTile("Drawdown", None, "needs 252 prices")
    assert "Unavailable" in texts(tile) and "needs 252 prices" in texts(tile) and "0" not in texts(tile)
    assert KpiTile("Authority", "locked", "execution off", tone="neg").content.controls[1].style.color == theme.NEG
    with pytest.raises(ValueError):
        KpiTile("a", "1", tone="bad")


def test_stat_tile_sparkline_only_with_a_series() -> None:
    assert StatTile("1Y", "+12%", [1, 2, 3], "pos").data["points"] == 3
    assert len(StatTile("1Y", None).content.controls) == 1


def test_kpi_strip_requires_four_items() -> None:
    items = [("a", "1", "+1", "pos")] * 4
    assert KpiStrip("Portfolio", "EUR 1", "As of today", items).data["kit"] == "KpiStrip"
    with pytest.raises(ValueError):
        KpiStrip("p", "h", "s", items[:3])


def test_verdict_ring_none_shows_dash_and_draws_only_the_track() -> None:
    assert "\u2014" in texts(VerdictRing(None)) and VerdictRing(None).data["score"] is None
    ring = VerdictRing(250)
    assert ring.data["score"] == 100 and "100" in texts(ring)
    canvas = [c for c in ring.controls if hasattr(c, "shapes")][0]
    assert len(canvas.shapes) == 2 and len(VerdictRing(None).controls[1].shapes) == 1


def test_gate_check_states_and_engraved_separator() -> None:
    assert len(GateCheck(True, "A", "r").controls) == 3 and len(GateCheck(False, "A", last=True).controls) == 1
    assert GateCheck(None, "A").data["passed"] is None
    assert texts(GateCheck(False, "Drawdown", "Above limit"))[:2] == ["Drawdown", "Above limit"]


def test_pipeline_last_step_is_quail_green() -> None:
    row = Pipeline(["Ingest", "Score", "Review"])
    steps = [c for c in row.controls if getattr(c, "width", None) == 93]
    assert len(steps) == 3 and steps[0].height == 51
    assert steps[-1].content.controls[0].style.color == theme.SELECTED_INK
    assert steps[0].content.controls[0].style.color == theme.INK


def test_stepper_states_and_validation() -> None:
    stepper = Stepper([("Load", "Done", "done"), ("Run", "", "running"), ("Fail", "x", "failed"), ("Wait", "", "pending")])
    assert stepper.data["states"] == ["done", "running", "failed", "pending"]
    with pytest.raises(ValueError):
        Stepper([("a", "", "weird")])


# --- text protection rules (owner 2026-10-07) ---------------------------------------------------------------


def test_long_texts_truncate_with_ellipsis_and_tooltip() -> None:
    long = "A very long instrument name that cannot possibly fit in a narrow tile " * 3
    tile = KpiTile(long, long, long)
    label, value, sub = tile.content.controls
    for text in (label, value, sub):
        assert text.overflow == ft.TextOverflow.ELLIPSIS and text.max_lines == 1 and text.tooltip
    row = ListRow("ok", long, long)
    title = row.controls[0].content.controls[1].controls[0]
    assert title.overflow == ft.TextOverflow.ELLIPSIS and title.tooltip == long


def test_verdict_ring_centre_stays_inside_the_arc_band() -> None:
    for size in (96, 128, 160):
        ring = VerdictRing(100, size=size)
        thickness = 24.0 * size / 128
        centre = ring.controls[2].content
        assert centre.width <= size - 2 * thickness
        value = centre.content.controls[0]
        assert value.style.size <= 38 * size / 128
        assert value.style.size * 1.75 <= centre.width - 8 + 1e-6


def test_spacing_uses_the_scale_and_nested_radii_follow_outer_minus_padding() -> None:
    scale = {0, 4, 8, 12, 16, 20, 24, 28}
    assert set(theme.CARD_PADDING) <= scale and set(theme.CARD_PADDING_QUIET) <= scale
    toggle = Toggle(True)
    assert toggle.border_radius - toggle.padding.left == 9  # knob radius
    segmented = Segmented(["a", "b"], "a")
    assert segmented.border_radius - segmented.padding == theme.RADIUS_SEGMENT  # 14 - 4
