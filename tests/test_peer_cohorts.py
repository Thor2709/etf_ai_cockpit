from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from etf_cockpit.analysis.peer_cohorts import (
    AdapterDefinition,
    AdapterRegistry,
    PeerCohortError,
    PeerObservation,
    build_peer_projection,
    canonical_peer_result_payload,
    calculate_peer_metric,
    construct_cohort,
    effective_sample_size,
    peer_result_hash,
    weighted_empirical_cdf,
)
from etf_cockpit.application.ui_facade import load_peer_cohort_projection
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    ClassificationStore,
    resolve_instrument_context,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.peer_cohort_store import (
    PeerCohortStore,
    PeerCohortStoreError,
    build_point_in_time_peer_projection,
    read_peer_cohort_projection,
)
from etf_cockpit.services import build_snapshot


AS_OF = "2024-06-30T00:00:00Z"
DECISION = "2024-07-02T00:00:00Z"


def _context(
    instrument_id: str,
    *,
    sector: str = "technology",
    industry: str = "software",
    confidence: float = 0.95,
    cap_bucket: str = "large",
):
    values = {
        "instrument_type": "stock",
        "asset_class": "equity",
        "sector": sector,
        "industry": industry,
        "operating_country": "NO",
        "reporting_currency": "NOK",
        "cap_bucket": cap_bucket,
        "business_model_tag": "subscription",
        "entity_id": instrument_id,
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument_id}:{field}",
            instrument_id=instrument_id,
            field=field,
            value=value,
            source="test",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"test:{instrument_id}:{field}",
            confidence=confidence if field in {"sector", "industry"} else 0.99,
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(
        evidence,
        instrument_id=instrument_id,
        effective_at=AS_OF,
        decision_time=DECISION,
    )


def _stored_evidence(
    instrument_id: str,
    *,
    sector: str = "technology",
    valid_from: str = "2020-01-01T00:00:00Z",
    available_at: str = "2020-01-02T00:00:00Z",
    revision: int = 1,
):
    values = {
        "instrument_type": "stock",
        "asset_class": "equity",
        "sector": sector,
        "industry": "software",
        "operating_country": "NO",
        "reporting_currency": "NOK",
        "cap_bucket": "large",
        "entity_id": instrument_id,
    }
    return tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument_id}:{field}",
            instrument_id=instrument_id,
            field=field,
            value=value,
            source="test",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"test:{instrument_id}:{field}",
            confidence=0.99,
            valid_from=valid_from,
            available_at=available_at,
            revision=revision,
        )
        for field, value in values.items()
    )


def _observation(
    instrument_id: str,
    value: float,
    *,
    context=None,
    weight: float = 1.0,
    known_at: str = "2024-06-01T00:00:00Z",
    strategy: str | None = None,
    applicable: bool = True,
    effective_at: str = "2024-05-31T00:00:00Z",
    revision: int = 1,
) -> PeerObservation:
    return PeerObservation(
        instrument_id,
        context or _context(instrument_id),
        "quality",
        value,
        weight,
        effective_at,
        known_at,
        applicable,
        strategy,
        revision=revision,
    )


def _projection(target_id: str = "TARGET", decision_time: str = DECISION):
    target = replace(_context(target_id), decision_time=decision_time)
    observations = tuple(
        replace(
            _observation(f"P{i}", float(i)),
            context=replace(_context(f"P{i}"), decision_time=decision_time),
        )
        for i in range(1, 5)
    )
    return build_peer_projection(
        target,
        observations,
        metric="quality",
        target_value=2.5,
        effective_at=AS_OF,
        decision_time=decision_time,
        registry=AdapterRegistry(
            [AdapterDefinition("sector:technology", "tech-v1", frozenset({"quality"}))]
        ),
        applicable=True,
        bootstrap_seed=41,
    )


def _with_hash(projection):
    return replace(projection, result_hash=peer_result_hash(projection))


def test_point_in_time_filtering_sparse_fallback_and_share_class_deduplication() -> (
    None
):
    target = _context("TARGET")
    observations = (
        _observation("LEAF", 1.0),
        _observation("FUTURE", 2.0, known_at="2025-01-01T00:00:00Z"),
        _observation("CLASS-A", 3.0, strategy="same-company"),
        _observation("CLASS-B", 4.0, strategy="same-company"),
        _observation(
            "OTHER-SIZE", 5.0, context=_context("OTHER-SIZE", cap_bucket="small")
        ),
    )
    cohort = construct_cohort(
        target,
        observations,
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=3,
    )
    assert cohort.members == ("CLASS-A", "LEAF", "OTHER-SIZE")
    assert cohort.fallback_path[-1] == "industry+sector+country+currency"
    assert cohort.exclusions == {
        "CLASS-B": "economic_strategy_duplicate_of:CLASS-A",
        "FUTURE": "future_known",
    }
    assert cohort.support == 3


