from __future__ import annotations

import hashlib
from dataclasses import replace

import pandas as pd
from decimal import Decimal
from types import SimpleNamespace

from etf_cockpit.app.pages import portfolio as portfolio_page
from etf_cockpit.application import ui_facade
from etf_cockpit.data.event_calendar import (
    EVENT_COLUMNS,
    CalendarEvent,
    load_calendar_events,
    persist_calendar_events,
)
from etf_cockpit.data.market_adjustments import CorporateAction, CorporateActionStore
from etf_cockpit.portfolio.calendar import build_portfolio_calendar


DECISION = "2026-07-05T12:00:00+00:00"


def _action(
    action_id: str,
    instrument_id: str,
    action_type: str,
    *,
    amount: float,
    currency: str,
    revision: int = 1,
    status: str = "active",
    known_at: str = "2026-07-01T10:00:00+00:00",
    payable_at: str = "2026-09-15T00:00:00+00:00",
) -> CorporateAction:
    return CorporateAction(
        action_id=action_id,
        instrument_id=instrument_id,
        action_type=action_type,
        announced_at="2026-07-01T09:00:00+00:00",
        effective_at="2026-09-01T00:00:00+00:00",
        ex_date="2026-09-01",
        payable_at=payable_at,
        known_at=known_at,
        revision=revision,
        source="issuer",
        source_id="issuer-actions",
        source_checksum=hashlib.sha256(f"{action_id}:{revision}:{amount}".encode()).hexdigest(),
        amount=amount,
        currency=currency,
        status=status,
    )


def _event_frame(tmp_path) -> pd.DataFrame:
    event = CalendarEvent(
        event_id="issuer-dividend-date",
        instrument_id="STOCK",
        event_type="dividend",
        event_date="2026-08-10",
        available_at="2026-07-01T09:00:00+00:00",
        ingested_at="2026-07-01T09:01:00+00:00",
        source_id="issuer-calendar",
        source_authority="issuer",
        timezone_name="Europe/Berlin",
        title="Expected dividend payment",
        risk_level="high",
    )
    path = tmp_path / "event-calendar.parquet"
    raw = tmp_path / "raw" / "event-calendar"
    persist_calendar_events([event], raw_dir=raw, clean_path=path)
    return load_calendar_events(path, raw_dir=raw)


def _bond_terms() -> dict[str, object]:
    return {
        "status": "available",
        "terms": {
            "instrument_id": "BOND",
            "currency": "EUR",
            "maturity_date": "2027-01-01",
            "source_id": "bond-offering-document",
            "confidence": "high",
            "revision": 1,
        },
        "coupon_schedule": [
            {
                "payment_date": "2026-12-31",
                "amount": "5",
                "currency": "EUR",
                "source_id": "bond-offering-document",
                "source_version_id": "bond-terms-version-1",
                "sequence": 1,
            }
        ],
        "redemption_schedule": [
            {
                "payment_date": "2027-01-01",
                "amount": "100",
                "currency": "EUR",
                "source_id": "bond-offering-document",
                "source_version_id": "bond-terms-version-1",
            }
        ],
    }


def test_confirmed_contractual_and_estimated_calendar_events_are_distinct(tmp_path) -> None:
    result = build_portfolio_calendar(
        pd.DataFrame(
            [
                {"instrument_id": "STOCK", "quantity": "20", "asset_type": "stock"},
                {"instrument_id": "BOND", "quantity": "3", "asset_type": "bond"},
            ]
        ),
        decision_time=DECISION,
        event_rows=_event_frame(tmp_path),
        fixed_income_terms={"BOND": _bond_terms()},
        fx_rates=pd.DataFrame(),
    )

    statuses = {event["status"] for event in result["events"]}
    assert statuses == {"estimated", "confirmed"}
    event = next(item for item in result["events"] if item["event_id"] == "issuer-dividend-date")
    assert event["source_authority"] == "issuer"
    assert event["timezone_name"] == "Europe/Berlin"
    assert event["blackout_candidate"] is True


