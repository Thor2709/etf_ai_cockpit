from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.components.fixed_income_views import (
    build_fixed_income_bond_view_model,
    fixed_income_bond_panel,
)
from etf_cockpit.data.event_calendar import EVENT_COLUMNS
from etf_cockpit.application import portfolio_views, ui_facade
from etf_cockpit.portfolio.calendar import build_portfolio_calendar
from etf_cockpit.portfolio.maturity_ladder import build_portfolio_maturity_ladder


DECISION_TIME = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _terms_projection(
    *,
    instrument_id: str = "BOND-1",
    status: str = "available",
    reason_codes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "reason_codes": reason_codes or [],
        "terms": {
            "instrument_id": instrument_id,
            "issuer_id": "ISSUER-1",
            "security_type": "corporate_bond",
            "currency": "EUR",
            "maturity_date": "2027-01-01",
            "face_value": "100",
            "coupon_type": "fixed_rate",
            "coupon_rate": "0.05",
            "coupon_frequency": 1,
            "country": "DE",
            "confidence": "high",
            "source_id": "offering-document",
            "source_document": "terms.pdf",
            "known_at": "2026-09-30T10:00:00+00:00",
            "retrieved_at": "2026-09-30T10:05:00+00:00",
            "version_id": "terms-version-1",
        },
        "optionality_schedule": {"features": []},
        "coupon_schedule": [
            {
                "payment_date": "2026-12-31",
                "amount": "5",
                "currency": "EUR",
                "source_id": "offering-document",
                "source_version_id": "terms-version-1",
            }
        ],
        "redemption_schedule": [
            {
                "payment_date": "2027-01-01",
                "amount": "100",
                "currency": "EUR",
                "source_id": "offering-document",
                "source_version_id": "terms-version-1",
            }
        ],
    }


def test_bond_detail_ui_projection_values_match_api_export_projection() -> None:
    terms = _terms_projection()
    market = {"status": "available", "observations": [{"as_of": "2026-09-30"}]}
    analytics = {
        "status": "available",
        "clean_price": "99.5",
        "dirty_price": "100.0",
        "accrued_interest": "0.5",
        "current_yield": "0.05",
        "yield_to_maturity": "0.045",
        "yield_to_worst": "0.04",
        "dv01": "0.04",
    }
    risk = {"status": "available", "dv01": "0.04"}

    view = build_fixed_income_bond_view_model(
        "BOND-1",
        terms_projection=terms,
        market_data_projection=market,
        analytics_projection=analytics,
        risk_projection=risk,
    )

    assert view.projections == {
        "terms": terms,
        "market_data": market,
        "analytics": analytics,
        "risk": risk,
    }
    displayed = _control_text(fixed_income_bond_panel(view))
    assert "Canonical valuation and risk metrics:" in displayed
    for expected in (
        "clean_price=99.50",
        "dirty_price=100.00",
        "accrued_interest=0.50",
        "current_yield=5.0%",
        "yield_to_maturity=4.5%",
        "yield_to_worst=4.0%",
        "dv01=0.04",
        "status=available",
    ):
        assert expected in displayed
    assert "Principal/redemption schedule: date=2027-01-01; amount=100 EUR" in displayed


def test_bond_view_model_includes_coverage_and_source_as_of_dates() -> None:
    view = build_fixed_income_bond_view_model(
        "BOND-1",
        terms_projection=_terms_projection(),
        market_data_projection={"status": "available", "observations": [{"as_of": "2026-09-30"}]},
        analytics_projection={"status": "available"},
        risk_projection={"status": "unavailable", "reason_codes": ["risk_unavailable"]},
    )

    assert view.coverage["terms"] == "available"
    assert view.coverage["coupon_schedule"] == "available"
    assert view.coverage["risk"] == "unavailable"
    assert view.source_as_of_dates["terms"] == (
        "2026-09-30T10:00:00+00:00",
        "2026-09-30T10:05:00+00:00",
    )
    assert view.source_as_of_dates["market_data.observations"] == ("2026-09-30",)


def test_unsupported_bond_structure_carries_prominent_warning() -> None:
    terms = _terms_projection(status="quarantined", reason_codes=["unsupported_structure"])
    terms["optionality_schedule"] = {"features": ["convertible"]}
    view = build_fixed_income_bond_view_model(
        "BOND-1",
        terms_projection=terms,
        market_data_projection=None,
        analytics_projection=None,
        risk_projection=None,
    )

    assert any(
        warning.startswith("UNSUPPORTED FIXED-INCOME STRUCTURE:") and "convertible" in warning
        for warning in view.warnings
    )
    assert "UNSUPPORTED FIXED-INCOME STRUCTURE:" in _control_text(fixed_income_bond_panel(view))


