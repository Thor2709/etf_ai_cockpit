from __future__ import annotations

from dataclasses import replace
from copy import deepcopy

import pytest

from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkDefinition,
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
    CashProxyDefinition,
    PeerSetDefinition,
    ReferencePortfolioDefinition,
    VwceAnchorEvidence,
    VwceListingObservation,
    VWCE_CANONICAL_SHARE_CLASS,
    declare_reference_portfolios,
    project_profile_relative_analysis,
    resolve_vwce_anchor,
)
import etf_cockpit.portfolio.benchmark_reference_contract as contract


HASH_A = "a" * 64
HASH_B = "b" * 64
INSTRUMENT = {"asset_class": "equity", "exposure": "broad", "country_region": "global", "currency": "AUD"}


def _benchmark(**updates: object) -> BenchmarkDefinition:
    value: dict[str, object] = {
        "benchmark_id": "benchmark:global-equity",
        "version": "1.0.0",
        "hierarchy": "asset",
        "selector": {"asset_class": "equity"},
        "currency": "AUD",
        "minimum_horizon_years": 0.1,
        "maximum_horizon_years": 10.0,
        "effective_at": "2024-01-01T00:00:00Z",
        "known_at": "2024-01-02T00:00:00Z",
        "start_date": "2020-01-01",
        "end_date": "2030-01-01",
        "methodology": "fixture benchmark with adjusted total-return constituents",
        "constituents": ("BBB", "AAA"),
        "source_hashes": (HASH_A,),
    }
    value.update(updates)
    return BenchmarkDefinition(**value)  # type: ignore[arg-type]


def _cash(**updates: object) -> CashProxyDefinition:
    value: dict[str, object] = {
        "proxy_id": "cash:AUD-spot",
        "version": "1.0.0",
        "selector": {"asset_class": "equity"},
        "currency": "AUD",
        "minimum_horizon_years": 0.1,
        "maximum_horizon_years": 10.0,
        "effective_at": "2024-01-01T00:00:00Z",
        "known_at": "2024-01-02T00:00:00Z",
        "start_date": "2020-01-01",
        "end_date": "2030-01-01",
        "methodology": "fixture currency-matched spot cash evidence",
        "source_hashes": (HASH_B,),
    }
    value.update(updates)
    return CashProxyDefinition(**value)  # type: ignore[arg-type]


def _peer(**updates: object) -> PeerSetDefinition:
    value: dict[str, object] = {
        "peer_set_id": "peers:global-equity",
        "version": "1.0.0",
        "hierarchy": "asset",
        "selector": {"asset_class": "equity"},
        "member_instrument_ids": ("BBB", "AAA"),
        "effective_at": "2024-01-01T00:00:00Z",
        "known_at": "2024-01-02T00:00:00Z",
        "methodology": "fixture same-definition peer set",
        "source_hashes": (HASH_A,),
    }
    value.update(updates)
    return PeerSetDefinition(**value)  # type: ignore[arg-type]


def _registry(*, benchmark: BenchmarkDefinition | None = None, cash: CashProxyDefinition | None = None) -> CanonicalBenchmarkRegistry:
    references = declare_reference_portfolios(
        ("BBB", "AAA"),
        current_weights={"AAA": 0.7, "BBB": 0.3},
        effective_at="2024-01-01T00:00:00Z",
        known_at="2024-01-02T00:00:00Z",
        currency="AUD",
        minimum_horizon_years=0.1,
        maximum_horizon_years=10.0,
        start_date="2020-01-01",
        end_date="2030-01-01",
    )
    return CanonicalBenchmarkRegistry(
        benchmarks=(benchmark or _benchmark(),),
        cash_proxies=(cash or _cash(),),
        peer_sets=(_peer(),),
        reference_portfolios=references,
    )


