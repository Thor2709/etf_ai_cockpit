from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.tables import accessible_table


def _relative_luminance(colour: str) -> float:
    channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    light = max(_relative_luminance(foreground), _relative_luminance(background))
    dark = min(_relative_luminance(foreground), _relative_luminance(background))
    return (light + 0.05) / (dark + 0.05)


def test_accessible_table_search_is_case_insensitive_literal_and_trimmed() -> None:
    frame = pd.DataFrame(
        {
            "instrument": ["Alpha [A]", "beta", "Gamma"],
            "score": [3, 1, 2],
        }
    )
    table = accessible_table(frame, table_id="scores")

    assert table.search("  aLpHa [  ")["instrument"].tolist() == ["Alpha [A]"]
    assert table.search("BETA")["instrument"].tolist() == ["beta"]


def test_accessible_table_sort_is_stable_and_excludes_structured_columns() -> None:
    frame = pd.DataFrame(
        {
            "instrument": ["first", "second", "third"],
            "rank": [2, 1, 2],
            "metadata": [{"source": "a"}, {"source": "b"}, {"source": "c"}],
        }
    )
    table = accessible_table(frame, table_id="scores")

    sorted_frame = table.sort("rank")
    assert sorted_frame["instrument"].tolist() == ["second", "first", "third"]
    assert table.sortable_columns == ("instrument", "rank")
    pd.testing.assert_frame_equal(table.sort("metadata"), frame)


def test_accessible_table_search_event_refreshes_rows_and_text_status() -> None:
    frame = pd.DataFrame({"instrument": ["Alpha", "Beta"], "score": [8, 6]})
    table = accessible_table(frame, table_id="scores")

    table.search_control.on_change(SimpleNamespace(data="beta"))
    assert len(table.control.rows) == 1
    assert table.status_control.value == "1 rows; status is shown as text"

    table.search_control.on_change(SimpleNamespace(data=""))
    assert len(table.control.rows) == 2
    assert table.status_control.value == "2 rows; status is shown as text"


def test_dark_palette_text_and_semantic_states_meet_wcag_aa_contrast() -> None:
    foregrounds = (
        theme.TEXT,
        theme.MUTED,
        theme.GREEN,
        theme.AMBER,
        theme.RED,
        theme.PURPLE,
        theme.CYAN,
        theme.BLUE_GREY,
    )
    assert all(_contrast_ratio(foreground, theme.BG) >= 4.5 for foreground in foregrounds)
