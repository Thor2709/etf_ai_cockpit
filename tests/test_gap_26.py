from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.application.overlap import build_direct_overlap_view, direct_overlap_payload
from etf_cockpit.features.overlap import calculate_direct_overlap


def _direct_holdings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"instrument_id": "ETF-A", "security": "Alpha plc", "isin": "GB0002634946", "weight": 0.60, "as_of": "2026-07-01", "source_id": "a1", "authority": "issuer", "completeness": "full", "sector": "Technology"},
            {"instrument_id": "ETF-A", "security": "Beta SA", "isin": "FR0000120271", "weight": 0.40, "as_of": "2026-07-01", "source_id": "a1", "authority": "issuer", "completeness": "full", "sector": "Financials"},
            {"instrument_id": "ETF-B", "security": "Alpha renamed", "isin": "GB0002634946", "weight": 0.25, "as_of": "2026-07-02", "source_id": "b1", "authority": "issuer", "completeness": "full", "sector": "Technology"},
            {"instrument_id": "ETF-B", "security": "Gamma AG", "isin": "DE0007164600", "weight": 0.75, "as_of": "2026-07-02", "source_id": "b1", "authority": "issuer", "completeness": "full", "sector": "Industrials"},
        ]
    )


def test_direct_overlap_uses_typed_identity_and_weighted_minimum() -> None:
    report = calculate_direct_overlap(
        _direct_holdings(),
        ["ETF-B", "ETF-A"],
        current_weights={"ETF-A": 0.4, "ETF-B": 0.6},
        today=date(2026, 7, 18),
    )

    assert report.status == "full"
    assert report.pairs[0].observed_overlap_weight == pytest.approx(0.25)
    assert report.pairs[0].current_overlap_weight == pytest.approx(0.25)
    assert report.pairs[0].top_holdings[0].identity == "isin:GB0002634946"
    assert report.execution_allowed is False


def test_partial_identity_coverage_stays_a_dated_lower_bound() -> None:
    rows = _direct_holdings()
    rows.loc[rows["instrument_id"].eq("ETF-B") & rows["security"].eq("Gamma AG"), "isin"] = ""

    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    pair = report.pairs[0]
    assert pair.status == "dated_lower_bound"
    assert pair.observed_overlap_weight == pytest.approx(0.25)
    assert pair.current_overlap_weight is None
    assert pair.right_coverage.resolved_weight == pytest.approx(0.25)
    assert pair.right_coverage.unresolved_weight == pytest.approx(0.75)


def test_nested_depth_limit_conserves_unexpanded_fund_weight_as_unknown() -> None:
    rows = pd.DataFrame(
        [
            {"instrument_id": "ROOT", "security": "Alpha", "isin": "GB0002634946", "weight": 0.3, "as_of": "2026-07-01", "source_id": "root", "authority": "issuer", "completeness": "full", "exposure_type": "security", "sector": "Technology"},
            {"instrument_id": "ROOT", "security": "Nested ETF", "identity_type": "fund", "identity_namespace": "canonical", "identity_value": "NESTED", "nested_instrument_id": "NESTED", "weight": 0.5, "as_of": "2026-07-01", "source_id": "root", "authority": "issuer", "completeness": "full", "exposure_type": "fund"},
            {"instrument_id": "ROOT", "security": "Cash", "weight": 0.1, "as_of": "2026-07-01", "source_id": "root", "authority": "issuer", "completeness": "full", "exposure_type": "cash", "currency": "EUR"},
            {"instrument_id": "ROOT", "security": "Future", "identity_type": "derivative", "identity_namespace": "issuer", "identity_value": "future-1", "weight": 0.1, "as_of": "2026-07-01", "source_id": "root", "authority": "issuer", "completeness": "full", "exposure_type": "derivative"},
        ]
    )

    report = calculate_direct_overlap(
        rows,
        ["ROOT"],
        current_weights={"ROOT": 1.0},
        today=date(2026, 7, 18),
        max_depth=1,
    )

    assert report.input_weight == pytest.approx(1.0)
    assert report.mapped_weight == pytest.approx(0.4)
    assert report.unknown_weight == pytest.approx(0.6)
    assert report.mapped_weight + report.unknown_weight == pytest.approx(report.input_weight)
    assert "depth" in " ".join(report.warnings).lower()


def test_missing_holdings_stay_unavailable_in_application_payload() -> None:
    report = build_direct_overlap_view(
        None,
        ["ETF-A", "ETF-B"],
        current_weights={"ETF-A": 0.6, "ETF-B": 0.4},
        holdings=pd.DataFrame(),
        known_at=datetime(2026, 7, 18, 23, 59, tzinfo=timezone.utc),
    )

    payload = direct_overlap_payload(report)
    pair = payload["pairs"][0]
    assert payload["status"] == "missing"
    assert pair["status"] == "missing"
    assert pair["observed_overlap_weight"] is None
    assert pair["current_overlap_weight"] is None
    assert report.mapped_weight == 0.0
    assert report.unknown_weight == pytest.approx(1.0)
    assert any("no holdings evidence" in warning.lower() for warning in payload["warnings"])
    assert payload["execution_allowed"] is False
