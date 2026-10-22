"""Reported shares: filing provenance, durable history and fail-closed valuation."""

from dataclasses import replace
from datetime import date, datetime, timezone

import pandas as pd
from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import MarketInputs, build_stock_evidence
from etf_cockpit.data import esef_provider, sec_edgar_provider, stock_fundamentals as store, stock_sources


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _sec_entry(value: float, filed: str, *, end: str = "2025-12-31") -> dict:
    # Synthetic values in the existing companyfacts fixture shape.
    return {"end": end, "filed": filed, "val": value}


def _payload(entries: list[dict]) -> dict:
    return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": entries}}}}}


def _periods(rows: list[dict]) -> list[sm.Period]:
    frame, _ = store.append_period_rows(pd.DataFrame(columns=store.PERIOD_COLUMNS), "T", rows)
    return store.periods_for("T", frame, ["sec_edgar", "esef", "yfinance"])


def _statement() -> sm.Period:
    return sm.Period(date(2025, 12, 31), "FY", _time("2026-02-10"), "USD", "sec_edgar", {
        "revenue": 1000.0, "net_income_parent": 100.0, "ebit": 200.0,
        "cfo": 220.0, "capex": 70.0, "equity_parent": 900.0,
        "minority_interest": 0.0, "ib_debt": 300.0, "lease_liabilities": 50.0, "cash_sti": 150.0,
    })


def test_sec_default_refresh_preserves_each_filing_and_end_of_day_gate(tmp_path, monkeypatch) -> None:
    payload = _payload([
        _sec_entry(1000.0, "2026-02-10"),
        _sec_entry(1000.0, "2026-03-01"),  # unchanged value, distinct publication
        _sec_entry(1200.0, "2026-04-01"),
        _sec_entry(9999.0, "invalid"),
    ])
    calls = []

    def fetch(url, agent):
        calls.append(url)
        return payload

    monkeypatch.setattr(stock_sources, "http_get_json", fetch)
    config = {"sources": {"chain": ["sec_edgar"]}}
    kwargs = {"root": tmp_path, "config": config, "environ": {"ETF_COCKPIT_SEC_EDGAR_USER_AGENT": "test contact@test.invalid"}}
    target = store.StockTarget("T", "Test", "T", cik="0000000001")
    first = store.refresh_stock_fundamentals([target], **kwargs)
    assert first.rows_added == 3 and not first.failures and len(calls) == 1
    assert store.refresh_stock_fundamentals([target], **kwargs).rows_added == 0
    frame = store.read_periods(tmp_path)
    assert len(frame) == 3 and set(frame["source"]) == {"sec_dei"}
    assert frame["available_at"].tolist() == ["2026-02-10", "2026-03-01", "2026-04-01"]
    assert frame["available_at"].equals(frame["known_at"])
    assert set(frame["period_end"]) == {"2025-12-31"}
    periods = store.periods_for("T", frame, ["sec_edgar"])
    assert sm.latest_reported_shares(periods, _time("2026-02-10T12:00:00")) is None
    assert sm.latest_reported_shares(periods, _time("2026-02-10T23:59:59")).values["shares_outstanding"] == 1000.0
    assert sm.latest_reported_shares(periods, _time("2026-03-31T23:59:59")).values["shares_outstanding"] == 1000.0
    assert sm.latest_reported_shares(periods, _time("2026-04-01T23:59:59")).values["shares_outstanding"] == 1200.0
    assert sm.known_periods(periods, _time("2026-05-01")) == []  # counts cannot set statement currency


