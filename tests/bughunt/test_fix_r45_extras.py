from __future__ import annotations

import json

import pandas as pd
import pytest

from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.sec_facts import parse_companyfacts
from etf_cockpit.portfolio.valuation import SNAPSHOT_COLUMNS


def test_r45_sec_dimensioned_facts_are_not_canonical_totals(tmp_path):
    entry = {
        "val": 60,
        "start": "2025-01-01",
        "end": "2025-12-31",
        "filed": "2026-02-01",
        "form": "10-K",
        "accn": "0000000000-26-000001",
        "dimensions": {"StatementBusinessSegmentsAxis": "Cloud"},
    }
    path = tmp_path / "facts.json"
    path.write_text(json.dumps({"cik": 1, "facts": {"us-gaap": {"Revenue": {"units": {"USD": [entry]}}}}}))

    result = parse_companyfacts(
        path,
        CanonicalIdentity("X", "Example", None, "needs_verification", "X", "NYSE", "USD", "stock", {}, "high", (), "1"),
    )

    assert result.success
    assert len(result.records) == 1
    assert result.records[0].dimensions == '{"StatementBusinessSegmentsAxis":"Cloud"}'
    assert result.records[0].canonical_metric is None
    assert result.records[0].manual_review_required


def _snapshots(days: list[str], values: list[float]) -> pd.DataFrame:
    rows = []
    for index, (day, value) in enumerate(zip(days, values)):
        previous = values[index - 1] if index else None
        rows.append(
            dict(
                dict.fromkeys(SNAPSHOT_COLUMNS, 0.0),
                date=day,
                total_value=value,
                securities_value=value,
                invested_capital=100.0,
                period_return=float("nan") if previous is None else value / previous - 1.0,
                investment_pnl=float("nan") if previous is None else value - previous,
                valuation_status="available",
                flow_status="available",
                availability_evidence="timestamped",
                missing_reasons="",
                execution_allowed=False,
            )
        )
    return pd.DataFrame(rows)


def _fx_rates(days: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "as_of_date": day,
                "base_currency": "EUR",
                "quote_currency": "USD",
                "rate": value,
                "source": "ECB",
                "ingested_at": f"{day}T09:00:00Z",
            }
            for day, value in zip(days, values)
        ]
    )


def test_r45_fx_attribution_uses_pre_range_anchor_and_fails_closed_on_gaps():
    from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series

    snapshots = _snapshots(["2025-01-30", "2025-01-31", "2025-02-03", "2025-02-04"], [100.0] * 4)
    rates = _fx_rates(["2025-01-30", "2025-01-31", "2025-02-03", "2025-02-04"], [1.0, 1.1, 1.2, 1.3])
    kwargs = dict(
        metric="fx",
        date_range="custom",
        custom_start="2025-02-03",
        custom_end="2025-02-04",
        currency="USD",
        fx_rates=rates,
    )

    daily = build_portfolio_performance_series(snapshots, aggregation="day", **kwargs)
    monthly = build_portfolio_performance_series(snapshots, aggregation="month", **kwargs)

    assert daily.points[0].value == pytest.approx(10.0)
    assert monthly.points[0].value == pytest.approx(20.0)

    gapped = snapshots[snapshots["date"].ne("2025-01-31")]
    unavailable = build_portfolio_performance_series(gapped, aggregation="day", **kwargs)
    assert unavailable.points[0].value is None
    assert unavailable.points[0].status == "unavailable"