def test_mapping_is_shared_by_attribution_and_validation_and_exposes_read_only_ui_projection() -> None:
    registry = _registry()
    arguments = {
        "analysis_id": "analysis-1",
        "instrument_id": "ETF-1",
        "instrument": INSTRUMENT,
        "currency": "AUD",
        "horizon_years": 1.0,
        "start_date": "2024-02-01",
        "end_date": "2025-02-01",
        "decision_time": "2024-02-02T00:00:00Z",
        "reference_portfolio_ids": ("reference:equal_weight", "reference:maximum_diversification", "reference:no_trade"),
    }
    attribution = registry.resolve_analysis(purpose="attribution", **arguments)
    validation = registry.resolve_analysis(purpose="validation", **arguments)

    assert attribution.benchmark == validation.benchmark
    assert attribution.cash == validation.cash
    assert attribution.declaration.benchmark_id == "benchmark:global-equity"
    assert attribution.declaration.cash_proxy_id == "cash:AUD-spot"
    assert {item.method for item in attribution.references} == {"equal_weight", "maximum_diversification", "no_trade"}
    projection = registry.ui_projection(attribution)
    assert projection["benchmark"]["display"] == "benchmark:global-equity"
    assert projection["cash"]["display"] == "cash:AUD-spot"
    assert projection["execution_allowed"] is False


def test_specificity_is_deterministic_and_ties_are_ambiguous() -> None:
    broad = _benchmark()
    specific = _benchmark(
        benchmark_id="benchmark:global-equity-sector",
        hierarchy="sector",
        selector={"asset_class": "equity", "sector": "technology"},
    )
    registry = _registry(benchmark=broad)
    registry = CanonicalBenchmarkRegistry(
        benchmarks=(broad, specific), cash_proxies=registry.cash_proxies,
        peer_sets=registry.peer_sets, reference_portfolios=registry.reference_portfolios,
    )
    selected, _, _ = registry.map_instrument(
        {**INSTRUMENT, "sector": "technology"}, currency="AUD", horizon_years=1.0,
        start_date="2024-02-01", end_date="2025-02-01", decision_time="2024-02-02T00:00:00Z",
    )
    assert selected.selected_id == "benchmark:global-equity-sector"

    ambiguous = _benchmark(benchmark_id="benchmark:other-global-equity")
    registry = _registry(benchmark=ambiguous)
    registry = CanonicalBenchmarkRegistry(
        benchmarks=(ambiguous, _benchmark()), cash_proxies=registry.cash_proxies,
        peer_sets=registry.peer_sets, reference_portfolios=registry.reference_portfolios,
    )
    selection, _, _ = registry.map_instrument(
        INSTRUMENT, currency="AUD", horizon_years=1.0,
        start_date="2024-02-01", end_date="2025-02-01", decision_time="2024-02-02T00:00:00Z",
    )
    assert selection.status == "ambiguous"
    assert selection.reason == "ambiguous_mapping"


@pytest.mark.parametrize(
    ("currency", "horizon_years", "expected"),
    (("EUR", 1.0, "currency_mismatch_no_fx_substitution"), ("AUD", 20.0, "horizon_mismatch")),
)
def test_alignment_never_hides_fx_or_horizon_substitution(currency: str, horizon_years: float, expected: str) -> None:
    registry = _registry()
    benchmark, cash, _ = registry.map_instrument(
        INSTRUMENT, currency=currency, horizon_years=horizon_years,
        start_date="2024-02-01", end_date="2025-02-01", decision_time="2024-02-02T00:00:00Z",
    )
    assert benchmark.status == cash.status == "unavailable"
    assert benchmark.reason == cash.reason == expected
    assert benchmark.display_name == cash.display_name == "N/A"


