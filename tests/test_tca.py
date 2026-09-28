from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.application.ui_facade import load_paper_tca_view
from etf_cockpit.portfolio.paper_trading import PaperLedger
from etf_cockpit.trading.tca import (
    TCAAttributionStore,
    TCACalculator,
    calibrate_completed_fills,
)
from test_paper_trading import _proposal


def _fill(*, fill_id: str = "fill-1", quantity: float = 10.0, price: float = 102.3, fee: float = 2.0) -> dict[str, object]:
    return {
        "fill_id": fill_id,
        "order_id": "order-1",
        "instrument_id": "VWCE",
        "side": "buy",
        "quantity": quantity,
        "price": price,
        "fee": fee,
        "currency": "EUR",
        "as_of": "2026-07-20T10:00:00+00:00",
    }


def _order(*, status: str = "filled", quantity: float = 10.0, filled_quantity: float = 10.0) -> dict[str, object]:
    return {
        "order_id": "order-1",
        "proposal_id": "proposal-1",
        "instrument_id": "VWCE",
        "side": "buy",
        "quantity": quantity,
        "filled_quantity": filled_quantity,
        "execution_price": 100.0,
        "currency": "EUR",
        "status": status,
    }


def test_tca_decomposes_spread_delay_and_fees() -> None:
    record = TCACalculator().calculate(
        _fill(),
        _order(),
        benchmark={
            "decision_price": 100.0,
            "arrival_mid_price": 102.0,
            "arrival_spread_bps": 20.0,
            "decision_time": "2026-07-20T09:59:00+00:00",
            "arrival_time": "2026-07-20T10:00:00+00:00",
            "available_at": "2026-07-20T10:00:00+00:00",
            "source_authority": "synthetic_test_quote",
            "source_checksum": "a" * 64,
        },
    )

    assert record.delay_cost == pytest.approx(20.0)
    assert record.spread_cost == pytest.approx(1.02)
    assert record.impact_cost == pytest.approx(1.98)
    assert record.component_total_slippage == pytest.approx(record.realised_price_slippage)
    assert record.component_total_slippage == pytest.approx(23.0)
    assert record.reconciliation_status == "reconciled"
    assert record.realised_fee == 2.0
    assert record.realised_total_cost == pytest.approx(25.0)
    assert record.fee_cost == 2.0
    assert record.component_total_cost == pytest.approx(
        record.delay_cost + record.spread_cost + record.impact_cost + record.fee_cost
    )
    assert record.component_total_cost == pytest.approx(record.realised_total_cost)
    assert record.component_total_cost == pytest.approx(25.0)
    assert record.total_cost_reconciliation_status == "reconciled"


def test_tca_preserves_original_cost_forecast() -> None:
    forecast = {
        "estimate_id": "estimate-1",
        "total_cost_eur": 4.5,
        "total_cost_bps": 18.0,
        "order_value_eur": 2_500.0,
        "assumptions": ["synthetic forecast"],
    }
    original = {key: list(value) if isinstance(value, list) else value for key, value in forecast.items()}
    record = TCACalculator().calculate(_fill(), _order(), cost_forecast=forecast)

    assert forecast == original
    assert record.cost_forecast == original
    assert record.estimated_total_cost == pytest.approx(4.5)
    assert record.realised_total_cost == pytest.approx(25.0)
    assert record.estimated_to_realised_variance == pytest.approx(20.5)


def test_unfilled_orders_excluded_from_calibration() -> None:
    calculator = TCACalculator()
    partial = calculator.calculate(_fill(fill_id="partial", quantity=5.0), _order(status="partially_filled", filled_quantity=5.0))
    cancelled = calculator.calculate(_fill(fill_id="cancelled", quantity=5.0), _order(status="cancelled", filled_quantity=5.0))
    completed = calculator.calculate(_fill(fill_id="complete"), _order())

    calibration = calibrate_completed_fills((partial, cancelled, completed))

    assert partial.calibration_eligible is False
    assert cancelled.calibration_eligible is False
    assert completed.calibration_eligible is True
    assert calibration["sample_count"] == 1
    assert calibration["mean_realised_cost_bps"] == pytest.approx(completed.realised_cost_bps)


