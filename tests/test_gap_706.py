from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import etf_cockpit.application.etf_economics_view as economics_view
from etf_cockpit.data.etf_economics import (
    EtfEconomicsReport,
    calculate_etf_economics,
    load_etf_e1_fields,
)


INSTRUMENT_ID = "fixture-share-class"
BENCHMARK_ID = "fixture-benchmark"
DECISION_TIME = "2026-01-08"


def _evidence_row(**fields: object) -> dict[str, object]:
    return {
        "instrument_id": INSTRUMENT_ID,
        "as_of": "2026-01-07",
        "known_at": "2026-01-08",
        "source_id": "fixture-source",
        **fields,
    }


def _empty_e1_fields() -> dict[str, dict[str, object]]:
    return {
        name: {"value": None, "reason": f"{name}_missing_all_sources"}
        for name in ("ter", "aum", "distribution_policy", "country_split", "sector_split")
    }


def _disable_holdings_and_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(economics_view, "load_etf_reference_context", lambda _name: pd.DataFrame())
    monkeypatch.setattr(
        economics_view,
        "load_etf_holdings_evidence",
        lambda *_args: pd.DataFrame(),
    )


def test_fund_or_other_class_fees_do_not_become_requested_class_fees() -> None:
    fund = _evidence_row(scope="fund", ter=0.001, fee_unit="decimal_fraction")
    other_class = _evidence_row(
        scope="share_class",
        share_class_id="fixture-other-class",
        ter=0.002,
        fee_unit="decimal_fraction",
    )

    fields = load_etf_e1_fields(
        INSTRUMENT_ID,
        decision_time=DECISION_TIME,
        issuer_records=[fund, other_class],
    )

    assert fields["ter"]["value"] is None
    assert fields["ter"]["reason"] == "ter_share_class_mapping_unavailable"
    assert fields["ter"]["source"] is None


def test_exact_share_class_evidence_keeps_identity_and_dates() -> None:
    share_class = _evidence_row(
        scope="share_class",
        share_class_id=INSTRUMENT_ID,
        currency="EUR",
        benchmark_id=BENCHMARK_ID,
        ter=0.002,
        fee_unit="decimal_fraction",
    )

    ter = load_etf_e1_fields(
        INSTRUMENT_ID,
        decision_time=DECISION_TIME,
        issuer_records=[share_class],
        include_traceability=True,
    )["ter"]

    assert ter["value"] == 0.002
    assert ter["scope"] == "share_class"
    assert ter["share_class_id"] == INSTRUMENT_ID
    assert ter["benchmark_id"] == BENCHMARK_ID
    assert ter["currency"] == "EUR"
    assert ter["effective_at"] == "2026-01-07T00:00:00+00:00"
    assert ter["known_at"] == "2026-01-08T00:00:00+00:00"
    assert ter["freshness_status"] == "not_assessed"


@pytest.mark.parametrize(
    ("mismatch", "class_currency", "class_benchmark"),
    [
        ("currency", "GBP", BENCHMARK_ID),
        ("benchmark", "EUR", "fixture-other-benchmark"),
    ],
)
def test_class_currency_or_benchmark_mismatch_blocks_tracking(
    mismatch: str,
    class_currency: str,
    class_benchmark: str,
) -> None:
    records = [
        _evidence_row(
            scope="fund",
            currency="EUR",
            benchmark_id=BENCHMARK_ID,
            benchmark_currency="EUR",
            fee_unit="decimal_fraction",
        ),
        _evidence_row(
            scope="share_class",
            share_class_id=INSTRUMENT_ID,
            currency=class_currency,
            benchmark_id=class_benchmark,
            benchmark_currency="EUR",
            fee_unit="decimal_fraction",
        ),
    ]

    report = calculate_etf_economics(INSTRUMENT_ID, records, as_of=DECISION_TIME)

    assert report.tracking_status == "unavailable", mismatch
    assert report.tracking_difference is None
    assert "share_class_identity_mismatch" in report.missing_evidence


