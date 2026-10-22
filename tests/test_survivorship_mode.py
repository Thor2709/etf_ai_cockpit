"""Survivorship mode "unverified-delistings": listing derived from the first price date, delisting never inferred."""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.application import score_backfill
from etf_cockpit.data.replay_membership import (
    DELISTING_UNVERIFIED_STATUS, ListingHistory, MembershipPriceBook, PRICE_LISTING_EVIDENCE, SURVIVORSHIP_UNVERIFIED_BANNER,
    UNVERIFIED_DELISTINGS_MODE,
)
from tests.test_paper_bots_execution import _book
from tests.test_score_backfill import AS_OF, _config, _prices

FIRST = {"AAA": date(2026, 10, 15)}


def _mode_history(mode=UNVERIFIED_DELISTINGS_MODE) -> ListingHistory:
    return ListingHistory().with_price_history(FIRST, mode)


def test_listing_is_derived_from_first_price_date_and_unusable_before_it():
    history = _mode_history()
    (record,) = history.price_listings
    assert record["evidence_type"] == PRICE_LISTING_EVIDENCE == "listing_from_price_history"
    assert record["delisting_verified"] is False and record["valid_to"] is None
    before = history.snapshot(date(2026, 10, 14), ["AAA"])
    assert not before.eligible_ids and before.unverified_ids == ("AAA",) and before.delisting_unverified_ids == ()
    # Known only once that first session has closed: not before, not at the session open.
    assert not history.snapshot(datetime(2026, 10, 15, 9, tzinfo=timezone.utc), ["AAA"]).eligible_ids
    on_day = history.snapshot(date(2026, 10, 15), ["AAA"])
    assert on_day.eligible_ids == ("AAA",) and on_day.delisting_unverified_ids == ("AAA",)
    book = MembershipPriceBook(_book(sessions=[date(2026, 10, 15), date(2026, 10, 16)]), history)
    assert book.bar("AAA", date(2026, 10, 15)) is None  # cannot fill at the open of the day that proves the listing
    assert book.bar("AAA", date(2026, 10, 16)) is not None


def test_default_mode_still_excludes_and_keeps_fingerprints_unchanged():
    strict = _mode_history("strict")
    assert not strict.snapshot(date(2026, 10, 20), ["AAA"]).eligible_ids
    assert strict.snapshot(date(2026, 10, 20), ["AAA"]) == ListingHistory().snapshot(date(2026, 10, 20), ["AAA"])
    assert strict.fingerprint() == ListingHistory().fingerprint()
    assert _mode_history().fingerprint() != strict.fingerprint()
    with pytest.raises(ValueError):
        ListingHistory().with_price_history(FIRST, "lenient")


def test_delisting_is_never_inferred_from_prices():
    history = _mode_history()
    far = datetime(2027, 6, 1, tzinfo=timezone.utc)  # prices for AAA stopped long ago in any fixture: still no closure
    assert history.delistings(far) == ()
    assert history.snapshot(far, ["AAA"]).delisting_unverified_ids == ("AAA",)
    verified = ListingHistory((
        {"scope": "listing:t:all", "instrument_id": "AAA", "valid_from": "2020-01-01", "valid_to": "2026-10-17",
         "known_at": "2026-10-17T12:00:00+00:00", "source_kind": "self", "interval_id": "AAA", "revision_id": 1,
         "snapshot_date": "2026-10-17"},
    )).with_price_history(FIRST)
    # A stored (verified) listing history always governs: price evidence neither resurrects nor relabels it.
    assert not verified.snapshot(far, ["AAA"]).eligible_ids and verified.snapshot(far, ["AAA"]).delisting_unverified_ids == ()


def test_replay_flag_admits_labels_and_default_fails_closed(monkeypatch, tmp_path):
    from etf_cockpit.portfolio import paper_bots_execution as execution
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay
    from etf_cockpit.portfolio.paper_bots_report import build_paper_bots_overview
    from tests.test_paper_bots import _rows
    from tests.test_paper_bots_execution import _allow, _exec_config, _history_with_columns

    monkeypatch.setattr(ListingHistory, "from_root", classmethod(lambda cls, root: ListingHistory()))
    known = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    history = pd.DataFrame(_history_with_columns(_rows(known)))
    cutoff = datetime(2026, 10, 30, tzinfo=timezone.utc)
    book = _book(known_at=cutoff)
    track = execution.replay_track(tmp_path, _exec_config())
    _allow(tmp_path, track)
    denied = run_historical_replay(cutoff, root=tmp_path, history=history, price_book=book, now=cutoff, history_source="backfill")
    assert denied.status == "unavailable" and not denied.survivorship_unverified
    result = run_historical_replay(
        cutoff, root=tmp_path, history=history, price_book=book, now=cutoff, history_source="backfill",
        survivorship_mode=UNVERIFIED_DELISTINGS_MODE,
    )
    assert result.status in {"available", "partial"}, (result.reason, result.warnings)
    assert result.survivorship_unverified is True
    assert any(SURVIVORSHIP_UNVERIFIED_BANNER in warning for warning in result.warnings)
    overview = build_paper_bots_overview(tmp_path, as_of=cutoff, price_book=book)["replay"]
    assert overview["survivorship_unverified"] is True and overview["survivorship_banner"] == SURVIVORSHIP_UNVERIFIED_BANNER
    assert {"AAA", "BBB", "BAD", "VWCE"} >= set(overview["survivorship_unverified_ids"]) and overview["survivorship_unverified_ids"]
    assert all(row["execution_allowed"] is False for row in result.records)


def test_backfill_with_price_listings_labels_rows_and_parallel_equals_serial():
    config = _config()
    prices = _prices(config)
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    first = {key: value for key, value in prices.groupby(prices["etf_id"].astype(str))["date"].min().items()}
    listing = ListingHistory().with_price_history(first, UNVERIFIED_DELISTINGS_MODE)
    todo = [(1, AS_OF), (2, date(2022, 7, 1))]
    serial = list(score_backfill._score_sessions(config, prices, todo, pd.DataFrame(), "test", {}, 1, listing))
    parallel = list(score_backfill._score_sessions(config, prices, todo, pd.DataFrame(), "test", {}, 2, listing))
    scored = 0
    for (index, day, one), (other_index, other_day, two) in zip(serial, parallel, strict=True):
        assert (index, day) == (other_index, other_day)
        assert not isinstance(one, str) and not isinstance(two, str), (one, two)
        if one[0] is None:
            continue
        scored += 1
        pd.testing.assert_frame_equal(one[0], two[0])
        pd.testing.assert_frame_equal(one[1], two[1])
        assert one[1]["membership_status"].eq(DELISTING_UNVERIFIED_STATUS).any()
    assert scored
    strict = score_backfill.score_as_of(config, prices, AS_OF, membership=ListingHistory(), fx_rates=pd.DataFrame())
    assert strict[0] is None and strict[1]["membership_status"].eq("survivorship_unverified").all()