def test_only_completion_fill_is_eligible_for_calibration(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000.0)
    order = ledger.accept_proposal(_proposal(source="tca-partial-fills"), execution_price=10.0, fee=2.0)
    ledger.record_fill(str(order["order_id"]), quantity=5.0, price=11.0, fee=1.0)
    ledger.record_fill(str(order["order_id"]), quantity=5.0, price=12.0, fee=1.0)

    view = load_paper_tca_view(tmp_path)
    rows = view["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert rows[0]["completed_order"] is False
    assert rows[0]["calibration_eligible"] is False
    assert rows[1]["completed_order"] is True
    assert rows[1]["calibration_eligible"] is True
    assert view["calibration"]["sample_count"] == 1


def test_future_benchmark_timestamps_leave_attribution_unavailable() -> None:
    valid_times = {
        "decision_time": "2026-07-20T09:59:00+00:00",
        "arrival_time": "2026-07-20T10:00:00+00:00",
        "available_at": "2026-07-20T10:00:00+00:00",
    }
    invalid_times = (
        {**valid_times, "decision_time": "2026-07-20T10:01:00+00:00"},
        {**valid_times, "arrival_time": "2026-07-20T10:01:00+00:00"},
        {**valid_times, "available_at": "2026-07-20T10:01:00+00:00"},
        {**valid_times, "available_at": None},
        {**valid_times, "decision_time": "not-a-timestamp"},
        {
            **valid_times,
            "decision_time": "2026-07-20T09:59:30+00:00",
            "arrival_time": "2026-07-20T09:59:00+00:00",
        },
    )
    for timestamps in invalid_times:
        record = TCACalculator().calculate(
            _fill(),
            _order(),
            benchmark={
                "decision_price": 100.0,
                "arrival_mid_price": 102.0,
                "arrival_spread_bps": 20.0,
                **timestamps,
            },
        )

        assert record.delay_cost is None
        assert record.spread_cost is None
        assert record.impact_cost is None
        assert record.reconciliation_status == "incomplete"
        expected_limitation = (
            "benchmark_temporal_provenance_unavailable"
            if timestamps.get("available_at") is None
            else "benchmark_temporal_provenance_invalid"
        )
        assert expected_limitation in record.benchmark_limitations


def test_paper_fill_costs_reconcile_to_ledger_and_persist_attribution(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000.0)
    order = ledger.accept_proposal(_proposal(source="tca-ledger"), execution_price=10.0, fee=2.0)
    ledger.record_fill(str(order["order_id"]), quantity=10.0, price=11.0, fee=3.0)

    view = load_paper_tca_view(tmp_path)
    assert view["status"] == "available"
    rows = view["rows"]
    assert isinstance(rows, list)
    row = rows[0]
    assert row["fill_id"] == ledger.trade_rows()[0]["paper_trade_id"]
    assert row["order_id"] == order["order_id"]
    assert row["proposal_id"] == order["proposal_id"]
    assert row["fee"] == ledger.trade_rows()[0]["fee"] == 3.0
    assert row["ledger_fee_reconciliation"] == "matched"
    assert row["realised_price_slippage"] == pytest.approx(10.0)
    assert row["realised_total_cost"] == pytest.approx(13.0)
    assert row["delay_cost"] is None
    assert row["spread_cost"] is None
    assert row["impact_cost"] is None
    assert "decision_or_arrival_midpoint_unavailable" in row["benchmark_limitations"]
    assert row["calibration_eligible"] is True

    store = TCAAttributionStore(ledger.path.parent / "tca_attributions")
    persisted = store.load()
    assert len(persisted) == 1
    assert persisted[0]["fill_id"] == row["fill_id"]
    assert persisted[0]["realised_fee"] == row["fee"]
    assert load_paper_tca_view(tmp_path)["coverage"]["persisted_attribution_count"] == 1


def test_unexpected_fill_is_persisted_explicitly_and_not_calibrated(tmp_path: Path) -> None:
    record = TCACalculator().calculate(_fill(), None)
    store = TCAAttributionStore(tmp_path / "tca_attributions")
    store.persist((record,))
    persisted = store.load()[0]

    assert record.association_status == "unexpected"
    assert record.proposal_id is None
    assert record.calibration_eligible is False
    assert record.realised_price_slippage is None
    assert "pre_fill_reference_price_unavailable" in record.benchmark_limitations
    assert persisted["association_status"] == "unexpected"
    assert calibrate_completed_fills((persisted,))["sample_count"] == 0