def test_pit_version_replay_rejects_future_unknown_and_stale_evidence() -> None:
    old = _benchmark(version="1.0.0", effective_at="2023-01-01T00:00:00Z", known_at="2023-01-02T00:00:00Z")
    new = _benchmark(version="2.0.0", effective_at="2025-01-01T00:00:00Z", known_at="2025-01-02T00:00:00Z")
    registry = CanonicalBenchmarkRegistry(benchmarks=(new, old), cash_proxies=(_cash(),), peer_sets=(_peer(),), reference_portfolios=_registry().reference_portfolios)
    selected, _, _ = registry.map_instrument(INSTRUMENT, currency="AUD", horizon_years=1.0, start_date="2024-02-01", end_date="2025-02-01", decision_time="2024-02-02T00:00:00Z")
    assert selected.version == "1.0.0"
    future, _, _ = registry.map_instrument(INSTRUMENT, currency="AUD", horizon_years=1.0, start_date="2025-02-01", end_date="2026-02-01", decision_time="2025-01-01T00:00:00Z", benchmark_version="2.0.0")
    assert future.status == "unavailable"
    replay, _, _ = registry.map_instrument(INSTRUMENT, currency="AUD", horizon_years=1.0, start_date="2025-02-01", end_date="2026-02-01", decision_time="2025-02-02T00:00:00Z", benchmark_version="1.0.0")
    assert replay.status == "available"
    assert replay.version == "1.0.0"
    stale, _, _ = _registry(benchmark=replace(old, status="stale")).map_instrument(INSTRUMENT, currency="AUD", horizon_years=1.0, start_date="2024-02-01", end_date="2025-02-01", decision_time="2024-02-02T00:00:00Z")
    assert stale.reason == "benchmark_stale_or_unavailable"


def test_authoritative_stale_version_never_falls_back_to_older_available_definition() -> None:
    old_benchmark = _benchmark(version="1.0.0", effective_at="2023-01-01T00:00:00Z", known_at="2023-01-02T00:00:00Z")
    stale_benchmark = _benchmark(version="2.0.0", effective_at="2024-01-01T00:00:00Z", known_at="2024-01-02T00:00:00Z", status="stale")
    old_cash = _cash(version="1.0.0", effective_at="2023-01-01T00:00:00Z", known_at="2023-01-02T00:00:00Z")
    stale_cash = _cash(version="2.0.0", effective_at="2024-01-01T00:00:00Z", known_at="2024-01-02T00:00:00Z", status="stale")
    old_peer = _peer(version="1.0.0", effective_at="2023-01-01T00:00:00Z", known_at="2023-01-02T00:00:00Z")
    stale_peer = _peer(version="2.0.0", effective_at="2024-01-01T00:00:00Z", known_at="2024-01-02T00:00:00Z", status="stale")
    registry = CanonicalBenchmarkRegistry(
        benchmarks=(old_benchmark, stale_benchmark),
        cash_proxies=(old_cash, stale_cash),
        peer_sets=(old_peer, stale_peer),
    )
    benchmark, cash, peer = registry.map_instrument(
        INSTRUMENT, currency="AUD", horizon_years=1.0,
        start_date="2024-02-01", end_date="2025-02-01",
        decision_time="2024-02-02T00:00:00Z",
    )
    assert benchmark.reason == "benchmark_stale_or_unavailable"
    assert cash.reason == "cash_stale_or_unavailable"
    assert peer.reason == "peer_set_stale_or_unavailable"
    assert benchmark.status == cash.status == peer.status == "unavailable"


@pytest.mark.parametrize("value", [1, "yes", None])
def test_opportunity_anchor_requires_a_strict_boolean(value: object) -> None:
    with pytest.raises(BenchmarkReferenceError, match="opportunity_anchor"):
        _benchmark(opportunity_anchor=value)


def test_reference_portfolio_requires_effective_and_known_cutoffs() -> None:
    future = ReferencePortfolioDefinition(
        "reference:future",
        "1.0.0",
        "equal_weight",
        ("AAA", "BBB"),
        "future-effective fixture",
        "2025-01-02T00:00:00Z",
        "2025-01-03T00:00:00Z",
        currency="AUD",
        minimum_horizon_years=0.1,
        maximum_horizon_years=10.0,
        start_date="2020-01-01",
        end_date="2030-01-01",
    )
    registry = CanonicalBenchmarkRegistry(
        benchmarks=(_benchmark(),),
        cash_proxies=(_cash(),),
        peer_sets=(_peer(),),
        reference_portfolios=(*_registry().reference_portfolios, future),
    )
    resolution = registry.resolve_analysis(
        analysis_id="reference-pit",
        purpose="validation",
        instrument_id="ETF-1",
        instrument=INSTRUMENT,
        currency="AUD",
        horizon_years=1.0,
        start_date="2024-02-01",
        end_date="2025-02-01",
        decision_time="2025-01-01T00:00:00Z",
        reference_portfolio_ids=("reference:future",),
    )
    assert resolution.references == ()
    assert resolution.blockers == ("reference:unavailable:reference:future",)


