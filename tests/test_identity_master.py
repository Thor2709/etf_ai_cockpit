from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sqlite3

import pytest

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.instrument_identity import (
    IdentityClaim,
    IdentityResolutionError,
    IdentityReviewDecision,
)
from etf_cockpit.data.identity_master import (
    IdentityImportResult,
    IdentityMasterSchemaError,
    IdentityMasterStore,
    IdentitySourceRow,
    identity_master_exists,
)
from etf_cockpit.data.local_storage import storage_layout


def _row(
    row_id: str,
    instrument_id: str,
    *,
    object_type: str = "instrument",
    object_id: str | None = None,
    parent_object_id: str | None = None,
    relationship: str | None = None,
    isin: str | None = None,
    ticker: str | None = None,
    exchange: str | None = None,
    source: str = "fixture",
    source_id: str | None = None,
    authority: SourceAuthority = SourceAuthority.OFFICIAL,
    valid_from: str | None = "2024-01-01T00:00:00Z",
    valid_to: str | None = None,
    available_at: str | None = "2024-01-02T00:00:00Z",
    source_checksum: str = "",
) -> IdentitySourceRow:
    identifiers = {"isin": isin} if isin is not None else {}
    attributes = {}
    if ticker is not None:
        attributes["ticker"] = ticker
    if exchange is not None:
        attributes["exchange"] = exchange
    return IdentitySourceRow(
        row_id=row_id,
        instrument_id=instrument_id,
        object_type=object_type,
        object_id=instrument_id if object_id is None else object_id,
        parent_object_id=parent_object_id,
        relationship=relationship,
        identifiers=identifiers,
        attributes=attributes,
        source=source,
        authority=authority,
        source_id=source_id or f"{source}:{row_id}",
        valid_from=valid_from,
        valid_to=valid_to,
        available_at=available_at,
        source_checksum=source_checksum,
    )


def _claims(instrument_id: str, source_prefix: str) -> tuple[IdentityClaim, ...]:
    return (
        IdentityClaim(
            instrument_id,
            "ticker",
            instrument_id,
            "fixture",
            SourceAuthority.OFFICIAL,
            f"{source_prefix}:ticker",
            valid_from="2024-01-01T00:00:00Z",
            available_at="2024-01-02T00:00:00Z",
        ),
        IdentityClaim(
            instrument_id,
            "isin",
            f"US{instrument_id:0>10}"[:12],
            "fixture",
            SourceAuthority.OFFICIAL,
            f"{source_prefix}:isin",
            valid_from="2024-01-01T00:00:00Z",
            available_at="2024-01-02T00:00:00Z",
        ),
        IdentityClaim(
            instrument_id,
            "exchange",
            "XNAS",
            "fixture",
            SourceAuthority.OFFICIAL,
            f"{source_prefix}:exchange",
            valid_from="2024-01-01T00:00:00Z",
            available_at="2024-01-02T00:00:00Z",
        ),
    )


def test_import_rows_result_and_projection_are_fail_closed(tmp_path: Path) -> None:
    rows = (
        _row("known", "SEC-KNOWN", isin="US0000000001", ticker="KNOWN", exchange="XNAS"),
        _row("unresolved", "", object_id="", isin=None, ticker="MISSING"),
    )
    with IdentityMasterStore(tmp_path) as store:
        result = store.import_rows(rows)
        assert isinstance(result, IdentityImportResult)
        assert set(result.resolved_row_ids) == {"known"}
        assert set(result.unresolved_row_ids) == {"unresolved"}
        assert not result.quarantined_row_ids
        assert result.execution_allowed is False
        projection = store.projection("SEC-KNOWN")
        assert projection["execution_allowed"] is False
        assert projection.get("status") in {"available", "resolved"}
        assert projection.get("instrument_id") == "SEC-KNOWN"


