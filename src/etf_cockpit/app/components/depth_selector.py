"""Shell analysis-depth selector view model and control (ISSUE-0175 UI slice).

Pure projection of the existing application-layer profiles: nothing here
computes a workload, SLO or resource figure.  Missing measurements are shown as
"Unavailable" with a reason, never as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import status_tag
from etf_cockpit.application.analysis_depth import (
    ANALYSIS_TIMINGS_RELATIVE_PATH,
    AnalysisDepthError,
    AnalysisDepthProfile,
    AnalysisTimingRecord,
    create_resource_plan,
    load_analysis_depth_profiles,
    timing_percentiles,
)
from etf_cockpit.application.settings import ANALYSIS_DEPTHS

UNAVAILABLE = "Unavailable"
SELECTOR_KEY = "shell.analysis-depth-selector"
DETAIL_KEY = "shell.analysis-depth-detail"

TimingReader = Callable[[Path, str], list[AnalysisTimingRecord]]
CertificationReader = Callable[[Path, str], "dict[str, object] | None"]
DETAILS_KEY = "shell.analysis-depth-details"
COMPARE_KEY = "shell.analysis-depth-compare"


@dataclass(frozen=True)
class DepthSummary:
    """Display projection for one analysis depth."""

    depth: str
    label: str
    stages: str
    slo_target: str
    measured: str
    measured_available: bool
    resources: str
    resources_available: bool
    reason: str | None

    @property
    def lines(self) -> tuple[str, ...]:
        return (self.stages, self.slo_target, self.measured, self.resources)


def _default_root() -> Path:
    from etf_cockpit.core.paths import ROOT

    return ROOT


def _read_all_timings(root: Path, profile_id: str) -> list[AnalysisTimingRecord]:
    """Every stored timing kind (stage, cold acquisition, Training Centre) for one profile."""

    import pandas as pd

    path = Path(root) / ANALYSIS_TIMINGS_RELATIVE_PATH
    if not path.is_file():
        return []
    frame = pd.read_parquet(path)
    records: list[AnalysisTimingRecord] = []
    for row in frame.to_dict("records"):
        if row.get("profile_id") != profile_id:
            continue
        records.append(
            AnalysisTimingRecord(
                run_id=str(row["run_id"]),
                profile_id=str(row["profile_id"]),
                timing_kind=str(row["timing_kind"]),
                stage_id=str(row["stage_id"]),
                wall_time_seconds=float(row["wall_time_seconds"]),
                cache_state=str(row["cache_state"]),
                outcome=str(row.get("outcome") or "unknown"),
            )
        )
    return records


def _read_timings(root: Path, profile_id: str) -> list[AnalysisTimingRecord]:
    return [r for r in _read_all_timings(root, profile_id) if r.timing_kind == "stage"]


def _duration(seconds: float) -> str:
    return f"{seconds / 60:.1f} min" if seconds >= 60 else f"{seconds:.1f} s"


def depth_label(depth: object) -> str | None:
    """Chip text for a stored depth, or None when no valid depth is selected."""

    return depth.capitalize() if isinstance(depth, str) and depth in ANALYSIS_DEPTHS else None


def summarise_depth(
    depth: str,
    *,
    root: Path | None = None,
    profiles: dict[str, AnalysisDepthProfile] | None = None,
    timing_reader: TimingReader = _read_timings,
) -> DepthSummary:
    """Project a profile, its declared SLO target, measured timings and resource plan."""

    label = depth.capitalize()
    try:
        registry = profiles if profiles is not None else load_analysis_depth_profiles()
        profile = registry[depth]
    except (AnalysisDepthError, KeyError) as exc:
        reason = f"profile manifest unavailable: {exc}"
        return DepthSummary(
            depth,
            label,
            f"Stages: {UNAVAILABLE} ({reason})",
            f"SLO target: {UNAVAILABLE}",
            f"Measured: {UNAVAILABLE}",
            False,
            f"Resources: {UNAVAILABLE}",
            False,
            reason,
        )
    stages = (
        f"Stages: {len(profile.mandatory_stages)} mandatory, {len(profile.optional_stages)} optional "
        f"({profile.profile_version}, {profile.manifest_hash[:8]})"
    )
    slo_target = f"SLO target (provisional, reference machine): {_duration(profile.slo_seconds)}"

    measured_reason: str | None = None
    measured_available = False
    try:
        records = timing_reader(Path(root) if root is not None else _default_root(), depth)
        stats = timing_percentiles(records, profile_id=depth)
        measured = (
            f"Measured stage timings: p50 {_duration(float(stats['p50_seconds']))}, "
            f"p95 {_duration(float(stats['p95_seconds']))} (n={stats['sample_count']}); "
            "SLO certification not claimed"
        )
        measured_available = True
    except AnalysisDepthError:
        measured_reason = "no measured timings recorded for this profile"
    except Exception as exc:  # an unreadable store must not break the shell
        measured_reason = f"timing store unreadable ({type(exc).__name__})"
    if not measured_available:
        measured = f"Measured: {UNAVAILABLE} ({measured_reason})"

    resource_reason: str | None = None
    resources_available = False
    try:
        plan = create_resource_plan(profile)
        resources = (
            f"Resources ({plan.hardware_profile_id}, {plan.compatibility_status}): "
            f"~{plan.estimated_cpu:g} CPU, {plan.estimated_memory_mb} MB RAM, {plan.estimated_disk_mb} MB disk"
        )
        resources_available = True
    except Exception as exc:
        resource_reason = f"resource estimate unavailable ({type(exc).__name__})"
        resources = f"Resources: {UNAVAILABLE} ({resource_reason})"

    reason = "; ".join(item for item in (measured_reason, resource_reason) if item) or None
    return DepthSummary(
        depth, label, stages, slo_target, measured, measured_available, resources, resources_available, reason
    )


@dataclass(frozen=True)
class DepthDiff:
    """Read-only difference between two stored profile manifests."""

    from_depth: str
    to_depth: str
    only_in_from: tuple[str, ...]
    only_in_to: tuple[str, ...]
    shared: tuple[str, ...]
    version_changed: tuple[str, ...]
    slo_from: int
    slo_to: int

    @property
    def lines(self) -> tuple[str, ...]:
        def names(items: tuple[str, ...]) -> str:
            return ", ".join(items) if items else "none"

        return (
            f"Only in {self.from_depth.capitalize()}: {names(self.only_in_from)}",
            f"Only in {self.to_depth.capitalize()}: {names(self.only_in_to)}",
            f"Shared stages: {len(self.shared)}; with a different stage version: {names(self.version_changed)}",
            f"Provisional SLO target: {_duration(self.slo_from)} vs {_duration(self.slo_to)}",
        )


def stage_lists(profile: AnalysisDepthProfile) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Included stage ids (mandatory, optional) of one stored profile."""

    return profile.mandatory_stages, profile.optional_stages


