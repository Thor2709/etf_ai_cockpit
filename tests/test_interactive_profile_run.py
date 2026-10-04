from __future__ import annotations

import dataclasses
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.analysis_depth import (
    ANALYSIS_CERTIFICATIONS_RELATIVE_PATH,
    ANALYSIS_TIMINGS_RELATIVE_PATH,
    ProfileRunUnavailable,
    load_analysis_depth_profiles,
    read_certification,
    run_analysis_profile,
    run_analysis_profile_set,
)
from etf_cockpit.application.bulk_run import BulkAnalysisService
from etf_cockpit.core.config import ETFConfig, UniverseConfig
from etf_cockpit.core.types import DataQualityIssue, DataQualityReport, SignalResult
from etf_cockpit.application.snapshot_builder import CockpitSnapshot
from tests.test_analysis_depth_scheduling import _install_plan_estimate, _set_test_hardware
from etf_cockpit.application.interactive_profile_run import (
    INTERACTIVE_ANALYZER_ID,
    LOCAL_OPTIONAL_STAGES,
    SnapshotEvidence,
    _CONFIG_FIELDS,
    build_profile_bindings,
    interactive_profile_binder,
)


def fixture_snapshot(*, with_prices: bool = True, unverified: tuple[str, ...] = (), ids=("AAA", "BBB")):
    """Tiny universe: each instrument has 3 local price rows and complete feature/signal evidence."""

    etfs = [
        SimpleNamespace(
            id=name, enabled=True, isin=f"IE000000000{index}", isin_status="needs_verification" if name in unverified else "verified",
            instrument_type="etf", analysis_tier="primary", min_history_days=3, asset_class="equity", region="World",
            sector="Broad", theme="Global", role="core", currency="EUR", ter=0.002,
        )
        for index, name in enumerate(ids)
    ]
    rows = [
        {"etf_id": name, "date": date(2026, 1, day), "close": 100.0 + day}
        for name in ids for day in (1, 2, 3)
    ]
    features = [
        {"etf_id": name, "date": date(2026, 1, 3), "momentum_60d": 0.1, "liquidity_score": 0.8, "trend_200": float("nan")}
        for name in ids
    ]
    signals = [
        SimpleNamespace(
            etf_id=name, blocked_by=["forecast_uncertainty_unavailable"],
            supporting_metrics={"estimated_cost_bps": 13.0, "cost_model_id": "m1", "cost_data_quality": "configured", "baseline_score": 0.6},
        )
        for name in ids
    ]
    return SimpleNamespace(
        config=SimpleNamespace(universe=SimpleNamespace(etfs=etfs, enabled_ids=list(ids))),
        prices=pd.DataFrame(rows if with_prices else [], columns=["etf_id", "date", "close"]),
        latest_features=pd.DataFrame(features),
        signals=signals,
        data_report=SimpleNamespace(as_of_date=date(2026, 1, 3), issues=[], analysis_allowed=True),
        universe_revision="rev-1",
    )


def test_binder_builds_the_inputs_and_runner_bulk_run_executes_with_identical_stage_results(monkeypatch, tmp_path) -> None:
    profile = load_analysis_depth_profiles()["quick"]
    snapshot = fixture_snapshot()
    bindings = interactive_profile_binder(lambda: snapshot)("quick")
    assert [b.instrument_id for b in bindings] == ["AAA", "BBB"]  # the configured universe, sorted
    assert {b.analyzer_id for b in bindings} == {INTERACTIVE_ANALYZER_ID}

    facade = run_analysis_profile_set(profile, bindings, root=tmp_path / "ui")
    assert facade.status == "completed" and facade.reason is None

    # The same inputs and the same stage runner through BulkAnalysisService.start (the bulk_run path).
    _install_plan_estimate(monkeypatch)
    service = BulkAnalysisService(tmp_path / "bulk")
    _set_test_hardware(service, max_concurrency=1)
    run = service.start(
        {b.instrument_id: b.analysis_input for b in bindings},
        analyzer_id=INTERACTIVE_ANALYZER_ID,
        depth_profile="quick",
        stage_runner=bindings[0].stage_runner,
    )
    assert run.status == "succeeded" and not run.failures
    for binding in bindings:
        assert run.results[binding.instrument_id]["stages"] == facade.output["instruments"][binding.instrument_id]["stages"]
        assert set(run.results[binding.instrument_id]["stages"]) == {s.stage_id for s in profile.stages}


def test_stages_read_local_snapshot_evidence_and_unwired_optional_stages_are_omitted(tmp_path) -> None:
    profile = load_analysis_depth_profiles()["medium"]
    bindings = build_profile_bindings(fixture_snapshot())
    result = run_analysis_profile_set(profile, bindings[:1], root=tmp_path)
    assert result.status == "completed"
    output = result.output["instruments"]["AAA"]
    assert output["stages"]["prices_gate"]["rows"] == 3 and output["stages"]["liquidity_gate"]["liquidity_score"] == 0.8
    assert output["stages"]["formulas"]["unavailable"] == ["trend_200"]  # NaN is unavailable, never zero-filled
    assert output["stages"]["hard_risk_gate"]["unavailable_evidence"] == ["forecast_uncertainty_unavailable"]
    optional = {s.stage_id for s in profile.stages if not s.mandatory}
    assert set(output["omitted_optional_stages"]) == optional - set(LOCAL_OPTIONAL_STAGES)
    assert "core_ensemble" in output["omitted_optional_stages"]  # no network, nothing invented
    assert len(pd.read_parquet(tmp_path / ANALYSIS_TIMINGS_RELATIVE_PATH)) == len(profile.stages)


