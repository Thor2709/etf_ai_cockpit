"""Wave 2 train F: stock value inputs (2026-11-23)."""

from dataclasses import replace
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.analysis.stock_universe import as_traded_close, market_inputs, with_as_traded_factors
from etf_cockpit.data.stock_fundamentals import load_stock_config


def _legacy_prefix() -> pd.DataFrame:
    """The oldest row was stored before per-bar action evidence (False); the later rows, with a split, are evidenced."""

    return pd.DataFrame({
        "etf_id": ["NVDA"] * 4,
        "date": pd.to_datetime(["2022-10-17", "2022-11-30", "2024-06-10", "2024-06-11"]),
        "close": [11.888, 12.0, 121.0, 120.0],
        "adjusted_close": [11.5, 11.6, 120.5, 119.5],
        "volume": [100.0] * 4,
        "currency": ["USD"] * 4,
        "stock_splits": [0.0, 0.0, 10.0, 0.0],
        "dividends": [0.0] * 4,
        "actions_evidenced": [False, True, True, True],
    })


def _closes(prices: pd.DataFrame, day: date) -> list[tuple[float | None, str | None]]:
    """The close from the full series and from a decision-time cut that carries the full-series factors."""

    carried = with_as_traded_factors(prices)
    return [as_traded_close(prices, day), as_traded_close(carried.loc[carried["date"].dt.date <= day], day)]


def test_close_is_restored_when_its_row_and_every_later_row_are_evidenced():
    # Only the later rows' splits are reversed; they and the close's own row are evidenced, so the close is provable.
    assert _closes(_legacy_prefix(), date(2022, 11, 30)) == [(120.0, None)] * 2
    assert _closes(_legacy_prefix(), date(2024, 6, 11)) == [(120.0, None)] * 2


def test_unevidenced_split_in_the_reversed_window_stays_unavailable():
    prices = _legacy_prefix()
    prices.loc[2, "actions_evidenced"] = False  # the 10:1 split row is not evidenced
    for value, reason in _closes(prices, date(2022, 11, 30)):
        assert value is None and ("actions_evidence_missing" in reason or "split_history_invalid" in reason)
    # An unevidenced later row fails closed even when it shows no split, and so does an unevidenced close row.
    prices = _legacy_prefix()
    prices.loc[3, "actions_evidenced"] = False
    for when, frame in ((date(2024, 6, 10), prices), (date(2022, 10, 17), _legacy_prefix())):
        value, reason = as_traded_close(frame, when)
        assert value is None and "actions_evidence_missing" in reason


def test_unevidenced_dividend_rows_give_no_dividend_yield():
    prices = _legacy_prefix()
    prices.loc[1, ["date", "actions_evidenced"]] = [pd.Timestamp("2023-06-13"), False]  # in the trailing year
    market = market_inputs(prices, None, "USD", datetime(2024, 6, 12, 12, tzinfo=timezone.utc), pd.DataFrame(),
                           load_stock_config())
    assert market.price == 120.0
    assert market.dividends_per_share_12m is None and "actions_evidence_missing" in market.dividend_reason


def test_sector_and_country_spellings_map_to_one_label():
    from etf_cockpit.analysis.stock_labels import country_label, sector_label

    # Yahoo sector names, config spellings and GICS names seen in the 2026-11-22 store.
    for spellings, label in (
        (("Financial Services", "Financials", "Financial exchanges"), "Financials"),
        (("Basic Materials", "Materials"), "Materials"),
        (("Technology", "Information Technology"), "Information Technology"),
        (("Consumer Cyclical", "Consumer Discretionary", "Consumer discretionary"), "Consumer Discretionary"),
        (("Consumer Defensive", "Consumer Staples"), "Consumer Staples"),
        (("Healthcare", "Health Care"), "Health Care"),
        (("Communication", "Communication Services"), "Communication Services"),
        (("Unknown", "", None), ""),
    ):
        assert {sector_label(item) for item in spellings} == {label}
    assert sector_label("Banks") == "Banks"  # the bank exclusion label (scope.excluded_sectors) is kept
    for spellings, label in (
        (("South Korea", "south korea", "Korea (South)", "Korea, Republic of", "KR"), "South Korea"),
        (("Taiwan", "taiwan", "Taiwan Region"), "Taiwan"),
        (("Cayman Islands", "Cayman Island"), "Cayman Islands"),
        (("Hong Kong", "HK"), "Hong Kong"),
        (("United Kingdom", "united kingdom", "GB"), "United Kingdom"),
        (("", None), ""),
    ):
        assert {country_label(item) for item in spellings} == {label}


def test_full_history_action_fetch_heals_unchanged_legacy_bars():
    from etf_cockpit.data.import_pipeline import stamp_price_availability

    legacy = _legacy_prefix().assign(actions_evidenced=False)
    stored = stamp_price_availability(None, legacy, retrieved_at=datetime(2026, 11, 20, 9, 47, tzinfo=timezone.utc))
    # A fetch that did not request actions never sets the flag.
    unproven = stamp_price_availability(stored, legacy, retrieved_at=datetime(2026, 11, 21, tzinfo=timezone.utc))
    assert not unproven["actions_evidenced"].any()
    # The same values from an action-requesting fetch: the flag heals, every other stamp and value is kept.
    healed = stamp_price_availability(stored, legacy.assign(actions_evidenced=True),
                                      retrieved_at=datetime(2026, 11, 22, tzinfo=timezone.utc))
    assert healed["actions_evidenced"].tolist() == [True] * 4
    pd.testing.assert_frame_equal(healed.drop(columns="actions_evidenced"), stored.drop(columns="actions_evidenced"))
    value, reason = as_traded_close(healed, date(2022, 10, 17))
    assert value == pytest.approx(118.88) and reason is None


def test_cohort_profile_uses_one_sector_and_country_label():
    from etf_cockpit.analysis.stock_universe import StockRecord, _profile

    decision = datetime(2026, 11, 22, tzinfo=timezone.utc)
    config = load_stock_config()
    record = StockRecord("X", "X", "X", "USD", "KR", "Information Technology")
    profile = _profile(record, {"sector": "Technology", "country": "South Korea"}, pd.DataFrame(), config, decision)
    assert (profile.sector, profile.region) == ("Information Technology", "South Korea")
    # A blank config region is filled from the snapshot country; a blank snapshot sector falls back to the config.
    blank = replace(record, region="", sector="Consumer Cyclical")
    profile = _profile(blank, {"sector": "", "country": "Korea, Republic of"}, pd.DataFrame(), config, decision)
    assert (profile.sector, profile.region) == ("Consumer Discretionary", "South Korea")