def omitted_evidence(
    depth: str, profiles: dict[str, AnalysisDepthProfile] | None = None
) -> tuple[tuple[str, str], ...]:
    """Stages a higher profile includes that this one omits, as (stage_id, first higher depth)."""

    registry = profiles if profiles is not None else load_analysis_depth_profiles()
    own = {stage.stage_id for stage in registry[depth].stages}
    seen: dict[str, str] = {}
    for higher in ANALYSIS_DEPTHS[ANALYSIS_DEPTHS.index(depth) + 1 :]:
        if higher not in registry:
            continue
        for stage in registry[higher].stages:
            if stage.stage_id not in own and stage.stage_id not in seen:
                seen[stage.stage_id] = higher
    return tuple(seen.items())


def compare_depths(
    from_depth: str, to_depth: str, profiles: dict[str, AnalysisDepthProfile] | None = None
) -> DepthDiff:
    """Diff two stored profiles' stage sets; never runs or recomputes anything."""

    registry = profiles if profiles is not None else load_analysis_depth_profiles()
    a, b = registry[from_depth], registry[to_depth]
    a_ids = [stage.stage_id for stage in a.stages]
    b_ids = [stage.stage_id for stage in b.stages]
    shared = tuple(item for item in a_ids if item in b_ids)
    changed = tuple(item for item in shared if a.stage(item).stage_version != b.stage(item).stage_version)
    return DepthDiff(
        from_depth,
        to_depth,
        tuple(item for item in a_ids if item not in b_ids),
        tuple(item for item in b_ids if item not in a_ids),
        shared,
        changed,
        a.slo_seconds,
        b.slo_seconds,
    )


@dataclass(frozen=True)
class DepthHistory:
    """Measured timing history split by cache state and timing kind."""

    lines: tuple[str, ...]
    available: bool
    reason: str | None


def _split_line(label: str, records: list[AnalysisTimingRecord]) -> str:
    if not records:
        return f"{label}: {UNAVAILABLE} (no measurements recorded)"
    stats = timing_percentiles(records, timing_kind=records[0].timing_kind)
    return (
        f"{label}: p50 {_duration(float(stats['p50_seconds']))}, "
        f"p95 {_duration(float(stats['p95_seconds']))} (n={stats['sample_count']})"
    )


