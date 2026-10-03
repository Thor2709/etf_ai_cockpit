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


def _read_timings(root: Path, profile_id: str) -> list[AnalysisTimingRecord]:
    import pandas as pd

    path = Path(root) / ANALYSIS_TIMINGS_RELATIVE_PATH
    if not path.is_file():
        return []
    frame = pd.read_parquet(path)
    records: list[AnalysisTimingRecord] = []
    for row in frame.to_dict("records"):
        if row.get("profile_id") != profile_id or row.get("timing_kind") != "stage":
            continue
        records.append(
            AnalysisTimingRecord(
                run_id=str(row["run_id"]),
                profile_id=str(row["profile_id"]),
                timing_kind="stage",
                stage_id=str(row["stage_id"]),
                wall_time_seconds=float(row["wall_time_seconds"]),
                cache_state=str(row["cache_state"]),
                outcome=str(row.get("outcome") or "unknown"),
            )
        )
    return records


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


def depth_selector(
    selected: str | None,
    *,
    on_selected: Callable[[str], None],
    root: Path | None = None,
    profiles: dict[str, AnalysisDepthProfile] | None = None,
    timing_reader: TimingReader = _read_timings,
    width: int = 150,
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
    return ft.Container(content=ft.Column([dropdown, detail], spacing=2, tight=True), key=f"{SELECTOR_KEY}.group")