def test_robust_statistics_ties_mad_zero_weights_shrinkage_and_seed_replay() -> None:
    assert weighted_empirical_cdf([1.0, 2.0, 2.0, 3.0], [1, 1, 1, 1], 2.0) == 0.5
    assert effective_sample_size([1, 1, 2, 0, -1]) == pytest.approx(8 / 3)
    with pytest.raises(PeerCohortError):
        weighted_empirical_cdf([1.0], [0.0], 1.0)

    cohort = construct_cohort(
        _context("TARGET"),
        tuple(_observation(f"P{i}", 7.0) for i in range(4)),
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
    )
    first = calculate_peer_metric(
        "quality", 100.0, cohort, applicable=True, bootstrap_seed=9
    )
    second = calculate_peer_metric(
        "quality", 100.0, cohort, applicable=True, bootstrap_seed=9
    )
    assert first.mad == 0
    assert first.interval == second.interval
    assert first.percentile == 1.0
    assert first.shrunk_percentile == first.percentile


def test_metric_applicability_and_invalid_values_never_rank() -> None:
    cohort = construct_cohort(
        _context("TARGET"),
        (_observation("GOOD", 1), _observation("BAD-WEIGHT", 2, weight=0)),
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=1,
    )
    result = calculate_peer_metric("quality", 1, cohort, applicable=False)
    assert result.status == "N/A"
    assert result.percentile is None
    assert result.effective_sample_size == 0


def test_adapter_and_classification_versions_invalidate_hashes_and_low_confidence_falls_back() -> (
    None
):
    target = _context("TARGET")
    registry_v1 = AdapterRegistry(
        [AdapterDefinition("sector:technology", "1", frozenset())]
    )
    registry_v2 = AdapterRegistry(
        [AdapterDefinition("sector:technology", "2", frozenset())]
    )
    assert (
        registry_v1.select(target).lineage_hash
        != registry_v2.select(target).lineage_hash
    )

    changed = replace(target, score_invalidation_token="f" * 64)
    assert (
        registry_v1.select(target).lineage_hash
        != registry_v1.select(changed).lineage_hash
    )
    fallback = registry_v1.select(_context("LOW", confidence=0.5))
    assert fallback.adapter_id == "stock:broad"
    assert fallback.fallback is True
    assert fallback.execution_allowed is False


def test_revision_replay_uses_latest_row_known_at_each_cutoff() -> None:
    target = _context("TARGET")
    revisions = (
        _observation(
            "PEER",
            1,
            effective_at="2024-01-01T00:00:00Z",
            known_at="2024-01-02T00:00:00Z",
            revision=1,
        ),
        _observation(
            "PEER",
            9,
            effective_at="2024-01-01T00:00:00Z",
            known_at="2024-08-01T00:00:00Z",
            revision=2,
        ),
    )
    historical = construct_cohort(
        target,
        revisions,
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=1,
    )
    later_decision = "2024-09-01T00:00:00Z"
    later = construct_cohort(
        replace(target, decision_time=later_decision),
        tuple(
            replace(item, context=replace(item.context, decision_time=later_decision))
            for item in revisions
        ),
        metric="quality",
        effective_at=AS_OF,
        decision_time=later_decision,
        minimum_support=1,
    )
    assert [item.value for item in historical.observations] == [1]
    assert historical.exclusions["PEER"] == "future_known"
    assert [item.value for item in later.observations] == [9]
    assert later.exclusions["PEER@revision:1"] == "superseded_revision"


def test_classification_contexts_must_match_exact_aware_cutoffs() -> None:
    target = replace(_context("TARGET"), decision_time="2024-07-03T00:00:00Z")
    with pytest.raises(PeerCohortError, match="target classification"):
        construct_cohort(
            target, (), metric="quality", effective_at=AS_OF, decision_time=DECISION
        )

    equivalent = replace(
        _context("TARGET"),
        effective_at="2024-06-30T10:00:00+10:00",
        decision_time="2024-07-02T10:00:00+10:00",
    )
    cohort = construct_cohort(
        equivalent,
        (
            _observation(
                "FUTURE-CONTEXT",
                1,
                context=replace(
                    _context("FUTURE-CONTEXT"),
                    decision_time="2024-07-03T00:00:00Z",
                ),
            ),
            _observation("VALID", 2),
        ),
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=1,
    )
    assert cohort.members == ("VALID",)
    assert cohort.exclusions["FUTURE-CONTEXT"] == "classification_cutoff_mismatch"

    invalid = _observation(
        "WRONG",
        1,
        context=replace(_context("OTHER"), version_id="not-a-digest"),
    )
    cohort = construct_cohort(
        _context("TARGET"),
        (invalid,),
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=1,
    )
    assert cohort.exclusions["WRONG"] == "classification_identity_mismatch"


