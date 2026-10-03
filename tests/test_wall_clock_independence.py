"""Date-bomb guards: evidence ageing is measured against an explicit as-of, never an implicit wall clock."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages import risk as risk_page_module
from etf_cockpit.core.config import SettlementConfig
from etf_cockpit.data import trust_artifacts
from etf_cockpit.trading.order_lifecycle import OrderLifecycle, OrderState


def _holdings(as_of: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "instrument_id": "VWCE",
                "security": "Issuer holding",
                "as_of_date": as_of,
                "weight": 1.0,
                "source_id": "issuer-source",
                "completeness": "full",
                "freshness": "fresh",
                "confidence": 0.9,
                "authority": "issuer",
                "score_eligible": True,
            }
        ]
    )


def test_holdings_freshness_ages_against_the_supplied_reference_date() -> None:
    fresh = risk_page_module._refresh_holdings_freshness(_holdings("2026-07-10"), reference_date="2026-07-11")
    assert fresh.loc[0, "freshness"] == "fresh"
    assert bool(fresh.loc[0, "score_eligible"]) is True

    # Staleness is still enforced: far-future reference date, same stored evidence.
    far_future = risk_page_module._refresh_holdings_freshness(_holdings("2026-07-10"), reference_date="2099-01-01")
    assert far_future.loc[0, "freshness"] == "stale"
    assert bool(far_future.loc[0, "score_eligible"]) is False
    assert float(far_future.loc[0, "confidence"]) <= 0.25

    # Evidence dated after the reference date is invalid (no look-ahead).
    future = risk_page_module._refresh_holdings_freshness(_holdings("2026-07-10"), reference_date="2026-07-01")
    assert future.loc[0, "freshness"] == "invalid"
    assert bool(future.loc[0, "score_eligible"]) is False


def test_exposure_eligibility_uses_the_reference_date_for_age_and_future_checks() -> None:
    assert len(risk_page_module._exposure_eligible_holdings(_holdings("2026-07-10"), reference_date="2026-07-11")) == 1
    assert risk_page_module._exposure_eligible_holdings(_holdings("2026-07-10"), reference_date="2099-01-01").empty
    assert risk_page_module._exposure_eligible_holdings(_holdings("2026-07-10"), reference_date="2026-07-01").empty


def test_source_freshness_buckets_are_relative_to_the_supplied_as_of() -> None:
    freshness = trust_artifacts._freshness_from_date
    assert freshness("2026-07-10", "2026-07-11T08:00:00+00:00") == "ok"
    assert freshness("2026-07-10", "2026-07-18") == "warning"
    assert freshness("2026-07-10", "2099-01-01T00:00:00Z") == "stale_block"
    assert freshness("", "2099-01-01") == "missing_or_pending"
    assert freshness("not-a-date", "2026-07-11") == "unknown"

    score = SimpleNamespace(components=[], latest_date="2026-07-10")
    assert trust_artifacts._score_freshness(score, "2026-07-11T00:00:00+00:00") == "ok"
    assert trust_artifacts._score_freshness(score, "2099-01-01T00:00:00+00:00") == "stale_block"


class _FixedCash:
    cash_includes_unsettled_trades = False

    def cash_balance(self, *, account_id: str, currency: str, as_of: datetime) -> Decimal:
        return Decimal("1000")


def test_partial_fill_buying_power_depends_on_the_as_of_not_the_wall_clock(tmp_path: Path) -> None:
    lifecycle = OrderLifecycle(
        tmp_path / "orders.sqlite3",
        _FixedCash(),
        settlement=SettlementConfig(settlement_lags={"XETRA": {"etf": 2}}),
    )
    lifecycle.reserve_order(
        account_id="account-1",
        order_id="order-1",
        idempotency_key="request-1",
        currency="EUR",
        side="buy",
        quantity=Decimal("10"),
        limit_price=Decimal("10"),
        fee_estimate=Decimal("0.25"),
        venue="XETRA",
        instrument_type="etf",
        occurred_at=datetime(2026, 9, 30, 10, tzinfo=timezone.utc),
    )
    lifecycle.transition("order-1", OrderState.ACKNOWLEDGED, event_key="paper-ack")
    lifecycle.record_fill(
        "order-1",
        fill_id="fill-1",
        quantity=Decimal("4"),
        price=Decimal("9.95"),
        fee=Decimal("0.10"),
        occurred_at=datetime(2026, 9, 30, 10, tzinfo=timezone.utc),
    )

    on_fill_day = datetime(2026, 9, 30, 11, tzinfo=timezone.utc)
    after_settlement = datetime(2099, 1, 1, tzinfo=timezone.utc)
    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=on_fill_day) == Decimal("899.85")
    assert lifecycle.available_buying_power(account_id="account-1", currency="EUR", as_of=after_settlement) == Decimal("939.75")
