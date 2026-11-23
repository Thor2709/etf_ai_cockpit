"""D9: replay readers see licensed S&P history at its effective dates (reconstructed PIT); strict readers keep the stamps."""

from __future__ import annotations

from datetime import datetime, timezone

from etf_cockpit.data.replay_membership import ListingHistory
from etf_cockpit.data.universe_membership import membership_frame
from scripts.ingest_sp500 import ingest
from tests.test_univ1_sp500 import ingest_config

_IDS = ("synthetic-instrument-a", "synthetic-instrument-b")


def _late_identity_store(tmp_path):
    config = ingest_config(tmp_path)
    for row in config["cik_bindings"] + config["instrument_bindings"]:
        row["known_at"] = "2021-05-15T12:00:00Z"  # identities observed at acquisition, after the history
    root = tmp_path / "output"
    assert ingest(config, root=root, workers=1)["status"] == "complete"
    return config, root


def test_reconstructed_reader_sees_history_at_effective_dates_without_the_future_end(tmp_path):
    config, root = _late_identity_store(tmp_path)

    assert membership_frame(config["scope"], "2020-06-01T12:00:00Z", root=root).empty
    frame = membership_frame(config["scope"], "2020-06-01T12:00:00Z", root=root, reconstructed=True)

    assert set(frame.instrument_id) == set(_IDS)
    assert frame.valid_to.isna().all()  # the 2020-07-01 exit is not known before it happens
    assert set(frame.pit_basis) == {"reconstructed"}


def test_replay_listing_history_admits_licensed_members_only_when_reconstructed(tmp_path):
    _, root = _late_identity_store(tmp_path)
    when = datetime(2020, 6, 1, 12, tzinfo=timezone.utc)

    assert ListingHistory.from_root(root).snapshot(when, _IDS).eligible_ids == ()
    snapshot = ListingHistory.from_root(root, reconstructed=True).snapshot(when, _IDS)

    assert snapshot.eligible_ids == _IDS
    assert snapshot.pit_basis == "reconstructed"
