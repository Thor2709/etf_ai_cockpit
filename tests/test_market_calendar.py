from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from hypothesis import given, settings, strategies as st

from etf_cockpit.backtest.event_engine import CertifiedSessionCalendar
from etf_cockpit.data.market_calendar import (
    BusinessDayConvention,
    CalendarCorrection,
    ClockContext,
    DayCountConvention,
    ListingCalendarEvidence,
    MarketCalendarService,
    MarketClockError,
    SettlementCalendarEvidence,
    load_calendar_corrections,
)


UTC = timezone.utc


def _listing(
    mic: str = "XNYS",
    *,
    calendar: str | None = None,
    tz: str = "America/New_York",
    auctions: bool = False,
) -> ListingCalendarEvidence:
    return ListingCalendarEvidence(
        listing_id=f"listing:{mic}",
        instrument_id="ETF-A",
        mic=mic,
        calendar_id=calendar or mic,
        timezone=tz,
        source_id="identity-master:test-listing",
        source_checksum="a" * 64,
        valid_from=date(2020, 1, 1),
        known_at=datetime(2020, 1, 2, tzinfo=UTC),
        opening_auction_minutes=5 if auctions else 0,
        closing_auction_minutes=10 if auctions else 0,
    )


def _settlement(
    *, calendar: str = "XNYS", tz: str = "America/New_York"
) -> SettlementCalendarEvidence:
    return SettlementCalendarEvidence(
        settlement_calendar_id=f"settlement:{calendar}",
        instrument_id="ETF-A",
        calendar_id=calendar,
        timezone=tz,
        source_id="identity-master:test-settlement",
        source_checksum="d" * 64,
        valid_from=date(2020, 1, 1),
        known_at=datetime(2020, 1, 2, tzinfo=UTC),
    )


def test_cross_market_holiday_and_early_close_are_calendar_specific() -> None:
    service = MarketCalendarService()

    thanksgiving = datetime(2024, 11, 28, 16, 0, tzinfo=UTC)
    ny = service.market_state(_listing(), ClockContext.at(thanksgiving))
    london = service.market_state(
        _listing("XLON", tz="Europe/London"), ClockContext.at(thanksgiving)
    )
    early_close = service.market_state(
        _listing(), ClockContext.at(datetime(2024, 11, 29, 17, 30, tzinfo=UTC))
    )

    assert ny.certification == "certified"
    assert ny.phase == "closed"
    assert ny.is_session is False
    assert london.phase == "open"
    assert london.is_session is True
    assert early_close.phase == "open"
    assert early_close.early_close is True
    assert early_close.session_close == datetime(2024, 11, 29, 18, 0, tzinfo=UTC)
    assert ny.execution_allowed is london.execution_allowed is False


def test_dst_is_derived_from_listing_timezone_and_next_open_is_exact() -> None:
    service = MarketCalendarService()
    before_us_dst = service.market_state(
        _listing(), ClockContext.at(datetime(2024, 3, 8, 14, 0, tzinfo=UTC))
    )
    after_us_dst = service.market_state(
        _listing(), ClockContext.at(datetime(2024, 3, 11, 13, 0, tzinfo=UTC))
    )

    assert before_us_dst.next_execution_time == datetime(2024, 3, 8, 14, 30, tzinfo=UTC)
    assert after_us_dst.next_execution_time == datetime(2024, 3, 11, 13, 30, tzinfo=UTC)
    assert before_us_dst.timezone == after_us_dst.timezone == "America/New_York"


def test_auction_windows_are_flagged_but_only_return_the_auction_execution_time() -> (
    None
):
    service = MarketCalendarService()
    opening = service.market_state(
        _listing(auctions=True),
        ClockContext.at(datetime(2024, 3, 8, 14, 28, tzinfo=UTC)),
    )
    closing = service.market_state(
        _listing(auctions=True),
        ClockContext.at(datetime(2024, 3, 8, 20, 55, tzinfo=UTC)),
    )

    assert (opening.phase, opening.is_auction) == ("opening_auction", True)
    assert opening.next_execution_time == datetime(2024, 3, 8, 14, 30, tzinfo=UTC)
    assert (closing.phase, closing.is_auction) == ("closing_auction", True)
    assert closing.next_execution_time == datetime(2024, 3, 8, 21, 0, tzinfo=UTC)
    assert opening.execution_allowed is closing.execution_allowed is False


