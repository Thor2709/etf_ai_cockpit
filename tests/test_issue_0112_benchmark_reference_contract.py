from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.portfolio.benchmark_reference_contract import (
    AnalysisDeclaration,
    AnalysisResolution,
    BenchmarkDefinition,
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
    CashProxyDefinition,
    PeerSetDefinition,
    ReferencePortfolioDefinition,
    Selection,
    VwceAnchorEvidence,
    VwceListingObservation,
    VWCE_CANONICAL_SHARE_CLASS,
    declare_reference_portfolios,
    load_canonical_benchmark_registry,
    project_profile_relative_analysis,
    resolve_vwce_anchor,
)
import etf_cockpit.portfolio.benchmark_reference_contract as contract
from etf_cockpit.application.benchmark_reference import resolve_canonical_reference
from etf_cockpit.application.validation import build_validation_preview
from etf_cockpit.portfolio.attribution import build_performance_attribution


HASH_A = "a" * 64
HASH_B = "b" * 64
REGISTRY_PATH = Path("src/etf_cockpit/resources/benchmark_reference_registry.json")
INSTRUMENT = {"asset_class": "equity", "exposure": "broad", "country_region": "global", "currency": "AUD"}


def test_durable_local_registry_fixture_is_canonical_and_semantically_reconstructed() -> None:
    registry = load_canonical_benchmark_registry()
    assert registry.as_payload() == CanonicalBenchmarkRegistry.validate_payload(
        json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    )
    assert [item.benchmark_id for item in registry.benchmarks] == ["benchmark:ftse-all-world"]
    assert [item.proxy_id for item in registry.cash_proxies] == ["cash:EUR"]
    assert [item.peer_set_id for item in registry.peer_sets] == ["peers:global-equity"]
    assert {item.portfolio_id for item in registry.reference_portfolios} == {
        "reference:equal_weight", "reference:maximum_diversification",
    }
    assert registry.benchmarks[0].status == "unavailable"
    assert registry.cash_proxies[0].status == "unavailable"
    assert registry.peer_sets[0].status == "unavailable"
    assert registry.vwce_anchors[0].status == "unavailable"
    assert registry.benchmarks[0].source_hashes == ()
    assert registry.cash_proxies[0].source_hashes == ()
    assert registry.peer_sets[0].source_hashes == ()
    assert registry.vwce_anchors[0].source_hashes == ()
    assert all(not item.source_hashes for item in registry.reference_portfolios)
    assert registry.vwce_anchors[0].listing_observations[0].listing_id == "listing:vwce:xetra"
    assert registry.as_payload()["execution_allowed"] is False


def test_durable_local_registry_loader_fails_closed_on_missing_malformed_duplicate_and_tampered(
    tmp_path,
) -> None:
    with pytest.raises(BenchmarkReferenceError, match="unavailable or malformed"):
        load_canonical_benchmark_registry(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(BenchmarkReferenceError, match="unavailable or malformed"):
        load_canonical_benchmark_registry(malformed)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"contract":"first","contract":"second"}', encoding="utf-8")
    with pytest.raises(BenchmarkReferenceError, match="duplicate JSON key"):
        load_canonical_benchmark_registry(duplicate)

    tampered_payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    tampered_payload["records"][0]["payload"]["methodology"] = "tampered"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(tampered_payload), encoding="utf-8")
    with pytest.raises(BenchmarkReferenceError, match="registry hash mismatch"):
        load_canonical_benchmark_registry(tampered)


def test_canonical_registry_loader_fails_closed_on_deeply_recursive_json(tmp_path) -> None:
    nested = "0"
    for _ in range(10_000):
        nested = '{"nested":' + nested + "}"
    path = tmp_path / "recursive.json"
    path.write_text(nested, encoding="utf-8")

    with pytest.raises(BenchmarkReferenceError, match="canonical registry"):
        load_canonical_benchmark_registry(path)


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
        "decision_time": "2025-02-02T00:00:00Z",
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


