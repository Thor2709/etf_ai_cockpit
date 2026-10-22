"""BT3 focused evidence; fixture instruments/prices are synthetic test data."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd

from etf_cockpit.application import score_backfill
from etf_cockpit.application.replay_membership import (
    ListingHistory, MEMBERSHIP_POLICY, MembershipPriceBook, unverified_instruments,
)
from etf_cockpit.data.universe_membership import import_licensed_history
from tests.test_score_backfill import AS_OF, _config, _eur_ids, _prices
from tests.test_paper_bots_execution import _book


def _interval(instrument, *, start="2020-01-01", end=None, known="2020-01-01T00:00:00+00:00", revision=1):
    return {
        "scope": "listing:euronext_oslo:all", "instrument_id": instrument,
        "valid_from": start, "valid_to": end, "known_at": known,
        "source_kind": "self", "interval_id": instrument, "revision_id": revision,
        "snapshot_date": known[:10],
    }


def test_membership_half_open_boundaries_and_fill_session_gate(monkeypatch, tmp_path):
    history = ListingHistory((_interval("VWCE", start="2026-10-15", end="2026-10-19"),))
    assert not history.snapshot(date(2026, 10, 14), ["VWCE"]).eligible_ids
    assert history.snapshot(date(2026, 10, 15), ["VWCE"]).eligible_ids == ("VWCE",)
    assert not history.snapshot(date(2026, 10, 19), ["VWCE"]).eligible_ids
    book = MembershipPriceBook(_book(), history)
    assert book.bar("VWCE", date(2026, 10, 15)) is not None
    assert book.bar("VWCE", date(2026, 10, 19)) is None
    assert book.bar("AAA", date(2026, 10, 15)) is None
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay

    monkeypatch.setattr(ListingHistory, "from_root", classmethod(lambda cls, root: history))
    cutoff = datetime(2026, 10, 22, tzinfo=timezone.utc)
    stored = pd.DataFrame([{
        "as_of_date": "2026-10-19", "run_completed_at": "2026-10-19T23:59:59+00:00",
        "instrument_id": "VWCE", "membership_policy": MEMBERSHIP_POLICY,
    }])
    denied = run_historical_replay(cutoff, root=tmp_path, history=stored, price_book=_book(), now=cutoff)
    assert denied.status == "unavailable" and "violate listing membership" in denied.reason
    legacy = run_historical_replay(cutoff, root=tmp_path, history=stored.drop(columns="membership_policy"), price_book=_book(), now=cutoff)
    assert legacy.status == "unavailable" and "lacks point-in-time" in legacy.reason
    assert not (tmp_path / "data").exists()  # API checks precede any replay writes


def test_future_membership_revisions_cannot_change_past_scores_or_fills():
    opened = _interval("VWCE")
    closed = _interval("VWCE", end="2026-10-15", known="2026-10-20T12:00:00+00:00", revision=2)
    original = ListingHistory((opened,))
    revised = ListingHistory((opened, closed))
    assert revised.snapshot(date(2026, 10, 16), ["VWCE"]) == original.snapshot(date(2026, 10, 16), ["VWCE"])
    assert not revised.snapshot(date(2026, 10, 20), ["VWCE"]).eligible_ids
    licensed_open = {**opened, "source_kind": "licensed", "history_id": 1}
    assert not ListingHistory((licensed_open, closed)).snapshot(date(2026, 10, 20), ["VWCE"]).eligible_ids
    announced = ListingHistory((_interval("VWCE", known="2026-10-15T12:00:00+00:00"),))
    assert announced.snapshot(date(2026, 10, 15), ["VWCE"]).eligible_ids == ("VWCE",)
    assert MembershipPriceBook(_book(), announced).bar("VWCE", date(2026, 10, 15)) is None
    assert revised.delistings(datetime(2026, 10, 19, tzinfo=timezone.utc)) == ()
    assert revised.delistings(datetime(2026, 10, 21, tzinfo=timezone.utc)) == (
        (datetime(2026, 10, 20, 12, tzinfo=timezone.utc), "VWCE", date(2026, 10, 15)),
    )


def test_scoring_removes_prelisting_and_delisted_peers_and_restores_retained_identity():
    config = _config()
    first, second = _eur_ids(config, "etf", 2)
    prices = _prices(config)
    history = ListingHistory((
        _interval("VWCE"), _interval(first, end=AS_OF.isoformat()),
        _interval(second, start="2022-07-01"),
    ))
    run, log = score_backfill.score_as_of(config, prices, AS_OF, membership=history, fx_rates=pd.DataFrame())
    assert run is not None and set(run["instrument_id"]) == {"VWCE"}
    assert not log.loc[log["instrument_id"].isin([first, second]), "eligible"].any()
    assert log.set_index("instrument_id").loc[first, "membership_status"] == "outside_listing_interval"
    retained = config.model_copy(deep=True)
    identity = retained.universe.by_id()[first]
    identity.enabled, identity.lifecycle = False, "delisted"
    past = ListingHistory((_interval("VWCE"), _interval(first, end="2022-07-01")))
    restored, _ = score_backfill.score_as_of(retained, prices, AS_OF, membership=past, fx_rates=pd.DataFrame())
    assert first in set(restored["instrument_id"])
    assert not identity.enabled  # caller's present-day configuration stays intact


def test_delisting_liquidates_held_position_at_last_available_price_and_is_idempotent(monkeypatch, tmp_path):
    from etf_cockpit.portfolio import paper_bots_execution as execution
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay
    from etf_cockpit.portfolio.paper_trading import PaperLedger
    from tests.test_paper_bots import _rows
    from tests.test_paper_bots_execution import _allow, _exec_config, _history_with_columns, _plans, _records

    listing = ListingHistory(tuple(_interval(key, end="2026-10-19" if key == "AAA" else None)
                                   for key in ("VWCE", "AAA", "BBB", "BAD")))
    monkeypatch.setattr(ListingHistory, "from_root", classmethod(lambda cls, root: listing))
    known = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    history = pd.DataFrame(_history_with_columns(_rows(known)))
    history["as_of_date"], history["membership_policy"] = known.date().isoformat(), MEMBERSHIP_POLICY
    cutoff = datetime(2026, 10, 30, tzinfo=timezone.utc)
    # No final Friday bar; a post-delisting quote must never determine proceeds.
    book = _book(missing={("AAA", date(2026, 10, 16))}, opens={"AAA": {date(2026, 10, 19): 9999}})
    track = execution.replay_track(tmp_path, _exec_config())
    _allow(tmp_path, track)
    result = run_historical_replay(cutoff, root=tmp_path, history=history, price_book=book, now=cutoff, history_source="backfill")
    assert result.status in {"available", "partial"}, (result.reason, result.warnings)
    sales = [row for row in result.records if row["instrument_id"] == "AAA" and row["side"] == "sell" and row["status"] == "filled"]
    assert sales, (result.records, result.warnings)
    reference = Decimal(str(book.bar("AAA", date(2026, 10, 15))["close"]))
    for sale in sales:
        assert sale["session"] == "2026-10-19" and sale["price_as_of_date"] == "2026-10-15"
        assert Decimal(sale["reference_open"]) == reference
        assert sale["price_basis"] == "last_pre_delisting_close"
        ledger = PaperLedger(track.ledger_root, account_id=execution.account_id_for(sale["bot_id"]))
        assert not any(p.instrument_id == "AAA" and p.quantity > 0 for p in ledger.snapshot().positions)
        purchases = [t for t in ledger.trade_rows() if t["instrument_id"] == "AAA" and t["side"] == "buy"]
        assert sum(Decimal(str(t["quantity"])) for t in purchases) == Decimal(sale["quantity"])
        assert any(t["paper_trade_id"] == sale["fill_id"] for t in ledger.trade_rows())
    assert all(row["execution_allowed"] is False for row in result.records)
    before = _records(tmp_path, track)
    again = run_historical_replay(cutoff, root=tmp_path, history=history, price_book=book, now=cutoff, history_source="backfill")
    assert again.appended == 0 and _records(tmp_path, track) == before

    # A prior month's retries must not liquidate a future closure before the
    # next month's portfolio is sized (which would spend future sale proceeds).
    listing = ListingHistory(tuple(_interval(key, end="2026-11-04" if key == "AAA" else None)
                                   for key in ("VWCE", "AAA", "BBB", "BAD")))
    october = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    november = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    next_history = pd.DataFrame(_history_with_columns(_rows(october) + _rows(november, run_id="score-run-nov", snapshot="b")))
    next_history["as_of_date"] = next_history["run_completed_at"].str[:10]
    next_history["membership_policy"] = MEMBERSHIP_POLICY
    next_root = tmp_path / "month-boundary"
    next_track = execution.replay_track(next_root, _exec_config())
    _allow(next_root, next_track)
    cutoff = datetime(2026, 11, 16, tzinfo=timezone.utc)
    second = run_historical_replay(cutoff, root=next_root, history=next_history, price_book=_book(known_at=cutoff), now=cutoff)
    assert second.status in {"available", "partial"}, (second.reason, second.warnings)
    november_plans = [p for p in _plans(next_root, next_track) if p["decision_date"] == "2026-11-02"]
    assert november_plans and any(Decimal(p["held_before"].get("AAA", "0")) > 0 for p in november_plans)


def test_missing_listing_history_is_persisted_and_reported_even_when_nothing_scores(tmp_path):
    config = _config()
    retained_id = _eur_ids(config, "etf", 1)[0]
    config.universe.by_id()[retained_id].enabled = False
    config.universe.by_id()[retained_id].lifecycle = "delisted"
    prices = _prices(config)
    result = score_backfill.backfill_score_history(
        tmp_path, AS_OF, AS_OF, config=config, prices=prices, fx_rates=pd.DataFrame(),
    )
    assert result.status == "unavailable" and result.path is not None
    expected = {*config.universe.enabled_ids, *(item.id for item in config.universe.etfs if item.lifecycle in {"delisted", "merged"})}
    assert result.survivorship_unverified == sorted(expected)
    assert unverified_instruments(result.eligibility) == result.survivorship_unverified
    assert not result.eligibility["eligible"].any()
    assert result.eligibility["reasons"].str.contains("survivorship_unverified").all()
    from etf_cockpit.data.score_history_backfill import load_backfill_manifest

    report = load_backfill_manifest(tmp_path)
    assert report["survivorship_unverified"] == result.survivorship_unverified
    assert report["execution_allowed"] is False


def test_licensed_history_and_parallel_session_outputs_are_deterministic(tmp_path):
    config = _config()
    prices = _prices(config)
    ids = sorted(set(prices["etf_id"]))
    import_licensed_history([
        {"scope": "listing:euronext_oslo:all", "instrument_id": key,
         "valid_from": "2020-01-01", "valid_to": None, "known_at": "2020-01-01T00:00:00+00:00",
         "snapshot_date": "2020-01-01", "snapshot_complete": True}
        for key in ids
    ], source="synthetic-test-fixture", licence_ref="synthetic-test-fixture", root=tmp_path)
    listing = ListingHistory.from_root(tmp_path)
    assert listing.snapshot(AS_OF, ids).eligible_ids == tuple(ids)
    assert ListingHistory(tuple(reversed(listing.revisions))).snapshot(AS_OF, ids) == listing.snapshot(AS_OF, ids)
    todo = [(1, AS_OF), (2, date(2022, 7, 1))]
    serial = list(score_backfill._score_sessions(config, prices, todo, pd.DataFrame(), "test", {}, 1, listing))
    parallel = list(score_backfill._score_sessions(config, prices, todo, pd.DataFrame(), "test", {}, 2, listing))
    for (index, day, first), (other_index, other_day, second) in zip(serial, parallel, strict=True):
        assert (index, day) == (other_index, other_day)
        assert not isinstance(first, str) and not isinstance(second, str), (first, second)
        assert first[0] is not None
        pd.testing.assert_frame_equal(first[0], second[0])
        pd.testing.assert_frame_equal(first[1], second[1])
        assert first[0]["execution_allowed"].eq(False).all()
