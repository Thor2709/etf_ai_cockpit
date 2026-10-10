"""Bug-hunt batch T-SB: one focused test per fixed id (docs/development/BUGFIX-PLAN-2026-10-10.md)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis import stock_universe as su
from etf_cockpit.analysis.sparebank.bank_economics import build_bank_economics, normalisation_bridge, owner_normalisation
from etf_cockpit.analysis.sparebank.book_calcs import justified_price_to_book
from etf_cockpit.analysis.sparebank.claim import build_claim_state
from etf_cockpit.analysis.sparebank.dividends import dividend_history
from etf_cockpit.analysis.sparebank.events import merger_bridge
from etf_cockpit.analysis.sparebank.valuation import implementation_shortfall, valuation
from etf_cockpit.application.financial_institution_views import _financial_rows_for_instrument
from etf_cockpit.application.sparebank_evidence import _filing_identity, statement_series, with_derived_owner_earnings
from etf_cockpit.application.sparebank_peers import quarterly_score_history
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data.esef_extensions import equity_member_facts
from etf_cockpit.data.stock_fundamentals import load_stock_config


def _statements() -> dict[str, object]:
    return {
        "period_end": "2024-12-31",
        "prior_period_end": "2023-12-31",
        "current": {
            "net_interest_income": 1100.0, "operating_expenses": 400.0, "impairment_losses": 10.0,
            "total_assets": 21000.0, "equity": 2200.0, "income_before_tax": 800.0, "income_tax": 200.0,
        },
        "prior": {"net_interest_income": 1000.0, "total_assets": 19000.0, "equity": 2000.0, "impairment_losses": 30.0},
    }


def _claim(**overrides: object):
    facts = {
        "ec_capital": {"available": True, "value": 100.0},
        "overkursfond": {"available": True, "value": 50.0},
        "utjevningsfond": {"available": True, "value": 250.0},
        "sparebankens_fond": {"available": True, "value": 600.0},
        "gavefond": {"available": True, "value": 0.0},
        "registered_ec_count": {"available": True, "value": 4.0},
        "ec_attributable_result": {"available": True, "value": 48.0},
    }
    facts.update(overrides)  # type: ignore[arg-type]
    return build_claim_state({"facts": facts, "known_at": "2025-03-01T00:00:00Z", "source_url": "synthetic"})


def test_chat_p03_n003() -> None:
    kwargs = {"gross_benefit": 100.0, "recurring_added_capability": 10.0, "lost_customer_contribution": 5.0}
    assert merger_bridge(10.0, integration_costs=(10, 20), tax_rate=0.25, **kwargs)["status"] != "unavailable"
    bad_cost = merger_bridge(10.0, integration_costs=(10, "invalid"), tax_rate=0.25, **kwargs)
    assert bad_cost["status"] == "unavailable" and bad_cost["reason_code"] == "INVALID_MERGER_INPUT"
    for tax in (1.5, -0.1):
        bad_tax = merger_bridge(10.0, integration_costs=(10,), tax_rate=tax, **kwargs)
        assert bad_tax["status"] == "unavailable" and bad_tax["reason_code"] == "INVALID_MERGER_INPUT"


def test_chat_p03_n005() -> None:
    result = implementation_shortfall(reference_price=100.0, filled_quantity=0.1, fill_price=110.0)
    assert result["shortfall_pct"] == pytest.approx(0.10)
    assert implementation_shortfall(reference_price=100.0, filled_quantity=0.0, fill_price=110.0)["status"] == "unavailable"


def test_chat_p03_n008() -> None:
    prices = pd.DataFrame({"_price_date": pd.to_datetime(["2025-03-01", "2026-03-01"]), "dividends": [1.0, 2.0]})
    assert dividend_history(prices, 100.0, keep_events=0)["events"] == []
    assert len(dividend_history(prices, 100.0, keep_events=1)["events"]) == 1


def test_p03_n006() -> None:
    assert justified_price_to_book(0.12, 0.09, -0.02) is None
    assert justified_price_to_book(0.12, 0.09, 0.03) == pytest.approx(1.5)


def test_p03_n007() -> None:
    ok = normalisation_bridge(100.0, [{"amount": 5.0}])
    assert ok.status == "resolved" and ok.normalised == pytest.approx(105.0)
    bad = normalisation_bridge(100.0, [{"amount": 5.0}, {"amount": "bad"}])
    assert bad.normalised is None and bad.status == "unavailable" and bad.reason_code == "INVALID_NORMALISATION_ADJUSTMENT"
    bad_pretax = normalisation_bridge(100.0, [], reported_pre_tax=130.0, pre_tax_adjustments=[1.0, "x"])
    assert bad_pretax.status == "unavailable" and bad_pretax.reason_code == "INVALID_NORMALISATION_ADJUSTMENT"


def test_k01() -> None:
    config = load_stock_config()
    prices = pd.DataFrame({"date": pd.to_datetime(["2026-10-01"]), "close": [15.0], "currency": ["GBP"]})
    decision = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    market = su.market_inputs(prices, {"quote_currency": "GBp"}, "GBP", decision, pd.DataFrame(columns=store.FX_COLUMNS), config)
    # The stored close is already in major units, so it must be labelled GBP (not GBp, which would divide by 100 again).
    assert market.price == 15.0 and market.price_currency == "GBP"


def test_k02a() -> None:
    result = owner_normalisation(build_bank_economics({"statements": _statements()}, bank_metrics=[]), _claim())
    assert result.normalised["status"] == "resolved" and result.normalised["normalised_roe"] is not None
    assert result.normalised["missing_components"] == ()
    assert result.normalised["not_adjusted"]


def test_k02b() -> None:
    result = valuation(_claim(), price=150.0, assumptions={"price_to_book": 1.5, "k": 0.10, "cost_of_equity": 0.12, "g": 0.03})
    assert result["status"] == "unavailable" and result["reason_code"] == "VALUATION_ASSUMPTIONS_INVALID"
    assert result["reverse"]["status"] == "unavailable"


def _statement_row(metric: str, value: object, sha: str, end: str = "2024-12-31") -> dict[str, object]:
    return {
        "canonical_metric": metric, "concept": metric, "value": value, "unit": "NOK", "currency": "NOK", "start": f"{end[:4]}-01-01",
        "end": end, "known_at": "2025-05-08T00:00:00Z", "effective_at": end, "filing_version": "v1", "sha256": sha, "dimensions": "",
    }


def _prepared(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = pd.DataFrame([{"instrument_id": "T", "source_id": f"fx:{index}", **row} for index, row in enumerate(rows)])
    return _financial_rows_for_instrument(frame, "T", pd.Timestamp("2025-06-01T00:00:00Z"))


def test_k02c() -> None:
    assert _filing_identity({"filing_version": "v1", "sha256": "a"}) != _filing_identity({"filing_version": "v1", "sha256": "b"})
    rows = [_statement_row("net_interest_income", 1100.0, "a"), _statement_row("operating_expenses", 400.0, "b")]
    series = statement_series(_prepared(rows), target_period="2024-12-31")
    assert "operating_expenses" not in series["current"] and "operating_expenses" in series["unavailable_reasons"]


def test_k02d() -> None:
    series = statement_series(_prepared([_statement_row("net_interest_income", "not-a-number", "a")]), target_period="2024-12-31")
    assert series["status"] == "unavailable" and "net_interest_income" in series["unavailable_reasons"]
    assert not series.get("current")
    facts = {"x": {"known_at": "2025-01-01T00:00:00Z"}}
    assert with_derived_owner_earnings(facts, series) == facts


def test_k02e() -> None:
    claim = _claim(ec_attributable_result={"available": False, "value": None})
    result = owner_normalisation(build_bank_economics({"statements": _statements()}, bank_metrics=[]), claim)
    normalised = result.normalised
    assert normalised["status"] == "unavailable" and normalised["reason_code"] == "SUSTAINABLE_ROE_BRIDGE_INPUTS_MISSING"
    assert "EC-attributable result" in normalised["missing_components"]
    assert result.reasons["normalised_roe_minus_cost_of_equity_pp"]


def test_k02f() -> None:
    frame = pd.DataFrame(
        {
            "instrument_id": ["T", "T"],
            "run_id": ["sparebank:fy25", "sparebank:fy24-rerun"],
            "final_combined_score_10": [7.0, 6.0],
            "effective_at": ["2025-12-31T00:00:00Z", "2024-12-31T00:00:00Z"],
            "run_completed_at": ["2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z"],
        }
    )
    quarters = [row["quarter"] for row in quarterly_score_history(frame, "T")]
    assert quarters == ["2024 Q4", "2025 Q4"]


def test_k03() -> None:
    def record(member: str, value: int) -> object:
        return SimpleNamespace(
            concept="Equity", value=str(value), is_numeric=True, period_end="2024-12-31", period_start=None, consolidation_scope="consolidated",
            context_dimensions=(("ifrs-full:ComponentsOfEquityAxis", member),), context_id=f"c-{member}", unit="NOK", source_location="r.xhtml",
        )

    facts = equity_member_facts([record("ifrs-full:IssuedCapitalMember", 258), record("ifrs-full:SharePremiumMember", 1505)], "2024-12-31")
    assert {name: item["value"] for name, item in facts.items()} == {"ec_capital": "258", "overkursfond": "1505"}