def test_ui_projection_binds_selected_records_and_full_registry_to_content_digests() -> None:
    anchor = _vwce()
    base = _registry()
    first = CanonicalBenchmarkRegistry(
        benchmarks=base.benchmarks,
        cash_proxies=base.cash_proxies,
        peer_sets=base.peer_sets,
        reference_portfolios=base.reference_portfolios,
        vwce_anchors=(anchor,),
    )
    second = _registry(benchmark=_benchmark(source_hashes=(HASH_B,)))
    arguments = {
        "analysis_id": "digest-analysis",
        "purpose": "comparison",
        "instrument_id": "ETF-1",
        "instrument": INSTRUMENT,
        "currency": "AUD",
        "horizon_years": 1.0,
        "start_date": "2024-02-01",
        "end_date": "2025-02-01",
        "decision_time": "2025-02-02T00:00:00Z",
        "reference_portfolio_ids": ("reference:equal_weight",),
    }
    first_projection = first.ui_projection(
        first.resolve_analysis(**arguments), selected_vwce_anchor_digest=anchor.digest(),
    )
    second_projection = second.ui_projection(second.resolve_analysis(**arguments))
    assert first_projection["registry_hash"] != second_projection["registry_hash"]
    assert first_projection["benchmark"]["content_hash"] != second_projection["benchmark"]["content_hash"]
    assert first_projection["provenance"]["registry_hash"] == first_projection["registry_hash"]
    assert first_projection["provenance"]["selected_vwce_anchor_digest"] == anchor.digest()
    assert first_projection["selected_records"]["vwce_anchor"] == anchor.digest()

    with pytest.raises(BenchmarkReferenceError, match="uniquely bound"):
        first.ui_projection(
            first.resolve_analysis(**arguments), selected_vwce_anchor_digest=HASH_B,
        )


def _resolved_registry() -> tuple[CanonicalBenchmarkRegistry, AnalysisResolution]:
    registry = _registry()
    resolution = registry.resolve_analysis(
        analysis_id="projection-membership",
        purpose="comparison",
        instrument_id="ETF-1",
        instrument=INSTRUMENT,
        currency="AUD",
        horizon_years=1.0,
        start_date="2024-02-01",
        end_date="2025-02-01",
        decision_time="2025-02-02T00:00:00Z",
        reference_portfolio_ids=("reference:equal_weight",),
    )
    return registry, resolution


def test_analysis_resolution_rejects_swapped_or_wrong_selection_slots() -> None:
    _registry_value, resolution = _resolved_registry()
    with pytest.raises(BenchmarkReferenceError, match="selection slots are invalid"):
        replace(resolution, benchmark=resolution.cash, cash=resolution.benchmark)
    with pytest.raises(BenchmarkReferenceError, match="selection slots are invalid"):
        replace(resolution, peer_set=resolution.benchmark)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("benchmark_id", "benchmark:forged", "benchmark does not match"),
        ("cash_proxy_id", "cash:forged", "cash proxy does not match"),
        ("peer_set_id", "peers:forged", "peer set does not match"),
        ("reference_portfolio_ids", ("reference:maximum_diversification",), "references do not match"),
    ),
)
def test_analysis_resolution_rejects_forged_declaration_bindings(
    field: str,
    value: object,
    message: str,
) -> None:
    _registry_value, resolution = _resolved_registry()
    declaration = replace(resolution.declaration, **{field: value})
    with pytest.raises(BenchmarkReferenceError, match=message):
        replace(resolution, declaration=declaration)


def test_analysis_resolution_rejects_omitted_and_extra_references() -> None:
    registry, resolution = _resolved_registry()
    with pytest.raises(BenchmarkReferenceError, match="references do not match"):
        replace(resolution, references=())
    extra = next(
        item for item in registry.reference_portfolios
        if item.portfolio_id == "reference:maximum_diversification"
    )
    with pytest.raises(BenchmarkReferenceError, match="references do not match"):
        replace(resolution, references=(*resolution.references, extra))


