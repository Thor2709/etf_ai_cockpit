"""Read-only view model for Home / Simple Scores (FINAL_UI_SPEC 6.1, 8).

Plain values only: nothing here changes a score, gate or forecast. A missing value is ``None``
(shown as an em dash or "Unavailable" with a reason) and never zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

TIER_FILTERS = ("All", "Primary", "Secondary", "Sparebanken")
SORT_MODES = ("Score", "Rank", "Change")
BAND_LABELS = ("<3", "3", "4", "5", "6", "7+")
GREY = "mute"  # semantic dot colour; the page maps it to a theme token
MINUS = "−"

_STRONG = {"strong_evidence_candidate"}
_GOOD = {"positive_evidence_candidate", "research_candidate", "add_candidate"}
_MIXED = {"hold_context", "mixed_evidence_review", "maintain_review", "increase_exposure_review"}
_REVIEW = {"weak_evidence_review", "low_quality_manual_review"}
_WEAK = {"reduce_exposure_review", "trim_candidate"}
_PENDING = {"pending_refresh", "scorecard_owned"}


@dataclass(frozen=True)
class CheckRow:
    dot: str  # ok | warn | bad | info | hex colour
    title: str
    sub: str
    tag_text: str
    tag_kind: str  # ok | warn | bad | mute
    route: str
    order: int = 3


@dataclass(frozen=True)
class ScoreRow:
    rank: int | None
    instrument_id: str
    name: str
    tier: str
    score: float | None
    evidence_text: str
    evidence_kind: str
    risk: str | None
    rank_delta: int | None  # places gained (+) or lost (-) since the previous run; None = no previous run
    old_rank: int | None = None
    new_rank: int | None = None


@dataclass(frozen=True)
class HomeView:
    checks: tuple[CheckRow, ...]
    scores: tuple[ScoreRow, ...]
    data_status: str
    instrument_total: int
    valid_scores: int
    data_quality_pct: float | None
    extra_models: tuple[str, ...]
    changes_reason: str = "No previous run to compare"
    extras: Mapping[str, str] = field(default_factory=dict)


def tier_label(source_group: str) -> str:
    text = str(source_group or "").strip()
    lowered = text.lower()
    for name in ("Primary", "Secondary", "Sparebanken"):
        if lowered.startswith(name.lower()):
            return name
    return text or "—"


def evidence_tag(final_label: str | None, final_action: str | None = None, blocked: bool = False) -> tuple[str, str]:
    """Canonical ``final_label`` -> (tag text, kind); the one mapping used on every page (spec 6.1)."""
    label = str(final_label or "").strip().lower()
    action = str(final_action or "").strip().lower()
    if blocked:
        return "Blocked", "bad"
    if label in _STRONG:
        return "Strong", "ok"
    if label in _GOOD:
        return "Good", "ok"
    if label == "watchlist":
        return "Watchlist", "ok"
    if label in _MIXED:
        return "Mixed", "warn"
    if label in _REVIEW or action == "manual_review":
        return "Review", "warn"
    if label == "not_backtested_candidate":
        return "Untested", "warn"
    if label in _WEAK:
        return "Weak", "bad"
    if label in _PENDING:
        return "Pending", "mute"
    if not label:
        return "—", "mute"
    return label.replace("_", " ").capitalize(), "mute"


def risk_band(risk_friction_10: float | None) -> str | None:
    if risk_friction_10 is None:
        return None
    if risk_friction_10 >= 7.0:
        return "Low"
    if risk_friction_10 >= 4.0:
        return "Medium"
    return "High"


def signed(value: int | float | None, decimals: int = 0) -> str:
    """Signed number with a true minus; ``None`` is an em dash and zero is plain ``0``."""
    if value is None:
        return "—"
    if round(float(value), decimals) == 0:
        return "0"
    return f"{value:+.{decimals}f}".replace("-", MINUS)


def score_rows(
    scores: Iterable[object],
    rank_info: Mapping[str, tuple[float | None, float | None]],
    blocked_ids: Iterable[str] = (),
) -> tuple[ScoreRow, ...]:
    """Rows ordered by score; ``rank_info`` maps instrument id -> (previous rank, current rank)."""
    blocked = set(blocked_ids)
    ordered = sorted(
        scores,
        key=lambda s: (s.final_score_10 is None, -(s.final_score_10 or 0.0), str(s.display_id)),
    )
    rows: list[ScoreRow] = []
    for index, item in enumerate(ordered, 1):
        ident = str(item.display_id)
        old, new = rank_info.get(ident, (None, None))
        text, kind = evidence_tag(item.final_label, item.final_action, ident in blocked)
        rows.append(
            ScoreRow(
                rank=index if item.final_score_10 is not None else None,
                instrument_id=ident,
                name=str(item.name or ""),
                tier=tier_label(item.source_group),
                score=item.final_score_10,
                evidence_text=text,
                evidence_kind=kind,
                risk=risk_band(item.risk_friction_10),
                rank_delta=None if old is None or new is None else int(round(old - new)),
                old_rank=None if old is None else int(old),
                new_rank=None if new is None else int(new),
            )
        )
    return tuple(rows)


def filter_tier(rows: Sequence[ScoreRow], tier: str) -> list[ScoreRow]:
    return list(rows) if tier == "All" else [row for row in rows if row.tier == tier]


def sort_rows(rows: Sequence[ScoreRow], mode: str) -> list[ScoreRow]:
    if mode == "Rank":
        return sorted(rows, key=lambda r: (r.rank is None, r.rank or 0, r.instrument_id))
    if mode == "Change":
        return sorted(rows, key=lambda r: (r.rank_delta is None, -abs(r.rank_delta or 0), r.instrument_id))
    return sorted(rows, key=lambda r: (r.score is None, -(r.score or 0.0), r.instrument_id))


def score_bands(rows: Iterable[ScoreRow]) -> tuple[int, ...]:
    """Instrument counts per band <3, 3, 4, 5, 6, 7+ on the canonical 0-10 scale; unscored rows are skipped."""
    counts = [0] * len(BAND_LABELS)
    for row in rows:
        if row.score is None:
            continue
        counts[0 if row.score < 3 else 5 if row.score >= 7 else int(row.score) - 2] += 1
    return tuple(counts)


def band_insight(rows: Sequence[ScoreRow]) -> str | None:
    scored = [row for row in rows if row.score is not None]
    if not scored:
        return None
    high = sum(1 for row in scored if row.score >= 6)
    low = sum(1 for row in scored if row.score < 4)
    return f"{high} of {len(scored)} instruments score 6 or higher; {low} are below 4."


def rank_change_bars(rows: Iterable[ScoreRow], limit: int = 7) -> list[ScoreRow]:
    """Up to ``limit`` rows with the largest absolute rank change, largest gain first."""
    changed = [row for row in rows if row.rank_delta is not None]
    top = sorted(changed, key=lambda r: (-abs(r.rank_delta or 0), r.instrument_id))[:limit]
    return sorted(top, key=lambda r: (-(r.rank_delta or 0), r.instrument_id))


def rank_insight(bars: Sequence[ScoreRow]) -> str | None:
    if not bars:
        return None
    best, worst = bars[0], bars[-1]
    return (
        f"{best.instrument_id} gained the most ({signed(best.rank_delta)} places); "
        f"{worst.instrument_id} fell the most ({signed(worst.rank_delta)} places)."
    )


# ---------------------------------------------------------------------------
# What matters today
# ---------------------------------------------------------------------------

_ROUTES = {
    "model_failures": "/forecasts",
    "manual_review": "/signals",
    "stale_data": "/data-health",
    "warning_changes": "/what-changed",
    "score_changes": "/what-changed",
    "upcoming_events": "/instrument",
    "audit_export": "/import-export",
    "alerts": "/portfolio",
    "contradictions": "/news-context",
}
_Records = Mapping[str, Sequence[Mapping[str, object]] | None]


def _first(records: _Records, source: str) -> Mapping[str, object] | None:
    found = records.get(source)
    return found[0] if found else None


def _check(source: str, record: Mapping[str, object] | None, ok_tag: tuple[str, str],
           warn_tag: tuple[str, str]) -> CheckRow:
    route = _ROUTES[source]
    if record is None:
        return CheckRow(GREY, f"{source.replace('_', ' ').capitalize()} unavailable",
                        "No local evidence was read for this check.", "Unavailable", "mute", route, 2)
    title, sub = str(record.get("title", "")), str(record.get("detail", ""))
    severity, status = str(record.get("severity", "info")), str(record.get("status", "available"))
    if severity == "critical":
        return CheckRow("bad", title, sub, "Failed", "bad", route, 0)
    if status == "unavailable":
        return CheckRow(GREY, title, sub, "Unavailable", "mute", route, 2)
    if severity == "warning" or status == "manual_review":
        return CheckRow("warn", title, sub, warn_tag[0], warn_tag[1], route, 1)
    return CheckRow("ok", title, sub, ok_tag[0], ok_tag[1], route, 3)


def build_checks(
    records: _Records,
    *,
    regime_label: str | None,
    regime_detail: str,
    final_mode: str,
    data_status: str,
) -> tuple[CheckRow, ...]:
    """Ordered bad -> warn -> upcoming/unavailable -> ok; checks with nothing to say (no alert) are hidden."""
    ok, review = ("OK", "ok"), ("Review", "warn")
    rows = [
        _check("model_failures", _first(records, "model_failures"), ok, review),
        _check("manual_review", _first(records, "manual_review"), ok, review),
        _check("stale_data", _first(records, "stale_data"), ok, review),
        _check("warning_changes", _first(records, "warning_changes"), ok, ("Warning", "warn")),
        _check("score_changes", _first(records, "score_changes"), ok, ("Changed", "warn")),
        _check("audit_export", _first(records, "audit_export"), ok, review),
    ]
    stale = rows[2]
    if data_status:
        rows[2] = CheckRow(stale.dot, f"Data health is {data_status}", stale.sub, stale.tag_text, stale.tag_kind,
                           stale.route, stale.order)
    audit = _first(records, "audit_export")
    if audit is not None and str(audit.get("title", "")).startswith("No recent"):
        rows[5] = CheckRow(GREY, "No audit export yet", str(audit.get("detail", "")), "None", "mute",
                           _ROUTES["audit_export"], 2)
    event = _first(records, "upcoming_events")
    route = _ROUTES["upcoming_events"]
    if event is None or str(event.get("status")) == "unavailable":
        reason = str((event or {}).get("detail", "")) or "No validated event records are available."
        rows.append(CheckRow(GREY, "No validated event calendar", reason, "Unavailable", "mute", route, 2))
    elif str(event.get("severity")) == "warning":
        rows.append(CheckRow("ok", str(event["title"]), str(event.get("detail", "")), "Upcoming", "mute", route, 2))
    else:
        rows.append(CheckRow("ok", str(event["title"]), str(event.get("detail", "")), "None", "mute", route, 2))
    alert = _first(records, "alerts")
    if alert is not None and not str(alert.get("title", "")).startswith("No active"):
        rows.append(_check("alerts", alert, ok, review))
    flagged = [r for r in (records.get("contradictions") or ())
               if str(r.get("severity")) != "info" and str(r.get("status")) == "available"]
    if flagged:
        rows.append(CheckRow("warn", f"{len(flagged)} news/macro contradictions",
                             f"{flagged[0].get('title', '')} · {flagged[0].get('detail', '')}", "Review", "warn",
                             _ROUTES["contradictions"], 1))
    rows.append(CheckRow("ok" if regime_label else GREY, f"Market regime: {regime_label or 'Unavailable'}",
                         regime_detail, "Context", "mute", "/macro", 3 if regime_label else 2))
    normal = final_mode == "Normal"
    rows.append(CheckRow("ok" if normal else "warn", f"Final mode: {final_mode}", "advisory scoring only",
                         "OK" if normal else "Review", "ok" if normal else "warn", "/system-map", 3 if normal else 1))
    return tuple(sorted(rows, key=lambda r: r.order))
