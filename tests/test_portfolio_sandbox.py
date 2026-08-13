from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit import services
from etf_cockpit.application.portfolio_sandbox import (
    PORTFOLIO_SANDBOX_ENTITY,
    PORTFOLIO_SANDBOX_RESULT_ENTITY,
    analyse_portfolio_candidate,
    build_portfolio_candidate,
    draft_portfolio_proposal,
    export_portfolio_analysis,
    load_portfolio_candidate,
    portfolio_analysis_payload,
    save_portfolio_candidate,
    validate_portfolio_draft_handoff,
)
from etf_cockpit.application import portfolio_sandbox as sandbox_store
from etf_cockpit.core.config import load_config
from etf_cockpit.data.local_storage import StorageRevisionConflict, TransactionalStore
from etf_cockpit.portfolio.sandbox import holdings_checksum
from etf_cockpit.portfolio.sandbox import select_holdings_view
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkDefinition,
    CashProxyDefinition,
    CanonicalBenchmarkRegistry,
    PeerSetDefinition,
    VWCE_CANONICAL_ISIN,
    VWCE_CANONICAL_SHARE_CLASS,
    VwceAnchorEvidence,
    VwceListingObservation,
    declare_reference_portfolios,
)


def _benchmark_registry(source_hash: str) -> CanonicalBenchmarkRegistry:
    return CanonicalBenchmarkRegistry(
        benchmarks=(BenchmarkDefinition(
            benchmark_id="benchmark:fixture",
            version="1.0.0",
            hierarchy="asset",
            selector={"asset_class": "equity"},
            currency="AUD",
            minimum_horizon_years=0.1,
            maximum_horizon_years=10.0,
            effective_at="2024-01-01T00:00:00Z",
            known_at="2024-01-02T00:00:00Z",
            start_date="2020-01-01",
            end_date="2030-01-01",
            methodology="fixture",
            constituents=("VWCE",),
            source_hashes=(source_hash,),
        ),),
        reference_portfolios=declare_reference_portfolios(
            ("VWCE",),
            current_weights={"VWCE": 1.0},
            effective_at="2024-01-01T00:00:00Z",
            known_at="2024-01-02T00:00:00Z",
            currency="AUD",
            minimum_horizon_years=0.1,
            maximum_horizon_years=10.0,
            start_date="2020-01-01",
            end_date="2030-01-01",
        ),
    )


def _canonical_reference_registry(
    anchor: VwceAnchorEvidence,
    *,
    currency: str = "EUR",
) -> CanonicalBenchmarkRegistry:
    return CanonicalBenchmarkRegistry(
        benchmarks=(BenchmarkDefinition(
            benchmark_id="benchmark:global-equity",
            version="1.0.0",
            hierarchy="asset",
            selector={"asset_class": "equity"},
            currency=currency,
            minimum_horizon_years=0.1,
            maximum_horizon_years=10.0,
            effective_at="2024-01-01T00:00:00Z",
            known_at="2024-01-02T00:00:00Z",
            start_date="2020-01-01",
            end_date="2030-01-01",
            methodology="fixture",
            constituents=("VWCE",),
            source_hashes=("a" * 64,),
        ),),
        cash_proxies=(CashProxyDefinition(
            proxy_id="cash:EUR",
            version="1.0.0",
            selector={"asset_class": "equity"},
            currency=currency,
            minimum_horizon_years=0.1,
            maximum_horizon_years=10.0,
            effective_at="2024-01-01T00:00:00Z",
            known_at="2024-01-02T00:00:00Z",
            start_date="2020-01-01",
            end_date="2030-01-01",
            methodology="fixture",
            source_hashes=("a" * 64,),
        ),),
        peer_sets=(PeerSetDefinition(
            peer_set_id="peers:global-equity",
            version="1.0.0",
            hierarchy="asset",
            selector={"asset_class": "equity"},
            member_instrument_ids=("VWCE",),
            effective_at="2024-01-01T00:00:00Z",
            known_at="2024-01-02T00:00:00Z",
            methodology="fixture",
            source_hashes=("a" * 64,),
        ),),
        reference_portfolios=declare_reference_portfolios(
            ("VWCE",),
            current_weights={"VWCE": 1.0},
            effective_at="2024-01-01T00:00:00Z",
            known_at="2024-01-02T00:00:00Z",
            currency=currency,
            minimum_horizon_years=0.1,
            maximum_horizon_years=10.0,
            start_date="2020-01-01",
            end_date="2030-01-01",
        ),
        vwce_anchors=(anchor,),
    )


def _snapshot(*, revision: str = "universe-1", vwce_weight: float = 0.4):
    return SimpleNamespace(
        config=load_config(),
        holdings=pd.DataFrame(
            [
                {"etf_id": "VWCE", "current_weight": vwce_weight, "market_value_eur": 40_000.0},
                {"etf_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0},
            ]
        ),
        universe_revision=revision,
        data_report=SimpleNamespace(as_of_date="2026-07-18"),
    )


def _vwce_anchor(**updates: object) -> VwceAnchorEvidence:
    values: dict[str, object] = {
        "canonical_isin": VWCE_CANONICAL_ISIN,
        "canonical_share_class_id": VWCE_CANONICAL_SHARE_CLASS,
        "official_facts_as_of": "2024-01-01",
        "benchmark_name": "FTSE All-World",
        "benchmark_as_of": "2024-01-01",
        "fees": {"ongoing_charges": "fixture"},
        "fees_as_of": "2024-01-01",
        "tracking": {"tracking_difference": "fixture"},
        "tracking_as_of": "2024-01-01",
        "product_risk_indicator": {"version": "priips-2.0"},
        "risk_indicator_as_of": "2024-01-01",
        "currency": "USD",
        "source_hashes": ("a" * 64,),
        "listing_observations": (VwceListingObservation(
            "listing:xetra", "VWCE", "XETR", "EUR",
            "2020-01-01T00:00:00Z", "2024-01-02T00:00:00Z", "a" * 64,
        ),),
        "effective_at": "2020-01-01T00:00:00Z",
        "known_at": "2024-01-02T00:00:00Z",
        "minimum_horizon_years": 0.1,
        "maximum_horizon_years": 10.0,
    }
    values.update(updates)
    return VwceAnchorEvidence(**values)  # type: ignore[arg-type]


def _candidate(snapshot=None):
    snapshot = snapshot or _snapshot()
    return build_portfolio_candidate(
        snapshot,
        name=" Core allocation ",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
    )


def test_candidate_analysis_is_deterministic_and_non_executable() -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)

    first = analyse_portfolio_candidate(snapshot, candidate)
    second = analyse_portfolio_candidate(snapshot, candidate)

    assert first == second
    assert candidate.name == "Core allocation"
    assert candidate.execution_allowed is False
    assert first.execution_allowed is False
    assert first.source_stale is False
    assert first.overlap_status == "missing"
    assert first.overlap.execution_allowed is False
    assert first.overlap.current_resolved_weight == 0.0
    rows = {row.instrument_id: row for row in first.allocations}
    assert rows["VWCE"].drift == pytest.approx(0.2)
    assert rows["VWCE"].signed_notional_eur == pytest.approx(20_000)
    assert rows["LYP6"].drift == pytest.approx(0.1)
    assert first.cost.total_order_value_eur == pytest.approx(30_000)
    assert any(row.bucket == "Europe" and row.target_weight == pytest.approx(0.3) for row in first.region_exposure)
    assert any("canonical direct holdings evidence is missing" in warning for warning in first.warnings)