def timing_history(
    depth: str,
    *,
    root: Path | None = None,
    history_reader: TimingReader = _read_all_timings,
) -> DepthHistory:
    """Project stored timings: warm/cold stage runs, cold acquisition and Training Centre."""

    try:
        records = history_reader(Path(root) if root is not None else _default_root(), depth)
    except Exception as exc:  # an unreadable store must not break the shell
        reason = f"timing store unreadable ({type(exc).__name__})"
        return DepthHistory((f"Measured history: {UNAVAILABLE} ({reason})",), False, reason)
    if not records:
        reason = "no measured timings recorded for this profile"
        return DepthHistory((f"Measured history: {UNAVAILABLE} ({reason})",), False, reason)
    stage = [r for r in records if r.timing_kind == "stage"]
    runs = sorted({r.run_id for r in records})
    lines = [
        f"Measured history: {len(runs)} run(s) recorded",
        _split_line("Stages, warm cache", [r for r in stage if r.cache_state == "warm"]),
        _split_line("Stages, cold cache", [r for r in stage if r.cache_state == "cold"]),
        _split_line("Cold acquisition", [r for r in records if r.timing_kind == "cold_acquisition"]),
        _split_line("Training Centre", [r for r in records if r.timing_kind == "training_centre"]),
    ]
    return DepthHistory(tuple(lines), True, None)


def _read_certification(root: Path, depth: str) -> dict[str, object] | None:
    """No application API stores certify_benchmark results yet, so there is nothing to read."""

    return None


def certification_line(
    depth: str, *, root: Path | None = None, certification_reader: CertificationReader = _read_certification
) -> tuple[str, str]:
    """(text, tone) for the SLO certification state; never claims certified without a stored result."""

    try:
        result = certification_reader(Path(root) if root is not None else _default_root(), depth)
    except Exception as exc:
        return f"Certification: not available ({type(exc).__name__})", "w"
    status = result.get("status") if isinstance(result, dict) else None
    if status == "certified":
        return "Certification: certified (stored benchmark result)", "g"
    if status == "not_certified":
        return f"Certification: not certified ({result.get('reason') or 'reason not recorded'})", "b"
    return "Certification: not available (no stored certify_benchmark result)", "w"


def depth_details_view(
    selected: str,
    *,
    root: Path | None = None,
    profiles: dict[str, AnalysisDepthProfile] | None = None,
    history_reader: TimingReader = _read_all_timings,
    certification_reader: CertificationReader = _read_certification,
    on_update: Callable[[], None] | None = None,
) -> ft.Column:
    """Stage lists, omitted-evidence warning, read-only compare, history and certification."""

    muted = dict(color=theme.MUTED, size=theme.FONT_XS, selectable=True)
    try:
        registry = profiles if profiles is not None else load_analysis_depth_profiles()
        profile = registry[selected]
    except (AnalysisDepthError, KeyError) as exc:
        return ft.Column(
            [
                ft.Text(
                    f"Stage list: {UNAVAILABLE} (profile manifest unavailable: {exc})",
                    key=f"{DETAILS_KEY}.stages",
                    **muted,
                )
            ],
            key=f"{DETAILS_KEY}.content",
        )
    mandatory, optional = stage_lists(profile)
    omitted = omitted_evidence(selected, registry)
    stages_text = ft.Text(
        f"Included ({len(mandatory)} mandatory): {', '.join(mandatory) or 'none'}. "
        f"Included ({len(optional)} optional): {', '.join(optional) or 'none'}.",
        key=f"{DETAILS_KEY}.stages",
        color=theme.TEXT,
        size=theme.FONT_XS,
        selectable=True,
    )
    if omitted:
        warning = ft.Text(
            "Omitted evidence: "
            + ", ".join(f"{stage} (in {depth.capitalize()})" for stage, depth in omitted)
            + ". Results at this depth do not include these stages.",
            key=f"{DETAILS_KEY}.omitted",
            color=theme.AMBER,
            size=theme.FONT_XS,
            selectable=True,
        )
    else:
        warning = ft.Text(
            "Omitted evidence: none; no higher profile adds stages.",
            key=f"{DETAILS_KEY}.omitted",
            **muted,
        )

    others = [item for item in ANALYSIS_DEPTHS if item != selected and item in registry]
    diff_text = ft.Text(
        "Choose a profile to compare with; this is a read-only view and starts no run.",
        key=f"{COMPARE_KEY}.result",
        **muted,
    )

    def compare_changed(event: ft.ControlEvent) -> None:
        value = getattr(getattr(event, "control", None), "value", None) or getattr(event, "data", None)
        if value in others:
            diff_text.value = "\n".join(compare_depths(selected, value, registry).lines)
            if on_update is not None:
                on_update()

    compare = ft.Dropdown(
        key="shell.analysis-depth-compare",
        label="Compare with",
        options=[ft.dropdown.Option(item, item.capitalize()) for item in others],
        width=170,
        dense=True,
        on_select=compare_changed,
    )
    history = timing_history(selected, root=root, history_reader=history_reader)
    history_text = ft.Text("\n".join(history.lines), key=f"{DETAILS_KEY}.history", **muted)
    cert_text, cert_tone = certification_line(selected, root=root, certification_reader=certification_reader)
    cert_tag = status_tag(cert_text, cert_tone, key=f"{DETAILS_KEY}.certification")
    return ft.Column(
        [
            ft.Text(f"{selected.capitalize()} profile stages", color=theme.TEXT, weight=ft.FontWeight.BOLD),
            stages_text,
            warning,
            compare,
            diff_text,
            history_text,
            cert_tag,
        ],
        key=f"{DETAILS_KEY}.content",
        spacing=8,
        tight=True,
        scroll=ft.ScrollMode.AUTO,
    )


