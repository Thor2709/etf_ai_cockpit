"""Read-only values the shell shows (badge count, footer rail). Nothing here changes a calculation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from etf_cockpit.app.formatting import format_timestamp

UNAVAILABLE = "Unavailable"

_QUALITY_STATES = {
    "clean": ("OK", "ok"),
    "ok": ("OK", "ok"),
    "pass": ("OK", "ok"),
    "passed": ("OK", "ok"),
    "warning": ("Review", "warn"),
    "review": ("Review", "warn"),
    "stale": ("Stale", "warn"),
    "blocked": ("Failed", "bad"),
    "failed": ("Failed", "bad"),
}


def material_change_count(state: object) -> int | None:
    """Number of instruments with a changed dimension in the latest run; None when unavailable.

    Cached per snapshot object so navigation does not re-read the score history every time.
    """
    snapshot = getattr(state, "snapshot", None)
    cache = getattr(state, "_shell_changes_cache", None)
    if cache is not None and cache[0] is snapshot:
        return cache[1]
    count: int | None
    try:
        from etf_cockpit.application.ui_facade import compare_runs, score_history_frame, select_comparison_runs

        history = score_history_frame()
        current, previous = select_comparison_runs(history) if not history.empty and "run_id" in history.columns else (None, None)
        if current is None:
            count = None
        else:
            report = compare_runs(history, current, previous)
            count = sum(1 for change in report.changes if "changed" in change.dimension_statuses.values())
    except Exception:  # the badge is advisory; any failure hides it instead of breaking navigation
        count = None
    try:
        state._shell_changes_cache = (snapshot, count)
    except Exception:
        pass
    return count


@dataclass(frozen=True)
class FooterValues:
    quality_text: str
    quality_kind: str
    quality_reason: str | None
    as_of: str
    as_of_reason: str | None
    forecast: str
    forecast_reason: str | None
    sample_data: bool


def _text(value: object) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return None if rendered.casefold() in {"", "none", "nan", "nat", "<na>", "unavailable"} else rendered


def footer_values(snapshot: object, data_report: object) -> FooterValues:
    status = _text(getattr(data_report, "status", None))
    if status is None:
        quality_text, quality_kind, quality_reason = UNAVAILABLE, "warn", "The current snapshot has no data-quality status."
    else:
        quality_text, quality_kind = _QUALITY_STATES.get(status.casefold(), (status, "warn"))
        quality_reason = None
    as_of_raw = _text(getattr(snapshot, "as_of_time", getattr(data_report, "as_of_time", None)))
    as_of_date = _text(getattr(data_report, "as_of_date", None))
    if as_of_raw is not None:
        as_of, as_of_reason = format_timestamp(as_of_raw), None
    elif as_of_date is not None:
        as_of, as_of_reason = format_timestamp(as_of_date), "The snapshot provides an as-of date but no as-of timestamp."
    else:
        as_of, as_of_reason = UNAVAILABLE, "The current snapshot has no as-of date or timestamp."

    forecasts = getattr(snapshot, "forecasts", None)
    forecast, forecast_reason = UNAVAILABLE, "No forecast source is available in the current snapshot."
    if forecasts is not None and not getattr(forecasts, "empty", True):
        columns = getattr(forecasts, "columns", ())
        models: list[str] = []
        for column in ("model", "model_id", "model_name", "forecast_model"):
            if column in columns:
                models = sorted({str(item) for item in forecasts[column].dropna().unique() if str(item).strip()})
                break
        if not models and "source_file" in columns:
            models = [Path(str(forecasts["source_file"].iloc[0])).stem]
        if models:
            forecast, forecast_reason = "baseline + " + ", ".join(models) + " (exp.)", None
        else:
            forecast, forecast_reason = "baseline", None
    return FooterValues(quality_text, quality_kind, quality_reason, as_of, as_of_reason, forecast, forecast_reason, _uses_sample(snapshot))


_SAMPLE_LABEL = re.compile("sample", re.IGNORECASE)


def _uses_sample(snapshot: object) -> bool:
    """True only when every price row comes from the bundled sample generator."""
    try:
        prices = getattr(snapshot, "prices", None)
        if prices is None or prices.empty or "source" not in prices.columns:
            return False
        # Test the distinct source labels, not every price row (same result, rebuilt on every navigation).
        return all(_SAMPLE_LABEL.search(str(label)) for label in prices["source"].unique())
    except Exception:
        return False