def test_store_boundary_resolves_exact_cutoffs_and_historical_revisions(
    tmp_path: Path,
) -> None:
    with ClassificationStore(tmp_path) as store:
        store.append_evidence((*_stored_evidence("TARGET"), *_stored_evidence("PEER")))
    supplied = _observation("PEER", 2, context=_context("UNTRUSTED"))
    kwargs = {
        "target_instrument_id": "TARGET",
        "observations": (supplied,),
        "metric": "quality",
        "target_value": 1.5,
        "effective_at": AS_OF,
        "decision_time": DECISION,
        "registry": AdapterRegistry(
            [AdapterDefinition("sector:technology", "tech-v1", frozenset({"quality"}))]
        ),
        "applicable": True,
        "minimum_support": 1,
    }
    before = build_point_in_time_peer_projection(tmp_path, **kwargs)
    assert before.cohort.members == ("PEER",)
    assert before.universe[0].context.instrument_id == "PEER"

    later = tuple(
        replace(
            item,
            value="financials" if item.field == "sector" else item.value,
            revision=2,
            valid_from="2025-01-01T00:00:00Z",
            available_at="2025-01-02T00:00:00Z",
        )
        for item in _stored_evidence("PEER")
    )
    with ClassificationStore(tmp_path) as store:
        store.append_evidence(later)
    replay = build_point_in_time_peer_projection(tmp_path, **kwargs)
    assert canonical_peer_result_payload(before) == canonical_peer_result_payload(
        replay
    )
    assert before.result_hash == replay.result_hash

    equivalent = build_point_in_time_peer_projection(
        tmp_path,
        **{
            **kwargs,
            "effective_at": "2024-06-30T10:00:00+10:00",
            "decision_time": "2024-07-02T10:00:00+10:00",
        },
    )
    assert equivalent.result_hash == before.result_hash


@pytest.mark.parametrize(
    ("valid_from", "available_at"),
    [
        ("2025-01-01T00:00:00Z", "2020-01-02T00:00:00Z"),
        ("2020-01-01T00:00:00Z", "2025-01-02T00:00:00Z"),
    ],
)
def test_store_boundary_future_target_fails_closed(
    tmp_path: Path, valid_from: str, available_at: str
) -> None:
    with ClassificationStore(tmp_path) as store:
        store.append_evidence(
            _stored_evidence("TARGET", valid_from=valid_from, available_at=available_at)
        )
    with pytest.raises(PeerCohortError, match="target classification"):
        build_point_in_time_peer_projection(
            tmp_path,
            target_instrument_id="TARGET",
            observations=(),
            metric="quality",
            target_value=1,
            effective_at=AS_OF,
            decision_time=DECISION,
            registry=AdapterRegistry(),
            applicable=True,
        )


def test_store_boundary_future_only_candidate_is_explicitly_excluded(
    tmp_path: Path,
) -> None:
    with ClassificationStore(tmp_path) as store:
        store.append_evidence(
            (
                *_stored_evidence("TARGET"),
                *_stored_evidence("FUTURE", available_at="2025-01-02T00:00:00Z"),
            )
        )
    projection = build_point_in_time_peer_projection(
        tmp_path,
        target_instrument_id="TARGET",
        observations=(_observation("FUTURE", 2),),
        metric="quality",
        target_value=1,
        effective_at=AS_OF,
        decision_time=DECISION,
        registry=AdapterRegistry(),
        applicable=True,
        minimum_support=1,
    )
    assert projection.cohort.members == ()
    assert projection.cohort.exclusions["FUTURE"] == "classification_cutoff_mismatch"


