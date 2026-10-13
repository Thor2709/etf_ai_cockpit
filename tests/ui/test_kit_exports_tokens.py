from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.app import theme
from etf_cockpit.app.components import kit

SPEC_COMPONENTS = (
    "GlassCard",
    "Well",
    "DataTable",
    "Tag",
    "ScoreBar",
    "KpiTile",
    "StatTile",
    "Field",
    "Toggle",
    "Segmented",
    "Button",
    "ListRow",
    "GlossaryItem",
    "Headline",
    "VerdictRing",
    "GateCheck",
    "Pipeline",
    "KpiStrip",
    "FloatingPanel",
    "Badge",
    "Note",
    "EmptyState",
    "CardMenu",
    "SectionHeader",
    "Disclosure",
    "EvidenceTableSwitcher",
    "Stepper",
)


def test_all_28_spec_components_are_exported() -> None:
    assert kit.KIT_COMPONENT_COUNT == 28
    for name in SPEC_COMPONENTS:
        assert hasattr(kit, name), name
    assert callable(kit.Button.primary) and callable(kit.Button.secondary)
    assert {name.split(".")[0] for name in kit.KIT_COMPONENTS} == set(SPEC_COMPONENTS)


def test_legacy_helpers_still_importable_for_current_pages() -> None:
    for name in ("glass_panel", "card", "kpi_tile", "status_tag", "pill_group", "toggle", "cta_button",
                 "table_style", "cylinder_bar", "backdrop", "score_bar"):
        assert callable(getattr(kit, name))


def test_spec_colour_tokens_use_the_spec_values() -> None:
    assert (theme.INK, theme.INK2, theme.INK3, theme.ACC) == ("#f4f7fd", "#c3cde2", "#8e9ab4", "#9ad1ff")
    assert (theme.POS, theme.NEG, theme.POS2) == ("#2fbf80", "#ff7d6e", "#8cf5c6")
    assert (theme.CHART_POS, theme.CHART_NEG, theme.STRIP_NEG) == ("#6fcfa6", "#e8897c", "#f0aa9e")
    assert theme.SELECTED_BG == ("#47806b", "#2a5645", "#21463a")
    assert theme.SELECTED_INK == "#f0c2ae" and theme.SELECTED_UNDER == "#10261e"
    assert theme.CATEGORICAL == ("#9ad1ff", "#6fcfb0", "#c9b8e8", "#e6c9a8", "#a9b6cc")
    assert theme.RETURN_RAMP[0] == "#a8605c" and theme.RETURN_RAMP[-1] == "#5fb3b0"
    assert theme.BAR_POSITIVE == ("#8fdcbc", "#4fae88") and theme.BAR_GOLD == ("#f0d79a", "#c9a45e")


def test_radii_padding_and_typography_tokens() -> None:
    assert (theme.CARD_RADIUS, theme.RADIUS_DOCK, theme.RADIUS_TOPBAR, theme.RADIUS_FOOTER) == (30, 34, 25, 24)
    assert (theme.RADIUS_WELL, theme.RADIUS_KPI, theme.RADIUS_FIELD, theme.RADIUS_CTA) == (18, 16, 12, 13)
    assert (theme.RADIUS_SEGMENT_GROUP, theme.RADIUS_SEGMENT, theme.RADIUS_TRACK) == (14, 10, 5)
    assert theme.CARD_PADDING == (24, 24, 20) and theme.CARD_PADDING_QUIET == (16, 20, 12)
    assert theme.FONT_FAMILY == "Inter"


def test_rgba_helper_emits_flet_aarrggbb() -> None:
    assert theme.rgba(255, 255, 255, 0.07) == "#12ffffff"
    assert theme.rgba(0, 0, 0, 1) == "#ff000000"
    assert theme.rgba(9, 16, 32, 0.80) == "#cc091020"


@pytest.mark.parametrize(
    "relative",
    ["fonts/inter.woff2", "background/bg_3200.jpg", *[f"icons/{name}.png" for name in (
        "house", "globe", "telescope", "briefcase", "abacus", "alembic", "compass", "newspaper", "bulb")]],
)
def test_packaged_assets_exist(relative: str) -> None:
    path = theme.asset_path(relative)
    assert path.is_file() and path.stat().st_size > 1000


def test_pyinstaller_spec_ships_the_asset_folders() -> None:
    spec = (Path(__file__).resolve().parents[2] / "ETF_AI_Cockpit.spec").read_text(encoding="utf-8")
    for folder in ("icons", "fonts", "background"):
        assert f"assets/{folder}" in spec.replace("\\", "/")