def test_esef_named_concept_uses_existing_fact_shape_and_rooted_refresh(tmp_path) -> None:
    # Shape from test_pit_history_esef_adapter._fact. Retained report fixtures
    # contain weighted-average/certificate counts, not this outstanding concept.
    base = {"instrument_id": "T", "taxonomy": "ifrs-full", "concept": "NumberOfSharesOutstanding",
            "unit": "shares", "start": None, "end": "2025-12-31", "instant": "2025-12-31",
            "dimensions": "", "consolidation_scope": "consolidated"}
    facts = pd.DataFrame([
        {**base, "value": 1000.0, "known_at": "2026-02-10T12:00:00+00:00", "date_added": "2026-02-10T12:00:00+00:00"},
        {**base, "value": 1200.0, "known_at": "2026-04-01T12:00:00+00:00", "filed": "2026-04-01T12:00:00+00:00"},
        {**base, "value": 9999.0, "known_at": "2026-02-10T12:00:00+00:00", "dimensions": '{"class": "A"}'},
        {**base, "value": 9999.0, "known_at": "2026-02-10T12:00:00+00:00", "concept": "WeightedAverageNumberOfOrdinarySharesOutstandingBasic"},
        {**base, "value": 9999.0, "known_at": None},
        {**base, "value": 9999.0, "known_at": "2026-02-10T12:00:00+00:00", "instrument_id": "OTHER"},
    ])
    path = tmp_path / "data" / "clean" / "statement_facts.parquet"
    path.parent.mkdir(parents=True)
    facts.to_parquet(path)
    report = store.refresh_stock_fundamentals(
        [store.StockTarget("T", "Test", "T")], root=tmp_path,
        config={"sources": {"chain": ["esef"]}}, environ={},
    )
    assert report.rows_added == 2 and not report.failures
    frame = store.read_periods(tmp_path)
    assert set(frame["source"]) == {"esef_reported"} and frame["available_at"].equals(frame["known_at"])
    periods = store.periods_for("T", frame, ["esef"])
    assert sm.latest_reported_shares(periods, _time("2026-02-10T11:59:59")) is None
    assert sm.latest_reported_shares(periods, _time("2026-02-10T12:00:00")).values["shares_outstanding"] == 1000.0
    assert sm.latest_reported_shares(periods, _time("2026-04-01T12:00:00")).values["shares_outstanding"] == 1200.0
    # A later publication never marks the original count conflicted retroactively.
    assert esef_provider.parse_reported_shares(facts.iloc[:2], source_ref="test")[0]["shares_outstanding"] == 1000.0
    # Local-only imports carry acquisition known_at, not a publication date.
    assert esef_provider.parse_reported_shares(facts.iloc[:2].drop(columns=["filed", "date_added"]), source_ref="test") == []
    delayed = facts.iloc[:1].assign(known_at="2026-05-01T12:00:00+00:00")
    delayed_rows = esef_provider.parse_reported_shares(delayed, source_ref="test")
    assert delayed_rows[0]["available_at"] == "2026-02-10T12:00:00+00:00"
    assert sm.latest_reported_shares(_periods(delayed_rows), _time("2026-04-01")) is None
    later_publication = esef_provider.parse_reported_shares(facts.iloc[1:2], source_ref="test")
    # Learning an older filing late must not replace a newer published count.
    assert sm.latest_reported_shares(_periods([*delayed_rows, *later_publication]), _time("2026-05-02")).values["shares_outstanding"] == 1200.0


def test_latest_publication_wins_and_ambiguous_or_invalid_counts_fail_closed() -> None:
    rows = sec_edgar_provider.parse_reported_shares(_payload([
        _sec_entry(1000.0, "2026-02-10"),
        _sec_entry(1200.0, "2026-03-01", end="2025-11-30"),  # newest publication, older instant
        _sec_entry(1300.0, "2026-04-01"),
        _sec_entry(1400.0, "2026-04-01"),  # two classes: cannot infer total
        _sec_entry(float("inf"), "2026-05-01"),
    ]), source_ref="test")
    periods = _periods(list(reversed(rows)))
    assert sm.latest_reported_shares(periods, _time("2026-03-02")).values["shares_outstanding"] == 1200.0
    assert sm.latest_reported_shares(periods, _time("2026-04-02")) is None
    assert sm.latest_reported_shares(periods, _time("2026-05-02")) is None
    # A mismatched availability timestamp cannot expose a fact at its earlier known_at.
    delayed = {**rows[0], "available_at": "2026-06-01"}
    assert sm.latest_reported_shares(_periods([delayed]), _time("2026-05-02")) is None
    missing = {**rows[0], "available_at": None}
    assert sm.latest_reported_shares(_periods([missing]), _time("2026-05-02")) is None