def test_registry_hash_is_order_independent_and_tamper_evident() -> None:
    first = _registry()
    second = CanonicalBenchmarkRegistry(
        benchmarks=tuple(reversed(first.benchmarks)), cash_proxies=tuple(reversed(first.cash_proxies)),
        peer_sets=tuple(reversed(first.peer_sets)), reference_portfolios=tuple(reversed(first.reference_portfolios)),
    )
    assert first.as_payload() == second.as_payload()
    tampered = deepcopy(first.as_payload())
    tampered["records"][0]["content_hash"] = HASH_B  # type: ignore[index]
    with pytest.raises(BenchmarkReferenceError, match="hash mismatch"):
        CanonicalBenchmarkRegistry.validate_payload(tampered)
    assert _benchmark().digest() == _benchmark(constituents=("AAA", "BBB")).digest()


def test_semver_precedence_and_build_ties_are_deterministic() -> None:
    prerelease = _benchmark(version="1.0.0-rc.1")
    release = _benchmark(version="1.0.0")
    build_a = _benchmark(version="1.0.1+build.a")
    build_b = _benchmark(version="1.0.1+build.b")
    first = CanonicalBenchmarkRegistry(benchmarks=(build_b, release, prerelease, build_a))
    second = CanonicalBenchmarkRegistry(benchmarks=(prerelease, build_a, build_b, release))
    assert first.as_payload() == second.as_payload()
    assert [item.version for item in first.benchmarks] == [
        "1.0.0-rc.1", "1.0.0", "1.0.1+build.a", "1.0.1+build.b",
    ]


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), float("-inf")])
def test_horizon_bounds_reject_boolean_and_non_finite_values_at_contract_boundaries(value: object) -> None:
    with pytest.raises(BenchmarkReferenceError, match="finite"):
        _benchmark(minimum_horizon_years=value)
    with pytest.raises(BenchmarkReferenceError, match="finite"):
        _cash(maximum_horizon_years=value)
    with pytest.raises(BenchmarkReferenceError, match="finite"):
        ReferencePortfolioDefinition(
            "reference:equal_weight", "1.0.0", "equal_weight", ("AAA",), "fixture",
            "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z",
            currency="AUD", minimum_horizon_years=value, maximum_horizon_years=10.0,
        )
    with pytest.raises(BenchmarkReferenceError, match="finite"):
        contract.AnalysisDeclaration(
            "analysis", "comparison", "ETF-1", "AUD", value,
            "2024-01-01", "2024-02-01", "2024-01-02T00:00:00Z",
            "benchmark:x", "cash:x", None, ("reference:x",),
        )


def test_vwce_listing_status_is_validated_directly_and_after_recomputed_hash() -> None:
    with pytest.raises(BenchmarkReferenceError, match="listing status"):
        VwceListingObservation(
            "listing:xetra", "VWCE", "XETR", "EUR",
            "2020-01-01T00:00:00Z", "2024-01-02T00:00:00Z", HASH_A, status="bogus",
        )
    registry = CanonicalBenchmarkRegistry(vwce_anchors=(_vwce(),))
    tampered = deepcopy(registry.as_payload())
    observation = tampered["records"][-1]["payload"]["listing_observations"][0]
    observation["status"] = "bogus"
    record = tampered["records"][-1]
    record["content_hash"] = contract._content_hash(record["payload"])
    tampered["registry_hash"] = contract._content_hash({key: tampered[key] for key in tampered if key != "registry_hash"})
    with pytest.raises(BenchmarkReferenceError, match="semantically invalid"):
        CanonicalBenchmarkRegistry.validate_payload(tampered)


