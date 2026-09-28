from __future__ import annotations

from datetime import date

import pandas as pd

from etf_cockpit.application import ui_facade
from etf_cockpit.data.capital_allocation import capital_allocation_analysis
from etf_cockpit.data.market_adjustments import CorporateAction, CorporateActionCoverage


DECISION = "2026-12-31T00:00:00Z"
_CHECKSUM = "0" * 64


def _fact(
    year: int,
    metric: str,
    value: float,
    *,
    known_at: str | None = None,
    currency: str = "USD",
    unit: str | None = None,
    dimensions: str = "",
    restatement_kind: str = "reported",
    source_id: str | None = None,
    instant: bool = False,
) -> dict[str, object]:
    period_end = f"{year}-12-31"
    known = known_at or f"{year + 1}-02-15T00:00:00Z"
    return {
        "instrument_id": "ACME",
        "canonical_metric": metric,
        "value": value,
        "period_type": "instant" if instant else "annual",
        "period_key": f"instant:{period_end}" if instant else f"FY{year}",
        "start": None if instant else f"{year}-01-01",
        "end": period_end,
        "instant": period_end if instant else None,
        "period_end": period_end,
        "fiscal_year": year,
        "fiscal_period": "instant" if instant else "FY",
        "source_id": source_id or f"{metric}-{year}",
        "filed": known,
        "known_at": known,
        "available_at": known,
        "unit": unit or ("shares" if metric in {"shares_outstanding", "basic_shares", "diluted_shares", "treasury_shares", "shares_issued", "shares_repurchased"} else currency),
        "currency": None if metric in {"shares_outstanding", "basic_shares", "diluted_shares", "treasury_shares", "shares_issued", "shares_repurchased"} else currency,
        "dimensions": dimensions,
        "restatement_kind": restatement_kind,
    }


def _statements() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year, cash, equity, shares, diluted, treasury in (
        (2023, 40.0, 250.0, 100.0, 110.0, 5.0),
        (2024, 84.0, 291.0, 100.0, 110.0, 10.0),
        (2025, 172.0, 338.0, 100.0, 110.0, 15.0),
    ):
        rows.extend(
            _fact(year, metric, value, instant=True)
            for metric, value in (
                ("cash", cash),
                ("equity", equity),
                ("shares_outstanding", shares),
                ("diluted_shares", diluted),
                ("treasury_shares", treasury),
            )
        )

    flow_values = {
        2024: {
            "cash_from_operations": 100.0,
            "net_income": 50.0,
            "ebitda": 80.0,
            "revenue": 400.0,
            "capex": 20.0,
            "free_cash_flow": 75.0,
            "working_capital_contribution": 5.0,
            "cash_taxes_paid": 10.0,
            "cash_interest_paid": 4.0,
            "cash_from_investing": -30.0,
            "cash_from_financing": -26.0,
            "cash_from_fx": 0.0,
            "cash_net_change": 44.0,
            "acquisitions": 5.0,
            "disposals": 3.0,
            "debt_issuance": 10.0,
            "debt_repayment": 20.0,
            "dividends": 10.0,
            "gross_buybacks": 8.0,
            "equity_issuance": 2.0,
            "stock_based_compensation": 4.0,
            "other_comprehensive_income": 3.0,
            "shares_issued": 0.0,
            "shares_repurchased": 0.0,
        },
        2025: {
            "cash_from_operations": 120.0,
            "net_income": 60.0,
            "ebitda": 100.0,
            "revenue": 500.0,
            "capex": 25.0,
            "free_cash_flow": 90.0,
            "working_capital_contribution": -3.0,
            "cash_taxes_paid": 12.0,
            "cash_interest_paid": 5.0,
            "cash_from_investing": -40.0,
            "cash_from_financing": 8.0,
            "cash_from_fx": 0.0,
            "cash_net_change": 88.0,
            "acquisitions": 7.0,
            "disposals": 4.0,
            "debt_issuance": 50.0,
            "debt_repayment": 22.0,
            "dividends": 15.0,
            "gross_buybacks": 15.0,
            "equity_issuance": 10.0,
            "stock_based_compensation": 5.0,
            "other_comprehensive_income": 2.0,
            "shares_issued": 0.0,
            "shares_repurchased": 0.0,
        },
    }
    for year, metrics in flow_values.items():
        rows.extend(_fact(year, metric, value) for metric, value in metrics.items())
    return pd.DataFrame(rows)


