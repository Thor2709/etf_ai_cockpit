from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.analysis.decision.contracts import (
    OpportunityBenchmarkRank,
    OpportunityResult,
)
from etf_cockpit.analysis.decision.opportunity import opportunity_result_payload
from etf_cockpit.analysis.parity_report import (
    analysis_parity_report_path,
    build_parity_report,
    canonical_snapshot_hash,
    compare_source_package,
    load_analysis_parity_config,
    write_parity_report,
)
from etf_cockpit.application import diagnostics_views, ui_facade
from etf_cockpit.application.bulk_run import BulkAnalysisService
from etf_cockpit.portfolio.holdings_table import build_portfolio_holdings_table
from etf_cockpit.portfolio.performance_series import (
    PerformancePoint,
    PerformanceSeries,
    performance_series_frame,
    performance_series_to_csv,
)


NOW = date(2026, 1, 1)


def _result(instrument: str, asset_type: str) -> OpportunityResult:
    return OpportunityResult(
        instrument=instrument,
        asset_type=asset_type,
        decision_time="2026-01-01T00:00:00+00:00",
        status="Attractive",
        baseline_z=0.25,
        percentile=0.75,
        universe_rank=1,
        universe_support=3,
        peer_percentile=0.5,
        peer_rank=1,
        peer_support=3,
        domain_scores=(("quality", 0.25),),
        confidence=0.75,
        coverage=1.0,
        positive_drivers=(),
        negative_drivers=(),
        explanation="frozen replay fixture",
        timing="Neutral",
        timing_reason_code="MOMENTUM_PERCENTILE_NEUTRAL",
        benchmark_rankers=(
            OpportunityBenchmarkRank("v3", 0.25, 0.75, "AVAILABLE", "AVAILABLE"),
        ),
        universe_hash="a" * 64,
        peer_id="fixture-peer",
        config_hash="b" * 64,
        source_vintage_hash="c" * 64,
        reason_code="AVAILABLE",
    )


def _analysis_row(analysis: dict[str, object]) -> dict[str, object]:
    return {
        "instrument": analysis["instrument"],
        "analysis": analysis,
        "snapshot_id": canonical_snapshot_hash(analysis),
        "versions": {
            "schema_version": analysis["schema_version"],
            "formula_version": analysis["formula_version"],
        },
        "sources": [analysis["source_vintage_hash"]],
        "actions": [analysis["status"]],
        "blockers": [analysis["reason_code"]],
    }


def _row(instrument: str, asset_type: str) -> dict[str, object]:
    return _analysis_row(opportunity_result_payload(_result(instrument, asset_type)))


def _evidence() -> dict[str, object]:
    rows = {
        "ACME": _row("ACME", "stock"),
        "ETF_OLD": _row("ETF_OLD", "ETF"),
        "BOND-1": _row("BOND-1", "bond"),
    }
    return {surface: deepcopy(rows) for surface in ("detail", "bulk", "holdings")}


def _portfolio(*, final_value: float = 1.01) -> dict[str, object]:
    points = (
        PerformancePoint(NOW, NOW, 1.0, False, "complete", "available", None, "snapshot-a"),
        PerformancePoint(
            date(2026, 1, 2),
            date(2026, 1, 2),
            final_value,
            False,
            "complete",
            "available",
            None,
            "snapshot-b",
        ),
    )
    series = PerformanceSeries(
        metric="twr_index",
        unit="index",
        currency="EUR",
        period_start=NOW,
        period_end=date(2026, 1, 2),
        partial=False,
        quality="complete",
        status="available",
        reason=None,
        date_range="inception",
        aggregation="day",
        points=points,
    )
    dates = [point.period_end.isoformat() for point in points]
    totals = {"value": 1.01}
    return {
        "portfolio_snapshot_id": "portfolio-snapshot-fixture",
        "ledger": {"totals": dict(totals), "dates": list(dates)},
        "performance_series": {
            "totals": dict(totals),
            "dates": list(dates),
            "rows": performance_series_frame(series).to_dict("records"),
        },
        "csv_export": {
            "totals": dict(totals),
            "content": performance_series_to_csv(series),
        },
    }


def _proposal_order() -> dict[str, object]:
    analysis_id = canonical_snapshot_hash(_row("ACME", "stock")["analysis"])
    return {
        "policy_evidence": {"snapshot_id": "policy-snapshot-fixture"},
        "proposals": [
            {
                "instrument": "ACME",
                "analysis_snapshot_id": analysis_id,
                "portfolio_snapshot_id": "portfolio-snapshot-fixture",
                "policy_snapshot_id": "policy-snapshot-fixture",
            }
        ],
    }