def test_explicit_instrument_without_any_identity_evidence_remains_unresolved(tmp_path: Path) -> None:
    empty = _row("empty", "SEC-EMPTY", isin=None, ticker=None, exchange=None)
    with IdentityMasterStore(tmp_path) as store:
        result = store.import_rows((empty,))

        assert result.resolved_row_ids == ()
        assert result.unresolved_row_ids == ("empty",)
        with pytest.raises(KeyError):
            store.projection("SEC-EMPTY")


def test_read_only_existence_probe_does_not_create_local_storage(tmp_path: Path) -> None:
    assert identity_master_exists(tmp_path) is False
    assert not storage_layout(tmp_path).transactional_path.exists()


def test_existing_partial_identity_store_is_invalid_not_absent(tmp_path: Path) -> None:
    path = storage_layout(tmp_path).transactional_path
    path.parent.mkdir(parents=True)
    sqlite3.connect(path).close()

    with pytest.raises(IdentityMasterSchemaError, match="without the transactional schema"):
        identity_master_exists(tmp_path)


def test_cross_instrument_duplicate_isin_quarantines_candidates_and_retains_conflict(tmp_path: Path) -> None:
    rows = (
        _row("row-a", "SEC-A", isin="US1111111111", ticker="AAA", exchange="XNAS", source_id="official:a"),
        _row("row-b", "SEC-B", isin="US1111111111", ticker="BBB", exchange="XLON", source_id="official:b"),
    )
    with IdentityMasterStore(tmp_path) as store:
        result = store.import_rows(rows)
        assert set(result.quarantined_row_ids) == {"row-a", "row-b"}
        assert result.conflict_ids
        for instrument_id in ("SEC-A", "SEC-B"):
            projection = store.projection(instrument_id)
            assert projection["execution_allowed"] is False
            assert projection["identity_conflicts"]
            candidates = projection["identity_conflicts"]
            candidate_text = json.dumps(candidates, sort_keys=True)
            assert "US1111111111" in candidate_text
            assert "SEC-A" in candidate_text or "SEC-B" in candidate_text


def test_identity_graph_preserves_typed_issuer_fund_debt_listing_and_broker_objects(tmp_path: Path) -> None:
    instrument_id = "FUND-1"
    claims = [
        IdentityClaim(instrument_id, "name", "Issuer One", "fixture", SourceAuthority.OFFICIAL, "issuer:name", object_type="issuer", object_id="ISSUER-1", relationship="issuer_of"),
        IdentityClaim(instrument_id, "name", "Guarantor One", "fixture", SourceAuthority.OFFICIAL, "guarantor:name", object_type="guarantor", object_id="GUARANTOR-1", relationship="guarantees"),
        IdentityClaim(instrument_id, "isin", "IE0000000001", "fixture", SourceAuthority.OFFICIAL, "instrument:isin", object_type="instrument", object_id="FUND-1", parent_object_id="SC-1", relationship="share_class_of"),
        IdentityClaim(instrument_id, "debt_identifier", "DEBT-1", "fixture", SourceAuthority.OFFICIAL, "debt:identifier", object_type="debt_series", object_id="DEBT-1", parent_object_id="ISSUER-1", relationship="issued_by"),
        IdentityClaim(instrument_id, "name", "Fund vehicle", "fixture", SourceAuthority.OFFICIAL, "vehicle:name", object_type="fund_vehicle", object_id="VEHICLE-1", parent_object_id="ISSUER-1", relationship="managed_by"),
        IdentityClaim(instrument_id, "name", "Umbrella", "fixture", SourceAuthority.OFFICIAL, "umbrella:name", object_type="umbrella", object_id="UMBRELLA-1", relationship="umbrella_for"),
        IdentityClaim(instrument_id, "name", "Subfund", "fixture", SourceAuthority.OFFICIAL, "subfund:name", object_type="subfund", object_id="SUBFUND-1", parent_object_id="UMBRELLA-1", relationship="subfund_of"),
        IdentityClaim(instrument_id, "share_class", "Accumulating", "fixture", SourceAuthority.OFFICIAL, "share:name", object_type="share_class", object_id="SC-1", parent_object_id="SUBFUND-1", relationship="share_class_of"),
        IdentityClaim(instrument_id, "ticker", "FND", "fixture", SourceAuthority.OFFICIAL, "listing:ticker", object_type="listing", object_id="LISTING-XNAS", parent_object_id="SC-1", relationship="quotation_for"),
        IdentityClaim(instrument_id, "market", "XNAS", "fixture", SourceAuthority.OFFICIAL, "dealing:market", object_type="dealing", object_id="DEALING-XNAS", parent_object_id="LISTING-XNAS", relationship="deals_on"),
        IdentityClaim(instrument_id, "name", "Broker One", "fixture", SourceAuthority.OFFICIAL, "broker:name", object_type="broker", object_id="BROKER-1", parent_object_id="DEALING-XNAS", relationship="intermediates"),
    ]
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        result = store.resolve(instrument_id)
        object_keys = {(item.object_type, item.object_id) for item in result.objects}
        assert {item.object_type for item in result.objects} >= {
            "issuer",
            "guarantor",
            "instrument",
            "debt_series",
            "fund_vehicle",
            "umbrella",
            "subfund",
            "share_class",
            "listing",
            "dealing",
            "broker",
        }
        assert len(object_keys) == len(result.objects)
        assert result.execution_allowed is False


