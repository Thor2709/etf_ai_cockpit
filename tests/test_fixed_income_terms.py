from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

import pytest

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    ClassificationStore,
    resolve_instrument_context,
)
from etf_cockpit.data.fixed_income_terms import (
    FixedIncomeSecurityTerms,
    FixedIncomeTermsError,
    FixedIncomeTermsSchemaError,
    FixedIncomeTermsStore,
    OptionalitySchedule,
    SettlementConvention,
    fixed_income_terms_exists,
)
from etf_cockpit.data.identity_master import IdentityMasterStore
from etf_cockpit.data.instrument_identity import IdentityClaim
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.market_calendar import (
    BusinessDayConvention,
    DayCountConvention,
    SettlementCalendarEvidence,
)
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.ui_facade import load_fixed_income_terms_projection


UTC = timezone.utc
CHECKSUM = "a" * 64


def _identity(root: Path, instrument_id: str, issuer_id: str = "ISSUER-1") -> None:
    claims = (
        IdentityClaim(
            instrument_id,
            "name",
            issuer_id,
            "fixture",
            SourceAuthority.OFFICIAL,
            f"{issuer_id}:name",
            object_type="issuer",
            object_id=issuer_id,
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
            retrieved_at="2020-01-03T00:00:00Z",
        ),
        IdentityClaim(
            instrument_id,
            "isin",
            f"US{instrument_id[-10:]:0>10}"[:12],
            "fixture",
            SourceAuthority.OFFICIAL,
            f"{instrument_id}:isin",
            object_type="instrument",
            object_id=instrument_id,
            parent_object_id=issuer_id,
            relationship="issued_by",
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
            retrieved_at="2020-01-03T00:00:00Z",
        ),
    )
    with IdentityMasterStore(root) as store:
        store.append_claims(claims)


