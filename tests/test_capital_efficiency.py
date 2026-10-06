import pandas as pd

from etf_cockpit.data.capital_efficiency import capital_efficiency_analysis
from etf_cockpit.data.stock_research import build_stock_research_report
from test_stock_research import _statements


def test_capital_efficiency_consumes_audited_profitability_metrics() -> None:
    tax_rate = 0.25
    report = build_stock_research_report(
        _statements(),
        instrument_id="ACME",
        assumptions={"tax_rate": tax_rate},
        strict_comparability=False,
    )
    profitability_roic = report["profitability"]["metrics"]["roic"]["value"]
    capital = report["capital_efficiency"]
    reported = capital["reported"]

    assert capital["profitability_basis"]["status"] == "consumed"
    assert capital["profitability_basis"]["tax_rate"] == tax_rate
    assert reported["metrics"]["nopat"]["value"] == 27.0 * (1.0 - tax_rate)
    assert reported["metrics"]["roic"]["value"] == profitability_roic


def test_capital_efficiency_separates_goodwill_from_organic_capital() -> None:
    frame = _statements()
    template = frame[frame["fiscal_year"] == 2026].iloc[0].to_dict()
    additions = pd.DataFrame(
        [
            {**template, "canonical_metric": "goodwill", "value": 5.0},
            {**template, "canonical_metric": "acquired_intangibles", "value": 7.0},
        ]
    )

    report = capital_efficiency_analysis(
        pd.concat([frame, additions], ignore_index=True),
        instrument_id="ACME",
        tax_rate=0.25,
    )
    breakdown = report["reported"]["invested_capital_breakdown"]
    metrics = breakdown["metrics"]

    assert metrics["reported_invested_capital"]["value"] == 86.0
    assert metrics["goodwill"]["value"] == 5.0
    assert metrics["acquired_intangibles"]["value"] == 7.0
    assert metrics["invested_capital_excluding_goodwill"]["value"] == 81.0
    assert metrics["invested_capital_excluding_goodwill_and_acquired_intangibles"]["value"] == 74.0


def test_capital_efficiency_bank_delegation_suppresses_invested_capital() -> None:
    report = capital_efficiency_analysis(
        _statements(), instrument_id="ACME", sector="bank", tax_rate=0.25
    )
    reported = report["reported"]

    assert reported["metrics"]["invested_capital"]["value"] is None
    assert reported["metrics"]["invested_capital"]["status"] == "not_applicable"
    assert reported["invested_capital_breakdown"]["status"] == "not_applicable"


def test_capital_efficiency_rejects_currency_changes_across_periods() -> None:
    frame = _statements()
    frame["currency"] = "USD"
    frame["accounting_scope"] = "consolidated"
    frame.loc[frame["fiscal_year"] == 2025, "currency"] = "EUR"

    report = capital_efficiency_analysis(
        frame, instrument_id="ACME", tax_rate=0.25, strict_comparability=True
    )
    reported = report["reported"]

    assert reported["period_comparability"]["status"] == "unavailable"
    assert reported["period_comparability"]["reason"] == "currency_or_accounting_scope_changes_across_periods"
    assert reported["metrics"]["incremental_roic"]["status"] == "unavailable"


def _flow_and_balance_rows(balance_currency: str = "EUR") -> pd.DataFrame:
    values = dict(revenue=200, operating_income=20, equity=100, debt=30, cash=10)
    flow = {"revenue", "operating_income"}
    return pd.DataFrame(
        [
            dict(
                instrument_id="X", concept=k, canonical_metric=k, value=v, unit="EUR",
                currency="EUR" if k in flow else balance_currency, end="2025-12-31", fiscal_period="FY",
                start="2025-01-01" if k in flow else None,
                instant=None if k in flow else "2025-12-31", source_id=k, consolidation_scope="group",
            )
            for k, v in values.items()
        ]
    )


def test_flow_period_takes_balance_facts_at_its_period_end_and_checks_their_currency() -> None:
    result = capital_efficiency_analysis(_flow_and_balance_rows(), tax_rate=0.25, strict_comparability=True)
    history = result["reported"]["history"]
    assert len(history) == 1
    assert history[0]["invested_capital"] == 120.0
    assert history[0]["comparability"]["status"] == "available"
    assert "balance_period_keys" not in history[0]
    mismatch = capital_efficiency_analysis(_flow_and_balance_rows("USD"), tax_rate=0.25, strict_comparability=True)
    assert mismatch["reported"]["history"][0]["comparability"]["reason"] == "currency_mismatch_within_period"
    assert mismatch["reported"]["metrics"]["roic"]["value"] is None