def test_point_in_time_listing_and_lifecycle_replay_excludes_future_knowledge(tmp_path: Path) -> None:
    claims = (
        IdentityClaim(
            "SEC-1", "ticker", "OLD", "fixture", SourceAuthority.OFFICIAL, "listing:1",
            object_type="listing", object_id="LISTING-XNAS", parent_object_id="SEC-1", relationship="quotation_for",
            valid_from="2020-01-01T00:00:00Z", valid_to="2024-06-01T00:00:00Z", available_at="2020-01-02T00:00:00Z", event_type="listing_created",
        ),
        IdentityClaim(
            "SEC-1", "ticker", "NEW", "fixture", SourceAuthority.OFFICIAL, "listing:1",
            object_type="listing", object_id="LISTING-XNAS", parent_object_id="SEC-1", relationship="quotation_for",
            valid_from="2024-06-01T00:00:00Z", available_at="2024-06-02T00:00:00Z", revision=2, event_type="ticker_changed",
        ),
        IdentityClaim("SEC-1", "isin", "US0000000001", "fixture", SourceAuthority.OFFICIAL, "instrument:1", valid_from="2020-01-01T00:00:00Z", available_at="2020-01-02T00:00:00Z"),
        IdentityClaim("SEC-1", "exchange", "XNAS", "fixture", SourceAuthority.OFFICIAL, "instrument:1", valid_from="2020-01-01T00:00:00Z", available_at="2020-01-02T00:00:00Z"),
    )
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        old = store.resolve("SEC-1", effective_at="2024-05-01T00:00:00Z", decision_time="2024-05-01T00:00:00Z")
        new = store.resolve("SEC-1", effective_at="2024-07-01T00:00:00Z", decision_time="2024-07-01T00:00:00Z")
        listing_old = next(item for item in old.objects if item.object_id == "LISTING-XNAS")
        listing_new = next(item for item in new.objects if item.object_id == "LISTING-XNAS")
        assert listing_old.fields["ticker"] == "OLD"
        assert listing_new.fields["ticker"] == "NEW"
        assert [entry.value for entry in old.history if entry.object_id == "LISTING-XNAS"] == ["OLD"]
        assert [entry.value for entry in new.history if entry.object_id == "LISTING-XNAS"] == ["OLD", "NEW"]
        assert [claim.value for claim in old.excluded_claims] == ["NEW"]
        assert new.execution_allowed is False