def test_ui_projection_rejects_mutated_duplicate_declaration_references() -> None:
    registry, resolution = _resolved_registry()
    object.__setattr__(
        resolution.declaration,
        "reference_portfolio_ids",
        resolution.declaration.reference_portfolio_ids * 2,
    )
    with pytest.raises(BenchmarkReferenceError, match="references do not match"):
        registry.ui_projection(resolution)


def test_ui_projection_revalidates_mutated_resolution_and_preserves_valid_unavailable() -> None:
    registry, resolution = _resolved_registry()
    object.__setattr__(resolution, "cash", resolution.benchmark)
    with pytest.raises(BenchmarkReferenceError, match="selection slots are invalid"):
        registry.ui_projection(resolution)

    unavailable = registry.resolve_analysis(
        analysis_id="unavailable-reference",
        purpose="comparison",
        instrument_id="ETF-1",
        instrument=INSTRUMENT,
        currency="AUD",
        horizon_years=1.0,
        start_date="2024-02-01",
        end_date="2025-02-01",
        decision_time="2025-02-02T00:00:00Z",
        reference_portfolio_ids=("reference:missing",),
    )
    projection = registry.ui_projection(unavailable)
    assert projection["blockers"] == ["reference:unavailable:reference:missing"]

    stale_peer_registry = CanonicalBenchmarkRegistry(
        benchmarks=registry.benchmarks,
        cash_proxies=registry.cash_proxies,
        peer_sets=(replace(registry.peer_sets[0], status="stale"),),
        reference_portfolios=registry.reference_portfolios,
    )
    unavailable_peer = stale_peer_registry.resolve_analysis(
        analysis_id="unavailable-peer",
        purpose="comparison",
        instrument_id="ETF-1",
        instrument=INSTRUMENT,
        currency="AUD",
        horizon_years=1.0,
        start_date="2024-02-01",
        end_date="2025-02-01",
        decision_time="2025-02-02T00:00:00Z",
        reference_portfolio_ids=("reference:equal_weight",),
    )
    assert unavailable_peer.declaration.peer_set_id is None
    stale_peer_registry.ui_projection(unavailable_peer)
    object.__setattr__(unavailable_peer.declaration, "peer_set_id", "peers:forged")
    with pytest.raises(BenchmarkReferenceError, match="peer set does not match"):
        stale_peer_registry.ui_projection(unavailable_peer)


@pytest.mark.parametrize("field", ("benchmark", "cash", "peer_set"))
def test_ui_projection_rejects_forged_available_selection_digest(field: str) -> None:
    registry, resolution = _resolved_registry()
    forged = replace(getattr(resolution, field), content_hash=HASH_B)

    with pytest.raises(BenchmarkReferenceError, match="not uniquely bound to registry"):
        registry.ui_projection(replace(resolution, **{field: forged}))


def test_ui_projection_rejects_foreign_reference_digest() -> None:
    registry, resolution = _resolved_registry()
    foreign = replace(resolution.references[0], methodology="foreign methodology")

    with pytest.raises(BenchmarkReferenceError, match="selected reference.*not uniquely bound"):
        registry.ui_projection(replace(resolution, references=(foreign,)))


def test_ui_projection_rejects_absent_and_duplicate_available_members() -> None:
    registry, resolution = _resolved_registry()
    absent = replace(resolution.benchmark, selected_id="benchmark:absent")
    absent_declaration = replace(resolution.declaration, benchmark_id="benchmark:absent")
    with pytest.raises(BenchmarkReferenceError, match="selected benchmark.*not uniquely bound"):
        registry.ui_projection(replace(
            resolution, benchmark=absent, declaration=absent_declaration,
        ))

    object.__setattr__(
        registry,
        "benchmarks",
        (registry.benchmarks[0], registry.benchmarks[0]),
    )
    with pytest.raises(BenchmarkReferenceError, match="selected benchmark.*not uniquely bound"):
        registry.ui_projection(resolution)


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
        start_date="2024-02-01", end_date="2025-02-01", decision_time="2025-02-02T00:00:00Z",
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
        start_date="2024-02-01", end_date="2025-02-01", decision_time="2025-02-02T00:00:00Z",
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
        start_date="2024-02-01", end_date="2025-02-01", decision_time="2025-02-02T00:00:00Z",
    )
    assert benchmark.status == cash.status == "unavailable"
    assert benchmark.reason == cash.reason == expected
    assert benchmark.display_name == cash.display_name == "N/A"


