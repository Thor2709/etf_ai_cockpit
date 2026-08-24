"""Application facade for presentation-safe market-clock diagnostics."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from numbers import Integral
from typing import Mapping
from zoneinfo import ZoneInfo

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
        try:
            settlement = calendar_service.settlement_from_identity_projection(
                identity_projection
            )
        except MarketClockError as exc:
            payload["settlement_calendar"] = {
                "status": "unavailable",
                "reason_code": "declared_settlement_calendar_unavailable",
                "message": str(exc),
                "execution_allowed": False,
            }
        else:
            payload["settlement_calendar"] = {
                "status": "available",
                "settlement_calendar_id": settlement.settlement_calendar_id,
                "calendar_id": settlement.calendar_id,
                "timezone": settlement.timezone,
                "source_id": settlement.source_id,
                "source_version": settlement.source_version,
                "lineage_hash": settlement.lineage_hash,
                "execution_allowed": False,
            }
        if observed_at is not None and state.certification == "certified":
            try:
                staleness = calendar_service.assess_staleness(
                    listing,
                    observed_at=_instant(observed_at),
                    assessed_at=decision,
                    maximum_expected_sessions=maximum_expected_sessions,
                )
            except MarketClockError as exc:
                payload["staleness"] = {
                    "certification": "unavailable",
                    "status": "unknown",
                    "reason_code": "observation_cutoff_invalid",
                    "message": str(exc),
                    "execution_allowed": False,
                }
            else:
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


def operational_calendar_record_is_canonical(
    record: Mapping[str, object],
    *,
    instrument_id: str,
    signal_timestamp: object,
    execution_timestamp: object,
    signal_date: date,
    execution_date: date,
) -> bool:
    """Revalidate persisted operational calendar lineage for presentation."""

    text_fields = (
        "calendar_listing_id",
        "calendar_mic",
        "calendar_id",
        "calendar_timezone",
        "calendar_source_id",
        "calendar_source_checksum",
        "calendar_source_version",
        "calendar_identity_decision_id",
        "calendar_valid_from",
        "calendar_known_at",
        "calendar_identity_lineage_hash",
        "calendar_session_lineage_hash",
    )
    if any(type(record.get(field)) is not str or not str(record[field]).strip() for field in text_fields):
        return False
    hashes = (
        record["calendar_source_checksum"],
        record["calendar_identity_lineage_hash"],
        record["calendar_session_lineage_hash"],
    )
    if any(len(str(value)) != 64 for value in hashes):
        return False
    auction_fields = (
        record.get("calendar_opening_auction_minutes"),
        record.get("calendar_closing_auction_minutes"),
    )
    if any(not isinstance(value, Integral) or isinstance(value, bool) or value < 0 for value in auction_fields):
        return False
    projection = {
        "status": "available",
        "instrument_id": instrument_id,
        "identity_decision_id": record["calendar_identity_decision_id"],
        "identity_decision_time": record["calendar_known_at"],
        "identity_effective_at": record["calendar_valid_from"],
        "identity_objects": [
            {
                "object_type": "listing",
                "object_id": record["calendar_listing_id"],
                "fields": {
                    "mic": record["calendar_mic"],
                    "calendar_id": record["calendar_id"],
                    "timezone": record["calendar_timezone"],
                    "calendar_source_version": record["calendar_source_version"],
                    "opening_auction_minutes": record["calendar_opening_auction_minutes"],
                    "closing_auction_minutes": record["calendar_closing_auction_minutes"],
                },
            }
        ],
        "identity_history": [{"source_id": record["calendar_source_id"]}],
    }
    try:
        service = MarketCalendarService.from_correction_ledger(
            CONFIG_DIR / "market_calendar_corrections.yaml"
        )
        listing = service.listing_from_identity_projection(projection)
        if (
            listing.source_checksum != record["calendar_source_checksum"]
            or listing.lineage_hash != record["calendar_identity_lineage_hash"]
        ):
            return False
        signal_instant = _explicit_instant(signal_timestamp)
        execution_instant = _explicit_instant(execution_timestamp)
        zone = ZoneInfo(listing.timezone)
        signal_day = signal_instant.astimezone(zone).date()
        execution_day = execution_instant.astimezone(zone).date()
        cutoff = signal_instant
        if signal_date != signal_day or execution_date != execution_day:
            return False
        if not service.is_business_day(listing, signal_day, knowledge_cutoff=cutoff):
            return False
        if not service.is_business_day(listing, execution_day, knowledge_cutoff=cutoff):
            return False
        candidate = signal_day + timedelta(days=1)
        for _ in range(370):
            if service.is_business_day(listing, candidate, knowledge_cutoff=cutoff):
                break
            candidate += timedelta(days=1)
        else:
            return False
        if candidate != execution_day:
            return False
        signal_state = service.market_state(
            listing, ClockContext.at(signal_instant, knowledge_cutoff=cutoff)
        )
        execution_state = service.market_state(
            listing, ClockContext.at(execution_instant, knowledge_cutoff=cutoff)
        )
        if signal_state.certification != "certified" or execution_state.certification != "certified":
            return False
        if signal_state.session_close is None or signal_instant < signal_state.session_close:
            return False
        if execution_state.session_close is None or execution_instant < execution_state.session_close:
            return False
        lineage_payload = {
            "listing": listing.lineage_hash,
            "signal_state": signal_state.lineage_hash,
            "execution_state": execution_state.lineage_hash,
            "signal_date": signal_day.isoformat(),
            "execution_date": execution_day.isoformat(),
        }
        expected = hashlib.sha256(
            json.dumps(lineage_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return expected == record["calendar_session_lineage_hash"]
    except (MarketClockError, TypeError, ValueError, OverflowError, AttributeError):
        return False


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


def _explicit_instant(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str and value.strip() == value and "T" in value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MarketClockError("market-clock timestamp is invalid") from exc
    else:
        raise MarketClockError("market-clock timestamp must be an explicit instant")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MarketClockError("market-clock timestamp must include a timezone offset")
    return parsed.astimezone(UTC)


__all__ = [
    "build_market_clock_diagnostics",
    "operational_calendar_record_is_canonical",
]