def test_vwce_observation_chronology_is_bound_to_anchor_authority() -> None:
    listing = VwceListingObservation(
        "listing:xetra", "VWCE", "XETR", "EUR",
        "2020-01-01T00:00:00Z", "2024-01-03T00:00:00Z", HASH_A,
    )
    with pytest.raises(BenchmarkReferenceError, match="exceeds anchor authority"):
        _vwce(listing_observations=(listing,))
    prior = replace(listing, effective_at="2019-12-31T00:00:00Z", known_at="2020-01-01T00:00:00Z")
    with pytest.raises(BenchmarkReferenceError, match="precedes anchor authority"):
        _vwce(listing_observations=(prior,))


def test_vwce_direct_construction_rejects_nested_execution_authority() -> None:
    with pytest.raises(BenchmarkReferenceError, match="execution authority"):
        _vwce(fees={"execution_allowed": True})


@pytest.mark.parametrize("value", [True, "1", float("nan"), float("inf")])
def test_vwce_requested_horizon_rejects_boolean_string_and_non_finite_values(value: object) -> None:
    result = resolve_vwce_anchor(
        _vwce(), listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z", currency="EUR", horizon_years=value,
    )
    assert result.status == "unavailable"
    assert result.reason == "horizon_alignment_unavailable"


def test_caller_owned_nested_evidence_is_detached_and_sealed() -> None:
    selector = {"asset_class": "equity"}
    weights = {"AAA": 0.7, "BBB": 0.3}
    benchmark = _benchmark(selector=selector)
    reference = ReferencePortfolioDefinition(
        "reference:no_trade", "1.0.0", "no_trade", ("AAA", "BBB"), "hold current",
        "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z", weights,
        currency="AUD", minimum_horizon_years=0.1, maximum_horizon_years=10.0,
        start_date="2020-01-01", end_date="2030-01-01",
    )
    selector["asset_class"] = "fixed_income"
    weights["AAA"] = 0.1
    assert benchmark.selector["asset_class"] == "equity"
    assert reference.current_weights["AAA"] == 0.7
    with pytest.raises(TypeError):
        benchmark.selector["asset_class"] = "fixed_income"  # type: ignore[index]
    with pytest.raises(TypeError):
        reference.current_weights["AAA"] = 0.1  # type: ignore[index]

    nested = {"ongoing_charges": {"value": "fixture"}}
    evidence = _vwce(fees=nested)
    nested["ongoing_charges"]["value"] = "tampered"
    assert evidence.fees["ongoing_charges"]["value"] == "fixture"  # type: ignore[index]
    observations = [evidence.listing_observations[0]]
    detached = _vwce(listing_observations=observations)
    observations.clear()
    assert len(detached.listing_observations) == 1

    registry = _registry()
    with pytest.raises(AttributeError, match="immutable"):
        registry.benchmarks = ()


def _vwce(**updates: object) -> VwceAnchorEvidence:
    listing = VwceListingObservation("listing:xetra", "VWCE", "XETR", "EUR", "2020-01-01T00:00:00Z", "2024-01-02T00:00:00Z", HASH_A)
    value: dict[str, object] = {
        "canonical_isin": "IE00BK5BQT80",
        "canonical_share_class_id": VWCE_CANONICAL_SHARE_CLASS,
        "official_facts_as_of": "2024-01-01",
        "benchmark_name": "FTSE All-World",
        "benchmark_as_of": "2024-01-01",
        "fees": {"ongoing_charges": "fixture"},
        "fees_as_of": "2024-01-01",
        "tracking": {"tracking_difference": "fixture"},
        "tracking_as_of": "2024-01-01",
        "product_risk_indicator": {"version": "priips-2.0", "value": "fixture"},
        "risk_indicator_as_of": "2024-01-01",
        "currency": "USD",
        "source_hashes": (HASH_A, HASH_B),
        "listing_observations": (listing,),
        "effective_at": "2020-01-01T00:00:00Z",
        "known_at": "2024-01-02T00:00:00Z",
        "minimum_horizon_years": 0.1,
        "maximum_horizon_years": 10.0,
    }
    value.update(updates)
    return VwceAnchorEvidence(**value)  # type: ignore[arg-type]