def _coverage() -> CorporateActionCoverage:
    return CorporateActionCoverage(
        instrument_id="ACME",
        coverage_through="2025-12-31T00:00:00Z",
        published_at="2025-12-31T00:00:00Z",
        retrieved_at="2026-01-02T00:00:00Z",
        known_at="2026-01-02T00:00:00Z",
        revision=1,
        source="fixture",
        source_id="action-coverage",
        source_checksum=_CHECKSUM,
    )


def _split() -> CorporateAction:
    return CorporateAction(
        action_id="split-2025",
        instrument_id="ACME",
        action_type="split",
        announced_at="2025-05-01T00:00:00Z",
        effective_at="2025-06-01T00:00:00Z",
        ex_date="2025-06-01",
        payable_at=None,
        known_at="2025-05-02T00:00:00Z",
        revision=1,
        source="fixture",
        source_id="split-filing",
        source_checksum=_CHECKSUM,
        ratio=2.0,
    )


def _analyse(frame: pd.DataFrame | None = None, **kwargs: object) -> dict[str, object]:
    return capital_allocation_analysis(
        _statements() if frame is None else frame,
        instrument_id="ACME",
        as_known_at=DECISION,
        **kwargs,
    )


def test_cash_flow_quality_is_period_aligned_formula_labelled_and_separate_from_reported_fcf() -> None:
    result = _analyse(
        market_inputs={"market_cap": 1000.0, "market_cap_at": "2025-12-31", "currency": "USD", "source_id": "caller-market-cap"},
        corporate_action_coverage=_coverage(),
    )
    metrics = result["metrics"]

    assert metrics["cash_from_operations_to_net_income"]["value"] == 2.0
    assert metrics["cash_from_operations_to_ebitda"]["value"] == 1.2
    assert metrics["free_cash_flow"]["value"] == 95.0
    assert metrics["reported_free_cash_flow"]["value"] == 90.0
    assert metrics["free_cash_flow_margin"]["value"] == 0.19
    assert metrics["working_capital_contribution"]["value"] == -3.0
    assert metrics["cash_taxes_paid"]["value"] == 12.0
    assert metrics["cash_interest_paid"]["value"] == 5.0
    assert metrics["capex_intensity"]["value"] == 0.05
    assert metrics["cash_conversion"]["value"] == 2.0
    assert metrics["free_cash_flow"]["formula"] == "cash_from_operations - capex"
    assert metrics["free_cash_flow"]["period"] == "FY2025"
    assert metrics["free_cash_flow"]["currency"] == "USD"
    assert metrics["reported_free_cash_flow"]["formula"] == "reported free_cash_flow"
    assert result["maintenance_growth_capex"]["status"] == "unavailable"
    assert result["execution_allowed"] is False


def test_cash_sources_and_uses_reconcile_to_cash_and_broken_identity_is_flagged() -> None:
    result = _analyse()
    checks = {item["name"]: item for item in result["reconciliations"]}
    allocation = result["capital_allocation"]

    assert allocation["acquisitions"]["value"] == 7.0
    assert allocation["disposals"]["value"] == 4.0
    assert allocation["debt_issuance"]["value"] == 50.0
    assert allocation["debt_repayment"]["value"] == 22.0
    assert allocation["cash_accumulation"]["value"] == 88.0
    assert checks["cash_flow_identity"]["status"] == "passed"
    assert checks["cash_balance_change"]["status"] == "passed"
    assert checks["sources_and_uses_to_cash"]["status"] == "passed"

    broken = _statements()
    broken.loc[broken["canonical_metric"].eq("cash_net_change") & broken["fiscal_year"].eq(2025), "value"] = 99.0
    broken_result = _analyse(broken)
    broken_checks = {item["name"]: item for item in broken_result["reconciliations"]}
    assert broken_checks["cash_flow_identity"]["status"] == "failed"
    assert broken_checks["sources_and_uses_to_cash"]["status"] == "failed"