def depth_selector(
    selected: str | None,
    *,
    on_selected: Callable[[str], None],
    root: Path | None = None,
    profiles: dict[str, AnalysisDepthProfile] | None = None,
    timing_reader: TimingReader = _read_timings,
    width: int = 150,
    open_dialog: Callable[[ft.AlertDialog], None] | None = None,
    close_dialog: Callable[[ft.AlertDialog], None] | None = None,
    get_selected: Callable[[], str | None] | None = None,
    history_reader: TimingReader = _read_all_timings,
    certification_reader: CertificationReader = _read_certification,
) -> ft.Container:
    """Dropdown (Quick/Medium/High/Full) with a live SLO / workload detail line."""

    detail = ft.Text(
        "Select a depth to see its SLO target, measured timings and resource estimate.",
        key=DETAIL_KEY,
        color=theme.MUTED,
        size=theme.FONT_XS,
        max_lines=2,
        overflow=ft.TextOverflow.ELLIPSIS,
    )

    def refresh_detail(depth: str | None) -> None:
        if depth not in ANALYSIS_DEPTHS:
            return
        summary = summarise_depth(depth, root=root, profiles=profiles, timing_reader=timing_reader)
        detail.value = " | ".join(summary.lines)
        detail.tooltip = summary.reason or "Measured values come from the local timing store; targets are provisional."

    def changed(event: ft.ControlEvent) -> None:
        value = getattr(getattr(event, "control", None), "value", None) or getattr(event, "data", None)
        if value in ANALYSIS_DEPTHS:
            on_selected(value)
            refresh_detail(value)

    dropdown = ft.Dropdown(
        key="shell.analysis-depth-selector",
        label="Analysis depth",
        value=selected if selected in ANALYSIS_DEPTHS else None,
        options=[ft.dropdown.Option(item, item.capitalize()) for item in ANALYSIS_DEPTHS],
        width=width,
        dense=True,
        on_select=changed,
    )
    refresh_detail(selected)

    def show_details(_event: ft.ControlEvent) -> None:
        depth = get_selected() if get_selected is not None else dropdown.value
        if depth not in ANALYSIS_DEPTHS:
            detail.value = f"Stage list: {UNAVAILABLE} (select a depth first)"
            return
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Analysis depth details", color=theme.TEXT),
            content=ft.Container(
                width=560,
                content=depth_details_view(
                    depth,
                    root=root,
                    profiles=profiles,
                    history_reader=history_reader,
                    certification_reader=certification_reader,
                    on_update=lambda: dialog.update() if getattr(dialog, "page", None) else None,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Close",
                    key="shell.analysis-depth-details.close",
                    on_click=lambda _e: close_dialog(dialog) if close_dialog else None,
                )
            ],
        )
        if open_dialog is not None:
            open_dialog(dialog)

    details_button = ft.TextButton("Depth details", key="shell.analysis-depth-details", on_click=show_details)
    return ft.Container(
        content=ft.Column([dropdown, detail, details_button], spacing=2, tight=True), key=f"{SELECTOR_KEY}.group"
    )