def test_pit_version_replay_rejects_future_unknown_and_stale_evidence() -> None:
    old = _benchmark(version="1.0.0", effective_at="2023-01-01T00:00:00Z", known_at="2023-01-02T00:00:00Z")
    new = _benchmark(version="2.0.0", effective_at="2025-01-01T00:00:00Z", known_at="2025-01-02T00:00:00Z")
    registry = CanonicalBenchmarkRegistry(benchmarks=(new, old), cash_proxies=(_cash(),), peer_sets=(_peer(),), reference_portfolios=_registry().reference_portfolios)
    selected, _, _ = registry.map_instrument(INSTRUMENT, currency="AUD", horizon_years=1.0, start_date="2024-02-01", end_date="2025-02-01", decision_time="2025-02-02T00:00:00Z")
    assert selected.version == "1.0.0"
    future, _, _ = registry.map_instrument(INSTRUMENT, currency="AUD", horizon_years=1.0, start_date="2024-02-01", end_date="2025-02-01", decision_time="2025-02-02T00:00:00Z", benchmark_version="2.0.0")
    assert future.status == "unavailable"
    replay, _, _ = registry.map_instrument(INSTRUMENT, currency="AUD", horizon_years=1.0, start_date="2024-02-01", end_date="2025-02-01", decision_time="2025-02-02T00:00:00Z", benchmark_version="1.0.0")
    assert replay.status == "available"
    assert replay.version == "1.0.0"
    stale, _, _ = _registry(benchmark=replace(old, status="stale")).map_instrument(INSTRUMENT, currency="AUD", horizon_years=1.0, start_date="2024-02-01", end_date="2025-02-01", decision_time="2025-02-02T00:00:00Z")
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
        decision_time="2025-02-02T00:00:00Z",
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
        decision_time="2025-03-01T00:00:00Z",
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


@pytest.mark.parametrize("value", (int("1" * 64), True, b"a" * 64, None))
def test_source_hash_collections_reject_non_string_coercion(value: object) -> None:
    with pytest.raises(BenchmarkReferenceError, match="SHA-256 hashes"):
        _benchmark(source_hashes=(value,))


def test_duplicate_requested_reference_ids_are_rejected_before_normalization() -> None:
    registry = _registry()
    with pytest.raises(BenchmarkReferenceError, match="must not contain duplicates"):
        registry.resolve_analysis(
            analysis_id="duplicate-references",
            purpose="comparison",
            instrument_id="ETF-1",
            instrument=INSTRUMENT,
            currency="AUD",
            horizon_years=1.0,
            start_date="2024-02-01",
            end_date="2025-02-01",
            decision_time="2025-03-01T00:00:00Z",
            reference_portfolio_ids=("reference:equal_weight", " reference:equal_weight "),
        )


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


def test_vwce_listing_source_hash_requires_an_actual_string() -> None:
    class HashLike:
        def lower(self) -> str:
            return HASH_A

    with pytest.raises(BenchmarkReferenceError, match="source_hash must be SHA-256"):
        VwceListingObservation(
            "listing:xetra", "VWCE", "XETR", "EUR",
            "2020-01-01T00:00:00Z", "2024-01-02T00:00:00Z", HashLike(),  # type: ignore[arg-type]
        )


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


@pytest.mark.parametrize("version", [True, 1, ""])
def test_vwce_risk_indicator_version_requires_nonempty_string(version: object) -> None:
    with pytest.raises(BenchmarkReferenceError, match="versioned string"):
        _vwce(product_risk_indicator={"version": version})