def test_multiple_securities_and_share_classes_under_one_issuer_remain_distinct(tmp_path: Path) -> None:
    claims = []
    for suffix, isin, share_class in (("A", "US0000000002", "ACC"), ("B", "US0000000003", "DIST")):
        instrument_id = f"SEC-{suffix}"
        claims.extend(
            (
                IdentityClaim(instrument_id, "isin", isin, "fixture", SourceAuthority.OFFICIAL, f"{suffix}:isin", object_type="instrument", object_id=instrument_id, parent_object_id="ISSUER-1", relationship="issued_by"),
                IdentityClaim(instrument_id, "ticker", f"{suffix}{suffix}", "fixture", SourceAuthority.OFFICIAL, f"{suffix}:ticker", object_type="listing", object_id=f"LISTING-{suffix}", parent_object_id=instrument_id, relationship="quotation_for"),
                IdentityClaim(instrument_id, "share_class", share_class, "fixture", SourceAuthority.OFFICIAL, f"{suffix}:share", object_type="share_class", object_id=f"SC-{suffix}", parent_object_id=instrument_id, relationship="share_class_of"),
            )
        )
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        first = store.resolve("SEC-A")
        second = store.resolve("SEC-B")
        assert first.identity.isin == "US0000000002"
        assert second.identity.isin == "US0000000003"
        assert {obj.object_id for obj in first.objects} & {"SC-A", "LISTING-A"}
        assert {obj.object_id for obj in second.objects} & {"SC-B", "LISTING-B"}
        assert {obj.object_id for obj in first.objects}.isdisjoint({"SC-B", "LISTING-B"})


def test_similar_identifier_is_not_fuzzy_matched_or_invented(tmp_path: Path) -> None:
    with IdentityMasterStore(tmp_path) as store:
        store.import_rows((_row("known", "SEC-KNOWN", isin="US1234567890", ticker="KNOWN", exchange="XNAS"),))
        result = store.import_rows(
            (_row("near-match", "", object_id="", isin="US1234567891", ticker="UNKNOWN"),)
        )

        assert result.resolved_row_ids == ()
        assert result.unresolved_row_ids == ("near-match",)
        assert store.resolve("SEC-KNOWN").identity.isin == "US1234567890"


def test_exact_match_cannot_use_identity_evidence_unknown_at_the_source_row_cutoff(tmp_path: Path) -> None:
    future = _row(
        "future",
        "SEC-FUTURE",
        isin="US2222222222",
        ticker="FUTURE",
        exchange="XNAS",
        valid_from="2026-01-01T00:00:00Z",
        available_at="2026-01-02T00:00:00Z",
    )
    historical_unresolved = _row(
        "historical",
        "",
        object_id="",
        isin="US2222222222",
        valid_from="2024-01-01T00:00:00Z",
        available_at="2024-01-02T00:00:00Z",
    )
    with IdentityMasterStore(tmp_path) as store:
        store.import_rows((future,))
        result = store.import_rows((historical_unresolved,))

        assert result.resolved_row_ids == ()
        assert result.unresolved_row_ids == ("historical",)
        with pytest.raises((KeyError, ValueError)):
            store.resolve(
                "SEC-FUTURE",
                effective_at="2024-06-01T00:00:00Z",
                decision_time="2024-06-01T00:00:00Z",
            )


def test_exact_match_to_multiple_entities_is_quarantined_with_stable_conflict(tmp_path: Path) -> None:
    shared_lei = "5493001KJTIIGC8Y1R12"
    claims = tuple(
        IdentityClaim(
            instrument_id,
            "lei",
            shared_lei,
            "gleif",
            SourceAuthority.OFFICIAL,
            f"gleif:{instrument_id}",
            object_type="issuer",
            object_id="ISSUER-SHARED",
            valid_from="2024-01-01T00:00:00Z",
            available_at="2024-01-02T00:00:00Z",
        )
        for instrument_id in ("SEC-A", "SEC-B")
    )
    unresolved = IdentitySourceRow(
        row_id="ambiguous-lei",
        instrument_id="",
        object_type="issuer",
        object_id="ISSUER-SHARED",
        parent_object_id=None,
        relationship=None,
        identifiers={"lei": shared_lei},
        attributes={"name": "Shared issuer"},
        source="gleif",
        authority=SourceAuthority.OFFICIAL,
        source_id="gleif:ambiguous",
        valid_from="2024-02-01T00:00:00Z",
        available_at="2024-02-02T00:00:00Z",
    )
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        first = store.import_rows((unresolved,))
        second = store.import_rows((unresolved,))

    assert first.resolved_row_ids == first.unresolved_row_ids == ()
    assert first.quarantined_row_ids == ("ambiguous-lei",)
    assert first.conflict_ids == second.conflict_ids
    assert len(first.conflict_ids) == 1


