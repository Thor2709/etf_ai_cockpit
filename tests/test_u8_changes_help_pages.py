from __future__ import annotations

from datetime import date, datetime, timezone

import flet as ft

from etf_cockpit.app.components.glass_pages import page_panel
from etf_cockpit.app.formatting import format_count, format_timestamp


def test_format_timestamp_is_british_and_utc_labelled() -> None:
    assert format_timestamp("2026-10-02T14:05:09Z") == "2 Oct 2026, 14:05 UTC"
    assert format_timestamp(datetime(2026, 1, 9, 8, 0, tzinfo=timezone.utc)) == "9 Jan 2026, 08:00 UTC"
    assert format_timestamp(date(2026, 3, 4)) == "4 Mar 2026"


def test_format_timestamp_never_invents_or_hides_values() -> None:
    assert format_timestamp(None) == "N/A"
    assert format_timestamp("", unavailable="running") == "running"
    assert format_timestamp("not a date") == "not a date"
    assert format_timestamp("2026-10-02T14:05:00+02:00").endswith("+0200")


def test_format_count_groups_thousands_and_keeps_missing_unavailable() -> None:
    assert format_count(1234567) == "1,234,567"
    assert format_count(None) == "N/A"
    assert format_count("x", unavailable="duration unavailable") == "duration unavailable"
    assert format_count(float("nan")) == "N/A"


def test_page_panel_uses_keyed_glass_surface_with_accessible_label() -> None:
    panel = page_panel("demo")
    box = panel(ft.Column([ft.Column([ft.Text("Import and Export Centre")]), ft.Text("body")]), padding=10)
    assert box.key.startswith("demo.panel.import-and-export-centre-")
    assert box.tooltip == "Import and Export Centre"
    assert box.border_radius is not None and box.gradient is not None
    other = panel(ft.Text("x"))
    assert other.key != box.key
