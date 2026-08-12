"""Bounded, deterministic Dashboard context digest.

This module only formats already-available local evidence.  It does not fetch
data, infer missing facts, or grant execution authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd


DIGEST_SOURCES = (
    "score_changes",
    "warning_changes",
    "alerts",
    "model_failures",
    "contradictions",
    "manual_review",
    "upcoming_events",
    "stale_data",
    "audit_export",
)
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_STATUS_ORDER = {"manual_review": 0, "unavailable": 1, "available": 2}
_VALID_STATUSES = frozenset(_STATUS_ORDER)
_VALID_SEVERITIES = frozenset(_SEVERITY_ORDER)
MAX_DIGEST_ITEMS = 12


def filter_news_contradiction_inputs(
    news: pd.DataFrame,
    prices: pd.DataFrame,
    cutoff: object,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Keep only point-in-time news and prices usable at ``cutoff``.

    This is deliberately a small projection for the Dashboard contradiction
    view.  It does not infer missing timestamps or make a historical snapshot
    from current-only evidence.
    """

    if not isinstance(news, pd.DataFrame) or not isinstance(prices, pd.DataFrame) or news.empty or prices.empty:
        return None
    if not {"instrument_id", "published_at", "ingested_at", "available_at_decision_time", "headline"} <= set(news.columns):
        return None
    if not {"instrument_id", "date", "adjusted_close"} <= set(prices.columns):
        return None
    cutoff_ts = _aware_utc(cutoff)
    if cutoff_ts is None:
        return None

    news_frame = news.copy()
    published = news_frame["published_at"].map(_aware_utc)
    ingested = news_frame["ingested_at"].map(_aware_utc)
    available = news_frame["available_at_decision_time"].map(_is_true)
    news_frame = news_frame.loc[
        available & published.notna() & ingested.notna() & (published <= cutoff_ts) & (ingested <= cutoff_ts)
    ].copy()

    price_frame = prices.copy()
    price_dates = pd.to_datetime(price_frame["date"], errors="coerce")
    adjusted_close = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    instrument_ids = price_frame["instrument_id"].astype(str).str.strip()
    price_frame = price_frame.loc[
        price_dates.notna()
        & adjusted_close.notna()
        & instrument_ids.ne("")
        & (price_dates.dt.date <= cutoff_ts.date())
    ].copy()
    price_frame["adjusted_close"] = adjusted_close.loc[price_frame.index]
    if news_frame.empty or price_frame.empty:
        return None
    return news_frame.reset_index(drop=True), price_frame.reset_index(drop=True)


def _aware_utc(value: object) -> pd.Timestamp | None:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp.tz_convert("UTC")


def _is_true(value: object) -> bool:
    return (isinstance(value, bool) and value) or str(value).strip().casefold() == "true"


@dataclass(frozen=True)
class DigestItem:
    source: str
    title: str
    detail: str
    status: str
    severity: str
    as_of: str | None = None
    provenance: str = "local application evidence"
    execution_allowed: bool = False


@dataclass(frozen=True)
class DashboardDigest:
    items: tuple[DigestItem, ...]
    source_status: tuple[tuple[str, str], ...]
    as_of: str | None = None
    execution_allowed: bool = False


def build_digest(
    records: Mapping[str, Iterable[Mapping[str, object]] | None],
    *,
    as_of: str | None = None,
) -> DashboardDigest:
    """Build a stable, bounded digest from category records.

    ``None`` or an empty iterable means that the source is unavailable.  A
    caller can represent a healthy empty source with one explicit informational
    record, which keeps the distinction between "nothing found" and "not
    checked" visible to the user.
    """

    items: list[DigestItem] = []
    source_status: list[tuple[str, str]] = []
    for source_index, source in enumerate(DIGEST_SOURCES):
        raw_records = tuple(records.get(source) or ())
        if not raw_records:
            source_status.append((source, "unavailable"))
            continue
        source_items = tuple(
            _item_from_record(source, index, record, as_of=as_of)
            for index, record in enumerate(raw_records)
        )
        status = "manual_review" if any(item.status == "manual_review" for item in source_items) else (
            "unavailable" if any(item.status == "unavailable" for item in source_items) else "available"
        )
        source_status.append((source, status))
        items.extend(source_items)

    if not items:
        items.append(
            DigestItem(
                source="digest",
                title="No local digest evidence is available",
                detail="The Dashboard cannot prioritise today's context until its local evidence sources are available.",
                status="manual_review",
                severity="warning",
                as_of=as_of,
                provenance="application.digest",
            )
        )

    ordered = sorted(
        enumerate(items),
        key=lambda pair: (
            _SEVERITY_ORDER[pair[1].severity],
            _STATUS_ORDER[pair[1].status],
            _source_order(pair[1].source, source_status),
            pair[1].title,
            pair[0],
        ),
    )
    return DashboardDigest(
        items=tuple(item for _, item in ordered[:MAX_DIGEST_ITEMS]),
        source_status=tuple(source_status),
        as_of=as_of,
    )


def _item_from_record(
    source: str,
    index: int,
    record: Mapping[str, object],
    *,
    as_of: str | None,
) -> DigestItem:
    title = _text(record.get("title")) or f"{source.replace('_', ' ').title()} requires review"
    detail = _text(record.get("detail") or record.get("message"))
    provenance = _text(record.get("provenance")) or "unavailable"
    status = _normalise(record.get("status"), _VALID_STATUSES, "manual_review")
    severity = _normalise(record.get("severity"), _VALID_SEVERITIES, "warning" if status != "available" else "info")
    if not detail:
        detail = "The source did not provide a readable explanation; manual review is required."
        status = "manual_review"
    return DigestItem(
        source=source,
        title=title,
        detail=detail,
        status=status,
        severity=severity,
        as_of=_text(record.get("as_of")) or as_of,
        provenance=provenance,
    )


def _source_order(source: str, source_status: list[tuple[str, str]]) -> int:
    del source_status
    try:
        return DIGEST_SOURCES.index(source)
    except ValueError:
        return len(DIGEST_SOURCES)


def _normalise(value: object, accepted: frozenset[str], fallback: str) -> str:
    text = _text(value)
    return text.casefold() if text and text.casefold() in accepted else fallback


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "DIGEST_SOURCES",
    "DashboardDigest",
    "DigestItem",
    "MAX_DIGEST_ITEMS",
    "build_digest",
    "filter_news_contradiction_inputs",
]