def test_fund_share_class_fees_currencies_distribution_and_hedging_remain_distinct(tmp_path: Path) -> None:
    claims: list[IdentityClaim] = []
    for class_id, isin, distribution, currency, hedge_state, fee_bps in (
        ("SC-ACC-H", "IE0000000011", "accumulating", "EUR", "hedged", "18"),
        ("SC-DIST-U", "IE0000000012", "distributing", "USD", "unhedged", "12"),
    ):
        for field, value in (
            ("isin", isin),
            ("distribution_policy", distribution),
            ("share_class_currency", currency),
            ("hedge_state", hedge_state),
            ("ongoing_fee_bps", fee_bps),
        ):
            claims.append(
                IdentityClaim(
                    "FUND-STRATEGY-1",
                    field,
                    value,
                    "issuer",
                    SourceAuthority.ISSUER,
                    f"issuer:{class_id}",
                    object_type="share_class",
                    object_id=class_id,
                    parent_object_id="SUBFUND-1",
                    relationship="share_class_of",
                    valid_from="2024-01-01T00:00:00Z",
                    available_at="2024-01-02T00:00:00Z",
                )
            )

    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        result = store.resolve("FUND-STRATEGY-1")

    classes = {item.object_id: item.fields for item in result.objects if item.object_type == "share_class"}
    assert classes["SC-ACC-H"] == {
        "distribution_policy": "accumulating",
        "hedge_state": "hedged",
        "isin": "IE0000000011",
        "ongoing_fee_bps": "18",
        "share_class_currency": "EUR",
    }
    assert classes["SC-DIST-U"] == {
        "distribution_policy": "distributing",
        "hedge_state": "unhedged",
        "isin": "IE0000000012",
        "ongoing_fee_bps": "12",
        "share_class_currency": "USD",
    }
    assert not result.conflicts


def test_broker_contract_history_replays_without_collapsing_contract_object(tmp_path: Path) -> None:
    claims = (
        IdentityClaim(
            "SEC-BROKER",
            "broker_contract_id",
            "OLD-CONTRACT",
            "broker-import",
            SourceAuthority.VENDOR,
            "broker:contract",
            object_type="broker_contract",
            object_id="BROKER-CONTRACT-1",
            parent_object_id="LISTING-XNAS",
            relationship="routes_listing",
            valid_from="2023-01-01T00:00:00Z",
            valid_to="2025-01-01T00:00:00Z",
            available_at="2023-01-02T00:00:00Z",
            event_type="contract_created",
        ),
        IdentityClaim(
            "SEC-BROKER",
            "broker_contract_id",
            "NEW-CONTRACT",
            "broker-import",
            SourceAuthority.VENDOR,
            "broker:contract",
            object_type="broker_contract",
            object_id="BROKER-CONTRACT-1",
            parent_object_id="LISTING-XNAS",
            relationship="routes_listing",
            valid_from="2025-01-01T00:00:00Z",
            available_at="2025-01-02T00:00:00Z",
            revision=2,
            event_type="contract_changed",
        ),
    )
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        old = store.resolve(
            "SEC-BROKER",
            effective_at="2024-01-01T00:00:00Z",
            decision_time="2024-01-01T00:00:00Z",
        )
        current = store.resolve(
            "SEC-BROKER",
            effective_at="2026-01-01T00:00:00Z",
            decision_time="2026-01-01T00:00:00Z",
        )

    assert old.objects[0].fields["broker_contract_id"] == "OLD-CONTRACT"
    assert current.objects[0].fields["broker_contract_id"] == "NEW-CONTRACT"
    assert [entry.event_type for entry in current.history] == ["contract_created", "contract_changed"]
    assert old.execution_allowed is current.execution_allowed is False


