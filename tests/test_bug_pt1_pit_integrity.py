"""PT1 / #957: point-in-time and source-conflict integrity regression tests."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.analysis.look_through import _available_or_known
from etf_cockpit.data.bitemporal import BitemporalError, BitemporalStore
from etf_cockpit.data.contracts import CONTEXT_ONLY_AUTHORITIES, PRIMARY_SOURCE_AUTHORITIES, SourceAuthority
from etf_cockpit.data.evidence_ledger import EvidenceSource, ledger_entry_for_component
from etf_cockpit.data.fund_adapters import resolve_fund_evidence
from etf_cockpit.data.source_conflicts import MetricClaim, MetricPolicy, MetricResolutionError, resolve_conflicts
from etf_cockpit.features.feature_store import FeatureDefinition, LocalFeatureStore

CHECKSUM = "b" * 64
T0 = "2026-01-02T00:00:00Z"


def _observe(store: BitemporalStore, **overrides):
    values = dict(
        dataset_id="fundamentals",
        entity_id="ETF-1",
        stable_id="metric:nav",
        run_id="run-1",
        value={"v": 1},
        source_id="source:official",
        source_checksum=CHECKSUM,
        revision=1,
        valid_from="2025-01-01T00:00:00Z",
        available_at=T0,
        observed_at=T0,
        published_at=T0,
    )
    values.update(overrides)
    return store.record_observation(**values)


def _claim(authority: SourceAuthority, value: object, source_id: str, **overrides) -> MetricClaim:
    values = dict(
        unit="USD",
        period="FY2025",
        currency="USD",
        as_of="2026-01-31",
        available_at="2026-02-01T00:00:00Z",
        freshness_status="fresh",
    )
    values.update(overrides)
    return MetricClaim("X", "revenue", value, authority.value, authority, source_id, **values)


# A013-N001 (REJECTED on this base: conflict + official wins already held; kept as guard)
@pytest.mark.parametrize("decision_time", (None, "2026-03-01T00:00:00Z"))
def test_official_vs_vendor_same_as_of_is_a_conflict_and_official_wins(decision_time) -> None:
    result = resolve_conflicts(
        [_claim(SourceAuthority.VENDOR, 100, "v1", revision=9), _claim(SourceAuthority.OFFICIAL, 120, "o1")],
        decision_time=decision_time,
    )
    assert result.selected["revenue"].value == 120
    assert result.selected["revenue"].source_id == "o1"
    assert len(result.conflicts) == 1
    assert result.conflicts[0].source_ids == ("o1", "v1")
    assert result.conflicts[0].requires_manual_review is True


def test_official_vs_vendor_with_different_as_of_never_pools_silently() -> None:
    result = resolve_conflicts(
        [
            _claim(SourceAuthority.VENDOR, 100, "v1", as_of="2026-02-15", available_at="2026-02-16T00:00:00Z"),
            _claim(SourceAuthority.OFFICIAL, 120, "o1"),
        ],
        decision_time="2026-03-01T00:00:00Z",
    )
    assert result.conflicts and result.conflicts[0].state == "block"
    assert result.state == "block"


# A013-N003 / A013-N004 / C02-C2-N004 / A013-N002
def test_published_or_observed_after_available_is_rejected(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        with pytest.raises(BitemporalError, match="published_at"):
            _observe(store, published_at="2026-02-01T00:00:00Z")
        with pytest.raises(BitemporalError, match="observed_at"):
            _observe(store, observed_at="2026-02-01T00:00:00Z")
        assert store.observations("fundamentals") == ()


def test_backdated_retraction_is_honoured_and_value_never_resurfaces(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        target = _observe(store, available_at="2026-01-10T00:00:00Z", published_at="2026-01-10T00:00:00Z", observed_at="2026-01-10T00:00:00Z")
        store.record_retraction(target.observation_id, available_at="2026-01-05T00:00:00Z", run_id="run-r", reason="bad print")
        assert store.as_of("fundamentals", "2026-02-01T00:00:00Z").empty
        assert store.as_of("fundamentals", "2026-01-07T00:00:00Z").empty


def test_later_lower_revision_does_not_win_and_guard_is_scoped_to_entity_and_source(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        _observe(store, revision=2, value={"v": "rev2"}, available_at="2026-01-10T00:00:00Z", published_at="2026-01-10T00:00:00Z", observed_at="2026-01-10T00:00:00Z")
        with pytest.raises(BitemporalError):
            _observe(store, revision=1, value={"v": "rev1"}, available_at="2026-01-20T00:00:00Z", published_at="2026-01-20T00:00:00Z", observed_at="2026-01-20T00:00:00Z")
        # Another source / entity at revision 1 is not blocked by this source's revision 2.
        _observe(store, source_id="source:vendor", revision=1, value={"v": "other-source"})
        assert len(store.observations("fundamentals")) == 2


def test_as_of_ignores_lower_revision_written_with_guard_disabled(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        _observe(store, revision=2, value={"v": "rev2"}, available_at="2026-01-10T00:00:00Z", published_at="2026-01-10T00:00:00Z", observed_at="2026-01-10T00:00:00Z")
        _observe(
            store,
            revision=1,
            value={"v": "rev1"},
            available_at="2026-01-20T00:00:00Z",
            published_at="2026-01-20T00:00:00Z",
            observed_at="2026-01-20T00:00:00Z",
            require_revision_advance=False,
        )
        frame = store.as_of("fundamentals", "2026-02-01T00:00:00Z")
        assert frame["value"].tolist() == [{"v": "rev2"}]


# A113-N001 / A113-N002
def test_observation_identity_includes_entity_id(tmp_path: Path) -> None:
    ids = []
    for entity in ("ETF-1", "ETF-2"):
        with BitemporalStore(tmp_path / entity) as store:
            ids.append(_observe(store, entity_id=entity, stable_id="metric:shared").observation_id)
    assert ids[0] != ids[1]


@pytest.mark.xfail(
    strict=True,
    reason="A113-N001: the SQLite UNIQUE(dataset_id, stable_id, source_id, revision) constraint omits entity_id; "
    "fixing it needs a table-rebuild migration (NEEDS_OPUS_DECISION). Strict xfail flips to a failure once fixed.",
)
def test_two_instruments_sharing_a_metric_id_both_persist(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        _observe(store, entity_id="ETF-1", stable_id="metric:shared")
        _observe(store, entity_id="ETF-2", stable_id="metric:shared")
        assert {row.entity_id for row in store.observations("fundamentals")} == {"ETF-1", "ETF-2"}


# A121-N001 / A121-N002 / A013-N005 / A07-C2-N003
@pytest.mark.parametrize("bad", (float("nan"), float("inf"), float("-inf")))
def test_non_finite_metric_is_never_selected(bad: float) -> None:
    result = resolve_conflicts([_claim(SourceAuthority.OFFICIAL, bad, "o1"), _claim(SourceAuthority.VENDOR, 5, "v1")])
    assert result.selected["revenue"].value == 5
    alone = resolve_conflicts([_claim(SourceAuthority.OFFICIAL, bad, "o1")])
    assert alone.selected == {}
    assert alone.state == "block"


@pytest.mark.parametrize("bad", (float("inf"), float("nan"), -1.0))
def test_non_finite_tolerance_is_rejected(bad: float) -> None:
    with pytest.raises(MetricResolutionError):
        MetricPolicy("p", 1, absolute_tolerance=bad)
    with pytest.raises(MetricResolutionError):
        MetricPolicy("p", 1, relative_tolerance=bad)
    with pytest.raises(MetricResolutionError):
        MetricPolicy("p", 1, field_tolerances={"revenue": (bad, 0.0)})


@pytest.mark.parametrize("bad", (float("nan"), float("inf")))
def test_non_finite_value_is_never_stored(tmp_path: Path, bad: float) -> None:
    with BitemporalStore(tmp_path) as store:
        with pytest.raises(BitemporalError, match="NaN or Infinity"):
            _observe(store, value={"v": bad})
        with pytest.raises(BitemporalError, match="NaN or Infinity"):
            _observe(store, value=[1.0, bad])


def test_non_finite_fund_evidence_does_not_count_as_resolved() -> None:
    rows = [
        {"instrument_id": "F", "metric": "nav", "as_of": "2026-01-01", "value": "NaN", "authority": "official", "source": "a", "source_id": "a1"},
        {"instrument_id": "F", "metric": "nav", "as_of": "2026-01-01", "value": "Infinity", "authority": "issuer", "source": "b", "source_id": "b1"},
    ]
    resolved, conflicts = resolve_fund_evidence(rows)
    assert resolved == () and conflicts == ()


# A07-C2-N002
def test_fund_evidence_equality_uses_numeric_value_unit_and_currency() -> None:
    base = {"instrument_id": "F", "metric": "nav", "as_of": "2026-01-01", "authority": "official"}
    same = resolve_fund_evidence(
        [{**base, "value": "100.0", "currency": "EUR", "source": "a"}, {**base, "value": "100.00", "currency": "EUR", "source": "b"}]
    )
    assert same[0][0]["status"] == "resolved"
    different_currency = resolve_fund_evidence(
        [{**base, "value": "100", "currency": "EUR", "source": "a"}, {**base, "value": "100", "currency": "USD", "source": "b"}]
    )
    assert different_currency[0][0]["status"] == "conflict_at_preferred_authority"
    assert different_currency[1]


# A03-C2-N002 (REJECTED: identical duplicate revisions never conflict)
def test_duplicate_vendor_revisions_with_equal_values_are_not_a_conflict() -> None:
    result = resolve_conflicts(
        [
            _claim(SourceAuthority.VENDOR, 100, "fmp:v1", revision=1),
            _claim(SourceAuthority.VENDOR, 100, "fmp:v2", revision=2),
        ],
        decision_time="2026-03-01T00:00:00Z",
    )
    assert result.conflicts == ()


# C102-N002
def test_bitemporal_as_of_honours_effective_validity(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        _observe(store, stable_id="expired", valid_from="2025-01-01T00:00:00Z", valid_to="2025-06-01T00:00:00Z")
        _observe(store, stable_id="future", valid_from="2027-01-01T00:00:00Z")
        _observe(store, stable_id="current", valid_from="2025-01-01T00:00:00Z", valid_to="2027-01-01T00:00:00Z")
        frame = store.as_of("fundamentals", "2026-03-01T00:00:00Z")
        assert frame["stable_id"].tolist() == ["current"]


# A108-N004 / C102-N001 / C102-N003
def test_daily_candle_cutoff_uses_one_convention_for_naive_and_tz_aware_midnight(tmp_path: Path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))
    results = {}
    for label, stamp in {"naive": "2026-01-05", "tokyo": "2026-01-05T00:00:00+09:00", "ny": "2026-01-05T00:00:00-05:00"}.items():
        features = pd.DataFrame({"etf_id": ["A"], "date": [stamp], "signal": [1.0]})
        results[label] = [
            store.materialise(features, [decision], feature_ids=["signal"]).loc[0, "missing_signal"]
            for decision in ("2026-01-04", "2026-01-05")
        ]
    assert results["naive"] == results["tokyo"] == results["ny"] == [True, False]


def test_intraday_decision_keys_and_feature_time_keep_their_own_dimensions(tmp_path: Path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))
    features = pd.DataFrame(
        {"etf_id": ["A"], "date": ["2026-01-01"], "available_at": ["2026-01-02T08:00:00Z"], "signal": [1.0]}
    )
    matrix = store.materialise(features, ["2026-01-02T10:00:00Z", "2026-01-02T16:00:00Z", "2026-01-03"], feature_ids=["signal"])
    assert matrix["decision_time"].tolist() == ["2026-01-02T10:00:00", "2026-01-02T16:00:00", "2026-01-03"]
    assert matrix["feature_time"].unique().tolist() == ["2026-01-01"]
    assert matrix["source_vintage_hash"].nunique() == 3


# A112
def test_future_dated_or_unknown_freshness_evidence_is_not_fresh() -> None:
    future = EvidenceSource("prices", "p1", SourceAuthority.OFFICIAL, "2026-12-31", "fresh")
    entry = ledger_entry_for_component("X", "momentum", 7.0, future, decision_date="2026-06-01")
    assert entry.score_eligible is False and "after the decision date" in entry.reason
    unknown = EvidenceSource("prices", "p1", SourceAuthority.OFFICIAL, "2026-01-01", "unknown")
    assert ledger_entry_for_component("X", "momentum", 7.0, unknown, decision_date="2026-06-01").score_eligible is False
    ok = EvidenceSource("prices", "p1", SourceAuthority.OFFICIAL, "2026-01-01", "fresh")
    assert ledger_entry_for_component("X", "momentum", 7.0, ok, decision_date="2026-06-01").score_eligible is True


def test_context_only_authority_is_never_canonical() -> None:
    for authority in CONTEXT_ONLY_AUTHORITIES:
        source = EvidenceSource("prices", "p1", authority, "2026-01-01", "fresh")
        assert ledger_entry_for_component("X", "momentum", 7.0, source, decision_date="2026-06-01").score_eligible is False
    result = resolve_conflicts(
        [_claim(SourceAuthority.COMMUNITY, 1, "c1"), _claim(SourceAuthority.MANUAL, 2, "m1")],
        decision_time="2026-03-01T00:00:00Z",
    )
    assert result.selected == {}
    assert result.state == "block"


def test_future_as_of_claim_is_not_current_and_unknown_freshness_is_opt_in_blocked() -> None:
    future = _claim(SourceAuthority.OFFICIAL, 1, "o1", as_of="2026-05-01", available_at="2026-01-01T00:00:00Z")
    result = resolve_conflicts([future], decision_time="2026-03-01T00:00:00Z")
    assert result.selected == {} and future.source_id in {item.source_id for item in result.excluded_claims}
    unknown = _claim(SourceAuthority.OFFICIAL, 1, "o1", freshness_status="unknown")
    strict = resolve_conflicts([unknown], policy=MetricPolicy("strict", 1, require_known_freshness=True))
    assert strict.selected == {}


def test_fingerprint_changes_when_only_the_vintage_as_of_changes() -> None:
    first = resolve_conflicts([_claim(SourceAuthority.OFFICIAL, 1, "o1", as_of="2026-01-31")], decision_time="2026-03-01T00:00:00Z")
    second = resolve_conflicts([_claim(SourceAuthority.OFFICIAL, 1, "o1", as_of="2026-02-15")], decision_time="2026-03-01T00:00:00Z")
    assert first.decision_id != second.decision_id
    assert first.invalidation_token != second.invalidation_token


# C02-C2-N001 / C02-C2-N003
@pytest.mark.parametrize("empty", ("", "  ", None, float("nan"), pd.NaT))
def test_known_at_is_used_when_available_at_is_present_but_empty(empty) -> None:
    assert _available_or_known({"available_at": empty, "known_at": "2026-01-01T00:00:00Z"}) == "2026-01-01T00:00:00Z"
    assert _available_or_known({"available_at": "2026-02-01T00:00:00Z", "known_at": "2026-01-01T00:00:00Z"}) == "2026-02-01T00:00:00Z"


def test_naive_datetime_claim_timestamp_is_not_interpreted_as_utc() -> None:
    from datetime import datetime

    with pytest.raises(ValueError):
        resolve_conflicts([_claim(SourceAuthority.OFFICIAL, 1, "o1", available_at=datetime(2026, 1, 1, 12, 0))])


# B021-N001
def test_one_canonical_authority_whitelist_is_shared_by_all_selectors() -> None:
    assert PRIMARY_SOURCE_AUTHORITIES == {SourceAuthority.OFFICIAL, SourceAuthority.ISSUER}
    assert not PRIMARY_SOURCE_AUTHORITIES & CONTEXT_ONLY_AUTHORITIES
    assert PRIMARY_SOURCE_AUTHORITIES | CONTEXT_ONLY_AUTHORITIES | {SourceAuthority.VENDOR} == set(SourceAuthority)
    from etf_cockpit.analysis import cyclical_sector_adapters, financial_sector_adapters, innovation_sector_adapters

    for module in (cyclical_sector_adapters, financial_sector_adapters):
        assert module.PRIMARY_SOURCE_AUTHORITIES is PRIMARY_SOURCE_AUTHORITIES
    assert innovation_sector_adapters._ALLOWED_AUTHORITIES == PRIMARY_SOURCE_AUTHORITIES | {SourceAuthority.MANUAL}
    assert math.isfinite(1.0)