def test_anchor_resolution_rejects_execution_authority_directly() -> None:
    with pytest.raises(BenchmarkReferenceError, match="cannot grant execution"):
        contract.VwceAnchorResolution(
            "available", VWCE_CANONICAL_SHARE_CLASS, "listing:xetra", None,
            "2020-01-01T00:00:00Z", "2024-01-02T00:00:00Z", "EUR", 1.0,
            HASH_A, None, True,
        )


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


def test_canonical_hash_rejects_nested_non_string_key_collision_and_cannot_authorize_claims() -> None:
    registered = _vwce(fees={"1": "same"})
    unregistered = _vwce(fees={1: "same", "1": "same"})
    registry = CanonicalBenchmarkRegistry(vwce_anchors=(registered,))
    resolution = resolve_vwce_anchor(
        registered,
        listing_id="listing:xetra",
        effective_date="2024-02-01",
        decision_time="2025-02-02T00:00:00Z",
        currency="EUR",
        horizon_years=1.0,
    )

    with pytest.raises(BenchmarkReferenceError, match="canonical mappings require string keys"):
        unregistered.digest()
    with pytest.raises(BenchmarkReferenceError, match="canonical mappings require string keys"):
        project_profile_relative_analysis(
            {"analysis_status": "available"},
            resolution,
            anchor=unregistered,
            registry=registry,
        )


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


@pytest.mark.parametrize("field", ["fees", "tracking", "product_risk_indicator"])
@pytest.mark.parametrize(
    "nested_evidence",
    [
        {"status": "unavailable", "reason": "fixture"},
        {"status": "stale", "reason": "fixture"},
        {"status": "invalid", "reason": "fixture"},
        {"status": "available"},
    ],
    ids=["unavailable", "stale", "malformed-status", "missing-fact"],
)
def test_vwce_nested_evidence_must_be_semantically_available_for_resolution_and_profile_claims(
    field: str,
    nested_evidence: dict[str, str],
) -> None:
    nested = dict(nested_evidence)
    if field == "product_risk_indicator":
        nested["version"] = "priips-2.0"
        if nested_evidence == {"status": "available"}:
            nested["malformed_fact"] = {}
    anchor = _vwce(**{field: nested})
    resolution = resolve_vwce_anchor(
        anchor,
        listing_id="listing:xetra",
        effective_date="2024-02-01",
        decision_time="2025-02-02T00:00:00Z",
        currency="EUR",
        horizon_years=1.0,
    )
    assert resolution.status == "unavailable"
    assert resolution.reason == "vwce_nested_evidence_unavailable"

    projection = project_profile_relative_analysis(
        {"return": 0.12},
        resolution,
        anchor=anchor,
        registry=CanonicalBenchmarkRegistry(vwce_anchors=(anchor,)),
    )
    assert projection["profile_relative_status"] == "unavailable"
    assert projection["profile_relative_claims_allowed"] is False


@pytest.mark.parametrize("field", ["fees", "tracking", "product_risk_indicator"])
def test_vwce_metadata_only_nested_evidence_cannot_enable_profile_claims(field: str) -> None:
    anchor = _vwce(**{
        field: {
            "status": "available",
            "version": "metadata-only-1.0",
            "execution_allowed": False,
            "source_hashes": [HASH_A],
            "authority": "official",
            "source": "metadata-only",
            "published_at": "2024-01-02T00:00:00Z",
            "timestamp": "2024-01-02T00:00:00Z",
        }
    })
    resolution = resolve_vwce_anchor(
        anchor, listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z", currency="EUR", horizon_years=1.0,
    )
    assert resolution.status == "unavailable"
    projection = project_profile_relative_analysis(
        {"return": 0.12}, resolution, anchor=anchor,
        registry=CanonicalBenchmarkRegistry(vwce_anchors=(anchor,)),
    )
    assert projection["profile_relative_claims_allowed"] is False