def test_analysis_facade_projects_reference_contract_unavailable_without_corrupting_raw_analysis() -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)
    baseline = analyse_portfolio_candidate(snapshot, candidate)
    projected = analyse_portfolio_candidate(
        snapshot,
        candidate,
        reference_registry=CanonicalBenchmarkRegistry(),
        reference_instrument={"asset_class": "equity"},
        reference_currency="AUD",
        reference_horizon_years=1.0,
        reference_start_date="2024-01-01",
        reference_end_date="2025-01-01",
        reference_decision_time="2024-01-02T00:00:00Z",
        reference_portfolio_ids=(),
    )
    assert projected.allocations == baseline.allocations
    assert projected.service_evidence["benchmark_reference"]["status"] == "unavailable"
    assert projected.service_evidence["benchmark_reference"]["execution_allowed"] is False
    assert projected.execution_allowed is False


def test_analysis_facade_applies_vwce_profile_alignment_without_changing_raw_analysis() -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)
    baseline = analyse_portfolio_candidate(snapshot, candidate)
    listing = VwceListingObservation(
        "listing:xetra", "VWCE", "XETR", "EUR",
        "2020-01-01T00:00:00Z", "2024-01-02T00:00:00Z", "a" * 64,
    )
    anchor = VwceAnchorEvidence(
        canonical_isin=VWCE_CANONICAL_ISIN,
        canonical_share_class_id=VWCE_CANONICAL_SHARE_CLASS,
        official_facts_as_of="2024-01-01",
        benchmark_name="FTSE All-World",
        benchmark_as_of="2024-01-01",
        fees={"ongoing_charges": "fixture"},
        fees_as_of="2024-01-01",
        tracking={"tracking_difference": "fixture"},
        tracking_as_of="2024-01-01",
        product_risk_indicator={"version": "priips-2.0", "value": "fixture"},
        risk_indicator_as_of="2024-01-01",
        currency="USD",
        source_hashes=("a" * 64,),
        listing_observations=(listing,),
        effective_at="2020-01-01T00:00:00Z",
        known_at="2024-01-02T00:00:00Z",
        minimum_horizon_years=0.1,
        maximum_horizon_years=10.0,
    )
    arguments = {
        "reference_instrument": {"asset_class": "equity"},
        "reference_horizon_years": 1.0,
        "reference_start_date": "2024-02-01",
        "reference_end_date": "2025-02-01",
        "reference_decision_time": "2024-02-02T00:00:00Z",
        "reference_portfolio_ids": ("reference:equal_weight",),
        "vwce_anchor": anchor,
        "vwce_listing_id": "listing:xetra",
    }
    aligned = analyse_portfolio_candidate(
        snapshot, candidate, reference_currency="EUR",
        reference_registry=_canonical_reference_registry(anchor), **arguments,
    )
    misaligned = analyse_portfolio_candidate(
        snapshot, candidate, reference_currency="AUD",
        reference_registry=_canonical_reference_registry(anchor), **arguments,
    )
    conversion = {
        "from_currency": "EUR", "to_currency": "AUD",
        "effective_at": "2024-01-01T00:00:00Z", "known_at": "2024-01-02T00:00:00Z",
        "source_hash": "a" * 64,
    }
    converted = analyse_portfolio_candidate(
        snapshot,
        candidate,
        reference_currency="AUD",
        reference_registry=CanonicalBenchmarkRegistry(),
        vwce_conversion_evidence=conversion,
        **arguments,
    )
    aud_converted = analyse_portfolio_candidate(
        snapshot,
        candidate,
        reference_currency="AUD",
        reference_registry=_canonical_reference_registry(anchor, currency="AUD"),
        vwce_conversion_evidence=conversion,
        **arguments,
    )
    conversion["source_hash"] = "b" * 64

    assert aligned.allocations == misaligned.allocations == baseline.allocations
    assert aligned.service_evidence["profile_relative"]["profile_relative_claims_allowed"] is True
    assert misaligned.service_evidence["profile_relative"]["profile_relative_claims_allowed"] is False
    profile = converted.service_evidence["profile_relative"]
    assert profile["profile_relative_claims_allowed"] is False
    assert profile["anchor_reason"] == "registry_anchor_membership_unavailable"
    assert profile["anchor_resolution"]["status"] == "unavailable"
    assert profile["anchor_resolution"]["canonical_share_class_id"] == VWCE_CANONICAL_SHARE_CLASS
    assert profile["anchor_resolution"]["anchor_digest"] == anchor.digest()
    assert profile["anchor_resolution"]["conversion_digest"] is not None
    assert profile["anchor_resolution"]["resolution_digest"]
    assert profile["anchor_resolution"]["execution_allowed"] is False
    assert aud_converted.service_evidence["profile_relative"]["profile_relative_claims_allowed"] is True
    assert aud_converted.service_evidence["profile_relative"]["anchor_resolution"]["conversion_digest"] is not None
    assert aligned.execution_allowed is misaligned.execution_allowed is False


def test_default_production_and_persistence_paths_consume_snapshot_reference_evidence(tmp_path) -> None:
    snapshot = _snapshot()
    listing = VwceListingObservation(
        "listing:xetra", "VWCE", "XETR", "EUR",
        "2020-01-01T00:00:00Z", "2024-01-02T00:00:00Z", "a" * 64,
    )
    snapshot.vwce_anchor_evidence = VwceAnchorEvidence(
        canonical_isin=VWCE_CANONICAL_ISIN,
        canonical_share_class_id=VWCE_CANONICAL_SHARE_CLASS,
        official_facts_as_of="2024-01-01", benchmark_name="FTSE All-World",
        benchmark_as_of="2024-01-01", fees={"ongoing_charges": "fixture"},
        fees_as_of="2024-01-01", tracking={"tracking_difference": "fixture"},
        tracking_as_of="2024-01-01",
        product_risk_indicator={"version": "priips-2.0"},
        risk_indicator_as_of="2024-01-01", currency="USD",
        source_hashes=("a" * 64,), listing_observations=(listing,),
        effective_at="2020-01-01T00:00:00Z", known_at="2024-01-02T00:00:00Z",
        minimum_horizon_years=0.1, maximum_horizon_years=10.0,
    )
    snapshot.vwce_listing_id = "listing:xetra"
    snapshot.benchmark_reference_registry = _canonical_reference_registry(snapshot.vwce_anchor_evidence)
    snapshot.benchmark_reference_instrument = {"asset_class": "equity"}
    snapshot.benchmark_reference_currency = "EUR"
    snapshot.benchmark_reference_horizon_years = 1.0
    snapshot.benchmark_reference_start_date = "2024-02-01"
    snapshot.benchmark_reference_end_date = "2025-02-01"
    snapshot.benchmark_reference_decision_time = "2024-02-02T00:00:00Z"
    snapshot.benchmark_reference_portfolio_ids = ("reference:equal_weight",)
    candidate = _candidate(snapshot)

    direct = analyse_portfolio_candidate(snapshot, candidate)
    saved = save_portfolio_candidate(
        snapshot, name="Reference persisted", analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3}, cash_weight=0.1,
        expected_revision=0, root=tmp_path,
    )
    loaded = load_portfolio_candidate(snapshot, "Reference persisted", root=tmp_path)

    assert direct.service_evidence["profile_relative"]["profile_relative_claims_allowed"] is True
    assert saved.result_payload is not None
    assert loaded.result_payload is not None
    assert saved.result_payload["service_evidence"]["profile_relative"] == loaded.result_payload["service_evidence"]["profile_relative"]
    assert loaded.result_payload["service_evidence"]["profile_relative"]["execution_allowed"] is False


