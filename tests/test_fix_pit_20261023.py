from dataclasses import replace
from datetime import date
import json

import pandas as pd
import pytest

from etf_cockpit.data import fundamentals as fundamentals
from etf_cockpit.data import universe_membership as membership
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore, IdentitySourceRow
from etf_cockpit.data.instrument_identity import IdentityClaim


_VALUES = {"valuation": 7.0, "profitability": 6.0, "leverage": 5.0, "growth": 8.0, "shareholder_return": 4.0}
_SCOPE = "listing:euronext_oslo:all"


def _licensed(instrument_id, known_at="2026-01-02T00:00:00Z", **changes):
    return {
        "scope": _SCOPE, "instrument_id": instrument_id,
        "valid_from": "2026-01-01", "valid_to": None,
        "snapshot_date": "2026-01-01", "snapshot_complete": True,
        "known_at": known_at, **changes,
    }


def _identity_row(row_id, instrument_id, isin, **changes):
    return IdentitySourceRow(
        row_id=row_id, instrument_id=instrument_id, object_type="instrument",
        object_id=instrument_id, parent_object_id=None, relationship=None,
        identifiers={"isin": isin}, attributes={"ticker": instrument_id or row_id, "exchange": "XNAS"}, source="fixture",
        authority=SourceAuthority.OFFICIAL, source_id=instrument_id or row_id,
        valid_from="2026-01-01T00:00:00Z", available_at="2026-01-02T00:00:00Z",
        **changes,
    )


def test_future_available_at_not_score_eligible():
    """A11-F1: missing and future publications cannot become score inputs."""
    for available_at, reason in (
        (None, "ambiguous_available_at"), ("invalid", "ambiguous_available_at"),
        ("2026-02-28T00:00:00Z", "future_available_at"),
        ("2026-01-15T12:00:00Z", "future_available_at"),
        ("2026-01-15T00:00:00-05:00", "future_available_at"),
    ):
        evidence = fundamentals.build_fundamental_evidence(
            _VALUES, "MSFT", "2025-12-31", available_at=available_at, today=date(2026, 1, 15),
        )
        assert not evidence.score_eligible
        assert reason in evidence.warnings
        # Even legacy rows with an erroneously positive stored flag are blocked.
        row = {**_VALUES, "as_of_date": evidence.as_of, "available_at": available_at,
               "eligibility": "eligible", "score_eligible": True, "source_id": "fixture",
               "source_authority": "official", "sections_json": json.dumps(evidence.sections)}
        assessed = fundamentals.assess_fundamental_row(row, today=date(2026, 1, 15))
        assert not assessed.score_eligible
        assert reason in assessed.reasons
        assert assessed.freshness_status != "fresh"
    frame = pd.DataFrame([
        {"instrument_id": "MSFT", "as_of_date": "2025-12-31", "available_at": known, "valuation": value}
        for known, value in (("2026-01-02T00:00:00Z", 7.0), ("2026-02-28T00:00:00Z", 9.0), (None, 10.0))
    ])
    selected = fundamentals.latest_fundamental_rows(frame, decision_time="2026-01-15T00:00:00Z")
    assert selected["valuation"].tolist() == [7.0]
    eligible = fundamentals.build_fundamental_evidence(
        _VALUES, "MSFT", "2025-12-31", available_at="2026-01-15", today=date(2026, 1, 15),
    )
    assert eligible.score_eligible
    assert not eligible.executable_authority
    negative = fundamentals.build_fundamental_evidence(
        {**_VALUES, "valuation": -1.0}, "MSFT", "2025-12-31",
        available_at="2026-01-15", today=date(2026, 1, 15),
    )
    assert negative.eligibility == "eligible_negative_evidence"


