from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

import etf_cockpit.data.universe_membership as universe_membership

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore
from etf_cockpit.data.instrument_identity import IdentityClaim


def _dated(instrument_id: str, field: str, value: str, tag: str) -> IdentityClaim:
    return IdentityClaim(
        instrument_id,
        field,
        value,
        "fixture",
        SourceAuthority.OFFICIAL,
        f"{tag}:{field}",
        valid_from="2024-01-01T00:00:00Z",
        available_at="2024-01-02T00:00:00Z",
    )


def test_undated_unrelated_claim_does_not_block_pit_resolution(tmp_path: Path) -> None:
    """A014-N006: an undated claim of another entity must not block PIT resolution."""

    undated = IdentityClaim("SEC-OTHER", "isin", "US9999999999", "fixture", SourceAuthority.OFFICIAL, "other:isin")
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(
            (
                _dated("SEC-A", "ticker", "AAA", "a"),
                _dated("SEC-A", "isin", "US1111111111", "a"),
                undated,
            )
        )
        resolution = store.resolve("SEC-A", effective_at="2024-06-01T00:00:00Z", decision_time="2024-06-01T00:00:00Z")
        assert resolution.identity.instrument_id == "SEC-A"
        assert not [c for c in resolution.conflicts if c.reason_code == "duplicate_identity"]


_SCOPE = "listing:euronext_oslo:all"


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=timezone.utc)


def test_case_only_listing_id_change_is_not_a_close_and_open(tmp_path: Path) -> None:
    """A115-N001: listing IDs compare case-normalised across captures."""

    universe_membership.record_listing_capture(b'[{"instrument_id":"Abc"},{"instrument_id":"D"}]', "fixture", _SCOPE, _at(1), root=tmp_path)
    universe_membership.record_listing_capture(b'[{"instrument_id":"ABC"},{"instrument_id":"D"}]', "fixture", _SCOPE, _at(2), root=tmp_path)

    intervals = universe_membership.membership_intervals(_SCOPE, _at(3), root=tmp_path)
    assert len(intervals) == 2
    assert intervals["valid_to"].isna().all()
    assert not len(universe_membership.closure_events(_SCOPE, _at(3), root=tmp_path))


def test_same_bytes_cross_provider_capture_keeps_both_provenances(tmp_path: Path) -> None:
    """A115-N003: a second provider's identical same-day capture is not dropped as a duplicate."""

    payload = b'[{"instrument_id":"A"}]'
    first = universe_membership.record_listing_capture(
        payload, "provider_one", _SCOPE, _at(1), root=tmp_path, snapshot_date="2024-01-01"
    )
    second = universe_membership.record_listing_capture(
        payload, "provider_two", _SCOPE, _at(1, 13), root=tmp_path, snapshot_date="2024-01-01"
    )
    repeat = universe_membership.record_listing_capture(
        payload, "provider_two", _SCOPE, _at(1, 14), root=tmp_path, snapshot_date="2024-01-01"
    )

    assert first.status == "recorded"
    assert second.status == "recorded"
    assert repeat.status == "duplicate"
    log = universe_membership.capture_log(_SCOPE, root=tmp_path)
    assert list(log["source"]) == ["provider_one", "provider_two"]
    assert len(universe_membership.membership_intervals(_SCOPE, _at(2), root=tmp_path)) == 1


def test_backdated_listing_capture_cannot_invert_membership_interval(tmp_path: Path) -> None:
    """C022-N001: a capture dated before an open interval's start is rejected, nothing written."""

    universe_membership.record_listing_capture(b'[{"instrument_id":"A"},{"instrument_id":"B"}]', "fixture", _SCOPE, _at(5), root=tmp_path)
    with pytest.raises(universe_membership.MembershipCaptureError, match="backdated"):
        universe_membership.record_listing_capture(
            b'[{"instrument_id":"A"}]', "fixture", _SCOPE, _at(6), root=tmp_path, snapshot_date="2024-01-02"
        )

    assert len(universe_membership.capture_log(_SCOPE, root=tmp_path)) == 1
    intervals = universe_membership.membership_intervals(_SCOPE, _at(7), root=tmp_path)
    assert intervals["valid_to"].isna().all()


def test_row_provider_is_kept_in_dedup_key_and_batch_name_never_overrides() -> None:
    """A115-N002: two providers sharing a symbol are independent instruments, not duplicates."""

    from etf_cockpit.data.universe_import import dry_run_universe_import

    rows = [
        {"canonical_id": "INST-1", "ticker": "AAA", "provider": "p1", "provider_symbol": "S1"},
        {"canonical_id": "INST-2", "ticker": "BBB", "provider": "p2", "provider_symbol": "S1"},
        {"canonical_id": "INST-3", "ticker": "CCC", "provider": "p1", "provider_symbol": "S1"},
    ]
    report = dry_run_universe_import(rows, source_kind="provider", provider_name="batch")

    assert [record.instrument_id for record in report.records] == ["INST-1", "INST-2"]
    assert report.duplicate_rows == (3,)