def test_registry_anchor_membership_is_exact_and_bound_into_reference_provenance() -> None:
    snapshot = _snapshot()
    anchor = _vwce_anchor()
    candidate = _candidate(snapshot)
    arguments = {
        "reference_instrument": {"asset_class": "equity"},
        "reference_currency": "EUR",
        "reference_horizon_years": 1.0,
        "reference_start_date": "2024-02-01",
        "reference_end_date": "2025-02-01",
        "reference_decision_time": "2024-02-02T00:00:00Z",
        "reference_portfolio_ids": ("reference:equal_weight",),
        "vwce_anchor": anchor,
        "vwce_listing_id": "listing:xetra",
    }

    matched = analyse_portfolio_candidate(
        snapshot, candidate, reference_registry=_canonical_reference_registry(anchor), **arguments,
    )
    provenance = matched.service_evidence["benchmark_reference"]["provenance"]
    assert matched.service_evidence["profile_relative"]["profile_relative_claims_allowed"] is True
    assert provenance["selected_vwce_anchor_digest"] == anchor.digest()
    assert provenance["selected_records"]["vwce_anchor"] == anchor.digest()

    missing = _canonical_reference_registry(anchor)
    object.__setattr__(missing, "vwce_anchors", ())
    mismatched = _canonical_reference_registry(_vwce_anchor(tracking={"tracking_difference": "changed"}))
    duplicated = _canonical_reference_registry(anchor)
    object.__setattr__(duplicated, "vwce_anchors", (anchor, anchor))
    for registry in (missing, mismatched, duplicated):
        blocked = analyse_portfolio_candidate(
            snapshot, candidate, reference_registry=registry, **arguments,
        )
        reference = blocked.service_evidence["benchmark_reference"]
        profile = blocked.service_evidence["profile_relative"]
        assert reference["status"] == "unavailable"
        assert "vwce_anchor:registry_membership_unavailable" in reference["blockers"]
        assert reference["provenance"]["selected_vwce_anchor_digest"] == anchor.digest()
        assert profile["profile_relative_claims_allowed"] is False
        assert profile["anchor_reason"] == "registry_anchor_membership_unavailable"


def test_explicit_empty_reference_arguments_never_reuse_snapshot_evidence() -> None:
    snapshot = _snapshot()
    anchor = _vwce_anchor()
    snapshot.benchmark_reference_registry = _canonical_reference_registry(anchor, currency="AUD")
    snapshot.benchmark_reference_instrument = {"asset_class": "equity"}
    snapshot.benchmark_reference_currency = "AUD"
    snapshot.benchmark_reference_horizon_years = 1.0
    snapshot.benchmark_reference_start_date = "2024-02-01"
    snapshot.benchmark_reference_end_date = "2025-02-01"
    snapshot.benchmark_reference_decision_time = "2024-02-02T00:00:00Z"
    snapshot.benchmark_reference_portfolio_ids = ("reference:equal_weight",)
    snapshot.vwce_anchor_evidence = anchor
    snapshot.vwce_listing_id = "listing:xetra"
    snapshot.vwce_conversion_evidence = {
        "from_currency": "EUR",
        "to_currency": "AUD",
        "effective_at": "2024-01-01T00:00:00Z",
        "known_at": "2024-01-02T00:00:00Z",
        "source_hash": "a" * 64,
    }
    candidate = _candidate(snapshot)

    assert analyse_portfolio_candidate(snapshot, candidate).service_evidence["profile_relative"]["profile_relative_claims_allowed"] is True
    cases = (
        ({"reference_currency": ""}, "reference_resolution_incomplete"),
        ({"reference_start_date": ""}, "reference_resolution_incomplete"),
        ({"reference_end_date": ""}, "reference_resolution_incomplete"),
        ({"reference_decision_time": ""}, "reference_resolution_incomplete"),
        ({"vwce_listing_id": ""}, "listing_unavailable_at_cutoff"),
        ({"vwce_conversion_evidence": {}}, "currency_alignment_unavailable"),
    )
    for updates, reason in cases:
        profile = analyse_portfolio_candidate(
            snapshot, candidate, **updates,
        ).service_evidence["profile_relative"]
        assert profile["profile_relative_claims_allowed"] is False
        assert profile["anchor_reason"] == reason

    empty_ids = analyse_portfolio_candidate(
        snapshot, candidate, reference_portfolio_ids=(),
    ).service_evidence["benchmark_reference"]
    assert empty_ids["status"] == "unavailable"
    assert empty_ids["blockers"] == ["reference_resolution_invalid:BenchmarkReferenceError"]

    empty_instrument = analyse_portfolio_candidate(
        snapshot, candidate, reference_instrument={},
    ).service_evidence["benchmark_reference"]
    assert empty_instrument["status"] == "unavailable"
    assert "benchmark:no_point_in_time_mapping" in empty_instrument["blockers"]


def test_build_snapshot_wires_explicit_reference_evidence_into_real_production_path(monkeypatch) -> None:
    class FakeDataService:
        def __init__(self, config):
            self.config = config

        def update_prices(self, **kwargs):
            return None

        def load_prices(self):
            return pd.DataFrame()

        def validate_prices(self, prices, *, holdings=None):
            return SimpleNamespace(as_of_date="2026-07-18")

    monkeypatch.setattr(services, "configure_logging", lambda: None)
    monkeypatch.setattr(services, "ensure_project_dirs", lambda: None)
    monkeypatch.setattr(services, "load_config", load_config)
    monkeypatch.setattr(services, "_current_universe_revision", lambda: "production-reference-1")
    monkeypatch.setattr(services, "DataService", FakeDataService)
    monkeypatch.setattr(services, "load_holdings", lambda: pd.DataFrame([
        {"etf_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0},
    ]))
    monkeypatch.setattr(services, "model_availability", lambda config: {"timesfm": False, "toto": False})
    monkeypatch.setattr(services, "model_diagnostics", lambda config: [])
    monkeypatch.setattr(services, "load_latest_forecasts", lambda **kwargs: pd.DataFrame())
    monkeypatch.setattr(services, "_load_structure_caps", lambda *args: {})
    monkeypatch.setattr(services, "load_etf_economics_records", lambda: ())
    monkeypatch.setattr(services, "load_total_return_evidence", lambda path: None)
    monkeypatch.setattr(services, "load_closure_proxy_policy", lambda: None)

    snapshot = services._build_snapshot(force_sample=True)
    assert isinstance(snapshot.benchmark_reference_registry, CanonicalBenchmarkRegistry)
    assert snapshot.benchmark_reference_registry.as_payload()["registry_hash"]
    assert snapshot.vwce_anchor_evidence is None
    analysis = analyse_portfolio_candidate(snapshot, _candidate(snapshot))
    assert analysis.service_evidence["benchmark_reference"]["status"] == "unavailable"
    assert analysis.service_evidence["benchmark_reference"]["registry_hash"]
    assert analysis.service_evidence["profile_relative"]["profile_relative_status"] == "unavailable"
    assert analysis.execution_allowed is False


def test_changed_registry_source_hash_rejects_persisted_result_on_load(tmp_path) -> None:
    snapshot = _snapshot()
    snapshot.benchmark_reference_registry = _benchmark_registry("a" * 64)
    snapshot.benchmark_reference_instrument = {"asset_class": "equity"}
    snapshot.benchmark_reference_currency = "AUD"
    snapshot.benchmark_reference_horizon_years = 1.0
    snapshot.benchmark_reference_start_date = "2024-02-01"
    snapshot.benchmark_reference_end_date = "2025-02-01"
    snapshot.benchmark_reference_decision_time = "2024-02-02T00:00:00Z"
    snapshot.benchmark_reference_portfolio_ids = ("reference:equal_weight",)
    save_portfolio_candidate(
        snapshot,
        name="Registry stale result",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    snapshot.benchmark_reference_registry = _benchmark_registry("b" * 64)
    with pytest.raises(ValueError, match="does not match canonical recomputation"):
        load_portfolio_candidate(snapshot, "Registry stale result", root=tmp_path)


def test_candidate_overlap_excludes_evidence_known_after_snapshot_as_of(monkeypatch) -> None:
    evidence = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "security": "Old", "isin": "GB0002634946", "weight": 1.0, "as_of": "2026-07-01", "known_at": "2026-07-02T00:00:00Z", "source_id": "eligible", "authority": "issuer", "completeness": "full"},
            {"instrument_id": "VWCE", "security": "Future", "isin": "GB0002634946", "weight": 1.0, "as_of": "2026-07-17", "known_at": "2026-07-20T00:00:00Z", "source_id": "future", "authority": "issuer", "completeness": "full"},
        ]
    )
    original = sandbox_store.build_direct_overlap_view

    def build_with_evidence(snapshot, instrument_ids, **kwargs):
        return original(snapshot, instrument_ids, holdings=evidence, **kwargs)

    monkeypatch.setattr(sandbox_store, "build_direct_overlap_view", build_with_evidence)

    analysis = analyse_portfolio_candidate(_snapshot(), _candidate())

    selected = next(item for item in analysis.overlap.coverage if item.instrument_id == "VWCE")
    assert selected.source_id == "eligible"
    assert selected.known_at == "2026-07-02T00:00:00+00:00"


