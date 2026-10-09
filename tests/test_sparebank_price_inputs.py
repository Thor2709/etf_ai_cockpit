from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.analysis.sparebank import analyse_sparebank_ec
from etf_cockpit.application.financial_institution_views import _valuation_currency, _with_local_marketability


FIXTURES = Path(__file__).parent / "fixtures" / "sparebank"


def _teaching_bank() -> dict[str, object]:
    return json.loads((FIXTURES / "teaching_bank.json").read_text(encoding="utf-8"))


def test_marketability_rates_from_price_volume_parquet(tmp_path: Path) -> None:
    price_path = tmp_path / "data" / "clean" / "prices.parquet"
    price_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"date": "2025-01-01", "etf_id": "TEACHING-EC", "open": 99, "high": 101, "low": 98, "close": 100, "adjusted_close": 100, "volume": 1000, "currency": "NOK", "provider_symbol": "TEACHING-EC.OL", "source": "fixture", "is_adjusted": True, "dividends": 0, "stock_splits": 0, "capital_gains": 0},
            {"date": "2025-01-02", "etf_id": "TEACHING-EC", "open": 99, "high": 101, "low": 98, "close": 100, "adjusted_close": 100, "volume": 3000, "currency": "NOK", "provider_symbol": "TEACHING-EC.OL", "source": "fixture", "is_adjusted": True, "dividends": 0, "stock_splits": 0, "capital_gains": 0},
            {"date": "2025-01-03", "etf_id": "TEACHING-EC", "open": 99, "high": 101, "low": 98, "close": 100, "adjusted_close": 100, "volume": 99000, "currency": "NOK", "provider_symbol": "TEACHING-EC.OL", "source": "fixture", "is_adjusted": True, "dividends": 0, "stock_splits": 0, "capital_gains": 0},
            {"date": "2025-01-02", "etf_id": "OTHER-EC", "open": 99, "high": 101, "low": 98, "close": 100, "adjusted_close": 100, "volume": 99000, "currency": "NOK", "provider_symbol": "OTHER-EC.OL", "source": "fixture", "is_adjusted": True, "dividends": 0, "stock_splits": 0, "capital_gains": 0},
        ]
    ).to_parquet(price_path, index=False)
    assumptions = _with_local_marketability(
        tmp_path,
        "TEACHING-EC",
        pd.Timestamp("2025-01-02T23:59:59Z"),
        pd.read_parquet(price_path),
        {"marketability": {"order_quantity": 600}},
    )

    result = analyse_sparebank_ec(
        _teaching_bank(),
        decision_time="2025-01-02T23:59:59Z",
        price=100,
        valuation_assumptions=assumptions,
    )
    inputs = {row["id"]: row for row in result.scorecard.axes["marketability_implementation"]["inputs"]}

    assert assumptions["marketability"]["median_volume_60d"] == pytest.approx(2000)
    assert assumptions["marketability"]["days_to_trade"] == pytest.approx(3)
    assert inputs["median_volume_60d"]["status"] == "rated"
    assert inputs["days_to_trade"]["status"] == "rated"


def test_valuation_rates_book_multiple_from_filing_pool_facts_and_price() -> None:
    evidence = _teaching_bank()
    facts = evidence["facts"]
    facts.pop("owner_attributable_book")
    facts.pop("period_end_ec_count")
    facts.pop("outstanding_ec_count")
    facts["ec_capital"]["value"] = 40
    facts["overkursfond"] = {"available": True, "value": 60, "unit": "NOK", "period": "2024-12-31", "source_locator": "annual report"}
    facts["utjevningsfond"] = {"available": True, "value": 300, "unit": "NOK", "period": "2024-12-31", "source_locator": "annual report"}
    facts["registered_ec_count"] = {"available": True, "value": 4, "unit": "EC", "period": "2024-12-31", "source_locator": "annual report"}

    result = analyse_sparebank_ec(evidence, decision_time="2025-01-02T00:00:00Z", price=100)
    standalone = result.valuation["standalone"]
    inputs = {row["id"]: row for row in result.scorecard.axes["owner_valuation_expectations"]["inputs"]}

    assert standalone["owner_book_per_ec"] == pytest.approx(100)
    assert standalone["owner_pb"] == pytest.approx(1)
    assert standalone["owner_pe"] == pytest.approx(100 / 12)
    assert standalone["count_sources"]["book"] == "owner_pool_total"
    assert standalone["count_sources"]["book_count"] == "registered_ec_count"
    assert inputs["owner_pb"]["status"] == "rated"
    assert inputs["owner_pb"]["value"] == pytest.approx(1)
    assert inputs["owner_pe"]["status"] == "rated"


def test_filing_amount_unit_supplies_price_currency_when_assumptions_are_absent() -> None:
    assert _valuation_currency(None, None, {"ec_capital": {"available": True, "unit": "NOK"}}) == "NOK"