def test_unknown_or_conflicting_identity_calendar_fails_closed() -> None:
    service = MarketCalendarService()
    result = service.market_state(
        _listing("ZZZZ", calendar="ZZZZ", tz="UTC"),
        ClockContext.at(datetime(2024, 3, 11, 13, 0, tzinfo=UTC)),
    )

    assert result.certification == "unavailable"
    assert result.reason_code == "unknown_calendar"
    assert result.next_execution_time is None
    assert result.execution_allowed is False

    with pytest.raises(MarketClockError, match="conflict-free"):
        ListingCalendarEvidence(
            listing_id="listing:bad",
            instrument_id="ETF-A",
            mic="XNYS",
            calendar_id="XNYS",
            timezone="America/New_York",
            source_id="identity:test",
            source_checksum="b" * 64,
            valid_from=date(2020, 1, 1),
            known_at=datetime(2020, 1, 2, tzinfo=UTC),
            conflict_ids=("conflict-1",),
        )


def test_identity_evidence_can_map_a_known_mic_to_a_registered_calendar_alias() -> None:
    service = MarketCalendarService()
    listing = _listing("XNYS", calendar="NYSE")
    state = service.market_state(
        listing,
        ClockContext.at(datetime(2024, 3, 11, 15, 0, tzinfo=UTC)),
    )
    assert state.certification == "certified"
    assert state.mic == "XNYS"
    assert state.calendar_id == "NYSE"


def test_staleness_counts_expected_sessions_not_weekdays_or_holidays() -> None:
    service = MarketCalendarService()
    listing = _listing()

    assessment = service.assess_staleness(
        listing,
        observed_at=datetime(2024, 11, 27, 21, 0, tzinfo=UTC),
        assessed_at=datetime(2024, 12, 2, 22, 0, tzinfo=UTC),
        maximum_expected_sessions=1,
    )

    assert (
        assessment.expected_sessions_elapsed == 2
    )  # Fri 29 and Mon 2; Thanksgiving is excluded.
    assert assessment.status == "stale"
    assert assessment.execution_allowed is False


def test_staleness_counts_exact_session_closes_across_pre_and_post_open_cutoffs() -> (
    None
):
    service = MarketCalendarService()
    listing = _listing()
    monday_preopen = service.assess_staleness(
        listing,
        observed_at=datetime(2024, 11, 29, 18, 0, tzinfo=UTC),
        assessed_at=datetime(2024, 12, 2, 14, 0, tzinfo=UTC),
        maximum_expected_sessions=0,
    )
    monday_postclose = service.assess_staleness(
        listing,
        observed_at=datetime(2024, 12, 2, 13, 0, tzinfo=UTC),
        assessed_at=datetime(2024, 12, 2, 22, 0, tzinfo=UTC),
        maximum_expected_sessions=0,
    )
    assert monday_preopen.expected_sessions_elapsed == 0
    assert monday_preopen.status == "fresh"
    assert monday_postclose.expected_sessions_elapsed == 1
    assert monday_postclose.status == "stale"


def test_staleness_uses_early_and_corrected_close_instants() -> None:
    listing = _listing()
    service = MarketCalendarService()
    before_early_close = service.assess_staleness(
        listing,
        observed_at=datetime(2024, 11, 29, 17, 0, tzinfo=UTC),
        assessed_at=datetime(2024, 11, 29, 17, 59, tzinfo=UTC),
        maximum_expected_sessions=0,
    )
    at_early_close = service.assess_staleness(
        listing,
        observed_at=datetime(2024, 11, 29, 17, 0, tzinfo=UTC),
        assessed_at=datetime(2024, 11, 29, 18, 0, tzinfo=UTC),
        maximum_expected_sessions=0,
    )
    assert before_early_close.expected_sessions_elapsed == 0
    assert at_early_close.expected_sessions_elapsed == 1

    correction = CalendarCorrection(
        correction_id="xnys-2024-12-02-v1",
        mic="XNYS",
        session_date=date(2024, 12, 2),
        kind="modified_session",
        revision=1,
        reason="Corrected noon close fixture.",
        source_id="exchange-notice:test",
        source_checksum="f" * 64,
        timezone="America/New_York",
        valid_from=date(2024, 12, 2),
        known_at=datetime(2024, 12, 1, tzinfo=UTC),
        open_time=time(9, 30),
        close_time=time(12, 0),
    )
    corrected = MarketCalendarService(corrections=(correction,)).assess_staleness(
        listing,
        observed_at=datetime(2024, 12, 2, 16, 0, tzinfo=UTC),
        assessed_at=datetime(2024, 12, 2, 17, 0, tzinfo=UTC),
        maximum_expected_sessions=0,
    )
    assert corrected.expected_sessions_elapsed == 1