def test_overlap_cutoff_matches_the_as_of_emitted_in_source_binding(monkeypatch) -> None:
    snapshot = _snapshot()
    snapshot.holdings["as_of_date"] = "2026-07-17"
    evidence = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "security": "Eligible", "isin": "GB0002634946", "weight": 1.0, "as_of": "2026-07-16", "known_at": "2026-07-17T00:00:00Z", "source_id": "eligible", "authority": "issuer", "completeness": "full"},
            {"instrument_id": "VWCE", "security": "Future", "isin": "GB0002634946", "weight": 1.0, "as_of": "2026-07-18", "known_at": "2026-07-19T12:00:00Z", "source_id": "future", "authority": "issuer", "completeness": "full"},
        ]
    )
    original = sandbox_store.build_direct_overlap_view

    def build_with_evidence(current_snapshot, instrument_ids, **kwargs):
        return original(current_snapshot, instrument_ids, holdings=evidence, **kwargs)

    monkeypatch.setattr(sandbox_store, "build_direct_overlap_view", build_with_evidence)

    analysis = analyse_portfolio_candidate(snapshot, _candidate(snapshot))

    assert analysis.snapshot_binding is not None
    assert analysis.snapshot_binding.as_of == "2026-07-18"
    selected = next(item for item in analysis.overlap.coverage if item.instrument_id == "VWCE")
    assert selected.source_id == "eligible"


@pytest.mark.parametrize(
    ("target", "cash", "expected"),
    [
        (0.45, 0.55, "inside"),
        (0.50, 0.50, "above_soft_band"),
        (0.500_001, 0.499_999, "above_hard_band"),
    ],
)
def test_drift_band_boundaries_remain_strict(target, cash, expected) -> None:
    snapshot = _snapshot()
    candidate = build_portfolio_candidate(
        snapshot,
        name="Band boundary",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": target},
        cash_weight=cash,
    )
    row = next(item for item in analyse_portfolio_candidate(snapshot, candidate).allocations if item.instrument_id == "VWCE")
    assert row.drift_status == expected


def test_holdings_binding_is_independent_of_row_order() -> None:
    holdings = _snapshot().holdings
    assert holdings_checksum(holdings) == holdings_checksum(holdings.iloc[::-1].reset_index(drop=True))
    split = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.1, "market_value_eur": 10_000.0},
            {"etf_id": "VWCE", "current_weight": 0.3, "market_value_eur": 30_000.0},
            {"etf_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0},
        ]
    )
    assert holdings_checksum(holdings) != holdings_checksum(split)


def test_holdings_binding_preserves_line_associations_and_classifier_inputs() -> None:
    first = pd.DataFrame(
        [
            {"instrument_id": "DUP", "current_weight": 0.1, "market_value_eur": 10_000, "holding_view": "direct", "source_id": "one", "asset_type": "stock", "security_type": "ordinary_share", "cfi_code": "E", "crypto": False},
            {"instrument_id": "DUP", "current_weight": 0.2, "market_value_eur": 20_000, "holding_view": "look_through", "source_id": "two", "asset_type": "crypto", "security_type": "crypto", "cfi_code": "X", "crypto": True},
        ]
    )
    swapped = first.copy(deep=True)
    swapped.loc[:, ["current_weight", "market_value_eur"]] = swapped.loc[::-1, ["current_weight", "market_value_eur"]].to_numpy()
    classifier_changed = first.copy(deep=True)
    classifier_changed.loc[1, "crypto"] = False

    assert holdings_checksum(first) != holdings_checksum(swapped)
    assert holdings_checksum(first) != holdings_checksum(classifier_changed)


def test_duplicate_capability_aggregation_is_permutation_stable_and_fail_closed() -> None:
    rows = [
        {"instrument_id": "DUP", "asset_type": "stock", "security_type": "ordinary_share", "cfi_code": "E", "market_cap_usd": 1_000_000_000, "average_daily_value_usd": 1_000_000, "current_weight": 0.1, "market_value_eur": 10_000},
        {"instrument_id": "DUP", "asset_type": "crypto", "security_type": "crypto", "cfi_code": "X", "crypto": True, "current_weight": 0.2, "market_value_eur": 20_000},
    ]
    outcomes = []
    for ordered in (rows, list(reversed(rows))):
        snapshot = _snapshot()
        snapshot.holdings = pd.DataFrame(ordered)
        candidate = build_portfolio_candidate(
            snapshot,
            name="Duplicate classifier",
            analysis_notional_eur=100_000,
            target_weights={"DUP": 0.4},
            cash_weight=0.6,
        )
        allocation = analyse_portfolio_candidate(snapshot, candidate).allocations[0]
        outcomes.append((allocation.current_weight, allocation.capability_status, allocation.capability_reason, allocation.marginal_effect))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][1:] == ("unsupported", "EXCLUDED_CRYPTO_PRODUCT", "inapplicable")


def test_exposure_totals_and_concentration_warnings_reconcile() -> None:
    analysis = analyse_portfolio_candidate(_snapshot(), _candidate())
    eur = next(row for row in analysis.currency_exposure if row.bucket == "EUR")
    broad = next(row for row in analysis.sector_exposure if row.bucket == "Broad")
    assert eur.current_weight == pytest.approx(0.6)
    assert eur.target_weight == pytest.approx(0.9)
    assert broad.current_weight == pytest.approx(0.6)
    assert broad.target_weight == pytest.approx(0.9)
    assert any("Target sector cap exceeded: Broad" in warning for warning in analysis.warnings)


