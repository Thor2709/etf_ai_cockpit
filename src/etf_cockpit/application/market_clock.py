"""Application facade for presentation-safe market-clock diagnostics."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Mapping

from etf_cockpit.data.market_calendar import (
    ClockContext,
    MarketCalendarService,
    MarketClockError,
)
from etf_cockpit.core.paths import CONFIG_DIR


UTC = timezone.utc


def build_market_clock_diagnostics(
    identity_projection: Mapping[str, object],
    *,
    decision_time: str | date | datetime,
    observed_at: str | date | datetime | None = None,
    maximum_expected_sessions: int = 1,
    service: MarketCalendarService | None = None,
) -> dict[str, object]:
    """Build one fail-closed advisory market-state/staleness view model."""

    try:
        calendar_service = service or MarketCalendarService.from_correction_ledger(
            CONFIG_DIR / "market_calendar_corrections.yaml"
        )
        decision = _instant(decision_time)
        listing = calendar_service.listing_from_identity_projection(identity_projection)
        context = ClockContext.at(decision)
        state = calendar_service.market_state(listing, context)
        payload = state.as_dict()
        payload.update(
            {
                "status": "available"
                if state.certification == "certified"
                else "unavailable",
                "valuation_date": context.valuation_date.isoformat(),
                "decision_time": context.decision_time.isoformat(),
                "trade_date": context.trade_date.isoformat()
                if context.trade_date
                else None,
                "settlement_date": context.settlement_date.isoformat()
                if context.settlement_date
                else None,
                "knowledge_cutoff": context.knowledge_cutoff.isoformat(),
                "advisory_only": True,
                "execution_allowed": False,
            }
        )
        if observed_at is not None and state.certification == "certified":
            staleness = calendar_service.assess_staleness(
                listing,
                observed_at=_instant(observed_at),
                assessed_at=decision,
                maximum_expected_sessions=maximum_expected_sessions,
            )
            payload["staleness"] = staleness.as_dict()
        else:
            payload["staleness"] = {
                "certification": "unavailable",
                "status": "unknown",
                "reason_code": "observation_time_unavailable",
                "execution_allowed": False,
            }
        return payload
    except (MarketClockError, TypeError, ValueError, OverflowError) as exc:
        return {
            "status": "unavailable",
            "certification": "unavailable",
            "reason_code": "market_clock_evidence_unavailable",
            "message": str(exc),
            "phase": "unknown",
            "timezone": "unavailable",
            "next_decision_time": None,
            "next_execution_time": None,
            "staleness": {
                "certification": "unavailable",
                "status": "unknown",
                "reason_code": "market_clock_evidence_unavailable",
                "execution_allowed": False,
            },
            "advisory_only": True,
            "execution_allowed": False,
        }


def _instant(value: str | date | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, UTC)
    else:
        text = str(value).strip()
        if not text:
            raise MarketClockError("market-clock timestamp is required")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(text[:10]), time.min, UTC)
            except ValueError as exc:
                raise MarketClockError("market-clock timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = ["build_market_clock_diagnostics"]
