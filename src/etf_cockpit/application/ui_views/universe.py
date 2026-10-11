"""Read-only view model for the Universe page (FINAL_UI_SPEC 6.2, 8).

Plain values only: nothing here edits a record, a tier or a gate. Counts come from the records the page is
showing, a missing value stays ``None`` and is never zero-filled.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

TIERS = ("primary", "secondary", "sparebanken")
TIER_LABELS = {"primary": "Primary", "secondary": "Secondary", "sparebanken": "Sparebanken"}
TYPE_FILTERS = ("All", "ETF", "Stock")
_TYPE_LABELS = {"etf": "ETF", "stock": "Stock", "fund": "Fund", "bond": "Bond"}
_COMMODITY = {"commodity", "commodities", "gold", "precious_metals"}
_BOND = {"bond", "bonds", "fixed_income", "fixed income"}
CATEGORY_ORDER = ("Equity ETFs", "Bond ETFs", "Stocks", "Commodity", "Leveraged / inverse", "Funds", "Bonds", "Other")
MANUAL_REVIEW = "Manual review"


@dataclass(frozen=True)
class ReviewTag:
    text: str | None  # None renders as an em dash
    kind: str
    tooltip: str


@dataclass(frozen=True)
class CompositionSlice:
    name: str
    count: int


@dataclass(frozen=True)
class TierBar:
    label: str
    count: int


def tier_label(tier: str) -> str:
    return TIER_LABELS.get(str(tier).casefold(), str(tier).replace("_", " ").title() or "—")


def type_label(asset_type: str) -> str:
    key = str(asset_type or "").strip().casefold()
    return _TYPE_LABELS.get(key, key.replace("_", " ").title() or "—")


def flagged(record: object) -> str | None:
    """Leveraged / Inverse when the record carries the flag (inverse wins), else None."""
    if getattr(record, "inverse", False):
        return "Inverse"
    if getattr(record, "leveraged", False):
        return "Leveraged"
    return None


def tier_tag(record: object) -> tuple[str, str]:
    """Tag text and kind of the Tier column: leveraged / inverse instruments show a warn tag instead of the tier."""
    word = flagged(record)
    return (word, "warn") if word else (tier_label(getattr(record, "tier", "")), "mute")


def sub_line(record: object, accumulating: bool | None) -> str:
    """"<sector or theme> · <Accumulating / Distributing, or country>"; missing parts are left out."""
    first = str(getattr(record, "theme", "") or getattr(record, "sector", "") or "").strip()
    if accumulating is not None and str(getattr(record, "asset_type", "")).casefold() != "stock":
        second = "Accumulating" if accumulating else "Distributing"
    else:
        second = str(getattr(record, "region", "") or "").strip()
    return " · ".join(part for part in (first, second) if part)


def review_tag(record: object, policy_state: str | None, policy_reason: str | None) -> ReviewTag:
    """Review column: manual review beats needs-verification beats pending refresh; otherwise a dash."""
    state = str(policy_state or "unavailable")
    reason = str(policy_reason or "No versioned policy evidence is available.")
    isin_status = str(getattr(record, "isin_status", "verified"))
    evidence = f"Policy evidence: {state} · {reason} · ISIN status: {isin_status}"
    if state == "manual_review" or flagged(record):
        return ReviewTag("Manual review", "warn", evidence)
    if isin_status != "verified":
        return ReviewTag("Needs verification", "warn", evidence)
    if state in {"stale", "legacy_unmigrated"}:
        return ReviewTag("Pending refresh", "mute", evidence)
    return ReviewTag(None, "mute", evidence)


def needs_manual_review(record: object, policy_state: str | None = None) -> bool:
    return bool(flagged(record)) or str(policy_state or "") == "manual_review" or str(getattr(record, "isin_status", "verified")) != "verified"


def category(record: object, asset_class: str | None) -> str:
    """Composition group of a record (spec 6.2 slices)."""
    if flagged(record):
        return "Leveraged / inverse"
    kind = str(getattr(record, "asset_type", "") or "").casefold()
    cls = str(asset_class or "").casefold()
    if cls in _COMMODITY:
        return "Commodity"
    if kind == "etf":
        return "Bond ETFs" if cls in _BOND else "Equity ETFs"
    if kind == "stock":
        return "Stocks"
    if kind == "fund":
        return "Funds"
    if kind == "bond":
        return "Bonds"
    return "Other"


def composition(records: Iterable[object], asset_classes: Mapping[str, str]) -> list[CompositionSlice]:
    counts: dict[str, int] = {}
    for record in records:
        name = category(record, asset_classes.get(str(getattr(record, "instrument_id", ""))))
        counts[name] = counts.get(name, 0) + 1
    return [CompositionSlice(name, counts[name]) for name in CATEGORY_ORDER if counts.get(name)]


def composition_insight(slices: Sequence[CompositionSlice], review_count: int) -> str | None:
    total = sum(item.count for item in slices)
    if total <= 0:
        return None
    biggest = max(slices, key=lambda item: item.count)
    return f"{biggest.name} make up {biggest.count / total * 100:.0f}% of the universe; {review_count} leveraged or inverse instruments need manual review."


def enabled_by_tier(records: Sequence[object], policy_states: Mapping[str, str]) -> tuple[list[TierBar], int]:
    """Enabled instruments per tier plus the manual-review count; second value = disabled instruments."""
    bars = [TierBar(tier_label(tier), sum(1 for r in records if r.enabled and str(r.tier).casefold() == tier)) for tier in TIERS]
    review = sum(1 for r in records if needs_manual_review(r, policy_states.get(str(r.instrument_id))))
    disabled = sum(1 for r in records if not r.enabled)
    return [*bars, TierBar(MANUAL_REVIEW, review)], disabled


def tier_insight(bars: Sequence[TierBar]) -> str | None:
    tiers = [bar for bar in bars if bar.label != MANUAL_REVIEW]
    review = next((bar.count for bar in bars if bar.label == MANUAL_REVIEW), 0)
    if not tiers or max(bar.count for bar in tiers) <= 0:
        return None
    top = max(tiers, key=lambda bar: bar.count)
    return f"{top.label} holds most enabled instruments ({top.count}); {review} wait for manual review."


def matches(record: object, *, query: str = "", tier: str | None = None, kind: str = "All") -> bool:
    """Search and filters of the instrument table (tier None = all tiers; kind All / ETF / Stock)."""
    if tier and str(record.tier).casefold() != tier.casefold():
        return False
    if kind != "All" and str(record.asset_type).casefold() != kind.casefold():
        return False
    needle = query.strip().casefold()
    if not needle:
        return True
    hay = " ".join((record.instrument_id, record.name, record.ticker, record.isin, record.region, record.sector, record.theme))
    return needle in hay.casefold()


def subtitle(candidates: int, enabled: int) -> str:
    return f"Instruments the cockpit may use · {candidates:,} candidates · {enabled:,} enabled"


@dataclass(frozen=True)
class PreviewRow:
    name: str
    detail: str
    tag: str
    kind: str


def preview_rows(report: object, existing_ids: Iterable[str]) -> list[PreviewRow]:
    """Import preview: resolved rows are Added (new id) or Unchanged (id already present, never overwritten);
    error findings are Rejected with their reason. Warnings are listed as Changed notes on their row."""
    known = {str(item).casefold() for item in existing_ids}
    rows: list[PreviewRow] = []
    for record in getattr(report, "records", ()):
        added = str(record.instrument_id).casefold() not in known
        rows.append(PreviewRow(record.name or record.instrument_id, f"{record.instrument_id} · {record.ticker or '—'} · {record.isin or '—'}", "Added" if added else "Unchanged", "ok" if added else "mute"))
    for issue in getattr(report, "issues", ()):
        if issue.severity == "error":
            rows.append(PreviewRow(f"Row {issue.row_number}", issue.message, "Rejected", "bad"))
        elif issue.severity == "warning":
            rows.append(PreviewRow(f"Row {issue.row_number}", issue.message, "Changed", "warn"))
    return rows