def _package_runner(evidence: dict[str, object]):
    rows = evidence["detail"]
    assert isinstance(rows, dict)
    return lambda: rows


def _surface_evidence(tmp_path: Path, *, alternative_bulk: bool = False) -> dict[str, object]:
    instrument = "ACME"
    source_payload = opportunity_result_payload(_result(instrument, "stock"))
    shadow_result = {**source_payload, "execution_allowed": False}
    artifact_directory = tmp_path / "detail-artifacts"
    artifact_directory.mkdir(parents=True, exist_ok=True)
    artifact = {
        "schema_version": 1,
        "artifact_version": "decision-opportunity-shadow-v1",
        "run_id": "fixture-run",
        "decision_time": "2026-01-01T00:00:00+00:00",
        "config_hashes": {"opportunity": "d" * 64},
        "status": "complete",
        "results": [shadow_result],
        "execution_allowed": False,
    }
    (artifact_directory / "decision_opportunity_fixture-run.json").write_text(
        json.dumps(artifact), encoding="utf-8"
    )
    detail_output = ui_facade.load_opportunity_assessment(
        instrument,
        decision_time=NOW,
        run_id="fixture-run",
        artifact_directory=artifact_directory,
    )
    detail_analysis = {key: detail_output[key] for key in source_payload}
    detail_row = _analysis_row(detail_analysis)

    def analyze(instrument_id: str, analysis_input: dict[str, object]) -> dict[str, object]:
        analysis = deepcopy(analysis_input["analysis"])
        assert isinstance(analysis, dict)
        if alternative_bulk:
            analysis["baseline_z"] = 0.5
        return analysis

    bulk_root = tmp_path / "bulk-store"
    bulk_root.mkdir(parents=True, exist_ok=True)
    bulk_service = BulkAnalysisService(bulk_root)
    bulk_run = bulk_service.start(
        {instrument: {"analysis": source_payload}},
        analyze,
        analyzer_id="analysis-parity-fixture.v1",
    )
    assert instrument in bulk_run.results, bulk_run.failures
    bulk_analysis = bulk_run.results[instrument]
    assert isinstance(bulk_analysis, dict)
    bulk_row = _analysis_row(bulk_analysis)

    policy_id = "policy-snapshot-fixture"
    holdings_output = build_portfolio_holdings_table(
        pd.DataFrame(
            [
                {
                    "instrument_id": instrument,
                    "asset_type": "stock",
                    "quantity": 1,
                    "market_value_eur": 1.0,
                    "current_weight": 1.0,
                    "as_of_date": NOW,
                }
            ]
        ),
        portfolio_snapshot={
            "portfolio_id": "portfolio-fixture",
            "snapshot_id": "portfolio-snapshot-fixture",
            "as_of": NOW,
            "source_checksum": "fixture-checksum",
            "policy_id": policy_id,
        },
        performance_snapshot={
            "date": NOW,
            "snapshot_id": "portfolio-snapshot-fixture",
            "securities_value": 1.0,
            "policy_id": policy_id,
        },
        analysis_snapshot={
            "analysis_run_id": "fixture-run",
            "run_id": "fixture-run",
            "decision_time": source_payload["decision_time"],
            "status": "complete",
            "policy_id": policy_id,
            "policy_status": "available",
            "rows": {
                instrument: {
                    "instrument_id": instrument,
                    "analysis_run_id": "fixture-run",
                    "policy_id": policy_id,
                    "action": source_payload["status"],
                    "blockers": (source_payload["reason_code"],),
                    "scores": {"evidence": 0.25, "quality": 0.25, "risk": 0.25},
                    "rank": 1,
                    "peer_rank": 1,
                    "coverage": 1.0,
                }
            },
        },
        horizon_days=30,
        output_currency="EUR",
        currency_projection=SimpleNamespace(
            available=True,
            currency="EUR",
            reference_rate=1.0,
            decision_time=NOW,
            reason=None,
        ),
    )
    holdings_output_row = holdings_output["rows"][0]
    holdings_row = _analysis_row(source_payload)
    action = holdings_output_row["action"]["value"]
    blockers = holdings_output_row["blockers"]["value"]
    holdings_row["actions"] = [action]
    holdings_row["blockers"] = list(blockers)

    return {
        "detail": {instrument: detail_row},
        "bulk": {instrument: bulk_row},
        "holdings": {instrument: holdings_row},
    }