def _etf(instrument_id: str, **overrides: object) -> SimpleNamespace:
    values = {"id": instrument_id, "name": instrument_id, "ticker": instrument_id, "provider_symbol": None, "isin": None}
    return SimpleNamespace(**(values | overrides))


def _state(*etfs: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(snapshot=SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=list(etfs)))))


def test_placeholder_isin_lookup_is_ambiguous_and_inactive_instruments_are_not_searchable(monkeypatch) -> None:
    """E104 N002/N003: placeholder ISINs are no identity key; disabled/merged instruments are hidden."""

    from etf_cockpit.app.components.shell.search import (
        exact_instrument_id,
        exact_instrument_status,
        instrument_matches,
        search_universe,
    )
    from etf_cockpit.application import score_views

    monkeypatch.setattr(score_views, "snapshot_scores", lambda _snapshot: [])
    state = _state(
        _etf("CBUK", isin="needs_verification"),
        _etf("EUNK", isin="needs_verification"),
        _etf("SADG", isin="needs_verification", lifecycle="merged"),
        _etf("RABO", enabled=False),
        _etf("VWCE", isin="IE00BK5BQT80"),
    )
    universe = search_universe(state)

    assert [item.id for item in universe.etfs] == ["CBUK", "EUNK", "VWCE"]
    assert exact_instrument_status(universe, "needs_verification") == "ambiguous"
    assert exact_instrument_id(universe, "needs_verification") is None
    assert instrument_matches(universe, "needs_verification") == []
    assert exact_instrument_status(universe, "IE00BK5BQT80") == "unique"
    assert exact_instrument_id(universe, "IE00BK5BQT80") == "VWCE"
    assert [item.id for item in search_universe(state, include_inactive=True).etfs] == ["CBUK", "EUNK", "SADG", "RABO", "VWCE"]


def test_a114_decision_hash_and_lifecycle_retrieval_are_insertion_order_independent(tmp_path: Path) -> None:
    """A114: decision hash, revision ordering and lifecycle retrieval do not depend on insertion order."""

    from etf_cockpit.data.fund_identity import FundLifecycleEvent, FundLifecycleStatus

    claims = (
        _dated("SEC-A", "ticker", "AAA", "a"),
        _dated("SEC-A", "isin", "US1111111111", "a"),
        _dated("SEC-A", "exchange", "XNAS", "a"),
    )

    def event(revision: int, status: FundLifecycleStatus, available_at: str) -> FundLifecycleEvent:
        return FundLifecycleEvent(
            fund_id="SEC-A",
            event_id="ev-1",
            status=status,
            effective_at="2024-02-01T00:00:00Z",
            available_at=available_at,
            source="fixture",
            source_id="fixture:ev",
            authority=SourceAuthority.OFFICIAL,
            revision=revision,
        )

    events = (
        event(1, FundLifecycleStatus.LAUNCHED, "2024-02-02T00:00:00Z"),
        event(2, FundLifecycleStatus.CLOSED, "2024-03-02T00:00:00Z"),
    )
    decisions: list[str] = []
    retrieved: list[tuple[tuple[str, int], ...]] = []
    for name, ordered_claims, ordered_events in (
        ("fwd", claims, events),
        ("rev", claims[::-1], events[::-1]),
    ):
        with IdentityMasterStore(tmp_path / name) as store:
            store.append_claims(ordered_claims)
            store.append_fund_lifecycle_events(ordered_events)
            decisions.append(
                store.resolve("SEC-A", effective_at="2024-06-01T00:00:00Z", decision_time="2024-06-01T00:00:00Z").decision_id
            )
            early = store.fund_lifecycle_events(
                "SEC-A", effective_at="2024-02-15T00:00:00Z", decision_time="2024-02-15T00:00:00Z"
            )
            late = store.fund_lifecycle_events(
                "SEC-A", effective_at="2024-06-01T00:00:00Z", decision_time="2024-06-01T00:00:00Z"
            )
            retrieved.append(tuple((item.status.value, item.revision) for item in (*early, *late)))

    assert decisions[0] == decisions[1]
    assert retrieved[0] == retrieved[1]
    assert retrieved[0] == (("launched", 1), ("closed", 2))


def test_e02_c2_n001_ticker_collision_keeps_distinct_canonical_candidates() -> None:
    """E02-C2-N001: two distinct canonical instruments sharing a ticker are both kept."""

    from etf_cockpit.data.universe_import import dry_run_universe_import

    rows = [
        {"canonical_id": "INST-1", "ticker": "SAME", "mic": "XAMS"},
        {"canonical_id": "INST-2", "ticker": "SAME", "mic": "XLON"},
    ]
    report = dry_run_universe_import(rows, source_kind="provider")

    assert [record.instrument_id for record in report.records] == ["INST-1", "INST-2"]
    assert report.duplicate_rows == ()
