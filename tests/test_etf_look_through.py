from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.analysis.look_through import calculate_look_through
from etf_cockpit.application.ui_facade import load_etf_look_through


DECISION_TIME = "2026-07-15T16:00:00Z"
HOLDINGS_DATE = "2026-07-01"
APPLE_ISIN = "US0378331005"
MICROSOFT_ISIN = "US5949181045"
AMAZON_ISIN = "US0231351067"
FUND_ISIN = "IE00B4L5Y983"


def _holding(
    security: str,
    isin: str,
    weight: float,
    issuer: str,
    *,
    currency: str = "USD",
    exposure_type: str = "security",
) -> dict[str, object]:
    return {
        "security": security,
        "isin": isin,
        "weight": weight,
        "issuer": issuer,
        "company": issuer,
        "currency": currency,
        "exposure_type": exposure_type,
        "instrument_id": "TESTETF",
        "as_of": HOLDINGS_DATE,
        "source": "issuer",
        "source_id": "issuer:holdings-v1",
        "known_at": "2026-07-02T12:00:00Z",
        "revision": "revision-1",
    }


def _fundamental(
    identity: str,
    *,
    pe_ratio: float | None = None,
    roic: float | None = None,
    currency: str = "USD",
    available_at: str = "2026-07-10T10:00:00Z",
    as_of_date: str = "2026-06-30",
) -> dict[str, object]:
    return {
        "identity": identity,
        "pe_ratio": pe_ratio,
        "roic": roic,
        "currency": currency,
        "as_of_date": as_of_date,
        "available_at": available_at,
        "source_id": f"fundamental:{identity}",
    }


def _analyze(holdings: list[dict[str, object]], fundamentals: list[dict[str, object]] | None = None, **kwargs):
    return calculate_look_through(
        pd.DataFrame(holdings),
        instrument_id="TESTETF",
        decision_time=kwargs.pop("decision_time", DECISION_TIME),
        constituent_fundamentals=pd.DataFrame(fundamentals or []),
        **kwargs,
    )


def test_harmonic_pe_includes_negative_earnings_without_division_by_zero() -> None:
    summary = _analyze(
        [
            _holding("Positive Co", APPLE_ISIN, 0.8, "positive"),
            _holding("Loss Co", MICROSOFT_ISIN, 0.2, "loss"),
        ],
        [
            _fundamental("positive", pe_ratio=10.0),
            _fundamental("loss", pe_ratio=-20.0),
        ],
    )

    pe = summary.calculated_metrics["pe_ratio"]
    assert pe["status"] == "available"
    assert pe["value"] == pytest.approx(1 / (0.8 / 10 - 0.2 / 20))
    assert pe["negative_earnings_convention"].startswith("Negative P/E contributes")
    assert summary.fundamental_data_coverage["pe_ratio"]["coverage_fraction"] == 1.0

    cancelling = _analyze(
        [
            _holding("Positive Co", APPLE_ISIN, 0.5, "positive"),
            _holding("Loss Co", MICROSOFT_ISIN, 0.5, "loss"),
        ],
        [
            _fundamental("positive", pe_ratio=10.0),
            _fundamental("loss", pe_ratio=-10.0),
        ],
    )
    assert cancelling.calculated_metrics["pe_ratio"]["status"] == "unavailable"
    assert cancelling.calculated_metrics["pe_ratio"]["value"] is None
    assert any("zero or negative" in item for item in cancelling.limitations)


@pytest.mark.parametrize(
    ("weights", "status"),
    [([0.65, 0.4], "over_100"), ([0.4, 0.4], "under_100")],
)
def test_weight_reconciliation_and_total_limitations(weights: list[float], status: str) -> None:
    summary = _analyze(
        [
            _holding("Apple", APPLE_ISIN, weights[0], "apple"),
            _holding("Microsoft", MICROSOFT_ISIN, weights[1], "microsoft"),
        ]
    )

    assert summary.total_weight_status == status
    assert summary.mapped_weight + summary.cash_weight + summary.derivative_weight + summary.unresolved_weight == pytest.approx(
        summary.reported_total_weight, abs=1e-9
    )
    assert summary.reconciliation_delta == pytest.approx(0.0, abs=1e-9)
    if status == "over_100":
        assert summary.status == "invalid"
    else:
        assert summary.status == "partial"


def test_cash_derivative_and_unresolved_weights_remain_separate_and_conserved() -> None:
    rows = [
        _holding("Apple", APPLE_ISIN, 0.65, "apple"),
        _holding("USD cash", "", 0.1, "cash", exposure_type="cash"),
        _holding("Index future", MICROSOFT_ISIN, 0.15, "future", exposure_type="derivative"),
        _holding("Unidentified security", "", 0.1, "unknown"),
    ]
    summary = _analyze(rows)

    assert summary.mapped_weight == pytest.approx(0.65)
    assert summary.cash_weight == pytest.approx(0.1)
    assert summary.derivative_weight == pytest.approx(0.15)
    assert summary.unresolved_weight == pytest.approx(0.1)
    assert summary.mapped_weight + summary.cash_weight + summary.derivative_weight + summary.unresolved_weight == pytest.approx(1.0)


