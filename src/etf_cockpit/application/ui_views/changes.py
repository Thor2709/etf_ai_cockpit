"""Read-only view model for What Changed (FINAL_UI_SPEC 6.8, 8).

Projects an existing ``RunChangeReport`` into display rows. Nothing is recomputed: a value the report does
not hold is ``None`` and shown as "—"/"Unavailable", never as zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

SEGMENT_ITEMS = (
    "All dimensions",
    "Score",
    "Freshness",
    "Forecasts",
    "Portfolio",
    "Rank",
    "Warnings",
    "Model availability",
    "News inventory",
    "Backtest trust",
    "Lineage",
    "Source revisions",
    "Classification",
    "Policy versions",
)
# Segment label -> the report dimension keys it selects.
SEGMENT_DIMENSIONS: Mapping[str, tuple[str, ...]] = {
    "Score": ("score",),
    "Freshness": ("freshness",),
    "Forecasts": ("forecasts",),
    "Portfolio": ("portfolio_risk", "portfolio_targets"),
    "Rank": ("rank",),
    "Warnings": ("warnings",),
    "Model availability": ("model_availability",),
    "News inventory": ("news_inventory",),
    "Backtest trust": ("backtest_trust",),
    "Lineage": ("lineage",),
    "Source revisions": ("source_revisions",),
    "Classification": ("classification",),
    "Policy versions": ("policy_versions",),
}
_UPSTREAM = ("source_revisions", "classification", "policy_versions", "portfolio_targets")
MINUS = "−"


@dataclass(frozen=True)
class ChangeRow:
    instrument_id: str
    score_delta: float | None
    rank_delta: int | None  # places gained (+) or lost (-); None = no previous rank
    freshness: tuple[str, str]  # (tag text, kind)
    model: tuple[str, str]
    forecasts: str
    news: str | None
    backtest_trust: str | None
    portfolio_risk: str | None
    changed_dimensions: frozenset[str]
    summary: str = ""
    causal_paths: tuple[str, ...] = ()
    causal_status: str = "unavailable"
    causal_reason: str | None = None
    changed_inputs: tuple[tuple[str, str], ...] = ()  # (label, detail) of each changed input dimension


@dataclass(frozen=True)
class LineageRow:
    dot: str
    title: str
    sub: str


@dataclass(frozen=True)
class ChangesView:
    subtitle: str
    rows: tuple[ChangeRow, ...]
    lineage: tuple[LineageRow, ...]
    lineage_detail: str
    empty_reason: str = "No score runs with valid timezone-aware completion times are available to compare."
    extras: Mapping[str, str] = field(default_factory=dict)


def signed(value: float | int | None, decimals: int = 0) -> str:
    if value is None:
        return "—"
    if round(float(value), decimals) == 0:
        return "0"
    return f"{value:+.{decimals}f}".replace("-", MINUS)


def _status(change: object, key: str) -> str:
    return str(getattr(change, "dimension_statuses", {}).get(key, "unavailable"))


def _freshness(change: object) -> tuple[str, str]:
    value = str(getattr(change, "current_freshness", "unavailable") or "unavailable").strip().lower()
    if value in {"unavailable", "", "missing", "none"}:
        return "Missing", "bad"
    if "stale" in value:
        return "Stale", "warn"
    return "Fresh", "ok"


def _model(change: object) -> tuple[str, str]:
    value = str(getattr(change, "current_model_availability", "unavailable") or "unavailable").strip().lower()
    if value in {"unavailable", "", "missing", "none", "false", "0", "no"} or value.startswith("not"):
        return "Missing", "bad"
    return "Available", "ok"


def _forecasts(change: object) -> str:
    return {"changed": "Changed", "unchanged": "Unchanged"}.get(_status(change, "forecasts"), "Unavailable")


def _news(change: object) -> str | None:
    delta = getattr(change, "news_inventory_delta", None)
    return f"{delta:.0f} new" if delta is not None and delta > 0 else None


def _same_or_changed(change: object, key: str) -> str | None:
    return {"changed": "Changed", "unchanged": "Same"}.get(_status(change, key))


def _portfolio(change: object) -> str | None:
    delta = getattr(change, "portfolio_risk_delta", None)
    if delta is not None:
        return "Higher" if delta > 0 else "Lower" if delta < 0 else "Same"
    return _same_or_changed(change, "portfolio_risk")


def _changed_dimensions(change: object) -> frozenset[str]:
    changed = {key for key, status in getattr(change, "dimension_statuses", {}).items() if status == "changed"}
    if getattr(change, "score_delta", None):
        changed.add("score")
    if getattr(change, "score_rank_delta", None):
        changed.add("rank")
    for key in _UPSTREAM:
        value = getattr(change, "upstream_changes", {}).get(key)
        if value is not None and value[2]:
            changed.add(key)
    return frozenset(changed)


_INPUT_LABELS = (
    ("freshness", "Freshness"),
    ("model_availability", "Model availability"),
    ("forecasts", "Forecasts"),
    ("news_inventory", "News inventory"),
    ("backtest_trust", "Backtest trust"),
    ("portfolio_risk", "Portfolio risk"),
    ("warnings", "Warnings"),
    ("lineage", "Lineage"),
    ("source_revisions", "Source revisions"),
    ("classification", "Classification"),
    ("policy_versions", "Policy versions"),
    ("portfolio_targets", "Portfolio targets"),
)


def change_row(change: object) -> ChangeRow:
    rank_delta = getattr(change, "score_rank_delta", None)
    dims = _changed_dimensions(change)
    news = _news(change)
    inputs = tuple(
        (f"News: {news}" if key == "news_inventory" and news else label, key)
        for key, label in _INPUT_LABELS
        if key in dims
    )
    return ChangeRow(
        instrument_id=str(change.instrument_id),
        score_delta=getattr(change, "score_delta", None),
        rank_delta=None if rank_delta is None else -int(round(rank_delta)),
        freshness=_freshness(change),
        model=_model(change),
        forecasts=_forecasts(change),
        news=news,
        backtest_trust=_same_or_changed(change, "backtest_trust"),
        portfolio_risk=_portfolio(change),
        changed_dimensions=dims,
        summary=str(getattr(change, "summary", "") or ""),
        causal_paths=tuple(getattr(change, "causal_paths", ()) or ()),
        causal_status=str(getattr(change, "causal_paths_status", "unavailable")),
        causal_reason=getattr(change, "causal_paths_reason", None),
        changed_inputs=inputs,
    )


def sorted_rows(rows: Iterable[ChangeRow]) -> tuple[ChangeRow, ...]:
    """Largest absolute score change first; instruments without a score change last."""
    return tuple(sorted(rows, key=lambda r: (r.score_delta is None, -abs(r.score_delta or 0.0), r.instrument_id)))


def filter_rows(rows: Sequence[ChangeRow], *, query: str, changed_only: bool, segment: str) -> list[ChangeRow]:
    needle = (query or "").strip().casefold()
    wanted = SEGMENT_DIMENSIONS.get(segment)
    out = []
    for row in rows:
        if needle and needle not in row.instrument_id.casefold():
            continue
        if changed_only and not row.changed_dimensions:
            continue
        if wanted and not (set(wanted) & row.changed_dimensions):
            continue
        out.append(row)
    return out


def score_bars(rows: Iterable[ChangeRow], limit: int = 8) -> list[ChangeRow]:
    """Up to ``limit`` rows with the largest absolute score change, largest rise first."""
    changed = [r for r in rows if r.score_delta is not None]
    top = sorted(changed, key=lambda r: (-abs(r.score_delta or 0.0), r.instrument_id))[:limit]
    return sorted(top, key=lambda r: (-(r.score_delta or 0.0), r.instrument_id))


def score_insight(bars: Sequence[ChangeRow]) -> str | None:
    if not bars:
        return None
    return (
        f"{bars[0].instrument_id} rose most ({signed(bars[0].score_delta, 1)}); "
        f"{bars[-1].instrument_id} fell most ({signed(bars[-1].score_delta, 1)})."
    )


def lineage_rows(context: Mapping[str, object] | None, version_summary: Mapping[str, object] | None) -> tuple[LineageRow, ...]:
    """Run lineage rows from the existing upstream context; every missing source is explicit."""
    if context is None:
        out = [LineageRow("mute", "Run lineage unavailable", "Two comparable runs are needed.")]
    else:
        corrections, dependencies, paper = (
            value if isinstance(value, Mapping) else {}
            for value in (context.get("corrections"), context.get("dependencies"), context.get("paper_state"))
        )
        if corrections.get("status") == "available":
            changed = bool(corrections.get("changed"))
            out = [LineageRow("warn" if changed else "ok", "Data corrections",
                              f"{corrections.get('current_corrections')} corrections" if changed
                              else "Unchanged between runs (point-in-time)")]
        else:
            out = [LineageRow("mute", "Data corrections", f"Unavailable ({corrections.get('reason', 'not recorded')})")]
        if dependencies.get("status") == "available":
            moved = tuple(dependencies.get("changed_artifacts") or ())
            out.append(LineageRow("warn" if moved else "ok", "Run dependencies",
                                  "Changed: " + "; ".join(moved) if moved else "Unchanged"))
        else:
            out.append(LineageRow("mute", "Run dependencies",
                                  f"Unavailable ({dependencies.get('reason', 'not recorded')})"))
        out.append(LineageRow("ok" if paper.get("status") == "available" else "mute", "Paper / order state",
                              "Unchanged · execution_allowed=false" if paper.get("status") == "available"
                              else f"Unavailable ({paper.get('reason', 'not recorded')}) · execution_allowed=false"))
    if version_summary is not None:
        out.insert(2, LineageRow("info", "Formula / policy versions",
                                 f"Registry {version_summary.get('registry_version')} · "
                                 f"{version_summary.get('record_count')} records"))
    return tuple(out)
