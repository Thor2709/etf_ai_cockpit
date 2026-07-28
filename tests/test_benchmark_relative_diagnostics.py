from __future__ import annotations

from dataclasses import replace
import math

import pytest

from etf_cockpit.portfolio.benchmark_relative_diagnostics import (
    AttributionEvidence,
    BenchmarkDiagnosticsError,
    ReturnObservation,
    build_benchmark_relative_report,
    verify_benchmark_relative_report,
)

START = "2025-01-01T00:00:00Z"
END = "2025-02-01T00:00:00Z"
EFFECTIVE = "2025-02-01T00:00:00Z"
KNOWN = "2025-02-02T00:00:00Z"
CUTOFF = "2025-02-05T00:00:00Z"


def _return(
    kind: str, subject: str, value: float, **changes: object
) -> ReturnObservation:
    values = {
        "metric": "total_return",
        "subject_kind": kind,
        "subject_id": subject,
        "currency": "EUR",
        "frequency": "daily",
        "horizon": "1m",
        "start_at": START,
        "end_at": END,
        "effective_at": EFFECTIVE,
        "known_at": KNOWN,
        "value": value,
        "source_authority": "portfolio-ledger",
        "source_id": f"{kind}-return",
        "source_checksum": ("a" if kind == "portfolio" else "b") * 64,
    }
    values.update(changes)
    return ReturnObservation(**values)  # type: ignore[arg-type]


def _evidence(
    dimension: str, bucket: str, contribution: float, **changes: object
) -> AttributionEvidence:
    values = {
        "metric": "relative_return_contribution",
        "dimension": dimension,
        "bucket": bucket,
        "portfolio_id": "P1",
        "benchmark_id": "B1",
        "currency": "EUR",
        "frequency": "daily",
        "horizon": "1m",
        "start_at": START,
        "end_at": END,
        "effective_at": EFFECTIVE,
        "known_at": KNOWN,
        "contribution": contribution,
        "source_authority": "attribution-engine",
        "source_id": f"{dimension}-{bucket}",
        "source_checksum": (hex(len(bucket) % 15 + 1)[2:]) * 64,
        "coverage": 1.0,
    }
    values.update(changes)
    return AttributionEvidence(**values)  # type: ignore[arg-type]


def _complete() -> list[AttributionEvidence]:
    return [
        _evidence("instrument", "ETF-A", 0.002),
        _evidence(
            "look_through", "Issuer-X", 0.001, lineage="indirect", parent_bucket="ETF-A"
        ),
        _evidence("sector_theme", "Technology", 0.001),
        _evidence("country", "US", 0.001),
        _evidence("currency_fx", "EURUSD", 0.001),
        _evidence("factor", "Momentum", 0.002),
        _evidence("residual", "unexplained", 0.002),
    ]


def _build(
    evidence: list[AttributionEvidence] | None = None,
    returns: list[ReturnObservation] | None = None,
):
    return build_benchmark_relative_report(
        portfolio_id="P1",
        benchmark_id="B1",
        cutoff_at=CUTOFF,
        returns=returns
        or [_return("portfolio", "P1", 0.04), _return("benchmark", "B1", 0.03)],
        evidence=_complete() if evidence is None else evidence,
    )


def test_adjusted_same_horizon_full_decomposition_reconciles() -> None:
    report = _build()
    assert report.status == "available"
    assert report.relative_return == pytest.approx(0.01)
    assert report.component_sum == pytest.approx(0.008)
    assert report.residual == pytest.approx(0.002)
    assert report.reconciliation_gap == pytest.approx(0.0)
    assert [item.dimension for item in report.dimensions] == [
        "instrument",
        "look_through",
        "sector_theme",
        "country",
        "currency_fx",
        "factor",
    ]
    assert report.execution_allowed is False
    assert verify_benchmark_relative_report(report)


def test_partial_look_through_conserves_unresolved_coverage_without_renormalising() -> (
    None
):
    rows = _complete()
    rows[1] = replace(
        rows[1], contribution=0.0005, coverage=0.75, unresolved_weight=0.25
    )
    rows[-1] = replace(rows[-1], contribution=0.0025)
    report = _build(rows)
    look_through = report.dimensions[1]
    assert report.status == "partial"
    assert look_through.coverage == 0.75
    assert look_through.unresolved_weight == 0.25
    assert look_through.contributions[0].contribution == 0.0005
    assert report.reconciliation_gap == pytest.approx(0.0)


def test_legitimate_zero_is_available() -> None:
    rows = _complete()
    rows[4] = replace(rows[4], contribution=0.0)
    rows[-1] = replace(rows[-1], contribution=0.003)
    report = _build(rows)
    assert report.dimensions[4].status == "available"
    assert report.dimensions[4].contributions[0].contribution == 0.0


@pytest.mark.parametrize(
    ("returns", "message"),
    [
        (
            [_return("portfolio", "WRONG", 0.04), _return("benchmark", "B1", 0.03)],
            "portfolio",
        ),
        (
            [
                _return("portfolio", "P1", 0.04),
                _return("benchmark", "B1", 0.03, horizon="3m"),
            ],
            "identical dated",
        ),
        (
            [
                _return("portfolio", "P1", 0.04),
                _return("benchmark", "B1", 0.03, frequency="weekly"),
            ],
            "identical dated",
        ),
    ],
)
def test_return_identity_horizon_and_frequency_are_strict(
    returns: list[ReturnObservation], message: str
) -> None:
    with pytest.raises(BenchmarkDiagnosticsError, match=message):
        _build(returns=returns)