def test_missing_prices_fails_with_the_reason_and_certifies_nothing(tmp_path) -> None:
    profile = load_analysis_depth_profiles()["quick"]
    bindings = build_profile_bindings(fixture_snapshot(with_prices=False))
    result = run_analysis_profile_set(profile, bindings, root=tmp_path)
    assert result.status == "failed" and result.output["instruments"] == {}
    assert "no local prices for AAA" in result.reason and "2 of 2 instruments failed" in result.reason
    stored = pd.read_parquet(tmp_path / ANALYSIS_TIMINGS_RELATIVE_PATH)
    assert set(stored[stored["stage_id"] == "prices_gate"]["outcome"]) == {"failed"}
    assert not (tmp_path / ANALYSIS_CERTIFICATIONS_RELATIVE_PATH).exists()
    assert read_certification(tmp_path, "quick", manifest_hash=profile.manifest_hash) is None


def test_one_failing_instrument_does_not_hide_the_others_and_unverified_identity_fails_closed(tmp_path) -> None:
    profile = load_analysis_depth_profiles()["quick"]
    bindings = build_profile_bindings(fixture_snapshot(unverified=("BBB",)))
    result = run_analysis_profile_set(profile, bindings, root=tmp_path)
    assert result.status == "failed" and set(result.output["instruments"]) == {"AAA"}
    assert "1 of 2 instruments failed" in result.reason and "BBB ISIN status is needs_verification" in result.reason
    assert result.output["failed_instruments"]["BBB"].startswith("mandatory stage identity_gate failed")


def test_binder_states_why_it_cannot_bind() -> None:
    with pytest.raises(ProfileRunUnavailable, match="no data snapshot"):
        interactive_profile_binder(lambda: None)("quick")
    with pytest.raises(ProfileRunUnavailable, match="no enabled instruments"):
        build_profile_bindings(fixture_snapshot(ids=()))


def _run_with_cache(profile_id: str, snapshot, cache: dict, root) -> object:
    profile = load_analysis_depth_profiles()[profile_id]
    binding = next(b for b in build_profile_bindings(snapshot) if b.instrument_id == "AAA")
    return run_analysis_profile(profile, binding, root=root, cache=cache)


def test_changed_cost_metric_on_the_same_snapshot_and_cache_is_not_served_stale(tmp_path) -> None:
    snapshot, cache = fixture_snapshot(), {}
    first = _run_with_cache("medium", snapshot, cache, tmp_path)
    assert first.status == "completed" and first.output["stages"]["core_costs"]["estimated_cost_bps"] == 13.0
    snapshot.signals[0].supporting_metrics["estimated_cost_bps"] = 29.0
    snapshot.signals[0].supporting_metrics["baseline_score"] = 0.2
    second = _run_with_cache("medium", snapshot, cache, tmp_path)
    assert second.output["stages"]["core_costs"]["estimated_cost_bps"] == 29.0
    assert second.output["stages"]["forecast_baseline"]["baseline_score"] == 0.2


def test_changed_isin_status_on_the_same_snapshot_and_cache_fails_identity_instead_of_reusing_a_pass(tmp_path) -> None:
    snapshot, cache = fixture_snapshot(), {}
    assert _run_with_cache("quick", snapshot, cache, tmp_path).status == "completed"
    snapshot.config.universe.etfs[0].isin_status = "needs_verification"
    second = _run_with_cache("quick", snapshot, cache, tmp_path)
    assert second.status == "failed" and "ISIN status is needs_verification" in second.reason


def test_changed_analysis_allowed_on_the_same_snapshot_and_cache_changes_the_data_gate(tmp_path) -> None:
    snapshot, cache = fixture_snapshot(), {}
    assert _run_with_cache("quick", snapshot, cache, tmp_path).status == "completed"
    snapshot.data_report.analysis_allowed = False
    second = _run_with_cache("quick", snapshot, cache, tmp_path)
    assert second.status == "failed" and "portfolio data validation blocks analysis" in second.reason


def test_unavailable_evidence_hashes_as_a_sentinel_not_zero() -> None:
    zero, missing = fixture_snapshot(), fixture_snapshot()
    zero.signals[0].supporting_metrics["estimated_cost_bps"] = 0.0
    del missing.signals[0].supporting_metrics["estimated_cost_bps"]
    digests = {SnapshotEvidence(s).analysis_input("AAA")["evidence_digest"] for s in (zero, missing, fixture_snapshot())}
    assert len(digests) == 3


def test_every_attribute_the_stages_read_exists_on_the_real_types() -> None:
    config_fields = set(ETFConfig.model_fields)
    assert set(_CONFIG_FIELDS) <= config_fields
    assert {"universe_revision", "config", "prices", "latest_features", "signals", "data_report"} <= {
        f.name for f in dataclasses.fields(CockpitSnapshot)
    }
    assert {"supporting_metrics", "blocked_by", "etf_id"} <= {f.name for f in dataclasses.fields(SignalResult)}
    assert {"as_of_date", "issues"} <= {f.name for f in dataclasses.fields(DataQualityReport)}
    assert isinstance(DataQualityReport.analysis_allowed, property)
    assert {"etf_id", "severity", "code"} <= {f.name for f in dataclasses.fields(DataQualityIssue)}
    assert {"etfs"} <= set(UniverseConfig.model_fields) and isinstance(UniverseConfig.enabled_ids, property)
    etf = ETFConfig(id="AAA", name="A", ticker="A", role="core")
    report = DataQualityReport(date(2026, 1, 3), [DataQualityIssue("AAA", "block", "x", "m")])
    assert all(hasattr(etf, name) for name in _CONFIG_FIELDS) and report.analysis_allowed is False