@pytest.mark.parametrize("field", ["fees", "tracking", "product_risk_indicator"])
def test_vwce_content_hash_only_nested_evidence_cannot_enable_profile_claims(field: str) -> None:
    nested = {"status": "available", "content_hash": HASH_A}
    if field == "product_risk_indicator":
        nested["version"] = "priips-2.0"
    anchor = _vwce(**{field: nested})
    resolution = resolve_vwce_anchor(
        anchor, listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z", currency="EUR", horizon_years=1.0,
    )
    assert resolution.status == "unavailable"
    assert resolution.reason == "vwce_nested_evidence_unavailable"


def test_production_reference_consumers_share_one_explicit_benchmark_cash_request() -> None:
    registry = _registry()
    request = {
        "instrument_id": "ETF-1",
        "instrument": INSTRUMENT,
        "currency": "AUD",
        "horizon_years": 1.0,
        "start_date": "2024-02-01",
        "end_date": "2025-02-01",
        "decision_time": "2025-02-02T00:00:00Z",
        "reference_portfolio_ids": ("reference:equal_weight",),
    }
    attribution_context = resolve_canonical_reference(
        registry, analysis_id="attribution:fixture", purpose="attribution", **request,
    )
    validation_context = resolve_canonical_reference(
        registry, analysis_id="validation:fixture", purpose="validation", **request,
    )

    assert attribution_context.projection["benchmark"] == validation_context.projection["benchmark"]
    assert attribution_context.projection["cash"] == validation_context.projection["cash"]

    dates = pd.bdate_range("2024-02-01", periods=80)
    prices = pd.DataFrame({
        "date": dates.tolist(),
        "etf_id": "ETF-1",
        "adjusted_close": [100.0 + index for index in range(80)],
    })
    allocation = pd.DataFrame({"etf_id": ["ETF-1"], "current_weight": [0.8]})
    attribution = build_performance_attribution(prices, allocation, reference_context=attribution_context)
    validation = build_validation_preview(prices, reference_context=validation_context)
    assert attribution["benchmark_reference"]["benchmark"] == validation.trials[0].parameters["benchmark_reference"]["benchmark"]
    assert attribution["benchmark_reference"]["cash"] == validation.trials[0].parameters["benchmark_reference"]["cash"]


def test_attribution_cannot_bypass_unavailable_reference_or_forge_available_benchmark_returns() -> None:
    dates = pd.bdate_range("2024-02-01", periods=5)
    prices = pd.DataFrame({
        "date": dates.tolist(),
        "etf_id": "ETF-1",
        "adjusted_close": [100.0, 101.0, 102.0, 103.0, 104.0],
    })
    allocation = pd.DataFrame({"etf_id": ["ETF-1"], "current_weight": [0.8]})
    forged_returns = pd.DataFrame({
        "date": dates[1:].tolist(),
        "benchmark": "forged-benchmark",
        "return": [0.9, 0.9, 0.9, 0.9],
    })

    unavailable = build_performance_attribution(
        prices, allocation, benchmark_returns=forged_returns,
    )
    assert unavailable["benchmark_attribution"].empty
    assert unavailable["coverage"]["benchmark_status"] == "unavailable"

    registry = _registry(benchmark=_benchmark(constituents=("ETF-1",)))
    context = resolve_canonical_reference(
        registry,
        analysis_id="attribution:canonical-series",
        purpose="attribution",
        instrument_id="ETF-1",
        instrument=INSTRUMENT,
        currency="AUD",
        horizon_years=1.0,
        start_date="2024-02-01",
        end_date="2025-02-01",
        decision_time="2025-02-02T00:00:00Z",
        reference_portfolio_ids=("reference:equal_weight",),
    )
    available = build_performance_attribution(
        prices,
        allocation,
        benchmark_returns=forged_returns,
        reference_context=context,
    )
    row = available["benchmark_attribution"].iloc[0]
    assert row["benchmark"] == "ETF-1"
    assert row["return"] == pytest.approx(0.04)
    assert row["return"] != pytest.approx(0.9)