def test_detail_bulk_holdings_replay_from_frozen_surface_fixture(tmp_path) -> None:
    evidence = _surface_evidence(tmp_path)
    portfolio = _portfolio()
    report = build_parity_report(
        evidence,
        portfolio=portfolio,
        proposal_order=_proposal_order(),
        source_runner=_package_runner(evidence),
        packaged_runner=_package_runner(evidence),
    )

    assert report["status"] == "passed"
    assert report["lanes"]["core_analysis"]["status"] == "passed"
    assert report["lanes"]["source_package"]["status"] == "passed"
    assert report["lanes"]["proposal_order"]["status"] == "passed"
    assert report["tolerances"]["absolute"] == 1e-9
    assert report["tolerances"]["numeric_analysis_fields"] == [
        "baseline_z",
        "percentile",
        "peer_percentile",
        "domain_scores",
        "confidence",
        "coverage",
    ]
    assert load_analysis_parity_config()["required_core_surfaces"] == (
        "detail",
        "bulk",
        "holdings",
    )

    alternative = _surface_evidence(tmp_path / "alternative", alternative_bulk=True)
    alternative_report = build_parity_report(alternative)
    mismatch = alternative_report["first_mismatch"]
    assert alternative_report["lanes"]["core_analysis"]["status"] == "failed"
    assert mismatch["stage"] == "analysis_surface_parity"
    assert mismatch["path"].endswith("analysis.baseline_z")
    assert mismatch["dependency_path"] == [
        "analysis_snapshot",
        "detail.opportunity_result_payload",
        "bulk.opportunity_result_payload",
    ]
    assert alternative_report["mutation_catalogue"][0]["status"] == "detected"

    conversion = deepcopy(evidence)
    conversion["detail"]["ACME"]["future_conversion_basis"] = "current_spot"
    conversion_report = build_parity_report(conversion)
    conversion_mutation = next(
        item
        for item in conversion_report["mutation_catalogue"]
        if item["mutation"] == "current_spot_future_conversion"
    )
    depth = deepcopy(evidence)
    depth["detail"]["ACME"]["analysis_depth"] = "comprehensive"
    depth["bulk"]["ACME"]["analysis_depth"] = "standard"
    depth_report = build_parity_report(depth)
    depth_mutation = next(
        item
        for item in depth_report["mutation_catalogue"]
        if item["mutation"] == "silent_depth_downgrade"
    )
    assert conversion_mutation["status"] == "detected"
    assert depth_mutation["status"] == "detected"


def test_portfolio_reconciliation_uses_parsed_csv_values_and_dates() -> None:
    portfolio = _portfolio()
    report = build_parity_report(_evidence(), portfolio=portfolio)
    assert report["lanes"]["portfolio"]["status"] == "passed"
    assert not any(
        row["path"].startswith("portfolio.")
        for row in report["tolerances"]["uses"]
    )

    contradictory = _portfolio(final_value=2.0)
    assert contradictory["ledger"]["totals"] == {"value": 1.01}
    assert contradictory["performance_series"]["totals"] == {"value": 1.01}
    assert contradictory["csv_export"]["totals"] == {"value": 1.01}
    assert ",2.0," in contradictory["csv_export"]["content"]
    rejected = build_parity_report(_evidence(), portfolio=contradictory)
    assert rejected["lanes"]["portfolio"]["status"] == "failed"
    assert rejected["lanes"]["portfolio"]["first_mismatch"]["path"] == (
        "portfolio.totals.csv_export_content.value"
    )
    assert rejected["lanes"]["core_analysis"]["status"] == "passed"
    shortcut = build_parity_report(None, portfolio=portfolio)
    assert shortcut["lanes"]["core_analysis"]["status"] == "unavailable"
    assert shortcut["status"] != "passed"


def test_proposal_lineage_binds_to_verified_analysis_portfolio_and_policy() -> None:
    evidence = _evidence()
    portfolio = _portfolio()
    proposal = _proposal_order()
    valid = build_parity_report(evidence, portfolio=portfolio, proposal_order=proposal)

    stale_analysis = deepcopy(proposal)
    stale_analysis["proposals"][0]["analysis_snapshot_id"] = "stale-analysis"
    stale_analysis_report = build_parity_report(
        evidence, portfolio=portfolio, proposal_order=stale_analysis
    )
    stale_portfolio = _portfolio()
    stale_portfolio["portfolio_snapshot_id"] = "another-portfolio"
    stale_portfolio_report = build_parity_report(
        evidence, portfolio=stale_portfolio, proposal_order=proposal
    )
    stale_policy = deepcopy(proposal)
    stale_policy["policy_evidence"]["snapshot_id"] = "another-policy"
    stale_policy_report = build_parity_report(
        evidence, portfolio=portfolio, proposal_order=stale_policy
    )
    missing_binding = deepcopy(proposal)
    del missing_binding["proposals"][0]["policy_snapshot_id"]
    missing_report = build_parity_report(
        evidence, portfolio=portfolio, proposal_order=missing_binding
    )
    failed_portfolio_report = build_parity_report(
        evidence,
        portfolio=_portfolio(final_value=2.0),
        proposal_order=proposal,
    )

    assert valid["lanes"]["proposal_order"]["status"] == "passed"
    assert stale_analysis_report["lanes"]["proposal_order"]["status"] == "failed"
    assert stale_portfolio_report["lanes"]["proposal_order"]["status"] == "failed"
    assert stale_policy_report["lanes"]["proposal_order"]["status"] == "failed"
    assert missing_report["lanes"]["proposal_order"]["status"] == "failed"
    assert failed_portfolio_report["lanes"]["proposal_order"]["status"] == "failed"


