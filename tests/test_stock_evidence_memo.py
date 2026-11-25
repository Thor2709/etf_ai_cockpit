"""The fundamentals-only evidence blocks are built once per (instrument, known version set) in a run and give what a
fresh build gives at every session (a new version known, a balance turning stale with the version set unchanged)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from etf_cockpit.analysis import stock_evidence as se
from etf_cockpit.analysis import stock_universe as su
from etf_cockpit.data import stock_fundamentals as store

UTC = timezone.utc
CONFIG = store.load_stock_config()
SESSIONS = [datetime(2026, 1, 30, 22, tzinfo=UTC), datetime(2026, 2, 9, 22, tzinfo=UTC), datetime(2026, 3, 2, 22, tzinfo=UTC),
            datetime(2026, 4, 14, 22, tzinfo=UTC), datetime(2026, 4, 16, 22, tzinfo=UTC), datetime(2026, 4, 27, 22, tzinfo=UTC)]


def _year(instrument: str, year: int, known: str, scale: float = 1.0) -> dict:
    revenue = 1000.0 * scale * (1 + 0.1 * (year - 2020))
    return {
        "instrument_id": instrument, "period_end": f"{year}-12-31", "period_type": "FY", "fiscal_year": year, "currency": "EUR",
        "source": "sec_edgar", "source_ref": f"{instrument}{year}{known}", "known_at": f"{known}T00:00:00+00:00",
        "revenue": revenue, "gross_profit": revenue * 0.4, "ebit": revenue * 0.15, "da": revenue * 0.05, "net_income_parent": revenue * 0.1,
        "pretax_income": revenue * 0.13, "income_tax": revenue * 0.03, "cfo": revenue * 0.14, "capex": revenue * 0.04,
        "total_assets": revenue * 2, "total_liabilities": revenue * 1.2, "equity_parent": revenue * 0.8, "minority_interest": 0.0,
        "ib_debt": revenue * 0.5, "cash_sti": revenue * 0.2, "current_assets": revenue * 0.6, "current_liabilities": revenue * 0.4,
        "shares_outstanding": 100.0, "retained_earnings": revenue * 0.3,
    }


def _root(tmp_path):
    rows = [_year("AAA", year, "2025-03-01") for year in (2021, 2022, 2023, 2024)]
    rows += [_year("AAA", 2025, "2026-03-01"), _year("AAA", 2025, "2026-04-15", scale=1.3)]  # a restated version known later
    rows += [_year("BBB", year, "2025-03-01") for year in (2021, 2022, 2023, 2024)]  # its 2024 balance turns stale in February 2026
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(clean / "stock_fundamentals.parquet")
    days = pd.bdate_range("2024-12-02", "2026-04-30")
    prices = pd.concat(pd.DataFrame({
        "etf_id": instrument, "date": days, "close": [base + index * 0.01 for index in range(len(days))], "currency": "EUR",
        "stock_splits": 0.0, "actions_evidenced": True, "dividends": 0.0,
    }) for instrument, base in (("AAA", 50.0), ("BBB", 20.0)))
    records = [su.StockRecord(instrument, instrument, instrument, "EUR", "Europe", "Industrials") for instrument in ("AAA", "BBB")]
    return records, prices.reset_index(drop=True)


def test_memo_gives_a_fresh_build_at_every_session_and_builds_each_version_set_once(tmp_path, monkeypatch) -> None:
    records, prices = _root(tmp_path)
    real, calls = se._Builder.flow_metrics, []
    monkeypatch.setattr(se._Builder, "flow_metrics", lambda self: calls.append(self.id) or real(self))
    su._PERIODS.clear()
    run = [su.build_universe_evidence(records, prices, when, root=tmp_path, config=CONFIG) for when in SESSIONS]
    # AAA: 3 known version sets (2021-2024; + 2025; 2025 restated), BBB: 1; each built once over both passes and all sessions
    assert sorted(calls) == ["AAA", "AAA", "AAA", "BBB"]
    for when, memo in zip(SESSIONS, run):
        su._PERIODS.clear()  # the oracle: a fresh build with no run state
        fresh = su.build_universe_evidence(records, prices, when, root=tmp_path, config=CONFIG)
        assert memo.evidence == fresh.evidence, when
    # the cases are exercised: the restated version is used, and the stale balance changes a metric with the same version set
    assert run[4].evidence["AAA"].metrics["revenue"].value != run[3].evidence["AAA"].metrics["revenue"].value
    first, second = (run[index].evidence["BBB"].metrics["net_debt_to_ebitda"] for index in (0, 1))
    assert first.available and not second.available and "stale" in str(second.reason)


def test_ready_price_frames_take_the_kernel_path_with_the_python_result(tmp_path, monkeypatch) -> None:
    records, prices = _root(tmp_path)
    prices.loc[(prices["etf_id"] == "BBB") & (prices["date"] == "2025-06-02"), "stock_splits"] = 2.0  # a split inside the history
    real, calls = su.as_traded_prefixes, []
    monkeypatch.setattr(su, "as_traded_prefixes", lambda frame, versions: calls.append(len(versions)) or real(frame, versions))
    factored = su.with_as_traded_factors(prices)  # the score's frames carry full-series factors: today's path
    for when in SESSIONS:
        kernel = su.build_universe_evidence(records, prices, when, root=tmp_path, config=CONFIG)
        assert su.build_universe_evidence(records, factored, when, root=tmp_path, config=CONFIG).prices == kernel.prices
        with monkeypatch.context() as python_path:
            python_path.setattr(su, "as_traded_kernel_ready", lambda _frame: False)
            assert su.build_universe_evidence(records, prices, when, root=tmp_path, config=CONFIG).prices == kernel.prices, when
    assert calls == [1] * 2 * len(SESSIONS)  # one call per stock and session, only for frames without carried factors