@pytest.mark.parametrize(
    ("targets", "cash", "notional", "message"),
    [
        ({"VWCE": float("nan")}, 1.0, 100_000, "finite number"),
        ({"VWCE": float("inf")}, 1.0, 100_000, "finite number"),
        ({"VWCE": True}, 0.0, 100_000, "finite number"),
        ({"VWCE": np.bool_(True)}, 0.0, 100_000, "finite number"),
        ({"VWCE": -0.1}, 1.1, 100_000, "between 0% and 100%"),
        ({"UNKNOWN": 0.5}, 0.5, 100_000, "unknown or disabled"),
        ({"VWCE": 0.5}, 0.4, 100_000, "must equal 100%"),
        ({"VWCE": 0.5}, float("nan"), 100_000, "finite number"),
        ({"VWCE": 0.5}, 0.5, float("inf"), "finite number"),
        ({"VWCE": 0.5}, 0.5, 0, "greater than zero"),
        ({"VWCE": 0.5}, 0.5, 1_000_000_000_001, "no more than EUR 1 trillion"),
    ],
)
def test_candidate_validation_fails_closed(targets, cash, notional, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_portfolio_candidate(
            _snapshot(),
            name="Candidate",
            analysis_notional_eur=notional,
            target_weights=targets,
            cash_weight=cash,
        )


def test_candidate_persistence_round_trip_revision_conflict_and_stale_re_evaluation(tmp_path) -> None:
    snapshot = _snapshot()
    saved = save_portfolio_candidate(
        snapshot,
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    assert saved.revision == 1
    assert saved.result_payload is not None
    assert saved.result_payload["schema_version"] == "portfolio_sandbox_result.v1"
    assert saved.result_payload["candidate_revision"] == 1
    assert saved.result_payload["candidate_payload_checksum"] == sandbox_store._candidate_payload(saved.candidate)["payload_checksum"]
    assert saved.result_payload["execution_allowed"] is False
    loaded = load_portfolio_candidate(snapshot, " core allocation ", root=tmp_path)
    assert loaded.candidate == saved.candidate
    assert loaded.source_stale is False
    assert loaded.candidate.execution_allowed is False
    assert loaded.result_payload is not None

    updated = save_portfolio_candidate(
        snapshot,
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.5, "LYP6": 0.4},
        cash_weight=0.1,
        expected_revision=loaded.revision,
        root=tmp_path,
    )
    assert updated.revision == 2
    with pytest.raises(StorageRevisionConflict):
        save_portfolio_candidate(
            snapshot,
            name="Core allocation",
            analysis_notional_eur=100_000,
            target_weights={"VWCE": 0.4, "LYP6": 0.5},
            cash_weight=0.1,
            expected_revision=1,
            root=tmp_path,
        )

    changed = _snapshot(revision="universe-2", vwce_weight=0.5)
    stale = load_portfolio_candidate(changed, "Core allocation", root=tmp_path)
    assert stale.source_stale is True
    analysis = analyse_portfolio_candidate(changed, stale.candidate)
    assert analysis.source_stale is True
    assert any("re-evaluated" in warning for warning in analysis.warnings)


def test_legacy_candidate_only_record_upgrades_atomically_with_result(tmp_path) -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)
    with TransactionalStore(tmp_path) as store:
        store.put(PORTFOLIO_SANDBOX_ENTITY, candidate.candidate_id, sandbox_store._candidate_payload(candidate), expected_revision=0)
    upgraded = save_portfolio_candidate(
        snapshot,
        name=candidate.name,
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=1,
        root=tmp_path,
    )
    assert upgraded.revision == 2
    with TransactionalStore(tmp_path) as store:
        result = store.get(PORTFOLIO_SANDBOX_RESULT_ENTITY, candidate.candidate_id)
        assert result.revision == 1
        assert result.payload["candidate_revision"] == 2


def test_candidate_and_result_load_from_one_snapshot_during_interleaved_save(tmp_path, monkeypatch) -> None:
    snapshot = _snapshot()
    save_portfolio_candidate(
        snapshot,
        name="Interleaved pair",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    original_get = TransactionalStore.get
    interleaved = False

    def get_with_interleave(store, entity_type, entity_id, **kwargs):
        nonlocal interleaved
        record = original_get(store, entity_type, entity_id, **kwargs)
        if entity_type == PORTFOLIO_SANDBOX_ENTITY and not interleaved:
            interleaved = True
            save_portfolio_candidate(
                snapshot,
                name="Interleaved pair",
                analysis_notional_eur=100_000,
                target_weights={"VWCE": 0.5, "LYP6": 0.4},
                cash_weight=0.1,
                expected_revision=1,
                root=tmp_path,
            )
        return record

    monkeypatch.setattr(TransactionalStore, "get", get_with_interleave)
    loaded = load_portfolio_candidate(snapshot, "Interleaved pair", root=tmp_path)
    assert loaded.revision == 1
    assert loaded.candidate.targets == {"LYP6": 0.3, "VWCE": 0.6}
    assert loaded.result_payload["candidate_revision"] == 1


def test_direct_and_look_through_views_select_rows_and_bind_selected_checksum() -> None:
    snapshot = _snapshot()
    snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "DIRECT", "asset_type": "stock", "current_weight": 0.4, "market_value_eur": 40_000.0, "holding_view": "direct"},
            {"instrument_id": "INDIRECT", "asset_type": "etf", "current_weight": 0.2, "market_value_eur": 20_000.0, "holding_view": "look_through"},
        ]
    )
    candidate = build_portfolio_candidate(
        snapshot,
        name="View selection",
        analysis_notional_eur=100_000,
        target_weights={"DIRECT": 0.4, "INDIRECT": 0.2},
        cash_weight=0.4,
    )
    direct = analyse_portfolio_candidate(snapshot, candidate, holdings_view="direct")
    look_through = analyse_portfolio_candidate(snapshot, candidate, holdings_view="look_through")
    assert {row.instrument_id for row in direct.holdings} == {"DIRECT"}
    assert {row.instrument_id for row in look_through.holdings} == {"INDIRECT"}
    assert direct.current_value_eur != look_through.current_value_eur
    assert direct.snapshot_binding.source_checksum == holdings_checksum(select_holdings_view(snapshot.holdings, "direct"))
    assert look_through.snapshot_binding.source_checksum == holdings_checksum(select_holdings_view(snapshot.holdings, "look_through"))


def test_malformed_holding_lineage_fails_closed() -> None:
    snapshot = _snapshot()
    snapshot.holdings.loc[0, "holding_view"] = "mystery"
    with pytest.raises(ValueError, match="holding lineage is invalid"):
        analyse_portfolio_candidate(snapshot, _candidate(snapshot))


def test_sparse_look_through_flag_preserves_direct_drift_direction() -> None:
    snapshot = _snapshot()
    snapshot.holdings = pd.DataFrame(
        [
            {
                "instrument_id": "VWCE",
                "asset_type": "etf",
                "security_type": "ordinary_etf",
                "cfi_code": "CEQ",
                "average_daily_value_usd": 1_000_000,
                "current_weight": 0.4,
                "market_value_eur": 40_000.0,
                "holding_view": "direct",
            },
            {
                "instrument_id": "LYP6",
                "asset_type": "etf",
                "security_type": "ordinary_etf",
                "cfi_code": "CEQ",
                "average_daily_value_usd": 1_000_000,
                "current_weight": 0.2,
                "market_value_eur": 20_000.0,
                "holding_view": "look_through",
                "is_look_through": True,
            },
        ]
    )
    candidate = build_portfolio_candidate(
        snapshot,
        name="Sparse lineage",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.15},
        cash_weight=0.85,
        holdings_view="direct",
    )

    analysis = analyse_portfolio_candidate(snapshot, candidate, holdings_view="direct")
    allocation = next(row for row in analysis.allocations if row.instrument_id == "VWCE")
    handoff = draft_portfolio_proposal(snapshot, analysis)

    assert analysis.current_value_eur == 40_000.0
    assert allocation.current_weight == pytest.approx(0.4)
    assert allocation.drift == pytest.approx(-0.25)
    assert handoff["changes"] == [{"instrument_id": "VWCE", "weight_delta": -0.25}]


def test_duplicate_holding_permutation_keeps_result_payload_byte_stable() -> None:
    rows = [
        {
            "instrument_id": "VWCE",
            "asset_type": "etf",
            "security_type": "ordinary_etf",
            "cfi_code": "CEQ",
            "average_daily_value_usd": 1_000_000,
            "current_weight": 0.2,
            "market_value_eur": 20_000.0,
            "holding_view": "direct",
            "source_id": "A",
        },
        {
            "instrument_id": "VWCE",
            "asset_type": "crypto",
            "security_type": "crypto",
            "cfi_code": "X",
            "crypto": True,
            "current_weight": 0.1,
            "market_value_eur": 10_000.0,
            "holding_view": "direct",
            "source_id": "B",
        },
    ]

    payloads = []
    for ordered in (rows, list(reversed(rows))):
        snapshot = _snapshot()
        snapshot.snapshot_id = "stable"
        snapshot.holdings = pd.DataFrame(ordered)
        candidate = build_portfolio_candidate(
            snapshot,
            name="Permutation stable",
            analysis_notional_eur=100_000,
            target_weights={"VWCE": 0.3},
            cash_weight=0.7,
        )
        analysis = analyse_portfolio_candidate(snapshot, candidate, snapshot_id="stable")
        payloads.append(portfolio_analysis_payload(analysis))

    assert payloads[0] == payloads[1]