def test_maturity_ladder_reconciles_cash_flows_to_position_quantity_and_terms() -> None:
    terms = _terms_projection()
    holdings = [{"instrument_id": "BOND-1", "asset_type": "bond", "quantity": "3", "market_value_eur": "298.5"}]
    calendar = build_portfolio_calendar(
        pd.DataFrame(holdings),
        decision_time=DECISION_TIME,
        event_rows=pd.DataFrame(columns=EVENT_COLUMNS),
        fixed_income_terms={"BOND-1": terms},
        fx_rates=pd.DataFrame(),
    )

    ladder = build_portfolio_maturity_ladder(
        calendar,
        holdings=holdings,
        terms_projections={"BOND-1": terms},
    )
    amounts = {(row["flow_type"], row["currency"]): row["amount"] for row in ladder["totals"]}

    assert ladder["positions"][0]["quantity"] == Decimal("3")
    assert ladder["positions"][0]["maturity_date"] == terms["terms"]["maturity_date"]
    assert amounts[("income", "EUR")] == Decimal("15")
    assert amounts[("maturity_proceeds", "EUR")] == Decimal("300")
    assert amounts[("maturity_proceeds", "EUR")] == Decimal(terms["redemption_schedule"][0]["amount"]) * Decimal("3")

    second_terms = _terms_projection(instrument_id="BOND-2")
    incomplete = build_portfolio_maturity_ladder(
        calendar,
        holdings=[
            *holdings,
            {"instrument_id": "BOND-2", "asset_type": "bond", "quantity": "2", "market_value_eur": "200"},
        ],
        terms_projections={"BOND-1": terms, "BOND-2": second_terms},
    )
    second_position = next(row for row in incomplete["positions"] if row["instrument_id"] == "BOND-2")
    assert "contractual_cash_flows_unavailable" in second_position["reason_codes"]
    assert incomplete["coverage"]["missing_flow_instrument_ids"] == ["BOND-2"]
    assert incomplete["status"] == "partial"
    assert incomplete["totals"]
    assert all(row["amount"] is None for row in incomplete["totals"])
    assert all(row["status"] == "unavailable" for row in incomplete["totals"])
    assert all("contractual_cash_flows_unavailable" in row["reason_codes"] for row in incomplete["totals"])


def test_facade_ladder_loader_uses_the_snapshot_decision_cutoff(monkeypatch) -> None:
    cutoff = DECISION_TIME.isoformat()
    terms = _terms_projection()
    holdings = pd.DataFrame(
        [{"instrument_id": "BOND-1", "asset_type": "bond", "quantity": "3"}]
    )
    snapshot = SimpleNamespace(holdings=holdings)
    analysis = SimpleNamespace(snapshot_binding=SimpleNamespace(holdings_view="combined"))
    calendar = {
        "status": "available",
        "decision_time": cutoff,
        "currency": "EUR",
        "coverage": {"fixed_income_terms": {"status": "available"}},
        "cash_flows": [
            {
                "instrument_id": "BOND-1",
                "flow_type": "maturity_proceeds",
                "payment_date": "2027-01-01",
                "amount": Decimal("300"),
                "currency": "EUR",
                "source_id": "offering-document",
                "source_version_id": "terms-version-1",
            }
        ],
    }
    loaded_terms: list[dict[str, object]] = []
    monkeypatch.setattr(portfolio_views, "select_holdings_view", lambda rows, _view: rows)
    monkeypatch.setattr(
        portfolio_views,
        "load_portfolio_calendar_projection",
        lambda *_args, **_kwargs: calendar,
    )

    def load_terms(_instrument_id: str, **kwargs: object) -> dict[str, object]:
        loaded_terms.append(dict(kwargs))
        return terms

    monkeypatch.setattr(portfolio_views, "load_fixed_income_terms_projection", load_terms)
    projection = ui_facade.load_portfolio_maturity_ladder_projection(snapshot, analysis)

    assert loaded_terms == [{"storage_root": ui_facade.ROOT, "effective_at": cutoff, "decision_time": cutoff}]
    assert projection["decision_time"] == cutoff
    assert projection["totals"][0]["amount"] == Decimal("300")


def _control_text(control: object) -> str:
    values = [str(value) for value in (getattr(control, "value", None),) if isinstance(value, str)]
    content = getattr(control, "content", None)
    if content is not None:
        values.append(_control_text(content))
    children = getattr(control, "controls", None)
    if isinstance(children, (list, tuple)):
        values.extend(_control_text(child) for child in children)
    return " ".join(values)