def test_profile_projection_rejects_incomplete_manual_available_resolution() -> None:
    projection = project_profile_relative_analysis(
        {"return": 0.12},
        contract.VwceAnchorResolution("available", None, None, None),
    )
    assert projection["profile_relative_claims_allowed"] is False
    assert projection["profile_relative_status"] == "unavailable"
    assert projection["anchor_reason"] == "registry_anchor_membership_unavailable"


def test_selection_and_analysis_resolution_reject_execution_authority() -> None:
    with pytest.raises(BenchmarkReferenceError, match="selection cannot grant"):
        Selection("benchmark", "available", "benchmark:x", "1.0.0", None, execution_allowed=True)  # type: ignore[arg-type]

    declaration = AnalysisDeclaration(
        "analysis", "comparison", "ETF-1", "AUD", 1.0,
        "2024-02-01", "2025-02-01", "2025-02-02T00:00:00Z",
        "benchmark:x", "cash:x", None, ("reference:x",),
    )
    available = Selection("benchmark", "available", "benchmark:x", "1.0.0", None)
    cash = Selection("cash", "available", "cash:x", "1.0.0", None)
    peer = Selection("peer", "unavailable", None, None, "unavailable")
    with pytest.raises(BenchmarkReferenceError, match="resolution cannot grant"):
        AnalysisResolution(declaration, available, cash, peer, (), (), True)  # type: ignore[arg-type]

    object.__setattr__(available, "execution_allowed", True)
    with pytest.raises(BenchmarkReferenceError, match="contains execution authority"):
        AnalysisResolution(declaration, available, cash, peer, (), ())


def test_analysis_declaration_rejects_calculation_end_after_decision_time() -> None:
    with pytest.raises(BenchmarkReferenceError, match="end_date cannot be after decision_time"):
        AnalysisDeclaration(
            "analysis",
            "comparison",
            "ETF-1",
            "AUD",
            1.0,
            "2024-02-01",
            "2025-02-02",
            "2025-02-01T23:59:59Z",
            "benchmark:x",
            "cash:x",
            None,
            (),
        )


def test_profile_projection_rejects_nested_raw_execution_authority_and_keeps_safe_projection_recursive() -> None:
    anchor = _vwce()
    registry = CanonicalBenchmarkRegistry(vwce_anchors=(anchor,))
    resolution = resolve_vwce_anchor(
        anchor, listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z", currency="EUR", horizon_years=1.0,
    )
    with pytest.raises(BenchmarkReferenceError, match="execution authority"):
        project_profile_relative_analysis(
            {"nested": {"execution_allowed": True}},
            resolution,
            anchor=anchor,
            registry=registry,
        )

    projected = project_profile_relative_analysis(
        {"nested": {"execution_allowed": False}},
        resolution,
        anchor=anchor,
        registry=registry,
    )

    def assert_disabled(value: object) -> None:
        if isinstance(value, dict):
            if "execution_allowed" in value:
                assert value["execution_allowed"] is False
            for item in value.values():
                assert_disabled(item)
        elif isinstance(value, list):
            for item in value:
                assert_disabled(item)

    assert projected["profile_relative_claims_allowed"] is True
    assert_disabled(projected)


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


@pytest.mark.parametrize("status", ["stale", "unavailable"])
def test_latest_pit_listing_status_never_falls_back_to_obsolete_available_observation(status: str) -> None:
    historical = VwceListingObservation(
        "listing:xetra", "VWCE", "XETR", "EUR",
        "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z", HASH_A,
    )
    latest = replace(
        historical, effective_at="2023-01-01T00:00:00Z",
        known_at="2023-01-02T00:00:00Z", source_hash=HASH_B, status=status,
    )
    resolution = resolve_vwce_anchor(
        _vwce(listing_observations=(historical, latest)),
        listing_id="listing:xetra", effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z", currency="EUR", horizon_years=1.0,
    )
    assert resolution.status == "unavailable"
    assert resolution.reason == "listing_stale_or_unavailable"


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