def test_candidate_name_and_missing_record_fail_closed(tmp_path) -> None:
    with pytest.raises(ValueError, match="1 to 80"):
        build_portfolio_candidate(
            _snapshot(),
            name="   ",
            analysis_notional_eur=100_000,
            target_weights={"VWCE": 0.5},
            cash_weight=0.5,
        )
    with pytest.raises(ValueError, match="1 to 80"):
        build_portfolio_candidate(
            _snapshot(),
            name="x" * 81,
            analysis_notional_eur=100_000,
            target_weights={"VWCE": 0.5},
            cash_weight=0.5,
        )
    with pytest.raises(ValueError, match="no saved portfolio"):
        load_portfolio_candidate(_snapshot(), "Missing", root=tmp_path)


def test_malformed_or_execution_enabled_saved_candidate_fails_closed(tmp_path) -> None:
    snapshot = _snapshot()
    saved = save_portfolio_candidate(
        snapshot,
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    with TransactionalStore(tmp_path) as store:
        record = store.get(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id)
        payload = dict(record.payload)
        payload["execution_allowed"] = True
        store.put(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id, payload, expected_revision=1)

    with pytest.raises(ValueError, match="checksum does not match|no-execution contract"):
        load_portfolio_candidate(snapshot, "Core allocation", root=tmp_path)


def test_rechecks_schema_identity_and_no_execution_even_with_recomputed_checksum(tmp_path) -> None:
    snapshot = _snapshot()
    saved = save_portfolio_candidate(
        snapshot,
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    with TransactionalStore(tmp_path) as store:
        record = store.get(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id)
        payload = dict(record.payload)
        payload["execution_allowed"] = True
        body = {key: value for key, value in payload.items() if key != "payload_checksum"}
        payload["payload_checksum"] = sandbox_store._payload_checksum(body)
        store.put(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id, payload, expected_revision=1)
    with pytest.raises(ValueError, match="no-execution contract"):
        load_portfolio_candidate(snapshot, "Core allocation", root=tmp_path)


def test_saved_candidate_persists_intent_not_derived_analysis(tmp_path) -> None:
    saved = save_portfolio_candidate(
        _snapshot(),
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    with TransactionalStore(tmp_path) as store:
        record = store.get(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id)
    assert record is not None
    assert not ({"drift", "cost", "exposures", "allocations"} & set(record.payload))
    assert record.payload["execution_allowed"] is False


def test_mixed_assets_keep_lineage_capability_and_explicit_why_not() -> None:
    snapshot = _snapshot()
    snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "asset_type": "etf", "security_type": "ordinary_etf", "cfi_code": "CEQ", "average_daily_value_usd": 1_000_000, "current_weight": 0.2, "market_value_eur": 20_000.0, "holding_view": "direct"},
            {"instrument_id": "AAPL", "asset_type": "stock", "security_type": "ordinary_share", "cfi_code": "E", "market_cap_usd": 1_000_000_000, "average_daily_value_usd": 1_000_000, "current_weight": 0.2, "market_value_eur": 20_000.0, "holding_view": "direct"},
            {"instrument_id": "BOND-1", "asset_type": "fixed_rate_bond", "security_type": "fixed_rate_bond", "cfi_code": "DBF", "current_weight": 0.2, "market_value_eur": 20_000.0, "holding_view": "direct"},
            {"instrument_id": "ETF-HOLDING", "asset_type": "etf", "security_type": "ordinary_etf", "cfi_code": "CEQ", "average_daily_value_usd": 1_000_000, "current_weight": 0.1, "market_value_eur": 10_000.0, "holding_view": "look_through", "source_id": "holdings-2026-07-18"},
            {"instrument_id": "COIN", "asset_type": "crypto", "security_type": "crypto", "cfi_code": "X", "crypto": True, "current_weight": 0.1, "market_value_eur": 10_000.0, "holding_view": "direct"},
        ]
    )
    candidate = build_portfolio_candidate(
        snapshot,
        name="Mixed asset sandbox",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.2, "AAPL": 0.2, "BOND-1": 0.2, "ETF-HOLDING": 0.1, "COIN": 0.1},
        cash_weight=0.2,
    )

    analysis = analyse_portfolio_candidate(snapshot, candidate)
    holdings = {row.instrument_id: row for row in analysis.holdings}
    assert holdings["ETF-HOLDING"].holding_view == "look_through"
    assert holdings["AAPL"].capability_status == "supported"
    assert holdings["BOND-1"].capability_status == "unavailable"
    assert holdings["COIN"].capability_status == "unsupported"
    assert dict(analysis.why_not)["COIN"] == "EXCLUDED_CRYPTO_PRODUCT"
    assert any(item.status == "inapplicable" and item.name == "instrument:COIN" for item in analysis.constraints)
    assert analysis.snapshot_binding is not None
    assert analysis.snapshot_binding.execution_allowed is False
    assert analysis.proposal_boundary == "ISSUE-0130:draft-only"


def test_capability_resolution_rejects_contradictory_and_incomplete_classifiers() -> None:
    snapshot = _snapshot()
    snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "CONFLICT", "asset_type": "stock", "security_type": "ordinary_etf", "cfi_code": "CEQ", "current_weight": 0.2, "market_value_eur": 20_000.0},
            {"instrument_id": "INCOMPLETE", "asset_type": "stock", "current_weight": 0.2, "market_value_eur": 20_000.0},
        ]
    )
    candidate = build_portfolio_candidate(
        snapshot,
        name="Capability evidence",
        analysis_notional_eur=100_000,
        target_weights={"CONFLICT": 0.2, "INCOMPLETE": 0.2},
        cash_weight=0.6,
    )
    rows = {row.instrument_id: row for row in analyse_portfolio_candidate(snapshot, candidate).holdings}
    assert rows["CONFLICT"].capability_status == "unsupported"
    assert rows["INCOMPLETE"].capability_status == "unavailable"


def test_empty_holdings_configured_target_uses_canonical_capability() -> None:
    snapshot = _snapshot()
    snapshot.holdings = pd.DataFrame(columns=["instrument_id", "current_weight", "market_value_eur"])
    candidate = build_portfolio_candidate(
        snapshot,
        name="Target only",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.5},
        cash_weight=0.5,
    )
    allocation = analyse_portfolio_candidate(snapshot, candidate).allocations[0]
    assert allocation.instrument_id == "VWCE"
    assert allocation.capability_status == "supported"
    assert allocation.capability_reason != "canonical_capability_resolution_required"


def test_target_only_configured_instrument_with_malformed_resolver_input_is_unavailable() -> None:
    snapshot = _snapshot()
    configured = snapshot.config.universe.by_id()["VWCE"].model_copy(
        update={"average_daily_value_usd": "malformed"}
    )
    universe = snapshot.config.universe.model_copy(update={"etfs": [configured]})
    snapshot.config = snapshot.config.model_copy(update={"universe": universe})
    snapshot.holdings = pd.DataFrame(columns=["instrument_id", "current_weight", "market_value_eur"])
    candidate = build_portfolio_candidate(
        snapshot,
        name="Malformed target only",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.5},
        cash_weight=0.5,
    )
    allocation = analyse_portfolio_candidate(snapshot, candidate).allocations[0]
    assert allocation.capability_status == "unavailable"
    assert allocation.capability_reason == "CLASSIFICATION_EVIDENCE_INCOMPLETE"