def test_level_local_dedupe_does_not_let_nonmember_claim_strategy_and_excludes_target() -> (
    None
):
    target = _context("TARGET")
    nonmatching = _observation(
        "A-NONMATCH",
        1,
        context=_context("A-NONMATCH", cap_bucket="small"),
        strategy="shared",
    )
    matching = _observation("B-MATCH", 2, strategy="shared")
    cohort = construct_cohort(
        target,
        (nonmatching, matching, _observation("TARGET", 99)),
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=1,
    )
    assert cohort.members == ("B-MATCH",)
    assert "A-NONMATCH" not in cohort.exclusions
    assert cohort.exclusions["TARGET"] == "target_instrument"

    broad = construct_cohort(
        target,
        (nonmatching, matching),
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=2,
    )
    assert broad.members == ("A-NONMATCH",)
    assert broad.exclusions["B-MATCH"] == "economic_strategy_duplicate_of:A-NONMATCH"


def test_adapter_applicability_changes_lineage_blocks_metric_and_rejects_non_stock() -> (
    None
):
    target = _context("TARGET")
    quality = AdapterRegistry(
        [AdapterDefinition("sector:technology", "1", frozenset({"quality"}))]
    )
    valuation = AdapterRegistry(
        [AdapterDefinition("sector:technology", "1", frozenset({"valuation"}))]
    )
    assert quality.select(target).lineage_hash != valuation.select(target).lineage_hash
    projection = build_peer_projection(
        target,
        (_observation("PEER", 1),),
        metric="quality",
        target_value=1,
        effective_at=AS_OF,
        decision_time=DECISION,
        registry=valuation,
        applicable=True,
        minimum_support=1,
    )
    assert projection.metric.status == "N/A"
    assert projection.metric.percentile is None

    unsupported = replace(target, instrument_type="etf")
    with pytest.raises(PeerCohortError, match="classified stocks only"):
        quality.select(unsupported)


def test_shrinkage_uses_actual_next_broader_parent() -> None:
    target = _context("TARGET")
    leaf = (_observation("L1", 4), _observation("L2", 6))
    low_parent = tuple(
        _observation(
            f"LOW{i}",
            0,
            context=replace(_context(f"LOW{i}"), business_model_tags=("different",)),
        )
        for i in range(2)
    )
    high_parent = tuple(
        _observation(
            f"HIGH{i}",
            100,
            context=replace(_context(f"HIGH{i}"), business_model_tags=("different",)),
        )
        for i in range(2)
    )
    low_cohort = construct_cohort(
        target,
        (*leaf, *low_parent),
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=2,
    )
    high_cohort = construct_cohort(
        target,
        (*leaf, *high_parent),
        metric="quality",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=2,
    )
    low = calculate_peer_metric("quality", 5, low_cohort, applicable=True)
    high = calculate_peer_metric("quality", 5, high_cohort, applicable=True)
    assert low.percentile == high.percentile == 0.5
    assert low.shrunk_percentile > high.shrunk_percentile


def test_immutable_store_restart_duplicate_conflict_corruption_and_read_only_unavailable(
    tmp_path: Path,
) -> None:
    projection = _projection()
    missing_root = tmp_path / "missing"
    assert (
        load_peer_cohort_projection("TARGET", storage_root=missing_root)["status"]
        == "unavailable"
    )
    assert not missing_root.exists()

    with PeerCohortStore(tmp_path) as store:
        assert store.append(projection) == projection.result_hash
        assert store.append(projection) == projection.result_hash
    with PeerCohortStore(tmp_path) as restarted:
        replay = restarted.get(projection.result_hash)
        assert replay["result_hash"] == projection.result_hash
        conflict = _with_hash(
            replace(projection, metric=replace(projection.metric, support=999))
        )
        with pytest.raises(PeerCohortStoreError, match="not reproducible"):
            restarted.append(conflict)

    path = storage_layout(tmp_path).transactional_path
    connection = sqlite3.connect(path)
    payload = json.loads(
        connection.execute(
            "SELECT payload_json FROM transactional_records WHERE entity_type='peer_cohort_result_v1'"
        ).fetchone()[0]
    )
    payload["checksum"] = "0" * 64
    connection.execute(
        "UPDATE transactional_records SET payload_json=? WHERE entity_type='peer_cohort_result_v1'",
        (json.dumps(payload),),
    )
    connection.commit()
    connection.close()
    assert (
        read_peer_cohort_projection(tmp_path, "TARGET")["reason_code"]
        == "peer_cohort_evidence_invalid"
    )


def test_forged_result_hash_is_rejected_before_storage_creation(tmp_path: Path) -> None:
    forged = replace(_projection(), result_hash="f" * 64)
    root = tmp_path / "forged"
    with PeerCohortStore(root) as store:
        with pytest.raises(PeerCohortStoreError, match="canonical"):
            store.append(forged)
    assert not root.exists()

    projection = _projection()
    assert projection.result_hash == peer_result_hash(projection)