def test_panel_summary_exposes_tracking_traceability(monkeypatch: pytest.MonkeyPatch) -> None:
    report = EtfEconomicsReport(
        instrument_id=INSTRUMENT_ID,
        status="available",
        message="synthetic panel fixture",
        as_of=DECISION_TIME,
        benchmark_id=BENCHMARK_ID,
        benchmark_currency="EUR",
        benchmark_source_id="fixture-benchmark-source",
        benchmark_source_provenance="synthetic benchmark input",
        fund_source_id="fixture-fund-source",
        fund_source_provenance="synthetic fund input",
        currency="EUR",
        horizon_days=2,
        matched_start="2026-01-06T00:00:00Z",
        matched_end="2026-01-08T00:00:00Z",
        coverage="3/3 business_daily observations",
        coverage_ratio=1.0,
        matched_rows=3,
        tracking_difference=-0.002,
        tracking_error=0.003,
        tracking_status="available",
        tracking_evidence_label="calculated from matched canonical total-return evidence",
        fund_metrics={
            "scope": "fund",
            "instrument_id": INSTRUMENT_ID,
            "currency": "EUR",
            "benchmark_id": BENCHMARK_ID,
            "benchmark_currency": "EUR",
            "source_id": "fixture-fund-source",
            "source_provenance": "synthetic fund input",
            "aum": 100_000_000.0,
            "aum_unit": "currency_units",
            "aum_as_of": "2026-01-07",
            "evidence_known_at": "2026-01-08",
            "aum_status": "available",
            "flows": -100_000.0,
            "flows_unit": "currency_units",
            "flow_period_days": 30,
            "flows_as_of": "2026-01-07",
        },
        share_class_metrics={
            INSTRUMENT_ID: {
                "scope": "share_class",
                "instrument_id": INSTRUMENT_ID,
                "share_class_id": INSTRUMENT_ID,
                "currency": "EUR",
                "benchmark_id": BENCHMARK_ID,
                "benchmark_currency": "EUR",
                "ocf": 0.002,
                "fee_unit": "decimal_fraction",
                "source_id": "fixture-class-source",
                "effective_at": "2026-01-07",
                "known_at": "2026-01-08",
            }
        },
        closure_risk_proxy={
            "status": "unavailable",
            "label": "proxy/model; not an observed fact or probability",
            "method": "versioned age/AUM/flow proxy",
            "score": None,
            "factor_coverage": {"available": 2, "total": 3, "ratio": 2 / 3},
            "missing_factors": ("aum_stale",),
            "reason": "freshness unavailable",
        },
    )
    monkeypatch.setattr(economics_view, "calculate_etf_economics", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(economics_view, "load_etf_e1_fields", lambda *_args, **_kwargs: _empty_e1_fields())
    _disable_holdings_and_metadata(monkeypatch)

    panel = economics_view.build_etf_economics_panel(
        SimpleNamespace(data_report=SimpleNamespace(as_of_date=DECISION_TIME)),
        INSTRUMENT_ID,
    )

    tracking = panel["e1"]["tracking_difference"]
    assert tracking["status"] == "available"
    assert tracking["calculation_method"] == "compounded matched canonical total-return growth"
    assert tracking["benchmark_id"] == BENCHMARK_ID
    assert tracking["frequency"] == "business_daily"
    assert tracking["sample_count"] == 3
    assert tracking["coverage_ratio"] == 1.0
    assert tracking["freshness_status"] == "not_assessed"
    assert panel["identity_audit"]["status"] == "available"
    assert panel["identity_audit"]["listing_identity_status"] == "unavailable"
    assert "sample count 3" in panel["summary"]
    assert "sqrt(252)" in panel["summary"]
    assert "fixture-fund-source / fixture-benchmark-source" in panel["summary"]
    assert "OCF 0.20%" in panel["summary"]
    assert "Fund-scope AUM 100000000.0" in panel["summary"]
    assert "Fund-scope flows -100000.0" in panel["summary"]
    assert "Economic-quality/closure proxy: status unavailable" in panel["summary"]
    assert "factor coverage 2/3" in panel["summary"]


def test_missing_evidence_stays_unavailable_in_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    _disable_holdings_and_metadata(monkeypatch)

    panel = economics_view.build_etf_economics_panel(
        SimpleNamespace(
            etf_economics_records=(),
            etf_fund_total_return=None,
            etf_benchmark_total_return=None,
            data_report=SimpleNamespace(as_of_date=DECISION_TIME),
            etf_metadata=pd.DataFrame(),
        ),
        INSTRUMENT_ID,
    )

    assert panel["status"] == "unavailable"
    assert panel["e1"]["ter"]["value"] is None
    assert panel["e1"]["tracking_difference"]["value"] is None
    assert panel["e1"]["tracking_difference"]["status"] == "unavailable"
    assert panel["identity_audit"]["status"] == "unavailable"
    assert "fund_economics" in panel["missing_evidence"]
