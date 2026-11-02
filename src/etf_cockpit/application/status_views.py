"""Compact local status aggregators for MCP and other headless callers.

Open defaults: app-wide readiness is unavailable unless a bounded date interval
is supplied by its dedicated tool; status cards show at most 25 workflows and
8 paper-bot rows. The local paper-controls account is ``local-paper``.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any, Mapping

from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.validation_report import load_validation_report


def _root(session: object | None = None, root: Path | None = None) -> Path:
    session_root = getattr(session, "root", None)
    return Path(root or session_root or ROOT).resolve()


def _unavailable(reason: str) -> dict[str, object]:
    return {"status": "unavailable", "reason": reason}


def _safe_call(function, *args: object, **kwargs: object) -> dict[str, Any]:
    try:
        value = function(*args, **kwargs)
    except Exception as exc:  # status cards must expose a failed dependency, not hide it
        return _unavailable(f"{type(exc).__name__}: service could not be read")
    return value if isinstance(value, dict) else {"status": "available", "data": value}


def _data_health(root: Path) -> dict[str, Any]:
    from etf_cockpit.core.config import load_config
    from etf_cockpit.data.health import build_data_health

    report = build_data_health(load_config(root / "configs"), root)
    rows = [
        {
            "dataset": row.dataset,
            "status": str(getattr(row.status, "value", row.status)),
            "as_of": row.as_of,
            "warnings": list(row.warnings),
        }
        for row in report.rows
    ]
    statuses = {row["status"] for row in rows}
    status = "failed" if statuses & {"corrupt", "schema_mismatch"} else (
        "warning" if statuses & {"stale", "missing"} else "unavailable" if "unavailable" in statuses else "passed"
    )
    return {
        "status": status,
        "as_of": report.as_of_date,
        "datasets": rows,
        "execution_allowed": False,
    }


def build_gate_status(*, scope: str = "app", root: Path | None = None) -> dict[str, Any]:
    """Compose canonical local gate readers; unknown scopes and missing inputs stay unavailable."""

    if scope not in {"app", "instrument", "proposal"}:
        raise ValueError("scope must be app, instrument, or proposal")
    base = Path(root or ROOT).resolve()
    if scope != "app":
        reason = f"{scope} scope requires an identifier that is not part of the gates_status input contract"
        unavailable = _unavailable(reason)
        return {
            "scope": scope,
            "status": "unavailable",
            "readiness": unavailable,
            "data_quality": unavailable,
            "release_certification": unavailable,
            "last_validation": load_validation_report(base),
            "security": unavailable,
            "quality_programme": unavailable,
            "kill_switch": unavailable,
            "freeze": unavailable,
            "execution_allowed": False,
        }

    from etf_cockpit.application.quality_programme import load_quality_programme_report
    from etf_cockpit.governance.release_certification import release_certification_report
    from etf_cockpit.security.policy import build_security_report

    health = _safe_call(_data_health, base)
    release = _safe_call(release_certification_report, base)
    security = _safe_call(build_security_report, base)
    quality = _safe_call(load_quality_programme_report, base)
    controls = _paper_kill_switch_status(base)
    validation = load_validation_report(base)
    readiness = _unavailable("No date interval was supplied for the app-wide historical readiness gate")
    kill_switch = {
        "status": controls.get("status", "unavailable"),
        "active": controls.get("active"),
        "reason": None if controls.get("status") == "available" else controls.get("reason"),
    }
    freeze = _unavailable("No canonical application freeze projection is available")
    statuses = [health.get("status"), release.get("status"), security.get("status"), quality.get("status"), validation.get("status"), kill_switch.get("status")]
    if "failed" in statuses or "blocked" in statuses:
        overall = "failed"
    elif any(status in {"unavailable", "not_run", "incomplete"} for status in statuses):
        overall = "unavailable"
    elif kill_switch.get("active") is True:
        overall = "blocked"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "passed"
    return {
        "scope": scope,
        "status": overall,
        "readiness": readiness,
        "data_quality": health,
        "release_certification": release,
        "last_validation": validation,
        "security": security,
        "quality_programme": quality,
        "kill_switch": kill_switch,
        "freeze": freeze,
        "execution_allowed": False,
    }


def _paper_kill_switch_status(root: Path) -> dict[str, object]:
    """Read kill-switch state without opening the incident journal or creating its lock file."""

    from etf_cockpit.trading.pre_trade_controls import PreTradeControlError, PreTradeControls

    controls = PreTradeControls(root, account_id="local-paper")
    try:
        controls.load_limits()
        active = controls.kill_switch_active()
    except (PreTradeControlError, OSError, ValueError) as exc:
        return {"status": "unavailable", "active": None, "reason": f"paper kill-switch state unavailable ({type(exc).__name__})"}
    return {"status": "available", "active": active, "reason": None}


def build_cockpit_status(*, detail: str = "brief", session: object | None = None, enabled_tiers: tuple[str, ...] = ()) -> dict[str, Any]:
    """Build the L0 status card from existing application and governance readers."""

    if detail not in {"brief", "full"}:
        raise ValueError("detail must be 'brief' or 'full'")
    base = _root(session)
    gates = build_gate_status(root=base)
    health = gates["data_quality"]
    from etf_cockpit.application.paper_bots_view import load_paper_bots_view

    bots = _safe_call(load_paper_bots_view, base)
    jobs: list[object] = []
    if session is not None and callable(getattr(session, "list_workflows", None)):
        try:
            jobs = list(session.list_workflows(status=None, offset=0, limit=25))
        except Exception:
            jobs = []
    active_jobs = [row for row in jobs if str(getattr(getattr(row, "status", None), "value", getattr(row, "status", ""))) in {"queued", "running", "waiting"}]
    result: dict[str, Any] = {
        "status": "available" if gates.get("status") != "unavailable" else "unavailable",
        "as_of": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "freshness": health.get("status") if isinstance(health, Mapping) else "unavailable",
        "readiness": gates["readiness"],
        "gate_summary": {"status": gates.get("status"), "release": gates["release_certification"].get("status")},
        "active_jobs": [_compact(row) for row in active_jobs],
        "enabled_tiers": sorted(enabled_tiers),
        "paper_bots": _compact(bots),
        "execution_allowed": False,
    }
    if detail == "full":
        result["gates"] = gates
        result["data_quality"] = health
        result["jobs"] = [_compact(row) for row in jobs]
    return result


def build_local_diagnostics(root: Path) -> dict[str, Any]:
    """Compose the application-owned diagnostics readers for one configured root."""

    from etf_cockpit.application.diagnostics_views import build_resource_profile_diagnostics, load_analysis_parity_report
    from etf_cockpit.core.session_log import session_log_status
    from etf_cockpit.plugins.builtins import plugin_status_rows

    return {
        "resources": build_resource_profile_diagnostics(root),
        "analysis_parity": load_analysis_parity_report(),
        "plugins": list(plugin_status_rows()),
        "session_log": session_log_status(),
        "execution_allowed": False,
    }


def read_methodology_resource(root: Path, topic: str) -> dict[str, object]:
    """Read the allow-listed methodology configuration or forward-evidence summary."""

    topic = topic.strip().casefold().replace("-", "_")
    if topic not in {"score_engine_v3", "forecast_promotion", "glossary", "forward_evidence_diary"}:
        raise ValueError("methodology topic is not allow-listed")
    base = Path(root).resolve()
    if topic in {"score_engine_v3", "glossary"}:
        import yaml

        path = base / "configs" / ("score_engine_v3.yaml" if topic == "score_engine_v3" else "glossary.yaml")
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            return {"status": "unavailable", "topic": topic, "unavailable_reason": f"methodology source unavailable ({type(exc).__name__})", "execution_allowed": False}
        return {"status": "available", "topic": topic, "data": value, "execution_allowed": False}
    if topic == "forecast_promotion":
        from etf_cockpit.core.config import load_config

        try:
            settings = load_config(base / "configs").models.promotion.model_dump(mode="json")
        except Exception as exc:
            return {"status": "unavailable", "topic": topic, "unavailable_reason": f"promotion settings unavailable ({type(exc).__name__})", "execution_allowed": False}
        return {"status": "available", "topic": topic, "data": settings, "execution_allowed": False}
    from etf_cockpit.data.forward_evidence_diary import ForwardEvidenceDiary

    try:
        return {"status": "available", "topic": topic, "data": ForwardEvidenceDiary().export_summary(root=base), "execution_allowed": False}
    except Exception as exc:
        return {"status": "unavailable", "topic": topic, "unavailable_reason": f"forward evidence diary unavailable ({type(exc).__name__})", "execution_allowed": False}


def build_what_changed(*, since: str = "7d", root: Path | None = None, offset: int = 0, limit: int = 25) -> dict[str, Any]:
    """Compare stored score runs using the canonical run comparison and upstream context services."""

    from etf_cockpit.application.run_change_context import upstream_run_context
    from etf_cockpit.data.run_changes import compare_runs, run_completion_time
    from etf_cockpit.data.score_history import score_history_frame

    base = Path(root or ROOT).resolve()
    history = score_history_frame(root=base)
    if history.empty or "run_id" not in history.columns:
        return {"status": "unavailable", "unavailable_reason": "stored score history is unavailable", "changes": [], "execution_allowed": False}
    since_text = str(since).strip()
    if not since_text:
        raise ValueError("since must be a date, timestamp, or duration such as 7d")
    cutoff = _since_cutoff(since_text)
    valid_runs = []
    for run_id in dict.fromkeys(history["run_id"].astype(str).tolist()):
        completed_at = run_completion_time(history, run_id)
        if completed_at is not None:
            valid_runs.append((completed_at, run_id))
    valid_runs.sort(key=lambda row: (row[0], row[1]))
    recent_runs = [item for item in valid_runs if item[0] >= cutoff]
    if not recent_runs:
        return {"status": "unavailable", "since": since_text, "unavailable_reason": "no complete score run exists in the requested interval", "changes": [], "execution_allowed": False}
    completed, current = recent_runs[-1]
    previous = next((run_id for _, run_id in reversed(valid_runs) if run_id != current), None)
    if completed is None:
        return {"status": "unavailable", "unavailable_reason": "current run completion time is unavailable", "changes": [], "execution_allowed": False}
    report = compare_runs(history, current, previous, root=base)
    context = upstream_run_context(history, current, previous, root=base)
    changes = [asdict(item) if is_dataclass(item) else item for item in report.changes[offset : offset + limit + 1]]
    has_more = len(changes) > limit
    return {
        "status": "available",
        "since": since_text,
        "current_run_id": current,
        "previous_run_id": previous,
        "current_completed_at": completed.isoformat(),
        "summary": report.summary,
        "changes": changes[:limit],
        "total": len(report.changes),
        "upstream": context,
        "truncated": has_more,
        "execution_allowed": False,
    }


def _since_cutoff(value: str) -> datetime:
    match = re.fullmatch(r"(\d{1,4})d", value.strip(), flags=re.IGNORECASE)
    if match:
        return datetime.now(timezone.utc) - timedelta(days=int(match.group(1)))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("since must be an ISO date/time or duration such as 7d") from None
    if parsed.tzinfo is None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("since timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _compact(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return value


__all__ = ["build_cockpit_status", "build_gate_status", "build_local_diagnostics", "build_what_changed", "read_methodology_resource"]
