"""Golden: ``build_stock_research_report`` full output for pinned statement inputs (copied from tests/test_stock_research.py)."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import ui_facade
from etf_cockpit.data import stock_research as stock_research_data
from etf_cockpit.data.stock_research import build_stock_research_report
from refactor_parity._harness import assert_matches_golden
from refactor_parity._serialise import jsonable

# Pinned decision/cutoff dates.  The report is a pure function of its inputs: no wall-clock read exists on this
# path (verified: stock_research.py has no date.today()/datetime.now()), so nothing needs freezing.
KNOWN_AT = "2026-12-31T00:00:00Z"
DECISION_TIME = "2027-01-02T00:00:00Z"
NOTES = (
    "Inputs are copies of the tests/test_stock_research.py fixtures (ACME three annual periods FY2024-FY2026). "
    "Scenarios: unclassified defaults; industrial with peers+market inputs+valuation scenarios+intangible assumptions; "
    "bank residual-income route with a projection stub; point-in-time cutoff before the FY2026 filing; the ui_facade "
    "context loader with stubbed projections. Floats compared rel=1e-9/abs=1e-12, everything else exact. "
    "Defaults chosen: dates above; strict_comparability left at the library default (True)."
)


def _statements() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = {
        2024: {"revenue": 100.0, "gross_profit": 35.0, "operating_income": 18.0, "net_income": 12.0, "assets": 120.0, "equity": 55.0, "debt": 35.0, "cash": 8.0, "cash_from_operations": 16.0, "current_assets": 45.0, "current_liabilities": 30.0, "receivables": 12.0, "interest_expense": 3.0, "exceptional_items": 1.0, "shares_outstanding": 10.0, "free_cash_flow": 14.0},
        2025: {"revenue": 110.0, "gross_profit": 40.0, "operating_income": 22.0, "net_income": 15.0, "assets": 125.0, "equity": 60.0, "debt": 32.0, "cash": 10.0, "cash_from_operations": 20.0, "current_assets": 50.0, "current_liabilities": 28.0, "receivables": 13.0, "interest_expense": 2.5, "exceptional_items": 0.5, "shares_outstanding": 10.0, "free_cash_flow": 18.0},
        2026: {"revenue": 120.0, "gross_profit": 48.0, "operating_income": 27.0, "net_income": 20.0, "assets": 130.0, "equity": 68.0, "debt": 30.0, "cash": 12.0, "cash_from_operations": 25.0, "current_assets": 56.0, "current_liabilities": 25.0, "receivables": 14.0, "interest_expense": 2.0, "exceptional_items": 0.2, "shares_outstanding": 10.0, "free_cash_flow": 23.0},
    }
    for year, metrics in values.items():
        for metric, value in metrics.items():
            rows.append(
                {
                    "instrument_id": "ACME",
                    "canonical_metric": metric,
                    "value": value,
                    "period_type": "annual",
                    "period_key": f"FY{year}",
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": "FY",
                    "source_id": f"filing-{year}",
                    "filed": f"{year + 1}-02-15",
                    "restatement_kind": "reported",
                }
            )
    return pd.DataFrame(rows)


def _with_intangibles(frame: pd.DataFrame) -> pd.DataFrame:
    additions = []
    for year, research, advertising, ebitda in ((2024, 10.0, 4.0, 22.0), (2025, 12.0, 5.0, 27.0), (2026, 14.0, 6.0, 33.0)):
        template = frame[frame["fiscal_year"] == year].iloc[0].to_dict()
        for metric, value in (("research_and_development", research), ("advertising_expense", advertising), ("ebitda", ebitda)):
            additions.append({**template, "canonical_metric": metric, "value": value})
    return pd.concat([frame, pd.DataFrame(additions)], ignore_index=True)


def _bank_projection() -> SimpleNamespace:
    def metric(name: str, value: float) -> SimpleNamespace:
        return SimpleNamespace(
            metric=name, status="available", value=value, unit="currency", period="2026-12-31", reporting_standard="IFRS",
            jurisdiction="NO", business_model="bank", scope="consolidated", source_id="filing-2026", source_authority="official",
            as_of="2026-12-31T00:00:00Z", known_at="2027-02-15T00:00:00Z", execution_allowed=False,
        )

    return SimpleNamespace(
        status="available",
        instrument_id="ACME",
        execution_allowed=False,
        lineage={"decision_time": "2027-02-15T00:00:00Z", "sources": ("filing-2026",)},
        metrics=(metric("net_profit_attributable", 20.0), metric("closing_equity", 68.0), metric("tangible_book_value", 42.0)),
    )


def _scenario_unclassified() -> dict[str, object]:
    return build_stock_research_report(_statements(), instrument_id="ACME")


def _scenario_industrial_full() -> dict[str, object]:
    stamped = _with_intangibles(_statements()).assign(currency="EUR", consolidation_scope="consolidated", known_at=KNOWN_AT)
    peers = pd.concat(
        [
            _statements().assign(instrument_id="PEER-1", value=lambda frame: frame["value"] * 1.2),
            _statements().assign(instrument_id="PEER-2", value=lambda frame: frame["value"] * 0.9),
        ],
        ignore_index=True,
    ).assign(currency="EUR", consolidation_scope="consolidated", known_at=KNOWN_AT)
    return build_stock_research_report(
        stamped,
        instrument_id="ACME",
        sector="industrial",
        peer_frame=peers,
        peer_market_inputs={
            "PEER-1": {"market_cap": 360.0, "enterprise_value": 380.0, "share_price": 36.0, "currency": "EUR"},
            "PEER-2": {"market_cap": 270.0, "enterprise_value": 285.0, "share_price": 27.0, "currency": "EUR"},
        },
        classification_context={
            "status": "available",
            "sector": "industrial",
            "industry": "manufacturing",
            "reporting_currency": "EUR",
            "accounting_standard": "IFRS",
            "effective_at": KNOWN_AT,
            "decision_time": DECISION_TIME,
        },
        peer_context={"status": "available", "cohort": {"members": ["PEER-1", "PEER-2"]}},
        market_inputs={
            "market_cap": 300.0, "enterprise_value": 318.0, "share_price": 30.0, "dividend_per_share": 0.6, "currency": "EUR",
            "shares_outstanding": 10.0, "net_debt": 18.0, "reporting_currency": "EUR", "share_count_period_end": "2026-12-31", "net_debt_period_end": "2026-12-31",
        },
        assumptions={
            "forecast_years": 5,
            "discount_rate": 0.10,
            "terminal_growth": 0.02,
            "tax_rate": 0.25,
            "cost_of_capital": 0.10,
            "intangible_adjustment": {"enabled": True, "research_years": 3, "advertising_years": 2, "research_capitalisation_rate": 1.0, "advertising_capitalisation_rate": 0.5},
            "scenarios": {
                "bear": {"growth": 0.01, "margin": 0.18},
                "base": {"growth": 0.05, "margin": 0.225},
                "bull": {"growth": 0.08, "margin": 0.27},
            },
        },
        as_known_at=DECISION_TIME,
    )


def _scenario_bank_residual_income() -> dict[str, object]:
    frame = _statements()
    template = frame.loc[(frame["canonical_metric"] == "equity") & (frame["fiscal_year"] == 2026)].iloc[0].to_dict()
    template.update({"currency": "EUR", "consolidation_scope": "consolidated"})
    frame = pd.concat([frame, pd.DataFrame([{**template, "canonical_metric": "tangible_book_value", "value": 42.0}])], ignore_index=True)
    frame = frame.loc[~frame["canonical_metric"].isin(["equity", "net_income"])].copy()
    return build_stock_research_report(
        frame,
        instrument_id="ACME",
        sector="bank",
        market_inputs={"market_cap": 300.0, "shares_outstanding": 10.0, "net_debt": 18.0, "reporting_currency": "EUR", "share_count_period_end": "2026-12-31"},
        assumptions={"forecast_years": 5, "cost_of_equity": 0.10, "terminal_growth": 0.02, "sustainable_roe": 0.12},
        financial_projection=_bank_projection(),
    )


def _scenario_point_in_time_cutoff() -> dict[str, object]:
    # FY2026 was filed 2027-02-15; a cutoff of 2026-06-30 may only see FY2024 (filed 2025-02-15) and FY2025 (2026-02-15).
    stamped = _statements().assign(
        currency="EUR", consolidation_scope="consolidated", known_at=lambda frame: frame["filed"].map(lambda value: f"{value}T00:00:00Z")
    )
    return build_stock_research_report(
        stamped,
        instrument_id="ACME",
        sector="industrial",
        market_inputs={
            "market_cap": 300.0, "currency": "EUR", "shares_outstanding": 10.0, "net_debt": 18.0,
            "reporting_currency": "EUR", "share_count_period_end": "2025-12-31", "net_debt_period_end": "2025-12-31",
        },
        assumptions={},
        as_known_at="2026-06-30",
    )


def _scenario_facade_context(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    target = _statements().assign(instrument_id="ACME", currency="EUR", consolidation_scope="consolidated", known_at=KNOWN_AT)
    peer = _statements().assign(instrument_id="PEER-1", value=lambda frame: frame["value"] * 1.2, currency="EUR", consolidation_scope="consolidated", known_at=KNOWN_AT)
    facts = pd.concat([target, peer], ignore_index=True)
    classification = {
        "status": "available",
        "classification": {
            "instrument_id": "ACME", "sector": "industrial", "industry": "manufacturing", "reporting_currency": "EUR",
            "accounting_standard": "IFRS", "effective_at": KNOWN_AT, "decision_time": DECISION_TIME,
        },
        "execution_allowed": False,
    }
    peers = {"status": "available", "instrument_id": "ACME", "decision_time": DECISION_TIME, "cohort": {"members": ["PEER-1"]}, "execution_allowed": False}
    # load_stock_research_context looks the two projection loaders up in ITS OWN module globals: ui_facade before the
    # refactor, the module that now defines the function after it.  Patch there (a patch on a re-export is a no-op).
    context_module = importlib.import_module(ui_facade.load_stock_research_context.__module__)
    monkeypatch.setattr(context_module, "load_classification_projection", lambda instrument_id: classification)
    monkeypatch.setattr(context_module, "load_peer_cohort_projection", lambda instrument_id, decision_time=None: peers)
    monkeypatch.setattr(stock_research_data, "load_stock_research_frame", lambda path, instrument_id=None, as_known_at=None: facts.copy())
    context = ui_facade.load_stock_research_context("ACME", statements_path=ui_facade.STATEMENT_FACTS_PATH, decision_time=DECISION_TIME)
    report = build_stock_research_report(
        context["statements"],
        instrument_id="ACME",
        sector=context["sector"],
        peer_frame=context["peer_frame"],
        classification_context=context["classification"],
        peer_context=context["peer_context"],
        as_known_at=DECISION_TIME,
    )
    return {
        "context_keys": sorted(context),
        "context_without_frames": {key: jsonable(value) for key, value in context.items() if not isinstance(value, pd.DataFrame)},
        "statement_rows": len(context["statements"]),
        "peer_rows": len(context["peer_frame"]),
        "report": report,
    }


@pytest.fixture(scope="module")
def reports(request: pytest.FixtureRequest) -> dict[str, object]:
    patcher = pytest.MonkeyPatch()
    request.addfinalizer(patcher.undo)
    return {
        "unclassified_defaults": _scenario_unclassified(),
        "industrial_full": _scenario_industrial_full(),
        "bank_residual_income": _scenario_bank_residual_income(),
        "point_in_time_cutoff": _scenario_point_in_time_cutoff(),
        "facade_context": _scenario_facade_context(patcher),
    }


def test_stock_research_reports_match_golden(reports: dict[str, object]) -> None:
    payload = {name: jsonable(report) for name, report in reports.items()}
    assert_matches_golden("stock_research", {"scenarios": payload}, notes=NOTES)


def test_stock_research_goldens_are_not_vacuous(reports: dict[str, object]) -> None:
    # Guard against pinning an all-"unavailable" output: at least the industrial scenario must carry real values.
    industrial = reports["industrial_full"]
    assert isinstance(industrial, dict)
    assert industrial["profitability"]["metrics"]["gross_margin"]["value"] == pytest.approx(0.4)
    assert industrial["valuation"]["relative_metrics"]["price_to_earnings"]["value"] == pytest.approx(300.0 / 20.0)
    assert industrial["execution_allowed"] is False