def test_draft_handoff_excludes_unsupported_and_constraint_rows() -> None:
    snapshot = _snapshot()
    snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "asset_type": "etf", "security_type": "ordinary_etf", "cfi_code": "CEQ", "average_daily_value_usd": 1_000_000, "current_weight": 0.2, "market_value_eur": 20_000.0},
            {"instrument_id": "COIN", "asset_type": "crypto", "security_type": "crypto", "cfi_code": "X", "crypto": True, "current_weight": 0.1, "market_value_eur": 10_000.0},
        ]
    )
    candidate = build_portfolio_candidate(
        snapshot,
        name="Draft filtering",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "COIN": 0.1},
        cash_weight=0.3,
    )
    analysis = analyse_portfolio_candidate(snapshot, candidate)
    handoff = draft_portfolio_proposal(snapshot, analysis)
    changed_ids = {item["instrument_id"] for item in handoff["changes"]}
    rejected = {item["instrument_id"]: item["reason"] for item in handoff["rejected"]}
    assert "COIN" not in changed_ids
    assert "VWCE" not in changed_ids
    assert "COIN" in rejected
    assert "VWCE" in rejected
    assert handoff["proposal_policy_evaluated"] is False
    assert handoff["execution_allowed"] is False
    assert "evidence_checksum" in handoff


def test_aggregate_constraint_violation_rejects_every_change() -> None:
    snapshot = _snapshot(vwce_weight=0.1)
    snapshot.holdings.loc[snapshot.holdings["etf_id"] == "LYP6", "current_weight"] = 0.1
    candidate = build_portfolio_candidate(
        snapshot,
        name="Aggregate constraint",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.3, "LYP6": 0.3},
        cash_weight=0.4,
    )
    analysis = analyse_portfolio_candidate(snapshot, candidate)
    assert any(item.name.startswith("sector:") and item.status == "violated" for item in analysis.constraints)
    handoff = draft_portfolio_proposal(snapshot, analysis)
    assert handoff["changes"] == []
    assert {item["instrument_id"] for item in handoff["rejected"]} == {"VWCE", "LYP6"}
    assert all("portfolio_constraint_violation" in item["reason"] for item in handoff["rejected"])


def test_complete_handoff_checksum_rejects_mutated_changes() -> None:
    snapshot = _snapshot()
    handoff = draft_portfolio_proposal(snapshot, analyse_portfolio_candidate(snapshot, _candidate(snapshot)))
    assert validate_portfolio_draft_handoff(handoff) == handoff
    tampered = dict(handoff)
    tampered["changes"] = [{"instrument_id": "COIN", "weight_delta": 1.0}]
    with pytest.raises(ValueError, match="checksum"):
        validate_portfolio_draft_handoff(tampered)


def test_result_persistence_export_and_draft_handoff_are_isolated(tmp_path) -> None:
    snapshot = _snapshot()
    snapshot.account_id = "acct-1"
    snapshot.portfolio_id = "portfolio-1"
    snapshot.snapshot_id = "snap-1"
    before = snapshot.holdings.copy(deep=True)
    candidate = _candidate(snapshot)
    analysis = analyse_portfolio_candidate(snapshot, candidate, account_id="acct-1", portfolio_id="portfolio-1", snapshot_id="snap-1")
    payload = portfolio_analysis_payload(analysis)
    assert payload["source_snapshot"]["snapshot_id"] == "snap-1"
    assert payload["before_after"]
    assert payload["execution_allowed"] is False

    exported = export_portfolio_analysis(analysis, tmp_path / "sandbox.json")
    exported_payload = json.loads(exported.read_text(encoding="utf-8"))
    assert exported_payload["schema_version"] == "portfolio_sandbox_result.v1"
    assert exported_payload["execution_allowed"] is False
    handoff = draft_portfolio_proposal(snapshot, analysis)
    assert handoff["boundary"] == "ISSUE-0130"
    assert handoff["status"] == "pre_issue_0130_draft"
    assert handoff["proposal_allowed"] is False
    assert handoff["execution_allowed"] is False
    pd.testing.assert_frame_equal(snapshot.holdings, before)


def test_result_payload_rejects_a_caller_supplied_unbound_candidate_checksum() -> None:
    analysis = analyse_portfolio_candidate(_snapshot(), _candidate())

    with pytest.raises(ValueError, match="checksum does not match candidate"):
        portfolio_analysis_payload(analysis, candidate_payload_checksum="0" * 64)