def test_membership_known_at_rejects_future_interval(tmp_path):
    """A11-F2: dates and complete corrected snapshots respect source knowledge."""
    for changes in (
        {"snapshot_date": "2026-06-01"}, {"valid_to": "2026-12-31"},
        {"valid_from": "2026-06-01", "snapshot_date": "2026-06-01"},
    ):
        with pytest.raises(membership.MembershipCaptureError, match="after known_at"):
            membership.import_licensed_history([_licensed("MSFT", **changes)], "fixture", "licence", root=tmp_path)
        assert not tuple(tmp_path.iterdir())
    membership.import_licensed_history(
        [_licensed("MSFT"), _licensed("AAPL")], "fixture", "licence", root=tmp_path,
    )
    membership.import_licensed_history(
        [_licensed("msft", "2026-01-03T00:00:00Z"), _licensed("NEW", "2026-01-04T00:00:00Z")],
        "fixture", "licence", root=tmp_path,
    )
    before = membership.membership_frame(_SCOPE, "2026-01-03T12:00:00Z", root=tmp_path)
    after = membership.membership_frame(_SCOPE, "2026-01-04T00:00:00Z", root=tmp_path)
    assert set(before["instrument_id"]) == {"MSFT", "AAPL"}
    assert set(after["instrument_id"]) == {"msft", "NEW"}
    assert set(after["known_at"].str[:10]) == {"2026-01-04"}
    assert not after["instrument_id"].str.casefold().duplicated().any()
    with pytest.raises(membership.MembershipCaptureError, match="later source known_at"):
        membership.import_licensed_history([_licensed("MSFT")], "fixture", "licence", root=tmp_path)


def test_record_capture_rejects_backdated_snapshot(tmp_path):
    """A11-F3: fail atomically when day-resolution intervals cannot represent a capture."""
    membership.record_listing_capture(
        [{"instrument_id": "MSFT"}], "fixture", _SCOPE, "2026-01-02T12:00:00Z", root=tmp_path,
    )
    for rows, known_at, snapshot_date, message in (
        ([{"instrument_id": "MSFT"}, {"instrument_id": "AAPL"}], "2026-01-03T12:00:00Z", "2026-01-01", "backwards"),
        ([{"instrument_id": "AAPL"}], "2026-01-02T13:00:00Z", "2026-01-02", "on or before"),
    ):
        with pytest.raises(membership.MembershipCaptureError, match=message):
            membership.record_listing_capture(rows, "fixture", _SCOPE, known_at, root=tmp_path, snapshot_date=snapshot_date)
        assert len(membership.capture_log(_SCOPE, root=tmp_path)) == 1
        intervals = membership.membership_intervals(_SCOPE, "2026-01-04T00:00:00Z", root=tmp_path)
        assert intervals["instrument_id"].tolist() == ["MSFT"]
        assert intervals["valid_to"].isna().all()


def test_merge_ignores_future_period_context():
    """A11-F4: excluded context cannot erase an eligible period or its provenance."""
    present = {
        "instrument_id": "MSFT", "as_of_date": "2026-01-01", "source_id": "fixture",
        "source_authority": "official", "available_at": "2026-02-01T00:00:00Z",
        "freshness_status": "fresh", "sections": {
            field: {"value": value, "period_end": "2025-12-31", "note": "retained"}
            for field, value in _VALUES.items()
        },
    }
    future = {**present, "as_of_date": "2026-03-31", "available_at": "2026-05-01T00:00:00Z",
              "source_id": "future", "sections": None, **_VALUES}
    for future_instrument in ("MSFT", "AAPL"):
        merged = fundamentals.merge_fundamental_sources(
            present, {**future, "instrument_id": future_instrument}, decision_time="2026-03-01T00:00:00Z",
        )
        assert merged["valuation"] == 7.0
        assert merged["as_of_date"] == "2025-12-31"
        assert merged["sections"]["valuation"]["note"] == "retained"
        assert not merged["manual_review"]
        assert merged["excluded_candidate_count"] == 5
        assert merged["execution_allowed"] is False
    excluded = fundamentals.merge_fundamental_sources(future, decision_time="2026-03-01T00:00:00Z")
    assert "valuation" not in excluded
    assert "incompatible_metric_context" not in excluded["conflict_reason_codes"]


