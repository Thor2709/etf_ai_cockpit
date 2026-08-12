"""Bounded, deterministic Dashboard context digest.

This module only formats already-available local evidence.  It does not fetch
data, infer missing facts, or grant execution authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math
from typing import Any

import pandas as pd

from etf_cockpit.data.news_context import NEWS_SCHEMA_VERSION, NewsItem, validate_news_item


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


def score_run_pair_as_of(
    history: pd.DataFrame,
    cutoff: object,
) -> tuple[pd.DataFrame, str, str] | None:
    """Return the latest two timestamp-attributable score runs at ``cutoff``."""

    if not isinstance(history, pd.DataFrame) or history.empty:
        return None
    if not {"run_id", "run_completed_at"} <= set(history.columns):
        return None
    cutoff_ts = _aware_utc(cutoff)
    if cutoff_ts is None:
        return None

    eligible: list[tuple[pd.Timestamp, str]] = []
    for run_id, rows in history.groupby(history["run_id"].astype(str), sort=False):
        timestamps = tuple(rows["run_completed_at"].map(_aware_utc))
        if not timestamps or any(timestamp is None for timestamp in timestamps):
            continue
        unique = {timestamp.isoformat() for timestamp in timestamps if timestamp is not None}
        if len(unique) != 1:
            continue
        timestamp = next(timestamp for timestamp in timestamps if timestamp is not None)
        if timestamp <= cutoff_ts:
            eligible.append((timestamp, str(run_id)))
    eligible.sort(key=lambda item: (item[0], item[1]))
    if len(eligible) < 2:
        return None
    previous, current = eligible[-2][1], eligible[-1][1]
    selected = history.loc[history["run_id"].astype(str).isin({previous, current})].copy()
    return selected, current, previous


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
    required_news = {
        "schema_version",
        "news_id",
        "instrument_id",
        "headline",
        "published_at",
        "ingested_at",
        "available_at_decision_time",
        "timestamp_status",
        "backtest_eligible",
        "timestamp_confidence",
        "source_url",
        "provider_name",
        "source_authority",
        "instrument_mapping_method",
        "context_only",
        "executable_authority",
    }
    if not required_news <= set(news.columns):
        return None
    if not {"date", "adjusted_close"} <= set(prices.columns) or not {"instrument_id", "etf_id"}.intersection(prices.columns):
        return None
    cutoff_ts = _aware_utc(cutoff)
    if cutoff_ts is None:
        return None

    news_frame = news.copy()
    if not all(_canonical_news_row(row) for _, row in news_frame.iterrows()):
        return None
    published = news_frame["published_at"].map(_aware_utc)
    ingested = news_frame["ingested_at"].map(_aware_utc)
    news_frame = news_frame.loc[
        published.notna()
        & ingested.notna()
        & (published <= cutoff_ts)
        & (ingested <= cutoff_ts)
    ].copy()

    price_frame = prices.copy()
    instrument_ids = _normalise_price_identity(price_frame)
    if instrument_ids is None:
        return None
    price_frame["instrument_id"] = instrument_ids
    news_instruments = set(news_frame["instrument_id"].astype(str).str.strip())
    price_frame = price_frame.loc[price_frame["instrument_id"].isin(news_instruments)].copy()
    if price_frame.empty:
        return None
    price_dates = pd.to_datetime(price_frame["date"], errors="coerce")
    if bool(price_dates.isna().any()):
        return None
    within_cutoff = price_dates.dt.date <= cutoff_ts.date()
    price_frame = price_frame.loc[within_cutoff].copy()
    price_dates = price_dates.loc[price_frame.index]
    if price_frame.empty:
        return None
    adjusted_close = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    finite_positive = adjusted_close.map(
        lambda value: bool(pd.notna(value) and math.isfinite(float(value)) and float(value) > 0)
    )
    if not bool(finite_positive.all()):
        return None
    price_frame["adjusted_close"] = adjusted_close
    price_frame["_digest_date"] = price_dates.dt.date
    for _, item in news_frame.iterrows():
        published = _aware_utc(item["published_at"])
        if published is None:
            return None
        scoped = price_frame.loc[price_frame["instrument_id"].eq(str(item["instrument_id"]).strip())]
        if scoped.loc[scoped["_digest_date"] <= published.date()].empty:
            return None
        if scoped.loc[scoped["_digest_date"] > published.date()].empty:
            return None
    return (
        news_frame.reset_index(drop=True),
        price_frame.drop(columns=["_digest_date"], errors="ignore").reset_index(drop=True),
    )


def _canonical_news_row(row: pd.Series) -> bool:
    if _scalar_text(row.get("schema_version")) != NEWS_SCHEMA_VERSION:
        return False
    if not all(
        _scalar_text(row.get(field))
        for field in (
            "news_id",
            "instrument_id",
            "headline",
            "source_url",
            "provider_name",
            "source_authority",
            "instrument_mapping_method",
        )
    ):
        return False
    for canonical, alias in (
        ("provider_name", "provider"),
        ("source_url", "url"),
        ("source_authority", "source"),
    ):
        canonical_value = _scalar_text(row.get(canonical))
        alias_value = _scalar_text(row.get(alias))
        if alias_value and canonical_value != alias_value:
            return False
    available = _canonical_bool(row.get("available_at_decision_time"))
    backtest_eligible = _canonical_bool(row.get("backtest_eligible"))
    context_only = _canonical_bool(row.get("context_only"))
    executable_authority = _canonical_bool(row.get("executable_authority"))
    if available is not True or backtest_eligible is not True or context_only is not True or executable_authority is not False:
        return False
    published = _aware_utc(row.get("published_at"))
    ingested = _aware_utc(row.get("ingested_at"))
    if published is None or ingested is None or ingested < published:
        return False
    item = NewsItem(
        news_id=_scalar_text(row["news_id"]),
        instrument_id=_scalar_text(row["instrument_id"]),
        source=_scalar_text(row["source_authority"]),
        provider_name=_scalar_text(row["provider_name"]),
        headline=_scalar_text(row["headline"]),
        published_at=_scalar_text(row["published_at"]),
        ingested_at=_scalar_text(row["ingested_at"]),
        source_url=_scalar_text(row["source_url"]),
        instrument_mapping_method=_scalar_text(row["instrument_mapping_method"]),
        available_at_decision_time=available,
        timestamp_confidence=_scalar_text(row["timestamp_confidence"]),
        current_only=_canonical_bool(row.get("current_only")) is True,
        revised=_canonical_bool(row.get("revised")) is True,
        context_only=context_only,
        executable_authority=executable_authority,
    )
    validation = validate_news_item(item, max(published, ingested).to_pydatetime())
    return (
        validation.status == "valid_context"
        and validation.backtest_eligible is True
        and _scalar_text(row["timestamp_status"]) == validation.status
        and _scalar_text(row["timestamp_confidence"]) == validation.timestamp_confidence
        and backtest_eligible is validation.backtest_eligible
        and available is validation.available_at_decision_time
    )


def _normalise_price_identity(frame: pd.DataFrame) -> pd.Series | None:
    instrument = (
        frame["instrument_id"].map(_scalar_text)
        if "instrument_id" in frame.columns
        else pd.Series("", index=frame.index, dtype=str)
    )
    etf = (
        frame["etf_id"].map(_scalar_text)
        if "etf_id" in frame.columns
        else pd.Series("", index=frame.index, dtype=str)
    )
    if bool((instrument.ne("") & etf.ne("") & instrument.ne(etf)).any()):
        return None
    return instrument.where(instrument.ne(""), etf)


def _canonical_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if type(value).__module__ == "numpy" and type(value).__name__ == "bool_":
        return bool(value)
    return None


def _scalar_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _aware_utc(value: object) -> pd.Timestamp | None:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp.tz_convert("UTC")


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
    "score_run_pair_as_of",
]
