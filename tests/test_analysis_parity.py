from __future__ import annotations

from copy import deepcopy
from datetime import date
import json

from etf_cockpit.analysis.decision.contracts import (
    OpportunityBenchmarkRank,
    OpportunityResult,
)
from etf_cockpit.analysis.decision.opportunity import opportunity_result_payload
from etf_cockpit.analysis.parity_report import (
    build_parity_report,
    canonical_snapshot_hash,
    compare_source_package,
    load_analysis_parity_config,
)
from etf_cockpit.application.ui_facade import load_analysis_parity_report
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


def _row(instrument: str, asset_type: str) -> dict[str, object]:
    payload = opportunity_result_payload(_result(instrument, asset_type))
    return {
        "instrument": instrument,
        "analysis": payload,
        "snapshot_id": canonical_snapshot_hash(payload),
        "versions": {
            "schema_version": payload["schema_version"],
            "formula_version": payload["formula_version"],
        },
        "sources": [payload["source_vintage_hash"]],
        "actions": [payload["status"]],
        "blockers": [payload["reason_code"]],
    }


def _evidence() -> dict[str, object]:
    rows = {
        "ACME": _row("ACME", "stock"),
        "ETF_OLD": _row("ETF_OLD", "ETF"),
        "BOND-1": _row("BOND-1", "bond"),
    }
    return {surface: deepcopy(rows) for surface in ("detail", "bulk", "holdings")}


def _portfolio() -> dict[str, object]:
    points = (
        PerformancePoint(NOW, NOW, 1.0, False, "complete", "available", None, "snapshot-a"),
        PerformancePoint(
            date(2026, 1, 2),
            date(2026, 1, 2),
            1.01,
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
    totals = {"closing_index": 1.01}
    return {
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
    identities = {
        "analysis_snapshot_id": analysis_id,
        "portfolio_snapshot_id": "portfolio-snapshot-fixture",
        "policy_snapshot_id": "policy-snapshot-fixture",
    }
    return {"identities": identities, "proposals": [dict(identities)]}


def _package_runner(evidence: dict[str, object]):
    rows = evidence["detail"]
    assert isinstance(rows, dict)
    return lambda: rows


def test_detail_bulk_holdings_replay_from_one_frozen_fixture() -> None:
    evidence = _evidence()
    report = build_parity_report(
        evidence,
        portfolio=_portfolio(),
        proposal_order=_proposal_order(),
        source_runner=_package_runner(evidence),
        packaged_runner=_package_runner(evidence),
    )

    assert report["status"] == "passed"
    assert report["lanes"]["core_analysis"]["status"] == "passed"
    assert report["lanes"]["source_package"]["status"] == "passed"
    assert report["tolerances"]["absolute"] == 1e-9
    assert all(
        row["actions"] == evidence["detail"][instrument]["actions"]
        and row["blockers"] == evidence["detail"][instrument]["blockers"]
        and row["versions"] == evidence["detail"][instrument]["versions"]
        for instrument, row in evidence["holdings"].items()
    )
    assert load_analysis_parity_config()["required_core_surfaces"] == (
        "detail",
        "bulk",
        "holdings",
    )


def test_alternative_calculation_fails_at_first_divergent_stage() -> None:
    evidence = _evidence()
    evidence["bulk"]["ACME"]["analysis"]["baseline_z"] = 0.5

    report = build_parity_report(evidence)
    mismatch = report["first_mismatch"]

    assert report["lanes"]["core_analysis"]["status"] == "failed"
    assert mismatch["stage"] == "analysis_snapshot_identity"
    assert mismatch["path"].endswith("snapshot_id")
    assert mismatch["dependency_path"] == [
        "opportunity_result_payload.sha256",
        "bulk.snapshot_id",
    ]
    assert report["mutation_catalogue"][0]["status"] == "detected"


def test_required_mutations_are_detected_and_plain_text_api_key_fails() -> None:
    conversion = _evidence()
    conversion["detail"]["ACME"]["future_conversion_basis"] = "current_spot"
    conversion_report = build_parity_report(conversion)
    conversion_mutation = next(
        item
        for item in conversion_report["mutation_catalogue"]
        if item["mutation"] == "current_spot_future_conversion"
    )

    depth = _evidence()
    depth["detail"]["ACME"]["analysis_depth"] = "comprehensive"
    depth["bulk"]["ACME"]["analysis_depth"] = "standard"
    depth_report = build_parity_report(depth)
    depth_mutation = next(
        item
        for item in depth_report["mutation_catalogue"]
        if item["mutation"] == "silent_depth_downgrade"
    )

    credential = _evidence()
    credential["detail"]["ACME"]["api_key"] = "plaintext-test-key"
    credential_report = build_parity_report(credential)

    assert conversion_report["lanes"]["core_analysis"]["status"] == "failed"
    assert conversion_mutation["status"] == "detected"
    assert depth_report["lanes"]["core_analysis"]["status"] == "failed"
    assert depth_mutation["status"] == "detected"
    assert credential_report["status"] == "failed"
    assert credential_report["mutation_catalogue"][3]["status"] == "detected"
    assert "plaintext-test-key" not in str(credential_report)


def test_ledger_performance_series_and_csv_export_reconcile() -> None:
    portfolio = _portfolio()
    report = build_parity_report(_evidence(), portfolio=portfolio)

    assert report["lanes"]["portfolio"]["status"] == "passed"
    assert any(
        tolerance["path"].startswith("portfolio.")
        for tolerance in report["tolerances"]["uses"]
    )


def test_proposal_lineage_requires_exact_analysis_portfolio_and_policy_ids() -> None:
    valid = build_parity_report(_evidence(), proposal_order=_proposal_order())
    missing = _proposal_order()
    missing["identities"]["analysis_snapshot_id"] = ""
    missing_report = build_parity_report(_evidence(), proposal_order=missing)
    mismatched = _proposal_order()
    mismatched["proposals"][0]["policy_snapshot_id"] = "another-policy-snapshot"
    mismatch_report = build_parity_report(_evidence(), proposal_order=mismatched)

    assert valid["lanes"]["proposal_order"]["status"] == "passed"
    assert missing_report["lanes"]["proposal_order"]["status"] == "failed"
    assert mismatch_report["lanes"]["proposal_order"]["status"] == "failed"


def test_core_status_is_independent_and_missing_package_is_unavailable(tmp_path) -> None:
    evidence = _evidence()
    portfolio = _portfolio()
    portfolio["ledger"]["totals"]["closing_index"] = 3.0
    report = build_parity_report(
        evidence,
        portfolio=portfolio,
        source_runner=_package_runner(evidence),
        packaged_runner=None,
    )
    shortcut = build_parity_report(
        None,
        portfolio=_portfolio(),
        source_runner=_package_runner(evidence),
        packaged_runner=_package_runner(evidence),
    )
    differential = compare_source_package(_package_runner(evidence), None)
    stored_report = tmp_path / "parity.json"
    stored_report.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    diagnostics = load_analysis_parity_report(report_path=stored_report)

    assert report["lanes"]["portfolio"]["status"] == "failed"
    assert report["lanes"]["core_analysis"]["status"] == "passed"
    assert report["lanes"]["source_package"]["status"] == "unavailable"
    assert report["lanes"]["source_package"]["reason"]
    assert shortcut["lanes"]["core_analysis"]["status"] == "unavailable"
    assert shortcut["status"] != "passed"
    assert differential["status"] == "unavailable"
    assert diagnostics["status"] == "failed"
    assert diagnostics["first_mismatch"]["path"] == "analysis.bulk.ACME.baseline_z"
