"""Stock evidence: hand-computed metrics, point-in-time rules, currency, peers and score components."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from dataclasses import replace

import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis import stock_universe as su
from etf_cockpit.analysis.stock_evidence import AnalystInputs, MarketInputs, build_stock_evidence
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data.stock_fundamentals import load_stock_config

UTC = timezone.utc
DECISION = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
CONFIG = load_stock_config()


def _period(year: int, *, known: str | None = None, currency: str = "EUR", **overrides: float) -> sm.Period:
    values = {
        "revenue": 1000.0 * (1.1 ** (year - 2022)),
        "gross_profit": 400.0,
        "ebit": 200.0,
        "da": 60.0,
        "pretax_income": 180.0,
        "income_tax": 45.0,
        "net_income_parent": 100.0 * (1.1 ** (year - 2022)),
        "cfo": 220.0,
        "capex": 70.0,
        "dividends_paid": 30.0,
        "equity_parent": 900.0 + 100.0 * (year - 2022),
        "minority_interest": 30.0,
        "ib_debt": 300.0,
        "lease_liabilities": 50.0,
        "cash_sti": 150.0,
        "shares_outstanding": 10.0,
    }
    values.update(overrides)
    known_at = datetime.fromisoformat(known or f"{year + 1}-02-15").replace(tzinfo=UTC)
    return sm.Period(date(year, 12, 31), "FY", known_at, currency, "sec_edgar", values)


def _market(price: float = 50.0, currency: str = "EUR", **extra: object) -> MarketInputs:
    return MarketInputs(price=price, price_currency=currency, price_date=date(2026, 10, 8), **extra)  # type: ignore[arg-type]


def _evidence(periods=None, market=None, **kwargs):
    periods = periods or [_period(y) for y in (2022, 2023, 2024, 2025)]
    return build_stock_evidence("T", periods, DECISION, market or _market(), None, CONFIG, **kwargs)


def test_golden_metrics_for_a_fiscal_year_company() -> None:
    ev = _evidence()
    m = ev.metrics
    ni, rev = 100.0 * 1.1**3, 1000.0 * 1.1**3
    assert m["revenue"].value == pytest.approx(rev) and m["revenue"].basis == "FY"
    assert m["ebit_margin"].value == pytest.approx(200.0 / rev)
    assert m["roe"].value == pytest.approx(ni / ((1100.0 + 1200.0) / 2))  # average of opening FY2024 and closing FY2025
    nopat = 200.0 * (1 - 45.0 / 180.0)
    assert m["roic"].value == pytest.approx(nopat / (((1100 + 300 + 50 - 150) + (1200 + 300 + 50 - 150)) / 2))
    assert m["fcf"].value == pytest.approx(150.0) and m["net_debt"].value == pytest.approx(200.0)
    assert m["market_cap"].value == pytest.approx(500.0)  # 50 x 10
    assert m["ev"].value == pytest.approx(730.0)  # 500 + 200 net debt + 30 minority
    assert m["pe"].value == pytest.approx(500.0 / ni) and m["pb"].value == pytest.approx(500.0 / 1200.0)
    assert m["ev_ebit"].value == pytest.approx(730.0 / 200.0) and m["fcf_yield"].value == pytest.approx(150.0 / 500.0)
    assert m["net_debt_to_ebitda"].value == pytest.approx(200.0 / 260.0)
    assert m["revenue_cagr"].value == pytest.approx(0.10, abs=1e-9) and m["revenue_cagr"].source.startswith("FY2022->FY2025")


def test_only_facts_known_at_the_decision_time_are_used() -> None:
    periods = [_period(y) for y in (2022, 2023, 2024)] + [_period(2025, known="2026-11-01")]
    ev = _evidence(periods)
    assert ev.metrics["revenue"].as_of == "2024-12-31"  # FY2025 is only known in November
    only_future = _evidence([_period(2025, known="2026-11-01")], no_data_reason="x")
    assert only_future.metrics["revenue"].status == sm.UNAVAILABLE and only_future.metrics["revenue"].reason == "x"
    assert only_future.components["stock_value"].score_10 is None


def test_loss_is_not_meaningful_and_scores_zero_on_yield_inputs() -> None:
    ev = _evidence([_period(y, net_income_parent=-50.0, ebit=-20.0) for y in (2022, 2023, 2024, 2025)])
    assert ev.metrics["pe"].status == sm.NOT_MEANINGFUL and "loss" in ev.metrics["pe"].reason
    assert ev.metrics["pe"].value is None  # never a negative multiple
    ey = next(s for s in ev.components["stock_value"].inputs if s.key == "earnings_yield")
    assert ey.score == 0.0 and ey.value < 0  # a known loss scores the minimum, it is not treated as missing


def test_price_in_another_currency_needs_an_fx_rate() -> None:
    usd = _market(price=60.0, currency="USD")
    blocked = _evidence(market=usd)
    assert blocked.metrics["market_cap"].status == sm.UNAVAILABLE and "currency_mismatch" in blocked.metrics["pe"].reason
    converted = _evidence(market=_market(price=60.0, currency="USD", fx_to_reporting=0.9))
    assert converted.metrics["market_cap"].value == pytest.approx(60.0 * 0.9 * 10.0)
    pence = _evidence(market=_market(price=5000.0, currency="GBp", fx_to_reporting=1.2))  # 50 GBP x 1.2
    assert pence.metrics["market_cap"].value == pytest.approx(50.0 * 1.2 * 10.0)


def test_inconsistent_filing_share_count_falls_back_to_the_provider_count() -> None:
    periods = [_period(y, shares_outstanding=0.01) for y in (2022, 2023, 2024, 2025)]  # e.g. class A count against a class B price
    market = _market(shares_fallback=10.0, shares_fallback_known_at=datetime(2026, 10, 8, tzinfo=UTC))
    ev = _evidence(periods, market)
    assert ev.metrics["market_cap"].value == pytest.approx(500.0)
    assert any("differs from the provider count" in note for note in ev.notes)


def test_peer_median_excludes_the_instrument_and_shows_the_count() -> None:
    peers = {"pe": {"T": 99.0, "A": 10.0, "B": 20.0, "C": 30.0, "D": 40.0}}
    ev = _evidence(peer_values=peers)
    stat = ev.peer_stats["pe"]
    assert stat.count == 4 and stat.median == 25.0  # T itself is excluded
    own = ev.metrics["pe"].value
    assert stat.premium == pytest.approx(own / 25.0 - 1.0)
    assert ev.metrics["pe_vs_peers"].status == sm.OK
    few = _evidence(peer_values={"pe": {"A": 10.0, "B": 20.0}})
    assert few.metrics["pe_vs_peers"].status == sm.UNAVAILABLE and "3 needed" in few.metrics["pe_vs_peers"].reason


def test_valuation_history_percentile_uses_only_filings_known_at_each_date() -> None:
    periods = [_period(y) for y in (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025)]
    series = []
    day = date(2021, 11, 30)
    while day < date(2026, 10, 1):
        series.append((day, 50.0 + (day.year - 2021) * 2.0))
        year, month = (day.year + (day.month // 12), day.month % 12 + 1)
        day = (date(year, month, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    ev = _evidence(periods, _market(price_series=tuple(series)))
    assert ev.history_points >= 12
    assert 0.0 <= ev.metrics["pe_percentile"].value <= 1.0 and ev.metrics["pe_percentile"].status == sm.OK
    short = _evidence(market=_market(price_series=tuple(series[:3])))
    assert short.metrics["pe_percentile"].status == sm.UNAVAILABLE and "month-end" in short.metrics["pe_percentile"].reason


def test_reverse_valuation_is_unavailable_until_cost_of_equity_is_configured() -> None:
    ev = _evidence()
    assert ev.metrics["implied_growth_pe"].status == sm.UNAVAILABLE and "cost of equity" in ev.metrics["implied_growth_pe"].reason
    configured = {**CONFIG, "valuation": {**CONFIG["valuation"], "cost_of_equity": 0.09, "terminal_growth": 0.02}}
    ev = build_stock_evidence("T", [_period(y) for y in (2022, 2023, 2024, 2025)], DECISION, _market(), None, configured)
    pe, payout = ev.metrics["pe"].value, 30.0 / (100.0 * 1.1**3)
    assert ev.metrics["implied_growth_pe"].value == pytest.approx(0.09 - payout / pe)
    assert ev.metrics["implied_growth_dcf"].status == sm.OK


def test_components_score_from_available_inputs_and_state_what_is_missing() -> None:
    ev = _evidence()
    quality = ev.components["stock_quality"]
    roe = next(s for s in quality.inputs if s.key == "roe")
    assert roe.score == pytest.approx(10 * ev.metrics["roe"].value / 0.20, abs=1e-3)  # 0 at 0 %, 10 at 20 %
    assert quality.score_10 == pytest.approx(sum(s.score for s in quality.used) / len(quality.used), abs=1e-2)
    value = ev.components["stock_value"]
    assert value.score_10 is not None and "Not used" in value.why and "P/E vs own history" in value.why
    assert ev.components["analyst_revision"].score_10 is None and "no analyst estimate snapshot" in ev.components["analyst_revision"].why
    analyst = AnalystInputs(eps_current=4.4, eps_90d_ago=4.0, revisions_up_30d=4.0, revisions_down_30d=1.0, known_at=DECISION - timedelta(days=1))
    scored = build_stock_evidence("T", [_period(2025)], DECISION, _market(), analyst, CONFIG).components["analyst_revision"]
    assert scored.score_10 == pytest.approx((10.0 * (0.10 + 0.10) / 0.20 + 10.0 * 0.8) / 2, abs=1e-2)
    future = AnalystInputs(eps_current=4.4, eps_90d_ago=4.0, known_at=DECISION + timedelta(days=1))
    assert build_stock_evidence("T", [_period(2025)], DECISION, _market(), future, CONFIG).components["analyst_revision"].score_10 is None


def test_describe_stock_writes_numbers_and_keeps_the_reason_for_every_gap() -> None:
    from etf_cockpit.analysis.stock_text import describe_stock

    lines = describe_stock(_evidence(), CONFIG.get("text", {}), 5)
    text = "\n".join(lines)
    assert "EBIT margin 15.0%" in text  # 200 / 1331
    assert "P/E versus its own history: unavailable" in text  # no history in the fixture, so the reason is shown
    assert "Reverse valuation: unavailable" in text and "cost of equity" in text
    assert "None" not in text and "nan" not in text.casefold()


def test_peer_sentence_needs_enough_peers_like_the_metric_does() -> None:
    from etf_cockpit.analysis.stock_text import describe_stock

    one_peer = describe_stock(_evidence(peer_values={"pe": {"P1": 20.0}}), CONFIG.get("text", {}), 5)
    assert not any("peer median" in line for line in one_peer)
    assert any(line.startswith("P/E versus peers: unavailable") and "only 1 peer with" in line for line in one_peer)
    three = describe_stock(_evidence(peer_values={"pe": {"P1": 20.0, "P2": 22.0, "P3": 24.0}}), CONFIG.get("text", {}), 5)
    assert any("peer median" in line and "3 peers" in line for line in three)


def test_mixed_currency_roic_growth_and_ev_are_unavailable_and_minority_is_required() -> None:
    periods = [_period(y) for y in (2021, 2022, 2023, 2024, 2025)]
    opening = periods[3]
    periods[3] = replace(opening, values={**opening.values, "__currency_equity_parent": "USD"})
    roic = _evidence(periods=periods).metrics["roic"]
    assert roic.value is None and "currency_mismatch" in roic.reason

    changed = [_period(y) for y in (2022, 2023, 2024, 2025)]
    changed[0] = replace(changed[0], values={**changed[0].values, "__currency_revenue": "USD"})
    assert "currency_mismatch" in _evidence(periods=changed).metrics["revenue_cagr"].reason

    minority_mixed = [_period(y) for y in (2022, 2023, 2024, 2025)]
    minority_mixed[-1] = replace(minority_mixed[-1], values={**minority_mixed[-1].values, "__currency_minority_interest": "USD"})
    ev = _evidence(periods=minority_mixed).metrics["ev"]
    assert ev.value is None and "currency_mismatch" in ev.reason

    unreported = [replace(period, values={key: value for key, value in period.values.items() if key != "minority_interest"}) for period in changed]
    assert "missing_minority_interest" in _evidence(periods=unreported).metrics["ev"].reason
    explicit_zero = [replace(period, values={**period.values, "minority_interest": 0.0}) for period in unreported]
    assert _evidence(periods=explicit_zero).metrics["ev"].available


def test_dividend_yield_is_unavailable_when_the_trailing_year_is_incomplete() -> None:
    prices = pd.DataFrame(
        {
            "etf_id": ["T"] * 3,
            "date": pd.to_datetime(["2025-10-08", "2026-02-01", "2026-10-08"]),
            "close": [48.0, 49.0, 50.0],
            "currency": ["EUR"] * 3,
            "dividends": [0.0, None, 0.0],
        }
    )
    market = su.market_inputs(prices, None, "EUR", DECISION, pd.DataFrame(columns=store.FX_COLUMNS), CONFIG)
    assert market.dividends_per_share_12m is None
    metric = _evidence(market=market).metrics["dividend_yield"]
    assert metric.value is None and "incomplete_dividend_year" in metric.reason


def test_universe_evidence_cache_uses_the_complete_decision_timestamp(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    built = []

    def build(_records, _prices, decision_time, *, root=None):
        built.append(decision_time)
        return su.UniverseEvidence(decision_time)

    monkeypatch.setattr(su, "build_universe_evidence", build)
    su._CACHE.clear()
    records = []
    prices = pd.DataFrame()
    later = datetime(2026, 10, 9, 12, 50, tzinfo=UTC)
    earlier = datetime(2026, 10, 9, 12, 10, tzinfo=UTC)
    assert su.get_universe_evidence(records, prices, later, root=tmp_path).decision_time == later
    replay = su.get_universe_evidence(records, prices, earlier, root=tmp_path)
    assert replay.decision_time == earlier and built == [later, earlier]


def test_disabled_delisted_stock_keeps_historical_fundamentals_and_peer_contribution(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"id": "OLD", "instrument_type": "stock", "enabled": False, "lifecycle": "delisted", "lifecycle_date": "2026-06-30", "ticker": "OLD", "sector": "Industrials"},
        {"id": "T", "instrument_type": "stock", "enabled": True, "ticker": "T", "sector": "Industrials"},
    ]
    records = su.stock_records(rows, CONFIG)
    assert [record.instrument_id for record in records] == ["OLD", "T"]
    period_map = {instrument_id: [_period(year) for year in (2022, 2023, 2024, 2025)] for instrument_id in ("OLD", "T")}
    empty = pd.DataFrame(columns=store.PERIOD_COLUMNS)
    monkeypatch.setattr(store, "read_fundamentals", lambda _root: empty)
    monkeypatch.setattr(store, "read_snapshots", lambda _root: pd.DataFrame(columns=store.SNAPSHOT_COLUMNS))
    monkeypatch.setattr(store, "read_fx", lambda _root: pd.DataFrame(columns=store.FX_COLUMNS))
    monkeypatch.setattr(store, "periods_for", lambda instrument_id, _frame, _chain: period_map.get(instrument_id, []))
    monkeypatch.setattr(su, "load_user_peers", lambda _root: {"T": ["OLD"]})
    decision = datetime(2026, 3, 1, tzinfo=UTC)
    prices = pd.DataFrame(
        {"etf_id": ["OLD", "T"], "date": pd.to_datetime(["2026-02-27", "2026-02-27"]), "close": [50.0, 50.0], "currency": ["EUR", "EUR"], "dividends": [0.0, 0.0]}
    )
    evidence = su.build_universe_evidence(records, prices, decision, config=CONFIG)
    assert evidence.evidence["OLD"].metrics["revenue_cagr"].available
    assert evidence.peers["T"][0].instrument_id == "OLD"
    assert evidence.evidence["T"].peer_stats["revenue_cagr"].count == 1
