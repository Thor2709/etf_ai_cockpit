"""Analysis depth dialog (spec 5.5): depth profiles and evidence mode, opened from the footer rail."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.depth_selector import ProfileRunController, depth_details_view
from etf_cockpit.app.components.kit import Button, Segmented
from etf_cockpit.app.components.kit._base import sym, txt
from etf_cockpit.app.components.shell._glass import glass
from etf_cockpit.application.settings import ANALYSIS_DEPTHS
from etf_cockpit.application.interactive_profile_run import interactive_profile_binder

DIALOG_WIDTH = 560
_EVIDENCE_HINTS = {
    "compact": "Decision summary only.",
    "default": "Evidence and uncertainty beside each result.",
    "advanced": "Evidence plus diagnostics.",
}


def _deselect(control: ft.Container) -> None:
    """Show a Segmented with no active segment (no depth saved yet; never pretend one is chosen)."""
    row = control.content.content
    for segment in row.controls:
        segment.gradient = None
        segment.shadow = None
        segment.border = None
        segment.data = {**segment.data, "selected": False}
        if isinstance(segment.content, ft.Text) and segment.content.style is not None:
            segment.content.style.color = theme.INK2
            segment.content.style.shadow = None
    control.data["state"]["selected"] = None


def open_depth_dialog(page: ft.Page, state: object, *, on_changed: Callable[[], None]) -> ft.AlertDialog:
    """Build and show the dialog. ``on_changed`` refreshes the footer label after a depth or mode change."""
    controller = ProfileRunController(
        state,
        root=getattr(state, "settings_root", None),
        binder=interactive_profile_binder(lambda: getattr(state, "snapshot", None)),
    )
    current = getattr(state, "analysis_depth", None)
    details = ft.Column([], tight=True, scroll=ft.ScrollMode.AUTO, expand=True)
    status = txt("", 12.5, 400, theme.INK2, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
    dialog = ft.AlertDialog(
        modal=False,
        bgcolor="transparent",
        shadow_color="transparent",
        content_padding=0,
        inset_padding=ft.Padding(24, 24, 24, 24),
        barrier_color=theme.rgba(4, 8, 20, 0.55),
        shape=ft.RoundedRectangleBorder(radius=30),
    )

    def refresh_details(depth: str | None) -> None:
        if depth is None:
            details.controls = [txt("No analysis depth is saved yet. Choose Quick, Medium, High or Full.", 12.5, 400, theme.AMBER)]
            return
        view = depth_details_view(
            depth,
            root=getattr(state, "settings_root", None),
            run_controller=controller,
            on_update=lambda: dialog.update() if getattr(dialog, "page", None) else None,
        )
        details.controls = [view]

    def depth_chosen(label: str) -> None:
        depth = label.lower()
        state.set_analysis_depth(depth)  # type: ignore[attr-defined]
        status.value = f"{state.last_message}. {state.persist_analysis_depth(depth)}"  # type: ignore[attr-defined]
        refresh_details(depth)
        on_changed()
        page.update()

    labels = [item.capitalize() for item in ANALYSIS_DEPTHS]
    chosen = current.capitalize() if isinstance(current, str) and current.capitalize() in labels else None
    segmented = Segmented(labels, chosen or labels[0], on_change=depth_chosen, key="shell.depth-dialog.depth")
    if chosen is None:
        _deselect(segmented)
    refresh_details(chosen.lower() if chosen else None)

    mode_values = {theme.EVIDENCE_MODE_LABELS[value]: value for value in theme.EVIDENCE_MODES}

    def evidence_mode_changed(label: str) -> None:
        value = mode_values.get(label)
        if value in theme.EVIDENCE_MODES:
            state.set_evidence_mode(value)  # type: ignore[attr-defined]
            status.value = state.last_message  # type: ignore[attr-defined]
            hint.value = _EVIDENCE_HINTS[value]
            on_changed()
            page.update()

    current_mode = getattr(state, "evidence_mode", "default")
    hint = txt(_EVIDENCE_HINTS.get(current_mode, ""), 12.5, 400, theme.INK2)
    evidence_mode = Segmented(
        list(mode_values),
        theme.EVIDENCE_MODE_LABELS.get(current_mode, theme.EVIDENCE_MODE_LABELS["default"]),
        on_change=evidence_mode_changed,
        key="shell.evidence-mode",
    )

    from etf_cockpit.core.ui_preferences import missing_data_penalty

    def penalty_changed(event: ft.ControlEvent) -> None:
        setter = getattr(state, "set_missing_data_penalty", None)
        if callable(setter):
            setter(bool(event.control.value))
            status.value = state.last_message  # type: ignore[attr-defined]
            on_changed()
            refresh_page = getattr(page, "_shell_refresh", None)  # scores on the open page follow at once
            if callable(refresh_page):
                refresh_page()
            page.update()

    try:
        penalty_on = missing_data_penalty(getattr(state, "settings_root", None))
    except Exception:
        penalty_on = False
    penalty = ft.Checkbox(
        label="Penalise missing data (all pages)",
        tooltip="Pulls scores with thin evidence toward neutral 5: 5 + (score - 5) x coverage.",
        value=penalty_on,
        on_change=penalty_changed,
        key="shell.missing-data-penalty",
    )

    def close(_event: object | None = None) -> None:
        page.pop_dialog()

    body = ft.Column(
        [
            txt("Analysis depth", 18, 650, theme.INK, shadow=True),
            segmented,
            ft.Container(content=details, expand=True),
            txt("Evidence mode", 15, 600, theme.INK, shadow=True),
            evidence_mode,
            hint,
            txt("Scoring", 15, 600, theme.INK, shadow=True),
            penalty,
            status,
            ft.Row([ft.Container(expand=True), Button.secondary("Close", close, key="shell.depth-dialog.close")]),
        ],
        spacing=12,
        expand=True,
    )
    height = max(480, min(760, float(getattr(page, "height", 0) or 900) - 96))
    dialog.content = glass(body, radius=30, padding=sym(24, 24), width=DIALOG_WIDTH, height=height, key="shell.depth-dialog")
    page.show_dialog(dialog)
    return dialog