def test_shareholder_yield_and_buyback_offset_require_separated_components() -> None:
    result = _analyse(
        market_inputs={"market_cap": 1000.0, "market_cap_at": date(2025, 12, 31), "currency": "USD", "source_id": "caller-market-cap"},
        corporate_action_coverage=_coverage(),
    )
    metrics = result["metrics"]

    assert metrics["dividend_yield"]["value"] == 0.015
    assert metrics["buyback_yield"]["value"] == 0.015
    assert metrics["issuance_dilution_yield"]["value"] == -0.01
    assert metrics["shareholder_yield"]["value"] == 0.02
    assert metrics["buybacks_vs_sbc_issuance"]["status"] == "offsets"
    assert metrics["buybacks_vs_sbc_issuance"]["value"] == 0.0

    inseparable = _statements()
    inseparable = inseparable.loc[~(inseparable["canonical_metric"].eq("stock_based_compensation") & inseparable["fiscal_year"].eq(2025))]
    missing = _analyse(
        inseparable,
        market_inputs={"market_cap": 1000.0, "market_cap_at": "2025-12-31", "currency": "USD"},
        corporate_action_coverage=_coverage(),
    )["metrics"]["buybacks_vs_sbc_issuance"]
    assert missing["value"] is None
    assert missing["status"] == "missing"
    assert "stock_based_compensation_missing" in missing["limitation"]


def test_split_normalises_share_count_and_treasury_movement_is_not_double_counted() -> None:
    frame = _statements()
    frame.loc[frame["canonical_metric"].eq("shares_outstanding") & frame["fiscal_year"].eq(2025), "value"] = 200.0
    frame.loc[frame["canonical_metric"].eq("diluted_shares") & frame["fiscal_year"].eq(2025), "value"] = 220.0
    frame.loc[frame["canonical_metric"].eq("treasury_shares") & frame["fiscal_year"].eq(2025), "value"] = 20.0
    result = _analyse(frame, corporate_actions=(_split(),), corporate_action_coverage=_coverage())
    metrics = result["metrics"]

    assert metrics["basic_share_count_change"]["value"] == 0.0
    assert metrics["diluted_share_count_change"]["value"] == 0.0
    assert metrics["treasury_share_change"]["value"] == 10.0
    assert metrics["basic_share_count_change"]["denominator_value"] == 200.0
    assert metrics["basic_share_count_change"]["source_ids"] == ("shares_outstanding-2024", "shares_outstanding-2025", "split-filing")


def test_financial_institution_is_not_run_through_industrial_fcf_and_uses_existing_projection(monkeypatch) -> None:
    calls: list[str] = []

    def financial_projection(instrument_id: str, **_kwargs: object) -> dict[str, object]:
        calls.append(instrument_id)
        return {"status": "available", "instrument_id": instrument_id, "metrics": ()}

    monkeypatch.setattr(ui_facade, "load_financial_institution_projection", financial_projection)
    result = ui_facade.load_capital_allocation_analysis(
        _statements(),
        instrument_id="ACME",
        sector="bank",
        decision_time=DECISION,
    )

    assert result["metrics"]["free_cash_flow"]["value"] is None
    assert result["metrics"]["free_cash_flow"]["status"] == "not_applicable"
    assert result["financial_projection"]["status"] == "available"
    assert calls == ["ACME"]


def test_missing_dated_market_input_and_future_known_rows_remain_unavailable_or_excluded() -> None:
    frame = _statements()
    future_revision = _fact(
        2025,
        "cash_from_operations",
        999.0,
        known_at="2027-01-15T00:00:00Z",
        restatement_kind="amended",
        source_id="future-amendment",
    )
    frame = pd.concat([frame, pd.DataFrame([future_revision])], ignore_index=True)
    result = _analyse(
        frame,
        market_inputs={},
        corporate_action_coverage=_coverage(),
    )
    metrics = result["metrics"]

    assert metrics["free_cash_flow"]["value"] == 95.0
    assert metrics["dividend_yield"]["value"] is None
    assert metrics["dividend_yield"]["status"] == "missing"
    assert metrics["dividend_yield"]["limitation"] == "dated_price_or_market_cap_missing"
    assert metrics["shareholder_yield"]["value"] is None
    assert result["source_lineage"]["as_known_at"] == DECISION