def test_duplicate_groups_use_latest_revision(tmp_path):
    """A11-F5: a corrected source stops quarantining the other instrument."""
    first = _identity_row("a1", "INST_A", "US0000000001")
    second = _identity_row("b1", "INST_B", "US0000000001")
    correction = replace(first, row_id="a2", identifiers={"isin": "US0000000002"},
                         revision=2, available_at="2026-01-03T00:00:00Z")
    with IdentityMasterStore(tmp_path) as store:
        initial = store.import_rows((first, second))
        assert set(initial.quarantined_row_ids) == {"a1", "b1"}
        corrected = store.import_rows((correction,))
        assert corrected.resolved_row_ids == ("a2",)
        assert not corrected.quarantined_row_ids
        for instrument in ("INST_A", "INST_B"):
            before = store.resolve(instrument, decision_time="2026-01-02T12:00:00Z")
            after = store.resolve(instrument, decision_time="2026-01-04T00:00:00Z")
            assert any(c.reason_code == "duplicate_identity" for c in before.conflicts)
            assert not any(c.reason_code == "duplicate_identity" for c in after.conflicts)
            assert not after.requires_manual_review
            assert not after.execution_allowed
        assert not any(c.reason_code == "duplicate_identity" for c in store.resolve("INST_B").conflicts)
        match = replace(_identity_row("match", "", "US0000000001"), available_at="2026-01-04T00:00:00Z")
        matched = store.import_rows((match,))
        assert matched.resolved_row_ids == ("match",)
        assert not matched.quarantined_row_ids


def test_entity_identifier_does_not_auto_merge_security(tmp_path):
    """A11-F6: an entity identifier cannot assign a second security to the first."""
    for field in ("lei", "cik", "national_id"):
        with IdentityMasterStore(tmp_path / field) as store:
            first = replace(_identity_row("first", "INST_A", "US0000000001"),
                            identifiers={"isin": "US0000000001", field: "shared-issuer"})
            store.import_rows((first,))
            new = replace(first, row_id="new", instrument_id="", object_id="",
                          identifiers={"isin": "US0000000002", field: "shared-issuer"})
            result = store.import_rows((new,))
            assert result.unresolved_row_ids == ("new",)
            assert not result.resolved_row_ids
            assert not result.execution_allowed
            assert {c.value for c in store.resolve("INST_A").claims if c.field == "isin"} == {"US0000000001"}


def test_claim_key_distinguishes_validity_intervals(tmp_path):
    """A11-F7: same revision may describe distinct intervals, publications and events."""
    claim = IdentityClaim(
        "MSFT", "ticker", "MSFT", "fixture", SourceAuthority.OFFICIAL, "fixture:ticker",
        valid_from="2026-01-01T00:00:00Z", valid_to="2026-02-01T00:00:00Z",
        available_at="2026-01-02T00:00:00Z",
    )
    later = replace(claim, value="MSFT.NEW", valid_from="2026-02-01T00:00:00Z", valid_to=None)
    variants = (claim, later, replace(claim, valid_to="2026-01-31T00:00:00Z"),
                replace(claim, available_at="2026-01-03T00:00:00Z"), replace(claim, event_type="ticker_changed"))
    with IdentityMasterStore(tmp_path) as store:
        keys = store.append_claims(variants)
        assert len(set(keys)) == len(variants)
        assert store.append_claims(variants) == keys
        early = store.resolve("MSFT", decision_time="2026-01-15T00:00:00Z")
        late = store.resolve("MSFT", decision_time="2026-02-02T00:00:00Z")
        assert early.identity.ticker == "MSFT"
        assert late.identity.ticker == "MSFT.NEW"


def test_persist_read_error_preserves_history(tmp_path, monkeypatch):
    """A11-F8: failed reads cannot turn existing history into an empty store."""
    clean = tmp_path / "fundamentals.parquet"
    first = fundamentals.build_fundamental_evidence(
        _VALUES, "MSFT", "2025-12-31", available_at="2026-01-02", today=date(2026, 1, 15),
    )
    fundamentals.persist_fundamental_evidence(first, raw_dir=tmp_path / "raw", clean_path=clean)
    original = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def unreadable(*args, **kwargs):
        raise OSError("injected parquet read failure")

    monkeypatch.setattr(fundamentals.pd, "read_parquet", unreadable)
    with pytest.raises(OSError, match="injected parquet read failure"):
        fundamentals.persist_fundamental_evidence(replace(first, instrument_id="AAPL"), raw_dir=tmp_path / "raw", clean_path=clean)
    with pytest.raises(OSError, match="injected parquet read failure"):
        fundamentals.load_fundamental_evidence(clean)
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == original