def test_vwce_listings_resolve_to_one_share_class_and_stale_anchor_blocks_only_relative_claims() -> None:
    anchor = _vwce()
    resolved = resolve_vwce_anchor(anchor, listing_id="listing:xetra", effective_date="2024-02-01", decision_time="2024-02-02T00:00:00Z", currency="EUR", horizon_years=1.0)
    assert resolved.canonical_share_class_id == VWCE_CANONICAL_SHARE_CLASS
    assert resolved.listing_id == "listing:xetra"
    assert anchor.product_risk_indicator["version"] == "priips-2.0"
    assert "product_risk_indicator" not in INSTRUMENT

    blocked = resolve_vwce_anchor(replace(anchor, status="stale"), listing_id="listing:xetra", effective_date="2024-02-01", decision_time="2024-02-02T00:00:00Z", currency="EUR", horizon_years=1.0)
    raw = {"return": 0.12, "raw_status": "available"}
    projection = project_profile_relative_analysis(raw, blocked)
    assert projection["profile_relative_claims_allowed"] is False
    assert projection["raw_analysis"] == raw
    assert projection["execution_allowed"] is False


def test_profile_projection_rejects_incomplete_manual_available_resolution() -> None:
    projection = project_profile_relative_analysis(
        {"return": 0.12},
        contract.VwceAnchorResolution("available", None, None, None),
    )
    assert projection["profile_relative_claims_allowed"] is False
    assert projection["profile_relative_status"] == "unavailable"
    assert projection["anchor_reason"] == "anchor_resolution_incomplete"


def test_vwce_listing_observations_replay_historical_and_latest_versions() -> None:
    historical = VwceListingObservation(
        "listing:xetra", "VWCE", "XETR", "EUR",
        "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z", HASH_A,
    )
    latest = replace(
        historical,
        ticker="VWCE2",
        effective_at="2023-01-01T00:00:00Z",
        known_at="2023-01-02T00:00:00Z",
        source_hash=HASH_B,
    )
    historical_anchor = _vwce(
        official_facts_as_of="2020-01-01",
        benchmark_as_of="2020-01-01",
        fees_as_of="2020-01-01",
        tracking_as_of="2020-01-01",
        risk_indicator_as_of="2020-01-01",
        known_at="2020-01-02T00:00:00Z",
        listing_observations=(historical,),
    )
    anchor = _vwce(listing_observations=(latest, historical))
    replay = resolve_vwce_anchor(
        historical_anchor,
        listing_id="listing:xetra",
        effective_date="2022-01-01",
        decision_time="2022-01-02T00:00:00Z",
        currency="EUR",
        horizon_years=1.0,
    )
    current = resolve_vwce_anchor(
        anchor,
        listing_id="listing:xetra",
        effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z",
        currency="EUR",
        horizon_years=1.0,
    )
    assert replay.status == current.status == "available"
    assert replay.observation_effective_at == "2020-01-01T00:00:00Z"
    assert current.observation_effective_at == "2023-01-01T00:00:00Z"
    assert anchor.digest() == replace(anchor, listing_observations=(historical, latest)).digest()


def test_vwce_true_latest_tie_is_ambiguous_and_invalid_identity_fails_closed() -> None:
    listing = VwceListingObservation("listing:xetra", "VWCE", "XETR", "EUR", "2020-01-01T00:00:00Z", "2024-01-02T00:00:00Z", HASH_A)
    conflicting = replace(listing, ticker="VWCE-CONFLICT", source_hash=HASH_B)
    anchor = _vwce(listing_observations=(listing, conflicting))
    result = resolve_vwce_anchor(anchor, listing_id="listing:xetra", effective_date="2024-02-01", decision_time="2024-02-02T00:00:00Z", currency="EUR", horizon_years=1.0)
    assert result.status == "ambiguous"

    corroborated = resolve_vwce_anchor(
        _vwce(listing_observations=(listing, replace(listing, source_hash=HASH_B))),
        listing_id="listing:xetra",
        effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z",
        currency="EUR",
        horizon_years=1.0,
    )
    assert corroborated.status == "available"
    with pytest.raises(BenchmarkReferenceError, match="canonical ISIN"):
        _vwce(canonical_isin="not-vwce")
    with pytest.raises(BenchmarkReferenceError, match="canonical share class"):
        _vwce(canonical_share_class_id="vwce-share-class")
    with pytest.raises(BenchmarkReferenceError, match="duplicate versioned identifiers"):
        duplicate = _vwce()
        CanonicalBenchmarkRegistry(vwce_anchors=(duplicate, duplicate))


