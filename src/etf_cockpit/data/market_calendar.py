"""Certified, local-first exchange calendar and financial-clock service.

The service keeps calendar calculations behind one internal API.  It consumes
immutable listing identity evidence, delegates exchange schedules to the
licence-reviewed :mod:`exchange_calendars` dependency, applies point-in-time
manual corrections, and always remains advisory (``execution_allowed=False``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import exchange_calendars as xcals
import pandas as pd
import yaml  # type: ignore[import-untyped]


MARKET_CALENDAR_CONTRACT = "market-calendar.v1"
MARKET_CALENDAR_CORRECTIONS_SCHEMA = "market-calendar-corrections.v1"
CALENDAR_LIBRARY = "exchange_calendars"
CALENDAR_LIBRARY_VERSION = str(getattr(xcals, "__version__", "unavailable"))
UTC = timezone.utc
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MarketClockError(ValueError):
    """Raised when calendar or clock evidence cannot be certified."""


class BusinessDayConvention(StrEnum):
    UNADJUSTED = "unadjusted"
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"
    MODIFIED_PRECEDING = "modified_preceding"


class DayCountConvention(StrEnum):
    ACT_360 = "ACT/360"
    ACT_365F = "ACT/365F"
    ACT_ACT_ISDA = "ACT/ACT-ISDA"
    THIRTY_360_US = "30/360-US"
    THIRTY_E_360 = "30E/360"


@dataclass(frozen=True)
class ListingCalendarEvidence:
    """Immutable MIC/calendar/timezone link supplied by the identity master."""

    listing_id: str
    mic: str
    calendar_id: str
    timezone: str
    source_id: str
    source_checksum: str
    valid_from: date
    known_at: datetime
    source_version: str = "1"
    valid_to: date | None = None
    conflict_ids: tuple[str, ...] = ()
    opening_auction_minutes: int = 0
    closing_auction_minutes: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "listing_id",
            "mic",
            "calendar_id",
            "timezone",
            "source_id",
            "source_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise MarketClockError(f"listing calendar {field_name} is required")
        if self.known_at.tzinfo is None:
            raise MarketClockError("listing calendar known_at must be timezone-aware")
        if not _SHA256.fullmatch(self.source_checksum.casefold()):
            raise MarketClockError(
                "listing calendar source_checksum must be a SHA-256 digest"
            )
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise MarketClockError("listing calendar valid_to must follow valid_from")
        if self.conflict_ids:
            raise MarketClockError("listing calendar evidence must be conflict-free")
        if self.opening_auction_minutes < 0 or self.closing_auction_minutes < 0:
            raise MarketClockError("listing auction windows cannot be negative")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise MarketClockError(
                f"listing calendar timezone is unknown: {self.timezone}"
            ) from exc

    @property
    def lineage_hash(self) -> str:
        return _hash(asdict(self))


@dataclass(frozen=True)
class ClockContext:
    """Financial dates/times that must never be silently collapsed."""

    valuation_date: date
    decision_time: datetime
    trade_date: date | None
    settlement_date: date | None
    knowledge_cutoff: datetime

    def __post_init__(self) -> None:
        if self.decision_time.tzinfo is None or self.knowledge_cutoff.tzinfo is None:
            raise MarketClockError(
                "decision_time and knowledge_cutoff must be timezone-aware"
            )
        if self.knowledge_cutoff > self.decision_time:
            raise MarketClockError("knowledge_cutoff cannot follow decision_time")

    @classmethod
    def at(
        cls,
        decision_time: datetime,
        *,
        valuation_date: date | None = None,
        trade_date: date | None = None,
        settlement_date: date | None = None,
        knowledge_cutoff: datetime | None = None,
    ) -> ClockContext:
        if decision_time.tzinfo is None:
            raise MarketClockError("decision_time must be timezone-aware")
        instant = decision_time.astimezone(UTC)
        return cls(
            valuation_date=valuation_date or instant.date(),
            decision_time=instant,
            trade_date=trade_date,
            settlement_date=settlement_date,
            knowledge_cutoff=(knowledge_cutoff or instant).astimezone(UTC),
        )


@dataclass(frozen=True)
class CalendarCorrection:
    correction_id: str
    mic: str
    session_date: date
    kind: str
    revision: int
    reason: str
    source_id: str
    source_checksum: str
    valid_from: date
    known_at: datetime
    source_version: str = "1"
    open_time: time | None = None
    close_time: time | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"exceptional_closure", "modified_session"}:
            raise MarketClockError(f"unsupported calendar correction kind: {self.kind}")
        if self.revision < 1:
            raise MarketClockError("calendar correction revision must be positive")
        if self.known_at.tzinfo is None:
            raise MarketClockError(
                "calendar correction known_at must be timezone-aware"
            )
        if not all(
            str(value).strip()
            for value in (
                self.correction_id,
                self.mic,
                self.reason,
                self.source_id,
                self.source_version,
            )
        ):
            raise MarketClockError(
                "calendar correction identity, MIC, reason, source and version are required"
            )
        if not _SHA256.fullmatch(self.source_checksum.casefold()):
            raise MarketClockError(
                "calendar correction source_checksum must be a SHA-256 digest"
            )
        if self.kind == "modified_session" and (
            self.open_time is None or self.close_time is None
        ):
            raise MarketClockError(
                "modified-session corrections require open_time and close_time"
            )

    @classmethod
    def exceptional_closure(cls, **values: Any) -> CalendarCorrection:
        return cls(kind="exceptional_closure", **values)


@dataclass(frozen=True)
class MarketState:
    certification: str
    reason_code: str
    mic: str
    calendar_id: str
    timezone: str
    phase: str
    is_session: bool
    is_auction: bool
    early_close: bool
    exceptional_closure: bool
    session_open: datetime | None
    session_close: datetime | None
    next_decision_time: datetime | None
    next_execution_time: datetime | None
    correction_ids: tuple[str, ...]
    calendar_source: str
    calendar_version: str
    identity_lineage_hash: str
    lineage_hash: str
    execution_allowed: bool = False

    def as_dict(self) -> dict[str, object]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class StalenessAssessment:
    certification: str
    status: str
    expected_sessions_elapsed: int | None
    maximum_expected_sessions: int
    reason_code: str
    lineage_hash: str
    execution_allowed: bool = False

    def as_dict(self) -> dict[str, object]:
        return _jsonable(asdict(self))


class MarketCalendarService:
    """Canonical calendar/session/day-count API with point-in-time corrections."""

    def __init__(self, *, corrections: Iterable[CalendarCorrection] = ()) -> None:
        self._corrections = tuple(corrections)
        identifiers = [item.correction_id for item in self._corrections]
        if len(identifiers) != len(set(identifiers)):
            raise MarketClockError(
                "calendar correction_id values must be immutable and unique"
            )
        versions: dict[tuple[str, date, str], list[CalendarCorrection]] = {}
        for item in self._corrections:
            versions.setdefault(
                (item.mic.upper(), item.session_date, item.kind), []
            ).append(item)
        for group in versions.values():
            ordered = sorted(group, key=lambda item: item.revision)
            if [item.revision for item in ordered] != list(range(1, len(ordered) + 1)):
                raise MarketClockError(
                    "calendar correction revisions must be contiguous from one"
                )
            if any(
                right.known_at <= left.known_at
                for left, right in zip(ordered, ordered[1:])
            ):
                raise MarketClockError(
                    "calendar correction knowledge time must advance with revision"
                )

    @classmethod
    def from_correction_ledger(cls, path: str | Path) -> MarketCalendarService:
        return cls(corrections=load_calendar_corrections(path))

    def market_state(
        self, listing: ListingCalendarEvidence, context: ClockContext
    ) -> MarketState:
        instant = context.decision_time.astimezone(UTC)
        identity_reason = self._identity_reason(listing, context)
        calendar = (
            self._calendar(listing, instant.date()) if identity_reason is None else None
        )
        if identity_reason is not None or calendar is None:
            return self._unavailable_state(
                listing, identity_reason or "unknown_calendar"
            )

        local_date = instant.astimezone(ZoneInfo(listing.timezone)).date()
        corrections = self._active_corrections(
            listing.mic, local_date, context.knowledge_cutoff
        )
        closure = next(
            (item for item in corrections if item.kind == "exceptional_closure"), None
        )
        schedule = calendar.schedule[
            calendar.schedule.index == pd.Timestamp(local_date)
        ]
        if closure is not None:
            schedule = schedule.iloc[0:0]
        if schedule.empty:
            next_open = self._next_open(
                calendar, instant, listing, context.knowledge_cutoff
            )
            return self._state(
                listing,
                phase="closed",
                is_session=False,
                is_auction=False,
                early_close=False,
                exceptional_closure=closure is not None,
                session_open=None,
                session_close=None,
                next_decision_time=next_open,
                next_execution_time=next_open,
                corrections=corrections,
            )

        row = schedule.iloc[0]
        session_open = _utc_datetime(row["open"])
        session_close = _utc_datetime(row["close"])
        modified = next(
            (item for item in corrections if item.kind == "modified_session"), None
        )
        if modified is not None:
            zone = ZoneInfo(listing.timezone)
            assert modified.open_time is not None and modified.close_time is not None
            session_open = datetime.combine(
                local_date, modified.open_time, zone
            ).astimezone(UTC)
            session_close = datetime.combine(
                local_date, modified.close_time, zone
            ).astimezone(UTC)
        break_start = _optional_utc_datetime(row.get("break_start"))
        break_end = _optional_utc_datetime(row.get("break_end"))
        early_close = (
            bool(local_date in {item.date() for item in calendar.early_closes})
            or modified is not None
        )

        opening_auction = (
            listing.opening_auction_minutes > 0
            and session_open - timedelta(minutes=listing.opening_auction_minutes)
            <= instant
            < session_open
        )
        closing_auction = (
            listing.closing_auction_minutes > 0
            and session_close - timedelta(minutes=listing.closing_auction_minutes)
            <= instant
            < session_close
        )
        in_break = (
            break_start is not None
            and break_end is not None
            and break_start <= instant < break_end
        )
        if opening_auction:
            phase = "opening_auction"
        elif closing_auction:
            phase = "closing_auction"
        elif session_open <= instant < session_close and not in_break:
            phase = "open"
        elif in_break:
            phase = "break"
        elif instant < session_open:
            phase = "pre_open"
        else:
            phase = "post_close"
        is_auction = opening_auction or closing_auction
        next_decision = (
            instant
            if phase in {"open", "opening_auction", "closing_auction"}
            else (
                break_end
                if phase == "break"
                else session_open
                if phase == "pre_open"
                else self._next_open(
                    calendar, instant, listing, context.knowledge_cutoff
                )
            )
        )
        next_execution = (
            session_open
            if phase == "opening_auction"
            else session_close
            if phase == "closing_auction"
            else next_decision
        )
        return self._state(
            listing,
            phase=phase,
            is_session=True,
            is_auction=is_auction,
            early_close=early_close,
            exceptional_closure=False,
            session_open=session_open,
            session_close=session_close,
            next_decision_time=next_decision,
            next_execution_time=next_execution,
            corrections=corrections,
        )

    def assess_staleness(
        self,
        listing: ListingCalendarEvidence,
        *,
        observed_at: datetime,
        assessed_at: datetime,
        maximum_expected_sessions: int,
        knowledge_cutoff: datetime | None = None,
    ) -> StalenessAssessment:
        if maximum_expected_sessions < 0:
            raise MarketClockError("maximum_expected_sessions cannot be negative")
        if observed_at.tzinfo is None or assessed_at.tzinfo is None:
            raise MarketClockError("staleness timestamps must be timezone-aware")
        if assessed_at < observed_at:
            raise MarketClockError("assessed_at cannot precede observed_at")
        context = ClockContext.at(assessed_at, knowledge_cutoff=knowledge_cutoff)
        reason = self._identity_reason(listing, context)
        calendar = (
            self._calendar(listing, assessed_at.date()) if reason is None else None
        )
        if calendar is None:
            lineage = _hash(
                {
                    "listing": listing.lineage_hash,
                    "reason": reason or "unknown_calendar",
                }
            )
            return StalenessAssessment(
                "unavailable",
                "unknown",
                None,
                maximum_expected_sessions,
                reason or "unknown_calendar",
                lineage,
            )
        zone = ZoneInfo(listing.timezone)
        start = observed_at.astimezone(zone).date()
        end = assessed_at.astimezone(zone).date()
        sessions = [
            item.date() for item in calendar.sessions_in_range(str(start), str(end))
        ]
        cutoff = context.knowledge_cutoff
        active_closures = {
            day
            for day in sessions
            if any(
                item.kind == "exceptional_closure"
                for item in self._active_corrections(listing.mic, day, cutoff)
            )
        }
        elapsed = sum(
            1 for day in sessions if day > start and day not in active_closures
        )
        status = "fresh" if elapsed <= maximum_expected_sessions else "stale"
        lineage = _hash(
            {
                "contract": MARKET_CALENDAR_CONTRACT,
                "listing": listing.lineage_hash,
                "sessions": [day.isoformat() for day in sessions],
                "closures": sorted(day.isoformat() for day in active_closures),
                "observed_at": observed_at,
                "assessed_at": assessed_at,
                "maximum": maximum_expected_sessions,
            }
        )
        return StalenessAssessment(
            "certified",
            status,
            elapsed,
            maximum_expected_sessions,
            "expected_sessions",
            lineage,
        )

    def is_business_day(
        self,
        listing: ListingCalendarEvidence,
        value: date,
        *,
        knowledge_cutoff: datetime | None = None,
    ) -> bool:
        cutoff = knowledge_cutoff or datetime.combine(value, time.max, UTC)
        context = ClockContext.at(cutoff)
        if self._identity_reason(listing, context) is not None:
            raise MarketClockError("business-day calendar is uncertified")
        calendar = self._calendar(listing, value)
        if calendar is None:
            raise MarketClockError("business-day calendar is unknown")
        if any(
            item.kind == "exceptional_closure"
            for item in self._active_corrections(listing.mic, value, cutoff)
        ):
            return False
        return bool(calendar.is_session(str(value)))

    def adjust_business_day(
        self,
        listing: ListingCalendarEvidence,
        value: date,
        convention: BusinessDayConvention,
        *,
        knowledge_cutoff: datetime | None = None,
    ) -> date:
        convention = BusinessDayConvention(convention)
        if convention == BusinessDayConvention.UNADJUSTED or self.is_business_day(
            listing, value, knowledge_cutoff=knowledge_cutoff
        ):
            return value
        forward = convention in {
            BusinessDayConvention.FOLLOWING,
            BusinessDayConvention.MODIFIED_FOLLOWING,
        }
        candidate = self._walk_business_days(
            listing, value, 1 if forward else -1, knowledge_cutoff
        )
        if (
            convention == BusinessDayConvention.MODIFIED_FOLLOWING
            and candidate.month != value.month
        ):
            candidate = self._walk_business_days(listing, value, -1, knowledge_cutoff)
        if (
            convention == BusinessDayConvention.MODIFIED_PRECEDING
            and candidate.month != value.month
        ):
            candidate = self._walk_business_days(listing, value, 1, knowledge_cutoff)
        return candidate

    def settlement_date(
        self,
        listing: ListingCalendarEvidence,
        trade_date: date,
        settlement_business_days: int,
        *,
        knowledge_cutoff: datetime | None = None,
    ) -> date:
        if settlement_business_days < 0:
            raise MarketClockError("settlement_business_days cannot be negative")
        candidate = self.adjust_business_day(
            listing,
            trade_date,
            BusinessDayConvention.FOLLOWING,
            knowledge_cutoff=knowledge_cutoff,
        )
        for _ in range(settlement_business_days):
            candidate = self._walk_business_days(
                listing, candidate, 1, knowledge_cutoff
            )
        return candidate

    @staticmethod
    def year_fraction(start: date, end: date, convention: DayCountConvention) -> float:
        convention = DayCountConvention(convention)
        if end < start:
            return -MarketCalendarService.year_fraction(end, start, convention)
        if start == end:
            return 0.0
        if convention == DayCountConvention.ACT_360:
            return (end - start).days / 360.0
        if convention == DayCountConvention.ACT_365F:
            return (end - start).days / 365.0
        if convention == DayCountConvention.THIRTY_E_360:
            return (
                (end.year - start.year) * 360
                + (end.month - start.month) * 30
                + min(end.day, 30)
                - min(start.day, 30)
            ) / 360.0
        if convention == DayCountConvention.THIRTY_360_US:
            d1 = 30 if start.day == 31 else start.day
            d2 = 30 if end.day == 31 and d1 == 30 else end.day
            return (
                (end.year - start.year) * 360 + (end.month - start.month) * 30 + d2 - d1
            ) / 360.0
        cursor = start
        fraction = 0.0
        while cursor < end:
            boundary = min(end, date(cursor.year + 1, 1, 1))
            denominator = 366.0 if _is_leap(cursor.year) else 365.0
            fraction += (boundary - cursor).days / denominator
            cursor = boundary
        return fraction

    @staticmethod
    def listing_from_identity_projection(
        projection: Mapping[str, object],
    ) -> ListingCalendarEvidence:
        if projection.get("status") != "available" or projection.get(
            "identity_conflict_ids"
        ):
            raise MarketClockError("identity projection is unavailable or conflicted")
        objects = projection.get("identity_objects")
        if not isinstance(objects, list):
            raise MarketClockError("identity projection has no immutable objects")
        candidates: list[Mapping[str, object]] = []
        for item in objects:
            if not isinstance(item, Mapping) or str(
                item.get("object_type", "")
            ).casefold() not in {"listing", "quotation"}:
                continue
            fields = item.get("fields")
            if isinstance(fields, Mapping) and all(
                str(fields.get(key, "")).strip()
                for key in ("mic", "calendar_id", "timezone")
            ):
                candidates.append(item)
        if len(candidates) != 1:
            raise MarketClockError(
                "identity projection must resolve exactly one calendar-certified listing"
            )
        item = candidates[0]
        fields = item["fields"]
        assert isinstance(fields, Mapping)
        history = projection.get("identity_history")
        source_ids = (
            sorted(
                {
                    str(row.get("source_id"))
                    for row in history
                    if isinstance(row, Mapping) and row.get("source_id")
                }
            )
            if isinstance(history, list)
            else []
        )
        source_payload = {
            "instrument_id": projection.get("instrument_id"),
            "object": item,
            "decision_id": projection.get("identity_decision_id"),
            "sources": source_ids,
        }
        known_raw = projection.get("identity_decision_time")
        effective_raw = projection.get("identity_effective_at")
        if known_raw in {None, "latest"} or effective_raw in {None, "latest"}:
            raise MarketClockError(
                "identity projection requires explicit effective and decision times"
            )
        known = _parse_datetime(known_raw)
        valid_from = _parse_date(effective_raw)
        return ListingCalendarEvidence(
            listing_id=str(item.get("object_id", "")),
            mic=str(fields["mic"]).upper(),
            calendar_id=str(fields["calendar_id"]),
            timezone=str(fields["timezone"]),
            source_id="|".join(source_ids) or "identity-master:projection",
            source_checksum=_hash(source_payload),
            valid_from=valid_from,
            known_at=known,
            source_version=str(
                fields.get("calendar_source_version")
                or fields.get("source_version")
                or "identity-master.v1"
            ),
            opening_auction_minutes=_non_negative_int(
                fields.get("opening_auction_minutes", 0)
            ),
            closing_auction_minutes=_non_negative_int(
                fields.get("closing_auction_minutes", 0)
            ),
        )

    def _walk_business_days(
        self,
        listing: ListingCalendarEvidence,
        value: date,
        step: int,
        knowledge_cutoff: datetime | None,
    ) -> date:
        candidate = value
        for _ in range(370):
            candidate += timedelta(days=step)
            if self.is_business_day(
                listing, candidate, knowledge_cutoff=knowledge_cutoff
            ):
                return candidate
        raise MarketClockError("no business day found within certified search horizon")

    @staticmethod
    def _calendar(listing: ListingCalendarEvidence, around: date) -> Any | None:
        registered = xcals.get_calendar_names()
        if (
            listing.mic.upper() not in registered
            or listing.calendar_id.upper() not in registered
        ):
            return None
        try:
            calendar = xcals.get_calendar(
                listing.calendar_id.upper(),
                start=f"{around.year - 3}-01-01",
                end=f"{around.year + 3}-12-31",
            )
        except (KeyError, ValueError, TypeError):
            return None
        return calendar if str(calendar.tz) == listing.timezone else None

    @staticmethod
    def _identity_reason(
        listing: ListingCalendarEvidence, context: ClockContext
    ) -> str | None:
        local_date = context.decision_time.astimezone(ZoneInfo(listing.timezone)).date()
        if context.knowledge_cutoff < listing.known_at.astimezone(UTC):
            return "identity_calendar_not_known"
        if local_date < listing.valid_from or (
            listing.valid_to is not None and local_date >= listing.valid_to
        ):
            return "identity_calendar_not_effective"
        return None

    def _active_corrections(
        self, mic: str, session_date: date, cutoff: datetime
    ) -> tuple[CalendarCorrection, ...]:
        known = [
            item
            for item in self._corrections
            if item.mic.upper() == mic.upper()
            and item.session_date == session_date
            and item.valid_from <= session_date
            and item.known_at.astimezone(UTC) <= cutoff.astimezone(UTC)
        ]
        latest: dict[str, CalendarCorrection] = {}
        for item in known:
            current = latest.get(item.kind)
            if current is None or item.revision > current.revision:
                latest[item.kind] = item
        return tuple(
            sorted(latest.values(), key=lambda item: (item.kind, item.revision))
        )

    def _next_open(
        self,
        calendar: Any,
        instant: datetime,
        listing: ListingCalendarEvidence,
        cutoff: datetime,
    ) -> datetime | None:
        cursor = instant
        for _ in range(370):
            try:
                candidate = _utc_datetime(calendar.next_open(pd.Timestamp(cursor)))
            except (ValueError, KeyError):
                return None
            local_date = candidate.astimezone(ZoneInfo(listing.timezone)).date()
            if not any(
                item.kind == "exceptional_closure"
                for item in self._active_corrections(listing.mic, local_date, cutoff)
            ):
                modified = next(
                    (
                        item
                        for item in self._active_corrections(
                            listing.mic, local_date, cutoff
                        )
                        if item.kind == "modified_session"
                    ),
                    None,
                )
                if modified is not None:
                    assert modified.open_time is not None
                    return datetime.combine(
                        local_date, modified.open_time, ZoneInfo(listing.timezone)
                    ).astimezone(UTC)
                return candidate
            cursor = candidate
        return None

    def _state(self, listing: ListingCalendarEvidence, **values: Any) -> MarketState:
        corrections = tuple(values.pop("corrections"))
        lineage_payload = {
            "contract": MARKET_CALENDAR_CONTRACT,
            "library": CALENDAR_LIBRARY,
            "version": CALENDAR_LIBRARY_VERSION,
            "identity": listing.lineage_hash,
            "corrections": [asdict(item) for item in corrections],
            **values,
        }
        return MarketState(
            certification="certified",
            reason_code="certified_calendar_state",
            mic=listing.mic.upper(),
            calendar_id=listing.calendar_id,
            timezone=listing.timezone,
            correction_ids=tuple(item.correction_id for item in corrections),
            calendar_source=CALENDAR_LIBRARY,
            calendar_version=CALENDAR_LIBRARY_VERSION,
            identity_lineage_hash=listing.lineage_hash,
            lineage_hash=_hash(lineage_payload),
            **values,
        )

    @staticmethod
    def _unavailable_state(
        listing: ListingCalendarEvidence, reason: str
    ) -> MarketState:
        return MarketState(
            certification="unavailable",
            reason_code=reason,
            mic=listing.mic.upper(),
            calendar_id=listing.calendar_id,
            timezone=listing.timezone,
            phase="unknown",
            is_session=False,
            is_auction=False,
            early_close=False,
            exceptional_closure=False,
            session_open=None,
            session_close=None,
            next_decision_time=None,
            next_execution_time=None,
            correction_ids=(),
            calendar_source=CALENDAR_LIBRARY,
            calendar_version=CALENDAR_LIBRARY_VERSION,
            identity_lineage_hash=listing.lineage_hash,
            lineage_hash=_hash(
                {
                    "contract": MARKET_CALENDAR_CONTRACT,
                    "identity": listing.lineage_hash,
                    "reason": reason,
                }
            ),
        )


def _parse_datetime(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketClockError("identity decision time is invalid") from exc
    if parsed.tzinfo is None:
        raise MarketClockError("identity decision time must be timezone-aware")
    return parsed.astimezone(UTC)


def _parse_date(value: object) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise MarketClockError("identity effective date is invalid") from exc


def load_calendar_corrections(path: str | Path) -> tuple[CalendarCorrection, ...]:
    """Load the versioned local correction ledger without any network access."""

    try:
        with open(path, encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise MarketClockError(
            f"calendar correction ledger is unavailable: {path}"
        ) from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != MARKET_CALENDAR_CORRECTIONS_SCHEMA
    ):
        raise MarketClockError(
            f"calendar correction ledger must use schema {MARKET_CALENDAR_CORRECTIONS_SCHEMA}"
        )
    rows = payload.get("corrections")
    if not isinstance(rows, list):
        raise MarketClockError("calendar correction ledger requires a corrections list")
    results: list[CalendarCorrection] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise MarketClockError("calendar correction row must be a mapping")
        try:
            results.append(
                CalendarCorrection(
                    correction_id=str(row["correction_id"]),
                    mic=str(row["mic"]),
                    session_date=_parse_date(row["session_date"]),
                    kind=str(row["kind"]),
                    revision=int(row["revision"]),
                    reason=str(row["reason"]),
                    source_id=str(row["source_id"]),
                    source_checksum=str(row["source_checksum"]),
                    source_version=str(row["source_version"]),
                    valid_from=_parse_date(row["valid_from"]),
                    known_at=_parse_datetime(row["known_at"]),
                    open_time=_parse_time(row.get("open_time")),
                    close_time=_parse_time(row.get("close_time")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketClockError(
                "calendar correction row is incomplete or invalid"
            ) from exc
    MarketCalendarService(corrections=results)
    return tuple(results)


def _parse_time(value: object) -> time | None:
    if value in {None, ""}:
        return None
    try:
        return time.fromisoformat(str(value))
    except ValueError as exc:
        raise MarketClockError("calendar correction time is invalid") from exc


def _non_negative_int(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise MarketClockError("listing auction window is invalid") from exc
    if parsed < 0:
        raise MarketClockError("listing auction window cannot be negative")
    return parsed


def _utc_datetime(value: object) -> datetime:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC").to_pydatetime()


def _optional_utc_datetime(value: object) -> datetime | None:
    return None if value is None or pd.isna(value) else _utc_datetime(value)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _jsonable(value: object) -> Any:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _hash(value: object) -> str:
    payload = json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "BusinessDayConvention",
    "CALENDAR_LIBRARY_VERSION",
    "CalendarCorrection",
    "ClockContext",
    "DayCountConvention",
    "ListingCalendarEvidence",
    "MARKET_CALENDAR_CONTRACT",
    "MARKET_CALENDAR_CORRECTIONS_SCHEMA",
    "MarketCalendarService",
    "MarketClockError",
    "MarketState",
    "StalenessAssessment",
    "load_calendar_corrections",
]