@pytest.mark.parametrize("mutation", ["execution", "identity", "candidate_revision", "candidate_checksum"])
def test_tampered_recomputed_result_fails_closed(tmp_path, mutation) -> None:
    snapshot = _snapshot()
    saved = save_portfolio_candidate(
        snapshot,
        name="Tamper result",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    with TransactionalStore(tmp_path) as store:
        record = store.get(PORTFOLIO_SANDBOX_RESULT_ENTITY, saved.candidate.candidate_id)
        payload = dict(record.payload)
        if mutation == "execution":
            payload["execution_allowed"] = True
        elif mutation == "identity":
            payload["candidate_id"] = "portfolio_tampered"
        elif mutation == "candidate_revision":
            payload["candidate_revision"] = 99
        else:
            payload["candidate_payload_checksum"] = "f" * 64
        body = {key: value for key, value in payload.items() if key != "payload_checksum"}
        payload["payload_checksum"] = sandbox_store._payload_checksum(body)
        store.put(PORTFOLIO_SANDBOX_RESULT_ENTITY, saved.candidate.candidate_id, payload, expected_revision=1)
    with pytest.raises(ValueError, match="no-execution|identity|revision|checksum"):
        load_portfolio_candidate(snapshot, "Tamper result", root=tmp_path)


def test_tampered_recomputed_source_binding_is_not_surface_as_current(tmp_path) -> None:
    snapshot = _snapshot()
    saved = save_portfolio_candidate(
        snapshot,
        name="Tamper source",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    with TransactionalStore(tmp_path) as store:
        record = store.get(PORTFOLIO_SANDBOX_RESULT_ENTITY, saved.candidate.candidate_id)
        payload = dict(record.payload)
        source = dict(payload["source_snapshot"])
        source["account_id"] = "tampered-account"
        payload["source_snapshot"] = source
        body = {key: value for key, value in payload.items() if key != "payload_checksum"}
        payload["payload_checksum"] = sandbox_store._payload_checksum(body)
        store.put(PORTFOLIO_SANDBOX_RESULT_ENTITY, saved.candidate.candidate_id, payload, expected_revision=1)
    loaded = load_portfolio_candidate(snapshot, "Tamper source", root=tmp_path)
    assert loaded.result_payload is None
    assert loaded.source_stale is True


def test_as_of_only_change_marks_source_stale_and_suppresses_result(tmp_path) -> None:
    snapshot = _snapshot()
    save_portfolio_candidate(
        snapshot,
        name="As-of binding",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    snapshot.data_report.as_of_date = "2026-07-19"

    loaded = load_portfolio_candidate(snapshot, "As-of binding", root=tmp_path)

    assert loaded.source_stale is True
    assert loaded.result_payload is None


def test_adjusted_price_change_marks_result_stale_instead_of_failing_recomputation(tmp_path) -> None:
    snapshot = _snapshot()
    snapshot.price_revision = "prices-1"
    snapshot.prices = pd.DataFrame(
        [
            {
                "date": f"2026-07-{day:02d}",
                "etf_id": instrument_id,
                "adjusted_close": base + day * step,
            }
            for day in range(1, 11)
            for instrument_id, base, step in (("VWCE", 100.0, 1.0), ("LYP6", 80.0, 0.4))
        ]
    )
    save_portfolio_candidate(
        snapshot,
        name="Price-bound result",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    snapshot.price_revision = "prices-2"
    snapshot.prices.loc[
        snapshot.prices["etf_id"].eq("VWCE") & snapshot.prices["date"].eq("2026-07-10"),
        "adjusted_close",
    ] = 130.0

    loaded = load_portfolio_candidate(snapshot, "Price-bound result", root=tmp_path)

    assert loaded.source_stale is True
    assert loaded.result_payload is None


def test_holdings_vintage_and_provider_change_invalidate_result(tmp_path) -> None:
    snapshot = _snapshot()
    snapshot.holdings["as_of_date"] = "2026-07-17"
    snapshot.holdings["source"] = "broker-A"
    saved = save_portfolio_candidate(
        snapshot,
        name="Holdings provenance",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    assert saved.result_payload["source_snapshot"]["as_of"] == "2026-07-18"
    assert saved.result_payload["source_snapshot"]["holdings_sources"] == ["broker-A"]

    snapshot.holdings["as_of_date"] = "2026-07-18"
    snapshot.holdings["source"] = "broker-B"
    loaded = load_portfolio_candidate(snapshot, "Holdings provenance", root=tmp_path)

    assert loaded.source_stale is True
    assert loaded.result_payload is None


def test_recomputed_checksum_cannot_authorise_noncanonical_result_content(tmp_path) -> None:
    snapshot = _snapshot()
    saved = save_portfolio_candidate(
        snapshot,
        name="Canonical result",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    with TransactionalStore(tmp_path) as store:
        record = store.get(PORTFOLIO_SANDBOX_RESULT_ENTITY, saved.candidate.candidate_id)
        payload = dict(record.payload)
        allocations = [dict(item) for item in payload["allocations"]]
        allocations[0]["target_weight"] = 0.123
        payload["allocations"] = allocations
        body = {key: value for key, value in payload.items() if key != "payload_checksum"}
        payload["payload_checksum"] = sandbox_store._payload_checksum(body)
        store.put(
            PORTFOLIO_SANDBOX_RESULT_ENTITY,
            saved.candidate.candidate_id,
            payload,
            expected_revision=record.revision,
        )

    with pytest.raises(ValueError, match="canonical recomputation"):
        load_portfolio_candidate(snapshot, "Canonical result", root=tmp_path)


def test_classifier_change_changes_binding_and_suppresses_stale_result(tmp_path) -> None:
    snapshot = _snapshot()
    snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "AAPL", "asset_type": "stock", "security_type": "ordinary_share", "cfi_code": "E", "market_cap_usd": 1_000_000_000, "average_daily_value_usd": 1_000_000, "current_weight": 0.5, "market_value_eur": 50_000},
        ]
    )
    original_checksum = holdings_checksum(snapshot.holdings)
    save_portfolio_candidate(
        snapshot,
        name="Classifier stale",
        analysis_notional_eur=100_000,
        target_weights={"AAPL": 0.5},
        cash_weight=0.5,
        expected_revision=0,
        root=tmp_path,
    )
    snapshot.holdings.loc[0, ["asset_type", "security_type", "cfi_code", "crypto"]] = ["crypto", "crypto", "X", True]
    assert holdings_checksum(snapshot.holdings) != original_checksum
    loaded = load_portfolio_candidate(snapshot, "Classifier stale", root=tmp_path)
    assert loaded.source_stale is True
    assert loaded.result_payload is None


def test_saved_mixed_asset_candidate_reloads_after_asset_leaves_current_holdings(tmp_path) -> None:
    snapshot = _snapshot()
    snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "asset_type": "etf", "security_type": "ordinary_etf", "cfi_code": "CEQ", "average_daily_value_usd": 1_000_000, "current_weight": 0.4, "market_value_eur": 40_000.0},
            {"instrument_id": "AAPL", "asset_type": "stock", "security_type": "ordinary_share", "cfi_code": "E", "market_cap_usd": 1_000_000_000, "average_daily_value_usd": 1_000_000, "current_weight": 0.3, "market_value_eur": 30_000.0},
        ]
    )
    save_portfolio_candidate(
        snapshot,
        name="Former mixed holding",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.4, "AAPL": 0.3},
        cash_weight=0.3,
        expected_revision=0,
        root=tmp_path,
    )
    snapshot.holdings = snapshot.holdings.loc[
        snapshot.holdings["instrument_id"].eq("VWCE")
    ].reset_index(drop=True)

    loaded = load_portfolio_candidate(snapshot, "Former mixed holding", root=tmp_path)

    assert loaded.candidate.targets["AAPL"] == pytest.approx(0.3)
    assert loaded.source_stale is True
    assert loaded.result_payload is None


def test_snapshot_binding_rejects_identity_relabelling_and_distinguishes_snapshots() -> None:
    first = _snapshot()
    first.account_id = "account-A"
    first.portfolio_id = "portfolio-A"
    first.snapshot_id = "snapshot-A"
    second = _snapshot(vwce_weight=0.5)
    second.account_id = "account-B"
    second.portfolio_id = "portfolio-B"
    second.snapshot_id = "snapshot-B"
    second.prices = pd.DataFrame(
        [{"date": "2026-07-18", "etf_id": "VWCE", "adjusted_close": 101.0}]
    )

    first_binding = sandbox_store.portfolio_snapshot_binding(first)
    second_binding = sandbox_store.portfolio_snapshot_binding(second)

    assert first_binding.account_id == "account-A"
    assert second_binding.account_id == "account-B"
    assert first_binding.source_checksum != second_binding.source_checksum
    assert first_binding.price_source_checksum != second_binding.price_source_checksum
    with pytest.raises(ValueError, match="selected account_id does not match"):
        sandbox_store.portfolio_snapshot_binding(first, account_id="account-B")
    with pytest.raises(ValueError, match="selected snapshot_id does not match"):
        sandbox_store.portfolio_snapshot_binding(first, snapshot_id="snapshot-B")


def test_failed_atomic_export_preserves_prior_file(tmp_path, monkeypatch) -> None:
    analysis = analyse_portfolio_candidate(_snapshot(), _candidate())
    destination = tmp_path / "sandbox.json"
    destination.write_bytes(b"prior-export")

    def fail(*_args, **_kwargs):
        raise OSError("interrupted export")

    monkeypatch.setattr(sandbox_store, "atomic_write_bytes", fail)
    with pytest.raises(OSError, match="interrupted export"):
        export_portfolio_analysis(analysis, destination)
    assert destination.read_bytes() == b"prior-export"


def test_what_if_targets_are_composed_through_existing_services(monkeypatch) -> None:
    snapshot = _snapshot()
    snapshot.prices = pd.DataFrame([{"date": "2026-07-01", "etf_id": "VWCE", "adjusted_close": 100.0}])
    calls: dict[str, object] = {}

    class Solution:
        status = "success"
        method = "minimum_variance"
        feasible = True
        weights = pd.Series({"VWCE": 0.6})
        warnings = ()
        model_version = "test-optimiser"

    class Optimiser:
        def solve(self, method, *, constraints, current_weights):
            calls["optimiser"] = (method, dict(current_weights), constraints.cash_weight)
            return Solution()

    def fake_optimiser(prices):
        calls["prices"] = prices
        return Optimiser(), pd.DataFrame({"VWCE": [0.01]})

    def fake_risk(prices, allocation, **kwargs):
        calls["risk"] = allocation
        return {"status": "partial", "model_version": "test-risk", "selected_estimator": "sample", "warnings": []}

    monkeypatch.setattr(sandbox_store, "build_portfolio_optimiser", fake_optimiser)
    monkeypatch.setattr(sandbox_store, "build_robust_risk_report", fake_risk)
    analysis = analyse_portfolio_candidate(snapshot, _candidate(snapshot))

    assert "prices" in calls and "optimiser" in calls and "risk" in calls
    assert calls["optimiser"][0] == "minimum_variance"
    assert calls["optimiser"][1]["VWCE"] == pytest.approx(0.6)
    assert analysis.service_evidence["optimiser"]["model_version"] == "test-optimiser"
    assert analysis.service_evidence["risk"]["model_version"] == "test-risk"
