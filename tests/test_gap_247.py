from __future__ import annotations

from datetime import datetime, timezone

from etf_cockpit.analysis.etf_tax_context import (
    ETFContextAssumptions,
    build_etf_tax_context_panel,
)
from etf_cockpit.application import instrument_detail_view


def _resolved_domicile() -> dict[str, object]:
    return {
        "status": "resolved",
        "value": "Ireland",
        "source_id": "report:synthetic",
        "document_id": "report:synthetic",
        "document_date": "2026-06-30",
        "known_at": "2026-07-01T00:00:00Z",
        "page": 4,
        "checksum": "synthetic-checksum",
    }


def test_integrates_document_domicile_and_dated_distribution_sources() -> None:
    context = build_etf_tax_context_panel(
        {"fields": {"domicile": _resolved_domicile()}},
        {
            "e1": {
                "distribution_policy": {
                    "value": "distributing",
                    "source": "economics:synthetic",
                    "as_of": "2026-06-30",
                    "known_at": "2026-07-01T00:00:00Z",
                }
            },
            "share_class_metrics": {
                "ETF-TEST": {
                    "distribution_frequency": "quarterly",
                    "distribution_amount": 1.25,
                    "source_id": "economics:synthetic",
                    "as_of": "2026-06-30",
                    "known_at": "2026-07-01T00:00:00Z",
                }
            },
        },
        trading_currency="EUR",
        share_class_id="ETF-TEST",
        assumptions=ETFContextAssumptions(),
    )

    assert context["domicile"]["value"] == "Ireland"
    assert context["domicile"]["source"] == "report:synthetic"
    assert context["distribution"]["policy"]["value"] == "distributing"
    assert context["distribution"]["frequency"]["value"] == "quarterly"
    assert context["distribution"]["share_class_id"] == "ETF-TEST"
    assert context["distribution"]["amount"]["status"] == "unavailable"
    assert "currency is unavailable" in context["distribution"]["amount"]["reason"]


def test_residence_tax_and_hedge_economics_stay_unavailable_without_inputs() -> None:
    as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assumptions = ETFContextAssumptions(
        tax_enabled=True,
        tax_residence_country="DE",
        source_withholding_rate=0.15,
        known_at=as_of,
        hedge_enabled=True,
        hedge_ratio=0.5,
        hedge_target_currency="EUR",
    )

    context = build_etf_tax_context_panel(
        None,
        None,
        trading_currency="GBP",
        assumptions=assumptions,
        decision_time=as_of,
    )

    assert context["source_withholding"]["status"] == "unavailable"
    assert context["source_withholding"]["net_return_rate"] is None
    assert context["residence_tax"]["status"] == "unavailable"
    assert "Residence-specific rates" in context["residence_tax"]["reason"]
    assert context["hedge_assumption"]["status"] == "available"
    assert context["hedge_assumption"]["ratio"] == 0.5
    assert context["hedge_economics"]["status"] == "unavailable"
    assert context["hedge_economics"]["value"] is None

    future_context = build_etf_tax_context_panel(
        None,
        None,
        trading_currency="GBP",
        assumptions=ETFContextAssumptions(
            tax_enabled=True,
            source_withholding_rate=0.15,
            known_at=as_of.replace(day=2),
            hedge_enabled=True,
            hedge_ratio=0.5,
            hedge_target_currency="EUR",
        ),
        decision_time=as_of,
    )
    assert future_context["assumptions"]["status"] == "unavailable"
    assert future_context["hedge_assumption"]["ratio"] is None


def test_detail_panel_presents_context_and_its_unavailable_states(monkeypatch) -> None:
    monkeypatch.setattr(
        instrument_detail_view,
        "load_tax_hedge_assumptions",
        lambda _path: ETFContextAssumptions(),
    )
    economics = {"summary": "Existing economics."}

    context = instrument_detail_view._attach_etf_tax_context(
        economics,
        {"fields": {"domicile": _resolved_domicile()}},
        trading_currency="EUR",
        decision_time="2026-07-01T23:59:59Z",
    )

    assert economics["tax_context"] is context
    assert "Existing economics." in economics["summary"]
    assert "domicile Ireland (source report:synthetic, as of 2026-06-30" in economics["summary"]
    assert "residence tax unavailable" in economics["summary"]
    assert "hedge economics unavailable" in economics["summary"]


def test_missing_or_unresolved_evidence_fails_closed() -> None:
    context = build_etf_tax_context_panel(
        {"fields": {"domicile": {"status": "unknown", "value": "Ireland"}}},
        {},
        trading_currency="EUR",
        assumptions=ETFContextAssumptions(),
    )

    assert context["domicile"]["status"] == "unavailable"
    assert context["domicile"]["value"] is None
    assert context["distribution"]["status"] == "unavailable"
    assert context["distribution"]["policy"]["value"] is None
    assert context["currency"]["economic_currency_weights"] is None
    assert context["currency"]["primary_economic_currency"] is None
    assert context["currency"]["trading_currency_differs_from_economic"] is None
