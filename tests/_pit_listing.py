"""Synthetic listing history for tests that exercise scoring/replay, not the survivorship gate itself."""

from __future__ import annotations

import pytest

from etf_cockpit.application.replay_membership import ListingHistory
from etf_cockpit.core.config import load_config

SYNTHETIC_IDS = ("AAA", "BBB", "BAD", "VWCE")


def listed_since(ids, start: str = "2000-01-01") -> ListingHistory:
    return ListingHistory(tuple({
        "scope": "listing:test:all", "instrument_id": key, "valid_from": start, "valid_to": None,
        "known_at": f"{start}T00:00:00+00:00", "source_kind": "self", "interval_id": key,
        "revision_id": 1, "snapshot_date": start,
    } for key in sorted(set(ids))))


@pytest.fixture(autouse=True)
def verified_listing_history(monkeypatch):
    """Listing history known long before every test date, so survivorship is verified.

    The production gate is unchanged: only the history source is replaced, and ids outside it stay
    ``survivorship_unverified``. The gate itself is tested in test_replay_pit_membership.py.
    """

    history = listed_since([*(item.id for item in load_config().universe.etfs), *SYNTHETIC_IDS])
    monkeypatch.setattr(ListingHistory, "from_root", classmethod(lambda cls, _root: history))
