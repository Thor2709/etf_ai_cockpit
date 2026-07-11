from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class NewsItem:
    news_id: str
    instrument_id: str
    source: str
    provider: str
    headline: str
    published_at: str
    ingested_at: str
    url: str
    credibility: str


@dataclass(frozen=True)
class NewsValidation:
    status: str
    backtest_eligible: bool
    reason: str
    context_only: bool = True


def validate_news_item(item: NewsItem, decision_time: datetime) -> NewsValidation:
    try:
        published = datetime.fromisoformat(item.published_at)
        ingested = datetime.fromisoformat(item.ingested_at) if item.ingested_at else None
    except ValueError:
        return NewsValidation("ambiguous_timestamp", False, "Published/ingested timestamp is not ISO-8601 with timezone.")
    if published.tzinfo is None or ingested is None or ingested.tzinfo is None:
        return NewsValidation("ambiguous_timestamp", False, "Published/ingested timestamp must include timezone.")
    decision = decision_time if decision_time.tzinfo else decision_time.replace(tzinfo=timezone.utc)
    if published > decision or ingested > decision:
        return NewsValidation("after_decision_time", False, "News was not available at the decision time.")
    if not item.source or not item.provider or not item.instrument_id:
        return NewsValidation("missing_provenance", False, "News source, provider and instrument mapping are required.")
    return NewsValidation("valid_context", True, "Timestamp and provenance are valid; news remains context-only.")