def test_stock_value_uses_reported_shares_at_each_decision_and_history_date() -> None:
    shares = _periods(sec_edgar_provider.parse_reported_shares(_payload([
        _sec_entry(10.0, "2026-02-10"), _sec_entry(12.0, "2026-04-01"),
    ]), source_ref="test"))
    config = store.load_stock_config()
    market = MarketInputs(price=50.0, price_currency="USD", price_date=date(2026, 3, 31),
                          price_series=((date(2026, 2, 28), 40.0), (date(2026, 3, 31), 50.0)))
    periods = [_statement(), *shares]
    early = build_stock_evidence("T", periods, _time("2026-03-31T23:59:59"), market, None, config)
    assert early.metrics["market_cap"].value == 500.0 and early.reporting_currency == "USD"
    assert early.metrics["pe"].value == 5.0 and early.history_points == 2
    assert early.components["stock_value"].score_10 is not None
    assert "sec_dei" in early.metrics["market_cap"].source
    late = build_stock_evidence("T", periods, _time("2026-04-02"), replace(market, price=60.0, price_date=date(2026, 4, 1)), None, config)
    assert late.metrics["market_cap"].value == 720.0 and late.metrics["pe"].value == 7.2
    without_future = build_stock_evidence("T", periods[:-1], _time("2026-03-31T23:59:59"), market, None, config)
    assert early.metrics == without_future.metrics and early.components == without_future.components


def test_no_reported_count_rejects_eps_net_income_derived_counts_and_snapshot() -> None:
    config = store.load_stock_config()
    market = MarketInputs(price=50.0, price_currency="USD", price_date=date(2026, 3, 31),
                          shares_fallback=10.0, shares_fallback_known_at=_time("2026-02-10"))
    base = _statement()
    for values, sources, statuses in [
        ({"eps": 10.0}, {}, {}),  # income / EPS would yield 10, but is forbidden
        ({"shares_outstanding": 10.0}, {"shares_outstanding": "yfinance"}, {}),
        ({"shares_outstanding": 10.0}, {"shares_outstanding": "sec_dei"}, {"shares_outstanding": "derived"}),
    ]:
        period = replace(base, values={**base.values, **values}, field_sources=sources, value_status=statuses)
        ev = build_stock_evidence("T", [period], _time("2026-03-31"), market, None, config)
        assert ev.metrics["market_cap"].status == sm.UNAVAILABLE
        assert ev.metrics["pe"].value is None
        # With no dividend history either, every valuation input is unavailable.
        assert ev.components["stock_value"].score_10 is None


def test_provider_market_cap_and_share_snapshot_cross_checks_still_block() -> None:
    shares = _periods(sec_edgar_provider.parse_reported_shares(_payload([_sec_entry(10.0, "2026-02-10")]), source_ref="test"))
    market = MarketInputs(price=50.0, price_currency="USD", price_date=date(2026, 3, 31))
    config = store.load_stock_config()
    for mismatch in (replace(market, market_cap_provider=5000.0),
                     replace(market, shares_fallback=100.0, shares_fallback_known_at=_time("2026-02-10"))):
        ev = build_stock_evidence("T", [_statement(), *shares], _time("2026-03-31"), mismatch, None, config)
        assert ev.metrics["market_cap"].status == sm.UNAVAILABLE and ev.metrics["pe"].value is None
        assert "differ" in ev.metrics["market_cap"].reason
    assert sm.price_shares_consistency(50.0, 10.0, 500.0) == (True, None)
    assert sm.price_shares_consistency(50.0, 10.0, 5000.0)[0] is False
    assert sm.price_shares_consistency(50.0, 10.0, None) == (None, None)