def test_rehashed_semantic_tamper_still_fails_verified_replay(tmp_path: Path) -> None:
    projection = _projection()
    with PeerCohortStore(tmp_path) as store:
        store.append(projection)
    path = storage_layout(tmp_path).transactional_path
    connection = sqlite3.connect(path)
    envelope = json.loads(
        connection.execute(
            "SELECT payload_json FROM transactional_records "
            "WHERE entity_type='peer_cohort_result_v1'"
        ).fetchone()[0]
    )
    envelope["payload"]["metric"]["median"] = 999.0
    envelope["payload"]["result_hash"] = peer_result_hash(envelope["payload"])
    envelope["checksum"] = hashlib.sha256(
        json.dumps(
            envelope["payload"],
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    connection.execute(
        "UPDATE transactional_records SET payload_json=? "
        "WHERE entity_type='peer_cohort_result_v1'",
        (json.dumps(envelope),),
    )
    connection.commit()
    connection.close()
    assert (
        read_peer_cohort_projection(tmp_path, "TARGET")["reason_code"]
        == "peer_cohort_evidence_invalid"
    )


def test_concurrent_exact_writers_are_idempotent(tmp_path: Path) -> None:
    projection = _projection()

    def append() -> str:
        with PeerCohortStore(tmp_path) as store:
            return store.append(projection)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(lambda _index: append(), range(8)))) == 1


def test_store_queries_use_aware_instants_and_exclude_future_rows(
    tmp_path: Path,
) -> None:
    projection = _projection()
    same_instant = _with_hash(
        replace(
            projection,
            decision_time="2024-07-02T02:00:00+02:00",
        )
    )
    future = _projection(decision_time="2024-07-03T00:00:00Z")
    with PeerCohortStore(tmp_path) as store:
        store.append(same_instant)
        store.append(future)
        replay = store.projection("TARGET", decision_time="2024-07-02T01:00:00+01:00")
    assert replay["result_hash"] == same_instant.result_hash

    path = storage_layout(tmp_path).transactional_path
    connection = sqlite3.connect(path)
    envelope = json.loads(
        connection.execute(
            "SELECT payload_json FROM transactional_records "
            "WHERE entity_type='peer_cohort_result_v1'",
        ).fetchone()[0]
    )
    envelope["payload"]["decision_time"] = "malformed"
    envelope["checksum"] = hashlib.sha256(
        json.dumps(
            envelope["payload"],
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    connection.execute(
        "UPDATE transactional_records SET payload_json=? "
        "WHERE entity_type='peer_cohort_result_v1'",
        (json.dumps(envelope),),
    )
    connection.commit()
    connection.close()
    assert (
        read_peer_cohort_projection(tmp_path, "TARGET")["reason_code"]
        == "peer_cohort_evidence_invalid"
    )


def test_concurrent_distinct_writers_do_not_lose_records(tmp_path: Path) -> None:
    projections = tuple(_projection(target_id=f"TARGET-{index}") for index in range(8))

    def append(projection) -> str:
        with PeerCohortStore(tmp_path) as store:
            return store.append(projection)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(append, projections)) == {
            projection.result_hash for projection in projections
        }
    with PeerCohortStore(tmp_path) as store:
        assert all(
            store.projection(projection.instrument_id)["result_hash"]
            == projection.result_hash
            for projection in projections
        )


def test_facade_and_selector_replay_stored_peer_evidence_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    from etf_cockpit.app.selectors import instrument_detail as selector

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    projection = _projection(target_id=instrument_id)
    with PeerCohortStore(tmp_path) as store:
        store.append(projection)
    monkeypatch.setattr(
        selector,
        "load_peer_cohort_projection",
        lambda selected, **kwargs: load_peer_cohort_projection(
            selected, storage_root=tmp_path, **kwargs
        ),
    )
    model = selector.build_instrument_detail(snapshot, instrument_id)
    assert model.sections["peer_cohort"]["result_hash"] == projection.result_hash
    assert model.sections["peer_cohort"]["execution_allowed"] is False

    missing = tmp_path / "absent"
    assert (
        load_peer_cohort_projection(instrument_id, storage_root=missing)["status"]
        == "unavailable"
    )
    assert not missing.exists()


def test_ui_contract_declares_peer_cohort_surface() -> None:
    text = Path("configs/ui_acceptance.yaml").read_text(encoding="utf-8")
    assert "instrument-detail.peer-cohort" in text
    source = Path("src/etf_cockpit/app/pages/instrument_detail.py").read_text(
        encoding="utf-8"
    )
    assert '"Peer cohort and adapter lineage"' in source
