"""Bughunt A (#955): corporate actions, adjusted returns and OHLCV discrepancy checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
import math
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.application import market_views
from etf_cockpit.data.market_adjustments import (
    CorporateAction,
    CorporateActionCoverage,
    CorporateActionCoverageStore,
    CorporateActionStore,
    FXObservation,
    FXObservationStore,
    MarketAdjustmentError,
    apply_total_return_adjustments,
    reconcile_adjustments,
    selected_currency_return,
)
from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.tiingo_provider import TiingoProvider
from etf_cockpit.data.ohlcv_discrepancy import (
    OhlcvNormalisationError,
    build_discrepancy_report,
    normalise_ohlcv,
)

ASSET = "US-ETF-001"


def _action(
    action_id: str,
    action_type: str,
    *,
    ex_date: str = "2024-01-11",
    payable_at: str = "2024-01-31",
    source: str = "provider:a",
    ratio: float | None = None,
    amount: float | None = None,
    currency: str = "USD",
) -> CorporateAction:
    return CorporateAction(
        action_id=action_id,
        instrument_id=ASSET,
        action_type=action_type,
        announced_at="2023-12-15T00:00:00Z",
        effective_at="2024-01-10T00:00:00Z",
        ex_date=ex_date,
        payable_at=payable_at,
        known_at="2024-01-02T00:00:00Z",
        revision=1,
        source=source,
        source_id=f"{source}:{action_id}",
        source_checksum=f"sha256:{action_id}:{source}",
        ratio=ratio,
        amount=amount,
        currency=currency,
    )


def _prices(dates: list[str], closes: list[float], **extra: object) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "close": closes, **extra})


SPLIT_DATES = ["2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12", "2024-01-31", "2024-02-01"]
SPLIT_CLOSES = [100.0, 100.0, 50.0, 50.0, 50.0, 50.0]


# --- A010-N002 / A110-N001 -------------------------------------------------------------


@pytest.mark.parametrize("convention", ["reinvest_on_ex_date", "cash_on_payable_date", "split_adjusted"])
def test_split_applies_on_ex_date_not_payable_date(convention: str) -> None:
    split = _action("SPLIT-1", "split", ratio=2.0)
    result = apply_total_return_adjustments(_prices(SPLIT_DATES, SPLIT_CLOSES), (split,), convention=convention)

    assert result.status == "available"
    frame = result.frame
    assert frame["price_return"].iloc[2] == pytest.approx(0.0)
    assert frame["price_return"].iloc[4] == pytest.approx(0.0)
    assert frame["quantity_factor"].tolist()[2] == 2.0
    assert frame["quantity_factor"].tolist()[4] == 1.0


def test_cross_provider_duplicate_split_is_applied_once() -> None:
    first = _action("SPLIT-A", "split", ratio=2.0, source="provider:a")
    second = _action("SPLIT-B", "split", ratio=2.0, source="provider:b", currency="EUR", payable_at="2024-01-30")

    sequence = apply_total_return_adjustments(prices=(100.0, 50.0), actions=(first, second))
    assert sequence.status == "available"
    assert sequence.total_return == pytest.approx(0.0)
    assert sequence.applied_ratio == 2.0
    assert reconcile_adjustments((100.0, 50.0), sequence.adjusted_prices, (first, second)).available

    framed = apply_total_return_adjustments(_prices(SPLIT_DATES, SPLIT_CLOSES), (first, second))
    assert framed.status == "available"
    assert framed.frame["quantity_factor"].iloc[2] == 2.0
    assert framed.total_return == pytest.approx(0.0)


def test_same_event_with_different_ratios_is_a_conflict_that_keeps_raw() -> None:
    first = _action("SPLIT-A", "split", ratio=2.0, source="provider:a")
    second = _action("SPLIT-B", "split", ratio=4.0, source="provider:b")

    sequence = apply_total_return_adjustments(prices=(100.0, 50.0), actions=(first, second))
    assert sequence.status == "quarantined"
    framed = apply_total_return_adjustments(_prices(SPLIT_DATES, SPLIT_CLOSES), (first, second))
    assert framed.status == "quarantined"
    assert framed.frame["raw_close"].tolist() == SPLIT_CLOSES
    assert framed.frame["adjusted_close"].isna().all()
    assert framed.frame["price_return"].isna().all()
    assert framed.price_return is None and framed.total_return is None


def test_dividend_conflict_blocks_total_return_only() -> None:
    low = _action("DIV-1", "dividend", amount=1.0, source="provider:a")
    high = _action("DIV-2", "dividend", amount=1.5, source="provider:b")
    # Same action id from two providers disagreeing on the amount.
    high = replace(high, action_id="DIV-1")
    result = apply_total_return_adjustments(_prices(SPLIT_DATES, [100.0, 100.0, 99.0, 99.0, 99.0, 99.0]), (low, high))

    assert result.status == "quarantined"
    assert result.frame["total_return_index"].isna().all()
    assert result.frame["price_return"].iloc[2:].notna().all()
    assert result.price_return == pytest.approx(-0.01)
    assert result.total_return is None


# --- A010-N003 / A010-N001 -------------------------------------------------------------


def test_duplicate_candle_does_not_double_apply_split() -> None:
    split = _action("SPLIT-1", "split", ratio=2.0)
    dates = ["2024-01-10", "2024-01-11", "2024-01-11", "2024-01-12"]
    result = apply_total_return_adjustments(_prices(dates, [100.0, 50.0, 50.0, 50.0]), (split,))

    assert result.status == "available"
    assert len(result.frame) == 3
    assert result.frame["quantity_factor"].tolist() == [1.0, 2.0, 1.0]
    assert result.frame["local_total_return"].iloc[1:].tolist() == pytest.approx([0.0, 0.0])
    assert any(item.startswith("collapsed_duplicate_candles") for item in result.warnings)


def test_conflicting_duplicate_candle_is_quarantined() -> None:
    dates = ["2024-01-10", "2024-01-11", "2024-01-11"]
    result = apply_total_return_adjustments(_prices(dates, [100.0, 50.0, 52.0]), ())

    assert result.status == "quarantined"
    assert "conflicting_duplicate_candle:2024-01-11" in result.warnings
    assert result.frame["adjusted_close"].isna().all()


def test_old_out_of_range_action_does_not_quarantine_chart() -> None:
    old = _action("SPLIT-OLD", "split", ratio=2.0, ex_date="2019-05-02", payable_at="2019-05-10")
    future = _action("DIV-FUTURE", "dividend", amount=1.0, ex_date="2030-01-02", payable_at="2030-01-10")
    result = apply_total_return_adjustments(_prices(["2024-01-10", "2024-01-11", "2024-01-12"], [100.0, 101.0, 102.0]), (old, future))

    assert result.status == "available"
    assert result.total_return == pytest.approx(0.02)
    assert any(item.startswith("ignored_out_of_range_action:SPLIT-OLD") for item in result.warnings)
    assert any(item.startswith("ignored_out_of_range_action:DIV-FUTURE") for item in result.warnings)


def test_conflicting_old_action_is_ignored_with_the_rest_of_the_chart() -> None:
    old_a = _action("SPLIT-OLD-A", "split", ratio=2.0, ex_date="2019-05-02", source="provider:a")
    old_b = _action("SPLIT-OLD-B", "split", ratio=3.0, ex_date="2019-05-02", source="provider:b")
    result = apply_total_return_adjustments(_prices(["2024-01-10", "2024-01-11"], [100.0, 101.0]), (old_a, old_b))
    assert result.status == "available"


# --- A010-N004 -------------------------------------------------------------------------


def test_dividend_currency_is_reconciled_with_price_currency() -> None:
    dividend = _action("DIV-EUR", "dividend", amount=1.0, currency="EUR")
    dates = ["2024-01-10", "2024-01-11", "2024-01-12"]
    mismatch = apply_total_return_adjustments(_prices(dates, [100.0, 99.0, 99.0], currency="USD"), (dividend,))
    assert mismatch.status == "unavailable"
    assert any(item.startswith("action_currency_mismatch:DIV-EUR") for item in mismatch.warnings)
    assert mismatch.frame["total_return_index"].isna().all()
    assert mismatch.price_return == pytest.approx(-0.01)

    same = apply_total_return_adjustments(_prices(dates, [100.0, 99.0, 99.0], currency="EUR"), (dividend,))
    assert same.status == "available"
    assert same.total_return == pytest.approx(0.0)

    mixed = pd.concat([_prices(dates[:2], [100.0, 99.0], currency="USD"), _prices(dates[2:], [99.0], currency="EUR")])
    assert apply_total_return_adjustments(mixed, ()).status == "unavailable"


# --- A110-N002 -------------------------------------------------------------------------


def test_split_adjusted_price_return_excludes_dividend_and_total_return_includes_it() -> None:
    dividend = _action("DIV-1", "dividend", amount=5.0)
    split = _action("SPLIT-1", "split", ratio=2.0, ex_date="2024-01-12", payable_at="2024-01-12")
    dates = ["2024-01-10", "2024-01-11", "2024-01-12"]
    result = apply_total_return_adjustments(_prices(dates, [100.0, 95.0, 47.5]), (dividend, split))

    assert result.status == "available"
    assert result.price_return == pytest.approx(-0.05)
    frame = result.frame
    assert frame["price_return"].iloc[1] == pytest.approx(-0.05)
    assert frame["local_total_return"].iloc[1] == pytest.approx(0.0)
    assert frame["price_return"].iloc[2] == pytest.approx(0.0)
    assert result.total_return == pytest.approx(0.0)
    assert frame["price_return_index"].iloc[-1] == pytest.approx(95.0)
    assert frame["total_return_index"].iloc[-1] == pytest.approx(100.0)
    assert frame["adjusted_close_basis"].eq("total_return").all()
    assert frame["price_adjusted_close"].iloc[-1] == pytest.approx(47.5)


# --- A110-N003 / A010-N005 -------------------------------------------------------------


def test_missing_adjusted_close_is_not_replaced_by_raw_close() -> None:
    raw = pd.DataFrame({"Date": ["2024-01-10", "2024-01-11"], "Close": [100.0, 101.0]})
    normalised = normalise_ohlcv(raw, source="stooq", symbol="VWCE", currency="EUR")
    assert normalised["adjusted_close"].isna().all()
    assert not normalised["is_adjusted"].any()

    adjusted = pd.DataFrame({"Date": ["2024-01-10", "2024-01-11"], "Close": [100.0, 101.0], "Adj Close": [50.0, 50.5]})
    report = build_discrepancy_report(raw, adjusted, symbol="VWCE", primary_name="stooq", secondary_name="yfinance")
    assert not [row for row in report.discrepancies if row.field == "adjusted_close"]
    missing = [row for row in report.discrepancies if row.field == "missing_field"]
    assert len(missing) == 1 and "adjusted_close" in missing[0].message
    assert report.quality_cap < 1.0


# --- A110-N004 / A123-N002 ---------------------------------------------------------------


def test_relative_tolerance_is_symmetric_across_provider_swap() -> None:
    low = pd.DataFrame({"Date": ["2024-01-10"], "Close": [100.0], "Volume": [1000.0]})
    high = pd.DataFrame({"Date": ["2024-01-10"], "Close": [100.4], "Volume": [1052.0]})
    forward = build_discrepancy_report(low, high, symbol="X", primary_name="a", secondary_name="b")
    backward = build_discrepancy_report(high, low, symbol="X", primary_name="b", secondary_name="a")
    assert sorted(row.field for row in forward.discrepancies if row.field != "missing_field") == sorted(
        row.field for row in backward.discrepancies if row.field != "missing_field"
    )
    assert forward.quality_cap == backward.quality_cap
    # 52 / 1052 = 4.94% is inside the 5% volume tolerance whichever provider is primary.
    assert not forward.has_discrepancies and not backward.has_discrepancies


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, True, "0.1", 1.0, 5.0])
def test_unsafe_custom_tolerance_is_rejected(bad: object) -> None:
    frame = pd.DataFrame({"Date": ["2024-01-10"], "Close": [100.0]})
    with pytest.raises(ValueError, match="tolerance"):
        build_discrepancy_report(frame, frame, tolerances={"close": bad})  # type: ignore[dict-item]


def test_safe_custom_tolerance_is_accepted() -> None:
    frame = pd.DataFrame({"Date": ["2024-01-10"], "Close": [100.0]})
    other = pd.DataFrame({"Date": ["2024-01-10"], "Close": [101.0]})
    assert not build_discrepancy_report(frame, other, tolerances={"close": 0.05}).has_discrepancies


# --- A023 / A123 -------------------------------------------------------------------------


def test_normalise_keeps_intraday_time() -> None:
    raw = pd.DataFrame(
        {"datetime": ["2024-01-10 09:30:00", "2024-01-10 09:35:00", "2024-01-11"], "Close": [1.0, 2.0, 3.0]}
    )
    stamps = normalise_ohlcv(raw, source="td", symbol="X", currency="USD")["date"].tolist()
    assert len(set(stamps)) == 3
    assert stamps[0] == pd.Timestamp("2024-01-10 09:30:00", tz="UTC")
    daily = normalise_ohlcv(pd.DataFrame({"Date": ["2024-01-10"], "Close": [1.0]}), source="s", symbol="X")
    assert daily["date"].iloc[0].isoformat() == "2024-01-10"


def test_normalise_blocks_mixed_currency_and_identity() -> None:
    frame = pd.DataFrame({"Date": ["2024-01-10", "2024-01-11"], "Close": [1.0, 2.0], "Currency": ["USD", "EUR"]})
    with pytest.raises(OhlcvNormalisationError, match="currency"):
        normalise_ohlcv(frame, source="s", symbol="X")
    ids = pd.DataFrame({"Date": ["2024-01-10", "2024-01-11"], "Close": [1.0, 2.0], "ticker": ["AAA", "BBB"]})
    with pytest.raises(OhlcvNormalisationError, match="provider_symbol"):
        normalise_ohlcv(ids, source="s")
    clash = pd.DataFrame({"Date": ["2024-01-10"], "Close": [1.0], "Currency": ["EUR"]})
    with pytest.raises(OhlcvNormalisationError, match="currency"):
        normalise_ohlcv(clash, source="s", symbol="X", currency="USD")
    assert normalise_ohlcv(clash, source="s", symbol="X", currency="eur")["currency"].tolist() == ["EUR"]


def test_normalise_parses_string_flags_and_marks_unknown() -> None:
    frame = pd.DataFrame(
        {"Date": ["2024-01-10", "2024-01-11", "2024-01-12"], "Close": [1.0, 2.0, 3.0], "is_adjusted": ["False", "true", "0"]}
    )
    assert normalise_ohlcv(frame, source="s", symbol="X")["is_adjusted"].tolist() == [False, True, False]
    unknown = frame.assign(is_adjusted=["False", float("nan"), "maybe"])
    flags = normalise_ohlcv(unknown, source="s", symbol="X")["is_adjusted"]
    assert flags.iloc[0] is False or flags.iloc[0] == False  # noqa: E712
    assert pd.isna(flags.iloc[1]) and pd.isna(flags.iloc[2])


def test_infinity_counts_as_discrepancy_even_when_both_providers_agree() -> None:
    both_inf = pd.DataFrame({"Date": ["2024-01-10"], "Close": [float("inf")], "Volume": [1000.0]})
    report = build_discrepancy_report(both_inf, both_inf, symbol="X", primary_name="a", secondary_name="b")
    assert [row.field for row in report.discrepancies] == ["close"]
    assert report.quality_cap < 1.0


def test_duplicate_dates_collapse_or_block_never_overwrite() -> None:
    same = pd.DataFrame({"Date": ["2024-01-10", "2024-01-10"], "Close": [1.0, 1.0]})
    assert len(normalise_ohlcv(same, source="s", symbol="X")) == 1
    conflicting = pd.DataFrame({"Date": ["2024-01-10", "2024-01-10"], "Close": [1.0, 9.0]})
    with pytest.raises(OhlcvNormalisationError, match="same timestamp"):
        normalise_ohlcv(conflicting, source="s", symbol="X")
    with pytest.raises(OhlcvNormalisationError):
        build_discrepancy_report(conflicting, same, symbol="X")


def test_alias_collision_is_a_controlled_error_unless_values_agree() -> None:
    agree = pd.DataFrame({"Date": ["2024-01-10"], "datetime": ["2024-01-10"], "Close": [1.0]})
    assert len(normalise_ohlcv(agree, source="s", symbol="X")) == 1
    clash = pd.DataFrame({"Date": ["2024-01-10"], "datetime": ["2024-01-11"], "Close": [1.0]})
    with pytest.raises(OhlcvNormalisationError, match="date"):
        normalise_ohlcv(clash, source="s", symbol="X")


def test_missing_field_counterpart_per_bar_is_reported() -> None:
    primary = pd.DataFrame({"Date": ["2024-01-10", "2024-01-11"], "Close": [1.0, 2.0], "Volume": [100.0, float("nan")]})
    secondary = pd.DataFrame({"Date": ["2024-01-10", "2024-01-11"], "Close": [1.0, 2.0], "Volume": [100.0, 100.0]})
    report = build_discrepancy_report(primary, secondary, symbol="X", primary_name="a", secondary_name="b")
    rows = [row for row in report.discrepancies if row.field == "missing_field"]
    assert len(rows) == 1 and rows[0].date.isoformat() == "2024-01-11"


# --- D010-N003 -------------------------------------------------------------------------


def test_exact_total_loss_is_representable(tmp_path: Path) -> None:
    sequence = apply_total_return_adjustments(prices=(100.0, 0.0), actions=())
    assert sequence.status == "available"
    assert sequence.total_return == pytest.approx(-1.0)
    assert sequence.price_return == pytest.approx(-1.0)

    frame = apply_total_return_adjustments(_prices(["2024-01-10", "2024-01-11"], [100.0, 0.0]), ())
    assert frame.status == "available"
    assert frame.total_return == pytest.approx(-1.0)
    assert not math.isnan(float(frame.frame["adjusted_close"].iloc[-1]))

    with FXObservationStore(tmp_path) as store:
        for day, rate in (("2024-01-10", 1.1), ("2024-01-11", 1.2)):
            store.append(
                FXObservation(
                    observation_id=f"FX-{day}",
                    base_currency="USD",
                    quote_currency="EUR",
                    rate=Decimal(str(rate)),
                    valid_at=f"{day}T00:00:00Z",
                    published_at=f"{day}T00:00:00Z",
                    retrieved_at=f"{day}T00:00:00Z",
                    known_at=f"{day}T00:00:00Z",
                    revision=1,
                    source="fixture:ecb",
                    source_id=f"fixture:ecb:{day}",
                    source_checksum=f"sha256:{day}",
                )
            )
        loss = selected_currency_return(
            -1.0,
            transaction_at="2024-01-10T00:00:00Z",
            valuation_at="2024-01-11T00:00:00Z",
            base_currency="USD",
            output_currency="EUR",
            fx_store=store,
        )
    assert loss.status == "available" and loss.output_return == pytest.approx(-1.0)
    with pytest.raises(MarketAdjustmentError):
        selected_currency_return(-1.5)

    with pytest.raises(MarketAdjustmentError):
        apply_total_return_adjustments(prices=(100.0, 0.0, 50.0), actions=())
    with pytest.raises(MarketAdjustmentError):
        apply_total_return_adjustments(_prices(["2024-01-10", "2024-01-11", "2024-01-12"], [100.0, 0.0, 50.0]), ())


def test_total_loss_with_final_day_cash_distribution_is_not_zeroed() -> None:
    dividend = _action("DIV-LOSS", "dividend", amount=1.0)
    result = apply_total_return_adjustments(_prices(["2024-01-10", "2024-01-11"], [100.0, 0.0]), (dividend,))
    assert result.status == "available"
    adjusted = result.frame["adjusted_close"].tolist()
    assert adjusted == pytest.approx([100.0, 1.0])
    assert any(value > 0.0 for value in adjusted)


# --- A010-N005 / A010-N004 / A010-N003 (correction pass 1) -----------------------------


def _series_projection(tmp_path: Path, prices: pd.DataFrame, *, basis: str, actions: tuple[CorporateAction, ...] = (), local_currency: str = "USD") -> dict[str, object]:
    seeded = tmp_path / "seeded.marker"
    if not seeded.exists():
        _seed_evidence(tmp_path, actions)
        seeded.write_text("1", encoding="utf-8")
    return market_views._load_market_series_projection(
        prices.assign(etf_id=ASSET),
        ASSET,
        basis=basis,
        local_currency=local_currency,
        storage_root=tmp_path,
        decision_time="2024-03-01T00:00:00Z",
    )


def _seed_evidence(tmp_path: Path, actions: tuple[CorporateAction, ...]) -> None:
    with CorporateActionStore(tmp_path) as store:
        for action in actions:
            store.append(action)
    with CorporateActionCoverageStore(tmp_path) as store:
        store.append(
            CorporateActionCoverage(
                instrument_id=ASSET,
                coverage_through="2024-02-01T00:00:00Z",
                published_at="2024-02-02T00:00:00Z",
                retrieved_at="2024-02-02T00:00:00Z",
                known_at="2024-02-02T00:00:00Z",
                revision=1,
                source="provider:a",
                source_id="provider:a:coverage",
                source_checksum="sha256:coverage",
            )
        )


def test_raw_basis_survives_action_conflict_but_adjusted_bases_do_not(tmp_path: Path) -> None:
    conflict = (
        _action("SPLIT-A", "split", ratio=2.0, source="provider:a"),
        _action("SPLIT-B", "split", ratio=4.0, source="provider:b"),
    )
    prices = _prices(SPLIT_DATES, SPLIT_CLOSES)

    raw = _series_projection(tmp_path, prices, basis="raw", actions=conflict)
    assert raw["status"] == "available" and raw["basis"] == "raw"
    assert raw["frame"]["series_value"].tolist() == SPLIT_CLOSES
    for basis in ("adjusted", "total_return"):
        blocked = _series_projection(tmp_path, prices, basis=basis)
        assert blocked["status"] != "available"
        assert blocked["reason_code"] == "corporate_action_discrepancy"


def test_raw_fallback_refuses_duplicate_candle_conflict_and_mixed_currency(tmp_path: Path) -> None:
    conflict = (
        _action("SPLIT-A", "split", ratio=2.0, source="provider:a"),
        _action("SPLIT-B", "split", ratio=4.0, source="provider:b"),
    )
    duplicate = _prices(["2024-01-10", "2024-01-11", "2024-01-11", "2024-01-12"], [100.0, 50.0, 52.0, 52.0])
    result = _series_projection(tmp_path, duplicate, basis="raw", actions=conflict)
    assert result["status"] != "available" and result["reason_code"] == "corporate_action_discrepancy"

    mixed = _prices(SPLIT_DATES, SPLIT_CLOSES, currency=["USD", "USD", "USD", "EUR", "EUR", "EUR"])
    result = _series_projection(tmp_path, mixed, basis="raw", actions=conflict)
    assert result["status"] != "available" and result["reason_code"] == "corporate_action_discrepancy"


def test_same_known_at_duplicate_close_conflict_is_quarantined() -> None:
    dates = ["2024-01-10", "2024-01-11", "2024-01-11"]
    stamps = ["2024-01-10T18:00:00Z", "2024-01-11T18:00:00Z", "2024-01-11T18:00:00Z"]
    result = apply_total_return_adjustments(_prices(dates, [50.0, 50.0, 52.0], known_at=stamps), ())

    assert result.status == "quarantined"
    assert "conflicting_duplicate_candle:2024-01-11" in result.warnings
    assert result.frame["price_return_index"].isna().all()
    # A later revision stamp is still a legitimate revision, and missing stamps group together.
    revised = apply_total_return_adjustments(_prices(dates, [50.0, 50.0, 52.0], known_at=[stamps[0], stamps[1], "2024-01-12T18:00:00Z"]), ())
    assert revised.status == "available" and len(revised.frame) == 3
    missing = apply_total_return_adjustments(_prices(dates, [50.0, 50.0, 52.0], known_at=[None, None, None]), ())
    assert missing.status == "quarantined"


def test_series_projection_passes_local_currency_to_the_cash_action_check(tmp_path: Path) -> None:
    dividend = _action("DIV-EUR", "dividend", amount=1.0, currency="EUR")
    result = _series_projection(tmp_path, _prices(SPLIT_DATES, [100.0, 100.0, 99.0, 99.0, 99.0, 99.0]), basis="total_return", actions=(dividend,))
    assert result["status"] != "available"
    assert result["reason_code"] == "corporate_action_discrepancy"

    unknown = _series_projection(tmp_path, _prices(SPLIT_DATES, [100.0, 100.0, 99.0, 99.0, 99.0, 99.0]), basis="total_return", local_currency="")
    assert unknown["status"] == "unavailable" and unknown["reason_code"] == "price_currency_unavailable"


def test_same_key_duplicate_rows_with_different_dividend_or_nav_quarantine() -> None:
    dates = pd.bdate_range("2026-01-01", periods=3)
    base = pd.DataFrame({"date": [*dates, dates[-1]], "close": [100.0, 101.0, 102.0, 102.0], "nav": [99.0, 100.0, 101.0, 101.0], "dividend": 0.0})
    assert apply_total_return_adjustments(base).status != "quarantined"  # exact duplicate collapses
    for column, value in (("dividend", 0.5), ("nav", 100.0)):
        changed = base.copy()
        changed.loc[3, column] = value
        result = apply_total_return_adjustments(changed)
        assert result.status == "quarantined"
        assert any(w.startswith("conflicting_duplicate_candle:") for w in result.warnings)


def test_conflicting_provider_rows_make_only_that_instrument_unavailable() -> None:
    good = [{"date": "2024-01-09", "close": 1.0}, {"date": "2024-01-10", "close": 1.5}]
    bad = [{"date": "2024-01-10", "close": 1.0}, {"date": "2024-01-10", "close": 9.0}]

    def transport(url: str, _headers: dict[str, str]) -> list[dict[str, object]]:
        return bad if "/BAD/" in url else good

    provider = TiingoProvider(section=ProviderSection(active_provider="tiingo", api_key="k"), transport=transport)
    assert provider.fetch_daily_prices("BAD", date(2024, 1, 1), date(2024, 1, 31)).empty
    result = provider.fetch_prices(["BAD", "GOOD"], date(2024, 1, 1), date(2024, 1, 31))
    assert result.data is not None and set(result.data["provider_symbol"]) == {"GOOD"}
    assert result.status == "unavailable" and "BAD: conflicting rows for the same timestamp" in result.message