def test_projected_dividend_distribution_coupon_and_redemption_reconcile_to_quantity_terms() -> None:
    result = build_portfolio_calendar(
        pd.DataFrame(
            [
                {"instrument_id": "STOCK", "quantity": "10", "asset_type": "stock"},
                {"instrument_id": "ETF", "quantity": "4", "asset_type": "etf"},
                {"instrument_id": "BOND", "quantity": "3", "asset_type": "bond"},
            ]
        ),
        decision_time=DECISION,
        event_rows=pd.DataFrame(columns=EVENT_COLUMNS),
        corporate_actions=(
            _action("stock-dividend", "STOCK", "dividend", amount=2, currency="EUR"),
            _action("etf-distribution", "ETF", "distribution", amount=3, currency="EUR"),
        ),
        fixed_income_terms={"BOND": _bond_terms()},
        fx_rates=pd.DataFrame(),
    )

    flows = result["cash_flows"]
    amounts = {
        (flow["instrument_id"], flow["flow_type"], flow["source_id"]): flow["amount"]
        for flow in flows
    }
    assert amounts[("STOCK", "income", "issuer-actions")] == Decimal("20.0")
    assert amounts[("ETF", "income", "issuer-actions")] == Decimal("12.0")
    bond_flows = [flow for flow in flows if flow["instrument_id"] == "BOND"]
    assert {flow["flow_type"]: flow["amount"] for flow in bond_flows} == {
        "income": Decimal("15"),
        "maturity_proceeds": Decimal("300"),
    }
    assert all(flow["status"] == "confirmed" for flow in bond_flows)


def test_revised_and_cancelled_actions_keep_append_only_history(tmp_path) -> None:
    with CorporateActionStore(tmp_path) as store:
        store.append(_action("etf-distribution", "ETF", "distribution", amount=1, currency="EUR"))
        store.append(
            _action(
                "etf-distribution",
                "ETF",
                "distribution",
                amount=1.25,
                currency="EUR",
                revision=2,
                known_at="2026-07-02T10:00:00+00:00",
            )
        )
        store.append(
            _action(
                "etf-distribution",
                "ETF",
                "distribution",
                amount=1.25,
                currency="EUR",
                revision=3,
                status="retracted",
                known_at="2026-07-03T10:00:00+00:00",
            )
        )
        history = store.query("ETF")

    result = build_portfolio_calendar(
        pd.DataFrame([{"instrument_id": "ETF", "quantity": "8", "asset_type": "etf"}]),
        decision_time=DECISION,
        event_rows=pd.DataFrame(columns=EVENT_COLUMNS),
        corporate_actions=history,
        fx_rates=pd.DataFrame(),
    )

    versions = result["event_versions"]
    assert len(history) == len(versions) == 3
    assert [item["status"] for item in versions] == ["revised", "revised", "cancelled"]
    assert [item["version"] for item in versions] == [1, 2, 3]
    assert result["events"][0]["status"] == "cancelled"
    assert result["cash_flows"] == []


def test_missing_fx_or_bond_terms_warn_and_never_project_zero() -> None:
    result = build_portfolio_calendar(
        pd.DataFrame(
            [
                {"instrument_id": "STOCK", "quantity": "10", "asset_type": "stock"},
                {"instrument_id": "BOND", "quantity": "3", "asset_type": "bond"},
            ]
        ),
        decision_time=DECISION,
        event_rows=pd.DataFrame(columns=EVENT_COLUMNS),
        corporate_actions=(
            _action("stock-dividend", "STOCK", "dividend", amount=2, currency="USD"),
            _action("bond-coupon", "BOND", "coupon", amount=5, currency="EUR"),
        ),
        fixed_income_terms={"BOND": {"status": "unavailable"}},
        fx_rates=pd.DataFrame(),
    )

    stock_flow = next(flow for flow in result["cash_flows"] if flow["instrument_id"] == "STOCK")
    bond_flow = next(flow for flow in result["cash_flows"] if flow["instrument_id"] == "BOND")
    assert stock_flow["amount"] is None
    assert stock_flow["reason"] == "fx_coverage_unavailable"
    assert bond_flow["amount"] is None
    assert bond_flow["local_amount"] is None
    assert bond_flow["reason"] == "fixed_income_terms_unavailable"
    assert result["coverage"]["fixed_income_terms"]["status"] == "partial"
    assert "fx_coverage_unavailable" in result["warnings"]
    assert "fixed_income_terms_unavailable:BOND" in result["warnings"]