def test_persistence_is_idempotent_and_invalid_batch_rolls_back_atomically(tmp_path: Path) -> None:
    valid = _row("valid", "SEC-VALID", isin="US0000000004", ticker="VALID", exchange="XNAS")
    invalid = _row("invalid", "SEC-INVALID", isin="US0000000005", ticker="INVALID", exchange="XNAS", authority="not-an-authority")  # type: ignore[arg-type]
    with IdentityMasterStore(tmp_path) as store:
        first = store.import_rows((valid,))
        second = store.import_rows((valid,))
        assert first.resolved_row_ids == second.resolved_row_ids == ("valid",)
        with pytest.raises(IdentityMasterSchemaError):
            store.import_rows((valid, invalid))

    with IdentityMasterStore(tmp_path) as reopened:
        assert reopened.resolve("SEC-VALID").identity.isin == "US0000000004"
        with pytest.raises((KeyError, ValueError, IdentityMasterSchemaError)):
            reopened.resolve("SEC-INVALID")


def test_append_claims_preserves_retrieval_observations_and_exact_idempotency(
    tmp_path: Path,
) -> None:
    claim = IdentityClaim(
        "SEC-CHRONOLOGY",
        "ticker",
        "CHRON",
        "fixture",
        SourceAuthority.OFFICIAL,
        "official:ticker",
        valid_from="2024-01-01T00:00:00Z",
        available_at="2024-01-02T00:00:00Z",
        retrieved_at="2024-01-03T00:00:00Z",
    )
    later = replace(claim, retrieved_at="2024-02-03T00:00:00Z")
    with IdentityMasterStore(tmp_path) as store:
        first_id = store.append_claims((claim,))
        duplicate_id = store.append_claims((claim,))
        later_id = store.append_claims((later,))

        assert first_id == duplicate_id
        assert later_id != first_id
        current = store.resolve("SEC-CHRONOLOGY")
        historical = store.resolve(
            "SEC-CHRONOLOGY",
            effective_at="2024-01-15T00:00:00Z",
            decision_time="2024-01-15T00:00:00Z",
        )

    assert [item.retrieved_at for item in current.claims] == [
        "2024-01-03T00:00:00Z",
        "2024-02-03T00:00:00Z",
    ]
    assert [item.retrieved_at for item in historical.claims] == [
        "2024-01-03T00:00:00Z"
    ]
    assert [item.retrieved_at for item in historical.excluded_claims] == [
        "2024-02-03T00:00:00Z"
    ]


def test_identity_master_replays_legacy_v1_decision_and_projects_v2_schema(
    tmp_path: Path,
) -> None:
    claims = _claims("SEC-LEGACY", "legacy")
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        first = store.resolve("SEC-LEGACY", decision_schema_version=1)
        replay = store.resolve("SEC-LEGACY", decision_schema_version=1)
        current = store.resolve("SEC-LEGACY")
        projection = store.projection("SEC-LEGACY")

    assert first.decision_id == replay.decision_id
    assert first.decision_schema_version == 1
    assert current.decision_schema_version == 2
    assert projection["identity_decision_schema_version"] == 2
    assert projection["execution_allowed"] is False
    with IdentityMasterStore(tmp_path) as store:
        with pytest.raises(
            IdentityResolutionError, match="unsupported identity decision schema"
        ):
            store.resolve("SEC-LEGACY", decision_schema_version=99)