def _terms(
    instrument_id: str = "BOND-00001",
    *,
    issuer_id: str = "ISSUER-1",
    currency: str = "USD",
    calendar_id: str = "XNYS",
    issue_date: date = date(2024, 1, 15),
    maturity_date: date = date(2026, 1, 15),
    coupon_type: str = "fixed_rate",
    coupon_rate: Decimal = Decimal("0.05"),
    coupon_frequency: int = 2,
    revision: int = 1,
    known_at: datetime = datetime(2024, 1, 2, tzinfo=UTC),
    retrieved_at: datetime = datetime(2024, 1, 3, tzinfo=UTC),
    conflict_ids: tuple[str, ...] = (),
    features: tuple[str, ...] = (),
) -> FixedIncomeSecurityTerms:
    calendar = SettlementCalendarEvidence(
        settlement_calendar_id=f"{instrument_id}:settlement",
        instrument_id=instrument_id,
        calendar_id=calendar_id,
        timezone="America/New_York" if calendar_id == "XNYS" else "Europe/London",
        source_id="official:calendar",
        source_checksum=CHECKSUM,
        valid_from=date(2000, 1, 1),
        known_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    return FixedIncomeSecurityTerms(
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        security_type="government_bond",
        currency=currency,
        issue_date=issue_date,
        maturity_date=maturity_date,
        face_value=Decimal("1000"),
        minimum_denomination=Decimal("1000"),
        denomination_increment=Decimal("1000"),
        coupon_type=coupon_type,
        coupon_rate=coupon_rate,
        coupon_frequency=coupon_frequency,
        day_count=DayCountConvention.THIRTY_360_US,
        settlement=SettlementConvention(
            2,
            BusinessDayConvention.MODIFIED_FOLLOWING,
            calendar,
            1,
        ),
        source_id="official:prospectus",
        source_checksum=CHECKSUM,
        source_document="local://prospectus.pdf",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
        known_at=known_at,
        retrieved_at=retrieved_at,
        revision=revision,
        conflict_ids=conflict_ids,
        optionality=OptionalitySchedule(features, "official:prospectus"),
    )


def test_golden_fixed_rate_government_schedule_and_lineage(tmp_path: Path) -> None:
    _identity(tmp_path, "BOND-00001")
    terms = _terms()
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((terms,))
        result = store.resolve(
            terms.instrument_id,
            effective_at=datetime(2025, 1, 1, tzinfo=UTC),
            decision_time=datetime(2025, 1, 1, tzinfo=UTC),
        )
        projection = store.projection(terms.instrument_id)

    assert result.status == "available"
    assert [item.contractual_date for item in result.coupon_schedule.payments] == [
        date(2024, 7, 15),
        date(2025, 1, 15),
        date(2025, 7, 15),
        date(2026, 1, 15),
    ]
    assert {item.amount for item in result.coupon_schedule.payments} == {
        Decimal("25.00")
    }
    assert sum(item.amount for item in result.redemption_schedule.payments) == Decimal(
        "1000"
    )
    assert all(
        item.source_version_id == terms.version_id
        for item in result.coupon_schedule.payments
    )
    assert {
        (item.source_id, item.source_checksum)
        for item in result.coupon_schedule.payments
    } == {("official:prospectus", CHECKSUM)}
    assert projection["execution_allowed"] is False
    assert projection["pricing_allowed"] is False
    assert projection["terms"]["source_id"] == "official:prospectus"
    assert projection["terms"]["retrieved_at"] == "2024-01-03T00:00:00Z"


def test_golden_zero_coupon_corporate_gbp_has_only_redemption(tmp_path: Path) -> None:
    _identity(tmp_path, "BOND-00002", "ISSUER-CORP")
    terms = _terms(
        "BOND-00002",
        issuer_id="ISSUER-CORP",
        currency="GBP",
        calendar_id="XLON",
        issue_date=date(2024, 6, 3),
        maturity_date=date(2025, 6, 3),
        coupon_type="zero_coupon",
        coupon_rate=Decimal("0"),
        coupon_frequency=0,
    )
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((terms,))
        result = store.resolve(terms.instrument_id)
    assert result.status == "available"
    assert result.coupon_schedule.payments == ()
    assert result.redemption_schedule.payments[0].amount == Decimal("1000")
    assert result.redemption_schedule.payments[0].currency == "GBP"


def test_multiple_bonds_for_one_issuer_remain_distinct(tmp_path: Path) -> None:
    for instrument_id in ("BOND-00003", "BOND-00004"):
        _identity(tmp_path, instrument_id, "ISSUER-SHARED")
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append(
            (
                _terms("BOND-00003", issuer_id="ISSUER-SHARED"),
                _terms(
                    "BOND-00004",
                    issuer_id="ISSUER-SHARED",
                    maturity_date=date(2027, 1, 15),
                ),
            )
        )
        first = store.resolve("BOND-00003")
        second = store.resolve("BOND-00004")
    assert first.terms.issuer_id == second.terms.issuer_id == "ISSUER-SHARED"
    assert first.terms.instrument_id != second.terms.instrument_id
    assert first.terms.version_id != second.terms.version_id


def test_shared_classification_conflict_quarantines_terms(tmp_path: Path) -> None:
    instrument_id = "BOND-CLASS"
    _identity(tmp_path, instrument_id)
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"class:{field}",
            instrument_id=instrument_id,
            field=field,
            value=value,
            authority=SourceAuthority.OFFICIAL,
            confidence=1.0,
            source="fixture",
            source_id=f"class:{field}",
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in (
            ("instrument_type", "bond"),
            ("asset_class", "fixed_income"),
            ("coupon_type", "zero_coupon"),
        )
    )
    context = resolve_instrument_context(evidence, instrument_id=instrument_id)
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((_terms(instrument_id),))
        result = store.resolve(instrument_id, classification=context)
    assert result.status == "quarantined"
    assert "classification_terms_conflict" in result.reason_codes


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"maturity_date": date(2023, 1, 1)}, "maturity_date"),
        ({"currency": "US"}, "currency"),
        ({"minimum_denomination": Decimal("1500")}, "increment"),
        ({"coupon_frequency": 3}, "frequency"),
        ({"source_checksum": "bad"}, "source_checksum"),
    ),
)
def test_malformed_critical_terms_fail_closed(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    _identity(tmp_path, "BOND-BAD")
    with FixedIncomeTermsStore(tmp_path) as store:
        with pytest.raises(FixedIncomeTermsError, match=message):
            store.append((replace(_terms("BOND-BAD"), **change),))


def test_conflicts_and_unsupported_structures_quarantine_authority(
    tmp_path: Path,
) -> None:
    _identity(tmp_path, "BOND-CONFLICT")
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append(
            (
                _terms("BOND-CONFLICT", conflict_ids=("conflict-1",)),
            )
        )
        conflict = store.resolve("BOND-CONFLICT")
    assert conflict.status == "quarantined"
    assert conflict.coupon_schedule is None
    assert conflict.pricing_allowed is conflict.screening_allowed is False

    _identity(tmp_path, "BOND-CALL")
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((_terms("BOND-CALL", features=("callable",)),))
        unsupported = store.resolve("BOND-CALL")
    assert unsupported.status == "quarantined"
    assert "unsupported_structure" in unsupported.reason_codes
    assert unsupported.capability_flags["unsupported_structure_present"] is True

    _identity(tmp_path, "BOND-UNKNOWN")
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((_terms("BOND-UNKNOWN", features=("novel_feature",)),))
        unknown = store.resolve("BOND-UNKNOWN")
    assert unknown.status == "quarantined"
    assert "unsupported_structure" in unknown.reason_codes


def test_same_revision_critical_disagreement_is_quarantined(tmp_path: Path) -> None:
    _identity(tmp_path, "BOND-DISAGREE")
    official = _terms("BOND-DISAGREE")
    vendor = replace(
        official,
        coupon_rate=Decimal("0.07"),
        source_id="vendor:terms",
        source_checksum="b" * 64,
    )
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((official, vendor))
        result = store.resolve("BOND-DISAGREE")
    assert result.status == "quarantined"
    assert "critical_terms_conflict" in result.reason_codes
    assert result.coupon_schedule is None


def test_uncertified_future_calendar_fails_closed(tmp_path: Path) -> None:
    instrument_id = "BOND-CALENDAR"
    _identity(tmp_path, instrument_id)
    terms = _terms(instrument_id)
    future_calendar = replace(
        terms.settlement.payment_calendar,
        known_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    terms = replace(
        terms,
        settlement=replace(terms.settlement, payment_calendar=future_calendar),
    )
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((terms,))
        result = store.resolve(
            instrument_id,
            decision_time=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert result.status == "quarantined"
    assert result.coupon_schedule is None
    assert result.execution_allowed is False


def test_point_in_time_overlay_replay_preserves_original(tmp_path: Path) -> None:
    _identity(tmp_path, "BOND-REPLAY")
    original = _terms("BOND-REPLAY")
    correction = replace(
        original,
        coupon_rate=Decimal("0.06"),
        revision=2,
        known_at=datetime(2025, 2, 1, tzinfo=UTC),
        retrieved_at=datetime(2025, 2, 2, tzinfo=UTC),
        overlay_of=original.version_id,
        source_id="local:review-overlay",
    )
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((original, correction))
        historical = store.resolve(
            "BOND-REPLAY",
            effective_at=datetime(2025, 1, 1, tzinfo=UTC),
            decision_time=datetime(2025, 1, 1, tzinfo=UTC),
        )
        current = store.resolve(
            "BOND-REPLAY",
            effective_at=datetime(2025, 3, 1, tzinfo=UTC),
            decision_time=datetime(2025, 3, 1, tzinfo=UTC),
        )
        historical_projection = store.projection(
            "BOND-REPLAY",
            effective_at=datetime(2025, 1, 1, tzinfo=UTC),
            decision_time=datetime(2025, 1, 1, tzinfo=UTC),
        )
        current_projection = store.projection(
            "BOND-REPLAY",
            effective_at=datetime(2025, 3, 1, tzinfo=UTC),
            decision_time=datetime(2025, 3, 1, tzinfo=UTC),
        )
    assert historical.terms.version_id == original.version_id
    assert historical.coupon_schedule.payments[0].amount == Decimal("25.00")
    assert current.terms.version_id == correction.version_id
    assert current.coupon_schedule.payments[0].amount == Decimal("30.00")
    assert [item.version_id for item in current.history] == [
        original.version_id,
        correction.version_id,
    ]
    historical_encoded = json.dumps(historical_projection, sort_keys=True)
    assert correction.version_id not in historical_encoded
    assert "local:review-overlay" not in historical_encoded
    assert '"coupon_rate": "0.06"' not in historical_encoded
    assert historical_projection["excluded_versions"] == []
    assert [item["source_id"] for item in current_projection["history"]] == [
        "official:prospectus",
        "local:review-overlay",
    ]


def test_overlay_must_reference_same_retained_security(tmp_path: Path) -> None:
    _identity(tmp_path, "BOND-OVERLAY")
    invalid = replace(
        _terms("BOND-OVERLAY"),
        revision=2,
        overlay_of="f" * 64,
    )
    with FixedIncomeTermsStore(tmp_path) as store:
        with pytest.raises(FixedIncomeTermsError, match="overlay_of"):
            store.append((invalid,))


@pytest.mark.parametrize("frequency", (1, 2, 4, 12))
def test_coupon_dates_are_monotonic_for_supported_frequencies(
    tmp_path: Path, frequency: int
) -> None:
    instrument_id = f"BOND-FREQ-{frequency}"
    _identity(tmp_path, instrument_id)
    terms = _terms(
        instrument_id,
        issue_date=date(2024, 1, 15),
        maturity_date=date(2026, 1, 15),
        coupon_frequency=frequency,
    )
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((terms,))
        result = store.resolve(instrument_id)
    dates = [item.contractual_date for item in result.coupon_schedule.payments]
    assert dates == sorted(set(dates))
    assert dates[-1] == terms.maturity_date


def test_persistence_restart_idempotency_corruption_and_future_schema(
    tmp_path: Path,
) -> None:
    _identity(tmp_path, "BOND-PERSIST")
    terms = _terms("BOND-PERSIST")
    with FixedIncomeTermsStore(tmp_path) as store:
        assert store.append((terms,)) == store.append((terms,))
    with FixedIncomeTermsStore(tmp_path) as reopened:
        assert reopened.resolve("BOND-PERSIST").terms.version_id == terms.version_id

    database = storage_layout(tmp_path).transactional_path
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT entity_id, payload_json FROM transactional_records "
            "WHERE entity_type='fixed_income_terms_v1'"
        ).fetchone()
        payload = json.loads(row[1])
        payload["schema_version"] = 99
        connection.execute(
            "UPDATE transactional_records SET payload_json=? "
            "WHERE entity_type='fixed_income_terms_v1' AND entity_id=?",
            (json.dumps(payload), row[0]),
        )
    with pytest.raises(FixedIncomeTermsSchemaError, match="unsupported"):
        FixedIncomeTermsStore(tmp_path)


def test_concurrent_distinct_versions_are_not_lost(tmp_path: Path) -> None:
    _identity(tmp_path, "BOND-CONCURRENT")
    original = _terms("BOND-CONCURRENT")
    corrected = replace(
        original,
        revision=2,
        coupon_rate=Decimal("0.055"),
        known_at=datetime(2025, 1, 1, tzinfo=UTC),
        retrieved_at=datetime(2025, 1, 2, tzinfo=UTC),
        source_id="official:corrected-prospectus",
    )
    independent = replace(
        original,
        revision=3,
        coupon_rate=Decimal("0.06"),
        known_at=datetime(2025, 2, 1, tzinfo=UTC),
        retrieved_at=datetime(2025, 2, 2, tzinfo=UTC),
        source_id="official:restated-prospectus",
        source_checksum="c" * 64,
    )
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((original,))

    def write(item: FixedIncomeSecurityTerms) -> None:
        with FixedIncomeTermsStore(tmp_path) as store:
            first = store.append((item,))
            duplicate = store.append((item,))
            assert first == duplicate

    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(executor.map(write, (corrected, independent)))
    with FixedIncomeTermsStore(tmp_path) as store:
        result = store.resolve("BOND-CONCURRENT")
    assert len(result.history) == 3
    assert len({item.version_id for item in result.history}) == 3
    assert result.terms.revision == 3


def test_terms_existence_probe_is_read_only(tmp_path: Path) -> None:
    assert fixed_income_terms_exists(tmp_path) is False
    assert not storage_layout(tmp_path).transactional_path.exists()
    unavailable = load_fixed_income_terms_projection(
        "BOND-MISSING", storage_root=tmp_path
    )
    assert unavailable["status"] == "unavailable"
    assert unavailable["execution_allowed"] is False
    assert not storage_layout(tmp_path).transactional_path.exists()


def test_application_facade_and_api_return_same_read_only_projection(
    tmp_path: Path,
) -> None:
    _identity(tmp_path, "BOND-API")
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((_terms("BOND-API"),))

    facade = load_fixed_income_terms_projection(
        "BOND-API", storage_root=tmp_path
    )
    api = LocalApplicationApi(lambda: object(), root=tmp_path)
    projected = api.get_fixed_income_terms("BOND-API")

    assert facade["terms"] == projected["terms"]
    assert facade["coupon_schedule"] == projected["coupon_schedule"]
    assert facade["execution_allowed"] is projected["execution_allowed"] is False


def test_facade_and_api_apply_persisted_classification_at_same_cutoff(
    tmp_path: Path,
) -> None:
    instrument_id = "BOND-API-CLASS"
    _identity(tmp_path, instrument_id)
    with FixedIncomeTermsStore(tmp_path) as store:
        store.append((_terms(instrument_id),))
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"stored:{field}",
            instrument_id=instrument_id,
            field=field,
            value=value,
            authority=SourceAuthority.OFFICIAL,
            confidence=1.0,
            source="fixture",
            source_id=f"stored:{field}",
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in (
            ("instrument_type", "bond"),
            ("asset_class", "fixed_income"),
            ("coupon_type", "zero_coupon"),
        )
    )
    with ClassificationStore(tmp_path) as store:
        store.append_evidence(evidence)

    cutoff = "2025-01-01T00:00:00Z"
    facade = load_fixed_income_terms_projection(
        instrument_id,
        storage_root=tmp_path,
        effective_at=cutoff,
        decision_time=cutoff,
    )
    api = LocalApplicationApi(lambda: object(), root=tmp_path)
    projected = api.get_fixed_income_terms(
        instrument_id,
        effective_at=cutoff,
        decision_time=cutoff,
    )

    assert facade["status"] == projected["status"] == "quarantined"
    assert "classification_terms_conflict" in facade["reason_codes"]
    assert facade["coupon_schedule"] == projected["coupon_schedule"] == []
    assert facade["execution_allowed"] is projected["execution_allowed"] is False