def test_conflicting_active_and_retracted_provider_statuses_have_no_payable_amount() -> None:
    active = _action("shared-dividend", "STOCK", "dividend", amount=2, currency="EUR")
    retracted = replace(
        _action(
            "shared-dividend",
            "STOCK",
            "dividend",
            amount=2,
            currency="EUR",
            status="retracted",
            known_at="2026-07-02T10:00:00+00:00",
        ),
        source_id="exchange-actions",
    )

    result = build_portfolio_calendar(
        pd.DataFrame([{"instrument_id": "STOCK", "quantity": "10", "asset_type": "stock"}]),
        decision_time=DECISION,
        event_rows=pd.DataFrame(columns=EVENT_COLUMNS),
        corporate_actions=(active, retracted),
        fx_rates=pd.DataFrame(),
    )

    assert len(result["cash_flows"]) == 1
    flow = result["cash_flows"][0]
    assert flow["amount"] is None
    assert flow["reason"] == "corporate_action_status_conflict"
    assert "corporate_action_status_conflict:shared-dividend" in result["warnings"]


def test_calendar_ui_currency_selection_reloads_projection(monkeypatch) -> None:
    calls: list[str] = []

    def load(_snapshot, _analysis, *, output_currency: str) -> dict[str, object]:
        calls.append(output_currency)
        return {
            "status": "available",
            "currency": output_currency,
            "available_output_currencies": ["EUR", "USD"],
            "events": [],
            "cash_flow_summaries": [],
            "warnings": [],
        }

    monkeypatch.setattr(portfolio_page, "load_portfolio_calendar_projection", load)
    state = SimpleNamespace(snapshot=SimpleNamespace(holdings=pd.DataFrame()))
    control = portfolio_page._portfolio_calendar_block(None, state, SimpleNamespace())
    pending = [control]
    seen: set[int] = set()
    currency_control = None
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if getattr(item, "key", None) == "portfolio.calendar.currency":
            currency_control = item
            break
        pending.extend(getattr(item, "controls", ()) or ())
        child = getattr(item, "content", None)
        if child is not None:
            pending.append(child)

    assert currency_control is not None
    assert currency_control.value == "EUR"
    assert callable(currency_control.on_select)
    currency_control.value = "USD"
    currency_control.on_select(SimpleNamespace())
    assert calls == ["EUR", "USD"]


def test_facade_calendar_loader_uses_snapshot_cutoff_without_creating_missing_store(tmp_path, monkeypatch) -> None:
    database = tmp_path / "missing.sqlite"
    monkeypatch.setattr(ui_facade, "select_holdings_view", lambda holdings, _view: holdings)
    monkeypatch.setattr(
        ui_facade,
        "load_calendar_events",
        lambda: pd.DataFrame(columns=EVENT_COLUMNS),
    )
    monkeypatch.setattr(
        ui_facade,
        "storage_layout",
        lambda _root: SimpleNamespace(transactional_path=database),
    )
    monkeypatch.setattr(ui_facade, "load_fx_rates", lambda: pd.DataFrame())

    snapshot = SimpleNamespace(
        holdings=pd.DataFrame([{"instrument_id": "STOCK", "quantity": "10", "asset_type": "stock"}])
    )
    analysis = SimpleNamespace(
        snapshot_binding=SimpleNamespace(as_of=DECISION, holdings_view="direct")
    )
    projection = ui_facade.load_portfolio_calendar_projection(snapshot, analysis)

    assert projection["decision_time"] == DECISION
    assert projection["currency"] == "EUR"
    assert projection["execution_allowed"] is False
    assert not database.exists()