def test_manual_exceptional_closure_is_versioned_by_knowledge_time() -> None:
    correction = CalendarCorrection.exceptional_closure(
        correction_id="nyse-2024-01-03-v1",
        mic="XNYS",
        session_date=date(2024, 1, 3),
        revision=1,
        reason="Exchange-declared exceptional closure fixture.",
        source_id="exchange-notice:test",
        source_checksum="c" * 64,
        timezone="America/New_York",
        valid_from=date(2024, 1, 3),
        known_at=datetime(2024, 1, 2, 12, 0, tzinfo=UTC),
    )
    service = MarketCalendarService(corrections=(correction,))

    before_known = service.market_state(
        _listing(),
        ClockContext.at(
            datetime(2024, 1, 3, 16, 0, tzinfo=UTC),
            knowledge_cutoff=datetime(2024, 1, 2, 11, 59, tzinfo=UTC),
        ),
    )
    after_known = service.market_state(
        _listing(),
        ClockContext.at(
            datetime(2024, 1, 3, 16, 0, tzinfo=UTC),
            knowledge_cutoff=datetime(2024, 1, 2, 12, 0, tzinfo=UTC),
        ),
    )

    assert before_known.phase == "open"
    assert after_known.phase == "closed"
    assert after_known.exceptional_closure is True
    assert after_known.correction_ids == ("nyse-2024-01-03-v1",)
    assert after_known.next_execution_time == datetime(2024, 1, 4, 14, 30, tzinfo=UTC)
    assert before_known.lineage_hash != after_known.lineage_hash


def test_versioned_local_correction_ledger_loads_without_network(tmp_path) -> None:
    ledger = tmp_path / "calendar-corrections.yaml"
    ledger.write_text(
        """schema_version: market-calendar-corrections.v1
corrections:
  - correction_id: nyse-2024-01-03-v1
    mic: XNYS
    session_date: 2024-01-03
    kind: exceptional_closure
    revision: 1
    reason: Exchange-declared closure.
    source_id: exchange-notice:test
    source_checksum: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
    timezone: America/New_York
    source_version: notice-v1
    valid_from: 2024-01-03
    known_at: 2024-01-02T12:00:00Z
""",
        encoding="utf-8",
    )
    corrections = load_calendar_corrections(ledger)
    assert corrections[0].source_version == "notice-v1"
    assert corrections[0].known_at == datetime(2024, 1, 2, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "values, session_date, message",
    [
        (
            {"open_time": time(16, 0), "close_time": time(9, 30)},
            date(2024, 3, 8),
            "open_time < close_time",
        ),
        (
            {
                "open_time": time(9, 30),
                "close_time": time(16, 0),
                "break_start": time(14, 0),
                "break_end": time(13, 0),
            },
            date(2024, 3, 8),
            "break must be ordered",
        ),
        (
            {"open_time": time(2, 30), "close_time": time(16, 0)},
            date(2024, 3, 10),
            "nonexistent DST",
        ),
        (
            {"open_time": time(1, 30), "close_time": time(16, 0)},
            date(2024, 11, 3),
            "ambiguous DST",
        ),
    ],
)
def test_invalid_modified_session_corrections_fail_closed(
    values: dict[str, time], session_date: date, message: str
) -> None:
    with pytest.raises(MarketClockError, match=message):
        CalendarCorrection(
            correction_id="invalid-v1",
            mic="XNYS",
            session_date=session_date,
            kind="modified_session",
            revision=1,
            reason="Invalid correction fixture.",
            source_id="exchange-notice:test",
            source_checksum="e" * 64,
            timezone="America/New_York",
            valid_from=session_date,
            known_at=datetime(2024, 3, 1, tzinfo=UTC),
            **values,
        )


