"""Stock score inputs (wave 1 train F). All identities and numbers below are synthetic test evidence."""

from datetime import date, datetime, timezone

import pandas as pd
from etf_cockpit.analysis.stock_evidence import MarketInputs, build_stock_evidence
from etf_cockpit.data import sec_edgar_provider, stock_fundamentals as store

DECISION = datetime(2026, 11, 20, 23, 59, 59, tzinfo=timezone.utc)


def test_newer_yfinance_share_row_does_not_hide_the_reported_sec_count() -> None:
    # Store shape on 2026-11-22 (as AAP): SEC statements and DEI counts dated by filing; a yfinance
    # quarter with no SEC quarter of the same end carries a share count dated by the 2026-11-08 fetch.
    dei = sec_edgar_provider.parse_reported_shares({"facts": {"dei": {"EntityCommonStockSharesOutstanding": {
        "units": {"shares": [{"end": "2026-10-15", "filed": "2026-10-30", "val": 10.0}]}}}}}, source_ref="test")
    statement = {"period_end": "2025-12-31", "period_type": "FY", "currency": "USD", "source": "sec_edgar",
                 "source_ref": "test", "known_at": "2026-02-10", "revenue": 1000.0, "net_income_parent": 100.0,
                 "ebit": 200.0, "cfo": 220.0, "capex": 70.0, "equity_parent": 900.0, "minority_interest": 0.0,
                 "ib_debt": 300.0, "lease_liabilities": 50.0, "cash_sti": 150.0}
    provider = {**statement, "period_end": "2026-09-30", "period_type": "Q", "source": "yfinance",
                "known_at": "2026-11-08T07:11:22+00:00", "shares_outstanding": 11.0}
    frame, _ = store.append_period_rows(pd.DataFrame(columns=store.PERIOD_COLUMNS), "T", [*dei, statement, provider])
    periods = store.periods_for("T", frame, ["sec_edgar", "esef", "yfinance"])
    market = MarketInputs(price=50.0, price_currency="USD", price_date=date(2026, 11, 20))
    ev = build_stock_evidence("T", periods, DECISION, market, None, store.load_stock_config())
    assert ev.metrics["market_cap"].value == 500.0
    assert "sec_dei" in ev.metrics["market_cap"].source