def test_vwce_fact_cutoffs_currency_and_horizon_fail_closed_without_conversion() -> None:
    future_fact = resolve_vwce_anchor(
        _vwce(official_facts_as_of="2024-03-01", known_at="2024-03-02T00:00:00Z"),
        listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-04-02T00:00:00Z", currency="EUR", horizon_years=1.0,
    )
    assert future_fact.reason == "vwce_facts_unavailable_at_cutoff"
    knowledge_cutoff = resolve_vwce_anchor(
        _vwce(), listing_id="listing:xetra", effective_date="2024-03-01",
        decision_time="2024-01-01T00:00:00Z", currency="EUR", horizon_years=1.0,
    )
    assert knowledge_cutoff.reason == "anchor_stale_or_unavailable"
    assert resolve_vwce_anchor(
        _vwce(), listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z", currency="AUD", horizon_years=1.0,
    ).reason == "currency_alignment_unavailable"
    assert resolve_vwce_anchor(
        _vwce(), listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z", currency="EUR", horizon_years=20.0,
    ).reason == "horizon_alignment_unavailable"
    conversion = resolve_vwce_anchor(
        _vwce(), listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z", currency="AUD", horizon_years=1.0,
        conversion_evidence={
            "from_currency": "EUR", "to_currency": "AUD",
            "effective_at": "2024-01-01T00:00:00Z", "known_at": "2024-01-02T00:00:00Z",
            "source_hash": HASH_A,
        },
    )
    assert conversion.status == "available"
    regressing_conversion = resolve_vwce_anchor(
        _vwce(), listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z", currency="AUD", horizon_years=1.0,
        conversion_evidence={
            "from_currency": "EUR", "to_currency": "AUD",
            "effective_at": "2024-01-03T00:00:00Z", "known_at": "2024-01-02T00:00:00Z",
            "source_hash": HASH_A,
        },
    )
    assert regressing_conversion.reason == "currency_alignment_unavailable"


def test_registry_payload_requires_strict_semantic_reconstruction() -> None:
    payload = _registry().as_payload()
    assert CanonicalBenchmarkRegistry.validate_payload(payload) == payload

    arbitrary = deepcopy(payload)
    arbitrary["unexpected"] = "reject"
    arbitrary["registry_hash"] = contract._content_hash({key: arbitrary[key] for key in arbitrary if key != "registry_hash"})
    with pytest.raises(BenchmarkReferenceError, match="envelope"):
        CanonicalBenchmarkRegistry.validate_payload(arbitrary)

    nested_execution = deepcopy(payload)
    benchmark_record = nested_execution["records"][0]
    benchmark_record["payload"]["selector"]["execution_allowed"] = True
    benchmark_record["content_hash"] = contract._content_hash(benchmark_record["payload"])
    nested_execution["registry_hash"] = contract._content_hash({key: nested_execution[key] for key in nested_execution if key != "registry_hash"})
    with pytest.raises(BenchmarkReferenceError, match="execution authority"):
        CanonicalBenchmarkRegistry.validate_payload(nested_execution)

    malformed = deepcopy(payload)
    malformed["records"][0]["payload"]["minimum_horizon_years"] = "one"
    malformed["records"][0]["content_hash"] = contract._content_hash(malformed["records"][0]["payload"])
    malformed["registry_hash"] = contract._content_hash({key: malformed[key] for key in malformed if key != "registry_hash"})
    with pytest.raises(BenchmarkReferenceError, match="semantically invalid"):
        CanonicalBenchmarkRegistry.validate_payload(malformed)

    duplicate = deepcopy(payload)
    duplicate["records"].append(deepcopy(duplicate["records"][0]))
    duplicate["registry_hash"] = contract._content_hash({key: duplicate[key] for key in duplicate if key != "registry_hash"})
    with pytest.raises(BenchmarkReferenceError, match="duplicate"):
        CanonicalBenchmarkRegistry.validate_payload(duplicate)