@pytest.mark.parametrize(
    "change",
    (
        {"listing_id": "listing:forged"},
        {"horizon_years": 2.0},
        {"effective_date": "2023-01-01"},
        {"decision_time": "2023-01-02T00:00:00Z"},
        {"conversion_digest": HASH_B},
    ),
)
def test_available_profile_resolution_is_replayed_against_bound_evidence(change: dict[str, object]) -> None:
    anchor = _vwce()
    resolution = resolve_vwce_anchor(
        anchor,
        listing_id="listing:xetra",
        effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z",
        currency="EUR",
        horizon_years=1.0,
    )
    forged = replace(resolution, **change)
    projection = contract.project_profile_relative_analysis(
        {"analysis_id": "forged"}, forged, anchor=anchor,
    )
    assert projection["profile_relative_claims_allowed"] is False
    assert projection["profile_relative_status"] == "unavailable"


def test_vwce_listing_source_hash_must_belong_to_anchor_provenance() -> None:
    forged_listing = replace(_vwce().listing_observations[0], source_hash=HASH_B)
    resolution = resolve_vwce_anchor(
        _vwce(source_hashes=(HASH_A,), listing_observations=(forged_listing,)),
        listing_id="listing:xetra",
        effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z",
        currency="EUR",
        horizon_years=1.0,
    )
    assert resolution.status == "unavailable"
    assert resolution.reason == "listing_provenance_unavailable"


def test_every_authoritative_tied_listing_source_must_belong_to_anchor_provenance() -> None:
    bound = _vwce().listing_observations[0]
    unbound = replace(bound, source_hash=HASH_B)
    resolution = resolve_vwce_anchor(
        _vwce(source_hashes=(HASH_A,), listing_observations=(bound, unbound)),
        listing_id="listing:xetra",
        effective_date="2024-02-01",
        decision_time="2024-02-02T00:00:00Z",
        currency="EUR",
        horizon_years=1.0,
    )
    assert resolution.status == "unavailable"
    assert resolution.reason == "listing_provenance_unavailable"


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
        decision_time="2025-02-02T00:00:00Z", reference_portfolio_ids=(reference.portfolio_id,),
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
        decision_time="2025-02-02T00:00:00Z", reference_portfolio_ids=(reference.portfolio_id,),
    )
    assert late.references == ()
    assert late.blockers == (f"reference:unavailable:{reference.portfolio_id}",)


@pytest.mark.parametrize(
    "newer_updates",
    (
        {"currency": "EUR"},
        {"minimum_horizon_years": 2.0, "maximum_horizon_years": 10.0},
        {"start_date": "2024-06-01", "end_date": "2030-01-01"},
    ),
    ids=("currency", "horizon", "coverage"),
)
def test_newest_pit_reference_version_blocks_without_falling_back_to_aligned_older_version(
    newer_updates: dict[str, object],
) -> None:
    older = next(
        item for item in _registry().reference_portfolios
        if item.portfolio_id == "reference:equal_weight"
    )
    newer = replace(
        older,
        version="2.0.0",
        effective_at="2024-01-15T00:00:00Z",
        known_at="2024-01-16T00:00:00Z",
        **newer_updates,
    )
    registry = CanonicalBenchmarkRegistry(
        benchmarks=(_benchmark(),),
        cash_proxies=(_cash(),),
        peer_sets=(_peer(),),
        reference_portfolios=(older, newer),
    )
    resolution = registry.resolve_analysis(
        analysis_id="authoritative-reference",
        purpose="comparison",
        instrument_id="ETF-1",
        instrument=INSTRUMENT,
        currency="AUD",
        horizon_years=1.0,
        start_date="2024-02-01",
        end_date="2025-02-01",
        decision_time="2025-02-02T00:00:00Z",
        reference_portfolio_ids=("reference:equal_weight",),
    )
    assert resolution.references == ()
    assert resolution.blockers == ("reference:unavailable:reference:equal_weight",)
