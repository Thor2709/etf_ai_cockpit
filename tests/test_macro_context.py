from __future__ import annotations

import pandas as pd

from etf_cockpit.features.macro import build_macro_context


def _prices(days: int = 240) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    rows = []
    for index, current in enumerate(dates):
        rows.extend(
            [
                {"date": current, "etf_id": "EQUITY", "adjusted_close": 100 + index * 0.2},
                {"date": current, "etf_id": "BOND", "adjusted_close": 100 + index * 0.03},
                {"date": current, "etf_id": "GOLD", "adjusted_close": 100 + index * 0.08},
            ]
        )
    return pd.DataFrame(rows)


def _instruments() -> list[dict[str, str]]:
    return [
        {"id": "EQUITY", "name": "Global equity proxy", "ticker": "EQ", "asset_class": "equity"},
        {"id": "BOND", "name": "Government bond proxy", "ticker": "BND", "asset_class": "bond"},
        {"id": "GOLD", "name": "Gold defensive proxy", "ticker": "GLD", "asset_class": "commodity", "theme": "gold"},
    ]


def test_macro_context_exposes_proxies_breadth_regime_and_provenance() -> None:
    report = build_macro_context(_prices(), _instruments())

    assert report["status"] == "available"
    assert report["authority"] == "context_only"
    assert report["execution_allowed"] is False
    assert report["executable_authority"] is False
    assert report["context_only"] is True
    assert report["score_eligible"] is False
    assert report["provenance"] == "local adjusted_close price snapshot"
    assert report["breadth"]["status"] == "available"
    assert report["volatility"]["status"] == "available"
    assert report["regime"]["label"] in {"risk-on", "neutral", "defensive", "stressed", "unknown"}
    assert report["regime"]["source_label"] != report["regime"]["label"]
    assert {row["proxy"] for row in report["proxy_rows"]} == {"equity", "bond_cash", "gold_defensive"}
    assert all(row["status"] == "available" for row in report["proxy_rows"])


def test_macro_context_keeps_missing_proxy_explicit() -> None:
    report = build_macro_context(_prices(), _instruments()[:1])

    rows = {row["proxy"]: row for row in report["proxy_rows"]}
    assert rows["equity"]["status"] == "available"
    assert rows["bond_cash"]["status"] == "unavailable"
    assert rows["gold_defensive"]["status"] == "unavailable"
    assert report["status"] == "available_with_gaps"


def test_macro_context_rejects_raw_close_only_input() -> None:
    prices = _prices().rename(columns={"adjusted_close": "close"})

    report = build_macro_context(prices, _instruments())

    assert report["status"] == "unavailable"
    assert report["execution_allowed"] is False
    assert report["regime"]["label"] == "Regime unavailable"


def test_macro_context_rejects_explicitly_unadjusted_series() -> None:
    prices = _prices()
    prices["is_adjusted"] = True
    prices.loc[0, "is_adjusted"] = False

    report = build_macro_context(prices, _instruments())

    assert report["status"] == "unavailable"
    assert "non-adjusted" in report["regime"]["summary"]


def test_macro_context_excludes_a_proxy_after_the_fill_bound() -> None:
    prices = _prices()
    prices = prices[~((prices["etf_id"] == "GOLD") & (prices["date"] > pd.Timestamp("2024-11-01")))]

    report = build_macro_context(prices, _instruments())

    gold = next(row for row in report["proxy_rows"] if row["proxy"] == "gold_defensive")
    assert gold["freshness_status"] == "stale"
    assert report["breadth"]["instrument_count"] == 2
