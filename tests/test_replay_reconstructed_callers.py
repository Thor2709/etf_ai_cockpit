"""D9 callers (OD-1 = b): the score backfill and the replay read listing membership by the same reconstructed rule."""

from datetime import date, datetime, timezone

import pandas as pd

from etf_cockpit.application import score_backfill
from etf_cockpit.data.replay_membership import ListingHistory, replay_preflight
from etf_cockpit.data.score_history_backfill import load_backfill_score_history
from etf_cockpit.data.universe_membership import import_licensed_history
from tests.test_paper_bots_execution import _book
from tests.test_score_backfill import AS_OF, _config, _eur_ids, _prices

_STORED = "2026-11-15T00:00:00+00:00"  # licensed history acquired long after the replayed sessions


def _late_licensed_store(root, ids):
    import_licensed_history([
        {"scope": "listing:sp500:all", "instrument_id": key, "valid_from": "2020-01-01", "valid_to": None,
         "known_at": _STORED, "snapshot_date": "2026-11-15", "snapshot_complete": False}
        for key in ids
    ], source="synthetic-test-fixture", licence_ref="synthetic-test-fixture", root=root)


def test_licensed_member_known_only_by_reconstruction_is_admitted_in_backfill_and_replay(tmp_path, readiness_pass):
    config = _config()
    prices = _prices(config)
    ids = sorted(set(prices["etf_id"]))
    _late_licensed_store(tmp_path, ids)
    stock = _eur_ids(config, "stock", 1)[0]

    result = score_backfill.backfill_score_history(tmp_path, AS_OF, AS_OF, config=config, prices=prices, fx_rates=pd.DataFrame())

    assert result.status == "available", result.reason
    log = result.eligibility.set_index("instrument_id")
    assert log.loc[stock, "membership_status"] == "listed" and log.loc[stock, "pit_basis"] == "reconstructed"
    history = load_backfill_score_history(tmp_path)
    assert stock in set(history["instrument_id"])

    cutoff = datetime(2022, 7, 5, tzinfo=timezone.utc)
    book = _book(sessions=[date(2022, 7, 1), date(2022, 7, 4)], known_at=cutoff)
    assert replay_preflight(history, ListingHistory.from_root(tmp_path, reconstructed=True), book, cutoff) is None
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay

    replay = run_historical_replay(cutoff, root=tmp_path, price_book=book, now=cutoff, history_source="backfill")
    assert "membership" not in str(replay.reason), replay.reason

    strict = ListingHistory.from_root(tmp_path)  # strict readers keep the stored stamps
    assert {pd.Timestamp(row["known_at"]) for row in strict.revisions} == {pd.Timestamp(_STORED)}
    assert strict.snapshot(AS_OF, [stock]).eligible_ids == ()