def test_pre_retrieval_field_v1_records_remain_readable_and_replayable(
    tmp_path: Path,
) -> None:
    claims = _claims("SEC-OLD-RECORD", "old-record")
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        expected = store.resolve(
            "SEC-OLD-RECORD", decision_schema_version=1
        ).decision_id

    with sqlite3.connect(storage_layout(tmp_path).transactional_path) as connection:
        rows = connection.execute(
            "SELECT entity_id, payload_json FROM transactional_records "
            "WHERE entity_type = 'identity_claim_v1'"
        ).fetchall()
        for entity_id, encoded in rows:
            payload = json.loads(encoded)
            payload["claim"].pop("retrieved_at", None)
            connection.execute(
                "UPDATE transactional_records SET payload_json = ? "
                "WHERE entity_type = 'identity_claim_v1' AND entity_id = ?",
                (json.dumps(payload, sort_keys=True), entity_id),
            )

    with IdentityMasterStore(tmp_path) as store:
        replay = store.resolve("SEC-OLD-RECORD", decision_schema_version=1)
    assert replay.decision_id == expected
    assert all(claim.retrieved_at is None for claim in replay.claims)


def test_source_checksum_must_be_auditable_sha256(tmp_path: Path) -> None:
    invalid = _row(
        "bad-checksum",
        "SEC-CHECKSUM",
        isin="US0000000042",
        ticker="CHECK",
        source_checksum="not-a-sha256",
    )
    with IdentityMasterStore(tmp_path) as store:
        with pytest.raises(IdentityMasterSchemaError, match="source_checksum"):
            store.import_rows((invalid,))
        with pytest.raises(KeyError):
            store.resolve("SEC-CHECKSUM")


def test_two_concurrent_writers_commit_without_lost_identity_rows(tmp_path: Path) -> None:
    def write(instrument_id: str) -> None:
        with IdentityMasterStore(tmp_path) as store:
            store.append_claims(_claims(instrument_id, f"writer:{instrument_id}"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, instrument_id) for instrument_id in ("CONCURRENT-A", "CONCURRENT-B")]
        for future in futures:
            future.result()

    with IdentityMasterStore(tmp_path) as store:
        assert store.resolve("CONCURRENT-A").identity.ticker == "CONCURRENT-A"
        assert store.resolve("CONCURRENT-B").identity.ticker == "CONCURRENT-B"


def test_concurrent_retrieval_observations_are_both_retained(tmp_path: Path) -> None:
    base = IdentityClaim(
        "CONCURRENT-CHRONOLOGY",
        "ticker",
        "CC",
        "fixture",
        SourceAuthority.OFFICIAL,
        "official:ticker",
        valid_from="2024-01-01T00:00:00Z",
        available_at="2024-01-02T00:00:00Z",
    )

    def write(retrieved_at: str) -> None:
        with IdentityMasterStore(tmp_path) as store:
            store.append_claims((replace(base, retrieved_at=retrieved_at),))

    retrievals = ("2024-01-03T00:00:00Z", "2024-02-03T00:00:00Z")
    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(executor.map(write, retrievals))

    with IdentityMasterStore(tmp_path) as store:
        resolution = store.resolve("CONCURRENT-CHRONOLOGY")
    assert tuple(item.retrieved_at for item in resolution.claims) == retrievals


def test_concurrent_duplicate_import_results_are_serialized_with_quarantine(tmp_path: Path) -> None:
    rows = (
        _row("concurrent-a", "SEC-A", isin="US3333333333", ticker="AAA", exchange="XNAS"),
        _row("concurrent-b", "SEC-B", isin="US3333333333", ticker="BBB", exchange="XLON"),
    )

    def write(row: IdentitySourceRow) -> IdentityImportResult:
        with IdentityMasterStore(tmp_path) as store:
            return store.import_rows((row,))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(write, rows))

    assert sum(bool(result.resolved_row_ids) for result in results) == 1
    assert sum(bool(result.quarantined_row_ids) for result in results) == 1
    assert next(result for result in results if result.quarantined_row_ids).conflict_ids
    with IdentityMasterStore(tmp_path) as store:
        assert store.resolve("SEC-A").resolution_state == "quarantined"
        assert store.resolve("SEC-B").resolution_state == "quarantined"