def test_core_requires_canonical_evidence_and_compares_versions_exactly() -> None:
    incomplete = {
        surface: {"ACME": {"instrument": "ACME"}}
        for surface in ("detail", "bulk", "holdings")
    }
    missing_report = build_parity_report(incomplete)
    assert missing_report["lanes"]["core_analysis"]["status"] == "failed"
    assert missing_report["lanes"]["core_analysis"]["reason"]

    within_tolerance = _evidence()
    numeric_candidate = within_tolerance["bulk"]["ACME"]
    numeric_candidate["analysis"]["baseline_z"] += 5e-10
    numeric_candidate["snapshot_id"] = canonical_snapshot_hash(numeric_candidate["analysis"])
    tolerant_report = build_parity_report(within_tolerance)
    assert tolerant_report["lanes"]["core_analysis"]["status"] == "passed"
    assert any(
        use["path"].endswith("analysis.baseline_z") and use["passed"]
        for use in tolerant_report["tolerances"]["uses"]
    )

    evidence = _evidence()
    candidate = evidence["bulk"]["ACME"]
    candidate["analysis"]["schema_version"] = 1.0000000005
    candidate["versions"]["schema_version"] = 1.0000000005
    candidate["snapshot_id"] = canonical_snapshot_hash(candidate["analysis"])
    version_report = build_parity_report(evidence)
    assert version_report["lanes"]["core_analysis"]["status"] == "failed"
    assert version_report["first_mismatch"]["path"].endswith("analysis.schema_version")
    assert not any(
        use["path"].endswith("schema_version")
        for use in version_report["tolerances"]["uses"]
    )


def test_diagnostics_uses_approved_path_and_missing_report_is_unavailable(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    config = project / "configs" / "universe.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("fixture: true\n", encoding="utf-8")
    approved = project / "artifacts" / "release" / "latest" / "analysis-parity-report.json"
    assert analysis_parity_report_path(project) == approved

    mismatch_report = {
        "schema_version": 2,
        "status": "failed",
        "release_status": "failed",
        "lanes": {"core_analysis": {"status": "failed"}},
        "first_mismatch": {
            "stage": "analysis_surface_parity",
            "path": "analysis.bulk.ACME.baseline_z",
            "dependency_path": ["detail", "bulk"],
        },
    }
    write_parity_report(mismatch_report, approved)
    monkeypatch.setattr(diagnostics_views, "analysis_parity_report_path", lambda: approved)
    diagnostics = ui_facade.load_analysis_parity_report()
    assert diagnostics["status"] == "failed"
    assert diagnostics["first_mismatch"]["path"] == "analysis.bulk.ACME.baseline_z"

    missing_path = tmp_path / "missing-report.json"
    monkeypatch.setattr(diagnostics_views, "analysis_parity_report_path", lambda: missing_path)
    unavailable = ui_facade.load_analysis_parity_report()
    assert unavailable["status"] == "unavailable"
    assert unavailable["reason"]


def test_secret_in_instrument_and_report_paths_is_redacted_everywhere(tmp_path) -> None:
    secret = "sk-abcdefghijklmnop"
    secret_row = _row(secret, "stock")
    evidence = {
        surface: {secret: deepcopy(secret_row)}
        for surface in ("detail", "bulk", "holdings")
    }
    report = build_parity_report(evidence)
    serialized = json.dumps(report)
    assert report["status"] == "failed"
    assert secret not in serialized
    assert "[REDACTED]" in serialized

    path = tmp_path / "sanitized-report.json"
    write_parity_report(
        {
            "schema_version": 2,
            "status": "failed",
            "field_path": f"evidence.detail.{secret}.api_key={secret}",
            "snapshot_hashes": {secret: "fixture-hash"},
        },
        path,
    )
    assert secret not in path.read_text(encoding="utf-8")

    package = compare_source_package(lambda: {"ACME": _row("ACME", "stock")}, None)
    assert package["status"] == "unavailable"
    assert package["reason"]