def test_missing_capex_negative_fcf_invalid_denominators_and_currency_mismatch_fail_closed() -> None:
    frame = _statements()
    missing_capex = frame.loc[~(frame["canonical_metric"].eq("capex") & frame["fiscal_year"].eq(2025))]
    missing_result = _analyse(missing_capex)["metrics"]
    assert missing_result["free_cash_flow"]["value"] is None
    assert missing_result["capex_intensity"]["value"] is None
    assert missing_result["reported_free_cash_flow"]["value"] == 90.0

    negative = _statements()
    negative.loc[negative["canonical_metric"].eq("capex") & negative["fiscal_year"].eq(2025), "value"] = 150.0
    assert _analyse(negative)["metrics"]["free_cash_flow"]["value"] == -30.0
    assert _analyse(negative)["metrics"]["free_cash_flow"]["status"] == "negative"

    zero_denominator = _statements()
    zero_denominator.loc[zero_denominator["canonical_metric"].eq("net_income") & zero_denominator["fiscal_year"].eq(2025), "value"] = 0.0
    zero_metric = _analyse(zero_denominator)["metrics"]["cash_conversion"]
    assert zero_metric["value"] is None
    assert zero_metric["status"] == "missing"
    assert zero_metric["limitation"] == "net_income_must_be_positive"

    currency_mismatch = _statements()
    latest_net_income = currency_mismatch["canonical_metric"].eq("net_income") & currency_mismatch["fiscal_year"].eq(2025)
    currency_mismatch.loc[latest_net_income, "currency"] = "EUR"
    currency_mismatch.loc[latest_net_income, "unit"] = "EUR"
    mismatch = _analyse(currency_mismatch)["metrics"]["cash_conversion"]
    assert mismatch["value"] is None
    assert mismatch["status"] == "missing"
    assert mismatch["limitation"] == "currency_mismatch"


def test_multiple_share_classes_are_not_summed_or_forward_filled() -> None:
    frame = _statements()
    second_class = _fact(2025, "shares_outstanding", 40.0, dimensions="class=second")
    frame = pd.concat([frame, pd.DataFrame([second_class])], ignore_index=True)
    result = _analyse(frame, corporate_action_coverage=_coverage())
    share_change = result["metrics"]["basic_share_count_change"]

    assert share_change["value"] is None
    assert share_change["status"] == "missing"
    assert "shares_outstanding_ambiguous_evidence" in share_change["limitation"]


def test_restatement_selection_is_decision_time_specific() -> None:
    frame = _statements()
    amendment = _fact(
        2025,
        "net_income",
        55.0,
        known_at="2026-04-01T00:00:00Z",
        restatement_kind="amended",
        source_id="net-income-amendment",
    )
    frame = pd.concat([frame, pd.DataFrame([amendment])], ignore_index=True)
    early = capital_allocation_analysis(frame, instrument_id="ACME", as_known_at="2026-03-01T00:00:00Z")
    late = capital_allocation_analysis(frame, instrument_id="ACME", as_known_at="2026-05-01T00:00:00Z")

    assert early["metrics"]["cash_from_operations_to_net_income"]["value"] == 2.0
    assert late["metrics"]["cash_from_operations_to_net_income"]["value"] == 120.0 / 55.0


def test_invalid_market_cap_and_missing_decision_time_do_not_become_zero() -> None:
    invalid_cap = _analyse(market_inputs={"market_cap": 0.0, "market_cap_at": "2025-12-31", "currency": "USD"})
    assert invalid_cap["metrics"]["shareholder_yield"]["value"] is None
    assert invalid_cap["metrics"]["dividend_yield"]["value"] is None

    no_decision = capital_allocation_analysis(_statements(), instrument_id="ACME")
    assert no_decision["status"] == "unavailable"
    assert no_decision["metrics"]["free_cash_flow"]["value"] is None
    assert no_decision["metrics"]["free_cash_flow"]["limitation"] == "decision_time_required"