def test_corrupt_or_unsupported_identity_schema_fails_closed(tmp_path: Path) -> None:
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(_claims("SEC-SCHEMA", "schema"))
    layout = storage_layout(tmp_path)
    with sqlite3.connect(layout.transactional_path) as connection:
        connection.execute(
            "UPDATE transactional_records SET payload_json = ? WHERE entity_type = 'identity_master_meta' AND entity_id = 'schema'",
            (json.dumps({"schema_version": 2, "contract": "identity-master.v1"}),),
        )
    with pytest.raises(IdentityMasterSchemaError, match="newer than supported"):
        with IdentityMasterStore(tmp_path):
            pass

    corrupt_root = tmp_path / "corrupt"
    with IdentityMasterStore(corrupt_root) as store:
        store.append_claims(_claims("SEC-CORRUPT", "corrupt"))
    with sqlite3.connect(storage_layout(corrupt_root).transactional_path) as connection:
        connection.execute(
            "UPDATE transactional_records SET payload_json = ? WHERE entity_type = 'identity_master_meta' AND entity_id = 'schema'",
            ("{not-json",),
        )
    with pytest.raises(IdentityMasterSchemaError):
        with IdentityMasterStore(corrupt_root):
            pass


def test_future_review_does_not_rewrite_historical_decision_and_projection_exposes_lineage(tmp_path: Path) -> None:
    claims = (
        IdentityClaim("SEC-REVIEW", "isin", "US0000000006", "fixture", SourceAuthority.VENDOR, "vendor:isin", valid_from="2024-01-01T00:00:00Z", available_at="2024-01-02T00:00:00Z"),
        IdentityClaim("SEC-REVIEW", "isin", "US0000000007", "fixture", SourceAuthority.OFFICIAL, "official:isin", valid_from="2024-01-01T00:00:00Z", available_at="2024-01-02T00:00:00Z"),
        IdentityClaim("SEC-REVIEW", "ticker", "REV", "fixture", SourceAuthority.OFFICIAL, "official:ticker", valid_from="2024-01-01T00:00:00Z", available_at="2024-01-02T00:00:00Z"),
        IdentityClaim("SEC-REVIEW", "exchange", "XNAS", "fixture", SourceAuthority.OFFICIAL, "official:exchange", valid_from="2024-01-01T00:00:00Z", available_at="2024-01-02T00:00:00Z"),
    )
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        initial = store.resolve("SEC-REVIEW", effective_at="2024-06-01T00:00:00Z", decision_time="2024-06-01T00:00:00Z")
        conflict_id = initial.conflicts[0].conflict_id
        store.append_reviews(
            (
                IdentityReviewDecision(
                    conflict_id,
                    "vendor:isin",
                    "reviewer-1",
                    "2026-01-01T00:00:00Z",
                    "Retained candidate verified after historical decision",
                ),
            )
        )
        historical = store.resolve("SEC-REVIEW", effective_at="2024-06-01T00:00:00Z", decision_time="2024-06-01T00:00:00Z")
        current = store.resolve("SEC-REVIEW", effective_at="2026-02-01T00:00:00Z", decision_time="2026-02-01T00:00:00Z")
        projection = store.projection("SEC-REVIEW", effective_at="2026-02-01T00:00:00Z", decision_time="2026-02-01T00:00:00Z")

        assert historical.decision_id == initial.decision_id
        assert historical.conflicts[0].resolution_status == "manual_review"
        assert current.identity.isin == "US0000000006"
        assert current.conflicts[0].resolution_status == "reviewed"
        assert projection["execution_allowed"] is False
        assert {"identity_objects", "identity_conflicts", "identity_history", "identity_reviews", "execution_allowed"} <= set(projection)
        assert projection["identity_reviews"]
