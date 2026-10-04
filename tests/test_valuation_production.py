from datetime import date

import pandas as pd

from etf_cockpit.application import ui_facade, valuation_views


def _statement_facts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "instrument_id": "ACME",
                "canonical_metric": metric,
                "value": value,
                "currency": "USD",
                "period_end": "2025-12-31",
                "filed": "2026-01-01",
                "available_at": "2026-01-01T00:00:00Z",
                "source_id": f"filing-{metric}",
                "consolidation_scope": "consolidated",
            }
            for metric, value in (
                ("diluted_shares", 10.0),
                ("debt", 30.0),
                ("cash", 5.0),
                ("lease_liabilities", 3.0),
                ("restricted_cash", 1.0),
            )
        ]
    )


def _local_market_sources(monkeypatch, tmp_path) -> None:
    price_path = tmp_path / "prices.parquet"
    fx_path = tmp_path / "fx.parquet"
    price_path.touch()
    fx_path.touch()
    monkeypatch.setattr(valuation_views, "PRICE_PARQUET", price_path)
    monkeypatch.setattr(valuation_views, "FX_CLEAN_PATH", fx_path)
    monkeypatch.setattr(
        valuation_views,
        "load_prices",
        lambda _path: pd.DataFrame(
            [
                {"instrument_id": "ACME", "date": date(2026, 1, 2), "close": 20.0, "currency": "EUR", "source": "local-quote"},
                {"instrument_id": "ACME", "date": date(2026, 1, 5), "close": 99.0, "currency": "EUR", "source": "same-day-close"},
                {"instrument_id": "ACME", "date": date(2026, 1, 6), "close": 100.0, "currency": "EUR", "source": "future-quote"},
            ]
        ),
    )
    monkeypatch.setattr(
        valuation_views,
        "load_fx_rates",
        lambda _path: pd.DataFrame(
            [
                {"as_of_date": "2026-01-02", "pair": "EURUSD", "rate": 1.1, "source": "local-fx"},
                {"as_of_date": "2026-01-05", "pair": "EURUSD", "rate": 1.2, "source": "after-quote-fx"},
            ]
        ),
    )


def test_valuation_market_inputs_are_cut_off_and_currency_aligned(monkeypatch, tmp_path) -> None:
    _local_market_sources(monkeypatch, tmp_path)

    result = ui_facade.load_valuation_market_inputs(
        "ACME",
        statements=_statement_facts(),
        decision_time="2026-01-05T16:00:00Z",
    )

    assert result["status"] == "available"
    assert result["price_timestamp"] == "2026-01-02"
    assert result["price_timestamp_precision"] == "date_only_close"
    assert result["share_price_native"] == 20.0
    assert result["share_price"] == 22.0
    assert result["shares_outstanding"] == 10.0
    assert result["market_cap"] == 220.0
    assert result["net_debt"] == 25.0
    assert result["enterprise_value"] == 247.0
    assert result["enterprise_value_adjustments"]["status"] == "available"
    assert result["currency_conversion_timestamp"] == "2026-01-02"
    assert result["currency_conversion_source_ids"] == ["local-fx"]
    assert result["decision_time"] == "2026-01-05T16:00:00+00:00"


def test_valuation_reference_rate_uses_explicit_horizon_and_decision_time(monkeypatch, tmp_path) -> None:
    _local_market_sources(monkeypatch, tmp_path)
    captured = {}

    def select_rate(_warehouse, *, root, mappings, currency, horizon_years, decision_time):
        captured.update(currency=currency, horizon=horizon_years, decision_time=decision_time)
        return {"status": "available", "rate": 0.04, "currency": currency, "available_at": "2026-01-03T00:00:00Z", "source_id": "curve-source"}

    monkeypatch.setattr(ui_facade.MacroWarehouse, "risk_free_rate", select_rate)
    monkeypatch.setattr(valuation_views, "load_risk_free_proxy_mappings", lambda: ())

    result = ui_facade.load_valuation_market_inputs(
        "ACME",
        statements=_statement_facts(),
        decision_time="2026-01-05T16:00:00Z",
        assumptions={"forecast_years": 5},
    )

    assert result["risk_free_reference"]["rate"] == 0.04
    assert captured == {"currency": "USD", "horizon": 5.0, "decision_time": "2026-01-05T16:00:00+00:00"}
    assert result["risk_free_reference"]["available_at"] <= result["decision_time"]


def test_valuation_market_inputs_require_diluted_shares_and_quote_currency(monkeypatch, tmp_path) -> None:
    _local_market_sources(monkeypatch, tmp_path)
    without_diluted = _statement_facts().loc[lambda frame: frame["canonical_metric"].ne("diluted_shares")]

    missing_shares = ui_facade.load_valuation_market_inputs(
        "ACME", statements=without_diluted, decision_time="2026-01-05T23:59:59Z"
    )
    assert missing_shares["status"] == "unavailable"
    assert "diluted share count" in missing_shares["reason"]

    monkeypatch.setattr(
        valuation_views,
        "load_prices",
        lambda _path: pd.DataFrame([{"instrument_id": "ACME", "date": date(2026, 1, 2), "close": 20.0}]),
    )
    missing_currency = ui_facade.load_valuation_market_inputs(
        "ACME", statements=_statement_facts(), decision_time="2026-01-05T23:59:59Z"
    )
    assert missing_currency["status"] == "unavailable"
    assert "no recorded currency" in missing_currency["reason"]