@pytest.mark.parametrize(
    ("convention", "expected"),
    [
        (DayCountConvention.ACT_360, 31 / 360),
        (DayCountConvention.ACT_365F, 31 / 365),
        (DayCountConvention.THIRTY_360_US, 30 / 360),
        (DayCountConvention.THIRTY_E_360, 30 / 360),
    ],
)
def test_day_count_golden_fixtures(
    convention: DayCountConvention, expected: float
) -> None:
    service = MarketCalendarService()
    assert service.year_fraction(
        date(2024, 1, 1), date(2024, 2, 1), convention
    ) == pytest.approx(expected)


def test_actual_actual_isda_splits_leap_years() -> None:
    service = MarketCalendarService()
    expected = 1 / 365 + 2 / 366
    assert service.year_fraction(
        date(2023, 12, 31), date(2024, 1, 3), DayCountConvention.ACT_ACT_ISDA
    ) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2023, 2, 28), date(2023, 3, 31), 30 / 360),
        (date(2024, 2, 29), date(2024, 3, 31), 30 / 360),
        (date(2024, 2, 28), date(2024, 3, 31), 33 / 360),
    ],
)
def test_us_30_360_applies_nasd_end_of_february_rules(
    start: date, end: date, expected: float
) -> None:
    assert MarketCalendarService.year_fraction(
        start, end, DayCountConvention.THIRTY_360_US
    ) == pytest.approx(expected)


def test_business_day_adjustment_and_settlement_use_declared_calendar() -> None:
    service = MarketCalendarService()
    listing = _listing()

    assert service.adjust_business_day(
        listing, date(2024, 8, 31), BusinessDayConvention.MODIFIED_FOLLOWING
    ) == date(2024, 8, 30)
    settlement = _settlement()
    assert service.settlement_date(settlement, date(2024, 11, 27), 1) == date(
        2024, 11, 29
    )
    assert service.coupon_date(
        settlement, date(2024, 8, 31), BusinessDayConvention.MODIFIED_FOLLOWING
    ) == date(2024, 8, 30)
    assert service.ex_date(settlement, date(2024, 12, 2), 1) == date(2024, 11, 29)


def test_settlement_operations_reject_trading_calendar_evidence() -> None:
    with pytest.raises((AttributeError, MarketClockError)):
        MarketCalendarService().settlement_date(  # type: ignore[arg-type]
            _listing(), date(2024, 11, 27), 1
        )


def test_clock_context_keeps_all_financial_times_distinct() -> None:
    context = ClockContext(
        valuation_date=date(2024, 11, 27),
        decision_time=datetime(2024, 11, 27, 20, 0, tzinfo=UTC),
        trade_date=date(2024, 11, 27),
        settlement_date=date(2024, 11, 29),
        knowledge_cutoff=datetime(2024, 11, 27, 19, 55, tzinfo=UTC),
    )
    assert context.valuation_date != context.settlement_date
    assert context.decision_time != context.knowledge_cutoff


def test_backtest_session_adapter_uses_certified_holiday_and_early_close() -> None:
    calendar = CertifiedSessionCalendar(_listing())

    assert calendar.is_session(datetime(2024, 11, 28, 10, 0)) is False
    assert calendar.is_session(datetime(2024, 11, 29, 12, 30)) is True
    assert calendar.is_session(datetime(2024, 11, 29, 13, 30)) is False


@settings(deadline=None)
@given(st.dates(min_value=date(2020, 1, 2), max_value=date(2027, 12, 1)))
def test_following_adjustment_always_returns_a_certified_business_day(
    value: date,
) -> None:
    service = MarketCalendarService()
    listing = _listing()
    adjusted = service.adjust_business_day(
        listing, value, BusinessDayConvention.FOLLOWING
    )
    assert adjusted >= value
    assert service.is_business_day(listing, adjusted)


@given(
    st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 1, 1)),
    st.integers(min_value=0, max_value=1_000),
)
def test_actual_day_counts_are_antisymmetric(start: date, offset: int) -> None:
    end = start + timedelta(days=offset)
    service = MarketCalendarService()
    forward = service.year_fraction(start, end, DayCountConvention.ACT_365F)
    backward = service.year_fraction(end, start, DayCountConvention.ACT_365F)
    assert forward == pytest.approx(-backward)