def test_slightly_over_100_percent_is_flagged_even_inside_normaliser_acceptance_band() -> None:
    summary = _analyze(
        [
            _holding("Apple", APPLE_ISIN, 0.605, "apple"),
            _holding("Microsoft", MICROSOFT_ISIN, 0.4, "microsoft"),
        ]
    )

    assert summary.total_weight_status == "over_100"
    assert summary.status == "overreported"
    assert summary.reported_total_weight == pytest.approx(1.005)
    assert summary.mapped_weight == pytest.approx(1.005)
    assert any("above 100%" in item for item in summary.limitations)


def test_duplicate_rows_and_multiple_listings_merge_to_one_economic_exposure() -> None:
    summary = _analyze(
        [
            _holding("Acme ordinary", APPLE_ISIN, 0.1, "acme"),
            _holding("Acme ordinary duplicate line", APPLE_ISIN, 0.1, "acme"),
            _holding("Acme ADR", MICROSOFT_ISIN, 0.2, "acme"),
            _holding("Other issuer", AMAZON_ISIN, 0.6, "other"),
        ]
    )

    top = summary.concentration["top_holdings"]
    acme = next(row for row in top if row["identity"] == "acme")
    assert acme["weight"] == pytest.approx(0.4)
    assert len(acme["listing_identities"]) == 2
    assert summary.exposures["issuer"]["acme"] == pytest.approx(0.4)


def test_missing_fundamentals_reduce_coverage_and_stale_holdings_are_flagged() -> None:
    partial = _analyze(
        [
            _holding("Apple", APPLE_ISIN, 0.5, "apple"),
            _holding("Microsoft", MICROSOFT_ISIN, 0.5, "microsoft"),
        ],
        [_fundamental("apple", pe_ratio=20.0, roic=0.1)],
    )
    stale_rows = [_holding("Apple", APPLE_ISIN, 1.0, "apple")]
    stale_rows[0]["as_of"] = "2025-01-01"
    stale_rows[0]["known_at"] = "2025-01-02T12:00:00Z"
    stale = _analyze(stale_rows, max_holdings_age_days=90, decision_time="2026-01-01T12:00:00Z")

    assert partial.fundamental_data_coverage["pe_ratio"]["covered_weight"] == pytest.approx(0.5)
    assert partial.fundamental_data_coverage["roic"]["coverage_fraction"] == pytest.approx(0.5)
    assert partial.status == "partial"
    assert stale.freshness == "stale"
    assert stale.status == "stale"
    assert any("older than the configured maximum age" in item for item in stale.limitations)


def test_provider_headline_metric_stays_provider_reported_when_constituents_are_missing() -> None:
    summary = _analyze(
        [_holding("Apple", APPLE_ISIN, 1.0, "apple")],
        [
            _fundamental("apple", pe_ratio=8.0, roic=0.5, available_at="2026-07-16T10:00:00Z"),
        ],
        provider_metrics={"pe_ratio": 18.5, "quality": 0.9},
    )

    assert summary.provider_reported_metrics["pe_ratio"] == {"label": "provider_reported", "value": 18.5}
    assert summary.calculated_metrics["pe_ratio"]["status"] == "unavailable"
    assert summary.calculated_metrics["pe_ratio"]["value"] is None
    assert summary.fundamental_data_coverage["pe_ratio"]["covered_weight"] == 0.0


def test_fund_of_funds_and_currency_mismatch_are_explicit_limitations() -> None:
    summary = _analyze(
        [
            _holding("Underlying company", APPLE_ISIN, 0.8, "company", currency="USD"),
            _holding("Other ETF", FUND_ISIN, 0.2, "other-fund", exposure_type="fund"),
        ],
        [_fundamental("company", pe_ratio=15.0, roic=0.12, currency="EUR")],
    )

    assert summary.fund_weight == pytest.approx(0.2)
    assert summary.unresolved_weight == pytest.approx(0.2)
    assert summary.mapped_weight == pytest.approx(0.8)
    assert any("Fund-of-funds" in item for item in summary.limitations)
    assert any("currency does not match" in item for item in summary.limitations)
    assert summary.fundamental_data_coverage["roic"]["covered_weight"] == 0.0


def test_application_facade_exposes_the_calculated_look_through_summary() -> None:
    result = load_etf_look_through(
        "TESTETF",
        decision_time=DECISION_TIME,
        holdings_frame=pd.DataFrame([_holding("Apple", APPLE_ISIN, 1.0, "Apple")]),
        fundamentals_frame=pd.DataFrame([_fundamental("apple", pe_ratio=20.0, roic=0.1)]),
    )

    assert result["status"] == "available"
    assert result["calculated_metrics"]["pe_ratio"]["value"] == pytest.approx(20.0)
    assert result["execution_allowed"] is False