def test_reference_declarations_include_no_trade_and_require_exact_current_weights() -> None:
    references = declare_reference_portfolios(
        ("BBB", "AAA"), current_weights={"AAA": 0.7, "BBB": 0.3},
        effective_at="2024-01-01T00:00:00Z", known_at="2024-01-02T00:00:00Z",
        currency="AUD", minimum_horizon_years=0.1, maximum_horizon_years=10.0,
        start_date="2020-01-01", end_date="2030-01-01",
    )
    assert [item.method for item in references] == ["equal_weight", "maximum_diversification", "no_trade"]
    assert references[-1].current_weights == {"AAA": 0.7, "BBB": 0.3}
    with pytest.raises(BenchmarkReferenceError, match="cover"):
        ReferencePortfolioDefinition("reference:no_trade", "1.0.0", "no_trade", ("AAA", "BBB"), "hold current", "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z", {"AAA": 1.0})


@pytest.mark.parametrize(
    "weights",
    (
        {"AAA": float("nan"), "BBB": 0.0},
        {"AAA": float("inf"), "BBB": 0.0},
        {"AAA": True, "BBB": 0.0},
        {"AAA": -0.1, "BBB": 1.1},
    ),
)
def test_reference_current_weights_reject_non_finite_boolean_and_negative_values(
    weights: dict[str, float],
) -> None:
    with pytest.raises(BenchmarkReferenceError, match="finite non-negative"):
        ReferencePortfolioDefinition(
            "reference:no_trade", "1.0.0", "no_trade", ("AAA", "BBB"),
            "hold current", "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z", weights,
        )


def test_no_trade_reference_current_weights_must_sum_to_one() -> None:
    with pytest.raises(BenchmarkReferenceError, match="sum to 1.0"):
        ReferencePortfolioDefinition(
            "reference:no_trade", "1.0.0", "no_trade", ("AAA", "BBB"),
            "hold current", "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z",
            {"AAA": 0.4, "BBB": 0.4},
        )


def test_reference_selection_requires_currency_horizon_and_date_coverage() -> None:
    reference = _registry().reference_portfolios[0]
    registry = CanonicalBenchmarkRegistry(
        benchmarks=(_benchmark(),), cash_proxies=(_cash(),), peer_sets=(_peer(),),
        reference_portfolios=(replace(reference, currency="EUR"),),
    )
    resolution = registry.resolve_analysis(
        analysis_id="reference-alignment", purpose="comparison", instrument_id="ETF-1",
        instrument=INSTRUMENT, currency="AUD", horizon_years=1.0,
        start_date="2024-02-01", end_date="2025-02-01",
        decision_time="2024-02-02T00:00:00Z", reference_portfolio_ids=(reference.portfolio_id,),
    )
    assert resolution.references == ()
    assert resolution.blockers == (f"reference:unavailable:{reference.portfolio_id}",)

    late_reference = replace(
        reference,
        effective_at="2024-06-01T00:00:00Z",
        known_at="2024-06-02T00:00:00Z",
    )
    late_registry = CanonicalBenchmarkRegistry(
        benchmarks=(_benchmark(),), cash_proxies=(_cash(),), peer_sets=(_peer(),),
        reference_portfolios=(late_reference,),
    )
    late = late_registry.resolve_analysis(
        analysis_id="reference-effective-cutoff", purpose="comparison", instrument_id="ETF-1",
        instrument=INSTRUMENT, currency="AUD", horizon_years=1.0,
        start_date="2024-02-01", end_date="2025-02-01",
        decision_time="2025-01-01T00:00:00Z", reference_portfolio_ids=(reference.portfolio_id,),
    )
    assert late.references == ()
    assert late.blockers == (f"reference:unavailable:{reference.portfolio_id}",)
