"""Diagnostics read models: analysis parity report, resource profiles and profiled forecast-lab workspace (application; ADR-0002)."""

from collections.abc import Mapping
import json
from pathlib import Path

from etf_cockpit.core.performance import (
    PerformanceBudgetError as PerformanceBudgetError,
    build_performance_report as build_performance_report,
)
from etf_cockpit.operations.event_store import load_events_with_tail_recovery as load_events_with_tail_recovery
from etf_cockpit.plugins.builtins import plugin_status_rows as plugin_status_rows
from etf_cockpit.security.policy import build_security_report as build_security_report
from etf_cockpit.analysis.parity_report import (
    analysis_parity_report_path,
    validate_parity_report,
)
from etf_cockpit.core.resource_profiles import (
    HardwareSnapshot,
    resource_profile_report,
)


def build_profiled_forecast_lab_workspace(
    config: object,
    forecasts: object,
    prices: object,
    *,
    profile_id: str = "auto",
) -> dict[str, object]:
    """Build Forecast Lab through the app facade with an explicit hardware profile."""

    from etf_cockpit.features.forecast_lab import build_forecast_lab_workspace

    return build_forecast_lab_workspace(
        config, forecasts, prices, profile_id=profile_id
    )


def build_resource_profile_diagnostics(
    root: Path | None = None,
    *,
    requested_profile: str = "auto",
    snapshot: HardwareSnapshot | None = None,
) -> dict[str, object]:
    """Expose local hardware limitations in the application diagnostics payload."""

    report = resource_profile_report(
        root, requested_profile=requested_profile, snapshot=snapshot
    )
    return {
        "status": report["selected_status"],
        "limitations": list(report["limitations"]),
        "resource_profile": report,
        "execution_allowed": False,
    }


def load_analysis_parity_report(
    *, report_path: Path | None = None
) -> dict[str, object]:
    """Read the latest approved v2 parity report for diagnostics."""

    unavailable = {
        "schema_version": 2,
        "status": "unavailable",
        "first_mismatch": None,
        "reason": "analysis parity report unavailable",
        "execution_allowed": False,
    }
    path = analysis_parity_report_path() if report_path is None else Path(report_path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return unavailable | {"reason": "analysis parity report is missing or unreadable"}
    if not isinstance(report, Mapping) or report.get("schema_version") != 2:
        return unavailable | {"reason": "analysis parity report schema is invalid"}
    if validate_parity_report(report):
        return {
            "schema_version": 2,
            "status": "failed",
            "first_mismatch": {
                "stage": "report_security",
                "path": "sensitive_report_field",
                "dependency_path": ["stored_report", "diagnostics"],
            },
            "reason": "analysis parity report contains a sensitive field",
            "execution_allowed": False,
        }
    lanes = report.get("lanes")
    lane_statuses = [
        str(lane.get("status", "unavailable"))
        for lane in lanes.values()
        if isinstance(lane, Mapping)
    ] if isinstance(lanes, Mapping) else []
    stored_status = str(report.get("release_status", report.get("status", "unavailable")))
    security = report.get("security")
    security_failed = isinstance(security, Mapping) and security.get("status") == "failed"
    if "failed" in lane_statuses or stored_status == "failed" or security_failed:
        status = "failed"
    elif (
        lane_statuses
        and all(item == "passed" for item in lane_statuses)
        and stored_status == "passed"
    ):
        status = "passed"
    else:
        status = "unavailable" if stored_status == "unavailable" else "incomplete"
    mismatch = report.get("first_mismatch")
    if not isinstance(mismatch, Mapping):
        mismatch = None
    return {
        "schema_version": 2,
        "status": status,
        "first_mismatch": dict(mismatch) if mismatch is not None else None,
        "reason": None,
        "execution_allowed": False,
    }