def test_currency_mismatch_is_rejected_even_with_fx_evidence() -> None:
    returns = [
        _return("portfolio", "P1", 0.04),
        _return("benchmark", "B1", 0.03, currency="USD"),
    ]
    with pytest.raises(
        BenchmarkDiagnosticsError, match="same measurement currency"
    ):
        _build(_complete(), returns)


def test_effective_at_before_period_end_is_rejected() -> None:
    rows = _complete()
    rows[0] = replace(rows[0], effective_at="2025-01-31T00:00:00Z")
    with pytest.raises(BenchmarkDiagnosticsError, match="effective_at cannot precede"):
        _build(rows)


def test_known_at_before_effective_at_is_rejected() -> None:
    rows = _complete()
    rows[0] = replace(rows[0], known_at="2025-01-31T00:00:00Z")
    with pytest.raises(BenchmarkDiagnosticsError, match="known_at cannot precede"):
        _build(rows)


def test_cutoff_and_effective_period_precede_known_revision_order() -> None:
    old_late = _evidence(
        "factor",
        "Momentum",
        0.9,
        known_at="2025-02-04T00:00:00Z",
        revision=99,
        source_checksum="c" * 64,
    )
    new_early = _evidence(
        "factor",
        "Momentum",
        0.002,
        effective_at="2025-02-02T00:00:00Z",
        known_at="2025-02-03T00:00:00Z",
        revision=1,
    )
    future = replace(
        new_early,
        contribution=0.8,
        known_at="2025-02-06T00:00:00Z",
        revision=100,
        source_checksum="d" * 64,
    )
    rows = [row for row in _complete() if row.dimension != "factor"] + [
        old_late,
        new_early,
        future,
    ]
    report = _build(rows)
    assert report.dimensions[5].contributions[0].contribution == 0.002


def test_same_vintage_conflict_is_rejected() -> None:
    row = _evidence("factor", "Momentum", 0.002)
    conflict = replace(row, contribution=0.003, source_checksum="e" * 64)
    rows = [item for item in _complete() if item.dimension != "factor"] + [
        row,
        conflict,
    ]
    with pytest.raises(BenchmarkDiagnosticsError, match="conflicting evidence"):
        _build(rows)


@pytest.mark.parametrize(
    "row",
    [
        _evidence("factor", "X", 0.0, source_checksum="bad"),
        _evidence("factor", "X", 0.0, source_authority="../unsafe"),
    ],
)
def test_checksum_and_authority_are_rejected(row: AttributionEvidence) -> None:
    with pytest.raises(BenchmarkDiagnosticsError):
        _build([row])


def test_missing_dimension_and_missing_residual_stay_partial() -> None:
    rows = [row for row in _complete() if row.dimension not in {"country", "residual"}]
    report = _build(rows)
    assert report.status == "partial"
    assert report.dimensions[3].status == "unavailable"
    assert report.residual is None
    assert "explicit_residual_unavailable" in report.limitations


def test_reconciliation_gap_is_transparent_outside_tolerance() -> None:
    rows = _complete()
    rows[-1] = replace(rows[-1], contribution=0.001)
    report = _build(rows)
    assert report.status == "partial"
    assert report.reconciliation_gap == pytest.approx(0.001)
    assert "contributions_do_not_reconcile" in report.limitations


def test_order_and_hash_are_deterministic() -> None:
    first = _build(_complete())
    second = _build(list(reversed(_complete())))
    assert first.report_hash == second.report_hash
    assert first == second


def test_recomputed_hash_does_not_bypass_malformed_nested_payload() -> None:
    report = _build()
    malformed = replace(
        report, component_sum=report.component_sum + 0.1, report_hash=""
    )
    from etf_cockpit.portfolio.benchmark_relative_diagnostics import (
        canonical_report_hash,
    )

    malformed = replace(malformed, report_hash=canonical_report_hash(malformed))
    with pytest.raises(
        BenchmarkDiagnosticsError, match="reconciliation identity|component sum"
    ):
        verify_benchmark_relative_report(malformed)


@pytest.mark.parametrize("value", [True, math.nan, math.inf, -math.inf])
def test_bool_nan_and_inf_are_rejected(value: float) -> None:
    with pytest.raises(BenchmarkDiagnosticsError, match="finite non-boolean"):
        _build(
            returns=[
                _return("portfolio", "P1", value),
                _return("benchmark", "B1", 0.03),
            ]
        )


def test_nested_unsafe_authority_and_identity_are_rejected_even_with_new_hash() -> None:
    report = _build()
    contribution = report.dimensions[0].contributions[0]
    bad_dimension = replace(
        report.dimensions[0],
        contributions=(replace(contribution, source_authority="../root"),),
    )
    malformed = replace(
        report, dimensions=(bad_dimension, *report.dimensions[1:]), report_hash=""
    )
    from etf_cockpit.portfolio.benchmark_relative_diagnostics import (
        canonical_report_hash,
    )

    malformed = replace(malformed, report_hash=canonical_report_hash(malformed))
    with pytest.raises(BenchmarkDiagnosticsError, match="unsafe"):
        verify_benchmark_relative_report(malformed)

    source = dict(report.source_evidence[0])
    source["portfolio_id"] = "OTHER"
    malformed = replace(
        report, source_evidence=(source, *report.source_evidence[1:]), report_hash=""
    )
    malformed = replace(malformed, report_hash=canonical_report_hash(malformed))
    with pytest.raises(BenchmarkDiagnosticsError, match="identity mismatch"):
        verify_benchmark_relative_report(malformed)
